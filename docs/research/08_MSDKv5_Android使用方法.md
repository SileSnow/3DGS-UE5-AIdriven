# 08 MSDK v5（Android）控制 DJI Mini 3 / 3 Pro / 4 Pro —— code-level 使用指南

> 调研日期：2026-11-08（Asia/Shanghai）。本文件只写"怎么用/代码级"，机型能力矩阵见 01。每条关键 API 均标注「来源 URL + 本地证据文件」；无法从一手资料确认的内容标 `TODO(未确认)`，不编造。
> 证据根目录：`dji_ue5_3dgs/data/dji/raw/`（本次新增 `api_v5/`、`msdkv5_sample/`；已有 `text/relnotes_all.txt` 等）。
> 目标读者：本项目 `llm_drone` Phase-2 Android 桥开发者。

## 0. 一页速查

| 项 | 结论 | 证据 |
|---|---|---|
| 适用机型 | Mini 3 / Mini 3 Pro（v5.3.0 起）、Mini 4 Pro（v5.13.0 起；RC-N3 自 v5.17.0） | 01 文档；`data/dji/raw/text/relnotes_all.txt` |
| 平台 | 仅 Android；MSDK V5 无 iOS 发布 | `data/dji/raw/dev_msdk_en.html` |
| 最新版本 | 5.20.1（2026-11-05），仅支持 arm64-v8a | `data/dji/raw/api_v5/repo_README.md` |
| 最低环境 | Android Studio Narwhal 3 Feature Drop / JDK 17 / Kotlin 2.1.0 / Gradle 8.12 / AGP 8.7.0 / minSdk 24 / targetSdk 35 | `.../msdkv5_docs_extracted/v-dadb0ffc.07ff76f1.js.txt`（"移植到空白工程"页） |
| Maven 坐标 | `implementation 'com.dji:dji-sdk-v5-aircraft:5.20.1'`、`compileOnly 'com.dji:dji-sdk-v5-aircraft-provided:5.20.1'`、`runtimeOnly 'com.dji:dji-sdk-v5-networkImp:5.20.1'` | `data/dji/raw/api_v5/repo_README.md`；`.../msdkv5_sample/...dependencies.gradle` |
| 遥控器 | RC-N2（v5.13.0 起）、RC-N3（v5.17.0 起）；带屏 DJI RC 2 不支持 MSDK | relnotes 5.13.0/5.17.0；dronedj[二级]见 01 |
| 初始化入口 | `SDKManager.getInstance().init(context, InitSettings(SDKLinKMode.LOCAL), callback)` → 回调 `INITIALIZE_COMPLETE` 后 `registerApp()` | `api_v5/SDKManager__DJISDKManager.html`；`msdkv5_sample/.../MSDKManagerVM.kt` |
| 核心范式 | 一切参数/动作走 Key：`KeyTools` 创建 Key，`KeyManager` 读写/监听/执行 Action | 迁移文档 `.../v-0acaef9a...txt`；`api_v5/IKeyManager__IKeyManager.html` |

## 1. 版本矩阵与硬约束

| 机型 | 首个支持版本 | 发布日期 | 遥控器/固件（发布时） | 证据 |
|---|---|---|---|---|
| Mini 3 | v5.3.0 | 2023-04-07 | RC N1，飞机 01.00.05.00，RC 04.16.05.00 | relnotes 5.3.0 / 5.13.0 固件表 |
| Mini 3 Pro | v5.3.0 | 2023-04-07 | RC N1 / RC Pro，01.00.09.00 / 04.14.07.00 / 03.02.09.00 | 同上 |
| Mini 4 Pro | v5.13.0 | 2025-03-17 | 仅 RC N2：飞机 01.00.0800、RC 01.01.0300 | relnotes 5.13.0 |
| Mini 4 Pro（新版） | v5.17.0 加 RC N3 | 2025-11-04 | 最新固件表：飞机 01.00.1100，RC N2/N3 均 01.01.0300 | relnotes 5.17.0 及之后固件表 |

要点：
- v4 与 v5 不兼容（官方原文 "Version 4.X is not compatible with version 5.X"，见 01 与 `.../v-0acaef9a...txt` 的 4.X→5.X 映射表）；Mini 2/SE 只能 v4（见 09），Mini 3/3 Pro/4 Pro 只能 v5。不能共用一套 App 代码。
- v5.10.0 起初始化包名变化：`com.secneo.sdk.Helper.install(this)` → `com.cySdkyc.clx.Helper.install(this)`（relnotes 5.10.0；迁移文档同款代码）。老教程照抄会崩溃。
- v5.17.0 起 Android API 升到 35，必须在 `<application>` 加 `android:extractNativeLibs="true"`（relnotes 5.17.0）。
- Mini 3/3 Pro 更换遥控器后必须先用 DJI Fly 重新绑定，否则持续上报 "binding device mismatch or under verification"（relnotes 5.3.0 原文 Note）。

来源 URL：
- https://developer.dji.com/mobile-sdk/ （产品页，支持的机型/平台）
- https://github.com/dji-sdk/Mobile-SDK-Android-V5 （官方仓库，README=5.20.1）
- https://developer.dji.com/doc/mobile-sdk-tutorial/en/ （官方教程站，SPA，正文已提取到 data/dji/raw/msdkv5_docs_extracted/）

## 2. 开发环境与依赖（可照抄）

推荐环境（官方"移植 MSDK 到空白工程"页原文口径）：Android Studio Narwhal 3 Feature Drop | 2025.1.3、Java Runtime 17、Kotlin 2.1.0、Gradle 8.12、AGP 8.7.0、minSdkVersion 24、targetSdkVersion 35。
本地证据：`data/dji/raw/msdkv5_docs_extracted/v-19a8b384.619f07ec.js.txt`（英）/ `v-dadb0ffc.07ff76f1.js.txt`（中）。

```groovy
// project/build.gradle
buildscript {
  repositories { google(); mavenCentral() }
  dependencies {
    classpath 'com.android.tools.build:gradle:8.7.0'
    classpath "org.jetbrains.kotlin:kotlin-gradle-plugin:$KOTLIN_VERSION"
  }
}
// app/build.gradle
android {
  namespace 'com.example.msdksample'
  compileSdk 35
  defaultConfig {
    minSdk 24
    targetSdk 35
    ndk { abiFilters 'arm64-v8a' }   // MSDK 只支持 arm64-v8a
  }
  packagingOptions {
    pickFirst 'lib/arm64-v8a/libc++_shared.so'
    doNotStrip "*/*/libdjibase.so"           // 官方给的长清单，此处只列示例
    doNotStrip "*/*/libDJICSDKCommon.so"
  }
}
dependencies {
  implementation 'com.dji:dji-sdk-v5-aircraft:5.20.1'
  compileOnly    'com.dji:dji-sdk-v5-aircraft-provided:5.20.1'
  runtimeOnly    'com.dji:dji-sdk-v5-networkImp:5.20.1'   // 无此包所有联网功能不可用，硬件控制仍可用
  // 航线 KMZ 编辑库（官方 Sample 的本地依赖；WPMZ 编辑 API 在 com.dji.wpmzsdk 包）
  implementation 'com.dji:wpmzsdk:1.0.5.2'
}
```
说明：
- 三个 artifact 的分工见官方 README "AAR Explanation"：aircraft=主包；aircraft-provided=仅编译期接口；networkImp=网络能力（注册、账号、部分云能力）。
- `wpmzsdk` 出现在官方 Sample 的 `dependencies.gradle`：`deps.wpmzSdk = 'com.dji:wpmzsdk:1.0.5.2'`，证据 `data/dji/raw/msdkv5_sample/SampleCode-V5__android-sdk-v5-as__dependencies.gradle`；sample 中用法 `com.dji.wpmzsdk.manager.WPMZManager.getInstance().init(ContextUtil.getContext())`（`WayPointV3Fragment.kt` L146）。
- 混淆规则：v5.8.0 起"无需手动添加混淆规则，规则已内置 SDK"（relnotes 5.8.0）。
- 本地证据：`data/dji/raw/api_v5/repo_README.md`、`.../msdkv5_sample/...dependencies.gradle`、`.../msdkv5_sample/...build.gradle`、`.../msdkv5_sample/...gradle.properties`。

