# 能力边界与限制（LIMITS）

> 状态：v1.0（2026-11-08）。本文件回答一个核心问题：**这套 LLM → MSDK v5 → Mini 4 Pro 方案，哪些能做、哪些不能做、哪些做到什么程度**。
> 证据：`docs/research/01_DJI_Mini_SDK能力矩阵.md`（官方兼容表/Release Notes）、`evidence/API_SYMBOLS_VERIFIED.md`（5.20.1 构件扫描）、`mapping.json`（逐 API 映射与未验证项）、`README.md` §6。

## 1. 平台级硬限制（无法通过工程绕过）

| # | 限制 | 影响 | 依据 |
|---|---|---|---|
| L1 | **MSDK v5 只有 Android，没有 iOS 版本** | 必须 Android 手机；iPhone/iPad 不可作为桥接端。历史 MSDK v4 有 iOS，但 v4 不支持 Mini 3/4/5 与 v5 不兼容 | 官方产品页仅 Android API Reference；Release Notes 仅收录 Android；GitHub 仅 Android 仓库 |
| L2 | **Mini 4 Pro 必须用 RC-N2（v5.13.0+）或 RC-N3（v5.17.0+）**；DJI RC / **RC 2 带屏遥控器不支持第三方 App** | 带屏 RC 用户无法用本方案（不能装 APK）；必须另购 RC-N2/N3 | v5.13.0/v5.17.0 Release Notes 固件表；dronedj 报道（二级佐证） |
| L3 | **Mini 5 Pro 无任何官方 SDK**（兼容表“不支持 SDK”，MSDK V5 支持列表与 GitHub README 均无） | 新机型不可用本桥；只能 DJI Fly 原生航点（半自动、最多 200 点） | 官方兼容表；MSDK V5 README V5.20.1 |
| L4 | **Mini 2 SE / Mini 4K 无 SDK** | 不可自动化；只能手动/定时拍照 | 官方兼容表 |
| L5 | **MSDK v4 与 v5 互不兼容** | Mini 2/Mini SE/Mavic Mini（v4 时代）不能复用 v5 代码；本项目只做 v5 机型 | 官方文档 |
| L6 | **无上云 API / Payload SDK / Onboard SDK 支持**（消费级 Mini 不在列） | 不能做机载算力、云机队、PSDK 负载；所有智能在本机手机/PC | 官方兼容表 |
| L7 | **App Key 与包名+签名绑定，且需联网注册** | 换签名/包名要重新申请；离线首启可能注册失败；Key 泄漏/滥用可能被限制 | DJI 开发者流程；官方 sample `dji.sdk.API_KEY` |
| L8 | **飞行法规与 DJI 条款**：限高 120m、禁飞区、实名登记、视距内；禁止破解 GEO/限高 | 任何“绕过”都是违规且危险；本桥安全层默认值必须保留 | `docs/research/01` §7（DJI 使用条款原文） |

## 2. 飞行控制能力边界

| # | 项 | 边界 | 说明/依据 |
|---|---|---|---|
| F1 | 起飞 | `KeyStartTakeoff` **无高度参数**，自动离地约 1.2m 悬停 | 官方 sample；到指定高度需虚拟摇杆爬升（或首个航点） |
| F2 | 指定高度悬停 | 虚拟摇杆 advanced mode 垂直速度闭环（5–25Hz 建议）精度约 ±0.3–0.5m | 未真机验证；需遥控器 N 档、退出自动任务、控制权在 App |
| F3 | 航线任务 | KMZ/WPML 上传执行；**Mini 4 Pro 断点续飞官方不保证**（仅 M30/M3E/3T/3M） | 官方 wayline 教程；中断后只能重飞 |
| F4 | 航点数 | 官方 DJI Fly 原生上限 200；MSDK 侧以 `KeyMaxWaypointNum` 为准 | 超限 `E_PARAM_RANGE` |
| F5 | 速度 | 航点 0.1–15 m/s（安全层默认上限 15）；首飞建议 2–5 | spec §8；Mini 4 Pro 实际安全上限按测试确认 |
| F6 | 返航 | `KeyStartGoHome` + `KeyGoHomeHeight`（≤120m）；可 `KeyStopGoHome` 中止 | 返航高度须 ≥ 障碍高度 |
| F7 | 降落 | `KeyStartAutoLanding`；复杂环境可能需 `KeyConfirmLanding` | 桥接层不自动确认，交操作员 |
| F8 | 手动接管 | MSDK 允许遥控器打杆接管航点任务 | 任务状态监听可发现模式变化；接管优先于 App |
| F9 | 失联动作 | 预设 GO_BACK/HOVER/LAND（安全层要求=返航） | 由 DJI Fly/飞控参数决定；App 不可靠进程保活 |
| F10 | 断链（手机↔RC） | 飞控继续执行已上传任务或按失联动作；App 丢失遥测 | 任务在飞控端执行是 KMZ 方案的优势 |

