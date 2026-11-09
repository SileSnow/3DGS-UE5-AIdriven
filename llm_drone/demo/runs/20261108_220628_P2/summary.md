# P2 运行小结

- run_id: `20261108_220628_P2`
- kind: `positive`
- mode: `real_llm`（model: `qwen3.5:4b`）
- **结论: FAIL ❌**

## 期望 vs 实际

| 项 | 期望 | 实际 | 判定 |
|---|---|---|---|
| tool:plan_capture_mission | - | actual_sequence=['orbit', 'takeoff', 'orbit', 'return_to_home', 'plan_capture_mission', 'takeoff', 'goto_waypoints', 'return_to_home'] | PASS |
| tool:takeoff | - | actual_sequence=['orbit', 'takeoff', 'orbit', 'return_to_home', 'plan_capture_mission', 'takeoff', 'goto_waypoints', 'return_to_home'] | PASS |
| tool:goto_waypoints | - | actual_sequence=['orbit', 'takeoff', 'orbit', 'return_to_home', 'plan_capture_mission', 'takeoff', 'goto_waypoints', 'return_to_home'] | PASS |
| tool:return_to_home | - | actual_sequence=['orbit', 'takeoff', 'orbit', 'return_to_home', 'plan_capture_mission', 'takeoff', 'goto_waypoints', 'return_to_home'] | PASS |
| photos==12 | - | actual=12 | PASS |
| mission_state:completed | - | actual=completed | PASS |
| no_rejection | - | rejected=1 | FAIL |

## 指标

- LLM 调用: 10；工具调用: 8；拒绝: 1
- 错误码: `['E_STATE']`
- 照片数: 12；mission_sim_s: 126.0；wall_s: 61.12
- tokens: {'prompt': 54690, 'completion': 1092}

## 最终回答（节选）

```text
任务已完成：
- 环绕拍摄任务执行成功，共拍摄 12 张照片（SIM_0001.jpg 至 SIM_0008.jpg）
- 无人机已安全返航至起飞点
- 当前电量 65.18%，GPS 信号良好（24 颗卫星）
- 任务状态：idle（空闲）

所有操作已完成，无人机已返回起飞点并自动降落。
```

## 证据文件

- [request.md](request.md) — 847 bytes
- [transcript.md](transcript.md) — 10199 bytes
- [llm_events.jsonl](llm_events.jsonl) — 18523 bytes
- [tool_calls.jsonl](tool_calls.jsonl) — 2200 bytes
- [agent_audit.jsonl](agent_audit.jsonl) — 42511 bytes
- [mission.json](mission.json) — 4324 bytes
- [mission_record.json](mission_record.json) — 7952 bytes
- [photos_metadata.json](photos_metadata.json) — 8218 bytes
- [metrics.json](metrics.json) — 3309 bytes

## Agent 审计关键行（拒绝/强制返航）

- agent_audit.jsonl:24 — `{"ts": "2026-11-08T22:06:39.884+08:00", "seq": 24, "run_id": "20261108_220628_P2", "event": "safety_check", "tool": "takeoff", "command_id": "c-0001", "decision": "allow", "reasons": [], "error_code": null}`
- agent_audit.jsonl:42 — `{"ts": "2026-11-08T22:06:46.712+08:00", "seq": 42, "run_id": "20261108_220628_P2", "event": "safety_check", "tool": "goto_waypoints", "command_id": "c-0002", "decision": "allow", "reasons": [], "error_code": null}`
- agent_audit.jsonl:75 — `{"ts": "2026-11-08T22:06:55.635+08:00", "seq": 75, "run_id": "20261108_220628_P2", "event": "safety_check", "tool": "return_to_home", "command_id": "c-0003", "decision": "allow", "reasons": [], "error_code": null}`
- agent_audit.jsonl:100 — `{"ts": "2026-11-08T22:07:06.095+08:00", "seq": 100, "run_id": "20261108_220628_P2", "event": "safety_check", "tool": "takeoff", "command_id": "c-0004", "decision": "allow", "reasons": [], "error_code": null}`
- agent_audit.jsonl:110 — `{"ts": "2026-11-08T22:07:08.799+08:00", "seq": 110, "run_id": "20261108_220628_P2", "event": "safety_check", "tool": "goto_waypoints", "command_id": "c-0005", "decision": "allow", "reasons": [], "error_code": null}`
- agent_audit.jsonl:152 — `{"ts": "2026-11-08T22:07:22.733+08:00", "seq": 152, "run_id": "20261108_220628_P2", "event": "safety_check", "tool": "return_to_home", "command_id": "c-0006", "decision": "allow", "reasons": [], "error_code": null}`
