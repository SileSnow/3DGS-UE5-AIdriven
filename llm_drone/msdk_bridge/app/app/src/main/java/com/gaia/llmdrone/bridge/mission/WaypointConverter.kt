package com.gaia.llmdrone.bridge.mission

import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlin.math.min

/**
 * Mission JSON（llm_drone.mission/v1）-> DJI KMZ（WPML）构建。
 *
 * 本文件已按 docs/research/10（KMZ/WPML 规范，2026-11-08）与参考生成器
 * docs/research/assets/make_sample_kmz.py 逐字段重构（T9 复核修正）。
 * 结构：
 * - wpmz/template.kml：author/createTime/updateTime + missionConfig（flyToWaylineMode/finishAction/
 *   exitOnRCLost/executeRCLostAction/takeOffSecurityHeight/globalTransitionalSpeed/droneInfo/payloadInfo）
 *   + Folder（templateType/templateId/waylineCoordinateSysParam/autoFlightSpeed/gimbalPitchMode/
 *   globalWaypointHeadingParam/globalWaypointTurnMode/globalUseStraightLine）+ Placemark（index/height/
 *   ellipsoidHeight/useGlobal*/waypointSpeed/gimbalPitchAngle/actionGroup）
 * - wpmz/waylines.wpml：missionConfig + Folder（templateId/executeHeightMode/waylineId/autoFlightSpeed）
 *   + Placemark（index/executeHeight/waypointSpeed/waypointHeadingParam/waypointTurnParam/useStraightLine/actionGroup）
 * - actionGroup：gimbalRotate（含 gimbalRotateTimeEnable/gimbalRotateTime/payloadPositionIndex）+ takePhoto
 *   （fileSuffix/payloadPositionIndex）/ startRecord / stopRecord。
 *
 * 官方依据：
 * - WPML overview / template-kml / waylines-wpml / common-element：
 *   https://developer.dji.com/doc/cloud-api-tutorial/en/api-reference/dji-wpml/overview.html
 * - MSDK 侧 KMZ 上传/执行：https://developer.dji.com/doc/mobile-sdk-tutorial/en/tutorials/waypoint.html
 *
 * !!! 仍未真机验证 !!!
 * 1) droneEnumValue/payloadEnumValue 对 Mini 4 Pro 的官方取值未知（10 §12 TODO）→ 占位 0；
 * 2) waypointHeadingMode 当前统一 followWayline，mission JSON 的 per-waypoint heading_deg 未落地（TODO）；
 * 3) photo_interval_s 未用 multipleTiming（Mini 支持性未知，10 §4），采用每航点 reachPoint+takePhoto；
 * 4) 生成后必须按 10 §13 的 12 项清单静态校验（Python ElementTree + IWPMZManager.checkValidation），
 *    再经 test_protocol.md T0/T3 真机小航线验证。
 */
object WaypointConverter {

    private const val TAG = "WaypointConverter"
    private const val TAKE_OFF_SECURITY_HEIGHT_M = 20.0
    private const val XML_HEAD = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
    private const val NS = "xmlns=\"http://www.opengis.net/kml/2.2\" xmlns:wpml=\"http://www.dji.com/wpmz/1.0.2\""

    fun buildKmz(mission: JSONObject, outFile: File): Result<File> = try {
        val waypoints = mission.optJSONArray("waypoints")
            ?: return Result.failure(IllegalArgumentException("mission.waypoints 缺失"))
        val flight = mission.optJSONObject("flight") ?: JSONObject()
        val speed = flight.optDouble("speed_mps", 5.0).coerceIn(1.0, 15.0)
        val gimbalPitch = flight.optDouble("gimbal_pitch_deg", -45.0).coerceIn(-90.0, 35.0)
        val takeoffAlt = waypoints.optJSONObject(0)?.optDouble("alt_rel_m", 40.0) ?: 40.0
        val securityHeight = min(TAKE_OFF_SECURITY_HEIGHT_M, maxOf(takeoffAlt, 1.0))

        val template = buildTemplateKml(waypoints, speed, gimbalPitch, securityHeight)
        val waylines = buildWaylinesWpml(waypoints, speed, gimbalPitch, securityHeight)
        FileOutputStream(outFile).use { fos ->
            ZipOutputStream(fos).use { zip ->
                zip.putNextEntry(ZipEntry("wpmz/")); zip.closeEntry()
                zip.putNextEntry(ZipEntry("wpmz/template.kml"))
                zip.write(template.toByteArray(Charsets.UTF_8)); zip.closeEntry()
                zip.putNextEntry(ZipEntry("wpmz/waylines.wpml"))
                zip.write(waylines.toByteArray(Charsets.UTF_8)); zip.closeEntry()
            }
        }
        Log.i(TAG, "KMZ written: " + outFile.absolutePath + " size=" + outFile.length())
        Result.success(outFile)
    } catch (t: Throwable) {
        Log.e(TAG, "buildKmz failed: " + t.message)
        Result.failure(t)
    }

