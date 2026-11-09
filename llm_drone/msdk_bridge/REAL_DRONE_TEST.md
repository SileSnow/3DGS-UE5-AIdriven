# 真机验证协议 —— DJI Mini 4 Pro × MSDK v5 Android 桥（Phase 2）

> 状态：**协议文档（v1.0，2026-11-08），本轮尚未执行**。无真机、无 Android SDK、无飞行许可，本文是“可执行的真机验证步骤 + 通过标准 + 应急方案”，不是飞行结果。
> 关联：`test_protocol.md`（可勾选执行清单）、`README.md`（部署步骤）、`DESIGN.md`（设计）、`LIMITS.md`（能力边界）、`mapping.json`（工具→API）。
> 铁律：**本协议任何一步失败都不允许“带病放飞”**；飞行类步骤必须有第二人（安全员）在场，且遥控器物理接管始终可用。

## 1. 前置条件（全部满足才允许进入 T1）

### 1.1 硬件

| 项 | 要求 | 核验方式 |
|---|---|---|
| 飞行器 | DJI Mini 4 Pro，机身无损伤、桨叶完好、电池健康 | 目视 + DJI Fly 电池信息 |
| 遥控器 | **DJI RC-N2**（MSDK v5.13.0 起）或 **RC-N3**（v5.17.0 起）；**DJI RC / RC 2 带屏遥控器不支持第三方 App，禁止使用** | 型号铭牌 |
| 手机 | Android 10+，arm64-v8a，USB-C OTG，开发者选项 + USB 调试；推荐 8GB RAM 以上 | 设置 → 关于手机 |
| 线缆 | 原装/认证 USB-C 数据线（**必须支持数据传输**，很多充电线不行） | 连接后 adb devices 可见 |
| 存储 | 手机剩余空间 ≥ 8GB（照片/日志）；飞机 SD 卡剩余 ≥ 8GB、速度 U3 | DJI Fly / 设置 |

### 1.2 软件与账号

1. **DJI 开发者账号**：developer.dji.com 注册 → 创建 App（Android，包名 `com.gaia.llmdrone.bridge`，填写签名证书 SHA-256）→ 获取 App Key。
   - App Key 写入 `app/gradle.properties` 的 `AIRCRAFT_API_KEY`（仅本地，不入库）；换签名/包名必须重新申请。
   - 首次联网注册需要网络；注册失败优先检查：包名/签名是否与申请一致、手机时间是否准确、是否被代理拦截。
2. **DJI Fly**：先用官方 App 完成飞机激活、固件升级、账号绑定、SD 卡格式化。
   - 已知配套版本（MSDK v5.13.0 Release Notes 口径）：Mini 4 Pro 机身 `01.00.0800`、RC-N2 `01.01.0300`；MSDK 5.20.1 可能要求更新固件，以当次 Release Notes 与 App 内提示为准。**升级后必须重新跑 T1**。
   - 机型能力清单（AAR `DJIMini4ProFlightControllerCapability.json`）标注 `supportedMSDKVersion=5.13.0`、`supportedMinFirmwareVersion=30.05.17.01`（该字段为机型能力库版本口径，不等于机身固件号）。
3. **账号绑定**：Mini 4 Pro 与 RC-N2 必须已用 DJI Fly 完成绑定（换遥控器后不重新绑定会持续报绑定校验错误——官方 v5.3.0 Release Notes 明确提示）。
4. **本项目**：Orchestrator/sim 侧 T1 之前先跑通仿真链路（本机 `python -m sim.server` + `orchestrator.run_demo`），确认契约侧无问题，再切真机。

### 1.3 环境

