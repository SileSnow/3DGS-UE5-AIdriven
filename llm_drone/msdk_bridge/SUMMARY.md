# 收尾交付摘要（SUMMARY）—— task-10：Android MSDK v5 无人机桥

> 生成：2026-11-08。状态：**设计 + 可审阅代码骨架 + 真机协议已完成；未编译、未安装、未连接真机、未飞行**（本机无 Android SDK、无 DJI 设备）。
> 唯一事实源：`llm_drone/spec/PROTOCOL.md` v1.0（FROZEN）+ `spec/tools.json`；任务契约：`llm_drone/docs/CONTRACT.md`。

## 1. 交付物清单（均在 llm_drone/msdk_bridge/）

| 文件 | 内容 | 规模 |
|---|---|---|
| `DESIGN.md` | 架构/线程模型/连接状态机/工具→MSDK API 映射表/安全层/遥测管线（≤10Hz+延迟补偿）/KMZ 航线/失败降级/部署 | ~22.7K 字符 |
| `mapping.json` | 15 工具 → MSDK v5 类/方法/回调 + 来源编号 + verified/unverified 状态 + 8 HTTP 端点映射 + 错误码映射 | ~24.7K 字符（JSON 合法） |
| `README.md` | 总览/契约同构/组件划分/构建部署/已验证-未验证边界/限制/风险/spec §8 安全规则落地表/FAQ | ~14.8K 字符 |
| `PROTOCOL_COMPLIANCE.md` | 与 frozen spec v1.0 逐条对照（端点/命令/字段/错误码/E_NOT_SUPPORTED/差异） | ~7.3K 字符 |
| `REAL_DRONE_TEST.md` | 真机验证协议：硬件/账号/固件/空域前置、T1 地面拆桨→T2 室内悬停→T3 空旷 2×2 网格→T4 故障演练、通过标准、应急中止 SOP、排障、合规 | ~9.6K 字符 |
| `test_protocol.md` | 现场可勾选执行清单 + 用例矩阵（C/F/W/R/A/L 系列）+ 记录模板 + 门禁 T0–T4 | ~5.1K 字符 |
| `LIMITS.md` | 平台硬限制（iOS/RC2/Mini5Pro）、飞行/相机/媒体/遥测延迟/手机网络/KMZ 风险/安全边界/未验证清单 | ~6.5K 字符 |
| `evidence/API_SYMBOLS_VERIFIED.md` | MSDK 5.20.1 构件级符号核验（Key 泛型签名、Manager 方法、枚举、Listener、Mini 4 Pro 能力清单）+ 未验证项 | ~15.6K 字符 |
| `evidence/INDEX.md` | 证据索引：来源编号 E1–E5 / S1–S20、复现命令、证据强度说明 | ~3.0K 字符 |
| `evidence/SELF_CHECK.md` | 自动自查结果（见 §3） | 生成 |
| `app/` | Android 工程骨架：Gradle KTS + gradle.properties + Manifest + **23 个 Kotlin 源文件**（任务要求 6 个入口文件齐全） | — |

任务要求的 6 个 Kotlin 入口文件全部存在且为真实实现：
`MainActivity.kt`、`DroneBridgeServer.kt`（NanoHTTPD HTTP+WS）、`CommandExecutor.kt`（分发/幂等/状态机）、`SafetyGuard.kt`（spec §8 16 条规则+审计）、`TelemetryPublisher.kt`（Key→遥测快照/5Hz 节流）、`WaypointConverter.kt`（waypoints→WPML/KMZ）；
另有支撑类：`msdk/MsdkInitManager`、`msdk/AircraftConnectionManager`、`flight/FlightController`、`mission/WaypointMissionController`、`mission/MissionExecutor`、`camera/CameraController`、`gimbal/GimbalController`、`media/MediaDownloader`、`safety/SafetyConfig+GeoFence`、`bridge/ProtocolDtos/ErrorMapper/MissionStore/AuditLogger/BridgeService/BridgeRuntime`、`DJIApplication`。

## 2. 15 工具映射覆盖（自查结果）

