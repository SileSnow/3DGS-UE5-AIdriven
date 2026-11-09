# MSDK v5.20.1 API 符号核验证据（task-10）

> 目的：为 `mapping.json` / `DESIGN.md` 的每条“工具 → MSDK API”映射提供**可复现的一手证据**，避免只凭记忆或二手博客。
> 核验日期：2026-11-08。所有符号均来自 DJI 官方发布物（Maven Central 构件 + 官方 GitHub sample），未做真机调用验证（真机验证见 `REAL_DRONE_TEST.md`）。

## 1. 证据来源与复现方法

| # | 来源 | 用途 | 复现方式 |
|---|---|---|---|
| E1 | `com.dji:dji-sdk-v5-aircraft-provided:5.20.1`（Maven Central，JAR 20,609,447 B，2026-11-05 发布） | 编译期 API 符号：Key 常量、泛型签名、Manager 接口方法、枚举值、Listener 方法 | 下载 `https://repo1.maven.org/maven2/com/dji/dji-sdk-v5-aircraft-provided/5.20.1/dji-sdk-v5-aircraft-provided-5.20.1.jar`，解压后扫描 `dji/**/*.class` 的常量池（字段名/泛型 Signature 属性/方法名） |
| E2 | `com.dji:dji-sdk-v5-aircraft:5.20.1`（AAR 133,651,350 B） | 机型能力清单：`assets/ProductCapability/DJIMini4Pro/*.json` | 下载 AAR（zip）解压，读取 6 个 `DJIMini4Pro*Capability.json` |
| E3 | 官方 sample 仓库 `dji-sdk/Mobile-SDK-Android-V5@dev-sdk-main` | 真实调用写法（注册、起飞、航点、相机、媒体、虚拟摇杆、POI） | 通过 `cdn.jsdelivr.net/gh/dji-sdk/mobile-sdk-android-v5@dev-sdk-main/SampleCode-V5/...` 获取；关键文件见 §5 |
| E4 | 官方依赖坐标 `SampleCode-V5/android-sdk-v5-as/dependencies.gradle` | build.gradle 版本与仓库 | 官方 sample 原文：`deps.aircraft = "com.dji:dji-sdk-v5-aircraft:5.20.1"`、`deps.wpmzSdk = 'com.dji:wpmzsdk:1.0.5.2'`、仓库 `https://repo1.maven.org/maven2` |
| E5 | `data/dji/raw/text/relnotes_all.txt`（前序调研落盘，官方 Release Notes 全文） | 版本-机型-固件对应（Mini 4 Pro 自 5.13.0 起） | 见 `docs/research/01_DJI_Mini_SDK能力矩阵.md` §1.4 |

> 说明：E3 的 wpmzsdk 类（`com.dji.wpmzsdk.*`）未在 E1/E2 中核验到（E4 显示其为独立构件 `com.dji:wpmzsdk:1.0.5.2`）。凡是只由 sample 代码证明的调用，状态标注为 `sample-verified`；未拿到定义者标注 `TODO(未确认)`。

## 2. 关键类与泛型签名（E1 扫描）

### 2.1 Key 常量类（字段名 → 泛型签名）

`dji.sdk.keyvalue.key.FlightControllerKey`（继承 `DJIFlightControllerKey`，Java 静态字段可经子类访问）：

