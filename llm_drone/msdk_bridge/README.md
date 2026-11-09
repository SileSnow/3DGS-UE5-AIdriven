# LLM Tool-Call 到 DJI MSDK v5 Android 桥接层（Phase-2 真机后端）

> **状态声明（必读）**：本模块是「设计 + Android 代码骨架」，**未编译、未安装、未连接真机、未飞行**。
> 环境核实（2026-11-08）：本机无 Android Studio、无 Android SDK（ANDROID_HOME 为空）、有 JDK 21、无 DJI 遥控器/飞机。
> 因此所有「行为描述」均为设计目标；本文唯一的「已验证」指 MSDK v5 类名/方法名/回调签名来自官方一手资料（developer.dji.com API Reference、官方 GitHub sample、Maven Central 构件 5.20.1 符号扫描，见 evidence/API_SYMBOLS_VERIFIED.md），**不是**编译或飞行结果。
> 规格事实源：llm_drone/spec/PROTOCOL.md **v1.1**（v1.0 FROZEN + §15 补充决议）+ tools.json + sample_mission.json。任务契约：llm_drone/docs/CONTRACT.md。
> 配套：DESIGN.md（详细设计）、mapping.json（工具到 API 映射）、PROTOCOL_COMPLIANCE.md（逐条对照）、test_protocol.md（真机协议）、evidence/（证据）。

## 1. 目标与范围

把 Phase-1 仿真后端（llm_drone/sim）替换为 **Android MSDK v5 App**：Orchestrator 通过同一套 HTTP JSON 契约下发工具调用，桥接 App 用 DJI Mobile SDK v5 控制 **DJI Mini 4 Pro**（RC-N2 / RC-N3 + Android 手机）。

- 桥接层实现 13 个 agent 工具：get_telemetry、preflight_check、takeoff、goto_waypoints、set_gimbal、capture_photo、start_video、stop_video、return_to_home、land、abort、get_mission_status、set_mode（白名单见 app/.../safety/SafetyConfig.kt）。
- plan_capture_mission / orbit 属于 Orchestrator 侧确定性规划工具（executor=orchestrator），**不进入桥接层**；orbit 由 Orchestrator 展开成圆形航点后以 goto_waypoints 下发。
- 不做：LLM 交互、任务规划、3DGS 重建、UE5 渲染；只做「意图 -> 飞控/相机指令 -> 遥测/任务记录回传」。
- 安全定位：**LLM 永不直接接触 DJI SDK**；桥接层 SafetyGuard 是**权威第二道安全门**（Orchestrator 侧校验可能被绕过，设备端校验不可绕过）。

## 2. 架构与数据流

```text
用户自然语言
   |
   v
① LLM Orchestrator（Python 本机；Ollama qwen3.5:4b 或任意 OpenAI 兼容 API）
   |  工具循环/规划/澄清；plan_capture_mission、orbit 为确定性代码
   |  HTTP/JSON（同一契约）：/v1/health /v1/telemetry /v1/command /v1/missions/{id} /v1/missions /v1/audit
   v
② Android Bridge App（本目录 app/，手机上 127.0.0.1:8765）
   |- DroneBridgeServer (NanoHTTPD)     <- spec §3.2 前 6 个端点
   |- CommandExecutor（幂等 + 白名单 + confirm + 异步执行）
   |- SafetyGuard（设备端 16 条规则 + Phase2 就绪检查）
   |- FlightController / WaypointMissionController / MissionExecutor
   |- CameraController / GimbalController / MediaDownloader
   |- TelemetryPublisher / MissionStore / AuditLogger
   |  DJI Mobile SDK v5（AAR 5.20.1，仅 Android）
   v
③ DJI RC-N2/RC-N3（OcuSync）—— DJI Mini 4 Pro
```

部署拓扑：手机 USB 连笔记本（USB 调试）→ adb forward tcp:8765 tcp:8765 → Orchestrator 访问 http://127.0.0.1:8765；手机与遥控器走 USB Accessory（官方 sample 同款）。HTTP 不暴露公网。

