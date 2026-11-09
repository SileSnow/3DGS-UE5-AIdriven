# 09 MSDK v4（Android/iOS）使用方法与 Mini 2 链路

> 调研日期：2026-11-08（Asia/Shanghai，断电恢复后续写）。本文补齐 01 文档"能支持"之外的"怎么用"：MSDK v4.16+ 对 **Mini 2 / Mini SE / Mavic Mini** 的注册、初始化、飞控、航线任务、iOS 差异，以及 v4 与 v5 为什么不能共用一套代码。
> 证据规范：每条 API 尽量给一手来源；未获取到一手证据的写 `TODO(未确认)`。
> 本地证据根：`dji_ue5_3dgs/data/dji/raw/api_v4/`（本次新增）、`data/dji/raw/msdk_v4_landing.html`、`data/dji/raw/msdk_v4_product_intro.html`。

## 0. 一页速查

| 项 | 结论 | 证据 |
|---|---|---|
| v4 最后版本 | **4.18（2024-10-24）**；Mini 2/Mini SE 支持自 **4.16（2021-12-31）** | v4 GitHub Releases 时间轴（见 01/references） |
| 适用机型（Mini 系） | Mavic Mini（论坛称 4.13 起[二级]）、Mini SE、Mini 2；**Mini 3/3 Pro/4 Pro 不支持 v4** | 官方兼容表（01 文档）+ v4 README 支持范围 |
| 平台 | Android + iOS（v4 双端都有 SDK） | `data/dji/raw/api_v4/Mobile-SDK-Android-README.md`；iOS API Reference 页 `api_v4/iOS_DJISDKManager.html` |
| Maven | `com.dji:dji-sdk:4.18` + `com.dji:dji-sdk-provided:4.18`（compile/provided） | v4 README 原文 |
| 注册入口 | `DJISDKManager.getInstance().registerApp(context, callback)` | `api_v4/DJISDKManager.html` 签名 |
| 连接入口 | 注册成功后 `startConnectionToProduct()` | 同上 |
| 飞控 | `DJISDKManager.getInstance().getProduct()` → `(Aircraft) product` → `getFlightController()` | v4 产品/组件模型；FlightController API 页 `api_v4/DJIFlightController.html` |
| 航线 | `MissionControl` 取 `WaypointMissionOperator`；`loadMission/uploadMission/startMission/pause/resume/stop` | `api_v4/DJIWaypointMissionOperator.html` |
| 与 v5 关系 | **不兼容、不能共用代码**（包名/类名/编程模型全变） | 官方 4.X→5.X 迁移文档（08 文档 §9 证据） |

## 1. v4 的机型覆盖与生命周期

- 官方 GitHub v4 仓库（https://github.com/dji-sdk/Mobile-SDK-Android）Release 时间轴：v4.16 = 2021-12-31；v4.16.1 = 2022-03-18；v4.16.2 = 2022-08-01；v4.16.3 = 2022-10-26；v4.16.4 = 2022-11-11；v4.17 = 2023-11-10；v4.18 = 2024-10-24（末版）。证据索引见 01 §1.5 与 references.md A11。
- 支持 Mini 2 / Mini SE 的版本是 **v4.16**：二级媒体转述官方 Release Notes（dronedj 2022-01-03）称 4.16 新增 Mini 2、Mini SE、Air 2S，能力口径为 camera / flight controller / gimbal / remote controller；该版已知缺口：全景拍照模式暂不支持、云台高度数据因固件问题暂不可得、FlyZoneManager 暂不可用（后续版本修复）。[二级] 证据链见 01 §1.5/§3。
- v4 已停止新增机型：Mini 3 及 이후机型全部走 MSDK v5（Android only），官方兼容表对 Mini 3/3 Pro/4 Pro 的"支持 SDK"指 v5，不是 v4。MINI 2 SE / Mini 4K 官方兼容表为"不支持"（见 01 §0.2）。
- 结论：做 Mini 2/SE/Mavic Mini 的自动化，只能维护一个 **v4 分支 App**；做 Mini 3/3 Pro/4 Pro，只能维护 **v5 分支 App**。本项目 Phase-2 若选 Mini 4 Pro，不需要 v4 代码。

来源 URL：
- v4 仓库 README（Maven 坐标/集成文档入口）：https://github.com/dji-sdk/Mobile-SDK-Android
- v4 产品页（Supported Products 分类）：https://developer.dji.com/mobile-sdk-v4/
- 官方兼容总表：https://support.dji.com/help/content?customId=01700000763&spaceId=17&re=CN&lang=zh-CN

## 2. 开发环境与依赖

v4 README 原文（"Integration" 节）：

