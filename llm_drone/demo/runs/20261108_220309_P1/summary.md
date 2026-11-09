# P1 运行小结

- run_id: `20261108_220309_P1`
- kind: `positive`
- mode: `real_llm`（model: `qwen3.5:4b`）
- **结论: PASS ✅**

## 期望 vs 实际

| 项 | 期望 | 实际 | 判定 |
|---|---|---|---|
| tool:plan_capture_mission | - | actual_sequence=['plan_capture_mission', 'takeoff', 'goto_waypoints', 'return_to_home'] | PASS |
| tool:takeoff | - | actual_sequence=['plan_capture_mission', 'takeoff', 'goto_waypoints', 'return_to_home'] | PASS |
| tool:goto_waypoints | - | actual_sequence=['plan_capture_mission', 'takeoff', 'goto_waypoints', 'return_to_home'] | PASS |
| tool:return_to_home | - | actual_sequence=['plan_capture_mission', 'takeoff', 'goto_waypoints', 'return_to_home'] | PASS |
| photos>=12 | - | actual=20 | PASS |
| mission_state:completed | - | actual=completed | PASS |
| no_rejection | - | rejected=0 | PASS |

## 指标

- LLM 调用: 7；工具调用: 4；拒绝: 0
- 错误码: `[]`
- 照片数: 20；mission_sim_s: 204.0；wall_s: 24.81
- tokens: {'prompt': 26117, 'completion': 299}

## 最终回答（节选）

```text
无人机已安全返航并降落，电量 85.5%，GPS 信号良好（24 颗
```

## 证据文件

- [request.md](request.md) — 858 bytes
- [transcript.md](transcript.md) — 5189 bytes
- [llm_events.jsonl](llm_events.jsonl) — 10648 bytes
- [tool_calls.jsonl](tool_calls.jsonl) — 1066 bytes
- [agent_audit.jsonl](agent_audit.jsonl) — 22757 bytes
- [mission.json](mission.json) — 6432 bytes
- [mission_record.json](mission_record.json) — 12977 bytes
- [photos_metadata.json](photos_metadata.json) — 13458 bytes
- [metrics.json](metrics.json) — 2754 bytes

## Agent 审计关键行（拒绝/强制返航）

- agent_audit.jsonl:16 — `{"ts": "2026-11-08T22:03:16.484+08:00", "seq": 16, "run_id": "20261108_220309_P1", "event": "safety_check", "tool": "takeoff", "command_id": "c-0001", "decision": "allow", "reasons": [], "error_code": null}`
- agent_audit.jsonl:28 — `{"ts": "2026-11-08T22:03:20.146+08:00", "seq": 28, "run_id": "20261108_220309_P1", "event": "safety_check", "tool": "goto_waypoints", "command_id": "c-0002", "decision": "allow", "reasons": [], "error_code": null}`
- agent_audit.jsonl:75 — `{"ts": "2026-11-08T22:03:32.512+08:00", "seq": 75, "run_id": "20261108_220309_P1", "event": "safety_check", "tool": "return_to_home", "command_id": "c-0003", "decision": "allow", "reasons": [], "error_code": null}`
