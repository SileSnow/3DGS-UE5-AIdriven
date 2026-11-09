package com.gaia.llmdrone.bridge.safety

import org.json.JSONArray
import org.json.JSONObject

/**
 * 设备端安全阈值：默认值必须与 PROTOCOL.md §8 完全一致（对抗测试用默认值断言）。
 * 可配置项在真机阶段可改为从 assets/safety_config.json 读取；本骨架先常量 + JSON 导出。
 */
object SafetyConfig {

    const val MAX_REL_ALTITUDE_M = 120.0
    const val MAX_SPEED_MPS = 15.0
    const val MIN_BATTERY_TAKEOFF_PCT = 30.0
    const val RTH_RESERVE_PCT = 20.0
    const val MIN_GPS_FIX = 3
    const val MIN_GPS_SATELLITES = 10
    const val GEOFENCE_CENTER_LAT = 39.9042
    const val GEOFENCE_CENTER_LON = 116.4074
    const val GEOFENCE_RADIUS_M = 300.0

    /** 任务并发限制：执行中只允许这些工具 */
    val BUSY_ALLOWED_TOOLS = setOf(
        "abort", "get_telemetry", "get_mission_status", "return_to_home"
    )

    /** 需要 confirm=true 的飞行工具（PROTOCOL.md §8 规则 12） */
    val CONFIRM_REQUIRED_TOOLS = setOf("takeoff", "goto_waypoints")

    /** 白名单（agent 执行工具；plan_capture_mission / orbit 是 orchestrator 工具，不进入桥接层） */
    val WHITELIST = setOf(
        "get_telemetry", "preflight_check", "takeoff", "goto_waypoints", "set_gimbal",
        "capture_photo", "start_video", "stop_video", "return_to_home", "land",
        "abort", "get_mission_status", "set_mode"
    )

    /** 工具参数白名单（additionalProperties=false 的设备端等价校验） */
    val ALLOWED_ARGS: Map<String, Set<String>> = mapOf(
        "get_telemetry" to emptySet(),
        "preflight_check" to emptySet(),
        "takeoff" to setOf("altitude_m", "confirm"),
        "goto_waypoints" to setOf("mission", "plan_id", "waypoints", "speed_mps", "take_photos", "photo_interval_s", "confirm"),
        "set_gimbal" to setOf("pitch_deg", "yaw_deg"),
        "capture_photo" to setOf("count", "interval_s"),
        "start_video" to emptySet(),
        "stop_video" to emptySet(),
        "return_to_home" to emptySet(),
        "land" to emptySet(),
        "abort" to setOf("reason"),
        "get_mission_status" to setOf("mission_id"),
        "set_mode" to setOf("mode", "confirm")
    )

    /** PROTOCOL.md §8.1 默认禁飞区多边形（与仿真一致） */
    val DEFAULT_NO_FLY_POLYGON: List<Pair<Double, Double>> = listOf(
        39.9046 to 116.4078,
        39.9050 to 116.4078,
        39.9050 to 116.4082,
        39.9046 to 116.4082
    )

    fun toJson(): JSONObject = JSONObject().apply {
        put("max_rel_altitude_m", MAX_REL_ALTITUDE_M)
        put("max_speed_mps", MAX_SPEED_MPS)
        put("min_battery_takeoff_pct", MIN_BATTERY_TAKEOFF_PCT)
        put("rth_reserve_pct", RTH_RESERVE_PCT)
        put("min_gps_fix", MIN_GPS_FIX)
        put("min_gps_satellites", MIN_GPS_SATELLITES)
        put("geofence", JSONObject().apply {
            put("center_lat", GEOFENCE_CENTER_LAT)
            put("center_lon", GEOFENCE_CENTER_LON)
            put("radius_m", GEOFENCE_RADIUS_M)
        })
        put("no_fly_polygon", JSONArray().apply {
            DEFAULT_NO_FLY_POLYGON.forEach { (lat, lon) ->
                put(JSONObject().apply { put("lat", lat); put("lon", lon) })
            }
        })
    }
}