```groovy
// Gradle（官方 README 的 compile/provided 写法，新 Gradle 请改为 implementation/compileOnly）
implementation 'com.dji:dji-sdk:4.18'
compileOnly    'com.dji:dji-sdk-provided:4.18'
```

- `dji-sdk-provided` 是"编译期接口包"，运行时不打包（与 v5 的 aircraft-provided 思路一致）。
- 混淆：README "ProGuard" 节要求 `-libraryjars dji_android_sdk.aar` 或引用官方 `proguard-project` 规则；v4 不内置混淆规则（与 v5.8.0 之后"内置混淆规则"不同）。
- 包名与最低 API：v4 时代普遍 minSdk 21/23；README 未强制 arm64-only（v5 才强制）。`TODO(未确认)`：4.18 对 compileSdk/targetSdk 的官方推荐值未在 README 列出，请以官方 Sample 工程为准。
- 本地证据：`data/dji/raw/api_v4/Mobile-SDK-Android-README.md`（本次通过 cdn.jsdelivr.net 拉取 master 分支 README，内容为 4.18）。

## 3. App Key 注册与初始化（v4 状态机）

v4 的注册是"一步式"：`registerApp` 同时完成 SDK 初始化 + App Key 校验（v5 拆成 init + registerApp 两步，见 08 §4）。签名（`api_v4/DJISDKManager.html` 原文）：

```java
synchronized static DJISDKManager getInstance()
void registerApp(final Context inContext, SDKManagerCallback callback)
void registerAppForLDM(final Context inContext, SDKManagerCallback callback)   // 仅 LDM/行业场景
boolean startConnectionToProduct()
void stopConnectionToProduct()
BaseProduct getProduct()
KeyManager getKeyManager()
MissionControl getMissionControl()
String getSDKVersion()
@Deprecated boolean hasSDKRegistered()
void setCallbackRunInUIThread(boolean enable)
```

典型流程（Android/Kotlin）：

```kotlin
import dji.sdk.sdkmanager.DJISDKManager
import dji.sdk.sdkmanager.DJISDKManager.SDKManagerCallback
import dji.sdk.base.BaseProduct
import dji.sdk.products.Aircraft
import dji.sdk.flightcontroller.FlightController

class MyApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        // v4：注意不要在 attachBaseContext 里 install（那是 v5 的 Helper 机制）
        DJISDKManager.getInstance().registerApp(this, object : SDKManagerCallback {
            // 官方 SDKManagerCallback 接口原文（api_v4/DJISDKManager_DJISDKManagerCallbackInterface.html）：
            //   void onRegister(DJIError error)
            //   void onProductConnect(BaseProduct product) / onProductDisconnect() / onProductChanged(BaseProduct product)
            //   void onComponentChange(BaseProduct.ComponentKey key, BaseComponent oldComponent, BaseComponent newComponent)
            //   void onInitProcess(DJISDKInitEvent event, int totalProcess) / onDatabaseDownloadProgress(long current, long total)
            override fun onRegister(error: DJIError?) {
                if (error == null) {
                    DJISDKManager.getInstance().startConnectionToProduct()   // 注册成功后才连飞机
                } else {
                    // App Key/包名/网络问题：记录 error.description()
                }
            }
            override fun onProductConnect(product: BaseProduct?) { /* 飞机/遥控器已连接 */ }
            override fun onProductDisconnect() { }
            override fun onProductChanged(product: BaseProduct?) { /* 机型变化，重新取组件 */ }
            override fun onComponentChange(key: BaseProduct.ComponentKey?, oldComponent: BaseComponent?, newComponent: BaseComponent?) { }
            override fun onInitProcess(event: DJISDKInitEvent?, totalProcess: Int) { }
            override fun onDatabaseDownloadProgress(current: Long, total: Long) { }
        })
    }
}
```
说明：
- `onComponentChange` 是 v4 组件级连接事件；v5 用各模块 KeyConnection 替代（迁移文档原文）。
- App Key 仍与包名绑定，写 `AndroidManifest.xml` 的 `com.dji.sdk.API_KEY` meta-data（与 v5 相同键名）。`TODO(未确认)`：v4 是否也支持"registerApp 后自动读 manifest"，官方 v4 集成文档仅演示 `registerApp(context, callback)`，未见无参重载（v5 才有无参 `registerApp()`）。
- v4 的 `SDKManagerCallback` 与 v5 完全不同：v4 是 `onRegister(DJIError)`（error==null 即成功）+ `onProductConnect(BaseProduct)` + `onComponentChange(BaseProduct.ComponentKey, …)`；v5 是 `onRegisterSuccess()/onRegisterFailure(IDJIError)` + `onProductConnect(int productId)`（v4 证据 `api_v4/DJISDKManager_DJISDKManagerCallbackInterface.html`；v5 证据见 08 §4）。**两代回调不能互相照抄**。

