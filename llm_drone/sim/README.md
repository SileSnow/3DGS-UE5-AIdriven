# llm_drone/sim —— Phase-1 无人机仿真 Agent（标准库 HTTP 服务）

> 工程规格唯一事实源：`llm_drone/spec/PROTOCOL.md` v1.0（FROZEN）。
> 本目录实现 §3 HTTP API、§4 命令表、§5 遥测、§6 Mission 执行、§7 任务/照片记录、§9.1 审计、§10 仿真模型。
> 安全校验全部委托 `llm_drone/safety/`（SafetyValidator，权威安全层），本目录**不做安全判断**。

## 1. 启动

```powershell
cd C:\Users\<user>\Desktop\GAIA项目\dji_ue5_3dgs\llm_drone
python -m sim.server --port 8765 --time-scale 20
```

可配置参数（`python -m sim.server --help`）：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--host` | 127.0.0.1 | 监听地址 |
| `--port` | 8765 | 监听端口（0=临时端口，测试用） |
| `--time-scale` | 20 | 仿真倍率：每 100ms 墙钟推进 `dt=0.1*time_scale` 仿真秒 |
| `--tick-wall-s` | 0.1 | 主循环墙钟 tick（仅测试调小） |
| `--home-lat/--home-lon/--home-alt` | 39.9042 / 116.4074 / 43.0 | 起飞点（home / 局部坐标原点） |
| `--audit-dir` | `llm_drone/logs/drone-sim` | 审计目录（`audit_<run_id>.jsonl`） |
| `--run-id` | default | 初始审计文件 run_id（`/v1/reset` 可切换） |
| `--safety-config` | `safety/config.json` | 安全配置覆盖路径 |
| `--echo-audit` | off | 审计同时打印到 stderr |

兼容入口：`python llm_drone/sim/drone_agent.py`（= `python -m sim.server`）与
`sim.drone_agent.create_server(...)`（旧测试辅助使用）。

## 2. HTTP 端点（PROTOCOL.md §3.2）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/v1/health` | `{ok, backend:"sim", version, mode, time_scale, state, ts, uptime_s, counters}` |
| GET | `/v1/telemetry` | §5 遥测快照（**直接返回对象，含 home**，无 ok 包裹） |
| POST | `/v1/command` | `{command_id, tool, args, confirm?, run_id?}`；command_id 幂等（缓存最近 100 条） |
| GET | `/v1/missions/{mission_id}` | §7.1 任务记录（photos 含 c2w），不存在 → `E_MISSION_NOT_FOUND` |
| GET | `/v1/missions?limit=N` | 最近任务列表（新→旧） |
| GET | `/v1/audit?since_seq=N` | `{ok, events:[...], last_seq}` |
| POST | `/v1/reset` | `{run_id?}`：重置状态/电量/位置/任务/幂等缓存，并切换审计文件 |
| POST | `/v1/sim/config` | 故障注入 `{battery_pct?, gps_fix?, gps_satellites?, rc_connected?, time_scale?}` |

业务失败（含安全拒绝）一律 **HTTP 200** + `{"ok":false,"error":{"code","message","details"?}}`；
HTTP 4xx/5xx 仅用于协议/服务器错误（非法 JSON → 400，未知端点 → 404）。

### 2.1 curl / PowerShell 示例

```bash
curl http://127.0.0.1:8765/v1/health
curl http://127.0.0.1:8765/v1/telemetry

curl -X POST http://127.0.0.1:8765/v1/command \
  -H "Content-Type: application/json" \
  -d '{"command_id":"c-0001","tool":"takeoff","args":{"altitude_m":40},"confirm":true}'

curl -X POST http://127.0.0.1:8765/v1/command \
  -H "Content-Type: application/json" \
  -d '{"command_id":"c-0002","tool":"goto_waypoints","args":{"mission":<§6 Mission JSON>,"photo_interval_s":1},"confirm":true}'

curl http://127.0.0.1:8765/v1/missions/sample-grid-16
curl -X POST http://127.0.0.1:8765/v1/reset -H "Content-Type: application/json" -d '{"run_id":"demo_001"}'
```

```powershell
# PowerShell 5.1/7
Invoke-RestMethod http://127.0.0.1:8765/v1/telemetry

$body = @{ command_id="c-0001"; tool="takeoff"; args=@{ altitude_m=40 }; confirm=$true } | ConvertTo-Json -Depth 6
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/v1/command -ContentType "application/json; charset=utf-8" -Body $body

$mission = Get-Content llm_drone\spec\sample_mission.json -Raw | ConvertFrom-Json
$body = @{ command_id="c-0002"; tool="goto_waypoints"; args=@{ mission=$mission; photo_interval_s=1 }; confirm=$true } | ConvertTo-Json -Depth 12
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/v1/command -ContentType "application/json; charset=utf-8" -Body $body
```

