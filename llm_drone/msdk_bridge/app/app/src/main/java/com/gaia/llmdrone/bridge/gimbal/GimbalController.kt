package com.gaia.llmdrone.bridge.gimbal

import android.util.Log
import dji.sdk.keyvalue.key.DJIKey
import dji.sdk.keyvalue.key.GimbalKey
import dji.sdk.keyvalue.key.KeyTools
import dji.sdk.keyvalue.value.common.Attitude
import dji.sdk.keyvalue.value.common.EmptyMsg
import dji.sdk.keyvalue.value.gimbal.GimbalAngleRotation
import dji.sdk.keyvalue.value.gimbal.GimbalAngleRotationMode
import dji.v5.common.callback.CommonCallbacks
import dji.v5.common.error.IDJIError
import dji.v5.et.create
import dji.v5.et.get
import dji.v5.et.listen
import dji.v5.manager.KeyManager
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/**
 * 云台控制：按绝对角度设置 pitch/yaw（Mini 4 Pro 云台俯仰 -90~0）。
 *
 * 官方依据：
 * - GimbalKey.KeyRotateByAngle（DJIActionKeyInfo<GimbalAngleRotation, EmptyMsg>）/ KeyGimbalAttitude：
 *   https://developer.dji.com/api-reference-v5/android-api/Components/IKeyManager/Key_GimbalKey.html
 * - KeyManager.performAction(DJIKey.ActionKey<P, R>, P param, CompletionCallbackWithParam<R>)：
 *   https://developer.dji.com/api-reference-v5/android-api/Components/IKeyManager/IKeyManager.html
 * - GimbalAngleRotationMode.ABSOLUTE_ANGLE / RELATIVE_ANGLE：同 GimbalKey 页面 DJIValue 枚举说明。
 *
 * T9 复核（evidence/API_SYMBOLS_VERIFIED.md §2 + docs/research/08 §6.4）：GimbalAngleRotation 是可变字段类
 * （mode/pitch/roll/yaw/pitchIgnored/...），用无参构造 + apply；KeyRotateByAngle 的 createKey 不传 componentIndex。
 * TODO(未确认)：角度符号约定与可达范围需真机回读 KeyGimbalAttitude 验证（Mini 4 Pro -90°~+35°）。
 * TODO(未确认)：Mini 4 Pro 的 yaw 是否为相对机头可独立控制需真机确认；默认 0（不改变）。
 */
object GimbalController {

    private const val TAG = "GimbalController"
    private val attitudeKey = GimbalKey.KeyGimbalAttitude.create()

    fun startListening(holder: Any) {
        try {
            attitudeKey.listen(holder) { _, _ -> }
        } catch (t: Throwable) {
            Log.w(TAG, "gimbal listen failed: " + t.message)
        }
    }

    suspend fun setAngle(pitchDeg: Double, yawDeg: Double?): Result<Unit> {
        val pitch = pitchDeg.coerceIn(-90.0, 0.0)
        val yaw = (yawDeg ?: 0.0).coerceIn(-180.0, 180.0)
        // T9 复核：evidence/API_SYMBOLS_VERIFIED.md E1 字段表显示 GimbalAngleRotation 为可变字段
        // (mode/pitch/roll/yaw/...)，08 §6.4 也是无参构造 + apply 写法；先前 4 参构造顺序无依据，已改为 apply。
        val rotation = GimbalAngleRotation().apply {
            mode = GimbalAngleRotationMode.ABSOLUTE_ANGLE
            this.pitch = pitch
            roll = 0.0
            this.yaw = yaw
        }
        return suspendCancellableCoroutine { cont ->
            try {
                // 08 §6.4：createKey(GimbalKey.KeyRotateByAngle) 不传 componentIndex（云台 Key 非相机 Key）
                @Suppress("UNCHECKED_CAST")
                val key = KeyTools.createKey(GimbalKey.KeyRotateByAngle)
                    as DJIKey.ActionKey<GimbalAngleRotation, EmptyMsg>
                KeyManager.getInstance().performAction(key, rotation,
                    object : CommonCallbacks.CompletionCallbackWithParam<EmptyMsg> {
                        override fun onSuccess(t: EmptyMsg?) {
                            cont.resume(Result.success(Unit))
                        }
                        override fun onFailure(error: IDJIError) {
                            cont.resume(Result.failure(IllegalStateException("gimbal rotate: " + error)))
                        }
                    })
            } catch (t: Throwable) {
                cont.resume(Result.failure(t))
            }
        }
    }

    /** 回读当前云台姿态；Attitude 构造参数用于默认值，真机前按 API Reference 校准。 */
    fun currentAttitude(): Attitude? = try {
        attitudeKey.get(Attitude(0.0, 0.0, 0.0))
    } catch (t: Throwable) {
        null
    }
}