## 4. 连接链路（Mini 2/SE：RC-N1 + 手机 USB）

- 链路：Android/iOS 手机 --USB--> RC-N1（Mini 2/SE/Mavic Mini 的手机夹持式遥控器）--OcuSync/Wi-Fi--> 飞机。
- 必须声明 USB Accessory：v4 集成文档要求 manifest 增加 `android.hardware.usb.accessory` feature 与 `USB_ACCESSORY_ATTACHED` intent-filter（与 v5 相同思路，见 08 §5）；同时 `startConnectionToProduct()` 负责发起 AOA 连接。
- 权限：存储/录音（媒体下载、录像）+ 运行时权限；USB 附件授权弹窗。
- 组件访问（官方 `DJIAircraft` 页原文）：`Aircraft.getFlightController()`、`getCameras()`/`getCameraWithComponentIndex(int)`、`getGimbals()`、`getBattery()`；`Aircraft` 的包名是 `dji.sdk.products`（故 `product.flightController` 这种 Kotlin 属性写法成立）。
- 连接判断：`onProductConnect` 后 `DJISDKManager.getInstance().getProduct()` 非空；再用 `ProductKey` / 组件 getter 判断相机/云台/飞控是否在线。`TODO(未确认)`：Mini 2 在 v4.16 早期固件下"云台高度数据不可得"（dronedj[二级]），本项目如用 Mini 2 做 3DGS，应避开依赖云台高度/俯仰精确值的逻辑。

## 5. FlightController（v4 飞控）真实 API

`DJIFlightController.html` 原文签名（节选，全部为 `void xxx(@Nullable CompletionCallback callback)` 形式）：

```java
class FlightController extends BaseComponent
@NonNull FlightControllerState getState()
void setStateCallback(@Nullable FlightControllerState.Callback callback)   // 飞控状态订阅（v4 的"遥测总线"）
void startTakeoff(@Nullable CompletionCallback callback)
void startPrecisionTakeoff(@Nullable CompletionCallback callback)
void cancelTakeoff(@Nullable CompletionCallback callback)
void startLanding(@Nullable CompletionCallback callback)
void cancelLanding(@Nullable CompletionCallback callback)
void confirmLanding(@Nullable CompletionCallback callback)
void startGoHome(@Nullable CompletionCallback callback)
void cancelGoHome(@Nullable CompletionCallback callback)
void turnOnMotors(@Nullable CompletionCallback callback)
void turnOffMotors(@Nullable CompletionCallback callback)
void setGoHomeHeightInMeters(@IntRange(from = 20, to = 500) int height, @Nullable CompletionCallback callback)
void setVirtualStickModeEnabled(boolean enabled, @Nullable CompletionCallback callback)
boolean isVirtualStickAdvancedModeEnabled()
void setVirtualStickAdvancedModeEnabled(boolean enabled)
void setVerticalControlMode(@NonNull VerticalControlMode mode)
void setRollPitchControlMode(@NonNull RollPitchControlMode mode)
void setYawControlMode(@NonNull YawControlMode mode)
void setRollPitchCoordinateSystem(@NonNull FlightCoordinateSystem system)
void sendVirtualStickFlightControlData(@NonNull FlightControlData controlData, @Nullable CompletionCallback callback)
```

代码（Kotlin，v4）：

```kotlin
fun getFlightController(): FlightController? {
    val product = DJISDKManager.getInstance().product
    return if (product is Aircraft) product.flightController else null
}
fun takeoff() = getFlightController()?.startTakeoff { err -> /* err==null 成功 */ }
fun land() = getFlightController()?.startLanding { err -> }
fun rth() = getFlightController()?.startGoHome { err -> }
fun motors(on: Boolean) = getFlightController()?.let { if (on) it.turnOnMotors{} else it.turnOffMotors{} }
fun goHomeHeight(m: Int) = getFlightController()?.setGoHomeHeightInMeters(m) { }
```
对比 v5：v4 是**面向对象组件**（`FlightController.startTakeoff`），v5 是**Key/ActionKey**（`FlightControllerKey.KeyStartTakeoff.create().action(...)`），方法名、回调类型、包名全部不同 → 不能共用代码（见 §8）。

## 6. WaypointMissionOperator 工作流（v4 航线）

v4 航线是"对象 + 操作员"模型：构造 `WaypointMission` → `loadMission` → `uploadMission` → `startMission`，由 `MissionControl` 提供 `WaypointMissionOperator`。`DJIWaypointMissionOperator.html` 原文签名：

