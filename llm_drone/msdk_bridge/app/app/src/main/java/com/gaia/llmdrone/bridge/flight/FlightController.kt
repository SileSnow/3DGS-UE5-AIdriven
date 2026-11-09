package com.gaia.llmdrone.bridge.flight

import android.util.Log
import com.gaia.llmdrone.bridge.bridge.BridgeRuntime
import com.gaia.llmdrone.bridge.bridge.ErrorMapper
import dji.sdk.keyvalue.key.FlightControllerKey
import dji.v5.common.callback.CommonCallbacks
import dji.v5.common.error.IDJIError
import dji.v5.manager.KeyManager
import dji.v5.et.action
import dji.v5.et.create
import dji.v5.et.get
import dji.v5.manager.aircraft.virtualstick.VirtualStickManager
import dji.sdk.keyvalue.value.flightcontroller.VirtualStickFlightControlParam
import dji.sdk.keyvalue.value.flightcontroller.FlightCoordinateSystem
import dji.sdk.keyvalue.value.flightcontroller.RollPitchControlMode
import dji.sdk.keyvalue.value.flightcontroller.VerticalControlMode
import dji.sdk.keyvalue.value.flightcontroller.YawControlMode
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/**
 * 飞行控制：起飞（含爬升到目标相对高度）、自动降落、返航、停止各类动作、悬停。
 *
 * 官方依据：
 * - KeyStartTakeoff / KeyStartAutoLanding / KeyStopAutoLanding / KeyStopTakeoff / KeyStartGoHome /
 *   KeyStopGoHome / KeyConfirmLanding / KeyGoHomeHeight / KeyIsInLandingMode：
 *   https://developer.dji.com/api-reference-v5/android-api/Components/IKeyManager/Key_FlightController_FlightControllerKey.html
 * - 官方 sample 的 action 用法（KeyStartTakeoff.create().action(onSuccess, onFailure)）：
 *   https://raw.githubusercontent.com/dji-sdk/Mobile-SDK-Android-V5/dev-sdk-main/SampleCode-V5/android-sdk-v5-sample/src/main/java/dji/sampleV5/aircraft/models/BasicAircraftControlVM.kt
 * - 虚拟摇杆（到指定高度需要接管控制权）：官方教程
 *   https://developer.dji.com/doc/mobile-sdk-tutorial/en/tutorials/virtual-stick.html
 *   要求：不在自动任务中、遥控器 N 档、发送频率 5–25Hz；本骨架以 10Hz 爬升。
 *
 * 未执行边界：本机无真机/Android SDK，以下逻辑未编译、未飞行验证。
 */
object FlightController {

    private const val TAG = "FlightController"
    private const val CLIMB_RATE_MPS = 2.0
    private const val CLIMB_TOLERANCE_M = 0.4
    private const val CLIMB_TIMEOUT_MS = 60_000L

    private val altitudeKey = FlightControllerKey.KeyAltitude.create()
    private val isFlyingKey = FlightControllerKey.KeyIsFlying.create()
    private val goHomeHeightKey = FlightControllerKey.KeyGoHomeHeight.create()

    /** 起飞并爬升到 altitudeM（相对起飞点）。dry_run 模式由 CommandExecutor 提前拦截，不会到这里。 */
    suspend fun takeoff(altitudeM: Double): Result<Unit> {
        BridgeRuntime.setState("taking_off")
        val started = action(FlightControllerKey.KeyStartTakeoff, "takeoff")
        if (started.isFailure) {
            BridgeRuntime.setState("idle")
            return started
        }
        // 等待飞机离地
        if (!waitUntil(20_000L) { isFlyingKey.get(false) == true }) {
            BridgeRuntime.setState("idle")
            return Result.failure(IllegalStateException("起飞后 20s 未检测到离地（KeyIsFlying=false）"))
        }
        // 到指定高度：KeyStartTakeoff 无高度参数，必须用虚拟摇杆爬升
        val climbed = climbTo(altitudeM)
        if (climbed.isFailure) return climbed
        BridgeRuntime.setState("hovering")
        return Result.success(Unit)
    }

    /** 垂直爬升/下降到目标相对高度（虚拟摇杆 advanced mode，垂直速度模式）。 */
    suspend fun climbTo(targetAltM: Double): Result<Unit> {
        val vsm = VirtualStickManager.getInstance()
        val enabled = suspendCancellableCoroutine<Result<Unit>> { cont ->
            vsm.enableVirtualStick(object : CommonCallbacks.CompletionCallback {
                override fun onSuccess() = cont.resume(Result.success(Unit))
                override fun onFailure(error: IDJIError) =
                    cont.resume(Result.failure(IllegalStateException("enableVirtualStick: " + error)))
            })
        }
        if (enabled.isFailure) return enabled
        vsm.setVirtualStickAdvancedModeEnabled(true)

        try {
            val deadline = System.currentTimeMillis() + CLIMB_TIMEOUT_MS
            while (System.currentTimeMillis() < deadline) {
                val altitude = altitudeKey.get(0.0)
                val delta = targetAltM - altitude
                if (kotlin.math.abs(delta) <= CLIMB_TOLERANCE_M) break
                val param = newVirtualStickParam(if (delta > 0) CLIMB_RATE_MPS else -CLIMB_RATE_MPS)
                vsm.sendVirtualStickAdvancedParam(param)
                delay(100L) // 10Hz
            }
            // 停止垂直运动
            val stopParam = newVirtualStickParam(0.0)
            vsm.sendVirtualStickAdvancedParam(stopParam)
            delay(300L)
        } finally {
            vsm.setVirtualStickAdvancedModeEnabled(false)
            suspendCancellableCoroutine<Unit> { cont ->
                vsm.disableVirtualStick(object : CommonCallbacks.CompletionCallback {
                    override fun onSuccess() { cont.resume(Unit) }
                    override fun onFailure(error: IDJIError) {
                        Log.w(TAG, "disableVirtualStick: " + error); cont.resume(Unit)
                    }
                })
            }
        }
        BridgeRuntime.setState("hovering")
        return Result.success(Unit)
    }

