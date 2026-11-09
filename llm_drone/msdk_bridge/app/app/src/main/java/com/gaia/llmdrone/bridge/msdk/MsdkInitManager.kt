package com.gaia.llmdrone.bridge.msdk

import android.content.Context
import android.util.Log
import dji.common.error.DJIError
import dji.v5.common.error.IDJIError
import dji.v5.common.register.DJISDKInitEvent
import dji.v5.common.register.InitSettings
import dji.v5.common.register.SDKLinKMode
import dji.v5.manager.SDKManager
import dji.v5.manager.interfaces.SDKManagerCallback

/**
 * MSDK v5 初始化 + App Key 注册。
 *
 * 官方依据（一手）：
 * - ISDKManager.init(Context, InitSettings, SDKManagerCallback)，MSDK 5.20.1 起；旧签名已 @Deprecated：
 *   https://developer.dji.com/api-reference-v5/android-api/Components/SDKManager/DJISDKManager.html
 * - registerApp() 必须在 onInitProcess 回调 DJISDKInitEvent.INITIALIZE_COMPLETE 之后调用；
 *   成功/失败通过 SDKManagerCallback.onRegisterSuccess/onRegisterFailure 返回。
 * - 官方 sample 调用序列（SDKManager.getInstance().init(...); ... registerApp()）：
 *   https://raw.githubusercontent.com/dji-sdk/Mobile-SDK-Android-V5/dev-sdk-main/SampleCode-V5/android-sdk-v5-sample/src/main/java/dji/sampleV5/aircraft/models/MSDKManagerVM.kt
 *
 * 说明（未执行）：本机无 Android SDK/真机，未编译、未联网注册，未验证 App Key 回调。
 */
object MsdkInitManager {

    private const val TAG = "MsdkInitManager"

    @Volatile var isRegistered: Boolean = false
        private set
    @Volatile var isProductConnected: Boolean = false
        internal set
    @Volatile var aircraftModel: String = ""
        internal set
    @Volatile var initComplete: Boolean = false
        private set
    @Volatile var lastError: String? = null
        private set

    @Volatile private var initialized = false

    fun init(appContext: Context) {
        if (initialized) return
        initialized = true

        val settings = InitSettings(SDKLinKMode.LOCAL) // 5.20.1 新增；LOCAL=本机直连遥控器
        SDKManager.getInstance().init(appContext, settings, object : SDKManagerCallback {
            override fun onRegisterSuccess() {
                isRegistered = true
                lastError = null
                Log.i(TAG, "MSDK register success")
            }

            override fun onRegisterFailure(error: IDJIError) {
                isRegistered = false
                lastError = "register failure: " + error
                Log.e(TAG, "MSDK register failure: " + error)
            }

            override fun onProductConnect(productId: Int) {
                isProductConnected = true
                Log.i(TAG, "product connected, id=" + productId)
                AircraftConnectionManager.onProductConnected(productId)
            }

            override fun onProductDisconnect(productId: Int) {
                isProductConnected = false
                aircraftModel = ""
                Log.w(TAG, "product disconnected, id=" + productId)
            }

            override fun onProductChanged(productId: Int) {
                Log.i(TAG, "product changed, id=" + productId)
            }

            override fun onInitProcess(event: DJISDKInitEvent, totalProcess: Int) {
                Log.i(TAG, "init process event=" + event + " total=" + totalProcess)
                if (event == DJISDKInitEvent.INITIALIZE_COMPLETE) {
                    initComplete = true
                    // 官方要求：INITIALIZE_COMPLETE 之后才能 registerApp（联网校验 App Key）
                    SDKManager.getInstance().registerApp()
                }
            }

            // 以下两个回调在 5.20.1 的 sample 中存在；若 AAR 版本不同可能不需要实现
            override fun onDatabaseDownloadProgress(current: Long, total: Long) {
                Log.d(TAG, "database download progress: " + current + "/" + total)
            }

            override fun onRemoteServerStateUpdated(state: dji.open.pilot.client.manager.ServerState) {
                // 仅 REMOTE_PILOT 模式使用；本桥使用 LOCAL 模式
            }

            override fun onRemoteServerCompatibleError(error: IDJIError) {
                Log.w(TAG, "remote server incompatible: " + error)
            }
        })
    }

    fun sdkVersion(): String = try {
        SDKManager.getInstance().sdkVersion
    } catch (t: Throwable) {
        "unknown"
    }

    fun destroy() {
        try {
            SDKManager.getInstance().destroy()
        } catch (t: Throwable) {
            Log.w(TAG, "destroy failed: " + t.message)
        }
        initialized = false
        isRegistered = false
        initComplete = false
    }

    // 兼容旧写法：DJI SDK 部分版本在 callback 里要求 onDatabaseDownloadProgress 的签名带 @Deprecated 标注；
    // 如编译报错请以 MSDK 5.20.1 的 SDKManagerCallback 接口为准调整。
}
