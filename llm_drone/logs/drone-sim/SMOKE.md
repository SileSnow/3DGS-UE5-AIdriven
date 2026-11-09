# SMOKE —— 真实 server 黑盒冒烟（规格：llm_drone/spec/PROTOCOL.md v1.0）

**结论：PASS**（2026-11-08 22:02:57，真实 `python -m sim.server` 子进程 + 独立 urllib 客户端）。

## 1. 复现命令

```powershell
cd C:\Users\<user>\Desktop\GAIA项目\dji_ue5_3dgs\llm_drone
python logs\drone-sim\smoke_run.py          # 真实启动 server（随机空闲端口，time-scale 20），退出码 0 = PASS
```

内部实际启动命令（脚本打印）：

```
python -m sim.server --port 60035 --time-scale 20 --audit-dir <repo>\dji_ue5_3dgs\llm_drone\logs\drone-sim
```

- 完整输出日志：`llm_drone/logs/drone-sim/smoke_20261108_220257.log`
- 本次真实审计文件：`llm_drone/logs/drone-sim/audit_smoke_20261108_220257.jsonl`（58 行）

## 2. 链路步骤与结果（全部 ok=true）

| 步骤 | 结果 |
|---|---|
| GET /v1/health | `ok=true, backend=sim, version=1.0.0, mode=sim, time_scale=20.0` |
| POST /v1/reset {run_id} | `state=idle, run_id=smoke_20261108_220257` |
| GET /v1/telemetry | `state=idle, battery_pct=100.0` |
| preflight_check | `can_fly=true` |
| takeoff {altitude_m:40} confirm=true | `ok, state=taking_off` → 轮询到 `hovering, alt_rel_m=40.0, battery=97.9` |
| goto_waypoints {mission: spec/sample_mission.json 16 点, photo_interval_s:1} confirm=true | `ok, mission_id=sample-grid-16, state=mission` |
| GET /v1/missions/sample-grid-16 | `state=completed, progress_pct=100.0, n_photos=16, stats={distance_m:319.239, duration_s:164.0, n_photos:16}` |
| 照片 c2w 正交性 | 16/16 `|R R^T - I| < 1e-6` 且 det(R)=+1（脚本纯 math 校验，不 import 实现代码） |
| return_to_home | `ok, state=returning` → 轮询到 `idle, lat=39.9042, lon=116.4074, alt_rel_m=0.0` |
| land（地面） | 预期拒绝 `E_STATE`（"land 需要空中状态"） |

## 3. 照片记录（mission record §7.1 摘录，第 0 张）

```json
{"index": 0, "file": "SIM_0001.jpg", "ts": "2026-11-08T22:02:59.627+08:00",
 "lat": 39.9039485, "lon": 116.4070721, "alt_rel_m": 40.0, "alt_abs_m": 83.0,
 "heading_deg": 0.0, "gimbal": {"pitch": -45.0, "yaw": 0.0, "roll": 0.0},
 "c2w": [0.0, 1.0, 0.0, -2800.001846,
         -0.707107, 0.0, -0.707107, 2799.998564,
         -0.707107, 0.0, 0.707107, 4000.0,
         0.0, 0.0, 0.0, 1.0]}
```

c2w 平移 = UE 世界 cm（+X=东、+Y=南、+Z=上）：第 0 点位于 home 西 ~28 m、北 ~28 m、高 40 m，
即 (-2800, +2800, 4000) cm，与 §2/§7.2 公式一致。

## 4. 审计 JSONL 校验（§9.1）

- 文件：`llm_drone/logs/drone-sim/audit_smoke_20261108_220257.jsonl`，**58 行，逐行 `json.loads` 通过**
- `seq` 从 1 严格递增到 58；每行含 `ts/seq/run_id/event`
- `/v1/audit?since_seq=0` 返回 `last_seq=58`，与文件一致
- 事件类型：`sim_reset, command_received, safety_check, command_accepted, command_rejected, takeoff_started, takeoff_completed, mission_started, photo_captured×16, mission_completed, rth_started, landed, telemetry_keyframe`

真实审计行摘录：

```json
{"ts": "2026-11-08T22:02:58.293+08:00", "seq": 1, "run_id": "smoke_20261108_220257", "event": "sim_reset", "state": "idle"}
{"ts": "2026-11-08T22:02:58.297+08:00", "seq": 2, "run_id": "smoke_20261108_220257", "event": "command_received", "tool": "preflight_check", "command_id": "c-0001", "args": {}, "confirm": null, "decision": "pending"}
{"ts": "2026-11-08T22:02:59.628+08:00", "seq": 17, "run_id": "smoke_20261108_220257", "event": "photo_captured", "mission_id": "sample-grid-16", "index": 0, "file": "SIM_0001.jpg", "lat": 39.9039485, "lon": 116.4070721, "alt_rel_m": 40.0, "heading_deg": 0.0, "source": "mission"}
{"ts": "2026-11-08T22:03:07.898+08:00", "seq": 48, "run_id": "smoke_20261108_220257", "event": "mission_completed", "mission_id": "sample-grid-16", "n_photos": 16, "distance_m": 319.24, "duration_s": 164.0}
{"ts": "2026-11-08T22:03:08.881+08:00", "seq": 55, "run_id": "smoke_20261108_220257", "event": "landed", "lat": 39.9042, "lon": 116.4074, "battery_pct": 90.92}
{"ts": "2026-11-08T22:03:08.885+08:00", "seq": 58, "run_id": "smoke_20261108_220257", "event": "command_rejected", "tool": "land", "command_id": "c-0005", "error_code": "E_STATE", "reasons": ["land 需要空中状态，当前 state='idle'"], "decision": "reject"}
```

## 5. 与 Lead 独立黑盒验收的关系

Lead 于 2026-11-08 21:55 用独立脚本（不 import 实现，只走 HTTP）对 `--port 8766 --time-scale 20` 复跑 spec §3/§4/§8：
**27/27 PASS**，证据 `llm_drone/logs/lead/acceptance_20261108_215559.{json,md}`。
本 SMOKE.md 是 drone-sim 自己独立复跑的补充证据（端口 60035，含 mission record / c2w / 审计逐行校验）。
