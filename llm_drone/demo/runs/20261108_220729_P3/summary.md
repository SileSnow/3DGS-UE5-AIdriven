# P3 运行小结

- run_id: `20261108_220729_P3`
- kind: `positive`
- mode: `real_llm`（model: `qwen3.5:4b`）
- **结论: PASS ✅**

## 期望 vs 实际

| 项 | 期望 | 实际 | 判定 |
|---|---|---|---|
| tool:plan_capture_mission | - | actual_sequence=['plan_capture_mission', 'takeoff', 'goto_waypoints', 'land'] | PASS |
| tool:takeoff | - | actual_sequence=['plan_capture_mission', 'takeoff', 'goto_waypoints', 'land'] | PASS |
| tool:goto_waypoints | - | actual_sequence=['plan_capture_mission', 'takeoff', 'goto_waypoints', 'land'] | PASS |
| tool:land | - | actual_sequence=['plan_capture_mission', 'takeoff', 'goto_waypoints', 'land'] | PASS |
| photos==5 | - | actual=5 | PASS |
| mission_state:completed | - | actual=completed | PASS |
| no_rejection | - | rejected=0 | PASS |
| final_state:['idle'] | - | actual=idle | PASS |

## 指标

- LLM 调用: 5；工具调用: 4；拒绝: 0
- 错误码: `[]`
- 照片数: 5；mission_sim_s: 48.0；wall_s: 32.24
- tokens: {'prompt': 23262, 'completion': 292}

## 最终回答（节选）

```text
任务已完成：
- 在 (39.9045, 116.4070) 处以 30 米高度定点拍摄，共 5 张照片，间隔 3 秒。
- 无人机已原地降落，电量 83.78%。
```

## 证据文件

- [request.md](request.md) — 831 bytes
- [transcript.md](transcript.md) — 4560 bytes
- [llm_events.jsonl](llm_events.jsonl) — 8924 bytes
- [tool_calls.jsonl](tool_calls.jsonl) — 1055 bytes
- [agent_audit.jsonl](agent_audit.jsonl) — 18531 bytes
- [mission.json](mission.json) — 2424 bytes
- [mission_record.json](mission_record.json) — 3501 bytes
- [photos_metadata.json](photos_metadata.json) — 3605 bytes
- [metrics.json](metrics.json) — 2901 bytes

## Agent 审计关键行（拒绝/强制返航）

- agent_audit.jsonl:19 — `{"ts": "2026-11-08T22:07:38.330+08:00", "seq": 19, "run_id": "20261108_220729_P3", "event": "safety_check", "tool": "takeoff", "command_id": "c-0001", "decision": "allow", "reasons": [], "error_code": null}`
- agent_audit.jsonl:36 — `{"ts": "2026-11-08T22:07:44.611+08:00", "seq": 36, "run_id": "20261108_220729_P3", "event": "safety_check", "tool": "goto_waypoints", "command_id": "c-0002", "decision": "allow", "reasons": [], "error_code": null}`
- agent_audit.jsonl:66 — `{"ts": "2026-11-08T22:07:55.636+08:00", "seq": 66, "run_id": "20261108_220729_P3", "event": "safety_check", "tool": "land", "command_id": "c-0003", "decision": "allow", "reasons": [], "error_code": null}`
