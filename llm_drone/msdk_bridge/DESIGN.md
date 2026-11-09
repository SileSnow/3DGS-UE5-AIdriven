# Android MSDK v5 无人机桥设计（Phase 2：真机后端）

> 状态：v1.0 设计稿（2026-11-08）。对应任务：task-10。
> 上游规格：**`llm_drone/spec/PROTOCOL.md` v1.0（FROZEN）+ `spec/tools.json` + `spec/sample_mission.json` 为唯一事实源**；`llm_drone/docs/CONTRACT.md` 是任务契约。两者冲突时以 FROZEN spec 为准。
> 配套文件：`README.md`（总览/契约/组件/部署/已验证-未验证边界/限制/风险）、`mapping.json`（工具→API 逐条映射，机器可读）、`evidence/API_SYMBOLS_VERIFIED.md`（符号核验证据）、`test_protocol.md`（真机测试协议与可勾选清单，本轮未执行）、`PROTOCOL_COMPLIANCE.md`（与 frozen spec 的逐条对照，含 real 模式 E_NOT_SUPPORTED）、`app/`（Kotlin 骨架）。
> 更新（恢复后收尾）：README/PROTOCOL_COMPLIANCE/test_protocol 已补齐；`LIMITS.md`（能力边界）与 `REAL_DRONE_TEST.md`（真机验证协议/通过标准/应急预案）作为配套文件已完成，与 test_protocol.md 互补：前者给能力与通过标准，后者给可勾选执行清单。
> 本机无 Android SDK，**骨架不要求编译**；语义与 API 调用链可直接审阅，真机联调按 `REAL_DRONE_TEST.md` 执行。

## 0. 一页结论

1. Phase 1 的 Drone Agent 接口（HTTP JSON）在 Phase 2 由 Android App 原样实现：同一 `/v1/*` 契约、同一安全语义、同一 mission/telemetry/audit schema；Orchestrator 只改 `--agent-url`，不改代码。
2. 桥接层 = **DJI MSDK v5（Android）**本地服务：手机通过 RC-N2 与 Mini 4 Pro 相连，App 内跑 HTTP/WS（默认 `127.0.0.1:8765`），把 `tool` 翻译为 MSDK 调用，并把遥测/mission 结果回传。
3. 三条不可协商的安全原则：
   - **LLM 永不直接接触 DJI SDK**，只产出工具调用；所有飞行指令经 App 侧 `SafetyGuard`（权威安全层）二次校验。
   - **拒绝优于截断**：超限参数一律返回 `E_*` 错误码，不做静默截断（便于对抗测试断言）。
   - **fail-closed**：SDK 未注册、机型不支持、禁飞区查询失败、Key 不可用 → 拒绝执行，绝不放行。
4. 机型限制先说清：MSDK v5 **只有 Android**；Mini 4 Pro 必须 **RC-N2（v5.13+）或 RC-N3（v5.17+）**，带屏 RC 2 不支持；Mini 5 Pro / Mini 2 SE / Mini 4K 无 SDK。详见 `LIMITS.md`。
5. 可行性结论：Mini 4 Pro + MSDK v5.20.1 具备“航线（KMZ/WPML）上传执行 + 相机/云台 + 媒体下载 + ≤10Hz 遥测”的完整自动化能力；风险集中在**真机安全流程、固件/App Key 绑定、断点续飞不保证**，均有降级方案。

## 1. 系统位置与总体架构

```
用户自然语言
   │
   ▼
① Orchestrator (Python, 本机)          —— LLM 工具循环/规划/澄清；plan_capture_mission/orbit 由确定性代码实现
   │  HTTP JSON：/v1/health /v1/telemetry /v1/command /v1/missions ... /v1/audit
   ▼
② Drone Agent（可替换后端）
   ├─ Phase 1：drone_sim（本机仿真，无真机）
   └─ Phase 2：Android MSDK v5 App（本目录 app/）   ◄── 本设计
          │  DJI Mobile SDK v5.20.1（Android）
          ▼
③ DJI Mini 4 Pro ── OcuSync ── DJI RC-N2 ── USB-C ── Android 手机
```

部署形态（Phase 2 推荐，二选一，安全等级不同）：

| 形态 | 拓扑 | 适用 | 风险 |
|---|---|---|---|
| A. 单机（推荐） | 手机 App 内 HTTP 服务绑定 `127.0.0.1:8765`；Orchestrator/LLM 直接跑在手机上（Termux/同机 Python） | Phase 2 演示、真机 | 无跨设备网络暴露；手机算力有限（见 LIMITS） |
| B. 双机 | 手机开热点，笔记本连入，App 绑定 `0.0.0.0:8765` + `X-Bridge-Token` + 强制 TLS/白名单（骨架仅留接口） | 需要本机 LLM 时 | 必须 token + 热点隔离；禁止公网 |

### 1.1 App 内部模块（与骨架文件一一对应）