    private fun missionConfig(securityHeight: Double, speed: Double): String {
        val sb = StringBuilder()
        sb.append("  <wpml:missionConfig>\n")
        sb.append("    <wpml:flyToWaylineMode>safely</wpml:flyToWaylineMode>\n")
        sb.append("    <wpml:finishAction>goHome</wpml:finishAction>\n")
        sb.append("    <wpml:exitOnRCLost>goContinue</wpml:exitOnRCLost>\n")
        sb.append("    <wpml:executeRCLostAction>hover</wpml:executeRCLostAction>\n")
        sb.append("    <wpml:takeOffSecurityHeight>").append(fmt(securityHeight)).append("</wpml:takeOffSecurityHeight>\n")
        sb.append("    <wpml:globalTransitionalSpeed>").append(fmt(speed)).append("</wpml:globalTransitionalSpeed>\n")
        sb.append("    <wpml:droneInfo>\n")
        sb.append("      <!-- TODO(未确认)：Mini 4 Pro 的 droneEnumValue 官方未列，0 为占位（10 §12） -->\n")
        sb.append("      <wpml:droneEnumValue>0</wpml:droneEnumValue>\n")
        sb.append("      <wpml:droneSubEnumValue>0</wpml:droneSubEnumValue>\n")
        sb.append("    </wpml:droneInfo>\n")
        sb.append("    <wpml:payloadInfo>\n")
        sb.append("      <wpml:payloadEnumValue>0</wpml:payloadEnumValue>\n")
        sb.append("      <wpml:payloadPositionIndex>0</wpml:payloadPositionIndex>\n")
        sb.append("    </wpml:payloadInfo>\n")
        sb.append("  </wpml:missionConfig>\n")
        return sb.toString()
    }