| 类别 | 工具 | 覆盖 |
|---|---|---|
| agent 执行（13） | get_telemetry、preflight_check、takeoff、goto_waypoints、set_gimbal、capture_photo、start_video、stop_video、return_to_home、land、abort、get_mission_status、set_mode | **13/13 均有 ≥1 条具体 MSDK API 调用链 + 失败处理** |
| orchestrator 侧（2） | plan_capture_mission、orbit | 桥接层不执行；mapping.json 标注 orchestrator-side 与 bridge 行为（收到即 `E_UNKNOWN_TOOL`），orbit 走 goto_waypoints |
| HTTP 端点 | /v1/health、/v1/telemetry、/v1/command、/v1/missions/{id}、/v1/missions?limit、/v1/audit?since_seq、/v1/reset(E_NOT_SUPPORTED)、/v1/sim/config(E_NOT_SUPPORTED) | 8/8 有实现位置映射 |

关键 API 链（详见 mapping.json/evidence）：
- 起飞/降落/返航：`FlightControllerKey.KeyStartTakeoff / KeyStartAutoLanding / KeyStartGoHome / KeyStopGoHome / KeyConfirmLanding / KeyGoHomeState`
- 航线：`WPMZManager.generateKMZFile` → `WaypointMissionManager.pushKMZFileToAircraft / getAvailableWaylineIDs / startMission / pause/resume/stop` + 3 个 Listener
- 相机/云台：`CameraKey.KeyCameraMode/KeyStartShootPhoto/KeyStartRecord/KeyStopRecord`、`GimbalKey.KeyRotateByAngle/KeyGimbalAttitude`
- 媒体：`MediaDataCenter.mediaManager.pullMediaFileListFromCamera` + `MediaFile.pullOriginalMediaFileFromCamera`
- 遥测：`KeyManager` listen 上述 Key，5Hz 节流、`age_ms` 延迟标注

## 3. 自查结果（evidence/SELF_CHECK.md）

- 必备文件：全部存在（README/DESIGN/mapping/PROTOCOL_COMPLIANCE/test_protocol/REAL_DRONE_TEST/LIMITS/2 份 evidence/Gradle/Manifest）。
- 工具覆盖：spec 15 → mapping 15，缺失 0；13 个 agent 工具全部有具体 API 调用链；端点映射 8 个。
- 骨架：23 个 .kt；6 个必需类声明命中各 1；10 个文件含 DJI SDK import；`TODO(未确认)` 共 21 处（均为未验证 API 细节，已显式标注）。
- 依赖：`app/app/build.gradle.kts` 含 `com.dji:dji-sdk-v5-aircraft:5.20.1`（+provided/networkImp、wpmzsdk 1.0.5.2）。
- 文档：PROTOCOL_COMPLIANCE 覆盖全部关键端点；README 含 20 种 spec 错误码。
- 结论：静态完整性**通过**；编译/安装/HTTP 端到端/真机飞行**未执行**。

## 4. 关键设计决策

1. **接口零改动**：Phase 2 App 实现 Phase 1 同一 `/v1/*` 契约；Orchestrator 只改 `--agent-url`。唯一 telemetry 差异 `sim_time_s=null`（已在 PROTOCOL_COMPLIANCE 标注）。
2. **安全双层**：Orchestrator 预检 + App 侧 SafetyGuard（权威）；拒绝优于截断；abort 永不排队；任务中仅 4 个白名单命令；审计 JSONL 不可关闭。
3. **航点主路径用 KMZ/WPML 由飞控执行**（手机断开任务可继续）；虚拟摇杆仅用于起飞后爬升/悬停兜底；POI 智能飞行未采用（无法精确指定拍摄点序列）。
4. **断点续飞不依赖**：Mini 4 Pro 不在官方保证列表，中断即 aborted 由人工决定重飞。
5. **照片位姿诚实标注**：真机无 UE c2w 真值，mission record 的 c2w 为计划值推算（estimated），3DGS 以 EXIF/XMP+特征匹配为主。

## 5. 剩余未验证项（诚实清单，详见 LIMITS.md §8 / README §6）

| # | 项 | 风险 | 验证方式 |
|---|---|---|---|
| 1 | 骨架编译/安装（本机无 Android SDK） | 中 | 有 Android Studio 的机器 assembleDebug |
| 2 | App Key 注册/机型绑定/固件匹配 | 中 | REAL_DRONE_TEST T1.1 |
| 3 | **KMZ/WPML 能否被 Mini 4 Pro 飞控接受** | **最高** | T3 第一步（先最小 KMZ） |
| 4 | 起飞后虚拟摇杆爬升至指定高度精度 | 中 | T2.2 |
| 5 | GimbalAngleRotation 参数语义、相机/媒体字段单位 | 中 | T1.4–T1.7 |
| 6 | 遥测实际频率/延迟、abort/RTH/land 时序 | 中 | T1.2、T2/T4 |
| 7 | 3DGS 用真实照片的位姿精度 | 中 | T3 后接 pipeline 训练对照 |