```
MainActivity.kt          权限申请 / SDK init + registerApp / 连接状态 UI / 启动·停止服务 / 保持亮屏
  │
  ├─ DroneBridgeServer.kt    NanoHTTPD：/v1/* 路由、token 鉴权、command_id 幂等缓存、WS 遥测推送
  │     └─ CommandExecutor.kt  工具白名单 → SafetyGuard 校验 → 状态机 → MSDK 调用（异步回调桥接）→ MissionStore
  │
  ├─ SafetyGuard.kt         规则引擎：schema/白名单/mode/confirm/state/battery/gps/rc/alt/speed/geofence/nofly/能量估算；审计 JSONL
  ├─ TelemetryPublisher.kt  KeyManager listen → 遥测快照（默认 5Hz，上限 10Hz）+ mission 进度/照片对账 + age_ms 延迟标注
  └─ WaypointConverter.kt   waypoints → WaylineMission/Template → WPMZManager.generateKMZFile；orbit → 圆形航点
```

> **与 app/ 实际骨架的对应（以代码为准）**：包名 `com.gaia.llmdrone.bridge`；`DroneBridgeServer.kt` → `bridge/DroneBridgeServer.kt`；`CommandExecutor.kt` → `bridge/CommandExecutor.kt`；`TelemetryPublisher.kt` → `bridge/TelemetryPublisher.kt`；`WaypointConverter.kt` → `mission/WaypointConverter.kt`；`Protocol.kt` → `bridge/ProtocolDtos.kt`；`SafetyGuard.kt` → `safety/SafetyGuard.kt`。
> **设计预留但骨架未实现**：WebSocket 遥测推送、`X-Bridge-Token` 鉴权、双机部署（绑定 0.0.0.0）、`age_ms/mono_ms` 扩展字段、真机开关 UI；当前骨架只实现 HTTP 且默认绑定 127.0.0.1。

### 1.2 线程模型

- **HTTP 服务**：NanoHTTPD 工作线程池；请求处理不阻塞，命令提交给单线程 `commandExecutor` 串行执行（天然满足 spec §8 规则 16“任务执行中仅允许 abort/get_telemetry/get_mission_status/return_to_home”）。
- **MSDK 调用**：统一 post 到主线程 `Handler(Looper.getMainLooper())`（DJI 部分回调要求主线程，统一策略最稳），回调结果桥接为 `CompletableFuture`。
- **遥测**：KeyManager 回调（SDK 线程）只更新 `AtomicReference<Snapshot>`；`HandlerThread` 定时（200ms）打包/节流后广播给 WS 与被查询。
- **长任务**（航点、返航、降落）：状态机由监听器驱动（`WaypointMissionExecuteStateListener` / `KeyGoHomeState` / `KeyIsInLandingMode`），不轮询阻塞。
- **abort**：独立高优先级执行通道，跳过 `commandExecutor` 队列（只做状态快照校验），确保任务执行中也能立即停止。

### 1.3 连接/初始化状态机

```
BOOT → SDK_INIT(init) → SDK_REGISTERING(INITIALIZE_COMPLETE→registerApp) → REGISTERED
     → PRODUCT_CONNECTED(onProductConnect(productId)) → READY
任意状态 ── onProductDisconnect ──► PRODUCT_LOST（停止任务、拒绝飞行命令、E_RC_LINK）
READY 下 mode = dry_run | real（spec 允许 sim，但桥接层返回 E_NOT_SUPPORTED，见 PROTOCOL_COMPLIANCE.md）
```

- SDK 初始化调用链（官方 sample `MSDKManagerVM.kt`，已核验）：
  `SDKManager.getInstance().init(appContext, InitSettings(SDKLinKMode.LOCAL), SDKManagerCallback)`；
  在 `onInitProcess(event=INITIALIZE_COMPLETE)` 内调用 `SDKManager.getInstance().registerApp()`；
  产品连接由 `onProductConnect(productId)` 通知。
- 连接后做机型校验：`ProductKey.KeyProductType` 必须为 `ProductType.DJI_MINI_4_PRO`（或 Mini 3/3 Pro 白名单），否则 `E_NOT_SUPPORTED` 并提示（防呆：避免 App 误连其它机型）。
- 版本校验：`ProductKey.KeyFirmwareVersion`、SDK 版本（BuildConfig）记入 `/v1/health` 与审计；低于机型能力清单的 `supportedMinFirmwareVersion` → 预检 fail（不阻止只读遥测）。

## 2. 与 Frozen Spec v1.0 的接口实现

> 逐条对照见 `PROTOCOL_COMPLIANCE.md`（含 REAL 模式唯一字段差异 `sim_time_s=null`）。

### 2.1 HTTP 端点（App 实现 spec §3.2 前 6 个 + 2 个 E_NOT_SUPPORTED）