    private fun buildTemplateKml(waypoints: JSONArray, speed: Double, gimbalPitch: Double, securityHeight: Double): String {
        val sb = StringBuilder(XML_HEAD)
        sb.append("<kml ").append(NS).append(">\n  <Document>\n")
        sb.append("    <wpml:author>llm-drone-bridge</wpml:author>\n")
        sb.append("    <wpml:createTime>").append(System.currentTimeMillis()).append("</wpml:createTime>\n")
        sb.append("    <wpml:updateTime>").append(System.currentTimeMillis()).append("</wpml:updateTime>\n")
        sb.append(missionConfig(securityHeight, speed))
        sb.append("  <Folder>\n    <wpml:templateType>waypoint</wpml:templateType>\n")
        sb.append("    <wpml:templateId>0</wpml:templateId>\n")
        sb.append("    <wpml:waylineCoordinateSysParam>\n")
        sb.append("      <wpml:coordinateMode>WGS84</wpml:coordinateMode>\n")
        sb.append("      <wpml:heightMode>relativeToStartPoint</wpml:heightMode>\n")
        sb.append("      <wpml:positioningType>GPS</wpml:positioningType>\n")
        sb.append("    </wpml:waylineCoordinateSysParam>\n")
        sb.append("    <wpml:autoFlightSpeed>").append(fmt(speed)).append("</wpml:autoFlightSpeed>\n")
        sb.append("    <wpml:gimbalPitchMode>usePointSetting</wpml:gimbalPitchMode>\n")
        sb.append("    <wpml:globalWaypointHeadingParam>\n")
        sb.append("      <wpml:waypointHeadingMode>followWayline</wpml:waypointHeadingMode>\n")
        sb.append("    </wpml:globalWaypointHeadingParam>\n")
        sb.append("    <wpml:globalWaypointTurnMode>toPointAndStopWithDiscontinuityCurvature</wpml:globalWaypointTurnMode>\n")
        sb.append("    <wpml:globalUseStraightLine>0</wpml:globalUseStraightLine>\n")
        for (i in 0 until waypoints.length()) {
            val wp = waypoints.getJSONObject(i)
            val lat = wp.optDouble("lat")
            val lon = wp.optDouble("lon")
            val alt = wp.optDouble("alt_rel_m", 40.0)
            val wpSpeed = wp.optDouble("speed_mps", speed).coerceIn(1.0, 15.0)
            val pitch = wp.optDouble("gimbal_pitch_deg", gimbalPitch).coerceIn(-90.0, 35.0)
            sb.append("    <Placemark>\n      <Point>\n")
            sb.append("        <coordinates>").append(fmtCoord(lon)).append(",").append(fmtCoord(lat)).append("</coordinates>\n")
            sb.append("      </Point>\n")
            sb.append("      <wpml:index>").append(i).append("</wpml:index>\n")
            sb.append("      <wpml:ellipsoidHeight>").append(fmt(alt)).append("</wpml:ellipsoidHeight>\n")
            sb.append("      <wpml:height>").append(fmt(alt)).append("</wpml:height>\n")
            sb.append("      <wpml:useGlobalHeight>0</wpml:useGlobalHeight>\n")
            sb.append("      <wpml:useGlobalSpeed>0</wpml:useGlobalSpeed>\n")
            sb.append("      <wpml:waypointSpeed>").append(fmt(wpSpeed)).append("</wpml:waypointSpeed>\n")
            sb.append("      <wpml:useGlobalHeadingParam>1</wpml:useGlobalHeadingParam>\n")
            sb.append("      <wpml:useGlobalTurnParam>1</wpml:useGlobalTurnParam>\n")
            sb.append("      <wpml:gimbalPitchAngle>").append(fmt(pitch)).append("</wpml:gimbalPitchAngle>\n")
            sb.append(actionGroup(i, wp, pitch))
            sb.append("    </Placemark>\n")
        }
        sb.append("  </Folder>\n  </Document>\n</kml>\n")
        return sb.toString()
    }

    private fun buildWaylinesWpml(waypoints: JSONArray, speed: Double, gimbalPitch: Double, securityHeight: Double): String {
        val sb = StringBuilder(XML_HEAD)
        sb.append("<kml ").append(NS).append(">\n  <Document>\n")
        sb.append(missionConfig(securityHeight, speed))
        sb.append("  <Folder>\n    <wpml:templateId>0</wpml:templateId>\n")
        sb.append("    <wpml:executeHeightMode>relativeToStartPoint</wpml:executeHeightMode>\n")
        sb.append("    <wpml:waylineId>0</wpml:waylineId>\n")
        sb.append("    <wpml:autoFlightSpeed>").append(fmt(speed)).append("</wpml:autoFlightSpeed>\n")
        for (i in 0 until waypoints.length()) {
            val wp = waypoints.getJSONObject(i)
            val lat = wp.optDouble("lat")
            val lon = wp.optDouble("lon")
            val alt = wp.optDouble("alt_rel_m", 40.0)
            val wpSpeed = wp.optDouble("speed_mps", speed).coerceIn(1.0, 15.0)
            val pitch = wp.optDouble("gimbal_pitch_deg", gimbalPitch).coerceIn(-90.0, 35.0)
            sb.append("    <Placemark>\n      <Point>\n")
            sb.append("        <coordinates>").append(fmtCoord(lon)).append(",").append(fmtCoord(lat)).append("</coordinates>\n")
            sb.append("      </Point>\n")
            sb.append("      <wpml:index>").append(i).append("</wpml:index>\n")
            sb.append("      <wpml:executeHeight>").append(fmt(alt)).append("</wpml:executeHeight>\n")
            sb.append("      <wpml:waypointSpeed>").append(fmt(wpSpeed)).append("</wpml:waypointSpeed>\n")
            sb.append("      <wpml:waypointHeadingParam>\n        <wpml:waypointHeadingMode>followWayline</wpml:waypointHeadingMode>\n      </wpml:waypointHeadingParam>\n")
            sb.append("      <wpml:waypointTurnParam>\n")
            sb.append("        <wpml:waypointTurnMode>toPointAndStopWithDiscontinuityCurvature</wpml:waypointTurnMode>\n")
            sb.append("        <wpml:waypointTurnDampingDist>0</wpml:waypointTurnDampingDist>\n")
            sb.append("      </wpml:waypointTurnParam>\n")
            sb.append("      <wpml:useStraightLine>0</wpml:useStraightLine>\n")
            sb.append(actionGroup(i, wp, pitch))
            sb.append("    </Placemark>\n")
        }
        sb.append("  </Folder>\n  </Document>\n</kml>\n")
        return sb.toString()
    }

