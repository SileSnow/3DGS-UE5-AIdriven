package com.gaia.llmdrone.bridge.bridge

import android.util.Log
import dji.sdk.keyvalue.key.BatteryKey
import dji.sdk.keyvalue.key.DJIKey
import dji.sdk.keyvalue.key.FlightControllerKey
import dji.sdk.keyvalue.key.GimbalKey
import dji.sdk.keyvalue.key.RemoteControllerKey
import dji.sdk.keyvalue.value.common.Attitude
import dji.sdk.keyvalue.value.common.LocationCoordinate2D
import dji.sdk.keyvalue.value.common.Velocity3D
import dji.sdk.keyvalue.value.flightcontroller.FlightMode
import dji.sdk.keyvalue.value.flightcontroller.GPSSignalLevel
import dji.sdk.keyvalue.value.flightcontroller.GoHomeState
import dji.v5.et.create
import dji.v5.et.listen
import dji.v5.manager.KeyManager

/**
 * 遥测聚合：把 MSDK v5 的 DJIKey 读数映射为 PROTOCOL.md §5 的遥测快照。
 *
 * 官方依据：
 * - IKeyManager.getValue(DJIKey<R>) / getValue(DJIKey<R>, R default) / listen(DJIKey<R>, holder, KeyListener)：
 *   https://developer.dji.com/api-reference-v5/android-api/Components/IKeyManager/IKeyManager.html
 * - FlightControllerKey.KeyAircraftLocation / KeyAltitude / KeyTakeoffLocationAltitude / KeyHomeLocation /
 *   KeyAircraftVelocity / KeyFlightMode / KeyGPSSatelliteCount / KeyGPSSignalLevel / KeyIsFlying /
 *   KeyIsFailsafe / KeyGoHomeStatus / KeyIsInLandingMode：
 *   https://developer.dji.com/api-reference-v5/android-api/Components/IKeyManager/Key_FlightController_FlightControllerKey.html
 * - BatteryKey.KeyChargeRemainingInPercent / GimbalKey.KeyGimbalAttitude / RemoteControllerKey.KeyConnection：
 *   BatteryKey / GimbalKey / RemoteControllerKey 的 API Reference 页面（同 API Reference 站点）。
 * - 官方 sample 的 Key 用法（create()/get(default)/listen(holder)）：
 *   WayPointV3VM.kt / VirtualStickVM.kt（github.com/dji-sdk/Mobile-SDK-Android-V5）
 *
 * 未执行边界：本机无真机，所有读数均为"设计值"，未与真实飞机比对。
 * TODO(未确认)：Attitude/Velocity3D 构造参数顺序以 API Reference 为准；AirLinkKey 链路质量 Key 名未核实。
 */
object TelemetryPublisher {

    private const val TAG = "TelemetryPublisher"

    // Key 只创建一次并复用（官方 sample 模式）
    private val aircraftLocation = FlightControllerKey.KeyAircraftLocation.create()
    private val altitudeKey = FlightControllerKey.KeyAltitude.create()
    private val takeoffAltKey = FlightControllerKey.KeyTakeoffLocationAltitude.create()
    private val homeLocationKey = FlightControllerKey.KeyHomeLocation.create()
    private val velocityKey = FlightControllerKey.KeyAircraftVelocity.create()
    private val flightModeKey = FlightControllerKey.KeyFlightMode.create()
    private val satelliteKey = FlightControllerKey.KeyGPSSatelliteCount.create()
    private val gpsLevelKey = FlightControllerKey.KeyGPSSignalLevel.create()
    private val isFlyingKey = FlightControllerKey.KeyIsFlying.create()
    private val isFailsafeKey = FlightControllerKey.KeyIsFailsafe.create()
    private val goHomeStatusKey = FlightControllerKey.KeyGoHomeStatus.create()
    private val isLandingKey = FlightControllerKey.KeyIsInLandingMode.create()
    private val batteryKey = BatteryKey.KeyChargeRemainingInPercent.create()
    private val gimbalAttitudeKey = GimbalKey.KeyGimbalAttitude.create()
    private val rcConnectionKey = RemoteControllerKey.KeyConnection.create()

    fun startListening(holder: Any) {
        // 关键遥测做长监听，避免 getValue 缓存为空；/v1/telemetry 仍以同步读为准
        listenKey(holder, aircraftLocation)
        listenKey(holder, altitudeKey)
        listenKey(holder, homeLocationKey)
        listenKey(holder, velocityKey)
        listenKey(holder, flightModeKey)
        listenKey(holder, satelliteKey)
        listenKey(holder, isFlyingKey)
        listenKey(holder, isFailsafeKey)
        listenKey(holder, goHomeStatusKey)
        listenKey(holder, batteryKey)
        listenKey(holder, gimbalAttitudeKey)
        listenKey(holder, rcConnectionKey)
    }

