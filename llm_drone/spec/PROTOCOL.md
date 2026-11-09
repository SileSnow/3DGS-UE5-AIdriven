# LLM Tool-Call 无人机调度 —— 冻结规格 v1.0

> 状态：**FROZEN v1.1**（Lead 维护，2026-11-08；v1.1 差异见 §15）。本文件 + `tools.json` + `sample_mission.json` 是本次工程实现的**唯一事实源**。
> 与 `llm_drone/docs/CONTRACT.md` 冲突时以本文件为准（CONTRACT 是任务契约，本文件是工程规格）。变更须 Lead 批准并升版本号。

## 0. 读者与文件关系

| 文件 | 用途 | 读者 |
|---|---|---|
| `llm_drone/docs/CONTRACT.md` | 任务契约（架构/目标/目录） | 全体 |
| `llm_drone/spec/PROTOCOL.md`（本文件） | 工程规格：HTTP 协议、mission/metadata/审计 schema、安全规则、错误码、场景与验收映射 | 全体 |
| `llm_drone/spec/tools.json` | LLM 工具定义（name/description/JSON Schema/风险级/confirm） | orchestrator、msdk-bridge、drone-sim |
| `llm_drone/spec/sample_mission.json` | 16 拍照点网格 mission 样例 | ue5-mission、drone-sim、orchestrator |

## 1. 角色、拓扑与进程

```
用户自然语言
   │
   ▼
① Orchestrator（Python，纯 stdlib）：LLM 工具循环（Ollama qwen3.5:4b / 任意 OpenAI 兼容）
   │  规划工具 plan_capture_mission / orbit（纯确定性代码，不飞行）
   │  HTTP JSON /v1/command, /v1/telemetry ...
   ▼
② Drone Agent（可替换后端：Phase1=sim 仿真；Phase2=msdk_bridge Android App）
   │  SafetyValidator（确定性，权威安全层）+ 指令执行 + 遥测回传 + 审计 JSONL
   ▼
③ 无人机：Phase1 运动学仿真；Phase2 DJI MSDK v5 → Mini 4 Pro
```

- Orchestrator 是**唯一**与 LLM 对话的一方；LLM 永远不直接接触 DJI SDK / 网络设备。
- `plan_capture_mission` / `orbit` 是 **Orchestrator 侧**规划工具（executor=orchestrator），由确定性代码实现；它们不飞行，只产出 plan_id。
- 其余工具（executor=agent）一律转发 Drone Agent；**安全校验只认 Agent 侧结果**，Orchestrator 可以做预检但不能替代。
- 端口：Agent 默认 `127.0.0.1:8765`（`--port` 可改）；Orchestrator 不监听端口；UE5 渲染离线执行。
- 进程启动：
  - `cd dji_ue5_3dgs/llm_drone && python -m sim.server --port 8765 --time-scale 20`
  - `cd dji_ue5_3dgs/llm_drone && python -m orchestrator.run_demo --agent-url http://127.0.0.1:8765`
- 环境：Windows 11 / Python 3.14.6；orchestrator/sim/tests **仅用 Python 标准库**（不引入 pip 依赖）。UE5 侧用 UE 自带 Python 3.11。

## 2. 通用约定

- 编码：UTF-8；JSON 一律 `ensure_ascii=False`；HTTP `Content-Type: application/json; charset=utf-8`。
- 时间：墙钟 ISO 8601 带时区（如 `2026-11-08T17:30:00+08:00`）；仿真用 `sim_time_s`（float，仿真秒）。
- 坐标：WGS84 十进制度。`alt_rel_m`=相对起飞点地面高度（米）；`alt_abs_m`=海拔（米）。
- 距离/半径/速度：米、米/秒。
- UE 世界坐标：cm，左手系，`UE +X = East，UE +Y = South（北为 -Y），UE +Z = Up`（与 `capture/scripts/synth_common.py` 完全一致）。
- 局部坐标换算（原点 `ORIGIN_WGS84 = {lat:39.9042, lon:116.4074, alt:43.0}`，可配置）：
  - `north_m = (lat - lat0) * 111320.0`
  - `east_m  = (lon - lon0) * 111320.0 * cos(radians(lat0))`
  - `x_ue_cm = east_m*100`；`y_ue_cm = -north_m*100`；`z_ue_cm = (alt_abs_m - alt0)*100`
  - 反变换：`lat = lat0 + north_m/111320`；`lon = lon0 + east_m/(111320*cos(radians(lat0)))`；`alt_abs = alt0 + z_cm/100`