## 3. DJI 开发者账号与 App Key

1. 在 https://developer.dji.com/ 注册 DJI 开发者账号（企业/个人均可；App 类型选 Mobile SDK）。
2. User Center → "Create App"：填 App 名称、**Android 包名（applicationId）必须与工程一致**；平台选 Android；生成 App Key。
3. 把 Key 写入 `AndroidManifest.xml`：

```xml
<application android:name=".MyApplication" android:extractNativeLibs="true">
  <meta-data android:name="com.dji.sdk.API_KEY" android:value="你的 App Key" />
</application>
```

4. 注册 API 为**无参** `SDKManager.getInstance().registerApp()`，SDK 从 manifest 读取 App Key；回调经 `SDKManagerCallback.onRegisterSuccess()/onRegisterFailure(IDJIError)` 返回。
   - 签名证据：`data/dji/raw/api_v5/SDKManager__DJISDKManager.html`（`void registerApp()`、`void init(Context, InitSettings, SDKManagerCallback)`、`boolean isRegistered()`、`void destroy()`）。
   - 官方 FAQ/论坛说明 App Key 与包名、签名绑定，包名改后需重新申请（TODO(未确认)：签名证书指纹是否参与校验，未见官方明文）。
5. 未注册会怎样：`isRegistered()==false` 时 Key 读写/动作回调失败；Sample 在 `DJINetworkManager` 网络可用后重试 `registerApp()`（`MSDKManagerVM.kt`）。

## 4. 初始化序列（状态机 + 错误处理）

```kotlin
class MyApplication : Application() {
    override fun attachBaseContext(base: Context?) {
        super.attachBaseContext(base)
        // v5.10.0+ ：com.cySdkyc.clx.Helper；< v5.10.0 ：com.secneo.sdk.Helper
        com.cySdkyc.clx.Helper.install(this)
    }
    override fun onCreate() {
        super.onCreate()
        val settings = InitSettings(SDKLinKMode.LOCAL)   // 普通手机 App 用 LOCAL；Pilot 插件用 REMOTE_PILOT
        SDKManager.getInstance().init(this, settings, object : SDKManagerCallback {
            override fun onInitProcess(event: DJISDKInitEvent, totalProcess: Int) {
                if (event == DJISDKInitEvent.INITIALIZE_COMPLETE) {
                    SDKManager.getInstance().registerApp()   // 无参，从 manifest 读 API_KEY
                }
            }
            override fun onRegisterSuccess() { /* 注册成功，可开始连飞机 */ }
            override fun onRegisterFailure(error: IDJIError) { /* 包名/Key 不匹配、网络不可用等 */ }
            override fun onProductConnect(productId: Int) { /* 飞机（或 RC）已连接 */ }
            override fun onProductDisconnect(productId: Int) { }
            override fun onProductChanged(productId: Int) { }
            override fun onDatabaseDownloadProgress(current: Long, total: Long) { }
        })
    }
}
```

状态机（官方回调定义，`api_v5/SDKManager__ISDKManager_SDKManagerCallback.html`）：

```
init() ──onInitProcess(INITIALIZE_COMPLETE)──► registerApp()
   ▲                                               │
   │                                    onRegisterSuccess / onRegisterFailure(IDJIError)
   │                                               │
   └── destroy()（退后台/退出时释放）        onProductConnect(productId) ── 设备就绪
```

- 错误对象：`IDJIError`（`dji.v5.common.error.IDJIError`），含 errorCode()/description()；`onRegisterFailure` 的常见原因：App Key 与包名不匹配、未联网、设备时间错误。官方未在 MSDK V5 文档中给出公开错误码全表，`TODO(未确认)` 具体枚举。
- `init()` 必须且仅调用一次；`destroy()` 后再 init 可恢复（relnotes 5.18.0 提到 destroy 后的一些监听 bug 修复）。
- 网络监听重试（Sample 写法）：`DJINetworkManager.getInstance().addNetworkStatusListener { available -> if (isInit && available && !isRegistered) registerApp() }`。
- 证据：`msdkv5_sample/.../MSDKManagerVM.kt`（头文件与完整回调）；`.../msdkv5_docs_extracted/v-dadb0ffc...txt`（官方 Quick Start 代码块）。

## 5. 连接链路：RC-N2/RC-N3 + Android 手机 USB

链路：Android 手机 --USB(附件模式)--> RC-N2/RC-N3 --OcuSync--> 飞机。App 运行在手机上；带屏遥控器（DJI RC 2）无法装第三方 App，故不在支持范围（01 文档已论证）。

必备 Manifest（官方移植文档原文）：

```xml
<uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE" />
<uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE" />
<uses-permission android:name="android.permission.RECORD_AUDIO" />
<uses-feature android:name="android.hardware.usb.host" android:required="false" />
<uses-feature android:name="android.hardware.usb.accessory" android:required="true" />
<application ...>
  <meta-data android:name="com.dji.sdk.API_KEY" android:value="your app key" />
</application>
<!-- 主 Activity 内声明 USB 附件广播 -->
<intent-filter>
  <action android:name="android.intent.action.MAIN" />
  <action android:name="android.hardware.usb.action.USB_ACCESSORY_ATTACHED" />
  <category android:name="android.intent.category.LAUNCHER" />
</intent-filter>
<meta-data android:name="android.hardware.usb.action.USB_ACCESSORY_ATTACHED"
           android:resource="@xml/accessory_filter" />
```
- `res/xml/accessory_filter.xml` 声明 DJI 遥控器的 USB accessory manufacturer/model（官方 Sample 资源文件；`TODO(未确认)`：如果你只做一个 App，可先用官方 Sample 的同名资源，避免手写错）。
- 运行时权限：Android 6+ 需动态申请存储/录音（用于媒体下载与录像）；USB 附件权限由系统弹窗授权（`UsbManager`），部分机型需在开发者选项/USB 配置中允许"USB 附件"。
- 连接成功判定：`SDKManagerCallback.onProductConnect(productId)` + `KeyTools.createKey(ProductKey.KeyConnection)` 或 `FlightControllerKey.KeyConnection`（v5 用各模块 KeyConnection 替代 v4 的 onComponentChange，见 4.X→5.X 迁移文档）。
- 固件要求：≥ 对应版本发布时固件表（见第 1 节）；固件过旧会导致 Key 不可用/相机控制失败。官方固件表 URL：https://developer.dji.com/doc/mobile-sdk-tutorial/en/ 的 Release Notes 页。
- 绑定校验：Mini 3/3 Pro 换遥控器后须用 DJI Fly 重新绑定（relnotes 5.3.0）；否则 App 反复收到绑定校验错误。

## 6. 模块 API 表 + 可审阅代码

统一范式：`KeyTools` 创建 Key → `KeyManager` 读写/监听/动作。方法签名（接口页原文）：
- `@Nullable <R> R getValue(DJIKey<R> key)`
- `<P> void setValue(DJIKey<P> key, P param, CommonCallbacks.CompletionCallback callback)`
- `<R> void performAction(DJIKey.ActionKey<?,R> key, CommonCallbacks.CompletionCallbackWithParam<R> callback)`
- `<P,R> void performAction(DJIKey.ActionKey<P,R> key, P param, CompletionCallbackWithParam<R> callback)`
- `<R> void listen(DJIKey<R> key, Object listenHolder, CommonCallbacks.KeyListener<R> callback)`
- `void cancelListen(Object listenHolder)`
证据：`data/dji/raw/api_v5/IKeyManager__IKeyManager.html`；创建入口 `KeyTools`（`api_v5/IKeyManager__KeyTools.html`）；回调 `api_v5/DJICommonCallbacks__DJICommonCallbacks_CompletionCallback.html`。