## 3. 相机/云台/媒体能力边界

| # | 项 | 边界 |
|---|---|---|
| C1 | 拍照 | `KeyStartShootPhoto` 单拍；连拍由桥接层定时器逐张触发（便于逐张记录位姿），间隔 ≥1s 稳妥；快门后建议悬停 1s 再移动（防糊） |
| C2 | 曝光 | 支持 `KeyExposureMode/KeyShutterSpeed/KeyISO/KeyExposureCompensation/KeyMeteringMode/KeyAntiFlicker/KeyWhiteBalance`（Mini 4 Pro 能力清单命中）；**光圈固定**（`KeyApertureExisted` 可读但不可调） |
| C3 | 格式 | RAW/JPEG/RAW_JPEG（`PhotoFileFormat`）；拍 RAW 会显著增加存储/下载时间 |
| C4 | 云台 | 3 轴稳定；`KeyRotateByAngle`（ABSOLUTE_ANGLE）+ `KeyGimbalAttitude` 回读；Mini 4 Pro 俯仰 -90..0（水平 0），yaw 相对机头；航向可达范围依机型 |
| C5 | 录像 | `KeyStartRecord/KeyStopRecord`；分辨率帧率 `KeyVideoResolutionFrameRate`；高码率长录占用大 |
| C6 | 媒体下载 | `MediaFile.pullOriginalMediaFileFromCamera` 走图传链路，速度受链路带宽限制（数十 MB/s 级，实际远低）；大批量照片建议 SD 卡直读或分批下载；支持 offset 续传（桥接层重试） |
| C7 | SD 卡 | 需 U3 以上；`KeyCameraSDCardState` 异常（FULL/SLOW/NOT_INSERTED）时桥接层拒绝拍照（`E_STATE`） |
| C8 | 图传 | `ICameraStreamManager` 可用（5.8.0+），但本桥不依赖图传做采集（只做状态/调试可选） |

## 4. 遥测与延迟补偿（LLM 控制的关键限制）

| # | 项 | 边界 | 应对 |
|---|---|---|---|
| T1 | MSDK 遥测频率 | 官方口径**最高 10Hz**，实际视链路可能更低 | 桥接层默认 5Hz 发布；>10Hz 截断 |
| T2 | 电话/主线程排队 | Key 回调→HTTP 返回可能几十~几百 ms | 快照带 `age_ms`；Orchestrator 在飞行/返航/abort 决策前重读遥测并要求 `age_ms < 1500ms`（建议阈值，可配） |
| T3 | LLM 延迟 | 本机 4B 模型单轮工具决策数百 ms~数秒；多轮更久 | **LLM 只做意图与参数**；长任务由设备端状态机执行（KMZ 在飞控端跑）；LLM 不参与实时控制回路 |
| T4 | 控制时延 | 命令→SDK→飞控实际响应 100ms 级+链路 | 安全关键动作（abort/RTH）留给设备端/遥控器，不依赖 LLM 及时性 |
| T5 | 时钟 | 手机墙钟可能漂移；真机无仿真时间 | `ts` 统一 ISO8601 并由 NTP 校时；`sim_time_s=null`；用 `mono_ms/age_ms` 度量时延 |
| T6 | 状态推断 | flight mode/GoHomeState 等枚举可能滞后/抖动 | 完成判定加 2s 稳定窗口；状态机以 SDK 监听为主、遥测为辅 |

## 5. 手机/网络/工程限制

| # | 项 | 边界 | 应对 |
|---|---|---|---|
| M1 | 手机算力 | 桥接层 + DJI SDK 常驻，低端机可能掉帧/发热 | 只做桥接；LLM/规划放 PC 或按单机部署降低负载；关后台省电 |
| M2 | 手机温度 | 长时间飞行+解码+网络易发热降频 | 避免阳光直射；任务间隙散热；监控 `KeyBatteryTemperature`（机型支持时） |
| M3 | 网络拓扑 | App 默认仅绑 127.0.0.1（USB adb forward）；双机热点方案需 token/隔离（骨架未实现 token/WS，设计预留） | 演示优先 USB 转发；禁止公网暴露 |
| M4 | 进程存活 | Android 电池优化/内存回收会杀 App | 前台服务 + 关闭电池优化 + 常亮；仍失败则重启 App（飞控任务可能继续） |
| M5 | 编译环境 | 本机无 Android SDK/JDK 配套，**骨架未编译** | 在有 Android Studio 的机器编译；真机前必须完成 T0/T1 |
| M6 | 依赖体积 | DJI AAR 133MB+，首同步慢 | 首次构建预留时间；不要重复清缓存 |
| M7 | 机型/固件升级 | 固件升级后 Key 支持/行为可能变化 | 每次升级后重跑 T1；记录版本到 run_meta |
| M8 | 单机单任务 | 桥接层一次只跑一个任务；无多机编队 | 需求外 |