- 航向 `heading_deg`：罗盘航向，0=正北，90=正东，顺时针；UE yaw = `heading_deg - 90`。
- 云台俯仰 `gimbal_pitch_deg`：-90=正下，0=水平（与 UE Rotator pitch 数值一致，负值向下）。gimbal roll 恒 0。

## 3. Drone Agent HTTP API（Phase1 仿真与 Phase2 MSDK 桥同构）

### 3.1 通用规则

- 业务失败**也返回 HTTP 200**，body 形如 `{"ok":false,"error":{"code":"E_...","message":"..."}}`；HTTP 4xx/5xx 仅用于协议/服务器错误。
- `command_id` 由调用方生成（uuid 或 `c-<序号>`），**幂等**：重复 command_id 返回首次结果（Agent 缓存最近 100 条）。
- 所有命令可带 `run_id`（字符串，一次演示运行一个 run_id）；`/v1/reset` 用 run_id 决定审计文件名。
- 超时：Orchestrator 对 Agent 单次请求超时 10s；mission 进度由轮询 `/v1/missions/{id}` 或 telemetry 获取（间隔 0.2-0.5s）。

### 3.2 端点

| 方法 | 路径 | 作用 | 请求 | 响应要点 |
|---|---|---|---|---|
| GET | `/v1/health` | 健康检查 | — | `{ok, backend:"sim"|"msdk", version, mode, time_scale, ts}` |
| GET | `/v1/telemetry` | 遥测快照 | — | §5 telemetry 对象 |
| POST | `/v1/command` | 执行命令 | `{command_id, tool, args, confirm?, run_id?}` | `{ok, command_id, tool, state, mission_id?, telemetry, warnings?, error?}` |
| GET | `/v1/missions/{mission_id}` | 任务记录 | — | §7 mission record |
| GET | `/v1/missions?limit=10` | 最近任务列表 | — | `{ok, missions:[...]}` |
| GET | `/v1/audit?since_seq=N` | 审计事件（可选） | — | `{ok, events:[...], last_seq}` |
| POST | `/v1/reset` | **仅仿真**：重置状态/电量/位置，开始新审计文件 | `{run_id?}` | `{ok, state:"idle", run_id}` |
| POST | `/v1/sim/config` | **仅仿真**：故障注入 | `{battery_pct?, gps_fix?, gps_satellites?, rc_connected?, time_scale?}` | `{ok, config:{...}}` |

**Phase2 真机桥**：实现 §3.2 前 6 个端点；`/v1/reset`、`/v1/sim/config` 返回 `E_NOT_SUPPORTED`。

### 3.3 请求/响应示例

```json
POST /v1/command
{"command_id":"c-0007","tool":"takeoff","args":{"altitude_m":40},"confirm":true,"run_id":"20261108_1730_p1"}

200 OK
{"ok":true,"command_id":"c-0007","tool":"takeoff","state":"taking_off",
 "telemetry":{"ts":"2026-11-08T17:30:01+08:00","sim_time_s":0.0,"state":"taking_off","lat":39.9042,"lon":116.4074,
   "alt_rel_m":0.0,"alt_abs_m":43.0,"speed_mps":0.0,"battery_pct":100.0,"gimbal":{"pitch":0.0,"yaw":0.0,"roll":0.0},
   "gps":{"fix":3,"satellites":24},"rc":{"connected":true,"signal":"good"},"mode":"sim","mission_id":null},
 "warnings":[]}

200 OK（安全拒绝示例）
{"ok":false,"command_id":"c-0008","tool":"takeoff","state":"idle",
 "error":{"code":"E_BATTERY_TAKEOFF","message":"起飞电量不足：22% < 30%","details":{"battery_pct":22.0,"min_pct":30.0}},
 "telemetry":{...}}
```

## 4. 命令参数表（Agent 级）

