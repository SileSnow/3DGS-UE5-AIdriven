package com.gaia.llmdrone.bridge.mission

import android.util.Log
import com.gaia.llmdrone.bridge.bridge.BridgeRuntime
import com.gaia.llmdrone.bridge.bridge.MissionRecord
import com.gaia.llmdrone.bridge.bridge.MissionStore
import com.gaia.llmdrone.bridge.bridge.PhotoRecord
import com.gaia.llmdrone.bridge.media.MediaDownloader
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject
import java.io.File
import java.time.OffsetDateTime
import kotlin.math.cos
import kotlin.math.sin

/**
 * goto_waypoints 的总编排：Mission JSON -> KMZ -> 上传 -> 执行 -> 监控 -> 照片对账 -> 任务记录。
 *
 * 与 spec 的对应：
 * - PROTOCOL.md §4 goto_waypoints：args 中 mission 必须是已展开的 llm_drone.mission/v1 JSON；
 *   桥接层不解析 plan_id（plan_capture_mission / orbit 由 Orchestrator 展开）。
 * - PROTOCOL.md §6：按 waypoints 顺序 stop_and_turn；action=photo 的航点各拍 1 张。
 * - PROTOCOL.md §7.1：任务记录字段；§7.2：c2w 推算公式（本文件在 real 模式下用"计划航点位姿"推算，
 *   标注为 estimated，见 README 的"已验证/未验证边界"）。
 *
 * 未执行边界：未编译、未真机飞行。照片与航点动作的精确对应需真机日志校准（WaypointActionListener）。
 */
object MissionExecutor {

    private const val TAG = "MissionExecutor"
    private const val ORIGIN_LAT = 39.9042
    private const val ORIGIN_LON = 116.4074
    private const val ORIGIN_ALT = 43.0
    // spec v1.1 §15.2：real 无真值，估算位姿精度默认 3.0m（可配 1–10m）
    private const val POSE_ACCURACY_M = 3.0

    suspend fun execute(missionJson: JSONObject): MissionRecord {
        val missionId = missionJson.optString("mission_id", BridgeRuntime.nextMissionId())
        val planId = missionJson.optString("plan_id", null)
        val waypoints = missionJson.optJSONArray("waypoints")
            ?: throw IllegalArgumentException("mission.waypoints 缺失")
        val photoIndices = mutableListOf<Int>()
        for (i in 0 until waypoints.length()) {
            if (waypoints.getJSONObject(i).optString("action", "none") == "photo") photoIndices.add(i)
        }

        val record = MissionRecord(
            missionId = missionId,
            planId = planId,
            state = "pending",
            createdAt = BridgeRuntime.nowIso(),
            startedAt = null,
            endedAt = null,
            progressPct = 0.0,
            photos = mutableListOf(),
            error = null,
            nWaypoints = waypoints.length(),
            nPhotoPoints = photoIndices.size
        )
        MissionStore.put(record)
        BridgeRuntime.currentMissionId = missionId
        BridgeRuntime.missionActive = true

        try {
            // 1) 生成 KMZ（缓存目录）
            val ctx = BridgeRuntime.appContext
            val dir = File(ctx.getExternalFilesDir(null), "kmz").apply { mkdirs() }
            val kmz = File(dir, missionId + ".kmz")
            val built = WaypointConverter.buildKmz(missionJson, kmz)
            if (built.isFailure) {
                record.state = "failed"
                record.error = com.gaia.llmdrone.bridge.bridge.ApiError(
                    "E_INTERNAL", "KMZ 构建失败: " + (built.exceptionOrNull()?.message ?: "unknown")
                )
                record.endedAt = BridgeRuntime.nowIso()
                return record
            }

            // 2) 上传（进度 0-30% 映射）
            val uploaded = WaypointMissionController.upload(kmz.absolutePath) { p ->
                record.progressPct = (p.coerceIn(0.0, 1.0) * 30.0)
            }
            if (uploaded.isFailure) {
                record.state = "failed"
                record.error = com.gaia.llmdrone.bridge.bridge.ApiError(
                    "E_INTERNAL", "KMZ 上传失败: " + (uploaded.exceptionOrNull()?.message ?: "unknown")
                )
                record.endedAt = BridgeRuntime.nowIso()
                return record
            }

            // 3) 启动任务并等待 FINISHED（超时 = 航点数 * 30s + 120s 缓冲；真实估算见 README）
            val timeoutMs = (waypoints.length() * 30_000L + 120_000L)
            record.startedAt = BridgeRuntime.nowIso()
            record.state = "executing"
            var accepted = false
            val outcome = WaypointMissionController.start(kmz.absolutePath) { ok -> accepted = ok }
            val result = withTimeoutOrNull(timeoutMs) { outcome.await() }
            if (result == null) {
                WaypointMissionController.stop()
                record.state = "failed"
                record.error = com.gaia.llmdrone.bridge.bridge.ApiError("E_STATE", "任务超时未完成")
            } else if (result != true || !accepted) {
                record.state = "failed"
                record.error = com.gaia.llmdrone.bridge.bridge.ApiError("E_STATE", "任务未成功完成")
            } else {
                record.state = "completed"
                record.progressPct = 100.0
            }
            record.endedAt = BridgeRuntime.nowIso()
        } catch (t: Throwable) {
            Log.e(TAG, "mission execution failed: " + t.message)
            record.state = "failed"
            record.error = com.gaia.llmdrone.bridge.bridge.ApiError(
                "E_INTERNAL", "任务执行异常: " + (t.message ?: "unknown")
            )
            record.endedAt = BridgeRuntime.nowIso()
        } finally {
            BridgeRuntime.missionActive = false
            BridgeRuntime.currentMissionId = null
        }

        // 4) 照片记录 + 媒体对账（不阻塞主流程失败：即使对账失败也返回已写记录）
        if (record.state == "completed") {
            fillPlannedPhotos(record, missionJson)
            reconcileWithMedia(record)
        }
        MissionStore.put(record)
        return record
    }

