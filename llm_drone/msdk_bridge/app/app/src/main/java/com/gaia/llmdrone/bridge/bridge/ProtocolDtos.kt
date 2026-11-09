package com.gaia.llmdrone.bridge.bridge

import org.json.JSONArray
import org.json.JSONObject

/**
 * 协议 DTO 与 JSON 序列化。
 * 事实源：llm_drone/spec/PROTOCOL.md §3/§5/§7（v1.0 FROZEN）。
 * 本文件是所有对 Orchestrator 输出字段的可执行定义；字段名必须与 spec 完全一致。
 */

data class ApiError(
    val code: String,
    val message: String,
    val details: JSONObject? = null
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("code", code)
        put("message", message)
        details?.let { put("details", it) }
    }
}

data class CommandRequest(
    val commandId: String,
    val tool: String,
    val args: JSONObject,
    val confirm: Boolean,
    val runId: String?
) {
    companion object {
        fun parse(body: JSONObject): CommandRequest {
            val confirm = body.optBoolean("confirm", false) ||
                (body.optJSONObject("args")?.optBoolean("confirm", false) ?: false)
            return CommandRequest(
                commandId = body.optString("command_id", ""),
                tool = body.optString("tool", ""),
                args = body.optJSONObject("args") ?: JSONObject(),
                confirm = confirm,
                runId = body.optString("run_id", null)
            )
        }
    }
}

/** PROTOCOL.md §5 遥测快照。real 模式 sim_time_s = null（唯一字段差异，见 PROTOCOL_COMPLIANCE.md）。 */
data class TelemetrySnapshot(
    val ts: String,
    val simTimeS: Double? = null,
    val state: String,
    val lat: Double,
    val lon: Double,
    val altRelM: Double,
    val altAbsM: Double,
    val speedMps: Double,
    val verticalSpeedMps: Double,
    val batteryPct: Double,
    val gimbalPitch: Double,
    val gimbalYaw: Double,
    val gimbalRoll: Double,
    val gpsFix: Int,
    val gpsSatellites: Int,
    val rcConnected: Boolean,
    val signal: String,
    val mode: String,
    val missionId: String?,
    val homeLat: Double,
    val homeLon: Double,
    val homeAltAbsM: Double
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("ts", ts)
        put("sim_time_s", simTimeS ?: JSONObject.NULL)
        put("state", state)
        put("lat", lat)
        put("lon", lon)
        put("alt_rel_m", altRelM)
        put("alt_abs_m", altAbsM)
        put("speed_mps", speedMps)
        put("vertical_speed_mps", verticalSpeedMps)
        put("battery_pct", batteryPct)
        put("gimbal", JSONObject().apply {
            put("pitch", gimbalPitch); put("yaw", gimbalYaw); put("roll", gimbalRoll)
        })
        put("gps", JSONObject().apply {
            put("fix", gpsFix); put("satellites", gpsSatellites)
        })
        put("rc", JSONObject().apply {
            put("connected", rcConnected); put("signal", signal)
        })
        put("mode", mode)
        put("mission_id", missionId ?: JSONObject.NULL)
        put("home", JSONObject().apply {
            put("lat", homeLat); put("lon", homeLon); put("alt_abs_m", homeAltAbsM)
        })
    }
}

/** PROTOCOL.md §7.1 照片记录（real 模式 c2w 为推算值，见 README 与 PROTOCOL_COMPLIANCE）。 */
data class PhotoRecord(
    val index: Int,
    val file: String,
    val ts: String,
    val lat: Double,
    val lon: Double,
    val altRelM: Double,
    val altAbsM: Double,
    val headingDeg: Double,
    val gimbalPitch: Double,
    val gimbalYaw: Double,
    val gimbalRoll: Double,
    val c2w: List<Double>?,
    // spec v1.1 §15.2：real 后端的位姿真相来源与精度。sim=truth；real=estimated；遥测缺失=unavailable
    val poseSource: String = "estimated",
    val poseAccuracyM: Double? = 3.0
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("index", index)
        put("file", file)
        put("ts", ts)
        put("lat", lat)
        put("lon", lon)
        put("alt_rel_m", altRelM)
        put("alt_abs_m", altAbsM)
        put("heading_deg", headingDeg)
        put("gimbal", JSONObject().apply {
            put("pitch", gimbalPitch); put("yaw", gimbalYaw); put("roll", gimbalRoll)
        })
        put("c2w", c2w?.let { JSONArray(it) } ?: JSONObject.NULL)
        put("pose_source", poseSource)
        put("pose_accuracy_m", poseAccuracyM ?: JSONObject.NULL)
    }
}

/** PROTOCOL.md §7.1 任务记录。state ∈ pending|executing|paused|completed|aborted|failed */
data class MissionRecord(
    val missionId: String,
    val planId: String?,
    var state: String,
    val createdAt: String,
    var startedAt: String?,
    var endedAt: String?,
    var progressPct: Double,
    val photos: MutableList<PhotoRecord>,
    var error: ApiError?,
    val nWaypoints: Int,
    val nPhotoPoints: Int
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("ok", true)
        put("mission_id", missionId)
        put("plan_id", planId ?: JSONObject.NULL)
        put("state", state)
        put("created_at", createdAt)
        put("started_at", startedAt ?: JSONObject.NULL)
        put("ended_at", endedAt ?: JSONObject.NULL)
        put("progress_pct", progressPct)
        put("photos", JSONArray().apply { photos.forEach { put(it.toJson()) } })
        put("error", error?.toJson() ?: JSONObject.NULL)
        put("stats", JSONObject().apply {
            put("distance_m", 0.0)   // TODO(未确认)：由任务航点几何估算；真机不单独测距
            put("duration_s", durationSeconds())
            put("n_photos", photos.size)
        })
    }

    private fun durationSeconds(): Double {
        val s = startedAt ?: return 0.0
        return try {
            val start = java.time.OffsetDateTime.parse(s).toInstant().toEpochMilli()
            val end = endedAt?.let { java.time.OffsetDateTime.parse(it).toInstant().toEpochMilli() }
                ?: System.currentTimeMillis()
            (end - start) / 1000.0
        } catch (t: Throwable) {
            0.0
        }
    }
}

/** 统一命令响应构造器（PROTOCOL.md §3.3）。 */
object Responses {

    fun commandOk(
        commandId: String,
        tool: String,
        state: String,
        telemetry: TelemetrySnapshot,
        warnings: List<String> = emptyList(),
        extra: JSONObject? = null
    ): JSONObject = JSONObject().apply {
        put("ok", true)
        put("command_id", commandId)
        put("tool", tool)
        put("state", state)
        put("telemetry", telemetry.toJson())
        put("warnings", JSONArray(warnings))
        extra?.keys()?.forEach { k -> put(k, extra.get(k)) }
    }

    fun commandError(
        commandId: String,
        tool: String,
        state: String,
        telemetry: TelemetrySnapshot,
        error: ApiError
    ): JSONObject = JSONObject().apply {
        put("ok", false)
        put("command_id", commandId)
        put("tool", tool)
        put("state", state)
        put("error", error.toJson())
        put("telemetry", telemetry.toJson())
        put("warnings", JSONArray())
    }

    fun notSupported(endpoint: String): JSONObject = JSONObject().apply {
        put("ok", false)
        put("error", ApiError(
            "E_NOT_SUPPORTED",
            endpoint + " 是仿真专属端点；Phase2 MSDK 桥不支持"
        ).toJson())
    }
}
