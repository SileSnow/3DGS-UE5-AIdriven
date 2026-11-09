# LLM Tool-Call 调度无人机 —— 接口契约（v0.1，2026-11-08）

## 0. 架构（三段式，LLM 永远不直接碰 DJI SDK）

```
用户自然语言
   │
   ▼
① LLM Orchestrator (Python)      —— 工具调用循环/规划/多轮澄清；本机 Ollama qwen3.5:4b（可替换任意 OpenAI 兼容 API）
   │  HTTP/WS JSON（本契约）
   ▼
② Drone Agent（可替换后端）       —— 安全/策略层 + 指令执行 + 遥测回传
   ├─ Phase 1: 仿真后端 drone_sim（本机，无真机）
   └─ Phase 2: Android MSDK v5 App（真机，DJI RC-N2 + Android 手机）
   │  DJI Mobile SDK v5
   ▼
③ DJI Mini 4 Pro 无人机
```

**安全原则**：LLM 只生成“意图 + 参数”；所有飞行指令必须经过确定性 SafetyValidator（地理围栏/限高/限速/电量/禁飞区/二次确认/审计）后才下发。

## 1. 工具（Tool / Function Calling）定义

Orchestrator 暴露给 LLM 的工具集（OpenAI function schema 风格），参数必须通过 JSON Schema 校验：

| 工具名 | 作用 | 关键参数 | 风险级 |
|---|---|---|---|
| `get_telemetry` | 读遥测 | — | 只读 |
| `preflight_check` | 起飞前检查（GPS/电量/禁飞区/固件） | — | 只读 |
| `plan_capture_mission` | 规划航拍任务（网格/五向/环绕），返回 waypoints 与拍照点 | `pattern, area(center,radius/polygon), altitude_m, overlap, gimbal_pitch` | 只读（不飞行） |
| `takeoff` | 起飞到指定相对高度 | `altitude_m, confirm` | 飞行 |
| `goto_waypoints` | 执行航点任务 | `waypoints[], speed_mps, take_photos, photo_interval_s` | 飞行 |
| `orbit` | 环绕目标拍摄 | `target{lat,lon}, radius_m, altitude_m, shots, gimbal_pitch` | 飞行 |
| `set_gimbal` | 云台角度 | `pitch_deg, yaw_deg` | 低风险 |
| `capture_photo` | 拍照 | `count, interval_s` | 低风险 |
| `start_video` / `stop_video` | 录像 | — | 低风险 |
| `return_to_home` | 一键返航 | — | 飞行（安全动作） |
| `land` | 降落 | — | 飞行 |
| `abort` | 中止任务（悬停/返航） | `reason` | 高优先 |
| `get_mission_status` | 任务/照片/电量进度 | `mission_id` | 只读 |
| `set_mode` | 切换 `dry_run|sim|real`（real 需人工确认） | `mode, confirm` | 高 |

**强制二次确认**：`takeoff/goto_waypoints/orbit/set_mode(real)` 必须带 `confirm=true`，且 `plan_capture_mission` 与执行必须两步（先出计划 → 人工/LLM 确认 → 执行）。

## 2. Drone Agent 本地接口（Phase1 仿真 / Phase2 MSDK App 同一契约）

HTTP（localhost）或 WebSocket，JSON；所有响应含 `ok/error/telemetry_snapshot`。

```jsonc
// POST /v1/command
{"command_id":"c-001","tool":"goto_waypoints","args":{"waypoints":[{"lat":39.9042,"lon":116.4074,"alt_rel_m":40,"speed_mps":6}],"take_photos":true}, "confirm": true}
// -> {"ok":true,"command_id":"c-001","mission_id":"m-001","state":"executing"}

// GET /v1/telemetry
{"ts":"2026-11-08T17:20:00+08:00","lat":39.9042,"lon":116.4074,"alt_rel_m":40.0,"alt_abs_m":83.0,
 "speed_mps":6.0,"battery_pct":87,"gimbal":{"pitch":-45,"yaw":90,"roll":0},
 "mode":"waypoint","gps":{"fix":3,"satellites":24},"rc":{"connected":true,"signal":"good"}}

// GET /v1/missions/{mission_id}
{"mission_id":"m-001","state":"completed","photos":[{"file":"IMG_0001.jpg","ts":"...","lat":...,"lon":...,"alt_rel_m":40,"gimbal":{"pitch":-45,"yaw":90}}],"progress_pct":100}
```