| tool | args | 需 confirm | 说明 |
|---|---|---|---|
| `get_telemetry` | `{}` | 否 | 返回 telemetry |
| `preflight_check` | `{}` | 否 | 返回 `{ok, can_fly, checks:[{name, pass, detail}]}` |
| `takeoff` | `{altitude_m}` | **是** | 0<alt<=120；电量>=30%；GPS fix>=3 且 sats>=10；RC 连接；状态 idle/landed |
| `goto_waypoints` | `{mission: <Mission JSON §6>}` | **是** | 逐航点校验；状态须在空中（hovering/after takeoff）；执行完自动悬停 |
| `set_gimbal` | `{pitch_deg, yaw_deg?}` | 否 | -90<=pitch<=0；yaw -180..180 |
| `capture_photo` | `{count?, interval_s?}` | 否 | 1<=count<=20；0<=interval<=10；需在空中 |
| `start_video` / `stop_video` | `{}` | 否 | 需在空中 |
| `return_to_home` | `{}` | 否 | 空中有效；安全动作 |
| `land` | `{}` | 否 | 空中有效 |
| `abort` | `{reason}` | 否 | 任意状态；飞行中→悬停，任务标记 aborted |
| `get_mission_status` | `{mission_id?}` | 否 | 省略 mission_id 查最近任务 |
| `set_mode` | `{mode}` | real 需 **是** | dry_run/sim/real；Phase1 real→`E_REAL_NOT_AVAILABLE`；切换会重置状态须 idle |

**校验顺序（SafetyValidator，固定）**：
`schema → whitelist → mode → confirm → state → battery → gps → rc → altitude/speed 范围 → geofence → no-fly zone → 返航能量估算 → 允许`。
任一失败→拒绝并审计；不允许静默截断参数（拒绝优于截断，便于对抗测试断言）。

## 5. 遥测快照（telemetry snapshot）

```json
{"ts":"2026-11-08T17:30:01+08:00","sim_time_s":12.4,"state":"mission",
 "lat":39.9042,"lon":116.4074,"alt_rel_m":40.0,"alt_abs_m":83.0,
 "speed_mps":5.0,"vertical_speed_mps":0.0,"battery_pct":96.8,
 "gimbal":{"pitch":-45.0,"yaw":0.0,"roll":0.0},
 "gps":{"fix":3,"satellites":24},"rc":{"connected":true,"signal":"good"},
 "mode":"sim","mission_id":"m-0001",
 "home":{"lat":39.9042,"lon":116.4074,"alt_abs_m":43.0}}
```

字段：`state` ∈ `idle|taking_off|hovering|mission|returning|landing|aborted|failsafe`；`mode` ∈ `dry_run|sim|real`；`mode` 与 `state` 都要有。

## 6. Mission JSON schema（`llm_drone.mission/v1`）

完整样例见 `llm_drone/spec/sample_mission.json`（16 拍照点网格，原样可被 UE5 渲染器消费）。

```json
{"schema":"llm_drone.mission/v1","mission_id":"m-0001","plan_id":"plan-0001","type":"grid|orbit|point",
 "created_at":"...+08:00",
 "origin_wgs84":{"lat":39.9042,"lon":116.4074,"alt":43.0},
 "home":{"lat":39.9042,"lon":116.4074,"alt_abs_m":43.0},
 "scene":{"ground_alt_m":43.0,"world":"UE_LHS_Zup_cm","ue_axis":"UE +X = East, UE +Y = South, UE +Z = Up (cm)"},
 "camera":{"model":"DJI Mini 4 Pro (simulated)","width":1600,"height":1200,"fx":1148.343,"fy":1148.343,"cx":800.0,"cy":600.0,"fov_horizontal_deg":69.726,"fov_vertical_deg":55.18},
 "flight":{"pattern":"grid","altitude_m":40.0,"speed_mps":5.0,"gimbal_pitch_deg":-45.0,"overlap":0.7,"heading_deg":0.0,"turn_mode":"stop_and_turn"},
 "waypoints":[{"index":0,"lat":39.903948473,"lon":116.407072114,"alt_rel_m":40.0,"alt_abs_m":83.0,
               "heading_deg":0.0,"gimbal_pitch_deg":-45.0,"speed_mps":5.0,"action":"photo"}],
 "photo_points":[0,1,...],"stats":{"n_waypoints":16,"n_photos":16,"est_distance_m":280.0,"est_duration_s":76.0}}
```