| 模块 | 入口类（真实 import） | 关键 API | 证据 |
|---|---|---|---|
| SDK 管理 | `dji.v5.manager.SDKManager` / `dji.v5.manager.interfaces.SDKManagerCallback` | init/registerApp/isRegistered/destroy | `api_v5/SDKManager__DJISDKManager.html`、`.../MSDKManagerVM.kt` |
| Key | `dji.v5.manager.KeyManager`、`dji.sdk.keyvalue.key.KeyTools` | getValue/setValue/performAction/listen/cancelListen | `api_v5/IKeyManager__*.html` |
| 飞控 | Key: `dji.sdk.keyvalue.key.FlightControllerKey` | 起降/返航/电机/Home 点/高度限值/状态 | `api_v5/IKeyManager__Key_FlightController_FlightControllerKey.html` |
| 航线 | `dji.v5.manager.aircraft.waypoint3.WaypointMissionManager`（单例 getInstance） | pushKMZFileToAircraft/startMission/pause/resume/stop/查询断点/监听 | `api_v5/IWaypointMissionManager__IWaypointMissionManager.html` |
| KMZ 编辑 | `com.dji.wpmzsdk.manager.WPMZManager`（wpmzsdk 库） | init/getKMZInfo/generateKMZFile/checkValidation/transKMLtoKMZ | `api_v5/IWaypointMissionManager__IWPMZManager.html`、`WayPointV3Fragment.kt` |
| 相机 | Key: `dji.sdk.keyvalue.key.CameraKey` | 拍照/录像/曝光/ISO/快门/间隔拍照/视频分辨率/变焦 | `api_v5/IKeyManager__Key_Camera_CameraKey.html`、`MediaVM.kt` |
| 云台 | Key: `dji.sdk.keyvalue.key.GimbalKey` | KeyGimbalAttitude / KeyRotateByAngle / KeyRotateBySpeed / KeyGimbalReset / KeyGimbalCalibrate | `api_v5/IKeyManager__Key_Gimbal_GimbalKey.html` |
| 媒体 | `dji.v5.manager.datacenter.MediaDataCenter`（`.mediaManager`） | enable/pullMediaFileListFromCamera/download/playVideoToSurface/delete | `api_v5/IMediaDataCenter__IMediaManager.html`、`MediaVM.kt` |
| 遥测 | Key 监听（FlightControllerKey/BatteryKey/RemoteControllerKey + `KeyManager.listen`） | 位置/姿态/速度/高度/GPS/电量/链路 ≤10Hz | `api_v5/*.html`、`.../text/msdk_introduction.txt` |
| 虚拟摇杆 | `dji.v5.manager.aircraft.virtualstick.VirtualStickManager`（单例） | enableVirtualStick/disable/leftStick/rightStick/sendVirtualStickAdvancedParam | `api_v5/IVirtualStickManager__*.html`、`VirtualStickVM.kt` |
| 图传 | `MediaDataCenter.getInstance().cameraStreamManager`（ICameraStreamManager，v5.8.0 起替代 IVideoStreamManager） | putCameraStreamSurface/removeCameraStreamSurface/addFrameListener | `api_v5/IMediaDataCenter__ICameraStreamManager.html` |
| 智能飞行 | `IIntelligentFlightManager`（v5.14.0，Mini 4 Pro 在支持列表） | POI/spotlight/flyTo | `api_v5/IIntelligentFlightManager__IIntelligentFlightManager.html`、relnotes 5.14.0 |

### 6.1 飞控（起飞/降落/返航/电机/状态）

```kotlin
import dji.sdk.keyvalue.key.FlightControllerKey
import dji.sdk.keyvalue.key.KeyTools
import dji.v5.common.callback.CommonCallbacks
import dji.v5.et.action        // Kotlin 扩展：ActionKey.action(...)
import dji.v5.et.create        // Kotlin 扩展：DJIKeyInfo.create()
import dji.v5.manager.KeyManager

// 关键：v5 没有 IFlightController 类，飞控动作是 FlightControllerKey 的 ActionKey
fun takeoff(cb: CommonCallbacks.CompletionCallbackWithParam<EmptyMsg>) {
    FlightControllerKey.KeyStartTakeoff.create().action(
        { r -> cb.onSuccess(r) },
        { e: IDJIError -> cb.onFailure(e) }
    )
}
fun land(cb: CommonCallbacks.CompletionCallbackWithParam<EmptyMsg>) =
    FlightControllerKey.KeyStartAutoLanding.create().action({ cb.onSuccess(it) }, { cb.onFailure(it) })
fun rth(cb: CommonCallbacks.CompletionCallbackWithParam<EmptyMsg>) =
    FlightControllerKey.KeyStartGoHome.create().action({ cb.onSuccess(it) }, { cb.onFailure(it) })

// 遥测：getValue 同步读（有缓存），listen 异步推送
val loc = KeyManager.getInstance()
    .getValue(KeyTools.createKey(FlightControllerKey.KeyAircraftLocation), LocationCoordinate2D(0.0, 0.0))
KeyManager.getInstance().listen(
    KeyTools.createKey(FlightControllerKey.KeyAircraftVelocity), this
) { _: Velocity3D?, v: Velocity3D? -> /* 处理速度 */ }
KeyManager.getInstance().listen(
    KeyTools.createKey(FlightControllerKey.KeyAreMotorsOn), this
) { _, on: Boolean? -> /* 电机状态 */ }
```
- 代码依据：`msdkv5_sample/.../BasicAircraftControlVM.kt`（KeyStartTakeoff/KeyStartAutoLanding 均用 `.create().action`）；`WayPointV3VM.kt`（KeyTool.createKey + getValue + listen）；Key 定义与描述见 `api_v5/IKeyManager__Key_FlightController_FlightControllerKey.html`。
- 关键 Key（类型→含义，官方原文）：`KeyStartTakeoff`(DJIActionKeyInfo<EmptyMsg,EmptyMsg>)、`KeyStartAutoLanding`、`KeyConfirmLanding`（0.7m 悬停待确认）、`KeyStartGoHome`、`KeyStopGoHome`、`KeyAreMotorsOn`(Boolean)、`KeyHomeLocation`(LocationCoordinate2D)、`KeyHomeLocationUsingCurrentAircraftLocation`(Action)、`KeyAircraftLocation`(LocationCoordinate2D)、`KeyAircraftAttitude`(Attitude)、`KeyAircraftVelocity`(Velocity3D, NED)、`KeyAltitude`(Double)、`KeyGPSSatelliteCount`(Integer)、`KeyGPSSignalLevel`(GPSSignalLevel)、`KeyFlightMode`(FlightMode)、`KeyGoHomeHeight`(Integer,settable)、`KeyHeightLimit`(Integer,settable)、`KeyIsFlying`(Boolean)、`KeyIsLandingConfirmationNeeded`(Boolean)、`KeyLowBatteryRTHInfo`。
- 限制：起飞需电机未启动；GPS 差时 `KeyStartGoHome` 会失败；Mini 系列无 `KeyPropellerRotation`/慢转桨（relnotes 5.15.0 仅 Matrice 400）。

### 6.2 航线任务（KMZ/WPML 上传、执行、暂停、恢复、状态机）

