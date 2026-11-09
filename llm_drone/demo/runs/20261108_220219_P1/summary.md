# P1 运行小结

- run_id: `20261108_220219_P1`
- kind: `positive`
- mode: `real_llm`（model: `qwen3.5:4b`）
- **结论: FAIL ❌**

## 期望 vs 实际

| 项 | 期望 | 实际 | 判定 |
|---|---|---|---|
| tool:plan_capture_mission | - | actual_sequence=['plan_capture_mission', 'get_telemetry', 'takeoff', 'get_telemetry', 'takeoff'] | PASS |
| tool:takeoff | - | actual_sequence=['plan_capture_mission', 'get_telemetry', 'takeoff', 'get_telemetry', 'takeoff'] | PASS |
| tool:goto_waypoints | - | actual_sequence=['plan_capture_mission', 'get_telemetry', 'takeoff', 'get_telemetry', 'takeoff'] | FAIL |
| tool:return_to_home | - | actual_sequence=['plan_capture_mission', 'get_telemetry', 'takeoff', 'get_telemetry', 'takeoff'] | FAIL |
| photos>=12 | - | actual=0 | FAIL |
| mission_state:completed | - | actual=None | FAIL |
| no_rejection | - | rejected=1 | FAIL |

## 指标

- LLM 调用: 9；工具调用: 5；拒绝: 1
- 错误码: `['E_STATE']`
- 照片数: 0；mission_sim_s: None；wall_s: 13.04
- tokens: {'prompt': 35843, 'completion': 341}

## 最终回答（节选）

```text
无人机当前处于悬停状态（hovering），无法直接起飞。需要先让无人机返回起飞点并自动降落，使其回到 idle 状态
```

## 证据文件

- [request.md](request.md) — 858 bytes
- [transcript.md](transcript.md) — 6771 bytes
- [llm_events.jsonl](llm_events.jsonl) — 12970 bytes
- [tool_calls.jsonl](tool_calls.jsonl) — 1257 bytes
- [agent_audit.jsonl](agent_audit.jsonl) — 7003 bytes
- [mission.json](mission.json) — 6432 bytes
- [mission_record.json](mission_record.json) — 2 bytes
- [photos_metadata.json](photos_metadata.json) — 377 bytes
- [metrics.json](metrics.json) — 2910 bytes

## Agent 审计关键行（拒绝/强制返航）

- agent_audit.jsonl:16 — `{"ts": "2026-11-08T22:02:26.346+08:00", "seq": 16, "run_id": "20261108_220219_P1", "event": "safety_check", "tool": "takeoff", "command_id": "c-0001", "decision": "allow", "reasons": [], "error_code": null}`
- agent_audit.jsonl:31 — `{"ts": "2026-11-08T22:02:31.545+08:00", "seq": 31, "run_id": "20261108_220219_P1", "event": "safety_check", "tool": "takeoff", "command_id": "c-0002", "decision": "reject", "reasons": ["takeoff 需要 state=idle，当前 state='ho`
- agent_audit.jsonl:32 — `{"ts": "2026-11-08T22:02:31.545+08:00", "seq": 32, "run_id": "20261108_220219_P1", "event": "command_rejected", "tool": "takeoff", "command_id": "c-0002", "error_code": "E_STATE", "reasons": ["takeoff 需要 state=idle，当前 st`