一次 goto_waypoints 的端到端时序：
1. Orchestrator 把 plan_id 展开为 mission JSON（llm_drone.mission/v1，spec §6）→ POST /v1/command。
2. CommandExecutor 做 command_id 幂等检查 → SafetyGuard 逐航点校验（限高/限速/围栏/禁飞区/电量/GPS/RC/confirm）→ **通过后立即返回** {ok:true, mission_id, state:"mission"}（小于 10s，满足 Orchestrator 单请求超时）。
3. 后台协程：WaypointConverter 生成 KMZ → WaypointMissionManager.pushKMZFileToAircraft（带进度）→ getAvailableWaylineIDs → startMission。
4. 飞控端执行航点任务（到点悬停/转向/云台/拍照）；桥接层监听 WaypointMissionExecuteStateListener 与 WaylineExecutingInfoListener。
5. Orchestrator 轮询 /v1/telemetry、/v1/missions/{id}；完成时 mission record 为 completed 且 photos[] 完整。
6. 照片回收：IMediaManager 拉列表（按时间回填文件名）→ MediaDownloader 下载原图到 App external files dir → adb pull 取回，用于 3DGS。

## 3. 与仿真后端同构的 HTTP JSON 契约

| 方法/端点 | 桥接层实现 | 与 Phase-1 仿真的差异 |
|---|---|---|
| GET /v1/health | {ok, backend:"msdk", version:"0.1.0", mode, time_scale:1.0, ts} + 只读 device{} | backend=msdk、mode=real；附加字段 additive |
| GET /v1/telemetry | spec §5 telemetry 对象（字段名一致） | **sim_time_s 返回 null**（real 无仿真时间，见 PROTOCOL_COMPLIANCE §2.1） |
| POST /v1/command | {command_id, tool, args, confirm?, run_id?} → {ok, command_id, tool, state, mission_id?, telemetry, warnings?, error?, can_fly?, checks?}；幂等缓存最近 100 条 | 飞行命令异步接受：安全通过即返回 state（taking_off/mission/landing/returning），执行在后台 |
| GET /v1/missions/{id} | spec §7.1 mission record；photos[].c2w 为推算值 | real 无真值 c2w：由计划航点+云台角按 spec §7.2 推算（estimated） |
| GET /v1/missions?limit=10 | {ok, missions:[...]} 创建时间倒序 | 同构 |
| GET /v1/audit?since_seq=N | {ok, events[], last_seq}；同时写 JSONL（App external files dir） | 桥接层补充端点，与仿真同构 |
| POST /v1/reset | E_NOT_SUPPORTED | 仿真专属，real 拒绝 |
| POST /v1/sim/config | E_NOT_SUPPORTED | 仿真专属，real 拒绝 |

命令语义补充：
- confirm 兼容两种位置：请求体顶层 confirm 或 args.confirm（tools.json 把 confirm 放在 args 内）；任一为 true 视为已确认。
- goto_waypoints **要求 Orchestrator 已展开 waypoints/mission**；只传 plan_id 返回 E_SCHEMA（桥接层不持有 Orchestrator 的 plan 存储）。
- takeoff：先 KeyStartTakeoff（无高度参数，自动离地悬停），再用虚拟摇杆 advanced mode 垂直爬升至 altitude_m（10Hz，官方建议 5–25Hz），到点关闭虚拟摇杆悬停。
- abort：停任务 + 悬停（不自动返航）；返航需显式 return_to_home。
- 业务失败一律 HTTP 200 + {ok:false, error:{code,message,details?}}；错误码全部来自 spec §8.2（21 个），MSDK 原生错误无业务码时映射 E_INTERNAL 并保留 details.msdk_error。
- 并发：任务执行中仅允许 abort / get_telemetry / get_mission_status / return_to_home，其余 E_BUSY（spec §8 规则 16）。
- **spec v1.1 §15 对齐（2026-11-08）**：real 模式 `sim_time_s` 允许 null；`photos[].c2w` 必须带 `pose_source`（truth/estimated/unavailable）与 `pose_accuracy_m`（估算默认 3.0m）；设备就绪错误 `E_RC_LINK.details.reason ∈ {not_registered,not_connected}`、机型不符 `E_STATE.details.reason=aircraft_mismatch`。

## 4. Android 端组件划分（与 app/ 实际文件一一对应）

