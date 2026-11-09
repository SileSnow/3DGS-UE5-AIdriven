# PROTOCOL_COMPLIANCE —— 桥接层与 spec v1.0（FROZEN）逐条对照

> 对象：llm_drone/spec/PROTOCOL.md（v1.0 FROZEN）、spec/tools.json、spec/sample_mission.json。
> 实现：llm_drone/msdk_bridge/app/（Kotlin 骨架，**未编译/未真机**）。
> 结论：端点、命令、遥测/任务字段、错误码与 spec 对齐；**3 处需 Lead 确认的差异/扩展**（§2、§5），另有 1 处已知实现偏差（审计 run_id，§5.3）与 5 项未实现项（§5.4）。

## 1. 端点对照（spec §3.2）

| # | spec 端点 | 实现位置 | 一致性 | 备注 |
|---|---|---|---|---|
| 1 | GET /v1/health | bridge/DroneBridgeServer.kt 的 healthJson() | 一致 | backend="msdk"、mode、time_scale=1.0、ts；附加只读 device{}（§5.1） |
| 2 | GET /v1/telemetry | bridge/TelemetryPublisher.kt 的 snapshot() | 一致（1 字段差异） | 字段齐全；**sim_time_s=null**（§2.1） |
| 3 | POST /v1/command | bridge/CommandExecutor.kt 的 dispatch() | 一致 | 幂等/白名单/confirm/异步接受（§3） |
| 4 | GET /v1/missions/{mission_id} | bridge/MissionStore.kt 的 get() | 一致 | §7.1 字段；photos[].c2w 为推算值（§2.2） |
| 5 | GET /v1/missions?limit=10 | DroneBridgeServer.kt | 一致 | {ok, missions:[...]} 创建时间倒序 |
| 6 | GET /v1/audit?since_seq=N | bridge/AuditLogger.kt 的 eventsSince() | 一致 | {ok, events[], last_seq}；同时 JSONL 落盘 |
| 7 | POST /v1/reset（仿真专属） | Responses.notSupported() | 一致 | 返回 E_NOT_SUPPORTED |
| 8 | POST /v1/sim/config（仿真专属） | Responses.notSupported() | 一致 | 返回 E_NOT_SUPPORTED |

通用约定：业务失败 HTTP 200 + {ok:false,error:{code,message,details?},telemetry:{...}}；4xx/5xx 仅协议/服务器错误（当前实现仅未知端点返回 HTTP 404 + JSON）；command_id 幂等为内存缓存最近 100 条（进程重启失效，真机长跑需注意）。

## 2. 字段级差异（已由 spec v1.1 §15 裁决，2026-11-08）

### 2.1 telemetry.sim_time_s（real 模式）
- spec §5 含 sim_time_s（float，仿真秒）；real 模式无仿真时间。
- 实现：real 返回 **null**（保留字段以维持 schema 形状）；mode=real、state 按 §5 枚举（idle/taking_off/hovering/mission/returning/landing/aborted/failsafe）。
- 影响：若 Orchestrator 假定 sim_time_s 为数字会报错；建议 Orchestrator 侧对 real 后端不使用该字段。
- **裁决（spec v1.1 §15.1）**：real 模式允许 `sim_time_s=null`；Orchestrator 必须容忍，任务时长由 `started_at/ended_at` 差值写入 stats.duration_s。当前实现即为 null，符合。

### 2.2 mission.photos[].c2w（real 模式）
- spec §7.1 要求 photos 含 c2w（16 floats），§7.2 给出公式。
- 实现：桥接层用「计划航点 lat/lon/alt + 计划 heading + 计划云台 pitch」代入 §7.2 公式写入 photos[].c2w；它**不是真值**（real 无 UE 坐标系真值），已在 MissionExecutor.estimateC2w() 注释与 README §7 标注 estimated。
- 风险：实际到点误差/云台稳定/风偏使位姿先验精度低于仿真；3DGS 建议以 EXIF/XMP + 特征匹配为主、c2w 为初值。
- **裁决（spec v1.1 §15.2）**：real 允许估算值，必须带 `pose_source="estimated"` 与 `pose_accuracy_m`（无 RTK 默认 3.0m，可配 1–10m）；遥测缺失时允许 `c2w=null` + `pose_source="unavailable"`。实现：`ProtocolDtos.PhotoRecord` 已增加 `poseSource/poseAccuracyM` 并在 `toJson()` 输出 `pose_source/pose_accuracy_m`；`MissionExecutor` 写入 estimated + 3.0m。