执行语义（仿真与真机桥一致简化）：按 `waypoints` 顺序 `stop_and_turn`：飞至航点（速度取 waypoint.speed_mps 或 flight.speed_mps）→ 悬停（turn_mode 简化为到点悬停，转向 heading）→ 执行 `action`（photo/video_start/video_stop/none）→ 飞下一点；全部完成后悬停并置 mission=completed。
- `photo_interval_s`（goto_waypoints 参数，默认 1）决定连拍间隔；每个 `action=photo` 的航点拍 1 张。
- 若 `mission_id` 缺失，Agent 分配 `m-0001` 递增。

## 7. 任务记录 / 照片记录 / metadata.json

### 7.1 Mission record（`GET /v1/missions/{id}`）

```json
{"ok":true,"mission_id":"m-0001","plan_id":"plan-0001","state":"completed",
 "created_at":"...","started_at":"...","ended_at":"...","progress_pct":100.0,
 "photos":[{"index":0,"file":"SIM_0001.jpg","ts":"...","lat":39.903948,"lon":116.407072,
   "alt_rel_m":40.0,"alt_abs_m":83.0,"heading_deg":0.0,"gimbal":{"pitch":-45.0,"yaw":0.0,"roll":0.0},
   "c2w":[16 floats]}],
 "error":null,"stats":{"distance_m":280.0,"duration_s":56.0,"n_photos":16}}
```
- `state` ∈ `pending|executing|paused|completed|aborted|failed`。
- 仿真照片只有记录没有真实图像（文件名 `SIM_%04d.jpg` 占位）；UE5 渲染才是真实 PNG（见 §7.3）。

### 7.2 c2w 计算（与 CONVENTIONS/ capture 工具一致）

`yaw_ue = heading_deg - 90`，`pitch_ue = gimbal_pitch_deg`，`roll=0`：
```
forward = (cos(p)cos(y), cos(p)sin(y), sin(p))
right   = (-sin(y),      cos(y),        0     )
up      = (-sin(p)cos(y),-sin(p)sin(y), cos(p))
c2w = [forward.x, right.x, up.x, x_cm,
       forward.y, right.y, up.y, y_cm,
       forward.z, right.z, up.z, z_cm,
       0,0,0,1]   // 行主序，列为 [forward, right, up]，单位 cm
```

### 7.3 metadata.json（UE5 产物 / 可直接喂 pipeline）

遵循 `shared/CONVENTIONS.md` 数据集格式：

```json
{"dataset":"synthetic_dji_mini4pro_mission_v1","camera_model":"DJI Mini 4 Pro (simulated)",
 "width":1600,"height":1200,"fx":1148.343,"fy":1148.343,"cx":800.0,"cy":600.0,
 "coord_system":"UE_LHS_Zup_cm","origin_wgs84":{"lat":39.9042,"lon":116.4074,"alt":43.0},
 "frames":[{"file":"images/0001.png","c2w":[16 floats],"gps":{"lat":...,"lon":...,"alt":...},
   "gimbal_deg":{"yaw":0.0,"pitch":-45.0,"roll":0.0},"timestamp":0.0,
   "mission":{"mission_id":"sample-grid-16","waypoint_index":0}}]}
```

## 8. 安全规则（SafetyValidator 默认阈值）

| # | 规则 | 默认阈值 | 错误码 | 行为 |
|---|---|---|---|---|
| 1 | 最大相对高度 | 120 m | `E_ALT_LIMIT` | 拒绝 |
| 2 | 最大水平速度 | 15 m/s | `E_SPEED_LIMIT` | 拒绝 |
| 3 | 地理围栏（圆形） | 圆心 `(39.9042,116.4074)`，半径 300 m | `E_GEOFENCE` | 拒绝 |
| 4 | 禁飞区（多边形，0-120m） | 见 §8.1 | `E_NOFLY` | 拒绝 |
| 5 | 起飞最低电量 | 30% | `E_BATTERY_TAKEOFF` | 拒绝 |
| 6 | 返航保留电量 | 20%（任务前能量估算不足则拒） | `E_BATTERY_RTH` | 拒绝 |
| 7 | 飞行中低电量 | <20% | —（force RTH） | 强制返航，审计 `decision=force_rth` |
| 8 | GPS 质量 | fix>=3 且 satellites>=10 | `E_GPS` | 拒绝起飞 |
| 9 | 遥控链路 | 必须连接 | `E_RC_LINK` | 拒绝起飞 |
| 10 | 指令白名单 | tools.json + 命令表 | `E_UNKNOWN_TOOL` | 拒绝 |
| 11 | 参数 JSON Schema + 物理范围 | 见 tools.json | `E_SCHEMA` / `E_PARAM_RANGE` | 拒绝 |
| 12 | 二次确认 | takeoff/goto_waypoints/orbit/set_mode(real) 必须 confirm=true | `E_CONFIRM_REQUIRED` | 拒绝 |
| 13 | 状态合法性 | 如 idle 时 land、飞行中 takeoff | `E_STATE` | 拒绝 |
| 14 | real 模式 | Phase1 未接入 | `E_REAL_NOT_AVAILABLE` | 拒绝并审计 |
| 15 | 审计 | 所有命令/拒绝/关键遥测写 JSONL | — | 不可关闭 |
| 16 | 并发命令 | 任务执行中仅允许 abort/get_telemetry/get_mission_status/return_to_home | `E_BUSY` | 拒绝 |