    /** 按计划航点生成照片记录（real 模式：位置/姿态来自计划航点；file 先占位，待媒体对账替换） */
    private fun fillPlannedPhotos(record: MissionRecord, missionJson: JSONObject) {
        val waypoints = missionJson.optJSONArray("waypoints") ?: return
        var photoIdx = 0
        for (i in 0 until waypoints.length()) {
            val wp = waypoints.getJSONObject(i)
            if (wp.optString("action", "none") != "photo") continue
            val lat = wp.optDouble("lat")
            val lon = wp.optDouble("lon")
            val altRel = wp.optDouble("alt_rel_m", 40.0)
            val heading = wp.optDouble("heading_deg", 0.0)
            val pitch = wp.optDouble("gimbal_pitch_deg", -45.0)
            record.photos.add(
                PhotoRecord(
                    index = photoIdx,
                    file = "PENDING_" + photoIdx,
                    ts = BridgeRuntime.nowIso(),
                    lat = lat,
                    lon = lon,
                    altRelM = altRel,
                    altAbsM = ORIGIN_ALT + altRel,
                    headingDeg = heading,
                    gimbalPitch = pitch,
                    gimbalYaw = 0.0,
                    gimbalRoll = 0.0,
                    c2w = estimateC2w(lat, lon, altRel, heading, pitch),
                    poseSource = "estimated",
                    poseAccuracyM = POSE_ACCURACY_M
                )
            )
            photoIdx++
        }
    }

    /** 用 MediaDataCenter 最近照片文件名按顺序回填（文件名对 3DGS 下载与 metadata 很关键） */
    private fun reconcileWithMedia(record: MissionRecord) {
        if (record.photos.isEmpty()) return
        val sinceMs = try {
            record.startedAt?.let { OffsetDateTime.parse(it).toInstant().toEpochMilli() }
                ?: System.currentTimeMillis()
        } catch (t: Throwable) {
            System.currentTimeMillis()
        }
        val files = MediaDownloader.listNewFilesSince(sinceMs)
        if (files.isEmpty()) {
            Log.w(TAG, "媒体列表无新照片，文件名保留 PENDING（真机阶段检查 MediaDataCenter 拉取时机）")
            return
        }
        record.photos.forEachIndexed { i, p ->
            if (i < files.size) {
                record.photos[i] = p.copy(file = files[i].fileName)
            }
        }
    }

    /**
     * PROTOCOL.md §7.2 的 c2w 推算（行主序，列 = [forward, right, up]，单位 cm）。
     * real 模式下这是"由计划航点/云台角推算"的估计值，不是真值；用于下游按位姿初始化 3DGS 时需按 README 说明标注。
     */
    private fun estimateC2w(
        lat: Double, lon: Double, altRelM: Double,
        headingDeg: Double, gimbalPitchDeg: Double
    ): List<Double> {
        val northM = (lat - ORIGIN_LAT) * 111320.0
        val eastM = (lon - ORIGIN_LON) * 111320.0 * cos(Math.toRadians(ORIGIN_LAT))
        val xCm = eastM * 100.0
        val yCm = -northM * 100.0
        val zCm = (ORIGIN_ALT + altRelM - ORIGIN_ALT) * 100.0

        val yaw = Math.toRadians(headingDeg - 90.0) // UE yaw = heading - 90
        val pitch = Math.toRadians(gimbalPitchDeg)
        val fx = cos(pitch) * cos(yaw); val fy = cos(pitch) * sin(yaw); val fz = sin(pitch)
        val rx = -sin(yaw); val ry = cos(yaw); val rz = 0.0
        val ux = -sin(pitch) * cos(yaw); val uy = -sin(pitch) * sin(yaw); val uz = cos(pitch)
        return listOf(
            fx, rx, ux, xCm,
            fy, ry, uy, yCm,
            fz, rz, uz, zCm,
            0.0, 0.0, 0.0, 1.0
        )
    }
}