```kotlin
import dji.v5.manager.aircraft.waypoint3.WaypointMissionManager
import dji.v5.manager.aircraft.waypoint3.WaypointMissionExecuteStateListener
import dji.v5.manager.aircraft.waypoint3.WaylineExecutingInfoListener
import dji.v5.manager.aircraft.waypoint3.WaypointActionListener
import dji.v5.manager.aircraft.waypoint3.model.WaypointMissionExecuteState
import dji.v5.manager.aircraft.waypoint3.model.BreakPointInfo
import dji.v5.common.callback.CommonCallbacks

val wpm = WaypointMissionManager.getInstance()
// 1) 上传 KMZ 到飞机（带进度 0.0~1.0）
wpm.pushKMZFileToAircraft(kmzPath, object : CommonCallbacks.CompletionCallbackWithProgress<Double> {
    override fun onProgressUpdate(p: Double) { /* 进度 */ }
    override fun onSuccess() {
        // 2) 取该 KMZ 内的 waylineId，再按 waylineId 执行
        val ids: List<Int> = WaypointMissionManager.getInstance().getAvailableWaylineIDs(kmzPath)
        wpm.startMission(kmzPath, ids, object : CommonCallbacks.CompletionCallback {
            override fun onSuccess() {}
            override fun onFailure(e: IDJIError) {}
        })
    }
    override fun onFailure(e: IDJIError) {}
})
// 暂停/恢复/停止
wpm.pauseMission(cb); wpm.resumeMission(cb); wpm.stopMission(kmzPath, cb)
// 断点续飞：仅 M30/M3E/3T/3M 保证支持（官方原文），Mini 系列不在列表
wpm.queryBreakPointInfoFromAircraft(kmzPath, object : CommonCallbacks.CompletionCallbackWithParam<BreakPointInfo> {
    override fun onSuccess(bp: BreakPointInfo?) { wpm.startMission(kmzPath, bp!!, cb) }
    override fun onFailure(e: IDJIError) {}
})
// 状态监听
wpm.addWaypointMissionExecuteStateListener(object : WaypointMissionExecuteStateListener {
    // 官方接口签名：void onMissionStateUpdate(WaypointMissionExecuteState missionState)
    override fun onMissionStateUpdate(state: WaypointMissionExecuteState) { /* READY/EXECUTING/PAUSED/FINISHED... */ }
})
wpm.addWaylineExecutingInfoListener(object : WaylineExecutingInfoListener {
    override fun onWaylineExecutingInfoUpdate(info: WaylineExecutingInfo) { /* 当前航点/进度 */ }
    // default 方法（v5.3.0 起）：航线执行中断原因
    override fun onWaylineExecutingInterruptReasonUpdate(error: IDJIError) { /* 中断原因 */ }
})
wpm.addWaypointActionListener(object : WaypointActionListener {
    // 5.6.0 起推荐 (actionGroup, actionId) 重载；旧的 (actionId) 重载已 @Deprecated
    override fun onExecutionStart(actionGroup: Int, actionId: Int) {}
    override fun onExecutionFinish(actionGroup: Int, actionId: Int, error: IDJIError?) {}
})
```
- WaylineExecutingInfo 提供 getMissionFileName() / getWaylineID() / getCurrentWaypointIndex()（官方类页原文），可直接映射本项目 mission 进度。
- 监听器签名（各自接口页原文，均已核对）：WaypointMissionExecuteStateListener.onMissionStateUpdate(WaypointMissionExecuteState)；WaylineExecutingInfoListener.onWaylineExecutingInfoUpdate(WaylineExecutingInfo) + default onWaylineExecutingInterruptReasonUpdate(IDJIError)；WaypointActionListener.onExecutionStart(int actionGroup, int actionId) / onExecutionFinish(int actionGroup, int actionId, IDJIError)（旧的单参重载已 @Deprecated）。
- 方法签名原文（`api_v5/IWaypointMissionManager__IWaypointMissionManager.html`）：`pushKMZFileToAircraft(String, CompletionCallbackWithProgress<Double>)`、`startMission(String, List<Integer>, CompletionCallback)`、`startMission(String, BreakPointInfo, CompletionCallback)`、`pauseMission`、`resumeMission`、`stopMission(String, CompletionCallback)`、`getAvailableWaylineIDs(String)`、`queryBreakPointInfoFromAircraft(String, CompletionCallbackWithParam<BreakPointInfo>)`；监听器 `addWaypointMissionExecuteStateListener` / `addWaylineExecutingInfoListener` / `addWaypointActionListener`。
- 流程依据：官方 "Wayline Management" 页（`data/dji/raw/text/waypoint.txt`）+ Sample `WayPointV3VM.kt` / `WayPointV3Fragment.kt`。官方原文："A wayline file ... 上传-执行-暂停-恢复-监控"，断点续飞 "supported on Matrice 30/30T, Mavic 3E/3T/3M"。
- KMZ 生成：`WPMZManager`（见 10 文档）；上传前建议 `checkValidation(kmzPath)` 静态检查。
- 错误码：`IDJIError` 无公开全表；`WaypointMissionExecuteState` 枚举可区分 READY/EXECUTING/PAUSED/FINISHED 等（页面 `IWaypointMissionManager_WaypointMissionExecuteStateListener.html`）；`TODO(未确认)`：Mini 系列在 v5 下的 mission 错误码清单未在官方文档列出，需真机抓取回调 `error.description()`。

### 6.3 相机（拍照/录像/曝光）

```kotlin
import dji.sdk.keyvalue.key.CameraKey
import dji.sdk.keyvalue.key.KeyTools
import dji.sdk.keyvalue.value.camera.CameraMode
import dji.sdk.keyvalue.value.common.ComponentIndexType
import dji.v5.manager.KeyManager

val cameraIndex = ComponentIndexType.LEFT_OR_MAIN   // 主相机；官方枚举值：LEFT_OR_MAIN / RIGHT / UP / FPV / PORT_1..PORT_8（KeyTools 页原文）
// 切拍照模式 → 拍照（官方 Sample 用 Rx 串联，这里展开为回调写法）
KeyManager.getInstance().setValue(
    KeyTools.createKey(CameraKey.KeyCameraMode, cameraIndex), CameraMode.PHOTO_NORMAL,
    object : CommonCallbacks.CompletionCallback { override fun onSuccess() {}; override fun onFailure(e: IDJIError) {} })
KeyManager.getInstance().performAction(
    KeyTools.createKey(CameraKey.KeyStartShootPhoto, cameraIndex),
    object : CommonCallbacks.CompletionCallback {
        override fun onSuccess() {}; override fun onFailure(e: IDJIError) {} })

// 录像
KeyManager.getInstance().setValue(KeyTools.createKey(CameraKey.KeyCameraMode, cameraIndex), CameraMode.VIDEO_NORMAL, cb)
KeyManager.getInstance().performAction(KeyTools.createKey(CameraKey.KeyStartRecord, cameraIndex), cb)
KeyManager.getInstance().performAction(KeyTools.createKey(CameraKey.KeyStopRecord, cameraIndex), cb)

// 手动曝光：曝光模式 → ISO / 快门 / EV（必须是当前 liveview 镜头）
KeyManager.getInstance().setValue(KeyTools.createKey(CameraKey.KeyExposureMode, cameraIndex),
    CameraExposureMode.MANUAL, cb)
// TODO(未确认)：CameraISO / CameraShutterSpeed 只作为 KeyISO/KeyShutterSpeed 的泛型类型出现在官方 Key 页，
// 官方 API 参考站未收录这两个类的独立页面（本会话未取得构造器/静态工厂一手签名）。
// 5.20.1 下请先用 javap/构件符号核对实例化方式，再替换下面两行占位：
setCameraIso(cameraIndex, 400)           // 期望：KeyManager.setValue(createKey(CameraKey.KeyISO, cameraIndex), <CameraISO 实例>, cb)
setCameraShutter(cameraIndex, 1.0 / 500) // 期望：KeyManager.setValue(createKey(CameraKey.KeyShutterSpeed, cameraIndex), <CameraShutterSpeed 实例>, cb)

// 间隔拍照（航测/3DGS 采集关键）
KeyManager.getInstance().setValue(KeyTools.createKey(CameraKey.KeyCameraMode, cameraIndex),
    CameraMode.PHOTO_INTERVAL, cb)
KeyManager.getInstance().setValue(KeyTools.createKey(CameraKey.KeyPhotoIntervalShootSettings, cameraIndex),
    PhotoIntervalShootSettings().apply { interval = 2.0; count = 100 }, cb)  // 官方 Value 页：setInterval(Double 秒) / setCount(Integer 张)，无参 + setter
KeyManager.getInstance().performAction(KeyTools.createKey(CameraKey.KeyStartShootPhoto, cameraIndex), cb)
// 停止间隔：KeyStopShootPhoto
```
- 依据：`api_v5/IKeyManager__Key_Camera_CameraKey.html`（KeyStartShootPhoto/KeyStopShootPhoto/KeyStartRecord/KeyStopRecord/KeyExposureMode/CameraExposureMode/KeyISO→CameraISO/KeyShutterSpeed→CameraShutterSpeed/KeyPhotoIntervalShootSettings→PhotoIntervalShootSettings/KeyCameraMode→CameraMode/KeyVideoResolutionFrameRate/KeyCameraZoomRatios/KeyCameraFocusMode 均原文列出）；`msdkv5_sample/.../MediaVM.kt` 中 `takePhoto()` 真实写法：`RxUtil.setValue(createKey<CameraMode>(CameraKey.KeyCameraMode, index), CameraMode.PHOTO_NORMAL).andThen(RxUtil.performActionWithOutResult(createKey(CameraKey.KeyStartShootPhoto, index)))`。
- 注意（官方 Key 描述原文）：①曝光设置只对"当前 liveview 流所在镜头"生效；②间隔拍照/全景/超分模式下需 `KeyStopShootPhoto` 停止；③全景模式需飞机起飞后才能激活；④Mini 系列无光圈 Key（固定光圈），用快门/ISO/EV 控制曝光。
- 证据边界：`ComponentIndexType` 枚举值（LEFT_OR_MAIN/RIGHT/UP/FPV/PORT_1..PORT_8）与 `PhotoIntervalShootSettings` 的 setter（setCount(Integer)/setInterval(Double)）均已按官方页核对（`api_v5/IKeyManager__KeyTools.html`、`api_v5/Value_Camera_Struct_PhotoIntervalShootSettings.html`）；`CameraISO`/`CameraShutterSpeed` 的实例化方式仍 `TODO(未确认)`（官方 API 参考站无类页，需 5.20.1 构件核对）。

