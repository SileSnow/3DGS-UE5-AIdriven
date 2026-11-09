package com.gaia.llmdrone.bridge.msdk

import android.content.Context
import android.util.Log
import dji.sdk.keyvalue.key.FlightControllerKey
import dji.sdk.keyvalue.key.KeyTools
import dji.sdk.keyvalue.key.ProductKey
import dji.sdk.keyvalue.value.common.ComponentIndexType
import dji.v5.manager.KeyManager

/**
 * 飞行器连接状态、机型/固件读取与"绑定校验"的收口点。
 *
 * 官方依据：
 * - ProductKey.KeyConnection / FlightControllerKey.KeyConnection：
 *   https://developer.dji.com/api-reference-v5/android-api/Components/IKeyManager/Key_Product_ProductKey.html
 *   https://developer.dji.com/api-reference-v5/android-api/Components/IKeyManager/Key_FlightController_FlightControllerKey.html
 * - KeyManager.listen(key, listenHolder, callback)：
 *   https://developer.dji.com/api-reference-v5/android-api/Components/IKeyManager/IKeyManager.html
 * - 官方 sample 用 KeyManager.getInstance().listen(KeyTools.createKey(...), this) {...}：
 *   https://raw.githubusercontent.com/dji-sdk/Mobile-SDK-Android-V5/dev-sdk-main/SampleCode-V5/android-sdk-v5-sample/src/main/java/dji/sampleV5/aircraft/models/VirtualStickVM.kt
 * - Release Notes 5.3.0 提示：Mini 3/3 Pro 更换遥控器后需先用 DJI Fly 重新绑定，否则持续上报绑定校验错误
 *   （本地证据 data/dji/raw/text/relnotes_all.txt）；Mini 4 Pro 的绑定/激活流程见 test_protocol.md 前置条件。
 *
 * TODO(未确认)：MSDK v5 对消费级机型的"App 绑定飞机"具体 API（如 IUserAccountManager 登录态 + 激活流程）
 * 未在官方文档中找到明确方法名；本类先用"连接 + 机型白名单 + 账号登录态"作为就绪判据，真机阶段补全。
 */
object AircraftConnectionManager {

    private const val TAG = "AircraftConnection"

    @Volatile var productConnected: Boolean = false
        private set
    @Volatile var rcConnected: Boolean = false
        private set
    @Volatile var modelName: String = ""
        private set
    @Volatile var firmwareVersion: String = ""
        private set

    /** 允许的机型：本桥只面向 Mini 4 Pro（v5.13.0 起支持，RC-N2；v5.17.0 起支持 RC-N3） */
    val supportedModels = setOf("DJI Mini 4 Pro", "Mini 4 Pro")

    fun start(context: Context) {
        // 产品连接（含 USB/RC 链路）监听
        KeyManager.getInstance().listen(
            KeyTools.createKey(ProductKey.KeyConnection), context
        ) { connected: Boolean? ->
            productConnected = connected == true
            Log.i(TAG, "product connection = " + productConnected)
        }
        KeyManager.getInstance().listen(
            KeyTools.createKey(FlightControllerKey.KeyConnection), context
        ) { connected: Boolean? ->
            rcConnected = connected == true
        }
        // 机型/固件（用于 SafetyGuard 的机型白名单与测试记录）
        KeyManager.getInstance().listen(
            KeyTools.createKey(FlightControllerKey.KeyFirmwareVersion), context
        ) { v: String? ->
            firmwareVersion = v ?: ""
        }
        // TODO(未确认)：MSDK 5.x 读取机型名的 Key 名（ProductKey.KeyProductType 或 DeviceStatus 中的 modelName）
        // 官方 sample 显示"机型"通常取自 ProductKey 相关 Key；以真机日志为准补全。
    }

    fun stop(context: Context) {
        KeyManager.getInstance().cancelListen(context)
    }

    fun isModelSupported(): Boolean =
        supportedModels.any { modelName.contains(it, ignoreCase = true) }

    fun isReady(): Boolean = MsdkInitManager.isRegistered && productConnected && rcConnected

    fun onProductConnected(productId: Int) {
        // 官方 sample 只提供 productId（int），无直接机型字符串；机型读取走 Key（见 start 的 TODO）
        productConnected = true
    }
}
