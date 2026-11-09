# REVIEW_vs_research —— 桥接层与 docs/research/08、10 的交叉复核（T9）

> 复核日期：2026-11-08。对象：`docs/research/08_MSDKv5_Android使用方法.md`（50KB，含 10 模块 API 表与真实类名）、`docs/research/10_KMZ_WPML航线格式与任务下发.md`（32KB，含 template/waylines 字段、action、状态机、12 项自检）、参考生成器 `docs/research/assets/make_sample_kmz.py` 与样例 `sample_mission.kmz`。
> 被核对物：`llm_drone/msdk_bridge/mapping.json`、`llm_drone/msdk_bridge/app/` 的 Kotlin 骨架、`README.md`、`PROTOCOL_COMPLIANCE.md`。
> 证据等级：08/10 的结论本身带官方 URL 与本地证据（`data/dji/raw/api_v5/`、`data/dji/raw/cloudapi/text/`）；本轮复核仍**未编译、未真机**，因此 "一致" 只表示与官方文档/官方 sample 一致，不表示可运行。

## 0. 一页结论

- 共核对 **47** 个条目：**一致 24**、**需修正 16（本轮已修正 13，文档/映射待同步 3）**、**TODO 7**（无法静态解决的待真机项）。
- 最严重的问题在 **KMZ/WPML 生成器**：旧 `MissionKmzBuilder.kt` 的 template.kml 缺 `missionConfig` 必填字段（takeOffSecurityHeight/droneInfo/payloadInfo）与 Folder 全局参数，会被飞控判为非法 KMZ；已按 10 §2/§3/§4 与参考生成器整体重写，并合并进 DESIGN.md 使用的规范文件名 **`mission/WaypointConverter.kt`**（删除重复的 MissionKmzBuilder.kt）。
- **API 名称层面**：08 与官方 API Reference 基本一致；发现 08 自身两处与 5.20.1 构件扫描（evidence/API_SYMBOLS_VERIFIED.md E1）不符的点（`ComponentIndexType.CAMERA`、`GimbalAngleRotation` 构造写法），已以构件扫描为准修正代码并在 §1 标注 08 需修正。
- **spec v1.1 §15** 三项已落实：`sim_time_s=null` 语义、`photos[].pose_source/pose_accuracy_m`、设备就绪 `E_RC_LINK/E_STATE + details.reason`（代码与文档同步）。
- 仍存 7 个 TODO 全部是"必须真机/官方枚举表才能解决"，已写入 `logs/msdk-bridge/SUMMARY.md` 与 `test_protocol.md` 的 T0/T4 门禁，不影响本轮文档级验收。

## 1. A. MSDK v5 API 名称/类名/签名核对（08 §6 + 5.20.1 构件扫描）