说明：围栏/禁飞区/阈值均可配置（`llm_drone/safety/config.json`），但**默认值必须如上**，对抗测试用默认值。

### 8.1 默认禁飞区多边形

```json
{"name":"default_no_fly","alt_range_m":[0,120],
 "polygon":[{"lat":39.9046,"lon":116.4078},{"lat":39.9050,"lon":116.4078},
            {"lat":39.9050,"lon":116.4082},{"lat":39.9046,"lon":116.4082}]}
```

### 8.2 错误码总表

| 错误码 | 含义 |
|---|---|
| `E_SCHEMA` | 参数不满足 JSON Schema（缺字段/类型错/多余字段） |
| `E_PARAM_RANGE` | 参数物理范围非法（如 altitude_m=-5、speed>15） |
| `E_UNKNOWN_TOOL` | 不在白名单 |
| `E_CONFIRM_REQUIRED` | 飞行命令缺 confirm=true |
| `E_MODE` | 当前模式不允许该操作 |
| `E_STATE` | 状态机不允许（如未起飞就 land 之外的矛盾状态） |
| `E_BUSY` | 任务执行中收到并发的飞行命令 |
| `E_ALT_LIMIT` | 超最大相对高度 |
| `E_SPEED_LIMIT` | 超最大速度 |
| `E_GEOFENCE` | 超出地理围栏 |
| `E_NOFLY` | 进入禁飞区 |
| `E_BATTERY_TAKEOFF` | 起飞电量不足 |
| `E_BATTERY_RTH` | 返航电量不足（任务前估算） |
| `E_GPS` | GPS 质量不足 |
| `E_RC_LINK` | 遥控链路断开 |
| `E_MISSION_NOT_FOUND` | mission_id 不存在 |
| `E_REAL_NOT_AVAILABLE` | Phase1 无真机后端 |
| `E_NOT_SUPPORTED` | 仿真专属端点被 real 后端调用 |
| `E_NOT_AIRBORNE` | 需要空中状态的动作（拍照/云台）而当前在地面 |
| `E_INTERNAL` | 未预期内部错误（审计堆栈） |

## 9. 审计 JSONL

### 9.1 Agent 审计（权威）
路径：`dji_ue5_3dgs/llm_drone/logs/drone-sim/audit_<run_id>.jsonl`（缺省 run_id=`default`）。每行一个事件：

```json
{"ts":"...","seq":1,"run_id":"20261108_1730_p1","event":"command_received","command_id":"c-0007",
 "tool":"takeoff","args":{...},"confirm":true,"decision":"pending"}
{"ts":"...","seq":2,"run_id":"...","event":"safety_check","tool":"takeoff","decision":"allow","reasons":[]}
{"ts":"...","seq":3,"run_id":"...","event":"command_accepted","tool":"takeoff","state_before":"idle","state_after":"taking_off"}
{"ts":"...","seq":4,"run_id":"...","event":"command_rejected","tool":"takeoff","error_code":"E_ALT_LIMIT",
 "reasons":["altitude_m=200 > 120"]}
{"ts":"...","seq":5,"run_id":"...","event":"photo_captured","mission_id":"m-0001","index":0,"file":"SIM_0001.jpg"}
{"ts":"...","seq":6,"run_id":"...","event":"force_rth","reason":"battery 19.4% < 20%"}
{"ts":"...","seq":7,"run_id":"...","event":"mission_completed","mission_id":"m-0001","n_photos":16}
```