| 字段 | 签名 | 用途 |
|---|---|---|
| KeyStartTakeoff | `DJIActionKeyInfo<EmptyMsg,EmptyMsg>` | 起飞（自动升到约 1.2m 悬停，无高度参数） |
| KeyStopTakeoff | `DJIActionKeyInfo<...>` | 中止起飞 |
| KeyStartAutoLanding | `DJIActionKeyInfo<EmptyMsg,EmptyMsg>` | 自动降落 |
| KeyStopAutoLanding | `DJIActionKeyInfo<...>` | 取消降落 |
| KeyConfirmLanding | `DJIActionKeyInfo<EmptyMsg,EmptyMsg>` | 降落确认（需确认场景） |
| KeyStartGoHome / KeyStopGoHome | `DJIActionKeyInfo<EmptyMsg,EmptyMsg>` | 一键返航 / 中止返航 |
| KeyGoHomeHeight | `DJIKeyInfo<Integer>` | 返航高度（m），可 set |
| KeyGoHomeState（子类 `FlightControllerKey`） | `DJIKeyInfo<FCGoHomeState>` | 返航状态 |
| KeyGoHomeStatus（同名于子类，另一类型） | `DJIKeyInfo<GoHomeState>` | 返航/降落状态 |
| KeyFlightMode（子类） | `DJIKeyInfo<FlightMode>` | 飞行模式 |
| KeyFCFlightMode | `DJIKeyInfo<FCFlightMode>` | 飞控模式（底层） |
| KeyIsFlying | `DJIKeyInfo<Boolean>` | 是否在空中 |
| KeyIsFailsafe | `DJIKeyInfo<Boolean>` | 失控保护状态 |
| KeyAircraftLocation | `DJIKeyInfo<LocationCoordinate2D>` | 经纬度 |
| KeyAircraftLocation3D | `DJIKeyInfo<LocationCoordinate3D>` | 经纬度+高度 |
| KeyAltitude | `DJIKeyInfo<Double>` | 相对起飞点高度（m） |
| KeyTakeoffLocationAltitude | `DJIKeyInfo<Double>` | 起飞点海拔 |
| KeyAircraftVelocity | `DJIKeyInfo<Velocity3D>` | 三轴速度 |
| KeyAircraftAttitude | `DJIKeyInfo<Attitude>` | 姿态（roll/pitch/yaw） |
| KeyCompassHeading | `DJIKeyInfo<Double>` | 罗盘航向 |
| KeyHomeLocation | `DJIKeyInfo<LocationCoordinate2D>` | Home 点 |
| KeyGPSSatelliteCount | `DJIKeyInfo<Integer>` | 卫星数 |
| KeyGPSSignalLevel | `DJIKeyInfo<GPSSignalLevel>` | GPS 等级 |
| KeyGPSIsValid | `DJIKeyInfo<Boolean>` | GPS 是否有效 |
| KeyBatteryPowerPercent | `DJIKeyInfo<Integer>` | 电量（飞控侧，冗余） |
| KeyRemainingFlightTime | `DJIKeyInfo<Integer>` | 剩余可飞秒 |
| KeyIsLowBatteryWarning | `DJIKeyInfo<Boolean>` | 低电量告警 |
| KeyHeightLimit / HeightLimitRange | `DJIKeyInfo<Integer>` / `<IntValueConfig>` | 限高设置/范围 |
| KeyVirtualStickEnabled | `DJIKeyInfo<Boolean>` | 虚拟摇杆使能 |
| KeySimulatorState | `DJIKeyInfo<SimulatorState>` | 模拟器状态 |
| KeyWindSpeed | `DJIKeyInfo<Integer>` | 风速 |

`dji.sdk.keyvalue.key.CameraKey`（继承 `DJICameraKey`）：

| 字段 | 签名 | 用途 |
|---|---|---|
| KeyCameraMode（子类） | `DJIKeyInfo<CameraMode>` | 拍照/录像模式（CameraMode.PHOTO_NORMAL / VIDEO_NORMAL / PHOTO_AEB / PHOTO_INTERVAL …） |
| KeyShootPhotoMode | `DJIKeyInfo<CameraShootPhotoMode>` | 拍照子模式（NORMAL/HDR/BURST/AEB/INTERVAL/…） |
| KeyPhotoFileFormat | `DJIKeyInfo<PhotoFileFormat>` | RAW/JPEG/RAW_JPEG/HEIC… |
| KeyPhotoRatio / KeyPhotoSize（子类） | `DJIKeyInfo<PhotoRatio>` / `<PhotoSize>` | 画幅比例/尺寸 |
| KeyExposureMode | `DJIKeyInfo<CameraExposureMode>` | PROGRAM/SHUTTER_PRIORITY/APERTURE_PRIORITY/MANUAL |
| KeyShutterSpeed | `DJIKeyInfo<CameraShutterSpeed>` | 快门（枚举，含 AUTO） |
| KeyISO | `DJIKeyInfo<CameraISO>` | ISO（枚举，含 ISO_AUTO） |
| KeyExposureCompensation | `DJIKeyInfo<CameraExposureCompensation>` | EV（枚举，-5.0~+5.0） |
| KeyAperture | `DJIKeyInfo<CameraAperture>` | 光圈（Mini 4 Pro 固定，仍可读） |
| KeyCameraMeteringMode | `DJIKeyInfo<CameraMeteringMode>` | 测光 |
| KeyAntiFlicker | `DJIKeyInfo<CameraAntiFlicker>` | 防闪烁 |
| KeyWhiteBalance | `DJIKeyInfo<CameraWhiteBalanceInfo>` | 白平衡 |
| KeyStartShootPhoto / KeyStopShootPhoto | `DJIActionKeyInfo<EmptyMsg,EmptyMsg>` | 拍照（动作） |
| KeyStartRecord / KeyStopRecord | `DJIActionKeyInfo<EmptyMsg,EmptyMsg>` | 录像（动作） |
| KeyIsShootingPhoto / KeyIsRecording / KeyIsTakingPhoto | `DJIKeyInfo<Boolean>` | 拍照/录像状态 |
| KeyPhotoIntervalCountdown | `DJIKeyInfo<Integer>` | 定时拍照倒计时 |
| KeyCameraSDCardState | `DJIKeyInfo<CameraSDCardState>` | SD 卡状态（NORMAL/FULL/NOT_INSERTED/FORMAT_NEEDED…） |
| KeyCameraStorageLocation | `DJIKeyInfo<CameraStorageLocation>` | SDCARD/INTERNAL/INTERNAL_SSD |
| KeyFormatStorage | `DJIActionKeyInfo<CameraStorageLocation,EmptyMsg>` | 格式化存储（危险动作，桥接层不暴露） |
| KeyVideoResolutionFrameRate | `DJIKeyInfo<VideoResolutionFrameRate>` | 视频规格 |
| KeyNewlyGeneratedMediaFile | `DJIKeyInfo<GeneratedMediaFileInfo>` | 新生成照片（含 dir_no/file_no/type） |