### 6.4 云台

```kotlin
import dji.sdk.keyvalue.key.GimbalKey
import dji.sdk.keyvalue.key.KeyTools
import dji.sdk.keyvalue.value.gimbal.GimbalAngleRotation
import dji.sdk.keyvalue.value.gimbal.GimbalSpeedRotation
import dji.v5.manager.KeyManager

val key = KeyTools.createKey(GimbalKey.KeyRotateByAngle)   // DJIKey.ActionKey<GimbalAngleRotation, EmptyMsg>
// 官方 Value 页原文：class GimbalAngleRotation（无参 + setMode/setPitch/setYaw/setRoll/setDuration，字段均 Double）
val rotation = GimbalAngleRotation().apply {
    pitch = -45.0; roll = 0.0; yaw = 0.0; duration = 0.0
    // TODO(未确认)：GimbalAngleRotationMode 枚举常量名（官方 Key 描述仅说明支持 relative/absolute 两种角度模式，
    // API 参考站未收录该枚举页；5.20.1 下请以 javap 核对后取消注释）
    // mode = GimbalAngleRotationMode.ABSOLUTE_ANGLE
}
KeyManager.getInstance().performAction(key, rotation, object : CommonCallbacks.CompletionCallbackWithParam<EmptyMsg> {
    override fun onSuccess(r: EmptyMsg?) {}; override fun onFailure(e: IDJIError) {}
})
// 读姿态 / 速度模式旋转
val att = KeyManager.getInstance().getValue(KeyTools.createKey(GimbalKey.KeyGimbalAttitude))  // @Nullable getValue(key) 重载；不依赖 Attitude 构造器
KeyManager.getInstance().performAction(KeyTools.createKey(GimbalKey.KeyRotateBySpeed),
    GimbalSpeedRotation().apply { pitch = 0.0; yaw = 0.0; roll = 0.0 }, cb)   // Value 页：无参 + setter；单位 0.1°/s
```
- 依据：`api_v5/IKeyManager__Key_Gimbal_GimbalKey.html`：`KeyRotateByAngle`(DJIActionKeyInfo<GimbalAngleRotation,EmptyMsg>)、`KeyRotateBySpeed`(GimbalSpeedRotation；单位 0.1°/s)、`KeyGimbalAttitude`(Attitude，yaw 用 NED，相对机头用 `KeyYawRelativeToAircraftHeading`)、`KeyGimbalReset`(GimbalResetType)、`KeyGimbalCalibrate`、`KeyPitchRangeExtensionEnabled`。
- 证据边界：`GimbalAngleRotation`（setMode/setPitch/setYaw/setRoll/setDuration）与 `GimbalSpeedRotation`（setPitch/setYaw/setRoll）字段已按官方 Value 页核对（`api_v5/Value_Gimbal_Struct_GimbalAngleRotation.html`、`..._GimbalSpeedRotation.html`）；仅 `GimbalAngleRotationMode` 枚举常量名 `TODO(未确认)`。Mini 系列支持的俯仰区间以真机 `KeyGimbalAttitude` + 官方规格页为准（Mini 4 Pro：-90°~+35° 俯仰，见 02）。

### 6.5 媒体文件（列表/下载/回放）

```kotlin
import dji.v5.manager.datacenter.MediaDataCenter
import dji.v5.manager.datacenter.media.*

val media = MediaDataCenter.getInstance().mediaManager   // Java: getMediaManager()
media.enable(object : CommonCallbacks.CompletionCallback { override fun onSuccess() {}; override fun onFailure(e: IDJIError) {} })
// 拉列表（分页）
media.pullMediaFileListFromCamera(
    PullMediaFileListParam.Builder().mediaFileIndex(0).count(50).build(),
    object : CommonCallbacks.CompletionCallback {
        override fun onSuccess() {}
        override fun onFailure(e: IDJIError) {}
    })
media.addMediaFileListStateListener(object : MediaFileListStateListener {
    override fun onUpdate(state: MediaFileListState) {
        if (state == MediaFileListState.UP_TO_DATE) {
            val list: List<MediaFile> = media.mediaFileListData.data
        }
    }
})
// 下载原文件（回调里拿 ByteArray 自己写盘）
media.mediaFileListData.data.first().pullOriginalMediaFileFromCamera(0L,
    object : MediaFileDownloadListener {
        override fun onStart() {}
        override fun onProgress(total: Long, current: Long) {}
        override fun onRealtimeDataUpdate(data: ByteArray, position: Long) { /* 追加写文件 */ }
        override fun onFinish() {}
        override fun onFailure(e: IDJIError) {}
    })
// 回放：playVideoToSurface / seekVideo / pauseVideo / resumeVideo / stopVideo / release
```
- 依据：`api_v5/IMediaDataCenter__IMediaManager.html`（`enable/disable/pullMediaFileListFromCamera(PullMediaFileListParam, cb)/getMediaFileListData/deleteMediaFiles/setMediaFileDataSource/playVideoToSurface/seekVideo/...`）；Sample `MediaVM.kt` 完整实现（`MediaDataCenter.getInstance().mediaManager`、`PullMediaFileListParam.Builder().mediaFileIndex(i).count(n).build()`、`MediaFile.pullOriginalMediaFileFromCamera(offset, listener)`）。
- 注意：媒体下载前需 `enable()` 进入回放/下载模式；下载速率受图传链路限制；XMP 自定义信息有 `setMediaFileXMPCustomInfo`（可用于写入任务/照片关联 ID，对本项目 metadata 对接有用）。

### 6.6 遥测（≤10Hz）

官方口径："GPS position, compass, barometer, flight velocity, and altitude ... up to 10 Hz"（`data/dji/raw/text/msdk_introduction.txt`）。
v5 不提供统一 `AircraftState` 对象（v4 的 `FlightControllerState` 不存在于 v5），而是用 Key 监听：