```java
class WaypointMissionOperator
@Nullable DJIError loadMission(@NonNull WaypointMission mission)
@Nullable WaypointMission getLoadedMission()
void getPreviousInterruption(CommonCallbacks.CompletionCallbackWith<WaypointMissionInterruption> callback)
void uploadMission(@Nullable final CompletionCallback callback)
void retryUploadMission(@Nullable CompletionCallback callback)
void downloadMission(@Nullable CompletionCallback callback)
void startMission(@Nullable CompletionCallback callback)
void resumeMission(@Nullable CompletionCallback callback)
void pauseMission(@Nullable CompletionCallback callback)
void stopMission(@Nullable CompletionCallback callback)
void setAutoFlightSpeed(@FloatRange(from = -15.0f, to = 15.0f) float speed, @Nullable CompletionCallback<DJIWaypointV2Error> callback)
void getAutoFlightSpeed(CommonCallbacks.CompletionCallbackWith<Float> callback)
@NonNull WaypointMissionState getCurrentState()
void addListener(@NonNull final WaypointMissionOperatorListener listener)
void removeListener(@NonNull WaypointMissionOperatorListener listener)
```

`WaypointMission`（`DJIWaypointMission.html` 原文成员，节选）：

```java
final class WaypointMission
  enum WaypointMissionExecuteState
  enum WaypointMissionFinishedAction
  enum WaypointMissionHeadingMode
  enum WaypointMissionFlightPathMode
  enum WaypointMissionGotoWaypointMode
  LocationCoordinate2D getCoordinate(); float getAltitude(); int getIndex(); int getMissionID()
  DJIError checkParameters(); int getWaypointCount(); List<Waypoint> getWaypointList()
  float getMaxFlightSpeed(); float getAutoFlightSpeed()
  WaypointMissionGotoWaypointMode getGotoFirstWaypointMode()
  WaypointMissionFinishedAction getFinishedAction()
  WaypointMissionHeadingMode getHeadingMode()
  LocationCoordinate2D getPointOfInterest()
  WaypointMissionFlightPathMode getFlightPathMode()
  boolean isExitMissionOnRCSignalLostEnabled()
  boolean isGimbalPitchRotationEnabled()
  int getRepeatTimes()
```

典型调用（v4 惯用 Builder；`WaypointMission.Builder` 的 setter 名官方 API 页未在本会话抓取到完整签名，`TODO(未确认)` 具体 setter 以 v4 API 页 `WaypointMission.Builder` 小节为准）：

```kotlin
val mission = WaypointMission.Builder()
    .autoFlightSpeed(5f)
    .maxFlightSpeed(10f)
    .finishedAction(WaypointMissionFinishedAction.GO_HOME)
    .headingMode(WaypointMissionHeadingMode.AUTO)
    .flightPathMode(WaypointMissionFlightPathMode.NORMAL)
    .gotoFirstWaypointMode(WaypointMissionGotoWaypointMode.SAFELY)
    .repeatTimes(1)
    .build()
// 逐点添加 Waypoint（经纬度/高度/动作），再 checkParameters() 校验
val op = DJISDKManager.getInstance().missionControl?.waypointMissionOperator
op?.loadMission(mission)?.let { err -> /* 参数错误 */ }
op?.addListener(object : WaypointMissionOperatorListener {
    // 官方 Listener 页原文：onUploadUpdate(WaypointMissionUploadEvent)、onDownloadUpdate(WaypointMissionDownloadEvent)、
    //   onExecutionStart()、onExecutionUpdate(WaypointMissionExecutionEvent)、onExecutionFinish(DJIError?)
    override fun onUploadUpdate(uploadEvent: WaypointMissionUploadEvent?) { /* 上传进度 */ }
    override fun onDownloadUpdate(downloadEvent: WaypointMissionDownloadEvent?) { }
    override fun onExecutionStart() { }
    override fun onExecutionUpdate(executionEvent: WaypointMissionExecutionEvent?) { /* 执行进度 */ }
    override fun onExecutionFinish(error: DJIError?) { }
})
op?.uploadMission { err -> if (err == null) op.startMission { } }
// 暂停/恢复/停止：op.pauseMission{} / op.resumeMission{} / op.stopMission{}
```
注意：
- 方法名是 `loadMission`（不是 v5 的 `pushKMZFileToAircraft`），任务以内存对象上传，**不涉及 KMZ/WPML**；v4 的 waypoint 上限/速度范围由机型固件决定，`TODO(未确认)` Mini 2 的上限。
- v4 的"断点"是 `getPreviousInterruption` / `WaypointMissionInterruption`，与 v5 的 `BreakPointInfo` 不同构。
- 证据：`api_v4/DJIWaypointMissionOperator.html`、`api_v4/DJIWaypointMission.html`；v4 Mission 文档入口 https://developer.dji.com/mobile-sdk/documentation/introduction/index.html 。

