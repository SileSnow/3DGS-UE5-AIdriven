package com.gaia.llmdrone.bridge

import android.app.Application
import android.util.Log
import com.gaia.llmdrone.bridge.msdk.MsdkInitManager

/**
 * 应用入口：先安装 DJI 的 Helper，再初始化 MSDK。
 *
 * 官方依据（官方 sample V5.20.1）：
 * - DJIAircraftApplication.attachBaseContext 中调用 Helper.install(this)：
 *   https://raw.githubusercontent.com/dji-sdk/Mobile-SDK-Android-V5/dev-sdk-main/SampleCode-V5/android-sdk-v5-sample/src/main/java/dji/sampleV5/aircraft/DJIAircraftApplication.kt
 *   该文件原文：com.cySdkyc.clx.Helper.install(this)
 * - DJIApplication.onCreate 中初始化 MSDK（官方 sample 走 ViewModel，本骨架收敛到 MsdkInitManager）：
 *   https://raw.githubusercontent.com/dji-sdk/Mobile-SDK-Android-V5/dev-sdk-main/SampleCode-V5/android-sdk-v5-sample/src/main/java/dji/sampleV5/aircraft/models/MSDKManagerVM.kt
 *
 * TODO(未确认)：Helper 在官方文档中未给出稳定类名，官方 sample 使用混淆类 com.cySdkyc.clx.Helper；
 * 若工程不引入 uxsdk（本骨架未引入），先按注释行启用并真机验证 MSDK 初始化是否仍成功。
 */
class DJIApplication : Application() {

    override fun attachBaseContext(base: android.content.Context?) {
        super.attachBaseContext(base)
        try {
            // 与官方 sample 完全一致（混淆类）；若 AAR 升级后类名变化，改为 dji.v5.ux.util.Helper.install(this) 并引入 uxsdk
            com.cySdkyc.clx.Helper.install(this)
        } catch (t: Throwable) {
            Log.e(TAG, "DJI Helper.install failed: " + t.message)
        }
    }

    override fun onCreate() {
        super.onCreate()
        // SDKManager.init + registerApp 必须最先执行；registerApp 在 INITIALIZE_COMPLETE 后调用（见 MsdkInitManager）
        MsdkInitManager.init(this)
    }

    companion object {
        private const val TAG = "DJIApplication"
    }
}
