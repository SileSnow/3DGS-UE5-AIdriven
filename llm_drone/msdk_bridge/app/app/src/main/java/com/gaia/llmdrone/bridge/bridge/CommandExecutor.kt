package com.gaia.llmdrone.bridge.bridge

import android.util.Log
import com.gaia.llmdrone.bridge.camera.CameraController
import com.gaia.llmdrone.bridge.flight.FlightController
import com.gaia.llmdrone.bridge.gimbal.GimbalController
import com.gaia.llmdrone.bridge.mission.MissionExecutor
import com.gaia.llmdrone.bridge.safety.SafetyConfig
import com.gaia.llmdrone.bridge.safety.SafetyGuard
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.util.Collections
import java.util.LinkedHashMap

/**
 * /v1/command 路由器：幂等缓存 -> 安全检查 -> 异步执行 -> 立即返回（遵守 Orchestrator 单请求 10s 超时）。
 *
 * 关键设计（PROTOCOL.md §3.1/§3.3）：
 * - 业务失败也 HTTP 200，body {"ok":false,"error":{code,message}}。
 * - 飞行类命令是"接受/拒绝"语义：安全通过后立刻返回 state（taking_off/mission/landing/returning），
 *   实际执行在后台协程；Orchestrator 用 /v1/telemetry、/v1/missions/{id} 轮询进度。
 * - command_id 幂等：同样 command_id 重复请求返回首次结果（缓存最近 100 条）。
 *
 * 未执行边界：未编译、未真机；异步执行中的并发状态机只在"单飞控单任务"假设下验证。
 */
object CommandExecutor {