## 7. Mini 2 / SE / Mavic Mini 实操要点

1. 遥控器：必须 RC-N1 类手机夹持式；带屏 Smart Controller 需确认 Litchi/Dronelink 支持（01 §6）。
2. v4.16 已知缺口（dronedj[二级]）：全景拍照模式未支持、云台高度数据不可得、FlyZoneManager 暂不可用；后续 4.16.x 修复。做 3DGS 采集时不要依赖"全景模式"与"云台相对高度"。
3. 相机/云台仍可用（v4 `Camera`/`Gimbal` 组件）；但本项目若用 Mini 2（1/2.3" 12MP）画质弱于 Mini 3/4 Pro 的 1/1.3" 48MP（见 02），3DGS 纹理质量受限。
4. 第三方 App 反证：Litchi 官方帮助明确支持 Mini 2 / Mini SE（version 1 only）/ Mavic Mini；Dronelink 支持 Mini 2（RC-N1，Android/iOS）。说明 v4 路径（第三方 App 集成 v4）在真机可用。证据：https://flylitchi.com/help、https://www.dronelink.com/supported-drones 。
5. v4 没有 Mini 3+ 支持：官方兼容表 + v4 Release Notes 均无 Mini 3/3 Pro/4 Pro 新增记录；v5 也没有 Mini 2（01 §4）。

## 8. iOS 差异

- v4 **有 iOS 版**：官方 API Reference 站有 "IOS SDK" 分类（`api_v4/iOS_DJISDKManager.html`，页内 "DJISDKManager"：`registerAppWithDelegate` 必须成功才能用 SDK；`startConnectionToProduct` 在注册成功且手机-遥控器数据连接建立后调用；`bluetoothProductConnector` 用于蓝牙机型）。
- 官方 v4 Android README 的 "Development Workflow / Sample Projects" 同时指向 iOS/Android 教程；v4 的 UX SDK 也分 iOS/Android。
- 差异点（对本项目）：
  1. iOS 无 v5（MSDK V5 只有 Android，见 08 §1）→ Mini 3/3 Pro/4 Pro 的 iOS 自动化无官方路径；Mini 2/SE 才可 iOS + v4。
  2. iOS 注册是 Delegate 模式（`registerAppWithDelegate`），不是 `registerApp(context, callback)`；连接是 `startConnectionToProduct`。
  3. 组件访问经 `DJISDKManager.product()` 的 `DJIAircraft`；航线经 `DJIMissionControl` 的 `waypointMissionOperator`（与 Android 概念一一对应，但类前缀 DJI + Objective-C/Swift）。
  4. `TODO(未确认)`：v4 iOS 对 Mini 2/Mini SE 的最低版本号（dronedj 称 4.16 Android 首发、iOS 随后跟进，未见 v4 iOS Release Notes 一手证据，01 §10 也列此未决）。
- 证据：`data/dji/raw/api_v4/iOS_DJISDKManager.html`（官方 iOS API Reference 页，经 developer.dji.com 抓取）。

## 9. 为什么 v4 与 v5 不能共用代码（对照表）

官方 4.X→5.X 迁移文档（MSDK V5 教程站，本地 `data/dji/raw/msdkv5_docs_extracted/v-0acaef9a.a4bf24b3.js.txt` / `v-23c38850.ea72e6de.js.txt`）原文映射：

| 能力 | v4 | v5 | 能否复用 |
|---|---|---|---|
| SDK 入口 | `dji.sdk.sdkmanager.DJISDKManager` | `dji.v5.manager.SDKManager` | 否 |
| 注册 | `registerApp(context, callback)`（一步） | `init(...)` + `registerApp()`（两步） | 否 |
| 参数系统 | `DJIKey` + `KeyManager`（`CameraKey.create(...)` 等） | `KeyTools` 创建 + `IKeyManager` 读写 | 否（API 全改） |
| 飞控 | `FlightController`（组件） | `FlightControllerKey`（ActionKey + KeyListener） | 否 |
| 航线 | `WaypointMission` + `WaypointMissionOperator`（对象上传） | `WaypointMissionManager` + KMZ/WPML（文件上传） | 否（数据模型都不同） |
| 相机/云台 | `Camera`/`Gimbal` 组件 | `CameraKey`/`GimbalKey` | 否 |
| 媒体 | `MediaManager`（组件） | `MediaDataCenter` + `IMediaManager` | 否 |
| 虚拟摇杆 | `FlightController.setVirtualStickModeEnabled` + `FlightControllerKeys.VIRTUAL_STICK_CONTROL_MODE_ENABLED` | `VirtualStickManager` + `KeySendVirtualStickFlightControlData` | 否 |
| 平台 | Android + iOS | 仅 Android | 否 |
| 机型 | 至 Mini 2/SE、Mavic 2 等旧机型 | Mini 3/3 Pro/4 Pro、Mavic 3E、M30、M300/350、Matrice 4 等 | 不重叠 |