## 3. 命令表（Agent 级，PROTOCOL.md §4）

| tool | args | 需 confirm | 说明 |
|---|---|---|---|
| get_telemetry | `{}` | 否 | 返回 telemetry |
| preflight_check | `{}` | 否 | 返回 `{ok, can_fly, checks:[{name,pass,detail}]}` |
| takeoff | `{altitude_m}` | **是** | 0<alt<=120；电量>=30%；GPS fix>=3/sats>=10；RC 连接；state=idle |
| goto_waypoints | `{mission:<§6 Mission JSON>, photo_interval_s?}` | **是** | 状态需 hovering；逐航点校验；完成后悬停、mission=completed |
| set_gimbal | `{pitch_deg, yaw_deg?}` | 否 | -90<=pitch<=0；yaw -180..180；需空中 |
| capture_photo | `{count?, interval_s?}` | 否 | 1<=count<=20；0<=interval<=10；需空中 |
| start_video / stop_video | `{}` | 否 | 需空中 |
| return_to_home | `{}` | 否 | 空中有效；任务中调用会中止任务 |
| land | `{}` | 否 | 空中有效 |
| abort | `{reason}` | 否 | 任意状态；飞行中→悬停，任务标记 aborted |
| get_mission_status | `{mission_id?}` | 否 | 省略查最近任务 |
| set_mode | `{mode}` | real 需 **是** | dry_run/sim/real；Phase1 real→`E_REAL_NOT_AVAILABLE`；切换需 state=idle |

**校验顺序（§4，SafetyValidator 固定）**：
schema → whitelist → mode → confirm → state → battery → gps → rc → altitude/speed 范围 → geofence → no-fly zone → 返航能量估算 → 允许。
拒绝优于截断（不做静默参数截断）。

实现细节（与规格兼容的解释，已与 orchestrator/Lead 对齐）：

- `confirm` 走请求顶层；同时兼容旧式 `args.confirm`（顶层优先）。
- `goto_waypoints.args.mission` 严格按 §6 消费（`action`∈photo/video_start/video_stop/none；
  不认旧 CONTRACT 的 `take_photo`/嵌套 `gimbal`）。mission_id 缺省时 Agent 分配 `m-0001` 递增。
- 校验顺序严格 §4：**A2/A3 演示需先 takeoff 再 goto**（地面 goto 会得到 `E_STATE`）。
- 任务执行中（state=mission）仅允许 `abort/get_telemetry/get_mission_status/return_to_home`，其余 `E_BUSY`。
- mode=dry_run 时飞行类命令只做安全校验并返回 `warnings:["dry_run: ... 未实际执行"]`（读命令照常执行）。
- `capture_photo` count>1 且 interval>0 时：首张立即拍，其余由主循环按仿真间隔补齐（响应 warnings 说明）；
  interval=0 时全部立即拍摄。任务内拍照按航点 `action=photo` 每点 1 张，间隔受 `photo_interval_s` 约束。
- mission_id 冲突时自动加 `-r2/-r3` 后缀（同一 run 内唯一）。

## 4. 遥测（§5）

```json
{"ts":"2026-11-08T22:02:58.297+08:00","sim_time_s":0.4,"state":"hovering",
 "lat":39.9042,"lon":116.4074,"alt_rel_m":40.0,"alt_abs_m":83.0,
 "speed_mps":0.0,"vertical_speed_mps":0.0,"battery_pct":97.9,
 "gimbal":{"pitch":0.0,"yaw":0.0,"roll":0.0},
 "gps":{"fix":3,"satellites":24},"rc":{"connected":true,"signal":"good"},
 "mode":"sim","mission_id":null,
 "home":{"lat":39.9042,"lon":116.4074,"alt_abs_m":43.0}}
```

- `state` ∈ idle|taking_off|hovering|mission|returning|landing|aborted|failsafe
- `mode` ∈ dry_run|sim|real（Phase1 只用 sim/dry_run）

## 5. 任务记录与照片（§7）

`GET /v1/missions/{id}` 返回 §7.1：

```json
{"ok":true,"mission_id":"sample-grid-16","plan_id":"plan-sample-001","state":"completed",
 "created_at":"...","started_at":"...","ended_at":"...","progress_pct":100.0,
 "photos":[{"index":0,"file":"SIM_0001.jpg","ts":"...","lat":39.9039485,"lon":116.4070721,
            "alt_rel_m":40.0,"alt_abs_m":83.0,"heading_deg":0.0,
            "gimbal":{"pitch":-45.0,"yaw":0.0,"roll":0.0},"c2w":[16 floats]}],
 "error":null,"stats":{"distance_m":319.239,"duration_s":164.0,"n_photos":16}}
```