| 项 | 要求 |
|---|---|
| 温度/风速 | 环境温度 0–40°C；地面风速 ≤ 8 m/s（首飞建议 ≤5 m/s），无降水、无沙尘、能见度良好 |
| 场地（T3） | 空旷、无人群、无高压线/铁塔/信号塔，视距内；起飞点 10m 内无遮挡 |
| GPS | 起飞点开阔，≥10 颗卫星、定位精度良好；**远离机场/军事区/城市敏感区** |
| 人员 | 飞手 1 人（持遥控器）+ 安全员 1 人（看 App/空域/电量，口令放行）；T2 需教练/有资质人员 |
| 法规 | 实名登记、空域查询与报备（如当地要求）、飞行高度 ≤120m、视距内、避开禁飞区与人群；遵守当地法规与 DJI 使用条款 |
| 网络 | 手机联网（App Key 注册）；Orchestrator 与手机同一网络或 USB 转发 |

## 2. 部署与连通性（T1 前置，不起飞）

```bash
# 1) 安装（首次需在 Android Studio 构建；本机无 Android SDK，此步在具备环境的机器执行）
cd app && ./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk

# 2) USB：手机连电脑 → 打开 App（首次授予定位/通知/存储权限）→ 前台服务启动 HTTP
adb devices
adb forward tcp:8765 tcp:8765
curl -s http://127.0.0.1:8765/v1/health | python -m json.tool
# 期望：{"ok":true,"backend":"msdk","mode":"dry_run","connected":...}

curl -s http://127.0.0.1:8765/v1/telemetry | python -m json.tool
# 期望：字段与 spec §5 一致，sim_time_s=null，state=idle
```

- App 内必须显示：MSDK 注册成功、产品已连接（Mini 4 Pro）、机型校验通过、HTTP 监听 127.0.0.1:8765。
- 任何一项不满足 → 禁止进入 T1 飞行类步骤；先按 §7 排障。

## 3. 测试分级（T0 → T4，逐级放行）

> 放行规则：上一级全部通过且**双人签字**后才执行下一级。T2/T3/T4 任一失败 → 立即降级回 T1 并复盘。

### T0 离线审阅（无设备）

| 项 | 步骤 | 通过标准 |
|---|---|---|
| T0.1 | 审阅 `DESIGN.md` / `mapping.json` / `PROTOCOL_COMPLIANCE.md` / `README.md` | 15 工具映射无缺口；错误码与 spec §8.2 一致 |
| T0.2 | `python -c "import json;json.load(open('llm_drone/msdk_bridge/mapping.json'))"` | JSON 合法 |
| T0.3 | 仿真链路回归（sim + orchestrator） | P1–P3 / A1–A10 通过（由 Phase-1 验收覆盖） |
| T0.4 | 静态检查 App 源码（人工/IDE） | 无编造 API；TODO(未确认) 均有真机核验计划 |

### T1 地面拆桨（**必须卸下全部桨叶**；可在室内）

目的：验证 SDK 注册/连接/遥测/相机/云台/媒体/中止链路，**不产生升力、不起飞**。

| # | 步骤 | 操作 | 通过标准 |
|---|---|---|---|
| T1.1 | 上电连接 | 飞机 + RC-N2 开机，手机连 RC，App 启动 | health `connected=true`、telemetry 5Hz（连续 60s 无断流） |
| T1.2 | 遥测正确性 | 对照 DJI Fly 显示：经纬度/高度/电量/云台/GPS/RC | 桥接数值与 DJI Fly 一致（允许传感器误差：高度 ±0.5m、角度 ±2°） |
| T1.3 | preflight 只读 | `POST /v1/command {"command_id":"c-t1-1","tool":"preflight_check","args":{}}` | `can_fly=true`，checks 全 pass |
| T1.4 | 云台 | `set_gimbal` pitch=-45 → -90 → 0 | 回读 `KeyGimbalAttitude` 误差 ≤2°；动作 ≤3s |
| T1.5 | 拍照 | `capture_photo` count=3, interval_s=2 | 3 张落 SD 卡；mission/photos 记录 3 条；文件名可对账 |
| T1.6 | 录像 | start_video → 10s → stop_video | `KeyIsRecording` 正确翻转；文件可播放 |
| T1.7 | 媒体下载 | 触发媒体对账/下载（或 adb pull App 目录） | 至少 1 张原图完整下载（大小与文件头校验） |
| T1.8 | **不起飞保护** | 执行 `goto_waypoints`（confirm=true，地面状态） | 返回 `E_STATE`，飞机无任何动作，审计有拒绝记录 |
| T1.9 | 中止演练（地面） | 任务“执行中”时发 `abort`（用 dry_run 或模拟任务） | 1.5s 内 state=idle；审计 event=command_rejected/accepted 正确 |
| T1.10 | dry_run 全链路 | `set_mode(dry_run, confirm=true)` 后跑 takeoff/goto_waypoints | 全部只校验不执行，返回 simulated=true，无 SDK 动作 |