## 6. KMZ/WPML 相关限制（最高工程风险）

| # | 项 | 边界/风险 | 应对 |
|---|---|---|---|
| K1 | KMZ 生成 | 桥接层按 WPML 规范 + 官方 sample 结构生成（template.kml + waylines.wpml）；**从未被 Mini 4 Pro 飞控接受过** | 真机 T3 第一件事就是上传最小 KMZ；失败时逐字段裁剪定位 |
| K2 | WPMZManager | 官方 sample 用 `com.dji:wpmzsdk:1.0.5.2` 的 `WPMZManager.generateKMZFile`；精确返回/校验语义未验证 | 生成后本地静态检查 + 真机上传验证 |
| K3 | 航点动作 | 拍照/云台/悬停动作依赖固件与 WPML 支持；`WaylineActionInfo` 构造参数未真机验证 | 最小动作集（TAKE_PHOTO + GIMBAL_ROTATE）优先；失败降级为“航点飞行 + 桥接层到点触发拍照”（虚拟摇杆/定时） |
| K4 | 断点续飞 | Mini 4 Pro 不在官方保证列表 | 不自动 resume；中断即 aborted，人工决定重飞 |
| K5 | 多 wayline | 一个 KMZ 可含多条 wayline；桥接层只取本次生成的 waylineIDs | 清楚记录 waylineIDs 与进度 |
| K6 | 坐标/高度模式 | WGS84 + RELATIVE_TO_START_POINT；高度基准是起飞点 | 起飞点地面高差会引入误差；3DGS 用 EXIF/GPS 校正 |
| K7 | 拍照位姿 | 真机无 UE c2w 真值；mission record 中 c2w 为**计划值推算**（estimated） | 3DGS 以 EXIF/XMP + 特征匹配（COLMAP）为主，计划位姿只作初值 |

## 7. 安全作动边界（不可协商）

1. 安全层默认阈值（限高 120m/限速 15/围栏 300m/禁飞区/电量 30% 起飞、20% 返航/GPS fix3+10星/RC 连接）**不得由 LLM 参数覆盖**；修改须人工在 App 配置并审计。
2. `takeoff/goto_waypoints/orbit/set_mode(real)` 必须 confirm=true 且 real 需设备端真机开关。
3. abort 永远可用、不排队；但最终安全兜底是**遥控器物理接管**，不是 App。
4. 断链/低电量/动态禁飞区命中 → 设备端强制返航，不等待 LLM 决策。
5. 任务执行中只允许 abort/get_telemetry/get_mission_status/return_to_home（spec 规则 16）。

## 8. 已知未验证项（诚实清单）

| # | 未验证项 | 风险 | 验证方式 |
|---|---|---|---|
| U1 | 骨架编译/安装 | 中 | 有 Android SDK 的机器上 `assembleDebug` |
| U2 | App Key 注册/绑定链路 | 中 | T1.1 |
| U3 | KMZ 被 Mini 4 Pro 接受 | **高** | T3 第一步 |
| U4 | 起飞爬升到指定高度的精度 | 中 | T2.2 |
| U5 | 相机/云台/媒体下载真机行为与字段单位 | 中 | T1.4–T1.7 |
| U6 | 遥测实际频率/时延与 `age_ms` | 中 | T1.2 记录 60s |
| U7 | abort/RTH/land 时序与状态机一致性 | 中高 | T2/T4 |
| U8 | 长时间任务手机发热/进程存活 | 中 | T3 多次重复 |
| U9 | 3DGS 用真实照片的位姿精度 | 中 | T3 后接 pipeline 训练对照 |

## 9. 结论

- **能做**：Mini 4 Pro + Android(RC-N2/N3) 下，MSDK v5.20.1 具备完整自动化采集所需 API（航线/相机/云台/媒体/遥测），LLM 只在“意图层”工作、设备端安全层兜底——工程可行。
- **不能做**：iOS、带屏 RC2、Mini 5 Pro/2 SE/4K、机载算力/上云 API、断点续飞保证、亚秒级 LLM 实时控制。
- **做到什么程度**：Phase 2 设计 + 可审阅骨架 + 真机协议；真机可用性以 `REAL_DRONE_TEST.md` T1–T4 全绿为准，当前**未执行**。