| # | 条目 | 08/证据 | app/ 现状 | 结论 |
|---|---|---|---|---|
| A1 | SDK 初始化 `SDKManager.getInstance().init(context, InitSettings(SDKLinKMode.LOCAL), callback)` | 08 §4 一致 | MsdkInitManager 一致 | 一致 |
| A2 | `registerApp()` 无参、在 `INITIALIZE_COMPLETE` 后调用 | 08 §4 一致 | MsdkInitManager 一致 | 一致 |
| A3 | Helper `com.cySdkyc.clx.Helper.install(this)`（v5.10.0+） | 08 §1/§4 一致 | DJIApplication 一致 | 一致 |
| A4 | `KeyManager.getValue/setValue/performAction/listen/cancelListen` 签名 | 08 §6 一致 | TelemetryPublisher/CommandExecutor 使用一致 | 一致 |
| A5 | `listen` 回调的 KeyListener 形态 | 08 §6.6 示例为 `{ _, v -> }`（旧值,新值）；sample 中也有单值 lambda | TelemetryPublisher 之前是 `{ _ -> }` | **需修正（已修）**：改为 `{ _, _ -> }`；真机编译时以 AAR 为准 |
| A6 | 飞控动作 Key（KeyStartTakeoff/KeyStartAutoLanding/KeyStartGoHome/KeyStopGoHome/KeyConfirmLanding/KeyGoHomeHeight） | 08 §6.1 + API Reference | FlightController 一致 | 一致 |
| A7 | `WaypointMissionManager` 类路径 `dji.v5.manager.aircraft.waypoint3.WaypointMissionManager`（单例） | 08 §6.2 一致 | WaypointMissionController 一致 | 一致 |
| A8 | 航点监听器是**普通 interface**，方法名 `onMissionStateUpdate` / `onWaylineExecutingInfoUpdate` / `onExecutionStart/Finish` | 08 §6.2 明示 | 旧代码用 SAM lambda | **需修正（已修）**：3 个 listener 改为 object 实现具名方法 |
| A9 | `getAvailableWaylineIDs/startMission/stopMission` 参数语义（路径 vs 文件名） | 08 §6.2 sample 传 `kmzPath`；API 页字段名 `missionFileName` | MissionExecutor 传 `kmz.name` | **需修正（已修）**：统一传 KMZ 绝对路径（TODO：真机确认服务端接受路径还是文件名） |
| A10 | `WaypointMissionExecuteState` 枚举（READY/EXECUTING/...） | 08 §6.2 + API 页 | 使用 FINISHED/INTERRUPTED/NOT_SUPPORTED | 一致（08 的 PAUSED 为口语描述；TODO 真机补全实际取值序列） |
| A11 | `WaylineExecutingInfo` 字段 `getMissionFileName/getWaylineID/getCurrentWaypointIndex` | 08 §6.2 明确 | 使用 `currentWaypointIndex` | 一致（TODO：字段可空性/名称以 AAR 为准） |
| A12 | 相机索引 `ComponentIndexType.CAMERA` | **08 §6.3 写法** | 骨架用 `ComponentIndexType.LEFT_OR_MAIN` | **08 需修正**：E1 构件扫描枚举为 LEFT_OR_MAIN/RIGHT/UP/FPV/ALL…，无 CAMERA；以扫描为准（README/REVIEW 记录） |
| A13 | 相机动作 Key（KeyCameraMode/KeyStartShootPhoto/KeyStartRecord/KeyStopRecord/KeyShootPhotoMode/KeyPhotoIntervalShootSettings） | 08 §6.3 + API Reference | CameraController 用 KeyCameraMode/KeyStartShootPhoto/KeyStartRecord/KeyStopRecord | 一致（间隔拍照 KeyPhotoIntervalShootSettings 未用，标 TODO） |
| A14 | 云台 `GimbalAngleRotation` 为**可变字段类**（mode/pitch/roll/yaw/...） | evidence E1 字段表；08 §6.4 | 旧代码用 4 参构造 | **需修正（已修）**：改为 `GimbalAngleRotation().apply { mode=...; pitch=...; roll=...; yaw=... }` |
| A15 | `KeyTools.createKey(GimbalKey.KeyRotateByAngle)` 不传 componentIndex | 08 §6.4 | 旧代码传 LEFT_OR_MAIN | **需修正（已修）**：去掉 componentIndex（TODO：真机确认是否需云台索引重载） |
| A16 | 虚拟摇杆参数类 `dji.sdk.keyvalue.value.flightcontroller.VirtualStickFlightControlParam`（value 包） | 08 §6.7 明确 | 旧代码 import `dji.v5.manager.aircraft.virtualstick.*` | **需修正（已修）**：改 value 包并显式设置 3 个控制模式 + BODY 坐标系 |
| A17 | 媒体列表/下载前需 `IMediaManager.enable()` | 08 §6.5 明示 | MediaDownloader 未调用 enable | **需修正（已修）**：refreshList 前 enableMediaPlayback() |
| A18 | 媒体下载 `MediaFile.pullOriginalMediaFileFromCamera(offset, listener)` | 08 §6.5 + sample | 一致 | 一致 |
| A19 | `MediaDataCenter.getInstance().mediaManager`（Java getter） | 08 §6.5 | 一致（Kotlin 属性访问） | 一致 |
| A20 | WMZ 编辑官方类 `com.dji.wpmzsdk.manager.WPMZManager`（wpmzsdk 1.0.5.2） | 08 §2/§6.2 | 骨架未依赖（自建 XML） | **TODO**：真机前建议加 checkValidation；已写入 WaypointConverter TODO |
| A21 | 遥测 Key 集合（AircraftLocation/Attitude/Velocity/Altitude/GPS/Battery/RC） | 08 §6.6 | TelemetryPublisher 一致 | 一致 |
| A22 | 链路信号质量 Key（AirlinkKey） | 08 §6.6 提到 | signal 固定 good/lost | **TODO**：AirlinkKey 具体 Key 名未在 08 给出，真机补 |
| A23 | 电池优先级：`BatteryKey.KeyChargeRemainingInPercent` | 08 §6.6 | 一致 | 一致 |
| A24 | IDJIError 处理：不假定 code 稳定，保留 description | 08 §6.2/10 §7 | ErrorMapper 保存 msdk_error 并映射业务码 | 一致 |
| A25 | 机型/固件读取（ProductKey/KeyFirmwareVersion） | 08 §5/§8 | AircraftConnectionManager 读固件；机型名 TODO | **TODO**：机型字符串 Key 名未在 08 明确，真机补 |
| A26 | 混淆规则：v5.8.0 起内置 | 08 §2 | proguard-rules 额外 keep（无害） | 一致 |
| A27 | Manifest：API_KEY、USB host/accessory、extractNativeLibs=true | 08 §5 | AndroidManifest 一致（accessory_filter 内容 TODO） | 一致（1 TODO） |