`dji.sdk.keyvalue.key.GimbalKey`（继承 `DJIGimbalKey`）：

| 字段 | 签名 | 用途 |
|---|---|---|
| KeyGimbalAttitude | `DJIKeyInfo<Attitude>` | 云台 pitch/roll/yaw（回读） |
| KeyRotateByAngle | `DJIActionKeyInfo<GimbalAngleRotation,EmptyMsg>` | 按角度转云台（set_gimbal 主用） |
| KeyRotateBySpeed | `DJIActionKeyInfo<GimbalSpeedRotation,EmptyMsg>` | 按速度转 |
| KeyGimbalReset | `DJIActionKeyInfo<GimbalResetType,EmptyMsg>` | 回中/自拍等 |
| KeyGimbalMode（子类） | `DJIKeyInfo<GimbalMode>` | FREE/FPV/YAW_FOLLOW |
| KeyGimbalAttitudeRange | `DJIKeyInfo<GimbalAttitudeRange>` | 角度范围（机型能力） |

`GimbalAngleRotation` 字段（E1 字段表）：`mode(GimbalAngleRotationMode: ABSOLUTE_ANGLE/RELATIVE_ANGLE)`、`pitch`、`roll`、`yaw`、`pitchIgnored`、`rollIgnored`、`yawIgnored`、`duration`、`jointReferenceUsed`、`timeout`（单位见 DJI API Reference）。

`dji.sdk.keyvalue.key.BatteryKey`（继承 `DJIBatteryKey`）：`KeyChargeRemainingInPercent<Integer>`、`KeyChargeRemaining`、`KeyVoltage`、`KeyBatteryTemperature<Double>`、`KeyNumberOfCells`、`KeyCellVoltages<List<Integer>>`、`KeyBatteryLife`。

`dji.sdk.keyvalue.key.RemoteControllerKey`（继承 `DJIRemoteControllerKey`）：`KeyConnection<Boolean>`、`KeyFlightModeSwitchState<RCFlightModeSwitch>`、`KeyIsStickNormal<Boolean>`、`KeyStickLeftHorizontal/LeftVertical/RightHorizontal/RightVertical`、`KeyGoHomeButtonDown`、`KeyPauseButtonDown`、`KeyShutterButtonDown`。

`dji.sdk.keyvalue.key.ProductKey`（继承 `DJIProductKey`）：`KeyProductType<ProductType>`、`KeyFirmwareVersion<String>`、`KeyConnection<Boolean>`、`KeySerialNumber<String>`。

### 2.2 Manager 接口方法（E1 扫描，类文件方法表）