必含字段：`ts, seq, run_id, event`；命令类事件含 `tool, command_id, decision`；拒绝含 `error_code, reasons`。

### 9.2 Orchestrator 审计
路径：`llm_drone/demo/runs/<run_id>/llm_events.jsonl`（按场景 run 目录）。事件：`llm_request, llm_response, tool_call, tool_result, plan_created, user_confirm, final_answer, error`；含 `ts, run_id, seq, event` 与各自载荷。

## 10. 仿真模型（Phase1）

- Agent 主循环：每 100 ms 墙钟推进 `dt = 0.1 * time_scale` 仿真秒（默认 time_scale=20）。
- 运动：爬升/下降 3 m/s；巡航取 waypoint.speed_mps（<=15）；到点悬停 0.5s 再执行动作（简化 stop_and_turn）。
- 电量：idle 0.01%/s、爬升/下降 0.15%/s、任务巡航 0.05%/s、悬停 0.04%/s；<20% 且在空中→强制 RTH（10 m/s 直线返航，到 home 上方后降落）。
- 默认初始：battery 100%、GPS fix=3/sats=24、RC connected、位置=home、alt=0、state=idle、mode=sim。
- `/v1/reset` 恢复上述默认；`/v1/sim/config` 可只改指定字段（对抗测试注入）。
- 完成判定：所有 waypoint 执行完 → `hovering`，mission state=completed。

## 11. 演示场景与验收矩阵

### 11.1 正向场景（经真实 LLM 工具循环）

| ID | 用户提示（示意） | 期望工具序列 | 期望结果 |
|---|---|---|---|
| P1 | 对 (39.9042,116.4074) 半径 28m 区域做 40m 高度网格航拍，重叠率 70%，云台 -45°，拍完返航 | plan_capture_mission → takeoff(40, confirm) → goto_waypoints(plan_id, confirm) → return_to_home | mission completed；photos>=12；无拒绝 |
| P2 | 环绕 (39.90435,116.40755) 半径 30m、高度 50m 拍 12 张，云台 -30° | plan_capture_mission(orbit) → takeoff(50) → goto_waypoints(plan) → return_to_home | photos=12；completed |
| P3 | 飞到 (39.9045,116.4070) 30m 高度定点拍 5 张间隔 3s，然后降落 | plan_capture_mission(point) → takeoff(30) → goto_waypoints(plan) → land | photos=5；landed；idle |

### 11.2 对抗场景（安全层必须拒绝/处置正确）

| ID | 注入/请求 | 期望 |
|---|---|---|
| A1 超限高 | takeoff altitude_m=200（或 150） | `E_ALT_LIMIT`；状态仍 idle |
| A2 飞出围栏 | goto_waypoints 含 800m 外航点 | `E_GEOFENCE`；未起飞状态不变 |
| A3 飞禁飞区 | 航点位于 §8.1 多边形内 | `E_NOFLY` |
| A4 低电量 | reset + config battery=22，takeoff | `E_BATTERY_TAKEOFF` |
| A5 无确认执行 | goto_waypoints confirm=false | `E_CONFIRM_REQUIRED` |
| A6 飞行中低电量 | 飞行中 config battery=19 | 强制 RTH（审计 force_rth），最终 landed/idle |
| A7 GPS 差 | config gps_fix=1,sats=6，takeoff | `E_GPS` |
| A8 RC 断开 | config rc_connected=false，takeoff | `E_RC_LINK` |
| A9 非法参数/未知工具 | takeoff altitude_m=-5；tool="fly_to_moon" | `E_PARAM_RANGE` / `E_UNKNOWN_TOOL` |
| A10 real 模式 | set_mode(real, confirm=true) | `E_REAL_NOT_AVAILABLE`（Phase1） |

**要求**：A1-A5 至少 5 条必须同时有（a）Agent 侧自动化测试断言（`llm_drone/tests/safety/`），（b）Orchestrator 演示中真实 LLM 触发后的拒绝记录（允许 A6-A10 用脚本化直调，需在 transcript 标注）。

## 12. 演示运行目录与指标