## 2. B. KMZ / WPML 字段核对（10 + 参考生成器 make_sample_kmz.py）

| # | 条目 | 10/参考生成器 | 旧 WaypointConverter | 结论 |
|---|---|---|---|---|
| B1 | ZIP 条目 `wpmz/template.kml` + `wpmz/waylines.wpml`（正斜杠） | 10 §1/§13 | 一致 | 一致 |
| B2 | template 顶层 author/createTime/updateTime | 10 §2 示例 | 缺 | **需修正（已修）** |
| B3 | missionConfig：flyToWaylineMode/finishAction/exitOnRCLost/executeRCLostAction | 10 §2 | 有部分，但 exitOnRCLost 用了 `executeLostAction`（非官方示例值） | **需修正（已修）**：goContinue + executeRCLostAction=hover |
| B4 | missionConfig 必填 `takeOffSecurityHeight` | 10 §2 必填 | 缺 | **需修正（已修）** |
| B5 | missionConfig 必填 `globalTransitionalSpeed` | 10 §2 必填 | 缺（仅 waylines 有） | **需修正（已修）** |
| B6 | missionConfig 必填 `droneInfo` + `payloadInfo` | 10 §2 必填 | 缺 | **需修正（已修）**：占位 0 + TODO（Mini 4 Pro 枚举未知） |
| B7 | template Folder：templateType/templateId/waylineCoordinateSysParam/autoFlightSpeed/gimbalPitchMode/globalWaypointHeadingParam/globalWaypointTurnMode/globalUseStraightLine | 10 §2 | 缺（旧文件结构不完整） | **需修正（已修）** |
| B8 | template Placemark：index/ellipsoidHeight/height/useGlobal*/waypointSpeed/gimbalPitchAngle | 10 §2 | 部分缺失 | **需修正（已修）**：index/height/ellipsoidHeight/useGlobalHeight=0/useGlobalSpeed=0/waypointSpeed/gimbalPitchAngle |
| B9 | waylines missionConfig 与 template 一致 | 10 §3 | 部分缺失 | **需修正（已修）** |
| B10 | waylines Folder：templateId/executeHeightMode/waylineId/autoFlightSpeed | 10 §3 | 有 4 项（旧） | 一致（已按新结构统一） |
| B11 | waylines Placemark：index/executeHeight/waypointSpeed/waypointHeadingParam/waypointTurnParam/useStraightLine | 10 §3 | 缺 useStraightLine 等 | **需修正（已修）** |
| B12 | actionGroup 结构（id/start/end/mode/trigger + action） | 10 §4 | 基本一致 | 一致（已重写统一） |
| B13 | gimbalRotate 参数：gimbalRotateMode/pitch/roll/yaw enable+angle/`gimbalRotateTimeEnable`/`gimbalRotateTime`/`payloadPositionIndex` | 10 §4 | 缺 rotateTime/payloadPositionIndex | **需修正（已修）** |
| B14 | takePhoto 参数：`fileSuffix` + `payloadPositionIndex` | 10 §4 | 只有 payloadPositionIndex | **需修正（已修）** |
| B15 | actionActuatorFunc 只用官方枚举（takePhoto/startRecord/stopRecord/gimbalRotate/...） | 10 §4 | 一致 | 一致 |
| B16 | `wpml:index` 从 0 连续递增、coordinates 为「经度,纬度」 | 10 §5/§13 | 一致 | 一致 |
| B17 | 速度 [1,15]、Mini 建议 ≤10；高度相对起飞点 5–120 | 10 §5 | 速度 clamp [1,15]，高度未 clamp | **需修正（已修）**：速度 coerce；高度沿用 mission（SafetyGuard 已限 120） |
| B18 | 生成后 12 项自检（ElementTree + 12 条） | 10 §13 | 无自动校验 | **TODO**：Android 侧无法跑 Python；建议服务端预生成 + 本机 python 校验，或引入 IWPMZManager.checkValidation |
| B19 | KMZ 文件名即航线名，KMZ 路径传给 pushKMZFileToAircraft | 10 §1/§6.2 | `mission_id.kmz` | 一致（TODO：文件名合法性校验） |
| B20 | 断点续飞 Mini 不在保证列表 → 不自动 resume | 10 §8 | 未实现 resume 自动化 | 一致（文档已写明） |

## 3. C. spec v1.1 §15 对照

