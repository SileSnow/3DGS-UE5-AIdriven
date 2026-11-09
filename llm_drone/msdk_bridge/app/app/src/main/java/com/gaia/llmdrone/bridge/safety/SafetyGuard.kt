package com.gaia.llmdrone.bridge.safety

import android.util.Log
import com.gaia.llmdrone.bridge.bridge.ApiError
import com.gaia.llmdrone.bridge.bridge.AuditLogger
import com.gaia.llmdrone.bridge.bridge.ErrorMapper
import com.gaia.llmdrone.bridge.bridge.BridgeRuntime
import com.gaia.llmdrone.bridge.bridge.TelemetrySnapshot
import com.gaia.llmdrone.bridge.msdk.AircraftConnectionManager
import com.gaia.llmdrone.bridge.msdk.MsdkInitManager
import org.json.JSONArray
import org.json.JSONObject

/**
 * 设备端 SafetyGuard（第二道安全门，权威）：Orchestrator 侧已有一道，但按 CONTRACT/PROTOCOL
 * "安全校验只认 Agent 侧结果"，桥接层必须完整实现。
 *
 * 校验顺序（PROTOCOL.md §4 固定）：
 * schema → whitelist → mode → confirm → state → battery → gps → rc → altitude/speed 范围 → geofence → no-fly zone → 返航能量估算 → 允许
 *
 * 与 Phase1 仿真的差异（Phase2 设备端附加项，写在 mode 之后、state 之前）：
 * - MSDK 已注册、产品/RC 已连接、机型在支持列表（Mini 4 Pro）→ 否则 E_RC_LINK / E_STATE
 *
 * 未执行边界：所有阈值/顺序与 spec 对齐，但未在真机运行；真机阶段要用 test_protocol.md 的对抗用例逐条复核。
 */
object SafetyGuard {

    private const val TAG = "SafetyGuard"

    data class Decision(val allow: Boolean, val error: ApiError? = null, val warnings: List<String> = emptyList())

    fun validate(tool: String, req: com.gaia.llmdrone.bridge.bridge.CommandRequest, tm: TelemetrySnapshot): Decision {
        // 1) schema：必须字段 + 类型 + 额外字段
        schemaError(tool, req.args)?.let { return deny(tool, req, it) }

        // 2) whitelist
        if (tool !in SafetyConfig.WHITELIST) {
            return deny(tool, req, ApiError("E_UNKNOWN_TOOL", "工具不在白名单: " + tool))
        }

        // 3) mode：dry_run 允许只读；real 正常执行；sim 不支持
        if (BridgeRuntime.mode == "sim") {
            return deny(tool, req, ApiError("E_NOT_SUPPORTED", "Phase2 桥接层不支持 sim 模式"))
        }
        if (BridgeRuntime.mode == "dry_run" && tool !in setOf("get_telemetry", "preflight_check", "get_mission_status")) {
            // dry_run：全部命令只做校验不执行（由 CommandExecutor 短路），这里仍放行以便返回"将会执行"的校验结论
            AuditLogger.append("safety_dry_run", JSONObject().apply {
                put("tool", tool); put("command_id", req.commandId)
            })
        }

        // 4) confirm
        if (tool in SafetyConfig.CONFIRM_REQUIRED_TOOLS && !req.confirm) {
            return deny(tool, req, ApiError("E_CONFIRM_REQUIRED", tool + " 需要 confirm=true"))
        }
        if (tool == "set_mode" && req.args.optString("mode") == "real" && !req.confirm) {
            return deny(tool, req, ApiError("E_CONFIRM_REQUIRED", "set_mode(real) 需要 confirm=true"))
        }

        // 4.5) Phase2 设备就绪（设备端附加检查）
        if (tool !in setOf("get_telemetry", "preflight_check", "set_mode", "get_mission_status")) {
            if (!MsdkInitManager.isRegistered) {
                return deny(tool, req, ErrorMapper.notRegistered("safety_guard"))
            }
            if (!AircraftConnectionManager.productConnected || !AircraftConnectionManager.rcConnected) {
                return deny(tool, req, ErrorMapper.notConnected("safety_guard"))
            }
            if (AircraftConnectionManager.modelName.isNotEmpty() && !AircraftConnectionManager.isModelSupported()) {
                return deny(tool, req, ErrorMapper.aircraftMismatch(AircraftConnectionManager.modelName))
            }
        }

        // 5) state
        stateError(tool, req, tm)?.let { return deny(tool, req, it) }

        // 6) battery / 7) gps / 8) rc：起飞类命令
        if (tool == "takeoff") {
            if (tm.batteryPct < SafetyConfig.MIN_BATTERY_TAKEOFF_PCT) {
                return deny(tool, req, ApiError("E_BATTERY_TAKEOFF",
                    "起飞电量不足: " + tm.batteryPct + "% < " + SafetyConfig.MIN_BATTERY_TAKEOFF_PCT + "%",
                    JSONObject().apply {
                        put("battery_pct", tm.batteryPct)
                        put("min_pct", SafetyConfig.MIN_BATTERY_TAKEOFF_PCT)
                    }))
            }
            if (tm.gpsFix < SafetyConfig.MIN_GPS_FIX || tm.gpsSatellites < SafetyConfig.MIN_GPS_SATELLITES) {
                return deny(tool, req, ApiError("E_GPS",
                    "GPS 质量不足: fix=" + tm.gpsFix + " sats=" + tm.gpsSatellites))
            }
            if (!tm.rcConnected) {
                return deny(tool, req, ErrorMapper.notConnected("telemetry_rc"))
            }
        }

        // 9) 高度/速度范围 + 10) geofence + 11) no-fly（对 takeoff / goto_waypoints）
        rangeError(tool, req.args)?.let { return deny(tool, req, it) }
        geofenceError(tool, req.args)?.let { return deny(tool, req, it) }
        noFlyError(tool, req.args)?.let { return deny(tool, req, it) }

        // 12) 返航能量估算（takeoff/goto_waypoints）
        rthEnergyError(tool, req.args, tm)?.let { return deny(tool, req, it) }

        AuditLogger.append("safety_check", JSONObject().apply {
            put("tool", tool); put("command_id", req.commandId); put("decision", "allow")
        })
        return Decision(true)
    }