| 方法/路径 | App 实现 | 说明 |
|---|---|---|
| `GET /v1/health` | `DroneBridgeServer.handleHealth()` | `{ok, backend:"msdk", version, mode, time_scale:1.0, sdk_version, product, connected, ts}` |
| `GET /v1/telemetry` | `TelemetryPublisher.snapshot()` | spec §5 同构；`sim_time_s=null` |
| `POST /v1/command` | `CommandExecutor.dispatch()` | `{command_id, tool, args, confirm?, run_id?}`；幂等缓存最近 100 条 |
| `GET /v1/missions/{id}` | `MissionStore.get()` | spec §7.1 mission record；持久化 App files 目录 JSON |
| `GET /v1/missions?limit=10` | `MissionStore.list()` | 创建时间倒序 |
| `GET /v1/audit?since_seq=N` | `SafetyGuard.AuditLogger.eventsSince()` | 与落盘 JSONL 同源 |
| `POST /v1/reset` | 返回 `E_NOT_SUPPORTED` | 仿真专属 |
| `POST /v1/sim/config` | 返回 `E_NOT_SUPPORTED` | 仿真专属 |

通用约定（照抄 spec）：业务失败 HTTP 200 + `{ok:false, error:{code, message, details?}, telemetry:{...}}`；4xx/5xx 只用于协议/服务器错误；`command_id` 幂等；单请求超时 10s。

### 2.2 命令处理流水线

```
POST /v1/command
  → JSON schema 校验（tools.json 对应参数）              → E_SCHEMA / E_UNKNOWN_TOOL
  → 幂等缓存命中? → 返回首次结果
  → SafetyGuard.validate(tool, args, confirm, mode, snapshot, state)   （固定顺序，见 §4）
  → 状态机 transitions（idle/hovering/mission/returning/landing/aborted）
  → CommandExecutor.execute（dry_run 只校验+审计，不调 SDK）
  → MSDK 调用（CompletableFuture 桥接，失败映射 code）
  → 返回 {ok, command_id, tool, state, mission_id?, telemetry, warnings?}
  → 长任务异步推进，mission record 更新，WS 广播
```

## 3. 工具 → MSDK v5 API 映射表（每个工具 ≥1 API + 失败处理）

> 机器可读全量版：`mapping.json`（含每个调用的类/方法/回调/版本/证据编号）。下表为审阅用摘要；“失败处理”是桥接层**必须实现**的兜底语义。