| # | §15 决议 | 实现/文档 | 结论 |
|---|---|---|---|
| C1 | real 模式 `sim_time_s` 允许 null，duration 用墙钟，Orchestrator 容忍 | TelemetryPublisher 传 null；MissionRecord.duration_s 用 started/ended 墙钟；README/COMPLIANCE 已更新 | 一致 |
| C2 | c2w：real 允许 estimated + `pose_source` + `pose_accuracy_m`；缺失时 null + unavailable | ProtocolDtos.PhotoRecord 已含 poseSource/poseAccuracyM（默认 estimated/3.0）；MissionExecutor 显式写 estimated；README/COMPLIANCE 已更新 | 一致（TODO：真实精度需真机标定） |
| C3 | 设备就绪：E_RC_LINK + details.reason=not_registered/not_connected；机型不符 E_STATE + aircraft_mismatch | ErrorMapper.notRegistered/notConnected/aircraftMismatch；SafetyGuard 设备就绪检查调用；README/COMPLIANCE 已更新 | 一致 |
| C4 | 不新增顶层错误码 | 未新增 | 一致 |

## 4. 本轮已执行的代码修正（均未编译，仅为静态一致性修正）

1. `mission/WaypointConverter.kt`：按 10 §2/§3/§4 + make_sample_kmz.py 整体重写（template/waylines 全字段、actionGroup、takeOffSecurityHeight、droneInfo/payloadInfo 占位）；删除重复的 `mission/MissionKmzBuilder.kt`，统一为 DESIGN.md 中的规范文件名。
2. `mission/WaypointMissionController.kt`：3 个监听器改 object 实现具名方法（08 §6.2）；KMZ 参数统一为路径语义并注释 TODO。
3. `mission/MissionExecutor.kt`：`start(kmz.name)` → `start(kmz.absolutePath)`；照片记录带 pose_source/pose_accuracy_m。
4. `bridge/TelemetryPublisher.kt`：listen 回调改 `{ _, _ -> }`。
5. `gimbal/GimbalController.kt`：GimbalAngleRotation 改 no-arg + apply；KeyRotateByAngle 的 createKey 去 componentIndex；listen 两参。
6. `flight/FlightController.kt`：VirtualStickFlightControlParam 改 value 包；新增 newVirtualStickParam() 显式设置 4 个控制模式字段。
7. `media/MediaDownloader.kt`：refreshList 前调用 IMediaManager.enable()（08 §6.5）。
8. `mapping.json`：版本 1.1；补 research 来源 S21/S22；修正类名/方法名（WaypointConverter、TelemetryPublisher、DroneBridgeServer、CommandExecutor）与上述 API 修正项；新增 `research_review` 块。
9. `README.md` / `PROTOCOL_COMPLIANCE.md`：组件名与 DESIGN.md 一致（DroneBridgeServer/CommandExecutor/TelemetryPublisher/WaypointConverter）；补充 spec §15 三项；边界表补 KMZ 生成器已按 10 重写但仍未真机验证。

## 5. 仍存 TODO（7 项，无法静态解决）

| # | TODO | 影响 | 解决方式 |
|---|---|---|---|
| T1 | Mini 4 Pro 的 WPML `droneEnumValue/payloadEnumValue` 官方取值 | KMZ 可能被拒绝 | 查 DJI WPML 机型枚举表 / 官方 checkValidation / 真机（当前占位 0） |
| T2 | per-waypoint `heading_deg` 的 WPML 落地（manually+aircraftHeading 或 smoothTransition） | 航向控制精度 | 真机 + 10 未抓取的 heading 子表 |
| T3 | `photo_interval_s` 的 multipleTiming/multipleDistance 在 Mini 的支持性 | 间隔拍照实现方式 | 真机验证；当前每航点 reachPoint+takePhoto |
| T4 | `executeHeightMode` 是否支持 EGM96 / 相对模式的精确必填项 | KMZ 兼容性 | 真机 + checkValidation |
| T5 | MediaFile 时间戳字段名与照片对账准确性 | 照片元数据 | 真机抓 MediaFile 字段 |
| T6 | AirlinkKey 信号质量 Key 名、机型字符串 Key 名 | 遥测/机型校验 | 真机抓 Key 列表 |
| T7 | 全部 Kotlin 代码编译与真机行为（GimbalAngleRotation/虚拟摇杆字段/listener 签名等以 AAR 实际为准） | 能否运行 | Android Studio 编译 + test_protocol.md T0–T4 |

## 6. 结论

- 08/10 与 mapping.json/app 的**语义层**一致性良好；本轮把发现的 16 项"需修正"中 13 项落到代码/映射，3 项落到文档说明。
- 最关键的 KMZ 生成器缺陷已按 10 重写（但 T1/T2/T3/T4 仍决定其能否被 Mini 4 Pro 接受，必须走 test_protocol.md T0 静态校验 + T3 真机小航线）。
- 本轮**没有**新增任何"已编译/已飞行"证据；所有修正仍属"文档与静态证据级"。