## 6. 证据与复现

- 构件：`com.dji:dji-sdk-v5-aircraft-provided:5.20.1`（JAR 20.6MB，Maven Central）符号扫描；`dji-sdk-v5-aircraft:5.20.1`（AAR 133.6MB）Mini 4 Pro 能力清单；官方 sample（jsDelivr 镜像）真实调用写法。复现命令见 `evidence/INDEX.md`。
- API 快照：`_tmp_api/`（developer.dji.com 官方页面 28 个 HTML）。
- 文献：`docs/research/01_DJI_Mini_SDK能力矩阵.md`、`06_Mini4Pro_3DGS采集SOP.md`、`data/dji/raw/text/relnotes_all.txt`。

## 7. 与验收标准映射（CONTRACT.md §6 第 5 条 / spec §13）

| 验收要求 | 交付证据 |
|---|---|
| MSDK v5 桥接口映射完整（每工具 ≥1 API + 失败处理） | `mapping.json`（15/15）+ `DESIGN.md` §3 映射表 + `evidence/API_SYMBOLS_VERIFIED.md` |
| 代码骨架可审阅 | `app/`（23 .kt，6 个任务要求入口 + 支撑类）+ `evidence/SELF_CHECK.md` |
| 真机测试协议可执行 | `REAL_DRONE_TEST.md` + `test_protocol.md`（前置/门禁 T0–T4/通过标准/应急/记录/合规） |
| 接口与 Phase-1 契约一致 | `PROTOCOL_COMPLIANCE.md`（8 端点 + 命令 + telemetry/mission schema + 错误码 + 差异说明） |
| 限制说明（iOS/RC2/Mini5Pro/遥测延迟/手机算力） | `LIMITS.md` 全节 + `DESIGN.md` §12 |

## 8. spec v1.1 §15 对齐（2026-11-08 收尾补充）

Lead 于 21:58 将 spec 升级为 **FROZEN v1.1**（§15，Lead 维护）；桥侧已按 §15 补齐（本轮未新增任何顶层错误码）：

| v1.1 决议 | 桥侧落点 | 状态 |
|---|---|---|
| real 模式 sim_time_s=null；任务时长用墙钟 start/end 差值 | TelemetrySnapshot.simTimeS=null；MissionRecord.durationSeconds | 已有，文档更新 |
| real photos[].c2w 允许估算值，必须带 pose_source 与 pose_accuracy_m（默认 3.0m）；缺失时 c2w=null + pose_source=unavailable | `ProtocolDtos.PhotoRecord` 新增 poseSource/poseAccuracyM 并输出；`MissionExecutor` 写 estimated + 3.0m | 已改骨架 |
| 设备就绪错误细节：未注册→E_RC_LINK.reason=not_registered；未连接→E_RC_LINK.reason=not_connected；机型不符→E_STATE.reason=aircraft_mismatch | `ErrorMapper` 新增 3 个 helper；`SafetyGuard` 设备就绪检查改用 | 已改骨架 |
| 不新增顶层错误码 | 沿用 spec §8.2 的 21 个 | 已遵守 |

对应文档更新：`PROTOCOL_COMPLIANCE.md` §2/§7（v1.1 裁决+对齐表）、`README.md` §3、`DESIGN.md` §10。

## 9. 下一步（真机阶段建议顺序）

1. 在具备 Android Studio 的机器编译安装（先修编译问题，不改契约）。
2. T0 离线审阅 + T1 地面拆桨（连接/遥测/云台/拍照/媒体/中止）。
3. T3 最小 KMZ 上传验证（最高风险项，先 1 个航点再 2×2 网格）。
4. T2/T4 安全演练；全绿后把真实照片接入 `pipeline/03_train_3dgs.py` 做真机数据对照。
5. 未通过项按阻塞等级回填 LIMITS/任务板；**未完成前不得宣称真机可用**。