| # | 工具 | 主要 MSDK v5 API（类.符号） | 成功判定 | 失败处理（关键） |
|---|---|---|---|---|
| 1 | `get_telemetry` | `KeyManager` listen/getValue：`FlightControllerKey.KeyAircraftLocation3D/KeyAltitude/KeyAircraftVelocity/KeyFlightMode/KeyIsFlying/KeyGPSSatelliteCount/KeyGPSSignalLevel`、`BatteryKey.KeyChargeRemainingInPercent`、`GimbalKey.KeyGimbalAttitude`、`RemoteControllerKey.KeyConnection` | 返回快照 | 未连接返回最近缓存快照 + `stale_ms`/`E_RC_LINK` 标记；**永不抛出**导致 orchestrator 崩溃 |
| 2 | `preflight_check` | `SDKManager`（注册/产品连接）、`KeyManager.getValue`、`IFlyZoneManager.getFlyZonesInSurroundingArea`（失败降级本地禁飞多边形）、`ProductKey.KeyFirmwareVersion`、`CameraKey.KeyCameraSDCardState` | 逐项 pass/fail | 任一硬项 fail → `can_fly=false`（仍 HTTP 200）；禁飞查询异常标记 `flyzone_api=unavailable` 且 `can_fly=false`（fail-closed） |
| 3 | `plan_capture_mission` | 无（executor=orchestrator）；App 收到时返回 `E_UNKNOWN_TOOL` | — | 白名单不含该工具 → 审计拒绝 |
| 4 | `takeoff` | `FlightControllerKey.KeyStartTakeoff.create().action(...)`；到目标高度：`VirtualStickManager.enableVirtualStick/setVirtualStickAdvancedModeEnabled(true)/sendVirtualStickAdvancedParam(VirtualStickFlightControlParam)` 爬升，`KeyAltitude` 到位判定；或降级为单航点 KMZ 任务（见 §6） | `KeyIsFlying=true` 且 `|alt - target| <= 0.5m` 持续 2s | MSDK 失败/toast 超时 → `E_INTERNAL`+回滚（禁用虚拟摇杆、原地悬停、审计）；起飞中失败 → 尝试 `KeyStartAutoLanding`；遥控器不在 N 档 → 预检拒绝 `E_STATE` |
| 5 | `goto_waypoints` | `WPMZManager.generateKMZFile`（KMZ/WPML）→ `WaypointMissionManager.pushKMZFileToAircraft(path, CompletionCallbackWithProgress<Double>)` → `getAvailableWaylineIDs` → `startMission(missionFileName, waylineIDs, cb)`；进度：`addWaylineExecutingInfoListener/addWaypointMissionExecuteStateListener/addWaypointActionListener` | state=`EXECUTING`→`FINISHED`；mission record completed | 上传失败 → 重试 1 次（指数退避），再失败 `E_INTERNAL`+保持悬停；start 失败 → 悬停+`E_STATE`；执行中断（`INTERRUPTED`/`DISCONNECTED`）→ mission failed + 建议 RTH；**断点续飞不保证**（Mini 4 Pro 不在官方列表）→ 不自动 resume |
| 6 | `orbit` | 无桥接命令（executor=orchestrator）；Orchestrator 展开为圆形航点 → `goto_waypoints` 同链路。设备端备选：`IntelligentFlightManager.poiMissionManager.startMission(POITarget, null, cb)`（本桥不启用，理由见 mapping.json） | 同 goto_waypoints | 同 goto_waypoints；若航点数 > 200 → `E_PARAM_RANGE` |
| 7 | `set_gimbal` | `KeyManager.performAction(KeyTools.createKey(GimbalKey.KeyRotateByAngle, LEFT_OR_MAIN), GimbalAngleRotation(mode=ABSOLUTE_ANGLE,pitch,...), cb)`；回读 `GimbalKey.KeyGimbalAttitude` | 回读角度误差 ≤2°（1s 内） | 超时/角度不可达 → 重试 1 次，仍失败 `E_INTERNAL`（不阻断拍照，返回 warning）；pitch 越界 → `E_PARAM_RANGE`；云台自检异常 `E_STATE` |
| 8 | `capture_photo` | `CameraKey.KeyCameraMode` setValue(PHOTO_NORMAL) → `CameraKey.KeyShootPhotoMode` setValue(NORMAL) → `KeyStartShootPhoto.create().action(...)` × count（由桥接层定时器控制 interval）；`KeyIsShootingPhoto/KeyCameraStoringFile` 完成判定；`KeyNewlyGeneratedMediaFile` 记录文件名 | 每张有 `KeyNewlyGeneratedMediaFile` 或 `KeyIsTakingPhoto` 结束 | SD 卡异常（`KeyCameraSDCardState != NORMAL`）→ 预检拒绝 `E_STATE`；拍照失败 → `E_INTERNAL`+已拍张数返回；count>20 或 interval 越界 → `E_PARAM_RANGE`；**快门后不立即移动**（真机协议要求悬停 1s） |
| 9 | `start_video` | `CameraKey.KeyStartRecord.create().action(...)`；`KeyIsRecording` 回读 | `KeyIsRecording=true` | 已在录像 → 幂等返回 ok（warning）；SD 卡满 → `E_STATE` |
| 10 | `stop_video` | `CameraKey.KeyStopRecord`；`KeyIsRecording` 回读 | `false` | 未在录像 → 幂等 ok；停止后等待 1s 再移动（协议要求） |
| 11 | `return_to_home` | `FlightControllerKey.KeyStartGoHome.create().action(...)`；`KeyGoHomeState`(`FCGoHomeState`) 监听；`KeyStopGoHome` 可中止；预检时 `KeyGoHomeHeight` setValue（≤120m，≥作业高度） | `GoHomeState.COMPLETED`/`KeyIsFlying=false` | 返航中可被 `abort` 打断（`KeyStopGoHome`→悬停）；超时（>预估 2 倍）→ 保持监听+审计告警，不重复下发 |
| 12 | `land` | `FlightControllerKey.KeyStartAutoLanding.create().action(...)`；`KeyIsInLandingMode/KeyIsFlying`；复杂环境 `KeyConfirmLanding` | `KeyIsFlying=false` | 已在地面 → 幂等 ok；降落被确认机制阻塞 → 返回 `state=landing_confirm_required`（不自动确认）；超时 → 审计告警 |
| 13 | `abort` | 按当前状态：`WaypointMissionManager.stopMission` + `KeyStopGoHome`/`KeyStopAutoLanding`/`KeyStopTakeoff` + 虚拟摇杆零速/禁用（悬停） | 1.5s 内 state=hovering（空中）或 idle（地面） | 任何异常 → 强制尝试 `KeyStartGoHome`（最后兜底）+ 审计；abort 不排队，直接执行 |
| 14 | `get_mission_status` | `MissionStore` + `WaylineExecutingInfoListener`（currentWaypointIndex）+ `MediaDataCenter.getInstance().mediaManager` 照片对账 | 返回 mission record | 未找到 → `E_MISSION_NOT_FOUND`；进度缺失 → 用已完成动作数/总拍照点数估算 |
| 15 | `set_mode` | 桥接层内部模式机（无直接 SDK API）；`real` 需 confirm + 人工确认（App UI/预置开关） | mode 切换成功 | 状态非 idle → `E_STATE`；`sim` → `E_NOT_SUPPORTED`；`real` 无 confirm → `E_CONFIRM_REQUIRED`；`real` 未连接真机 → `E_RC_LINK` |

**跨工具通用失败语义**：MSDK 错误对象 `IDJIError` → 映射到 spec 错误码（`E_RC_LINK/E_STATE/E_INTERNAL/...`），保留 `details.msdk_error = error.description()/errorCode`；所有失败写审计；不把 SDK 异常抛成 HTTP 5xx。

## 4. 安全层二次校验（SafetyGuard，权威）

> 定位：Orchestrator 侧可做预检，但**安全结果只认 App 侧**（spec §1）。App 独立实现 spec §8 全部 16 条规则，默认阈值不可被 LLM 参数覆盖；可在 App 设置页调整，但调整写审计。