```kotlin
// 建议：把一组 Key 的 listen 绑定到同一个 holder（Fragment/ViewModel），退出时统一 cancelListen(holder)
KeyManager.getInstance().listen(KeyTools.createKey(FlightControllerKey.KeyAircraftLocation), holder) { _, v: LocationCoordinate2D? -> }
KeyManager.getInstance().listen(KeyTools.createKey(FlightControllerKey.KeyAircraftAttitude), holder) { _, v: Attitude? -> }
KeyManager.getInstance().listen(KeyTools.createKey(FlightControllerKey.KeyAircraftVelocity), holder) { _, v: Velocity3D? -> }
KeyManager.getInstance().listen(KeyTools.createKey(FlightControllerKey.KeyAltitude), holder) { _, v: Double? -> }
KeyManager.getInstance().listen(KeyTools.createKey(FlightControllerKey.KeyGPSSatelliteCount), holder) { _, v: Int? -> }
KeyManager.getInstance().listen(KeyTools.createKey(FlightControllerKey.KeyFlightMode), holder) { _, v: FlightMode? -> }
KeyManager.getInstance().listen(KeyTools.createKey(BatteryKey.KeyChargeRemainingInPercent), holder) { _, v: Int? -> }
// 退出：
KeyManager.getInstance().cancelListen(holder)
```
- 依据：`api_v5/IKeyManager__IKeyManager.html`（listen(Holder)/cancelListen(Object)）；Sample `WayPointV3VM.kt`（`FlightControllerKey.KeyAircraftLocation.create()`、`KeyManager.getInstance().cancelListen(this)`）。
- 频率建议：SDK 本身回调上限约 10Hz（官方 msdk_introduction）；工程侧再降采样到 2–5Hz 写遥测快照即可，避免 LLM 侧高频噪声。
- 电量：`BatteryKey.KeyChargeRemainingInPercent`(Integer)、`KeyVoltage`(mV)、`KeyCellVoltages`(List<Integer>)；链路：`RemoteControllerKey.KeyConnection`、`AirlinkKey`（信号质量见 `Key_Flight_.../AirlinkKey` 页）。

### 6.7 虚拟摇杆

```kotlin
import dji.v5.manager.aircraft.virtualstick.VirtualStickManager
import dji.sdk.keyvalue.value.flightcontroller.VirtualStickFlightControlParam
import dji.sdk.keyvalue.value.flightcontroller.FlightCoordinateSystem
import dji.sdk.keyvalue.value.flightcontroller.RollPitchControlMode
import dji.sdk.keyvalue.value.flightcontroller.YawControlMode
import dji.sdk.keyvalue.value.flightcontroller.VerticalControlMode

val vs = VirtualStickManager.getInstance()
vs.enableVirtualStick(cb)                 // 进入虚拟摇杆（遥控器须在 N 档、飞机无自动任务）
vs.setVirtualStickAdvancedModeEnabled(true)
vs.sendVirtualStickAdvancedParam(VirtualStickFlightControlParam().apply {
    // 字段/枚举组合来自官方 Sample VirtualStickVM.kt（rollPitch=ANGLE、yaw=ANGULAR_VELOCITY、vertical=VELOCITY、BODY）
    rollPitchControlMode = RollPitchControlMode.ANGLE
    rollPitchCoordinateSystem = FlightCoordinateSystem.BODY
    yawControlMode = YawControlMode.ANGULAR_VELOCITY
    verticalControlMode = VerticalControlMode.VELOCITY
    pitch = 0.0; roll = 0.0; yaw = 0.0; verticalThrottle = 0.0   // 示例值：pitch/roll 单位度（ANGLE 模式）
})
// 关闭：vs.disableVirtualStick(cb)；状态监听：vs.setVirtualStickStateListener(...)
```
- 官方要求（`text/virtual_stick.txt` 原文）：飞机不能处于任何自动任务；遥控器在 normal position（如 N 档）；高级模式需先 `setVirtualStickAdvancedModeEnabled`；普通模式用左右杆 `getLeftStick()/getRightStick()` 的 `setVerticalPosition/setHorizontalPosition`（范围 ±660，见 `IStick`）；发送频率建议 5–25Hz。
- 依据：`api_v5/IVirtualStickManager__IVirtualStickManager.html`、`..._VirtualStickFlightControlParam.html`、`..._DJIStick.html`、Sample `VirtualStickVM.kt`。
- 风险：虚拟摇杆模式下避障可能被禁用（官方仅提 M3E/M3T/M3M 固件 < V7.01.10.03 的情形）；Mini 系列真机行为 `TODO(未确认)`，本项目 Phase-2 建议只用于低速微调且保留 RC 接管。

### 6.8 图传

```kotlin
val stream = MediaDataCenter.getInstance().cameraStreamManager
stream.putCameraStreamSurface(ComponentIndexType.LEFT_OR_MAIN, surface, w, h, ICameraStreamManager.ScaleType.FIX_XY)
stream.addFrameListener(ComponentIndexType.LEFT_OR_MAIN, ICameraStreamManager.FrameFormat.YUV420_888, listener)
stream.enableStream(ComponentIndexType.LEFT_OR_MAIN, true)
```
- 依据：`api_v5/IMediaDataCenter__ICameraStreamManager.html`（putCameraStreamSurface/removeCameraStreamSurface/addFrameListener/addReceiveStreamListener/enableStream/getLiveViewLocationWithGPS）；IVideoStreamManager 自 5.8.0 废弃（页面 Note 原文）。枚举值已核对：`ScaleType` = FIX_XY / CENTER_CROP / CENTER_INSIDE；`FrameFormat` = YUV420_888 / YUV444_888 / YUY2 / NV21 / RGBA_8888（该页原文）。
- 用途：本项目可用 `getLiveViewLocationWithGPS(pointPos, type)` 把画面像素反算成 GPS（做"点哪拍哪"），但 Mini 系列精度 `TODO(未确认)`。

## 7. 常见坑（按优先级）

1. `com.secneo` vs `com.cySdkyc`：v5.10.0 之后必须用新包名（relnotes 5.10.0）；老博客代码会直接闪退。
2. 只支持 arm64-v8a：x86 模拟器无法跑 MSDK；`abiFilters 'arm64-v8a'` 必须写。
3. Android API 35：必须 `android:extractNativeLibs="true"`（relnotes 5.17.0），否则 so 加载失败。
4. App Key/包名不一致 → `onRegisterFailure`；改包名要重新在 developer.dji.com 建 App。
5. RC-N2/N3 才支持 Mini 4 Pro；DJI RC 2（带屏）永远不行（01 已证）。
6. Mini 3/3 Pro 换遥控器 → 必须 DJI Fly 重绑（relnotes 5.3.0）。
7. 相机曝光只对当前 liveview 镜头生效；间隔拍照必须 `KeyStopShootPhoto` 停止，否则一直拍。
8. 断点续飞 Mini 不在官方保证列表 → 本项目 `goto_waypoints` 的"中断恢复"在真机上应退化为"重新上传+从头执行"。
9. `WaypointMissionManager` 是单例，监听器务必在 `onDestroy` `remove/clear`，否则内存泄漏 + 重复回调。
10. 媒体列表/下载要走 `enable()`；下载大文件注意手机存储与图传带宽。

## 8. 与 llm_drone 桥接的 API 映射（Phase-2 建议）

| 工具 | MSDK v5 落地 |
|---|---|
| `get_telemetry` | KeyManager listen/getValue：KeyAircraftLocation/Attitude/Velocity/Altitude/GPS/FlightMode/Battery |
| `preflight_check` | KeyConnection（FC/Camera/Gimbal/Battery/RC）、KeyGPSSatelliteCount、KeyChargeRemainingInPercent、KeyFlightMode、KeyIsFlying、固件版本（ProductKey/KeyFirmwareVersion） |
| `takeoff` | FlightControllerKey.KeyStartTakeoff |
| `goto_waypoints`/`orbit` | 服务端生成 KMZ → pushKMZFileToAircraft → getAvailableWaylineIDs → startMission；进度用 WaylineExecutingInfoListener |
| `set_gimbal` | GimbalKey.KeyRotateByAngle |
| `capture_photo` | CameraKey.KeyStartShootPhoto（连拍/间隔用 KeyPhotoIntervalShootSettings + KeyStopShootPhoto） |
| `start_video`/`stop_video` | CameraKey.KeyStartRecord/KeyStopRecord |
| `return_to_home` | FlightControllerKey.KeyStartGoHome |
| `land` | FlightControllerKey.KeyStartAutoLanding（+ KeyConfirmLanding） |
| `abort` | WaypointMissionManager.stopMission + KeyStopGoHome/KeyStartAutoLanding（按场景） |
| 照片元数据 | 下载时记录 MediaFile 文件名/时间，配合 XMP 自定义信息（setMediaFileXMPCustomInfo）与飞控遥测快照 |