### 2.3 goto_waypoints 的 plan_id
- tools.json 允许 plan_id；spec §4 注「优先传 plan_id（由 Orchestrator 展开为航点）」。
- 实现：桥接层**要求**请求携带已展开的 mission（对象）或 waypoints（数组）；仅有 plan_id 时返回 E_SCHEMA（details.has_plan_id=true，提示需 Orchestrator 展开）。
- 理由：桥接层不持有 Orchestrator 的 plan 存储；要求 Orchestrator 实现必须展开后再转发（与 spec 注一致）。

## 3. 命令对照（spec §4 + tools.json）

| 工具 | spec 参数 | 实现 | confirm | 说明 |
|---|---|---|---|---|
| get_telemetry | {} | 实现 | 否 | /v1/command 或 /v1/telemetry |
| preflight_check | {} | 实现 | 否 | 响应附 can_fly + checks[]（spec §4 要求） |
| plan_capture_mission | — | 不实现 | — | executor=orchestrator；桥接层返回 E_UNKNOWN_TOOL |
| takeoff | altitude_m, confirm | 实现 | **是** | 0<alt<=120；电量>=30；GPS fix>=3 且 sats>=10；RC 连接；state=idle |
| goto_waypoints | mission/waypoints, speed_mps?, take_photos?, photo_interval_s?, confirm | 实现 | **是** | 逐航点校验；需已起飞；异步接受 |
| orbit | — | 不实现 | — | executor=orchestrator；Orchestrator 展开为圆形航点后走 goto_waypoints |
| set_gimbal | pitch_deg, yaw_deg? | 实现 | 否 | -90<=pitch<=0；-180<=yaw<=180；需空中 |
| capture_photo | count?, interval_s? | 实现 | 否 | 1<=count<=20；0<=interval<=10；需空中 |
| start_video / stop_video | {} | 实现 | 否 | 需空中 |
| return_to_home | {} | 实现 | 否 | 空中有效；设置返航高度（默认 100m，<=120m）后 KeyStartGoHome |
| land | {} | 实现 | 否 | 空中有效；KeyStartAutoLanding + 需要时 KeyConfirmLanding |
| abort | reason | 实现 | 否 | 停任务 + 悬停（不自动返航）；白名单例外、不排队 |
| get_mission_status | mission_id? | 实现 | 否 | 省略查最近任务；无记录返回 E_MISSION_NOT_FOUND |
| set_mode | mode, confirm | 实现 | real 需 **是** | dry_run/real；sim -> E_NOT_SUPPORTED；切换需 idle |

**confirm 处理**：CommandRequest.parse() 取「请求体顶层 confirm OR args.confirm」，任一 true 即视为已确认；兼容 tools.json（confirm 在 args 内）与 spec §3.3 示例（confirm 在顶层），不降低安全性（仍需 SafetyGuard 放行）。

**校验顺序（spec §4 固定）**：schema -> whitelist -> mode -> confirm -> state -> battery -> gps -> rc -> altitude/speed 范围 -> geofence -> no-fly -> 返航能量估算 -> 允许（见 safety/SafetyGuard.validate()）。**Phase2 附加**：在 confirm 与 state 之间插入设备就绪检查（MSDK 已注册 / 产品&RC 已连接 / 机型在 Mini 4 Pro 白名单），失败映射 E_RC_LINK（未注册或未连接）或 E_STATE（机型不符）。**请 Lead 认可该映射**。

## 4. 错误码对照（spec §8.2，共 21 个）