T1 通过标准：T1.1–T1.10 全绿 + 遥测 60s 稳定 + 无异常审计错误码（E_INTERNAL 为 0）。

### T2 室内悬停（需开阔室内/护桨/教练；否则跳过直接 T3）

| # | 步骤 | 操作 | 通过标准 |
|---|---|---|---|
| T2.1 | 环境确认 | 室内 ≥8m×8m×4m 高，无人员进入飞行区，地面平整，GPS 可用或视觉定位正常 | DJI Fly 提示可飞 |
| T2.2 | 起飞 | `takeoff altitude_m=5 confirm=true` | 起飞后稳定悬停 5m±0.5m；App state=taking_off→hovering |
| T2.3 | 悬停 30s | 观察 telemetry：高度/速度/电量/姿态 | 无漂移恐慌；高度波动 ≤1m；链路正常 |
| T2.4 | RTH | `return_to_home` | 返航→降落→`KeyIsFlying=false`；全程无手动干预 |
| T2.5 | 再次起飞 + land | takeoff 5m → `land` | 降落平稳、电机停转、state=idle |
| T2.6 | 空中 abort | 悬停时发 `abort` | 原地悬停（不返航），1.5s 内 state=hovering；再手动 land |
| T2.7 | 低电量强制返航 | 若可注入（仅仿真）；真机不注入，观察阈值告警即可 | 不主动制造真机低电量 |

> T2 风险高：仅在教练/有资质人员监督下进行；任何异常立即遥控器物理接管（见 §5）。

### T3 空旷场地：1 个网格任务（核心验收）

任务参数（与 spec 示例量级一致、体量最小）：

| 项 | 值 | 理由 |
|---|---|---|
| 区域 | 中心 (lat0, lon0)（实际场地坐标），边长 ~20m 方形（2×2 网格 = 4 拍照点） | 最小可验证闭环 |
| 高度 | 15m 相对起飞点 | 低空、视距内 |
| 速度 | 2 m/s | 保守 |
| 云台 | -45° | 与 3DGS 采集一致 |
| 重叠率 | 0.7 | 生成 4 点足够 |
| 结束动作 | 自动返航（RTH） | 安全兜底 |

执行顺序（Orchestrator 侧可用自然语言驱动，也可 curl 直调）：

1. `get_telemetry` → 检查 `age_ms < 1500ms`、电量 ≥50%（首飞建议）、GPS/RC 正常。
2. `preflight_check` → `can_fly=true`；检查返航高度（`KeyGoHomeHeight` 设为 ≥15m 且 ≤120m）。
3. `plan_capture_mission`（orchestrator）→ 得 plan_id + 4 个拍照点。
4. `takeoff altitude_m=15 confirm=true` → 稳定悬停。
5. `goto_waypoints`（mission JSON，含 4 waypoints，take_photos=true，photo_interval_s=1，confirm=true）→ 返回 mission_id。
6. 轮询 `/v1/telemetry` 与 `/v1/missions/{id}`：state=executing→completed，progress=100%，photos=4。
7. `return_to_home`（若未配置自动返航）→ 落地、state=idle。
8. 照片对账：mission record 4 条 + SD 卡/Ap p 目录 4 个原图 + 每张含 GPS/云台/时间戳。
9. `adb pull` 照片与审计/日志到本机 `data/dji/real_test/<run_id>/`（测试目录，不入库大文件）。

