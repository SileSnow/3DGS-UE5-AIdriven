package com.gaia.llmdrone.bridge.bridge

import dji.v5.common.error.IDJIError
import org.json.JSONObject

/**
 * MSDK 错误 -> PROTOCOL.md §8.2 错误码。
 * 原则：能归类的归到 spec 业务码；不能归类的统一 E_INTERNAL，并把 MSDK 原始错误放进 details。
 * TODO(未确认)：IDJIError 的具体 code()/description() 取值在不同 AAR 版本可能不同，真机阶段按日志补全映射表。
 */
object ErrorMapper {

    fun internal(where: String, t: Throwable?): ApiError =
        ApiError("E_INTERNAL", "内部错误@" + where + ": " + (t?.message ?: "unknown"))

    fun fromMsdk(where: String, error: IDJIError?): ApiError {
        val details = JSONObject().apply {
            put("where", where)
            put("msdk_error", error?.toString() ?: "null")
        }
        val raw = error?.toString() ?: ""
        val code = when {
            raw.contains("TIMEOUT", true) -> "E_RC_LINK"
            raw.contains("NO_GPS", true) || raw.contains("GPS", true) -> "E_GPS"
            raw.contains("BATTERY", true) -> "E_BATTERY_TAKEOFF"
            raw.contains("FLY_ZONE", true) || raw.contains("NO_FLY", true) -> "E_NOFLY"
            raw.contains("NOT_SUPPORT", true) -> "E_NOT_SUPPORTED"
            raw.contains("MISSION", true) -> "E_STATE"
            else -> "E_INTERNAL"
        }
        return ApiError(code, "MSDK 调用失败@" + where + ": " + raw, details)
    }

    fun state(message: String, details: JSONObject? = null): ApiError =
        ApiError("E_STATE", message, details)

    fun busy(message: String): ApiError = ApiError("E_BUSY", message)

    fun notAirborne(message: String): ApiError = ApiError("E_NOT_AIRBORNE", message)

    fun missionNotFound(missionId: String): ApiError =
        ApiError("E_MISSION_NOT_FOUND", "mission 不存在: " + missionId)

    // ---- spec v1.1 §15.3：设备就绪错误码细节（不新增顶层错误码，细节放 details）----

    /** SDK/App 未注册（App Key/网络/激活问题）→ E_RC_LINK + details.reason=not_registered */
    fun notRegistered(where: String): ApiError = ApiError(
        "E_RC_LINK", "SDK 未注册（App Key/网络问题）",
        JSONObject().apply { put("where", where); put("reason", "not_registered") }
    )

    /** 飞机/遥控器未连接 → E_RC_LINK + details.reason=not_connected */
    fun notConnected(where: String): ApiError = ApiError(
        "E_RC_LINK", "飞行器/遥控器未连接",
        JSONObject().apply { put("where", where); put("reason", "not_connected") }
    )

    /** 机型不在支持列表 → E_STATE + details.reason=aircraft_mismatch */
    fun aircraftMismatch(actualModel: String): ApiError = ApiError(
        "E_STATE", "机型不在支持列表: " + actualModel,
        JSONObject().apply { put("reason", "aircraft_mismatch"); put("actual_model", actualModel) }
    )
}
