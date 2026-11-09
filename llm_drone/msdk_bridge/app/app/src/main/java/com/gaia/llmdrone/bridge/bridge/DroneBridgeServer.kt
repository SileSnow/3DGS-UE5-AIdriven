package com.gaia.llmdrone.bridge.bridge

import android.util.Log
import fi.iki.elonen.NanoHTTPD
import org.json.JSONObject

/**
 * 本机 HTTP 服务（NanoHTTPD，端口默认 8765）。
 *
 * 端点（事实源 PROTOCOL.md §3.2）：
 *   GET  /v1/health
 *   GET  /v1/telemetry
 *   POST /v1/command
 *   GET  /v1/missions/{mission_id}
 *   GET  /v1/missions?limit=10
 *   GET  /v1/audit?since_seq=N
 *   POST /v1/reset        -> E_NOT_SUPPORTED（仿真专属）
 *   POST /v1/sim/config   -> E_NOT_SUPPORTED（仿真专属）
 *
 * 部署方式：手机 USB 连电脑后 adb forward tcp:8765 tcp:8765，Orchestrator 访问 127.0.0.1:8765。
 * 未执行边界：未编译、未在手机启动；NanoHTTPD 选型见 README "Android 端组件划分"。
 */
// 默认只绑定回环地址（spec/部署默认），避免把无鉴权的桥接口暴露到局域网。
// 双机部署（手机热点）需显式改为 NanoHTTPD("0.0.0.0", port) 并加 token（DESIGN.md 设计预留，骨架未实现）。
class DroneBridgeServer(port: Int = 8765) : NanoHTTPD("127.0.0.1", port) {

    override fun serve(session: IHTTPSession): Response {
        val uri = session.uri ?: "/"
        val method = session.method
        return try {
            when {
                method == Method.GET && uri == "/v1/health" -> json(healthJson())
                method == Method.GET && uri == "/v1/telemetry" ->
                    json(TelemetryPublisher.snapshot().toJson())
                method == Method.POST && uri == "/v1/command" -> handleCommand(session)
                method == Method.GET && uri.startsWith("/v1/missions/") -> {
                    val id = uri.removePrefix("/v1/missions/").trim('/')
                    val record = MissionStore.get(id)
                    if (record == null) json(Responses.commandError(
                        "", "get_mission_status", BridgeRuntime.state,
                        TelemetryPublisher.snapshot(), ErrorMapper.missionNotFound(id)
                    )) else json(record.toJson())
                }
                method == Method.GET && uri == "/v1/missions" -> {
                    val limit = session.parameters["limit"]?.firstOrNull()?.toIntOrNull() ?: 10
                    json(JSONObject().apply {
                        put("ok", true)
                        put("missions", org.json.JSONArray().apply {
                            MissionStore.list(limit).forEach { put(it.toJson()) }
                        })
                    })
                }
                method == Method.GET && uri == "/v1/audit" -> {
                    val since = session.parameters["since_seq"]?.firstOrNull()?.toLongOrNull() ?: 0L
                    val (events, last) = AuditLogger.eventsSince(since)
                    json(JSONObject().apply {
                        put("ok", true); put("events", events); put("last_seq", last)
                    })
                }
                method == Method.POST && uri == "/v1/reset" -> json(Responses.notSupported("/v1/reset"))
                method == Method.POST && uri == "/v1/sim/config" -> json(Responses.notSupported("/v1/sim/config"))
                else -> newFixedLengthResponse(
                    Response.Status.NOT_FOUND,
                    "application/json; charset=utf-8",
                    JSONObject().apply {
                        put("ok", false)
                        put("error", ApiError("E_NOT_SUPPORTED", "未知端点: " + method + " " + uri).toJson())
                    }.toString()
                )
            }
        } catch (t: Throwable) {
            Log.e(TAG, "serve failed: " + t.message)
            json(JSONObject().apply {
                put("ok", false)
                put("error", ApiError("E_INTERNAL", "HTTP 处理异常: " + (t.message ?: "unknown")).toJson())
            })
        }
    }

    private fun healthJson(): JSONObject = JSONObject().apply {
        put("ok", true)
        put("backend", "msdk")
        put("version", BridgeRuntime.VERSION)
        put("mode", BridgeRuntime.mode)
        put("time_scale", 1.0) // real 模式按墙钟推进（非仿真时间）
        put("ts", BridgeRuntime.nowIso())
        // 附加只读诊断字段（additive，不改变 spec 语义；见 PROTOCOL_COMPLIANCE.md）
        put("device", JSONObject().apply {
            put("msdk_registered", com.gaia.llmdrone.bridge.msdk.MsdkInitManager.isRegistered)
            put("product_connected", com.gaia.llmdrone.bridge.msdk.MsdkInitManager.isProductConnected)
            put("sdk_version", com.gaia.llmdrone.bridge.msdk.MsdkInitManager.sdkVersion())
        })
    }

    private fun handleCommand(session: IHTTPSession): Response {
        val body = HashMap<String, String>()
        session.parseBody(body)
        val raw = body["postData"] ?: "{}"
        val req = CommandRequest.parse(JSONObject(raw))
        return json(CommandExecutor.dispatch(req))
    }

    private fun json(obj: JSONObject): Response =
        newFixedLengthResponse(Response.Status.OK, "application/json; charset=utf-8", obj.toString())

    companion object {
        private const val TAG = "DroneBridgeServer"
    }
}