| 类 | 方法 |
|---|---|
| `dji.v5.manager.KeyManager` | `getValue` / `getOnce` / `setValue` / `performAction` / `listen` / `cancelListen` / `isKeySupported` / `destroy` |
| `dji.v5.manager.SDKManager` | `init` / `registerApp` / `destroy`（`SDKManagerCallback`：onRegisterSuccess/onRegisterFailure/onProductConnect/onProductDisconnect/onProductChanged/onInitProcess/onDatabaseDownloadProgress/onRemoteServerStateUpdated/onRemoteServerCompatibleError） |
| `dji.v5.manager.aircraft.waypoint3.WaypointMissionManager` | `pushKMZFileToAircraft(String, CompletionCallbackWithProgress<Double>)`、`pushKMZFileToRemote`、`getAvailableWaylineIDs(missionFileName): List<Int>`、`startMission(missionFileName, waylineIDs, cb)`、`startMission(missionFileName, BreakPointInfo, cb)`、`pauseMission(cb)`、`resumeMission(cb)`、`resumeMission(BreakPointInfo, cb)`、`stopMission(missionFileName, cb)`、`queryBreakPointInfoFromAircraft(missionFileName, cb)`、`addWaylineExecutingInfoListener` / `addWaypointActionListener` / `addWaypointMissionExecuteStateListener` |
| `dji.v5.manager.aircraft.virtualstick.VirtualStickManager` | `enableVirtualStick` / `disableVirtualStick` / `speedLevel` / `leftStick` / `rightStick` / `sendVirtualStickAdvancedParam` / `setVirtualStickAdvancedModeEnabled` / `setVirtualStickStateListener` / `isEnabled` |
| `dji.v5.manager.interfaces.IMediaManager`（由 `MediaDataCenter.getInstance().mediaManager` 获取） | `pullMediaFileListFromCamera(PullMediaFileListParam, cb)` / `stopPullMediaFileListFromCamera` / `getMediaFileListData` / `addMediaFileListStateListener` / `setMediaFileDataSource` / `enable` / `disable` / `deleteMediaFiles` / `set/getMediaFileXMPCustomInfo` / `playVideo` / `playVideoToSurface` / `pauseVideo` / `resumeVideo` / `stopVideo` / `seekVideo` |
| `dji.v5.manager.intelligent.IIntelligentFlightManager`（接口）/ `dji.v5.manager.intelligent.IntelligentFlightManager`（单例） | `getPOIMissionManager` / `getFlyToMissionManager` / `getSpotLightManager` / `getSmartTrackMissionManager` / `selectIntelligentModel` / `startAutoSensing` / `stopAutoSensing` |
| `IPOIMissionManager`（extends `IMissionManager`） | `startMission(target, null, cb)` / `stopMission(cb)` / `updateMissionTarget(target, cb)` / `updateMissionParam(POIParam, cb)` / `lockCircularVelocity` / `lockGimbalPitch` |
| `dji.v5.manager.interfaces.IFlyZoneManager` | `getFlyZonesInSurroundingArea` 等禁飞区查询（E1 类存在；方法名以 API Reference 为准，桥接层失败降级为本地禁飞多边形 + `E_NOFLY`） |

### 2.3 媒体文件下载（E1 `MediaFile` 方法表 + E3 `MediaVM.kt`）

- `MediaFile.pullOriginalMediaFileFromCamera(offset: Long, listener: MediaFileDownloadListener)`
- `MediaFileDownloadListener`：`onStart()` / `onProgress(total, current)` / `onRealtimeDataUpdate(ByteArray, position)` / `onFinish()` / `onFailure(IDJIError?)`
- 文件字段：`fileName/fileIndex/dirIndex/fileSize/fileType/date/duration`（getter）
- 列表状态：`MediaFileListState.{IDLE, UP_TO_DATE, UPDATING}`

### 2.4 航点状态与监听器（E1）

- `WaypointMissionExecuteState`：`IDLE / UPLOADING / READY / PREPARING / ENTER_WAYLINE / EXECUTING / INTERRUPTED / RECOVERING / RETURN_TO_START_POINT / FINISHED / DISCONNECTED / NOT_SUPPORTED / UNKNOWN`
- `WaypointMissionExecuteStateListener.onMissionStateUpdate(WaypointMissionExecuteState)`
- `WaylineExecutingInfoListener.onWaylineExecutingInfoUpdate(WaylineExecutingInfo)`、`onWaylineExecutingInterruptReasonUpdate(IDJIError?)`
- `WaylineExecutingInfo` 字段：`missionFileName: String`、`waylineID: Int`、`currentWaypointIndex: Int`
- `WaypointActionListener.onExecutionStart(actionId)` / `onExecutionStart(actionGroup, actionId)` / `onExecutionFinish(actionId, error)` / `onExecutionFinish(actionGroup, actionId, error)`
- `BreakPointInfo` 存在（字段以 API Reference 为准；Mini 4 Pro 断点续飞官方不保证）