    suspend fun land(): Result<Unit> {
        BridgeRuntime.setState("landing")
        val r = action(FlightControllerKey.KeyStartAutoLanding, "land")
        if (r.isFailure) BridgeRuntime.setState("hovering")
        return r
    }

    suspend fun cancelLanding(): Result<Unit> = action(FlightControllerKey.KeyStopAutoLanding, "cancelLanding")

    suspend fun confirmLanding(): Result<Unit> = action(FlightControllerKey.KeyConfirmLanding, "confirmLanding")

    /** 一键返航；返航高度应由 SafetyGuard/预检设置为不超过 120m 且高于作业高度。 */
    suspend fun returnToHome(goHomeHeightM: Int = 100): Result<Unit> {
        try {
            // GoHomeHeight 为 Integer 米；避免默认高度过低。用官方 KeyManager.setValue 写入。
            KeyManager.getInstance().setValue(
                goHomeHeightKey, goHomeHeightM,
                object : CommonCallbacks.CompletionCallback {
                    override fun onSuccess() { Log.i(TAG, "GoHomeHeight set to " + goHomeHeightM) }
                    override fun onFailure(error: IDJIError) { Log.w(TAG, "set GoHomeHeight failed: " + error) }
                }
            )
        } catch (t: Throwable) {
            Log.w(TAG, "set GoHomeHeight failed: " + t.message)
        }
        BridgeRuntime.setState("returning")
        val r = action(FlightControllerKey.KeyStartGoHome, "returnToHome")
        if (r.isFailure) BridgeRuntime.setState("hovering")
        return r
    }

    suspend fun stopGoHome(): Result<Unit> = action(FlightControllerKey.KeyStopGoHome, "stopGoHome")

    suspend fun stopTakeoff(): Result<Unit> = action(FlightControllerKey.KeyStopTakeoff, "stopTakeoff")

    /** 悬停：停掉虚拟摇杆控制后飞机保持悬停（无独立 hover 动作 Key）。 */
    suspend fun hover(): Result<Unit> {
        return try {
            val vsm = VirtualStickManager.getInstance()
            vsm.sendVirtualStickAdvancedParam(newVirtualStickParam(0.0))
            vsm.disableVirtualStick(object : CommonCallbacks.CompletionCallback {
                override fun onSuccess() {}
                override fun onFailure(error: IDJIError) { Log.w(TAG, "hover disable: " + error) }
            })
            BridgeRuntime.setState("hovering")
            Result.success(Unit)
        } catch (t: Throwable) {
            Result.failure(t)
        }
    }

    fun isFlying(): Boolean = try {
        isFlyingKey.get(false) ?: false
    } catch (t: Throwable) {
        false
    }

    fun currentAltRelM(): Double = try {
        altitudeKey.get(0.0) ?: 0.0
    } catch (t: Throwable) {
        0.0
    }

    private suspend fun action(key: dji.sdk.keyvalue.key.DJIKey.ActionKey<*, *>, where: String): Result<Unit> =
        suspendCancellableCoroutine { cont ->
            try {
                @Suppress("UNCHECKED_CAST")
                val actionKey = key as dji.sdk.keyvalue.key.DJIKey.ActionKey<dji.sdk.keyvalue.value.common.EmptyMsg, dji.sdk.keyvalue.value.common.EmptyMsg>
                actionKey.action(
                    { cont.resume(Result.success(Unit)) },
                    { e: IDJIError -> cont.resume(Result.failure(IllegalStateException(where + ": " + e))) }
                )
            } catch (t: Throwable) {
                cont.resume(Result.failure(t))
            }
        }

    private suspend fun waitUntil(timeoutMs: Long, predicate: () -> Boolean): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (predicate()) return true
            delay(200L)
        }
        return predicate()
    }

    /**
     * 08 §6.7：虚拟摇杆 advanced mode 参数——显式设置三种控制模式（速度/角速度/速度），
     * 水平初值为 0 只用 verticalThrottle 做垂直速度闭环。
     * TODO(未确认)：字段名/单位以 5.20.1 AAR 的 VirtualStickFlightControlParam 为准；避障在虚拟摇杆下可能被抑制。
     */
    private fun newVirtualStickParam(verticalThrottleMps: Double): VirtualStickFlightControlParam =
        VirtualStickFlightControlParam().apply {
            rollPitchControlMode = RollPitchControlMode.VELOCITY
            rollPitchCoordinateSystem = FlightCoordinateSystem.BODY
            yawControlMode = YawControlMode.ANGULAR_VELOCITY
            verticalControlMode = VerticalControlMode.VELOCITY
            pitch = 0.0
            roll = 0.0
            yaw = 0.0
            verticalThrottle = verticalThrottleMps
        }
}