    /**
     * preflight_check 的逐项结果（PROTOCOL.md §4：返回 {ok, can_fly, checks:[{name,pass,detail}]}）。
     * 注意：本方法只读，不改变任何飞行状态。
     */
    fun preflight(tm: TelemetrySnapshot): Pair<Boolean, JSONArray> {
        val checks = JSONArray()
        fun add(name: String, pass: Boolean, detail: String) {
            checks.put(JSONObject().apply { put("name", name); put("pass", pass); put("detail", detail) })
        }
        add("msdk_registered", MsdkInitManager.isRegistered, "MSDK registered=" + MsdkInitManager.isRegistered)
        add("product_connected", AircraftConnectionManager.productConnected, "product connected=" + AircraftConnectionManager.productConnected)
        add("rc_link", tm.rcConnected, "rc connected=" + tm.rcConnected)
        add("gps", tm.gpsFix >= SafetyConfig.MIN_GPS_FIX && tm.gpsSatellites >= SafetyConfig.MIN_GPS_SATELLITES,
            "fix=" + tm.gpsFix + " sats=" + tm.gpsSatellites)
        add("battery_takeoff", tm.batteryPct >= SafetyConfig.MIN_BATTERY_TAKEOFF_PCT,
            "battery=" + tm.batteryPct + "%")
        add("battery_rth", tm.batteryPct >= SafetyConfig.RTH_RESERVE_PCT,
            "battery=" + tm.batteryPct + "% reserve=" + SafetyConfig.RTH_RESERVE_PCT + "%")
        add("model_supported", AircraftConnectionManager.isModelSupported() || AircraftConnectionManager.modelName.isEmpty(),
            "model=" + AircraftConnectionManager.modelName)
        add("home_location", tm.homeLat != 0.0 || tm.homeLon != 0.0, "home=" + tm.homeLat + "," + tm.homeLon)
        val canFly = (0 until checks.length()).all { checks.getJSONObject(it).getBoolean("pass") }
        return Pair(canFly, checks)
    }

    fun deny(tool: String, req: com.gaia.llmdrone.bridge.bridge.CommandRequest, error: ApiError): Decision {
        AuditLogger.append("command_rejected", JSONObject().apply {
            put("tool", tool)
            put("command_id", req.commandId)
            put("error_code", error.code)
            put("reasons", JSONArray().put(error.message))
        })
        Log.w(TAG, "reject " + tool + ": " + error.code + " " + error.message)
        return Decision(false, error)
    }

    // ---------- 具体检查 ----------