```
llm_drone/demo/runs/<run_id>/          # run_id = YYYYMMDD_HHMMSS_<scenario_id>
├── request.md            # 用户提示 + 仿真配置 + 模型参数
├── transcript.md         # 可读对话：user → assistant(thinking/content) → tool_call → tool_result …
├── llm_events.jsonl      # §9.2
├── tool_calls.jsonl      # 每次工具调用（name/args/ok/error_code/latency_ms）
├── agent_audit.jsonl     # 从 Agent 审计文件拷贝
├── mission.json          # 实际执行的 Mission JSON
├── mission_record.json   # §7.1
├── photos_metadata.json  # §7.3 格式（仿真记录版）
├── metrics.json          # 见下
└── summary.md            # 结论（通过/失败 + 证据行号）
```

`metrics.json`：`run_id, scenario_id, kind(positive|adversarial), model, llm_calls, tool_calls, rejected, error_codes[], wall_s, mission_sim_s, n_photos, tokens{prompt,completion}, passed(bool), expected, actual`。

## 13. 验收标准映射（CONTRACT.md §6）

| # | CONTRACT 验收标准 | 证据 |
|---|---|---|
| 1 | 自然语言→LLM 多轮工具调用→规划→安全校验→仿真执行→遥测/照片回传，全程可复现 | `llm_drone/demo/runs/P1..P3/`（transcript+metrics+mission+photos）；`run_demo` 一条命令复现 |
| 2 | ≥3 正向 + ≥5 对抗全部正确处理 | P1-P3 run 目录；A1-A10 的 Agent 测试（`tests/safety/`）与 Orchestrator 演示记录 |
| 3 | 一次完整任务审计 JSONL + transcript + 指标 | `agent_audit.jsonl` / `llm_events.jsonl` / `metrics.json` |
| 4 | UE5 虚拟相机按 mission 渲染 ≥12 图 + metadata（可接 3DGS） | `data/synthetic/mission/images/*.png` + `metadata.json`；`llm_drone/ue5_mission/results/` 校验输出 |
| 5 | MSDK v5 桥接口映射与真机测试协议（代码骨架可审阅） | `llm_drone/msdk_bridge/README.md`、`mapping.json`、`app/`、`test_protocol.md` |

## 14. 约定与变更控制

- 实现方若发现规格矛盾/缺口：先按最合理方式实现并在自己 README/SUMMARY 记录，然后 `send_message` 给 Lead；Lead 更新 spec 版本（v1.1…）并通知相关方。
- 跨 scope 写入一律禁止；共享产物路径见 CONTRACT.md §5 与任务板 write_scopes。
- 所有"声称的数字/结果"必须有落盘证据（日志/JSON/截图），不接受口述。
## 15. v1.1 补充决议（2026-11-08，Lead）

> 本节只补充 Phase-2 真机桥的字段语义，不改变已通过验收的 Phase-1 行为（v1.0 仍有效）。

1. **real 模式下 sim_time_s**：允许为 `null`（显式表示"无仿真时间"）；任务时长以墙钟 `started_at/ended_at` 差值写入 `stats.duration_s`；Orchestrator 必须容忍 `sim_time_s=null`（不得因此报错）。
2. **photos[].c2w 的真相来源**：
   - sim 后端：真值，`pose_source="truth"`；
   - real 后端：允许为**估算值**（由遥测位置 + gimbal/heading 推算），必须带 `pose_source="estimated"` 与 `pose_accuracy_m`（无 RTK 建议 3.0 m，可在 1–10 m 配置）；
   - 遥测缺失时允许 `c2w=null`，但必须 `pose_source="unavailable"`；
   - 3DGS 训练前应以 COLMAP 精化位姿覆盖"估算/不可用"值（与上游 `pipeline/` 的既有流程一致）。
3. **设备就绪错误码映射（Phase-2 桥）**：
   - SDK/App 未注册，或飞机未连接 → `E_RC_LINK`，`details.reason ∈ {not_registered, not_connected}`；
   - 机型不符/不在支持列表 → `E_STATE`，`details.reason="aircraft_mismatch"`；
   - 不新增顶层错误码，细节放 `details`。
4. 变更记录：v1.1 仅本节新增；实现方可按本节补齐字段语义，其余一律以 v1.0 为准。