通过标准（全部满足）：
- 4 个航点全部执行、4 张照片、无人工接管、无安全告警；
- mission record `state=completed, progress_pct=100, n_photos=4`；
- 照片元数据字段完整（file/ts/lat/lon/alt_rel_m/gimbal）；
- 审计 JSONL 完整（command_received/safety_check/command_accepted/photo_captured/mission_completed）；
- 全程天空/地面无风险事件；落地后电量 ≥30%。

### T4 故障与中止演练（T3 之后，仍空载/空旷）

| # | 场景 | 注入/操作 | 通过标准 |
|---|---|---|---|
| T4.1 | 任务中 abort | 任务执行到第 2 点时 `abort reason="drill"` | 1.5s 内停止航点并悬停；mission=aborted；审计含 abort；随后手动 RTH |
| T4.2 | 任务中 return_to_home | 执行中发 `return_to_home` | 允许（spec 规则 16 白名单）；任务停止并返航 |
| T4.3 | App 断连 | 飞行中强制停止 App（模拟进程被杀） | 飞控按失联动作（GO_BACK/HOVER，按预配置）执行；重连后 health 报告 last_mission_state；**必须提前将失联动作设为返航** |
| T4.4 | 遥控器接管 | 飞行中拨杆接管（MSDK 允许手动接管航点任务） | 手动控制生效；App 监控到模式变化；随后切回自动/降落 |
| T4.5 | 低电量策略 | 不主动制造；若真实触发 <20% | 桥接层 force RTH 生效，审计 force_rth |
| T4.6 | 相机/SD 异常 | 拔 SD 卡（地面）后拍照 | 返回 `E_STATE`（SD 卡异常），不误飞 |
| T4.7 | 非法参数/无确认 | 超限高/超速/围栏外/confirm=false | 全部 `E_*` 拒绝且飞机不动（对照 spec A1–A5/A9） |

## 4. 每次起飞前的固定检查单（打印随身）

1. 桨叶完好、电机无异物、机臂展开锁紧、电池卡扣到位、电量 ≥50%（首飞）。
2. RC-N2 与手机连接正常、App health `connected=true`、机型=DJI_MINI_4_PRO、固件版本记录。
3. GPS ≥10 星、返航点已刷新、返航高度 15–120m、失联动作=返航、低电量告警阈值默认。
4. 空域已确认：无禁飞区、无人员、无高压线；安全员就位；遥控器物理接管已演练。
5. App 模式：先 `dry_run` 跑一遍命令校验，再 `set_mode(real, confirm=true)`。
6. 起飞点半径 3m 内无人；飞机朝向安全方向；风速 ≤5m/s。

## 5. 应急中止 SOP（按优先级）

1. **遥控器物理接管**（最高优先级）：打杆 → 飞机进入手动控制；必要时内八/一键返航按键。
2. **App 级中止**：`POST /v1/command {"command_id":"c-abort-<ts>","tool":"abort","args":{"reason":"..."}}` → 停止任务并悬停（不自动返航）。
3. **返航**：`return_to_home`（或遥控器 RTH 键）；确认返航高度不会撞障碍。
4. **紧急降落**：远离人群/障碍的空地 → `land`；如 App 失效，用遥控器自动降落。
5. **失控/失联**：不追逐；等待失联动作执行；按 DJI 飞丢流程处理并记录。
6. **人员受伤/火情**：先撤离人员、拨打应急电话；飞行安全优先于设备。

> 任何应急事件后：立即 `abort`、落地、记录时间线与审计、复盘后才允许再次飞行。