工程结论：
- 如果项目将来同时要支持 Mini 2（v4）与 Mini 4 Pro（v5），必须做**两个 App 或两个 flavor**，公共逻辑只能放在"任务 JSON / HTTP 协议层"（即本项目 `llm_drone` 的 Drone Agent 契约），不能放在 SDK 调用层。
- 本项目 Phase-2 选用 Mini 4 Pro → 只写 v5（08 文档）；09 仅作为"legacy 路线 + 对照证据"保留。

## 10. 证据索引

| 内容 | URL | 本地证据 |
|---|---|---|
| v4 仓库 README（4.18/Maven/混淆/集成文档入口） | https://github.com/dji-sdk/Mobile-SDK-Android | data/dji/raw/api_v4/Mobile-SDK-Android-README.md |
| v4 DJISDKManager API | https://developer.dji.com/api-reference/android-api/Components/SDKManager/DJISDKManager.html | data/dji/raw/api_v4/DJISDKManager.html |
| v4 FlightController API | https://developer.dji.com/api-reference/android-api/Components/FlightController/DJIFlightController.html | data/dji/raw/api_v4/DJIFlightController.html |
| v4 WaypointMissionOperator API | https://developer.dji.com/api-reference/android-api/Components/Missions/DJIWaypointMissionOperator.html | data/dji/raw/api_v4/DJIWaypointMissionOperator.html |
| v4 WaypointMission API | https://developer.dji.com/api-reference/android-api/Components/Missions/DJIWaypointMission.html | data/dji/raw/api_v4/DJIWaypointMission.html |
| v4 iOS DJISDKManager API | https://developer.dji.com/api-reference/ios-api/Components/SDKManager/DJISDKManager.html | data/dji/raw/api_v4/iOS_DJISDKManager.html |
| v4 产品页 / Hardware Introduction | https://developer.dji.com/mobile-sdk-v4/ | data/dji/raw/msdk_v4_landing.html、msdk_v4_product_intro.html |
| v4 Release 时间轴（4.16→4.18） | https://github.com/dji-sdk/Mobile-SDK-Android/releases | 01 文档 §1.5（经 api.github.com 拉取） |
| 4.X→5.X API 映射（官方迁移文档） | https://developer.dji.com/doc/mobile-sdk-tutorial/en/ | data/dji/raw/msdkv5_docs_extracted/v-0acaef9a.a4bf24b3.js.txt、v-23c38850.ea72e6de.js.txt |
| 官方兼容表（Mini 2/SE 支持判定） | https://support.dji.com/help/content?customId=01700000763&spaceId=17&re=CN&lang=zh-CN | data/dji/raw/sdk_compat_cn.html |
| v4 SDKManagerCallback 接口（onRegister 等 7 方法） | https://developer.dji.com/api-reference/android-api/Components/SDKManager/DJISDKManager_DJISDKManagerCallbackInterface.html | data/dji/raw/api_v4/DJISDKManager_DJISDKManagerCallbackInterface.html |
| v4 WaypointMission.Builder（Builder 方法全集） | https://developer.dji.com/api-reference/android-api/Components/Missions/DJIWaypointMission_Builder.html | data/dji/raw/api_v4/DJIWaypointMission_Builder.html |
| v4 MissionControl（getWaypointMissionOperator） | https://developer.dji.com/api-reference/android-api/Components/Missions/DJIMissionControl.html | data/dji/raw/api_v4/DJIMissionControl.html |
| v4 WaypointMissionOperatorListener（5 个回调） | https://developer.dji.com/api-reference/android-api/Components/Missions/DJIWaypointMissionOperator_Listener.html | data/dji/raw/api_v4/DJIWaypointMissionOperator_Listener.html |
| v4 DJIAircraft（组件访问 getFlightController/getCameras/getGimbals/getBattery） | https://developer.dji.com/api-reference/android-api/Products/Aircraft/DJIAircraft.html | data/dji/raw/api_v4/DJIAircraft.html |
| v4 枚举值（FinishedAction/HeadingMode/FlightPathMode/GotoWaypointMode） | https://developer.dji.com/api-reference/android-api/Components/Missions/DJIWaypointMission.html | data/dji/raw/api_v4/DJIWaypointMission.html |

## 11. 未决问题