    private const val TAG = "CommandExecutor"
    private const val CACHE_MAX = 100

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val cache: MutableMap<String, JSONObject> = Collections.synchronizedMap(
        object : LinkedHashMap<String, JSONObject>(CACHE_MAX, 0.75f, true) {
            override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, JSONObject>?): Boolean =
                size > CACHE_MAX
        }
    )

    fun dispatch(req: CommandRequest): JSONObject {
        // 0) 参数合法性：command_id 必填（幂等键）
        if (req.commandId.isBlank()) {
            return errorResponse(req, ApiError("E_SCHEMA", "command_id 不能为空"))
        }
        cache[req.commandId]?.let {
            Log.i(TAG, "idempotent replay command_id=" + req.commandId)
            return it
        }

        AuditLogger.append("command_received", JSONObject().apply {
            put("command_id", req.commandId)
            put("tool", req.tool)
            put("args", req.args)
            put("confirm", req.confirm)
            put("run_id", req.runId ?: JSONObject.NULL)
        })

        val resp = try {
            handle(req)
        } catch (t: Throwable) {
            Log.e(TAG, "dispatch exception: " + t.message)
            errorResponse(req, ErrorMapper.internal("dispatch", t))
        }
        cache[req.commandId] = resp
        return resp
    }

    private fun handle(req: CommandRequest): JSONObject {
        val tm = TelemetryPublisher.snapshot()

        // 1) 白名单 + 并发控制（PROTOCOL.md §8 规则 16）
        if (req.tool !in SafetyConfig.WHITELIST) {
            return errorResponse(req, ApiError("E_UNKNOWN_TOOL", "工具不在白名单: " + req.tool))
        }
        if (BridgeRuntime.missionActive && req.tool !in SafetyConfig.BUSY_ALLOWED_TOOLS) {
            return errorResponse(req, ErrorMapper.busy("任务执行中，仅允许 " + SafetyConfig.BUSY_ALLOWED_TOOLS))
        }

        // 2) 安全检查（顺序固定；拒绝即返回）
        val decision = SafetyGuard.validate(req.tool, req, tm)
        if (!decision.allow) {
            return errorResponse(req, decision.error ?: ApiError("E_INTERNAL", "安全检查拒绝"))
        }

        // 3) dry_run：除只读外，只回"校验通过、未执行"，不触碰飞控
        if (BridgeRuntime.mode == "dry_run" && req.tool !in setOf("get_telemetry", "preflight_check", "get_mission_status")) {
            AuditLogger.append("command_dry_run", JSONObject().apply {
                put("tool", req.tool); put("command_id", req.commandId)
            })
            return Responses.commandOk(
                req.commandId, req.tool, tm.state, tm,
                warnings = listOf("dry_run: 校验通过，未执行"),
                extra = JSONObject().apply { put("executed", false) }
            )
        }

        // 4) 分派
        return when (req.tool) {
            "get_telemetry" -> Responses.commandOk(req.commandId, req.tool, tm.state, tm)
            "preflight_check" -> {
                val (canFly, checks) = SafetyGuard.preflight(tm)
                Responses.commandOk(req.commandId, req.tool, tm.state, tm, extra = JSONObject().apply {
                    put("can_fly", canFly)
                    put("checks", checks)
                })
            }
            "takeoff" -> {
                val altitude = req.args.optDouble("altitude_m")
                scope.launch {
                    val r = FlightController.takeoff(altitude)
                    AuditLogger.append(if (r.isSuccess) "takeoff_completed" else "takeoff_failed",
                        JSONObject().apply {
                            put("altitude_m", altitude)
                            if (r.isFailure) put("error", r.exceptionOrNull()?.message ?: "unknown")
                        })
                }
                BridgeRuntime.setState("taking_off")
                Responses.commandOk(req.commandId, req.tool, "taking_off", TelemetryPublisher.snapshot())
            }
            "goto_waypoints" -> {
                val mission = req.args.optJSONObject("mission")
                    ?: JSONObject().apply { put("waypoints", req.args.optJSONArray("waypoints") ?: JSONArray()) }
                val planId = req.args.optString("plan_id", null)
                if (planId != null && !mission.has("plan_id")) mission.put("plan_id", planId)
                val missionId = mission.optString("mission_id", BridgeRuntime.nextMissionId())
                mission.put("mission_id", missionId)
                BridgeRuntime.currentMissionId = missionId
                BridgeRuntime.missionActive = true
                scope.launch {
                    val record = MissionExecutor.execute(mission)
                    AuditLogger.append("mission_finished", JSONObject().apply {
                        put("mission_id", record.missionId)
                        put("state", record.state)
                        put("n_photos", record.photos.size)
                    })
                }
                Responses.commandOk(req.commandId, req.tool, "mission", TelemetryPublisher.snapshot(),
                    extra = JSONObject().apply { put("mission_id", missionId) })
            }
            "set_gimbal" -> {
                val pitch = req.args.optDouble("pitch_deg")
                val yaw = if (req.args.has("yaw_deg")) req.args.optDouble("yaw_deg") else null
                scope.launch { GimbalController.setAngle(pitch, yaw) }
                Responses.commandOk(req.commandId, req.tool, tm.state, tm)
            }
            "capture_photo" -> {
                val count = req.args.optInt("count", 1)
                val interval = req.args.optDouble("interval_s", 1.0)
                scope.launch { CameraController.capture(count, interval) }
                Responses.commandOk(req.commandId, req.tool, tm.state, tm)
            }
            "start_video" -> {
                scope.launch { CameraController.startVideo() }
                Responses.commandOk(req.commandId, req.tool, tm.state, tm)
            }
            "stop_video" -> {
                scope.launch { CameraController.stopVideo() }
                Responses.commandOk(req.commandId, req.tool, tm.state, tm)
            }
            "return_to_home" -> {
                BridgeRuntime.currentMissionId?.let {
                    scope.launch { /* MissionExecutor 会在任务完成时更新记录；RTH 期间标记 aborted 由 flight 回调完成 */ }
                }
                scope.launch { FlightController.returnToHome() }
                BridgeRuntime.setState("returning")
                Responses.commandOk(req.commandId, req.tool, "returning", TelemetryPublisher.snapshot())
            }
            "land" -> {
                scope.launch { FlightController.land() }
                BridgeRuntime.setState("landing")
                Responses.commandOk(req.commandId, req.tool, "landing", TelemetryPublisher.snapshot())
            }
            "abort" -> {
                val reason = req.args.optString("reason", "unspecified")
                BridgeRuntime.lastAbortReason = reason
                AuditLogger.append("abort_requested", JSONObject().apply { put("reason", reason) })
                scope.launch {
                    com.gaia.llmdrone.bridge.mission.WaypointMissionController.stop()
                    FlightController.hover()
                }
                Responses.commandOk(req.commandId, req.tool, "hovering", TelemetryPublisher.snapshot(),
                    extra = JSONObject().apply { put("reason", reason) })
            }
            "get_mission_status" -> {
                val missionId = req.args.optString("mission_id", null)
                val record = (missionId?.let { MissionStore.get(it) } ?: MissionStore.latest())
                if (record == null && missionId != null) {
                    errorResponse(req, ErrorMapper.missionNotFound(missionId))
                } else {
                    Responses.commandOk(req.commandId, req.tool, tm.state, tm, extra = JSONObject().apply {
                        put("mission", record?.toJson() ?: JSONObject.NULL)
                    })
                }
            }
            "set_mode" -> {
                val newMode = req.args.optString("mode")
                if (newMode == "sim") {
                    errorResponse(req, ApiError("E_NOT_SUPPORTED", "Phase2 桥接层不支持 sim 模式"))
                } else {
                    BridgeRuntime.resetForMode(newMode)
                    AuditLogger.append("mode_changed", JSONObject().apply {
                        put("mode", newMode); put("confirm", req.confirm)
                    })
                    Responses.commandOk(req.commandId, req.tool, "idle", TelemetryPublisher.snapshot(),
                        extra = JSONObject().apply { put("mode", newMode) })
                }
            }
            else -> errorResponse(req, ApiError("E_UNKNOWN_TOOL", "工具不在白名单: " + req.tool))
        }
    }

    private fun errorResponse(req: CommandRequest, error: ApiError): JSONObject =
        Responses.commandError(req.commandId, req.tool, TelemetryPublisher.snapshot().state,
            TelemetryPublisher.snapshot(), error)
}