| spec 错误码 | 桥接层产生位置 | 触发条件 |
|---|---|---|
| E_SCHEMA | SafetyGuard.schemaError / CommandExecutor | 缺字段/类型错/多余字段；goto_waypoints 缺展开航点 |
| E_PARAM_RANGE | SafetyGuard.rangeError | 云台/拍照参数物理范围非法 |
| E_UNKNOWN_TOOL | CommandExecutor.dispatch | 不在 13 工具白名单（含 plan_capture_mission/orbit） |
| E_CONFIRM_REQUIRED | SafetyGuard.validate | takeoff/goto_waypoints/set_mode(real) 无 confirm |
| E_MODE | （预留，未产生） | 当前由 set_mode/E_NOT_SUPPORTED 覆盖；如需严格对齐可补 |
| E_STATE | SafetyGuard.stateError | 未起飞 land、飞行中 takeoff、非 idle set_mode、机型不符 |
| E_BUSY | CommandExecutor.dispatch | 任务执行中收到并发飞行命令 |
| E_ALT_LIMIT | SafetyGuard.rangeError | altitude_m 或航点 alt_rel_m >120 或 <=0 |
| E_SPEED_LIMIT | SafetyGuard.rangeError | speed_mps >15 或 <=0 |
| E_GEOFENCE | SafetyGuard.geofenceError | 航点超出圆形围栏（默认 300m） |
| E_NOFLY | SafetyGuard.noFlyError | 航点位于禁飞多边形（spec §8.1） |
| E_BATTERY_TAKEOFF | SafetyGuard.validate | 电量 <30% 时 takeoff |
| E_BATTERY_RTH | SafetyGuard.rthEnergyError | 起飞前能量估算不足（保留 20%） |
| E_GPS | SafetyGuard.validate | fix<3 或 sats<10 时 takeoff |
| E_RC_LINK | SafetyGuard.validate / ErrorMapper | RC 未连接、MSDK 未注册、产品未连接 |
| E_MISSION_NOT_FOUND | CommandExecutor / ErrorMapper | mission_id 不存在 |
| E_REAL_NOT_AVAILABLE | 桥接层不产生 | Phase2 已接 real；该码属 Phase1 语义 |
| E_NOT_SUPPORTED | Responses.notSupported / set_mode(sim) | /v1/reset、/v1/sim/config、sim 模式 |
| E_NOT_AIRBORNE | SafetyGuard.stateError | 拍照/云台/录像在非空中状态 |
| E_INTERNAL | ErrorMapper.internal/fromMsdk | 未归类 MSDK 错误/内部异常（details 保留 IDJIError） |
| E_UNKNOWN_TOOL | 同 E_UNKNOWN_TOOL 行 | 同上 |

> 说明：飞行中低电量（<20%）强制 RTH 目前依赖飞控自身策略 + 桥接层状态观测（GoHomeState.RETURNING_TO_HOME 可识别）；「主动触发 force RTH」标记为待真机补全（spec §8 规则 7）。

## 5. 扩展（additive）与实现偏差（需 Lead 批准/知晓）

### 5.1 /v1/health 附加只读字段
device{msdk_registered, product_connected, sdk_version}：只读、向后兼容；不改变 spec 既有字段语义。

### 5.2 命令响应附加字段
mission_id（goto_waypoints 必需，spec §3.3 示例已有）、executed（dry_run 时 false）、reason（abort）、mission（get_mission_status 附带记录）、can_fly/checks（preflight）。

### 5.3 审计 run_id 偏差（已知）
AuditLogger.init(ctx, "default") 固定文件名 audit_default.jsonl；CommandRequest.run_id 未用于切换审计文件（因 /v1/reset 在 real 不可用）。影响：多次 run 复用同一 JSONL，需按时间/seq 区分；后续版本可用首个命令 run_id 初始化文件名（AuditLogger.events(runId) 已预留）。