| 层 | 文件（app/app/src/main/java/com/gaia/llmdrone/bridge/） | 职责 |
|---|---|---|
| 应用入口 | DJIApplication.kt | Application：Helper.install(this)（官方 sample 同款）；onCreate 初始化 MSDK |
| 入口 UI | MainActivity.kt | 运行时权限、启动前台服务、显示注册/连接/端口状态（骨架级 UI） |
| SDK 初始化 | msdk/MsdkInitManager.kt | SDKManager.getInstance().init(ctx, InitSettings(SDKLinKMode.LOCAL), callback)；INITIALIZE_COMPLETE 后 registerApp()；注册/连接状态 |
| 连接管理 | msdk/AircraftConnectionManager.kt | Product/FlightController KeyConnection 监听、机型白名单（Mini 4 Pro）、固件读取、绑定校验占位（TODO 真机补全） |
| HTTP 服务 | bridge/DroneBridgeServer.kt | NanoHTTPD 路由 8 端点；JSON 收发；默认绑定 127.0.0.1（设计） |
| 前台服务 | bridge/BridgeService.kt | 承载 HTTP 服务与各监听器，避免 App 退后台被杀 |
| 命令路由 | bridge/CommandExecutor.kt | 幂等缓存、白名单、SafetyGuard 调用、异步执行、响应构造 |
| 运行期状态 | bridge/BridgeRuntime.kt | mode（dry_run/real）、state 枚举、当前 mission_id、时间工具 |
| 遥测 | bridge/TelemetryPublisher.kt | DJIKey 到 spec §5 快照；state 推导（GoHomeState/IsFlying/IsFailsafe/IsInLandingMode） |
| 协议 DTO | bridge/ProtocolDtos.kt | CommandRequest/TelemetrySnapshot/PhotoRecord/MissionRecord/Responses/ApiError（org.json，无 Gson） |
| 错误映射 | bridge/ErrorMapper.kt | IDJIError 到 spec 错误码；内部错误上下文 |
| 任务记录 | bridge/MissionStore.kt | mission record 内存 + external files JSON 落盘；最近 50 条 |
| 审计 | bridge/AuditLogger.kt | 事件 JSONL（不可关闭）+ 环形缓冲供 /v1/audit |
| 飞行控制 | flight/FlightController.kt | 起飞/爬升/自动降落/返航/停止各类动作/悬停；KeyStartTakeoff 等 |
| 航点任务 | mission/WaypointMissionController.kt | KMZ 上传（进度）、waylineIDs、start/pause/resume/stop、状态监听 |
| KMZ 构建 | mission/WaypointConverter.kt | mission JSON 生成 KMZ（wpmz/template.kml + waylines.wpml）；WPML 字段未真机验证 |
| 任务编排 | mission/MissionExecutor.kt | 生成 KMZ -> 上传 -> 执行 -> 监控 -> 任务记录 -> 照片对账 -> c2w 推算 |
| 相机 | camera/CameraController.kt | 拍照（单/连拍，桥接层定间隔）、录像开始/停止；CameraKey |
| 云台 | gimbal/GimbalController.kt | GimbalKey.KeyRotateByAngle 绝对角度 + KeyGimbalAttitude 回读 |
| 媒体 | media/MediaDownloader.kt | IMediaManager 列表拉取、原图流式下载（pullOriginalMediaFileFromCamera） |
| 安全 | safety/SafetyGuard.kt + SafetyConfig.kt + GeoFence.kt | spec §8 全部规则（顺序固定）+ 圆形围栏/多边形禁飞区几何（纯 Kotlin 可单测） |
| 资源/配置 | AndroidManifest.xml、res/xml/accessory_filter.xml、res/values/strings.xml | 权限、com.dji.sdk.API_KEY、USB accessory、前台服务声明 |

> 说明：骨架文件命名与任务要求一致：MainActivity / DroneBridgeServer / CommandExecutor / SafetyGuard / TelemetryPublisher / WaypointConverter；其余为支撑类（msdk/flight/mission/camera/gimbal/media/bridge 等，见上表）。DESIGN.md 中 WS/token/双机部署为**设计预留（骨架未实现）**。

## 5. 构建与部署步骤（设计稿；本机未执行）