### 2.5 枚举（E1 常量池）

| 枚举 | 常量 |
|---|---|
| `FlightMode` | `AUTO_TAKE_OFF / AUTO_LANDING / GPS_NORMAL / GPS_SPORT / GPS_TRIPOD / ATTI / GO_HOME / WAYPOINT / POI / VIRTUAL_STICK / AUTO_AVOIDANCE / APAS / SMART_FLIGHT / TAP_FLY / TIME_LAPSE / PANO / QUICK_MOVIE / MOTOR_START / TAKE_OFF_READY / MANUAL / CSY / ISY / RSY / USY / XSY / DRAW / CLICK_GO / CINEMATIC / FOLLOW_ME / SMART_FLY / MASTER_SHOT / FORCE_LANDING / ATTI_LANDING / UNKNOWN` |
| `FCGoHomeState` | `IDLE / PREASCENDING / ALIGN / ASCENDING / CRUISE / BRAKING / AVOID_ASCENDING / COMPLETED` |
| `GPSSignalLevel` | `LEVEL_NONE / LEVEL_0 / LEVEL_1 / LEVEL_2 / LEVEL_3 / LEVEL_4 / LEVEL_5 / LEVEL_10`（5.10.0 起官方倾向新定位接口，见 TODO） |
| `CameraMode` | `PHOTO_NORMAL / PHOTO_AEB / PHOTO_BURST / PHOTO_INTERVAL / PHOTO_HIGH_RESOLUTION / PHOTO_SUPER_RESOLUTION / PHOTO_HYPER_LIGHT / PHOTO_PANORAMA / VIDEO_NORMAL / UNKNOWN` |
| `CameraShootPhotoMode` | `NORMAL / HDR / BURST / AEB / INTERVAL / STATIONARY_TIME_LAPSE / MOTION_TIME_LAPSE / HYPER_TIME_LAPSE / PANO_APP / RAW_BURST / EHDR / HYPER_LIGHT / HYPER_LAPSE / VISION_PANO / VISION_BOKEH` |
| `CameraExposureMode` | `PROGRAM / SHUTTER_PRIORITY / APERTURE_PRIORITY / MANUAL` |
| `PhotoFileFormat` | `RAW / JPEG / RAW_JPEG / HEIC / RAW_HEIC / TIFF_8_BIT / TIFF_14_BIT / …` |
| `CameraSDCardState` | `NORMAL / NOT_INSERTED / INVALID / READ_ONLY / FORMAT_NEEDED / FORMATTING / FULL / SLOW / …` |
| `GimbalMode` | `FREE / FPV / YAW_FOLLOW` |
| `GimbalAngleRotationMode` | `ABSOLUTE_ANGLE / RELATIVE_ANGLE` |
| `FailsafeAction` | `HOVER / LANDING / GOHOME` |
| `MediaFileListState` | `IDLE / UP_TO_DATE / UPDATING` |
| `ProductType` | 含 `DJI_MINI_4_PRO / DJI_MINI_3_PRO / DJI_MINI_3`（用于连接后机型校验） |
| `ComponentIndexType` | `LEFT_OR_MAIN / RIGHT / UP / FPV / ALL / …`（Mini 4 Pro 单相机用 `LEFT_OR_MAIN`） |

## 3. Mini 4 Pro 机型能力清单（E2，`assets/ProductCapability/DJIMini4Pro/`）