## 6. 记录与证据（每次 run 一个目录）

```
data/dji/real_test/<run_id>/
  run_meta.json        # 日期/地点(脱敏)/人员/机型/固件/App 版本/MSDK 版本/天气/风速
  preflight.json       # preflight_check 响应
  telemetry_log.jsonl  # 采样遥测（含 age_ms）
  command_log.jsonl    # 每个 /v1/command 请求与响应
  agent_audit.jsonl    # 从 App external files dir 拉取
  mission.json         # 实际下发的 mission JSON
  mission_record.json  # GET /v1/missions/{id}
  photos/              # 原图（或仅清单+大小/MD5）
  video/               # 录屏（手机屏幕 + 遥控器画面）
  checklist.md         # §3/§4 勾选结果 + 签字
  summary.md           # 通过/失败、偏差、结论、待办
```

- 时间同步：手机与电脑 NTP 同步；日志统一 ISO8601。
- 采集命令（示例）：`adb pull /sdcard/Android/data/com.gaia.llmdrone.bridge/files/audit_default.jsonl`、`adb logcat -d -s DJI:V MSDK:V > logcat.txt`。
- 证据只写“发生了什么”，不得补写/美化；失败也照录（这正是任务要求的诚实边界）。

## 7. 排障表

| 症状 | 可能原因 | 处理 |
|---|---|---|
| health 一直 connected=false | RC/飞机未开机；USB 线仅充电；App 未获 USB 权限 | 换数据线、确认 USB 弹窗授权、重启 App/RC |
| 注册失败（App Key） | 包名/签名不匹配；无网络；Key 未激活 | 核对申请信息；连网；重新申请 Key |
| E_NOT_SUPPORTED（机型） | 连到非白名单机型（如 Mini 5 Pro） | 换 Mini 4 Pro；只读遥测可看但禁止飞行 |
| telemetry 中断/错乱 | 链路差；Key 回调频率过高 | 降低采样到 5Hz；靠近飞机；检查干扰源 |
| KMZ 上传失败 | WPML 字段不合规/WPMZManager 未 init | 本地静态校验 KMZ；看审计 details.msdk_error；真机联调放宽字段逐项试 |
| 任务 start 失败 | 未取到 waylineIDs；飞控状态不 READY | 先上传→查 waylineIDs→再 start；确保 idle/悬停状态 |
| 拍照无文件 | SD 卡满/未插、相机 busy | 地面预检 SD 状态；等待上一张存储完成 |
| 媒体下载慢/失败 | 图传链路带宽 | 降分辨率或分批次；重试 offset 续传；优先 SD 卡直接拷 |
| App 被杀 | 电池优化/后台限制 | 关闭电池优化、保持前台服务、锁屏常亮 |

## 8. 退出标准与下一阶段

- T1 全绿 = 桥接层“软件/硬链接口可用”；T2 全绿 = 基础飞控闭环可用；T3 全绿 = 3DGS 采集链路真机闭环；T4 全绿 = 安全兜底可信。
- 全部通过后：把 T3 照片 + metadata 接入 `pipeline/03_train_3dgs.py` 做一次真实数据重建对照（与合成数据报告对比），作为项目最终可行性结论的真机证据。
- 未通过项按“阻塞/非阻塞”分类回填 `LIMITS.md` 与任务板；**不得在未通过时对外宣称真机可用**。

## 9. 合规与数据

- 遵守当地无人驾驶航空器法规：实名登记、空域申请/报备、限高 120m、视距内、避让有人机与人群。
- **禁止**使用逆向/固件修改工具绕过 GEO、限高、限速（违反 DJI 使用条款，见 `docs/research/01` §7）。
- 照片/遥测含 GPS 与人员影像：仅项目内部使用，外发脱敏；测试后按数据管理要求清理。
- App Key/账号凭据不入库；审计与日志脱敏后再共享。