## 9. 一手证据索引

| 内容 | URL | 本地证据 |
|---|---|---|
| MSDK V5 官方 README（5.20.1/Maven 坐标/支持机型） | https://github.com/dji-sdk/Mobile-SDK-Android-V5 | data/dji/raw/api_v5/repo_README.md（经 cdn.jsdelivr.net 拉取） |
| 官方集成教程（移植到空白工程：环境/依赖/manifest/MyApplication） | https://developer.dji.com/doc/mobile-sdk-tutorial/en/ | data/dji/raw/msdkv5_docs_extracted/v-dadb0ffc.07ff76f1.js.txt、v-19a8b384.619f07ec.js.txt |
| 4.X→5.X API 映射（Key/Manager 对照） | 同上教程 "Migrate from 4.X to 5.X" | .../v-0acaef9a.a4bf24b3.js.txt、v-23c38850.ea72e6de.js.txt |
| SDKManager/回调/初始化 | https://developer.dji.com/api-reference-v5/android-api/Components/SDKManager/DJISDKManager.html | data/dji/raw/api_v5/SDKManager__DJISDKManager.html、SDKManager__ISDKManager_SDKManagerCallback.html |
| IKeyManager/KeyTools/回调 | https://developer.dji.com/api-reference-v5/android-api/Components/IKeyManager/IKeyManager.html | data/dji/raw/api_v5/IKeyManager__IKeyManager.html、KeyTools.html、DJICommonCallbacks__*.html |
| 飞控 Key 全集 | .../IKeyManager/Key_FlightController_FlightControllerKey.html | data/dji/raw/api_v5/IKeyManager__Key_FlightController_FlightControllerKey.html |
| 相机 Key 全集 | .../IKeyManager/Key_Camera_CameraKey.html | data/dji/raw/api_v5/IKeyManager__Key_Camera_CameraKey.html |
| 云台 Key 全集 | .../IKeyManager/Key_Gimbal_GimbalKey.html | data/dji/raw/api_v5/IKeyManager__Key_Gimbal_GimbalKey.html |
| 电池 Key | .../IKeyManager/Key_Battery_BatteryKey.html | data/dji/raw/api_v5/IKeyManager__Key_Battery_BatteryKey.html |
| 航线任务管理 | .../IWaypointMissionManager/IWaypointMissionManager.html | data/dji/raw/api_v5/IWaypointMissionManager__IWaypointMissionManager.html |
| KMZ 编辑 WPMZManager | .../IWaypointMissionManager/IWPMZManager.html | data/dji/raw/api_v5/IWaypointMissionManager__IWPMZManager.html |
| 媒体/图传 | .../IMediaDataCenter/IMediaManager.html、ICameraStreamManager.html | data/dji/raw/api_v5/IMediaDataCenter__*.html |
| 虚拟摇杆 | .../IVirtualStickManager/IVirtualStickManager.html | data/dji/raw/api_v5/IVirtualStickManager__*.html |
| 官方 Sample 代码（E2E 用法） | https://github.com/dji-sdk/Mobile-SDK-Android-V5/tree/dev-sdk-main/SampleCode-V5 | data/dji/raw/msdkv5_sample/（MSDKManagerVM/WayPointV3VM/VirtualStickVM/MediaVM/BasicAircraftControlVM/WayPointV3Fragment/MediaFragment/AndroidManifest/dependencies.gradle） |
| Release Notes（版本-机型-固件） | https://developer.dji.com/doc/mobile-sdk-tutorial/en/ | data/dji/raw/text/relnotes_all.txt |
| 官方介绍（10Hz 遥测/相机/任务概念） | 同上 | data/dji/raw/text/msdk_introduction.txt、missions.txt、virtual_stick.txt、media_file.txt、waypoint.txt |

## 10. 未决问题 / TODO

1. `CameraISO`/`CameraShutterSpeed` 的实例化方式（官方 API 参考站无类页）；`GimbalAngleRotationMode` 枚举常量名。`GimbalAngleRotation`/`GimbalSpeedRotation`/`PhotoIntervalShootSettings` 的字段/用法已按 `Value_*` 页核对（2026-11-08 复核修正）。
2. Mini 系列在 v5 下 `WaypointMissionExecuteState` 的实际取值序列与错误码表：需真机日志（官方 Release Notes 仅给通用修复记录）。
3. `accessory_filter.xml` 的官方示例内容未抓到正文（Sample 资源文件路径推断），建议直接复用官方 Sample 工程。
4. Mini 4 Pro 的 `IIntelligentFlightManager`（POI/spotlight/flyTo）能力在 v5.14.0 支持列表内，但 Mini 4 Pro 具体可用子功能（SmartTrack 仅企业机）需真机 Key 可用性验证。
5. App Key 与签名证书指纹的绑定规则未见官方明文（`TODO(未确认)`）。

## 11. 端到端实施清单（从零到真机首飞）

阶段 A：工程可编译（1–2 天）
1. 建 Android 工程：minSdk 24 / targetSdk 35 / compileSdk 35 / Kotlin 2.1.0 / AGP 8.7.0 / JDK 17 / 只打 arm64-v8a。
2. 加三个 Maven 依赖（aircraft / provided / networkImp = 5.20.1），Sync Gradle。
3. Manifest 配 API_KEY、USB host/accessory、accessory_filter、extractNativeLibs=true。
4. 写 MyApplication（attachBaseContext 里 cySdkyc Helper.install；onCreate 里 init+registerApp），跑通注册日志。
5. 手机 USB 连 RC-N2/N3，遥控器与飞机开机、固件升到最新，确认 onProductConnect 被调用。

阶段 B：只读链路（1 天）
6. 用 KeyManager.getValue 读 KeyAircraftLocation / KeyAltitude / KeyGPSSatelliteCount / KeyChargeRemainingInPercent，把数值打到界面。
7. 用 listen 订阅 KeyAircraftAttitude / KeyAircraftVelocity / KeyFlightMode，确认回调频率与数值合理（约 10Hz 上限）。
8. 拔线/关遥控器，验证 onProductDisconnect 与 Key 回调停止，记录界面状态机迁移。

阶段 C：低风险动作（1 天）
9. 空旷地：先拆桨验证电机启停或按官方安全流程；相机拍照、云台 -45° 俯仰、读回 KeyGimbalAttitude。
10. 拍照后通过 IMediaManager 拉列表并下载一张到手机，核对文件名/时间/大小。

阶段 D：航线（2–3 天）
11. 先用服务端脚本生成 KMZ（docs/research/assets/make_sample_kmz.py，格式说明见 10 文档），checkValidation 通过。
12. pushKMZFileToAircraft 观察进度到 1.0；getAvailableWaylineIDs 拿 waylineId。
13. 空旷场地、低高度、短航线（3–6 点）执行 startMission，盯 WaylineExecutingInfo 与飞机状态。
14. 验证 pause/resume/stop；验证遥控器打杆中断时的回调（onWaylineExecutingInterruptReasonUpdate）。
15. 全程把 IDJIError 的 errorCode/description 记日志，形成本项目自己的错误码映射表。

阶段 E：与 LLM 桥接（1 天）
16. Android 侧起本地 HTTP/WebSocket 服务（或前台 Service），实现 CONTRACT 第 2 节的 /v1/command、/v1/telemetry、/v1/missions/{id}。
17. 每个工具映射到第 8 节表格；所有飞行指令在 App 内再过一遍本地安全阈值（双保险）。
18. 用 Phase-1 仿真录好的 mission JSON 做回放：同一 mission 先仿真、再真机小范围。