1. **环境**：Android Studio（AGP 8.7.0 / Kotlin 2.1.0 / compileSdk 35 / minSdk 24 / JDK 17+）；手机 arm64、Android 10+、开启 USB 调试。
2. **DJI App Key**：登录 developer.dji.com 创建 App（Android，包名 com.gaia.llmdrone.bridge + 签名证书 SHA256）获取 App Key；写入 app/gradle.properties 的 AIRCRAFT_API_KEY（manifestPlaceholders 注入 com.dji.sdk.API_KEY）；**不要把真实 Key 提交仓库**；换签名需重新申请。
3. **依赖确认**：com.dji:dji-sdk-v5-aircraft:5.20.1（implementation）、dji-sdk-v5-aircraft-provided:5.20.1（compileOnly）、dji-sdk-v5-networkImp:5.20.1（runtimeOnly，注册/授权需联网）、org.nanohttpd:nanohttpd:2.3.1、coroutines-android；packaging 的 pickFirst/keepDebugSymbols 照官方 sample（避免 libc++_shared.so 冲突）。
4. **构建**：cd app 然后 ./gradlew :app:assembleDebug（Windows 用 gradlew.bat）；首次同步需联网拉取 DJI AAR（体积大）。
5. **硬件**：Mini 4 Pro + **RC-N2**（MSDK v5.13.0 起支持；RC-N3 需 v5.17.0+；**RC 2 带屏遥控器不支持第三方 App**）；手机 USB 连遥控器（USB Accessory）；先用 DJI Fly 完成激活/固件升级/账号绑定。
6. **运行**：安装 App -> 打开 -> 前台服务启动 HTTP（8765）-> adb forward tcp:8765 tcp:8765 -> 电脑 curl http://127.0.0.1:8765/v1/health 应见 "backend":"msdk" 且 device.msdk_registered=true。
7. **Orchestrator 接入**：--agent-url http://127.0.0.1:8765（与仿真 URL 形状一致，代码无需改动）。先 set_mode(dry_run, confirm=true) 地面验证，再 set_mode(real, confirm=true)。
8. **真机放飞**：严格按 test_protocol.md：空载、空旷场地、视距内、手动接管随时可用；逐级 T0（离线审阅）-> T1（地面拆桨）-> T2（室内悬停）-> T3（空旷航点）-> T4（故障演练）。

## 6. 已验证 / 未验证边界表

| # | 结论 | 证据 | 状态 |
|---|---|---|---|
| 1 | MSDK v5 仅 Android；Mini 4 Pro 自 v5.13.0 支持（RC-N2），RC-N3 自 v5.17.0；RC 2 不支持 | 官方 Release Notes/兼容表（docs/research/01） | 文档已验证 |
| 2 | AAR 坐标 com.dji:dji-sdk-v5-aircraft:5.20.1 + provided + networkImp；WPMZ com.dji:wpmzsdk:1.0.5.2 | 官方 README V5.20.1 + dependencies.gradle + Maven Central 构件 | 文档已验证 |
| 3 | SDKManager.init(Context, InitSettings, SDKManagerCallback)；registerApp() 在 INITIALIZE_COMPLETE 后调用 | API Reference + 官方 sample MSDKManagerVM.kt + 5.20.1 JAR 符号扫描 | 文档已验证 |
| 4 | FlightControllerKey.KeyStartTakeoff/KeyStartAutoLanding/KeyStartGoHome/KeyStopGoHome/KeyConfirmLanding/KeyGoHomeHeight/KeyIsInLandingMode 等 | API Reference + JAR 常量池扫描（evidence §2.1） | 文档已验证 |
| 5 | WaypointMissionManager.pushKMZFileToAircraft/startMission/getAvailableWaylineIDs/pause/resume/stop + 三个 Listener | API Reference + 官方 sample WayPointV3VM.kt | 文档已验证 |
| 6 | CameraKey 拍照/录像、GimbalKey.KeyRotateByAngle、IMediaManager 列表/下载、IVirtualStickManager | API Reference + 官方 sample MediaVM/VirtualStickVM | 文档已验证 |
| 7 | **KMZ/WPML 字段能否被 Mini 4 Pro 飞控接受** | WaypointConverter.kt 为按 WPML 规范编写的结构示意，从未上传 | **未验证（最高风险）** |
| 8 | GimbalAngleRotation 构造参数顺序、VirtualStickFlightControlParam setter 名、WaylineExecutingInfo 字段名 | 官方页面未给出构造细节 | 未验证（代码 TODO(未确认)） |
| 9 | 起飞到指定高度的虚拟摇杆爬升（控制权切换/N 档前提/实际精度） | 设计推断 + 官方教程 | 未验证 |
| 10 | App Key 注册、Mini 4 Pro 实际 Key 可读性/单位、机型绑定 | 无真机 | 未验证 |
| 11 | **编译/安装/HTTP 端到端/真机飞行** | 无 Android SDK、无真机 | **未执行** |
| 12 | WPML 生成器已按 docs/research/10 + 参考生成器 make_sample_kmz.py 逐字段重写（template/waylines 必填字段、actionGroup、takeOffSecurityHeight 等） | REVIEW_vs_research.md 的 B1-B20 | 静态修正（**仍未真机验证**） |
| 13 | photos[].c2w 带 pose_source/pose_accuracy_m（spec v1.1 §15.2）；real=estimated 3.0m、缺失=unavailable | ProtocolDtos.PhotoRecord + MissionExecutor | 代码/文档对齐（精度待真机标定） |