| 规则 | 默认 | 错误码 | 实现要点 |
|---|---|---|---|
| 最大相对高度 | 120m | E_ALT_LIMIT | 校验 takeoff.altitude_m 与每个 waypoint.alt_rel_m |
| 最大水平速度 | 15 m/s | E_SPEED_LIMIT | waypoints[].speed_mps 与 flight.speed_mps |
| 圆形围栏 | 中心 (39.9042,116.4074) R=300m | E_GEOFENCE | haversine 到 center；配置可换 |
| 禁飞区多边形 | spec §8.1 | E_NOFLY | 射线法 point-in-polygon；高度区间 [0,120] |
| 起飞电量 | ≥30% | E_BATTERY_TAKEOFF | BatteryKey.KeyChargeRemainingInPercent |
| 返航保留 | ≥20% | E_BATTERY_RTH | 估计任务往返能量（距离/速度+悬停），不足拒绝 |
| 飞行中低电量 | <20% | —（force RTH） | 遥测线程触发：stopMission→KeyStartGoHome，审计 `force_rth` |
| GPS | fix≥3 且 sats≥10 | E_GPS | KeyGPSSatelliteCount + KeyGPSSignalLevel（见 evidence TODO 4） |
| 遥控链路 | 必须连接 | E_RC_LINK | RemoteControllerKey.KeyConnection && ProductKey.KeyConnection |
| 指令白名单 | tools.json 13 个 agent 工具 | E_UNKNOWN_TOOL | 不在白名单直接拒 |
| 参数 schema+范围 | tools.json | E_SCHEMA / E_PARAM_RANGE | 严格类型、拒绝多余字段、拒绝静默截断 |
| 二次确认 | takeoff/goto_waypoints/set_mode(real) | E_CONFIRM_REQUIRED | 除 confirm 外，real 模式还需 App 内“真机开关”=ON |
| 状态合法性 | 状态机 | E_STATE | 未起飞 land / 飞行中 takeoff / 非 idle set_mode 等 |
| 并发命令 | 任务中仅 abort/get_telemetry/get_mission_status/return_to_home | E_BUSY | 单线程执行器 + 显式白名单 |
| 机型/固件 | Mini 4 Pro 白名单 | E_NOT_SUPPORTED | ProductType + capability 清单 |
| 审计 | 不可关闭 | — | JSONL：ts/seq/run_id/event/tool/command_id/decision/error_code/reasons |

补充硬规则（App 独有，优先级高于 LLM 意图）：
- `abort` 白名单例外，永不排队、永不因参数校验失败被拒（缺 reason 时自动补 `"unspecified"`）。
- 所有飞行命令要求 `state ∈ {idle, hovering, mission, returning, landing}` 的合法组合；`dry_run` 下全部只校验不执行（返回 simulated=true）。
- 任务执行中低电量/链路丢失/禁飞区动态命中 → 立即 force RTH（不询问 LLM）。
- 审计文件 `audit_<run_id>.jsonl`（App external files dir，滚动 50MB×5），`GET /v1/audit?since_seq=N` 可增量拉取。
- 真机开关（App UI，物理/软件双人确认位）关闭时 mode 恒为 dry_run，`set_mode(real)` 返回 `E_MODE`。

## 5. 遥测管线（≤10Hz + 延迟补偿）

### 5.1 字段映射（spec §5 同构）

| telemetry 字段 | MSDK 来源 | 备注 |
|---|---|---|
| `ts` / `mono_ms` | 手机墙钟 / `SystemClock.elapsedRealtimeNanos` | `ts` ISO8601+08:00；`mono_ms` 毫秒 |
| `sim_time_s` | **null** | Phase2 与 Phase1 唯一字段差异（见 PROTOCOL_COMPLIANCE） |
| `state` | 桥接层状态机 | idle/taking_off/hovering/mission/returning/landing/aborted/failsafe |
| `lat`/`lon` | KeyAircraftLocation3D | WGS84 |
| `alt_rel_m` | KeyAltitude（相对起飞点） | 已用 KeyTakeoffLocationAltitude 结合校准 |
| `alt_abs_m` | KeyTakeoffLocationAltitude + KeyAltitude（或 LocationCoordinate3D.altitude） | |
| `speed_mps` / `vertical_speed_mps` | KeyAircraftVelocity (Velocity3D) | 水平=sqrt(x²+y²) |
| `battery_pct` | BatteryKey.KeyChargeRemainingInPercent | 冗余：KeyBatteryPowerPercent |
| `gimbal{pitch,yaw,roll}` | GimbalKey.KeyGimbalAttitude (Attitude) | |
| `gps{fix,satellites}` | KeyGPSSignalLevel→fix(level-1 映射 0..5)、KeyGPSSatelliteCount | |
| `rc{connected,signal}` | RemoteControllerKey.KeyConnection + OcuSync/AirLink 信号（未核验，先给 good/unknown） | |
| `mode` | dry_run/real | |
| `mission_id` | 当前 mission | |
| `home{lat,lon,alt_abs_m}` | KeyHomeLocation (+ 起飞点海拔) | |
| `age_ms`（扩展，**骨架未实现**） | 采样到发布的时延 | 设计预留，见 PROTOCOL_COMPLIANCE §5.4 |