1. ~~v4 `WaypointMission.Builder` 字段方法名未核对~~ → **已核对**（`api_v4/DJIWaypointMission_Builder.html`）：`addWaypoint(Waypoint)`、`waypointCount(int)`、`maxFlightSpeed(float)`、`autoFlightSpeed(float)`、`gotoFirstWaypointMode(...)`、`finishedAction(...)`、`headingMode(...)`、`flightPathMode(...)`、`repeatTimes(int)`、`build()` 均为官方签名；§6 代码片段已按此对齐（旧 TODO 作废）。
2. Mini 2/Mini SE 在 v4.16 的相机/云台能力上限（是否支持间隔拍照 `PhotoIntervalShootSettings`、曝光 Key）未从一手文档确认 → 若做 3DGS 采集需真机验证。
3. v4 iOS 对 Mini 2 的最低版本（4.16 是否 iOS 首发）无一手 Release Notes，标 `TODO(未确认)`。
4. 官方兼容表称 Mavic Mini 支持 SDK（论坛 4.13 起[二级]），但 v4 README 与 API 文档未列 Mini 系列（文档滞后）——以兼容表 + Release Notes 为准。

## 12. Mini 2 / Mini SE 做 3DGS 采集的 v4 SOP（半自动 → 自动）

前提：Mini 2 相机 1/2.3 英寸 12MP、无 D-Log（见 02 文档），采集质量弱于 Mini 3/4 Pro；如果只是为了验证整条链路（SDK→照片→3DGS→UE5），Mini 2 是成本最低的 v4 入口。

步骤 1：设备与固件
- 手机（Android 或 iOS）+ RC-N1 + Mini 2/SE；固件与 DJI Fly 都升到最新；先在 DJI Fly 里完成激活与绑定。
- 关闭手机的省电优化，允许 USB 附件；关闭 DJI Fly 后台，避免与自研 App 抢 USB。

步骤 2：航线规划（v4 是对象上传，不是 KMZ）
- 在地图上选区域，生成网格航点（本项目可由 `plan_capture_mission` 生成同一套 waypoints JSON），再转成 `WaypointMission.Builder()`。
- 参数：相对高度 40–80m、速度 3–6m/s、机头朝向 AUTO、完成动作 GO_HOME、重复 1 次；航点动作只在需要处加「拍照」。
- 上传前用 `mission.checkParameters()` 预检，再 `loadMission` + `uploadMission`。

步骤 3：采集（两种模式）
- 模式 A：航点动作拍照（每个航点触发一次 takePhoto）。优点是同步可控；缺点是拍照间隔受飞控动作调度影响。
- 模式 B：相机间隔拍照（`Camera` 组件设置 PHOTO_INTERVAL，或 v4 Key 的 `CameraKey.PHOTO_TIME_INTERVAL_SETTINGS`）。优点是不依赖航点动作；缺点是开始/停止时机要自己控制。
- 3DGS 建议：模式 B + 飞行速度与间隔匹配（相邻照片重叠 ≥60%），并在起飞前手动对焦到无穷远、锁定曝光/白平衡。

步骤 4：回收与下载
- 任务结束 GO_HOME 或手动降落；用 `MediaManager` 拉列表下载原片（或直接拔 SD 卡读卡器，工程上更稳）。
- 照片元数据以 EXIF/XMP 为准（03/04 文档），SDK 遥测只作为辅助；下载后跑一遍 `pipeline` 的元数据解析，确认 GPS/云台/时间可用。

步骤 5：失败面预案
- 注册失败（App Key/包名）→ 换官方 Sample 验证是环境还是代码问题。
- USB 连不上 → 换数据线、换 USB 口、确认遥控器固件、确认手机支持 OTG/AOA。
- 航线上传失败 → 先 checkParameters，再检查飞机 GPS/电机状态/是否已连接。
- 任务中断 → v4 可用 `getPreviousInterruption` 拿中断信息，但 Mini 2 是否支持断点恢复未确认（TODO(未确认)），保守做法是重新上传。

## 13. v4 代码库维护与迁移建议

1. 独立分支/独立 App：v4 依赖 `com.dji:dji-sdk:4.18`，v5 依赖 `com.dji:dji-sdk-v5-aircraft:5.20.1`，两者包名与依赖冲突，不能放同一个 App；建议两个工程或两个 productFlavor + 两套源码集。
2. 公共层只在协议层：任务 JSON、HTTP 契约、安全校验、照片元数据格式全部放共享库（本项目 llm_drone 的做法），SDK 调用层各写各的。
3. 不升级 v4 到 v5：官方没有迁移工具，模型从对象式（FlightController/WaypointMission）变为 Key + KMZ，重写成本约等于新做；机型不重叠（Mini 2 vs Mini 3/4）时没有迁移动力。
4. 安全：v4 同样受 DJI 使用条款约束（不得解除限高/围栏/逆向）；采集前检查固件 FlySafe 数据版本。