## 7. 已知限制

1. **仅 Android**：MSDK v5 无 iOS 版本（官方产品页/Release Notes 仅 Android）。
2. **带屏遥控器不可用**：DJI RC / RC 2 不能安装第三方 App；Mini 4 Pro 必须 RC-N2（或 v5.17.0+ RC-N3）+ Android 手机。
3. **SDK/固件匹配**：Mini 4 Pro 需 MSDK >=5.13.0（本项目按 5.20.1 设计）；机身/RC 固件需与 Release Notes 配套（v5.13.0 记录机身 01.00.0800 / RC-N2 01.01.0300）；升级后必须重新回归。
4. **断点续飞不保证**：官方仅列 M30/M3E/M3T/M3M，Mini 系列不在列；任务中断只能重飞。
5. **KMZ 依赖飞控端执行**：虚拟摇杆逐点闭环需持续 5–25Hz 指令且链路抖动风险高，本设计主用 KMZ，虚拟摇杆仅用于起飞爬升/悬停。
6. **照片位姿是推算值**：real 无 UE 坐标系真值，photos[].c2w 由计划航点+云台角按 spec §7.2 推算；实际到点/云台稳定/风偏带来误差，3DGS 建议以 EXIF/XMP+特征匹配为主、c2w 为初值。
7. **单任务、单机**：任务执行中仅允许 4 个安全/只读命令；同一 App 不并发多任务；HTTP 无鉴权（只绑定本机，靠 adb forward 访问）。
8. **审计 run_id**：real 模式 /v1/reset 不可用，审计文件固定 audit_default.jsonl（可 adb pull）；per-run 文件待下一版实现（PROTOCOL_COMPLIANCE §5.3）。
9. **前台依赖**：任务期间 App 必须前台服务运行；需关闭 Android 电池优化，否则可能被杀进程。

## 8. 风险与合规

- **安全**：LLM 意图驱动真机，必须保持「LLM 不直连 SDK + 双层 SafetyGuard + confirm + 设备端审计」；首飞空载、空旷、视距内、手动接管可用；异常优先遥控器物理接管，不以 App 为飞行状态唯一依据。
- **合规**：空域报备/实名登记/高度不超过 120m/避开禁飞区；不得用逆向工具绕过 GEO/限高（违反 DJI 使用条款，见 docs/research/01 §7）；DJI App Key 使用遵守 MSDK 许可与隐私政策。
- **数据**：照片含 GPS 属敏感数据；下载目录不加密，mission/audit JSON 含坐标与操作记录，外发前需脱敏，测试后清理。
- **诚实边界**：本模块**没有**产生任何飞行/编译/端到端证据；「能用」需 test_protocol.md 全绿后才成立。

## 9. 文件索引