### 5.2 频率与节流

- MSDK 侧监听回调实际可达 ~10Hz（官方口径上限 10Hz，视链路/机型）；桥接层**默认 5Hz 发布**（200ms），可配置 1–10Hz，>10Hz 截断到 10Hz。
- 多 Key 更新合并为**单个快照**发布（避免一个字段变一次发一次）；相同字段去重（仅时间戳变化不推送，除非距上次 >1s 的心跳）。
- 姿态/速度用于拍照触发判定时以**采样时刻**为准：mission 照片记录里保存 `ts`、`mono_ms` 与触发时的快照，而不是收到 HTTP 时的状态。

### 5.3 延迟补偿（给 LLM/Orchestrator 的约定）

- 桥接层在每个快照中给出 `age_ms`（Key 采样→HTTP/WS 返回的时延，含主线程排队）；WS 推送里另有 `publish_ms`。
- 控制指令下发时间戳 `command_received_ts` 与状态变化 `state_since_ms` 写审计，便于计算“LLM 决策 → 执行”端到端时延。
- **LLM 决策基于过期状态的风险**：Orchestrator 应在 `takeoff/return_to_home/abort` 前重新 `get_telemetry` 并检查 `age_ms < 1500ms`（建议阈值，见 LIMITS.md §4）；桥接层也会在执行前按 spec 规则重新校验一遍（双保险）。
- 不做“预测/插值”控制（安全关键场景宁慢勿错）；仅遥测展示层可在 WS 侧做单调时间戳插值。

## 6. 航线子系统（KMZ/WPML）

### 6.1 执行链路（官方 sample 写法，已核验）

```
waypoints (spec §6 mission JSON)
  → WaypointConverter.buildKmz(): WaylineMissionConfig + Template + WaylineWaypoint[]
  → WPMZManager.getInstance().init(context)            // 进程内一次
  → WPMZManager.getInstance().generateKMZFile(kmzPath, waylineMission, missionConfig, template)
  → WaypointMissionManager.getInstance().pushKMZFileToAircraft(kmzPath, progressCb)   // 重试 1 次
  → getAvailableWaylineIDs(missionFileName)            // 取本次 KMZ 的 wayline
  → startMission(missionFileName, waylineIDs, cb)
  → 进度：WaylineExecutingInfoListener / WaypointActionListener / WaypointMissionExecuteStateListener
```

- **航点最小间隔**：真机要求相邻航点水平距离 ≥1m（否则跳过）；转换器在生成时做去重/合并并记录 warning。
- **速度**：航点 `speed_mps` 生效范围 0.1–15（Mini 4 Pro 实际安全上限按 15，测试用 2–5）。
- **拍照动作**：`WaylineActionInfo(actionType=TAKE_PHOTO)` 在到达航点后执行；`photo_interval_s` 用桥接层定时器逐张触发（便于逐张记录遥测），不依赖飞控 INTERVAL 模式（3DGS 需要每张有独立位姿记录）。
- **云台动作**：航点动作 `GIMBAL_ROTATE`（ABSOLUTE_ANGLE）；到位后再 TAKE_PHOTO（顺序动作组，`WaylineActionsRelationType.SEQUENCE`）。
- **目标点环绕**：Orchestrator 生成圆形航点（半径/张数/朝向中心），桥接层不启用 POI 智能飞行（无法精确指定拍摄点序列）。
- **断点续飞**：官方仅保证 M30/M3E/3T/3M；Mini 4 Pro 不在列 → 桥接层**不自动 resume**；中断后 state=aborted，需人工判断是否重新执行（记录 `break_info` 到审计）。
- **航点数上限**：spec/计划工具控制 ≤200（DJI Fly 原生上限 200，MSDK 侧以 `KeyMaxWaypointNum` 读取为准，超限 `E_PARAM_RANGE`）。

### 6.2 task JSON 与 WPML 的字段对照

| spec mission waypoint 字段 | WPML/Wayline 字段 | 说明 |
|---|---|---|
| lat/lon/alt_rel_m | `WaylineLocationCoordinate3D(latitude, longitude, altitude)` + `WaylineAltitudeMode.RELATIVE_TO_START_POINT` | WGS84，相对起飞点 |
| speed_mps | `WaylineWaypoint.speed`（或全局 autoFlightSpeed） | 0.1–15 |
| heading_deg | `WaylineWaypointYawParam(yawMode=FOLLOW_WAYLINE/…) / WaylineWaypoint.yaw` | 以 sample 的 `WaylineWaypointYawMode` 为准 |
| gimbal_pitch_deg | `WaylineActionInfo(GIMBAL_ROTATE, ActionGimbalRotateParam(enablePitch, pitch, rotateMode=ABSOLUTE_ANGLE))` | sample 写法 |
| action=photo | `WaylineActionInfo(TAKE_PHOTO, ActionTakePhotoParam(...))` | |
| action=video_start/stop | `START_RECORD / STOP_RECORD`（ActionStartRecordParam/ActionStopRecordParam） | |
| 全局速度/结束动作 | `WaylineMissionConfig.finishAction=WaylineFinishedAction.GO_HOME`；`exitOnRCLostType=WaylineExitOnRCLostAction.GO_BACK` | 失联返航 |