    fun stopListening(holder: Any) {
        try {
            KeyManager.getInstance().cancelListen(holder)
        } catch (t: Throwable) {
            Log.w(TAG, "cancelListen failed: " + t.message)
        }
    }

    fun snapshot(): TelemetrySnapshot {
        val loc = read(aircraftLocation, LocationCoordinate2D(0.0, 0.0))
        val home = read(homeLocationKey, LocationCoordinate2D(0.0, 0.0))
        val altRel = read(altitudeKey, 0.0)
        val takeoffAlt = read(takeoffAltKey, 0.0)
        val vel = read(velocityKey, Velocity3D(0.0, 0.0, 0.0))
        val gimbal = read(gimbalAttitudeKey, Attitude(0.0, 0.0, 0.0))
        val level = read(gpsLevelKey, GPSSignalLevel.LEVEL_NONE)
        val sats = read(satelliteKey, 0)
        val battery = read(batteryKey, 0)
        val rc = read(rcConnectionKey, false)
        val flying = read(isFlyingKey, false)
        val failsafe = read(isFailsafeKey, false)
        val goHome = read(goHomeStatusKey, GoHomeState.IDLE)
        val landing = read(isLandingKey, false)
        val flightMode = read(flightModeKey, FlightMode.UNKNOWN)

        val speed = Math.hypot(vel.x, vel.y)
        val state = deriveState(flying, failsafe, goHome, landing)

        return TelemetrySnapshot(
            ts = BridgeRuntime.nowIso(),
            // real 模式没有"仿真秒"；spec 的 sim_time_s 在 real 返回 null（PROTOCOL_COMPLIANCE.md §2.1）
            simTimeS = null,
            state = state,
            lat = loc.latitude,
            lon = loc.longitude,
            altRelM = altRel,
            altAbsM = takeoffAlt + altRel,
            speedMps = speed,
            verticalSpeedMps = vel.z,
            batteryPct = battery.toDouble(),
            gimbalPitch = gimbal.pitch,
            gimbalYaw = gimbal.yaw,
            gimbalRoll = gimbal.roll,
            gpsFix = gpsFix(level),
            gpsSatellites = sats,
            rcConnected = rc,
            signal = if (rc) "good" else "lost", // TODO(未确认)：AirLinkKey 链路质量 Key 名未核实
            mode = BridgeRuntime.mode,
            missionId = BridgeRuntime.currentMissionId,
            homeLat = home.latitude,
            homeLon = home.longitude,
            homeAltAbsM = takeoffAlt
        ).also {
            BridgeRuntime.setState(state)
            Log.v(TAG, "state=" + state + " flightMode=" + flightMode + " battery=" + battery)
        }
    }

    private fun deriveState(
        flying: Boolean,
        failsafe: Boolean,
        goHome: GoHomeState,
        landing: Boolean
    ): String = when {
        failsafe -> "failsafe"
        goHome == GoHomeState.RETURNING_TO_HOME -> "returning"
        goHome == GoHomeState.LANDING || landing -> "landing"
        BridgeRuntime.missionActive -> "mission"
        BridgeRuntime.state == "taking_off" -> "taking_off"
        BridgeRuntime.state == "aborted" -> "aborted"
        flying -> "hovering"
        else -> "idle"
    }

    /** GPSSignalLevel 映射为 spec 的 gps.fix（>=3 视为可起飞）。MSDK 5.10.0 起该枚举 deprecated。
     *  TODO(未确认)：官方建议改用 getPositioningSolution 获取定位解状态，真机阶段按实际 API 替换。 */
    private fun gpsFix(level: GPSSignalLevel?): Int = when (level) {
        null, GPSSignalLevel.LEVEL_NONE, GPSSignalLevel.LEVEL_0 -> 0
        GPSSignalLevel.LEVEL_1 -> 1
        GPSSignalLevel.LEVEL_2 -> 2
        GPSSignalLevel.LEVEL_3 -> 3
        GPSSignalLevel.LEVEL_4 -> 4
        GPSSignalLevel.LEVEL_5 -> 5
        GPSSignalLevel.LEVEL_10 -> 6
        else -> 0
    }

    /** 同步读缓存值；任何异常返回默认值，保证 /v1/telemetry 永不抛异常。 */
    private fun <T> read(key: DJIKey<T>, default: T): T = try {
        KeyManager.getInstance().getValue(key, default) ?: default
    } catch (t: Throwable) {
        Log.w(TAG, "get " + key + " failed: " + t.message)
        default
    }

    private fun <T> listenKey(holder: Any, key: DJIKey<T>) {
        try {
            key.listen(holder) { _, _ -> }
        } catch (t: Throwable) {
            Log.w(TAG, "listen failed on " + key + ": " + t.message)
        }
    }
}
