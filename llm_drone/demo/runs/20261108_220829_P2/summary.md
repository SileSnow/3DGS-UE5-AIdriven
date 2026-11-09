# P2 运行小结

- run_id: `20261108_220829_P2`
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
| photos==12 | - | actual=12 | PASS |
| mission_state:completed | - | actual=completed | PASS |
| final_state:['idle'] | - | actual=idle | PASS |

## 指标

- LLM 调用: 5；工具调用: 4；拒绝: 0
- 错误码: `[]`
- 照片数: 12；mission_sim_s: 126.0；wall_s: 36.95
- tokens: {'prompt': 23882, 'completion': 398}

## 最终回答（节选）

```text
任务已完成：环绕拍摄（m-0001）成功执行，共拍摄 12 张照片；无人机已自动返航并降落。当前电量 81.9%，状态 idle。
```

## 证据文件

- [request.md](request.md) — 847 bytes
- [transcript.md](transcript.md) — 5053 bytes
- [llm_events.jsonl](llm_events.jsonl) — 9428 bytes
- [tool_calls.jsonl](tool_calls.jsonl) — 1065 bytes
- [agent_audit.jsonl](agent_audit.jsonl) — 23606 bytes
- [mission.json](mission.json) — 4324 bytes
- [mission_record.json](mission_record.json) — 7952 bytes
- [photos_metadata.json](photos_metadata.json) — 8218 bytes
- [metrics.json](metrics.json) — 2989 bytes

## Agent 审计关键行（拒绝/强制返航）

- agent_audit.jsonl:24 — `{"ts": "2026-11-08T22:08:41.132+08:00", "seq": 24, "run_id": "20261108_220829_P2", "event": "safety_check", "tool": "takeoff", "command_id": "c-0001", "decision": "allow", "reasons": [], "error_code": null}`
- agent_audit.jsonl:42 — `{"ts": "2026-11-08T22:08:48.145+08:00", "seq": 42, "run_id": "20261108_220829_P2", "event": "safety_check", "tool": "goto_waypoints", "command_id": "c-0002", "decision": "allow", "reasons": [], "error_code": null}`
- agent_audit.jsonl:77 — `{"ts": "2026-11-08T22:08:58.101+08:00", "seq": 77, "run_id": "20261108_220829_P2", "event": "safety_check", "tool": "return_to_home", "command_id": "c-0003", "decision": "allow", "reasons": [], "error_code": null}`