    private fun schemaError(tool: String, args: JSONObject): ApiError? {
        val allowed = SafetyConfig.ALLOWED_ARGS[tool] ?: return ApiError("E_UNKNOWN_TOOL", "工具不在白名单: " + tool)
        val keys = args.keys()
        while (keys.hasNext()) {
            val k = keys.next()
            if (k !in allowed) {
                return ApiError("E_SCHEMA", "多余参数: " + k,
                    JSONObject().apply { put("tool", tool); put("arg", k) })
            }
        }
        fun requireNumber(name: String): ApiError? =
            if (!args.has(name) || !args.opt(name).let { it is Number }) {
                ApiError("E_SCHEMA", "缺少或类型错误: " + name)
            } else null
        fun requireString(name: String): ApiError? =
            if (!args.has(name) || args.isNull(name) || args.opt(name) !is String) {
                ApiError("E_SCHEMA", "缺少或类型错误: " + name)
            } else null

        return when (tool) {
            "takeoff" -> requireNumber("altitude_m")
            "goto_waypoints" -> {
                val hasMission = args.has("mission") && args.opt("mission") is JSONObject
                val hasWaypoints = args.has("waypoints") && args.opt("waypoints") is JSONArray
                if (!hasMission && !hasWaypoints) {
                    ApiError("E_SCHEMA", "goto_waypoints 需要已展开的 mission(对象) 或 waypoints(数组)；plan_id 必须由 Orchestrator 展开",
                        JSONObject().apply { put("has_plan_id", args.has("plan_id")) })
                } else null
            }
            "set_gimbal" -> requireNumber("pitch_deg")
            "capture_photo" -> null
            "abort" -> requireString("reason")
            "get_mission_status" -> null
            "set_mode" -> {
                val m = args.optString("mode", "")
                if (m !in setOf("dry_run", "sim", "real")) ApiError("E_SCHEMA", "mode 非法: " + m)
                else null
            }
            else -> null
        }
    }

    private fun stateError(
        tool: String, req: com.gaia.llmdrone.bridge.bridge.CommandRequest, tm: TelemetrySnapshot
    ): ApiError? {
        val flying = tm.state !in setOf("idle")
        val airborne = tm.state in setOf("hovering", "mission", "returning", "landing", "taking_off", "aborted", "failsafe")
        return when (tool) {
            "takeoff" -> if (flying) ApiError("E_STATE", "当前状态不允许起飞: " + tm.state) else null
            "land", "return_to_home" -> if (!airborne) ApiError("E_STATE", "空中动作需要已起飞: " + tm.state) else null
            "goto_waypoints" -> if (!airborne) ApiError("E_STATE", "航点任务需要已起飞: " + tm.state) else null
            "capture_photo", "start_video", "stop_video" -> if (!airborne) ApiError("E_NOT_AIRBORNE", "需要空中状态: " + tm.state) else null
            "set_gimbal" -> if (!airborne) ApiError("E_NOT_AIRBORNE", "需要空中状态: " + tm.state) else null
            "abort" -> null
            "set_mode" -> if (tm.state != "idle") ApiError("E_STATE", "切换模式需要 idle 状态: " + tm.state) else null
            "get_mission_status", "get_telemetry", "preflight_check" -> null
            else -> null
        }
    }