## 12. v5 能力边界与限制总表（Mini 3 / 3 Pro / 4 Pro）

| 能力 | 可用性 | 限制/备注 |
|---|---|---|
| 航线 KMZ 上传/执行/暂停/恢复/停止 | 可用 | Mini 系不在断点续飞保证列表；KMZ 由服务端或 WPMZ 库生成 |
| 虚拟摇杆（连续速度控制） | 可用 | 需退出自动任务、遥控器 N 档；建议 5–25Hz；避障在部分机型/固件可能被抑制 |
| 相机拍照/录像/间隔拍照 | 可用 | 无光圈可调（固定光圈）；曝光只对当前 liveview 镜头生效 |
| 相机手动曝光（ISO/快门/EV） | 可用 | 需先切 EXPOSURE_MODE；夜景/长曝光受限于快门范围 |
| 云台俯仰/横滚/偏航 | 可用（角度/速度两种模式） | 机械限位随机型不同，超范围回调失败 |
| 媒体列表/下载/回放 | 可用 | 下载走图传链路，大文件慢；需先 enable() |
| 图传（主相机） | 可用（v5.8.0 起 ICameraStreamManager） | 仅主相机；旧 IVideoStreamManager 已废弃 |
| 遥测（位置/姿态/速度/高度/GPS/电量） | 可用，Key 监听 | 官方口径最高 10Hz；无统一 AircraftState 聚合对象 |
| 智能飞行 POI/Spotlight/FlyTo | Mini 4 Pro 在 v5.14.0 支持列表 | SmartTrack 仅企业机型；Mini 3/3 Pro 未确认 |
| 避障/感知接口 | 未在 Mini 文档明确开放 | 消费级 Mini 的 Perception 能力有限，按 Key 可用性判断 |
| 全景拍照（panoShot） | 未确认 Mini 支持 | DJI Fly 支持全景，但 MSDK 的 panoShot 支持机型列表无 Mini |
| 固件升级/日志/限飞区查询 | 部分可用 | UpgradeManager/FlyZoneManager 在 v5 存在；Mini 系能力以真机为准 |

说明：本表把散落在 API 页/Release Notes 的限制集中起来，方便桥接层决定哪些工具在 Mini 上必须降级或禁用。每一项的原始证据见第 9 节证据索引。

## 13. 安全阈值在 App 侧的实现建议

MSDK 本身不做业务级安全校验（限高/限速/围栏/禁飞区/电量是 DJI 固件与 FlySafe 的职责，且不能替代本项目 SafetyValidator）。建议 App 在每次下发飞行动作前自己做一次「确定性检查」，检查项与 CONTRACT 第 3 节一一对应：

1. 相对高度：目标高度 + 当前起飞点海拔推算，超过配置上限（默认 120m）直接拒绝，不下发 SDK 调用。
2. 水平速度：航线 autoFlightSpeed / waypointSpeed 与虚拟摇杆速度向量都检查上限（默认 15m/s，Mini 建议 10m/s）。
3. 围栏：起飞前读 KeyAircraftLocation + KeyHomeLocation，判断是否在配置的圆形/多边形围栏内；航线每个航点在生成 KMZ 前就校验。
4. 禁飞区：无本地数据库时，退化为「人工确认 + DJI 固件拒绝」双保险；不要把 FlyZoneManager 当作唯一防线。
5. 电量：起飞前 KeyChargeRemainingInPercent ≥ 30%；执行中低于 20% 主动 stopMission 并 RTH。
6. GPS：KeyGPSSatelliteCount ≥ 10 且 KeyGPSSignalLevel 达到可用等级才允许 takeoff/startMission。
7. 链路：RemoteControllerKey.KeyConnection + AircraftKey/AirlinkKey 质量，断开时不允许继续下发新动作。
8. 二次确认：takeoff/goto_waypoints/orbit/set_mode(real) 在 App 侧也必须带 confirm，不能只靠 Orchestrator。

实现位置建议：`SafetyGate` 类集中检查，返回结构化错误（code/message/detail），与 CONTRACT 第 8.2 节错误码对齐；所有拒绝写本地审计 JSONL，再通过 HTTP 回传。这样即使 LLM 侧出现幻觉参数，真机也不会执行。

## 14. 合规与安全提示（与 01 文档互补）

- 采集飞行必须遵守当地空域法规（中国《无人驾驶航空器飞行管理暂行条例》等）；本项目 CONTRACT 的 120m 限高、围栏、禁飞区、电量阈值是工程兜底，不替代法规要求。
- DJI《飞行器产品使用条款》（2024-07-12 版）第 3 条禁止修改/解锁/解码/反向编译产品与 App、禁止解除或修改地理围栏与飞行高度限制（一手原文与本地证据见 01 第 7 节与 data/dji/raw/dji_terms_cn.html）。本项目只用官方 MSDK v5 与官方 WPML 格式，不做逆向或改固件。
- Mini 系列消费级机型无 PSDK / 上云 API（01 第 2 节），因此机载边缘计算 / 云平台直连路线不可行；必须走手机 App as Drone Agent。
- 真机建议：先拆桨/室内验证 Key 可读性 → 空旷场地低高度短航线 → 再逐步放大范围；全程保留人工接管（RC 打杆可中断航线，官方支持）。

## 15. FAQ（工程向）

Q1：为什么 v5 找不到 IFlightController / ICamera 这类类？
A：v5 把组件控制改成了 Key 体系：飞控/相机/云台/电池都是 Key（FlightControllerKey / CameraKey / GimbalKey / BatteryKey），动作是 ActionKey，读值写值是 DJIKey。官方迁移文档有完整 4.X→5.X 对照表（本文件第 9 节证据）。

Q2：registerApp() 为什么没有参数？App Key 在哪读？
A：v5 的 registerApp() 无参重载从 AndroidManifest 的 com.dji.sdk.API_KEY meta-data 读取；App Key 与包名绑定，改包名需到 developer.dji.com 重新建 App。

Q3：为什么必须 arm64-v8a？
A：MSDK V5 的 so 库只提供 arm64-v8a（官方移植文档原文）。x86 模拟器/32 位手机会在加载 so 时失败，典型表现是 UnsatisfiedLinkError 或注册直接失败。

Q4：遥测为什么没有统一的 AircraftState？
A：v5 没有 v4 的 FlightControllerState 聚合对象，官方推荐用 Key 监听（KeyManager.listen）。本项目在 App 内自己聚合成 TelemetrySnapshot 再回传 HTTP 层（字段与 CONTRACT 第 2 节对齐）。

Q5：拍照后怎么拿到照片文件与元数据？
A：两个通道：一是 CameraKey.KeyNewlyGeneratedMediaFile（GeneratedMediaFileInfo，拍照/录像开始后回调新文件信息）；二是 IMediaManager 拉媒体列表后按文件名/时间匹配，再 pullOriginalMediaFileFromCamera 下载。元数据（GPS/云台）用拍照时刻的 Key 快照记录，不要用下载时刻的遥测。

Q6：任务执行到一半 App 崩了/被杀怎么办？
A：航线在飞机侧执行（KMZ 已上传），App 崩溃不影响当前航线；重新打开 App 后重新注册、连接，用 WaylineExecutingInfoListener / WaypointMissionExecuteStateListener 恢复界面状态。但 Mini 系断点续飞无官方保证，中断后按第 6.2 节策略重新上传执行。对 Phase-2 的可靠性设计很关键：任务状态必须落盘在 App/后端，不能只存在内存。

Q7：Mini 3/3 Pro/4 Pro 的云台俯仰范围一样吗？
A：不一样（Mini 4 Pro 官方规格 -90°~+35°，Mini 3/3 Pro 见 02 文档）。代码上用 KeyGimbalAttitudeRange 或读当前 Attitude 判断，不要写死；GimbalKey.KeyRotateByAngle 超范围会回调失败。
