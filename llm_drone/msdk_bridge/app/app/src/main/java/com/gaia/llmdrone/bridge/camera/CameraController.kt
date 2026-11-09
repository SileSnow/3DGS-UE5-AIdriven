package com.gaia.llmdrone.bridge.camera

import android.util.Log
import dji.sdk.keyvalue.key.CameraKey
import dji.sdk.keyvalue.key.KeyTools
import dji.sdk.keyvalue.value.camera.CameraMode
import dji.sdk.keyvalue.value.common.ComponentIndexType
import dji.v5.common.callback.CommonCallbacks
import dji.v5.common.error.IDJIError
import dji.v5.manager.KeyManager
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/**
 * 相机控制：拍照（单拍/连拍/定时连拍）、录像开始/停止。
 *
 * 官方依据：
 * - CameraKey.KeyCameraMode / KeyStartShootPhoto / KeyStartRecord / KeyStopRecord / KeyIsShootingPhoto /
 *   KeyCameraStoringFile：https://developer.dji.com/api-reference-v5/android-api/Components/IKeyManager/Key_Camera_CameraKey.html
 * - 官方 sample 的调用（KeyCameraMode setValue + KeyStartShootPhoto performAction）：
 *   https://raw.githubusercontent.com/dji-sdk/Mobile-SDK-Android-V5/dev-sdk-main/SampleCode-V5/android-sdk-v5-sample/src/main/java/dji/sampleV5/aircraft/models/MediaVM.kt
 *
 * 未执行边界：未编译、未接真机；连拍间隔为桥接层定时器实现（便于逐张记录遥测），未使用官方定时连拍 Key。
 */
object CameraController {

    private const val TAG = "CameraController"
    private val cameraIndex = ComponentIndexType.LEFT_OR_MAIN // Mini 4 Pro 单主摄

    suspend fun capture(count: Int, intervalS: Double): Result<Unit> {
        val n = count.coerceIn(1, 20)
        val intervalMs = (intervalS.coerceIn(0.0, 10.0) * 1000).toLong()
        setPhotoMode()
        repeat(n) { i ->
            val r = performCameraAction(KeyTools.createKey(CameraKey.KeyStartShootPhoto, cameraIndex), "shootPhoto#" + i)
            if (r.isFailure) return r
            if (i < n - 1 && intervalMs > 0) delay(intervalMs)
        }
        // 等待写入存储（简化：固定等待；生产应轮询 KeyCameraStoringFile）
        delay(500L)
        return Result.success(Unit)
    }

    suspend fun startVideo(): Result<Unit> {
        setVideoMode()
        return performCameraAction(KeyTools.createKey(CameraKey.KeyStartRecord, cameraIndex), "startRecord")
    }

    suspend fun stopVideo(): Result<Unit> =
        performCameraAction(KeyTools.createKey(CameraKey.KeyStopRecord, cameraIndex), "stopRecord")

    private suspend fun setPhotoMode() {
        setCameraMode(CameraMode.PHOTO_NORMAL)
    }

    private suspend fun setVideoMode() {
        setCameraMode(CameraMode.VIDEO_NORMAL)
    }

    private suspend fun setCameraMode(mode: CameraMode) {
        val key = KeyTools.createKey(CameraKey.KeyCameraMode, cameraIndex)
        try {
            KeyManager.getInstance().setValue(key, mode, object : CommonCallbacks.CompletionCallback {
                override fun onSuccess() {}
                override fun onFailure(error: IDJIError) { Log.w(TAG, "set camera mode failed: " + error) }
            })
        } catch (t: Throwable) {
            Log.w(TAG, "set camera mode exception: " + t.message)
        }
    }

    private suspend fun performCameraAction(
        key: dji.sdk.keyvalue.key.DJIKey.ActionKey<dji.sdk.keyvalue.value.common.EmptyMsg, dji.sdk.keyvalue.value.common.EmptyMsg>,
        where: String
    ): Result<Unit> = suspendCancellableCoroutine { cont ->
        try {
            KeyManager.getInstance().performAction(key, object :
                CommonCallbacks.CompletionCallbackWithParam<dji.sdk.keyvalue.value.common.EmptyMsg> {
                override fun onSuccess(t: dji.sdk.keyvalue.value.common.EmptyMsg?) {
                    cont.resume(Result.success(Unit))
                }
                override fun onFailure(error: IDJIError) {
                    cont.resume(Result.failure(IllegalStateException(where + ": " + error)))
                }
            })
        } catch (t: Throwable) {
            cont.resume(Result.failure(t))
        }
    }
}