    private fun rangeError(tool: String, args: JSONObject): ApiError? {
        if (tool == "takeoff") {
            val alt = args.optDouble("altitude_m", -1.0)
            if (alt <= 0.0 || alt > SafetyConfig.MAX_REL_ALTITUDE_M) {
                return ApiError("E_ALT_LIMIT", "altitude_m 超出范围(0," + SafetyConfig.MAX_REL_ALTITUDE_M + "]: " + alt,
                    JSONObject().apply { put("altitude_m", alt); put("max_m", SafetyConfig.MAX_REL_ALTITUDE_M) })
            }
        }
        if (tool == "goto_waypoints") {
            val speed = args.optDouble("speed_mps", 5.0)
            if (speed <= 0.0 || speed > SafetyConfig.MAX_SPEED_MPS) {
                return ApiError("E_SPEED_LIMIT", "speed_mps 超限(0," + SafetyConfig.MAX_SPEED_MPS + "]: " + speed)
            }
            val waypoints = extractWaypoints(args) ?: return null
            for (i in 0 until waypoints.length()) {
                val wp = waypoints.getJSONObject(i)
                val alt = wp.optDouble("alt_rel_m", -1.0)
                if (alt <= 0.0 || alt > SafetyConfig.MAX_REL_ALTITUDE_M) {
                    return ApiError("E_ALT_LIMIT", "航点 " + i + " alt_rel_m 超限: " + alt)
                }
                val sp = wp.optDouble("speed_mps", speed)
                if (sp <= 0.0 || sp > SafetyConfig.MAX_SPEED_MPS) {
                    return ApiError("E_SPEED_LIMIT", "航点 " + i + " speed_mps 超限: " + sp)
                }
            }
        }
        if (tool == "set_gimbal") {
            val pitch = args.optDouble("pitch_deg", 999.0)
            if (pitch < -90.0 || pitch > 0.0) {
                return ApiError("E_PARAM_RANGE", "pitch_deg 超出 [-90,0]: " + pitch)
            }
            if (args.has("yaw_deg")) {
                val yaw = args.optDouble("yaw_deg", 999.0)
                if (yaw < -180.0 || yaw > 180.0) {
                    return ApiError("E_PARAM_RANGE", "yaw_deg 超出 [-180,180]: " + yaw)
                }
            }
        }
        if (tool == "capture_photo") {
            val count = args.optDouble("count", 1.0)
            if (count < 1 || count > 20) return ApiError("E_PARAM_RANGE", "count 超出 [1,20]: " + count)
            val interval = args.optDouble("interval_s", 1.0)
            if (interval < 0 || interval > 10) return ApiError("E_PARAM_RANGE", "interval_s 超出 [0,10]: " + interval)
        }
        return null
    }

    private fun geofenceError(tool: String, args: JSONObject): ApiError? {
        if (tool == "takeoff") return null // 起飞点即当前点，围栏在 preflight 已覆盖作业场地
        if (tool != "goto_waypoints") return null
        val waypoints = extractWaypoints(args) ?: return null
        for (i in 0 until waypoints.length()) {
            val wp = waypoints.getJSONObject(i)
            val lat = wp.optDouble("lat", 0.0)
            val lon = wp.optDouble("lon", 0.0)
            if (!GeoFence.insideCircle(lat, lon, SafetyConfig.GEOFENCE_CENTER_LAT,
                    SafetyConfig.GEOFENCE_CENTER_LON, SafetyConfig.GEOFENCE_RADIUS_M)) {
                return ApiError("E_GEOFENCE", "航点 " + i + " 超出地理围栏(" +
                    SafetyConfig.GEOFENCE_RADIUS_M + "m): " + lat + "," + lon)
            }
        }
        return null
    }

    private fun noFlyError(tool: String, args: JSONObject): ApiError? {
        if (tool != "goto_waypoints") return null
        val waypoints = extractWaypoints(args) ?: return null
        for (i in 0 until waypoints.length()) {
            val wp = waypoints.getJSONObject(i)
            val lat = wp.optDouble("lat", 0.0)
            val lon = wp.optDouble("lon", 0.0)
            if (GeoFence.insidePolygon(lat, lon, SafetyConfig.DEFAULT_NO_FLY_POLYGON)) {
                return ApiError("E_NOFLY", "航点 " + i + " 位于禁飞区: " + lat + "," + lon)
            }
        }
        return null
    }

    /** 简化能量估算：返航距离 * 1.2 安全系数 / 保守 8 m/s 巡航 + 30s 降落余量，按 1%/s 粗估耗电。 */
    private fun rthEnergyError(tool: String, args: JSONObject, tm: TelemetrySnapshot): ApiError? {
        if (tool != "takeoff" && tool != "goto_waypoints") return null
        val homeDist = maxOf(
            GeoFence.distanceM(tm.lat, tm.lon, tm.homeLat, tm.homeLon), 1.0
        ) * 1.2
        val estPct = (homeDist / 8.0 + 30.0) / 60.0 * 5.0 // 5%/min 耗电近似
        if (tm.batteryPct - estPct < SafetyConfig.RTH_RESERVE_PCT) {
            return ApiError("E_BATTERY_RTH",
                "返航能量不足：电量 " + tm.batteryPct + "% - 估算耗电 " + String.format("%.1f", estPct) +
                    "% < 保留 " + SafetyConfig.RTH_RESERVE_PCT + "%")
        }
        return null
    }

    private fun extractWaypoints(args: JSONObject): JSONArray? {
        args.optJSONObject("mission")?.let { m -> m.optJSONArray("waypoints")?.let { return it } }
        return args.optJSONArray("waypoints")
    }
}