## 7. 媒体下载与 metadata 闭环

- 拍照完成判定后：`MediaDataCenter.getInstance().mediaManager` 拉取文件列表（`pullMediaFileListFromCamera(PullMediaFileListParam.Builder()...)`，监听 `MediaFileListState.UP_TO_DATE`），按 `KeyNewlyGeneratedMediaFile` 的 dir/file 编号匹配本次任务照片。
- 下载：`MediaFile.pullOriginalMediaFileFromCamera(offset, MediaFileDownloadListener)` 流式写入 App external files `missions/<mission_id>/photos/`；**断点续传**：用 offset+已写字节重试（最多 3 次），并记录 `downloaded_bytes`。
- 元数据：每张照片落一条 record（file/ts/lat/lon/alt_rel_m/alt_abs_m/heading_deg/gimbal{pitch,yaw,roll}），写入 mission record 的 `photos[]`，满足 spec §7.1；不伪造 `c2w`（真机没有 UE 坐标系真值，c2w 仅仿真/UE 渲染提供）。
- 下载失败不阻塞 mission completed：mission record 标 `photos[].file=null, download_error`，并返回 `warnings`，Orchestrator 可重试 `get_mission_status`。

## 8. 失败处理与降级总表

| 场景 | 桥接层动作 | 返回 |
|---|---|---|
| SDK 未注册/产品未连接 | 拒绝飞行类命令；只读遥测返回 stale 快照 | `E_RC_LINK` |
| 机型不在白名单 | 拒绝所有 agent 命令（只读 health 可查） | `E_NOT_SUPPORTED` |
| KMZ 生成/静态校验失败 | 不调用上传；记录日志 | `E_INTERNAL` |
| 上传失败 | 重试 1 次（指数退避 1s/2s），仍失败 → 保持悬停 | `E_INTERNAL` |
| 任务中断（INTERRUPTED） | mission failed；建议 Orchestrator 调 `return_to_home`；不自动 resume | state=aborted |
| 任务执行中断链 | `INTERRUPTED/DISCONNECTED` 监听 | 审计 + mission failed |
| 相机忙/存储异常 | 预检拦截；执行中失败返回已拍张数 | `E_STATE` / `E_INTERNAL` |
| 云台角度不可达 | 重试 1 次；不阻断拍照流程 | `E_INTERNAL`（warning） |
| 低电量（飞行中） | force RTH | telemetry.state=returning + 审计 |
| HTTP 服务异常 | NanoHTTPD 捕获异常→500（仅协议错误） | 业务错误仍 200 |
| 手机进程被杀 | mission 记录已落盘；重连后 health 报告 `last_mission_state` | 需人工确认 |
| abort 时 SDK 全挂 | 记录 + 提示用遥控器物理返航（真机协议强制要求操作员在环） | 审计 |

## 9. App 工程结构与依赖（骨架见 `app/`）

```
app/
  settings.gradle.kts / build.gradle.kts / gradle.properties   Gradle KTS 根工程（AGP 8.7.0 / Kotlin 2.1.0）
  app/build.gradle.kts        com.dji:dji-sdk-v5-aircraft:5.20.1 / -provided / -networkImp / nanohttpd / appcompat / coroutines
  app/proguard-rules.pro      MSDK 保留规则（release 骨架阶段未开启混淆）
  app/src/main/AndroidManifest.xml 权限、com.dji.sdk.API_KEY meta-data、USB accessory、前台服务
  app/src/main/res/xml/accessory_filter.xml, res/values/strings.xml
  app/src/main/java/com/gaia/llmdrone/bridge/
    DJIApplication.kt         Helper.install + MsdkInitManager.init
    MainActivity.kt           运行时权限、启动前台服务、状态展示（骨架级 UI）
    msdk/MsdkInitManager.kt   SDKManager.init(InitSettings) + registerApp() 回调、注册/连接状态
    msdk/AircraftConnectionManager.kt  KeyConnection 监听、机型白名单、固件读取、绑定校验占位
    bridge/DroneBridgeServer.kt NanoHTTPD 8 端点、默认绑定 127.0.0.1
    bridge/BridgeService.kt   前台服务，承载 server 与监听器
    bridge/CommandExecutor.kt   幂等缓存、白名单、SafetyGuard、异步执行、响应构造
    bridge/BridgeRuntime.kt   mode/state/当前 mission_id
    bridge/TelemetryPublisher.kt  DJIKey → spec §5 遥测；state 推导
    bridge/ProtocolDtos.kt    DTO + org.json 序列化 + Responses/ApiError
    bridge/ErrorMapper.kt     IDJIError → spec 错误码
    bridge/MissionStore.kt    mission record 内存 + JSON 落盘
    bridge/AuditLogger.kt     审计 JSONL + 环形缓冲
    flight/FlightController.kt  起飞/爬升/降落/返航/停止/悬停
    mission/WaypointMissionController.kt  KMZ 上传/start/pause/resume/stop/监听
    mission/WaypointConverter.kt          mission JSON → KMZ/WPML（未验证）
    mission/MissionExecutor.kt            任务编排 + 照片对账 + c2w 推算
    camera/CameraController.kt            拍照/录像
    gimbal/GimbalController.kt            云台角度
    media/MediaDownloader.kt              媒体列表/下载
    safety/SafetyGuard.kt + SafetyConfig.kt + GeoFence.kt  设备端安全规则
```