### 5.4 未实现的 spec 项（诚实列表）
1. spec §8 规则 7「飞行中低电量主动强制 RTH」的触发逻辑（当前依赖飞控 + 状态观测）。
2. E_MODE（真机开关关闭时 set_mode(real) 拒绝）——骨架 mode 机已有，App 内真机开关 UI 未实现。
3. spec §12 的 demo run 目录/指标（Orchestrator 职责，不属桥接层）。
4. WS 遥测推送（spec 允许 HTTP 或 WS；骨架只实现 HTTP，DESIGN.md 中的 WS/token 为设计预留）。
5. /v1/missions 分页（仅 limit，无 cursor；spec 未要求）。

## 6. 未验证项（与「符合 spec」无关，但影响真机可用性）

- KMZ/WPML 能否被 Mini 4 Pro 接受（最高风险，WaypointConverter.kt 全部 TODO(未确认) 字段）。
- GimbalAngleRotation 构造参数顺序、VirtualStickFlightControlParam setter 名、WaylineExecutingInfo 字段。
- 遥测 Key 在 Mini 4 Pro 上的可读性/单位；gps.fix 由 GPSSignalLevel 映射的准确性。
- MediaFile 时间戳字段与照片对账正确性。
- 编译可行性（本机无 Android SDK）。

## 7. spec v1.1 §15 对齐（2026-11-08，补充决议）

| # | v1.1 决议 | 桥接层实现 | 状态 |
|---|---|---|---|
| 1 | real 允许 sim_time_s=null；时长用墙钟差值 | TelemetrySnapshot.simTimeS=null；MissionRecord.durationSeconds 用 started_at/ended_at | 已实现 |
| 2 | real photos[].c2w 为估算值，必须 pose_source=estimated + pose_accuracy_m（默认 3.0m）；遥测缺失 c2w=null + pose_source=unavailable | PhotoRecord 新增 pose_source/pose_accuracy_m 并在 JSON 输出；MissionExecutor 写 estimated + POSE_ACCURACY_M=3.0 | 已实现（骨架） |
| 3 | 设备就绪错误码细节：未注册→E_RC_LINK.reason=not_registered；未连接→E_RC_LINK.reason=not_connected；机型不符→E_STATE.reason=aircraft_mismatch | ErrorMapper.notRegistered/notConnected/aircraftMismatch；SafetyGuard 设备就绪检查改用它 | 已实现（骨架） |
| 4 | 不新增顶层错误码 | 沿用 spec §8.2 的 21 个错误码 | 已遵守 |

## 8. 对照结论

- spec §1–§4、§5（除 sim_time_s）、§7（除 c2w 语义）、§8.2 错误码、§3.2 端点：已按 1:1 实现或声明差异。
- 原待 Lead 决策项已由 spec v1.1 §15 裁决（sim_time_s=null、c2w=estimated+pose_accuracy_m、设备就绪 details.reason），实现已按 §7 对齐。
- 真机可用性证据：**无**（未执行）。

## 8. T9 复核结论（docs/research/08、10 交叉核对，2026-11-08）

| 项 | 结果 |
|---|---|
| 核对条目 | 47（API 名称/签名 27 + KMZ/WPML 20） |
| 一致 | 24 |
| 需修正 | 16（本轮已写入代码/映射 13；文档同步 3） |
| TODO（必须真机/官方枚举） | 7：Mini 4 Pro WPML droneEnum/payload enum、per-waypoint heading 落地、multipleTiming 支持性、executeHeightMode/EGM96、MediaFile 时间戳、AirlinkKey/机型 Key 名、Kotlin 编译与真机行为 |
| 对 spec 的影响 | 无接口变化；spec v1.1 §15 三项已实现并文档对齐（§2/§3/§7） |
| 详细清单 | 见 REVIEW_vs_research.md |

本轮修正摘要：WaypointConverter.kt 按 10 重写；WaypointMissionController 监听器改具名接口实现；GimbalAngleRotation/createKey、VirtualStickFlightControlParam 包名与控制模式、MediaDownloader.enable()、TelemetryPublisher listen 双参回调；mapping.json 升 v1.1（补 S21/S22 来源与 research_review 块）。**仍未编译、未真机。**