## 14. v4 常见坑（按出现频率）

1. `compile` / `provided` 是旧 Gradle 语法，新工程要改 `implementation` / `compileOnly`。
2. 忘记 `startConnectionToProduct()`：只注册不连接，`getProduct()` 永远为空。
3. `onProductChange` 里缓存了旧的组件引用：机型/固件变化后要重新 `getFlightController()/getCamera()`。
4. 航线 `loadMission` 返回非空即参数错误，但很多人忽略返回值直接 upload → 必失败。
5. `WaypointMission` 的航点数、速度、高度范围随机型不同，Mini 2 的上限未在一手文档列出（TODO(未确认)），先小航线试。
6. RTH 高度 `setGoHomeHeightInMeters` 官方范围 [20,500]，设太小可能撞障碍，设太大可能超法规限高（本项目默认 ≤120m）。
7. iOS/Android 两端 API 名字不同（registerApp vs registerAppWithDelegate），不要复制粘贴。
8. v4 的 Key 系统（`DJIKeyManager`）与 v5 的 `IKeyManager` 不同构，Key 字符串/类型不能复用。

## 15. Mini 2（v4）与 Mini 4 Pro（v5）的工程取舍

| 维度 | Mini 2 + v4 | Mini 4 Pro + v5 |
|---|---|---|
| 相机 | 1/2.3 英寸 12MP，无 D-Log | 1/1.3 英寸 48MP，支持 D-Log M/HLG |
| SDK 平台 | Android + iOS | 仅 Android |
| 遥控器 | RC-N1（手机夹持） | RC-N2 / RC-N3 |
| 航线上传 | 内存对象（WaypointMission） | KMZ 文件（WPML） |
| 断点续飞 | 未确认（TODO） | 官方不保证（Mini 不在列表） |
| 第三方 App | Litchi / Dronelink 成熟 | Litchi Pilot / Dronelink（Android） |
| 采集质量（3DGS） | 纹理弱、细节少；小场景/低预算可用 | 纹理强、动态范围好；推荐主采集机型 |
| 代码成本 | 一套 v4 App（对象式，逻辑直观） | 一套 v5 App（Key + KMZ，学习曲线陡） |
| 结论 | 只适合验证链路/低预算 | 本项目 Phase-2 推荐 |

如果项目已有 Mini 2 设备而不想买新机：建议先用 DJI Fly 手动/定时拍照完成一次小场景采集，验证 3DGS→UE5 链路，再决定是否投入 v4 App 开发。理由：v4 App 的开发量并不比 v5 小（要处理注册/连接/航线/相机/媒体一整套），而 Mini 2 的画质上限会限制最终重建质量。

如果最终要交付「LLM 自动调度」demo：必须用 Mini 3/3 Pro/4 Pro 的 v5 Android 路线（01 文档已论证），因为只有 v5 才能在程序里生成并下发 KMZ 航线，且 LLM 生成的航点可以直接转成 WPML，不需要人工在 DJI Fly 里画点。

## 16. 结论（给本项目的一句话）

Mini 2 / Mini SE / Mavic Mini 确实可以用 MSDK v4.16+ 做程序化控制（注册→连接→FlightController→WaypointMissionOperator→Camera），Android 与 iOS 都有官方 v4 路径；但 v4 已停止新增机型，Mini 3 及以后全部走 v5（仅 Android），两代 SDK 的包名、类名、任务模型（对象 vs KMZ 文件）、Key 体系完全不兼容，**不能共用代码**。因此本项目 Phase-2 只实现 v5；v4 仅作为「已有 Mini 2 设备时的 legacy 备选」，且需接受 1/2.3 英寸传感器带来的 3DGS 画质上限。

## 17. 对研发的落地建议

1. 不要为了「兼容所有 Mini」做抽象层：v4/v5 的 SDK 调用层无法抽象成同一套接口（回调类型、Key 模型、任务模型都不同），抽象收益远小于维护成本。把抽象放在更上层——任务 JSON、HTTP 契约、安全规则、元数据格式。
2. 如果团队只有 Android 开发：v4 与 v5 都可行；如果只有 iOS 开发：只能做 Mini 2/SE 的 v4 路线，Mini 3/3 Pro/4 Pro 无官方 iOS SDK，不要相信「v5 iOS 测试版」之类非官方说法。
3. 采购建议：新项目直接买 Mini 3 Pro / Mini 4 Pro + RC-N2/N3（手机夹持式），避开带屏遥控器；Mini 2 只作为已有资产利用。
4. 文档留存：v4 的官方文档站仍可访问（developer.dji.com/mobile-sdk/documentation/...），但页面不再更新，遇到与 Mini 2 不符的地方以 Release Notes + 真机日志为准。