| 文件 | 说明 |
|---|---|
| README.md | 本文件：总览/契约/组件/部署/边界/限制/风险 |
| DESIGN.md | 详细设计（线程模型、失败降级、遥测管线、KMZ 字段对照等） |
| mapping.json | 工具到 MSDK v5 类/方法/回调 + 官方来源 + 状态（verified-from-docs/unverified），已用 python json.load 校验 |
| PROTOCOL_COMPLIANCE.md | 与 spec v1.0 逐条对照（端点/命令/字段/错误码/E_NOT_SUPPORTED/差异） |
| test_protocol.md | 真机测试协议（前置/用例矩阵/记录模板/异常处置/复盘），明确本轮未执行 |
| evidence/API_SYMBOLS_VERIFIED.md | 5.20.1 构件符号扫描 + 官方 sample 证据（E1–E5） |
| evidence/INDEX.md | 证据索引：来源编号总表 E1–E5 / S1–S20、复现命令、证据强度说明 |
| LIMITS.md | 能力边界与限制（平台/飞行/相机/媒体/合规逐项边界，配套 DESIGN.md） |
| REAL_DRONE_TEST.md | 真机验证协议（通过标准、应急方案、硬件/账号/环境前置），与 test_protocol.md 配套 |
| REVIEW_vs_research.md | T9 复核：与 docs/research/08、10 交叉核对 47 项（一致 24 / 需修正 16 / TODO 7）与修正记录 |
| app/ | Android 工程骨架：Gradle KTS x3 + gradle.properties、Manifest、23 个 Kotlin 源文件、资源文件 |
| SUMMARY.md | 收尾交付摘要：关键决策/文件清单/覆盖面自查/未决问题/证据 URL |

## 10. 安全规则落地表（spec §8 的 16 条规则在设备端如何实现）

| # | 规则 | 实现位置 | 默认值 | 违规错误码 |
|---|---|---|---|---|
| 1 | 最大相对高度 | SafetyGuard.rangeError（takeoff 与每个航点 alt_rel_m） | 120 m | E_ALT_LIMIT |
| 2 | 最大水平速度 | SafetyGuard.rangeError（flight.speed_mps 与航点 speed_mps） | 15 m/s | E_SPEED_LIMIT |
| 3 | 地理围栏（圆形） | SafetyGuard.geofenceError + GeoFence.insideCircle | 中心 39.9042,116.4074 / R=300 m | E_GEOFENCE |
| 4 | 禁飞区（多边形） | SafetyGuard.noFlyError + GeoFence.insidePolygon | spec §8.1 多边形 | E_NOFLY |
| 5 | 起飞最低电量 | SafetyGuard.validate（BatteryKey 读数） | 30% | E_BATTERY_TAKEOFF |
| 6 | 返航保留电量 | SafetyGuard.rthEnergyError（距离估算） | 20% | E_BATTERY_RTH |
| 7 | 飞行中低电量强制返航 | 飞控策略 + 遥测状态观测（主动触发逻辑未实现，见 PROTOCOL_COMPLIANCE §5.4） | 20% | 审计 force_rth / state=returning |
| 8 | GPS 质量 | SafetyGuard.validate（KeyGPSSatelliteCount + KeyGPSSignalLevel 映射） | fix>=3 且 sats>=10 | E_GPS |
| 9 | 遥控链路 | SafetyGuard.validate + AircraftConnectionManager | 必须连接 | E_RC_LINK |
| 10 | 指令白名单 | SafetyConfig.WHITELIST（13 工具） | tools.json | E_UNKNOWN_TOOL |
| 11 | 参数 schema 与物理范围 | SafetyGuard.schemaError / rangeError | tools.json | E_SCHEMA / E_PARAM_RANGE |
| 12 | 二次确认 | SafetyGuard.validate（confirm 在顶层或 args 均可） | takeoff/goto_waypoints/set_mode(real) | E_CONFIRM_REQUIRED |
| 13 | 状态合法性 | SafetyGuard.stateError + BridgeRuntime 状态机 | 见 spec §5 | E_STATE / E_NOT_AIRBORNE |
| 14 | real 模式 | CommandExecutor.set_mode（sim 不支持） | dry_run/real | E_NOT_SUPPORTED |
| 15 | 审计不可关闭 | AuditLogger（JSONL + 环形缓冲，/v1/audit） | 全部命令/拒绝 | 无（必须落盘） |
| 16 | 并发命令 | CommandExecutor（任务中只允许 4 个命令） | — | E_BUSY |

补充硬规则：abort 永不排队、永不因参数缺失被拒（reason 缺省补 unspecified）；飞行中低电量/链路丢失/禁飞区动态命中时设备端优先保护（返航/悬停），不等待 LLM 决策；任何拒绝都写审计，便于对抗测试断言。

## 11. 真机测试阶梯与验收映射

测试分五级门禁：T0 离线审阅（代码 + spec 对照 + KMZ 静态校验）-> T1 地面拆桨（连接/遥测/云台/拍照/媒体/中止）-> T2 室内悬停（5m/30s/RTH）-> T3 空旷场地（2x2 网格 4 张照片自动 RTH）-> T4 故障演练（低电量/链路丢失/任务中 abort/相机忙）。每一级的步骤、预期、记录字段、安全护栏与异常处置见 test_protocol.md；REAL_DRONE_TEST.md 提供通过标准与应急方案。