- FC 能力清单：`supportedMSDKVersion = 5.13.0`，`supportedMinFirmwareVersion = 30.05.17.01`；命中键：`KeyConnection / KeyIsFlying / KeyFlightTimeInSeconds / KeyAircraftLocation3D / KeyAircraftAttitude / KeyAircraftVelocity / KeyTakeoffLocationAltitude / KeyGPSSatelliteCount / KeyGPSSignalLevel / KeyCompassHeading / KeyAltitude / KeyFlightMode / KeyHomeLocation / KeyGoHomeHeight / KeyIsFailsafe / KeyWindSpeed` 等。
- Camera 能力清单：`KeyCameraMode / KeyStartShootPhoto / KeyStartRecord / KeyStopRecord / KeyPhotoIntervalCountdown / KeyExposureMode / KeyShutterSpeed / KeyISO / KeyExposureCompensation / KeyPhotoFileFormat / KeyVideoResolutionFrameRate / KeyCameraMeteringMode / KeyAntiFlicker / KeyWhiteBalance` 等。
- Gimbal 能力清单：`KeyGimbalMode / KeyGimbalAttitude / KeyRotateByAngle / KeyRotateBySpeed / KeyGimbalReset`。
- **注意**：能力清单是“该机型开放的能力子集”，不等于 SDK 全集。桥接层访问任何 Key 前调用 `KeyManager.isKeySupported(key)`，不支持 → `E_NOT_SUPPORTED`（审计），不要假设所有 Key 在 Mini 4 Pro 上可用。
- 电量以 `BatteryKey.KeyChargeRemainingInPercent` 为准（Mini 4 Pro Battery 能力清单命中）；`FlightControllerKey.KeyBatteryPowerPercent` 作冗余交叉校验。

## 4. 未验证 / 待真机确认清单（不隐藏风险）

1. `GimbalAngleRotation` 的角度符号约定（pitch 负值向下？）与速率/限位：需真机回读 `KeyGimbalAttitude` 校验。
2. `wpmzsdk`（`com.dji:wpmzsdk:1.0.5.2`）的 `WPMZManager.generateKMZFile` 精确签名/返回值：官方 sample 中为 `WPMZManager.getInstance().generateKMZFile(kmzOutPath, waylineMission, missionConfig, template)`，返回/异常语义 `TODO(未确认)`。
3. `WaylineWaypoint` / `WaylineMissionConfig` / `Template` 的构造与 setter 字段集：sample 中通过 `setXxx()` 逐项构造（见 E3 `KMZTestUtil.java`），桥接层以 sample 写法为基线，真机联调前用 WPML 静态校验兜底。
4. `KeyGPSSignalLevel` 自 5.10.0 起官方建议改用新定位接口（Release Notes 口径），本桥先保留并叠加 `KeyGPSSatelliteCount/KeyGPSIsValid`，不单独依赖该枚举。
5. `RemoteControllerKey.KeyConnection` 与 `ProductKey.KeyConnection` 的语义差异（链路 vs SDK 连接）：预检两者都要 true。
6. `IFlyZoneManager` 具体方法名/回调结构未逐字核验：桥接层调用失败时降级为“本地禁飞多边形校验 + 标记 flyzone_api=unavailable”，绝不因查询失败而放行。

## 5. 官方 sample 参考文件（E3）

| 文件（仓库相对路径） | 用途 |
|---|---|
| `SampleCode-V5/android-sdk-v5-sample/src/main/java/dji/sampleV5/aircraft/models/MSDKManagerVM.kt` | SDK 初始化：`SDKManager.getInstance().init(appContext, InitSettings(SDKLinKMode.LOCAL), SDKManagerCallback)` + `registerApp()` |
| `.../models/BasicAircraftControlVM.kt` | `KeyStartTakeoff` / `KeyStartAutoLanding` 的 `.create().action(...)` 写法 |
| `.../models/WayPointV3VM.kt` | `pushKMZFileToAircraft` / `getAvailableWaylineIDs` / `startMission` / 状态监听 |
| `.../models/MediaVM.kt` | `KeyCameraMode=PHOTO_NORMAL` + `KeyStartShootPhoto`；`MediaFile.pullOriginalMediaFileFromCamera` |
| `.../models/VirtualStickVM.kt` | `VirtualStickManager` 使能/速度/高级参数 |
| `.../models/IntelligentFlightVM.kt` | `IntelligentFlightManager.poiMissionManager.startMission(target, null, cb)`、`updateMissionParam(POIParam)` |
| `.../utils/KMZTestUtil.java` | `WaylineMissionConfig` / `Template` / `WaylineWaypoint` / `WaylineActionInfo`（TAKE_PHOTO/GIMBAL_ROTATE/HOVER）构造 |
| `.../models/MSDKManagerVM.kt`、`.../DJIApplication.kt` | App 生命周期内保持 SDK 回调、`destroy()` |