- `photos[].c2w` 按 §7.2：`yaw_ue=heading_deg-90`、`pitch=gimbal_pitch_deg`、roll=0，
  行主序 4x4，列为 forward/right/up，平移为 UE 世界 cm（`+X=东、+Y=南、+Z=上`）。
  实测 16/16 张满足 `|R R^T - I| < 1e-6` 且 det(R)=+1。
- `sim.export.mission_record_to_metadata(record, mission_def)` 可把记录转成 §7.3 metadata.json
  （`synthetic_dji_mini4pro_mission_v1`，供 orchestrator 生成 photos_metadata.json / 对照 UE5 真值）。

## 6. 审计（§9.1）

- 路径：`llm_drone/logs/drone-sim/audit_<run_id>.jsonl`（可用 `--audit-dir` / 环境变量 `LLM_DRONE_AUDIT_DIR` 覆盖）
- 每行一个 JSON：必含 `ts, seq, run_id, event`；命令类含 `tool, command_id, decision`；
  拒绝含 `error_code, reasons`；任务/照片事件含 `mission_id` 等。
- seq 在同一审计文件内从 1 严格递增。
- 主要事件：`server_start, sim_reset, command_received, safety_check, command_accepted,
  command_rejected, command_replayed, command_error, takeoff_started, takeoff_completed,
  mission_started, photo_captured, mission_completed, mission_aborted, rth_started, force_rth,
  landed, gimbal_set, video_started, video_stopped, mode_changed, sim_config, telemetry_keyframe, server_stop`。
- 飞行中低电量强制返航写入 `force_rth` 且 `decision="force_rth"`（同时任务标 aborted / error.code=FORCE_RTH）。

## 7. 仿真模型（§10）

- 主循环：墙钟每 `tick_wall_s`（默认 0.1s）推进 `time_scale * tick_wall_s` 仿真秒。
- 运动：水平速度 = 航点 `speed_mps`（<=15）；爬升/下降 3 m/s；到点悬停 0.5s → 转向 heading → 执行 action。
- 电量：idle 0.01%/s、爬升/下降 0.15%/s、任务巡航 0.05%/s、悬停 0.04%/s；
  空中电量 <20% → 强制 RTH（10 m/s 直线返航，到 home 上方后降落，最终 idle）。
- 默认初始：battery 100%、GPS fix=3/sats=24、RC connected、位置=home、state=idle、mode=sim；
  `/v1/reset` 恢复默认并清空任务/幂等缓存。
- `/v1/sim/config` 仅改指定字段（对抗测试注入 battery/gps/rc/time_scale）。

## 8. 目录结构

```
sim/
├── __init__.py      # 导出 SimConfig / DroneSimulator / MissionRuntime / SimulatorError
├── config.py        # SimConfig + CLI 解析（§10 默认值）
├── simulator.py     # 状态机/运动学/电量/任务执行器/§7.1 记录/§7.2 c2w
├── server.py        # ThreadingHTTPServer + tick 线程 + AgentApp（幂等/审计/端点）
├── drone_agent.py   # 兼容入口（create_server / main）
└── export.py        # §7.1 -> §7.3 metadata 导出
```

## 9. 测试与复现

```powershell
cd C:\Users\<user>\Desktop\GAIA项目\dji_ue5_3dgs\llm_drone
python -m unittest discover -s tests/sim -t tests -v     # 21 tests（协议/任务/审计）
python -m unittest discover -s tests/safety -t tests -v  # 45 tests（A1-A10/几何/c2w）
python -m unittest discover -s tests -v                  # 全仓（含其他 agent 测试）
python logs\drone-sim\smoke_run.py                       # 真实 server 黑盒冒烟
```

测试一律使用临时审计目录 + 随机端口（port=0），不污染 `logs/drone-sim/audit_*.jsonl`。

## 10. 边界（诚实标注）

- Phase1 只有仿真，无真机；`set_mode(real)` → `E_REAL_NOT_AVAILABLE`。
- 照片只有记录（`SIM_%04d.jpg` 占位）没有真实图像；真实 PNG 由 `llm_drone/ue5_mission/` 渲染。
- `/v1/reset`、`/v1/sim/config` 为仿真专属（Phase2 真机桥按 §3.2 返回 `E_NOT_SUPPORTED`）。
- `mission.error.code` 使用非协议错误码 `ABORTED` / `RETURN_TO_HOME` / `FORCE_RTH`
  （协议错误码表 §8.2 仅用于命令响应 error）。