    /** actionGroup：gimbalRotate（绝对角） -> takePhoto / startRecord / stopRecord（10 §4） */
    private fun actionGroup(groupId: Int, wp: JSONObject, pitch: Double): String {
        val action = wp.optString("action", "none")
        val sb = StringBuilder()
        sb.append("      <wpml:actionGroup>\n")
        sb.append("        <wpml:actionGroupId>").append(groupId).append("</wpml:actionGroupId>\n")
        sb.append("        <wpml:actionGroupStartIndex>").append(groupId).append("</wpml:actionGroupStartIndex>\n")
        sb.append("        <wpml:actionGroupEndIndex>").append(groupId).append("</wpml:actionGroupEndIndex>\n")
        sb.append("        <wpml:actionGroupMode>sequence</wpml:actionGroupMode>\n")
        sb.append("        <wpml:actionTrigger>\n          <wpml:actionTriggerType>reachPoint</wpml:actionTriggerType>\n        </wpml:actionTrigger>\n")
        sb.append("        <wpml:action>\n          <wpml:actionId>0</wpml:actionId>\n")
        sb.append("          <wpml:actionActuatorFunc>gimbalRotate</wpml:actionActuatorFunc>\n")
        sb.append("          <wpml:actionActuatorFuncParam>\n")
        sb.append("            <wpml:gimbalRotateMode>absoluteAngle</wpml:gimbalRotateMode>\n")
        sb.append("            <wpml:gimbalPitchRotateEnable>1</wpml:gimbalPitchRotateEnable>\n")
        sb.append("            <wpml:gimbalPitchRotateAngle>").append(fmt(pitch)).append("</wpml:gimbalPitchRotateAngle>\n")
        sb.append("            <wpml:gimbalRollRotateEnable>0</wpml:gimbalRollRotateEnable>\n")
        sb.append("            <wpml:gimbalRollRotateAngle>0</wpml:gimbalRollRotateAngle>\n")
        sb.append("            <wpml:gimbalYawRotateEnable>0</wpml:gimbalYawRotateEnable>\n")
        sb.append("            <wpml:gimbalYawRotateAngle>0</wpml:gimbalYawRotateAngle>\n")
        sb.append("            <wpml:gimbalRotateTimeEnable>0</wpml:gimbalRotateTimeEnable>\n")
        sb.append("            <wpml:gimbalRotateTime>0</wpml:gimbalRotateTime>\n")
        sb.append("            <wpml:payloadPositionIndex>0</wpml:payloadPositionIndex>\n")
        sb.append("          </wpml:actionActuatorFuncParam>\n        </wpml:action>\n")
        val actFunc = when (action) {
            "photo" -> "takePhoto"
            "video_start" -> "startRecord"
            "video_stop" -> "stopRecord"
            else -> null
        }
        if (actFunc != null) {
            sb.append("        <wpml:action>\n          <wpml:actionId>1</wpml:actionId>\n")
            sb.append("          <wpml:actionActuatorFunc>").append(actFunc).append("</wpml:actionActuatorFunc>\n")
            sb.append("          <wpml:actionActuatorFuncParam>\n")
            if (actFunc == "takePhoto") {
                sb.append("            <wpml:fileSuffix>wp").append(String.format("%02d", groupId)).append("</wpml:fileSuffix>\n")
            }
            sb.append("            <wpml:payloadPositionIndex>0</wpml:payloadPositionIndex>\n")
            sb.append("          </wpml:actionActuatorFuncParam>\n        </wpml:action>\n")
        }
        sb.append("      </wpml:actionGroup>\n")
        return sb.toString()
    }

    private fun fmt(v: Double): String =
        if (v == Math.floor(v)) v.toInt().toString() else String.format("%.1f", v)

    private fun fmtCoord(v: Double): String = String.format("%.8f", v)
}