关键依赖（与官方 sample 完全一致，`5.20.1` 于 2026-11-05 发布）：

```kotlin
// app/build.gradle.kts
implementation("com.dji:dji-sdk-v5-aircraft:5.20.1")
compileOnly("com.dji:dji-sdk-v5-aircraft-provided:5.20.1")
implementation("com.dji:dji-sdk-v5-networkImp:5.20.1")   // 官方 sample 同款（网络注册/授权依赖）
implementation("com.dji:wpmzsdk:1.0.5.2")               // KMZ/WPML 编辑（WPMZManager）
implementation("org.nanohttpd:nanohttpd:2.3.1")
implementation("org.nanohttpd:nanohttpd-websocket:2.3.1")
```

- `minSdk 24 / targetSdk 35 / compileSdk 35`，`abiFilters arm64-v8a`，`extractNativeLibs=true`，打包忽略列表照抄官方 sample（避免 libc++_shared 冲突）。
- App Key：DJI 开发者账号创建 App（包名 `com.gaia.dronebridge`）→ App Key 写入 `gradle.properties`（`AIRCRAFT_API_KEY`）→ manifest `com.dji.sdk.API_KEY` meta-data；App Key 与包名/签名绑定，换签名需重新申请。
- 网络：DJI SDK 需要联网激活/校验（networkImp）；室内可先离线只读遥测（仍建议先在 DJI Fly 完成首次激活与固件升级）。

## 10. 与 Phase 1 仿真的差异

见 `PROTOCOL_COMPLIANCE.md`。要点：
1. `sim_time_s=null`（real 模式无仿真时间），其余 telemetry 字段同构；
2. `/v1/reset`、`/v1/sim/config` 返回 `E_NOT_SUPPORTED`；
3. `set_mode`：`sim` 在 Phase 2 返回 `E_NOT_SUPPORTED`（DJI SimulatorManager 需飞机上电且不属本阶段验收）；`real` 在 App 真机开关打开且 confirm=true 时生效；
4. 真机 state 迁移依赖 SDK 监听器，可能比仿真慢/有抖动：mission 完成判定加 2s 稳定窗口；断链时 state→failsafe。
5. **spec v1.1 §15 对齐**：real 的 `sim_time_s=null` 合法；`photos[].c2w` 为估算值，必须带 `pose_source=estimated` 与 `pose_accuracy_m`（无 RTK 默认 3.0m，可配 1–10m）；设备就绪错误用 `E_RC_LINK.details.reason ∈ {not_registered, not_connected}`、机型不符用 `E_STATE.details.reason=aircraft_mismatch`（实现见 `ErrorMapper` / `ProtocolDtos.PhotoRecord` / `MissionExecutor`）。

## 11. 验证策略（真机细节见 test_protocol.md，本轮未执行）

| 阶段 | 内容 | 通过标准 |
|---|---|---|
| T0 离线 | 静态审阅 + 骨架编译（待 Android SDK）+ spec 对照 | PROTOCOL_COMPLIANCE 全绿 |
| T1 地面拆桨 | 上电连接、遥测 5Hz、云台、拍照、媒体下载、中止演练（不启动电机） | 无异常码；照片落盘；abort 1.5s 内 state=hovering/idle |
| T2 室内悬停 | 无桨保护/开阔室内 5m 悬停 30s、RTH、降落（需教练/安全员） | 高度/速度限内；RTH 完整 |
| T3 空旷场地 | 1 个 2×2 网格任务、4 张照片、自动 RTH | mission completed；照片元数据完整 |
| T4 故障演练 | 低电量/链路丢失/任务中 abort/相机忙 | 按 §8 正确处置，审计齐全 |

## 12. 参考

- `llm_drone/spec/PROTOCOL.md`（**v1.1 FROZEN**，§15 已对齐）、`spec/tools.json`、`spec/sample_mission.json`
- `llm_drone/msdk_bridge/mapping.json`（逐调用映射、证据编号 S1–S20）
- `llm_drone/msdk_bridge/evidence/API_SYMBOLS_VERIFIED.md`（5.20.1 符号核验）
- `docs/research/01_DJI_Mini_SDK能力矩阵.md`、`06_Mini4Pro_3DGS采集SOP.md`
- DJI 官方：Mobile SDK V5 产品页 / API Reference（developer.dji.com）/ GitHub `dji-sdk/Mobile-SDK-Android-V5` / WPML 规范