## 3. 安全/策略规则（SafetyValidator 必须实现）

| 规则 | 默认阈值 | 违规行为 |
|---|---|---|
| 最大相对高度 | 120 m（可配） | 拒绝/截断 |
| 最大水平速度 | 15 m/s（可配） | 拒绝 |
| 地理围栏 | 圆形（中心+半径）或多边形 | 拒绝/强制 RTH |
| 禁飞区 | 多边形+高度表（机场/军事/城市敏感区） | 拒绝 |
| 最低电量 | 起飞 ≥30%，返航阈值 20% | 拒绝起飞/自动 RTH |
| GPS 质量 | fix ≥3、卫星 ≥10 | 拒绝起飞 |
| 遥控链路 | 必须连接 | 拒绝 |
| 指令白名单 | 仅工具表内命令 | 拒绝并审计 |
| 参数范围 | 逐工具 JSON Schema + 物理范围 | 拒绝 |
| 二次确认 | 飞行/real 模式命令 | 拒绝无 confirm |
| 审计 | 所有命令/拒绝/遥测关键帧写 JSONL | 不可关闭 |

## 4. 与 3DGS/UE5 流水线的衔接（闭环）

任务执行后照片元数据必须能直接落成既有格式（`shared/CONVENTIONS.md` metadata.json）：
- 每张照片记录：`file, timestamp, gps{lat,lon,alt}, gimbal_deg{yaw,pitch,roll}, 预测内参`
- 仿真后端额外提供**真值相机位姿 c2w**（UE 坐标）用于对照
- Phase1 的 UE5 虚拟相机执行同一 mission JSON，渲染 PNG → 直接喂 `pipeline/03_train_3dgs.py`

## 5. 目录与写入范围

| 目录 | 负责人 | 内容 |
|---|---|---|
| `llm_drone/orchestrator/` | llm-orchestrator | LLM 工具循环、规划工具、审计、demo 场景 |
| `llm_drone/sim/` | drone-sim | 仿真后端、遥测、任务执行器 |
| `llm_drone/safety/` | drone-sim | SafetyValidator、禁飞区/围栏数据、对抗测试 |
| `llm_drone/msdk_bridge/` | msdk-bridge | Android MSDK v5 桥设计+代码骨架+真机协议 |
| `llm_drone/ue5_mission/` | ue5-mission | UE5 虚拟相机执行 mission JSON → PNG + metadata |
| `llm_drone/docs/`、`llm_drone/README.md` | lead | 方案、集成、报告 |
| `data/synthetic/mission/` | ue5-mission | 任务渲染输出（images + metadata） |

## 6. Phase-1 验收标准（本次验证目标）

1. 自然语言 → LLM 多轮工具调用 → 规划任务 → 安全校验 → 仿真执行 → 遥测/照片回传，全程可复现；
2. 至少 3 个正向场景（网格航拍/环绕拍摄/定点拍照）+ 5 个对抗场景（超限高、飞出围栏、飞禁飞区、低电量、无确认执行）全部被安全层正确处理；
3. 一次完整任务的审计日志（JSONL）+ 演示 transcript + 指标（命令数/拒绝数/任务耗时/照片数）；
4. UE5 虚拟相机能按 mission 渲染 ≥12 张图并生成 metadata（可接 3DGS 训练）；
5. MSDK v5 桥的接口映射与真机测试协议文档（代码骨架可审阅）。