与 CONTRACT.md §6 验收标准的对应：第 5 条（MSDK v5 桥接口映射与真机测试协议，代码骨架可审阅）由本文件 + mapping.json + app/ + PROTOCOL_COMPLIANCE.md + test_protocol.md 共同满足；**真机飞行不属本轮验收范围，本轮未执行**。

## 12. 常见问题（FAQ，面向评审/接手人）

**Q1：为什么不用虚拟摇杆直接飞完整条航线？** 虚拟摇杆需要 5–25Hz 连续指令、遥控器 N 档、且依赖手机程序持续存活；链路一抖就悬停/失控，不适合 3DGS 长航线。KMZ 航点任务由飞控端执行，手机断开也能继续，是本设计的主路径。

**Q2：为什么 takeoff 要分两步（先起飞再虚拟摇杆爬升）？** MSDK 的 KeyStartTakeoff 没有高度参数（自动离地约 1.2m 悬停）；到指定高度只能接管控制权用虚拟摇杆垂直速度闭环，或把首个航点当爬升点（降级方案）。两条路都标了未真机验证。

**Q3：照片位姿从哪来？** real 模式没有 UE 真值：桥接层按计划航点经纬度/高度 + 计划云台角 + heading，用 spec §7.2 公式推算 c2w，标注 estimated；同时记录拍摄时刻遥测快照。3DGS 建议以 EXIF/XMP + 特征匹配为主、推算 c2w 做初值。

**Q4：为什么 HTTP 只绑定 127.0.0.1？** 桥接层无鉴权，一旦绑定 0.0.0.0 就可能被局域网内任意程序控制真机；默认只允许 adb forward 的本机访问。双机部署需要额外 token/TLS，属设计预留（DESIGN.md）。

**Q5：本轮到底证明了什么？** 只证明了“契约与 API 映射在文档层面自洽、代码骨架结构完整可审阅”。没有编译、没有跑通 HTTP、没有连接飞控、没有飞行；所有“可用性”结论都要等 test_protocol.md 的 T0–T4 通过。

**Q6：没有 Android SDK 时还能做什么验证？** 可做：python 静态校验 mapping.json 与 spec 工具集覆盖、Java/Kotlin 语法审查、GeoFence 纯逻辑用 Python 复刻单测、WPML XML 结构对照官方文档。不能做：编译、安装、MSDK 注册、真机链路、KMZ 被飞控接受性。

## 13. T9 复核结论（与 docs/research/08、10 交叉核对，2026-11-08）

- 复核对象：mapping.json、app/ Kotlin 骨架、本 README、PROTOCOL_COMPLIANCE.md；对照 docs/research/08（MSDK v5 使用方法，10 模块 API 表/真实类名）与 10（KMZ/WPML 字段/action/状态机/12 项自检）。
- 结果：共 47 项，**一致 24 / 需修正 16（本轮已修 13，文档同步 3）/ TODO 7（必须真机或官方枚举表）**。详见 REVIEW_vs_research.md。
- 关键修正：WaypointConverter.kt 按 10 重写（旧版 template.kml 缺 takeOffSecurityHeight/droneInfo/payloadInfo/Folder 全局字段，会被判非法 KMZ）；WaypointMissionController 三个 Listener 改 object 具名方法；GimbalAngleRotation 改无参+apply；VirtualStickFlightControlParam 改 value 包并显式控制模式；MediaDownloader 增加 IMediaManager.enable()；TelemetryPublisher listen 双参回调。
- docs/research/08 自身需修正 2 处（已记录）：ComponentIndexType.CAMERA 与 5.20.1 构件扫描不符（应为 LEFT_OR_MAIN 等）；GimbalAngleRotation 构造写法以构件字段表为准。
- 剩余 TODO（T1-T7）：Mini 4 Pro WPML 机型/负载枚举值、per-waypoint heading 落地、multipleTiming 支持性、executeHeightMode/EGM96、MediaFile 时间戳、AirlinkKey/机型字符串 Key 名、全部 Kotlin 编译与真机行为。
- **本轮仍未编译、未真机**；T9 只提高「文档/静态一致性」，不改变诚实边界。

