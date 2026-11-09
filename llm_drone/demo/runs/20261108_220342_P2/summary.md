# P2 运行小结

- run_id: `20261108_220342_P2`
- kind: `positive`
- mode: `real_llm`（model: `qwen3.5:4b`）
- **结论: FAIL ❌**

## 期望 vs 实际

| 项 | 期望 | 实际 | 判定 |
|---|---|---|---|
| tool:plan_capture_mission | - | actual_sequence=['orbit', 'tool', 'set_mode'] | FAIL |
| tool:takeoff | - | actual_sequence=['orbit', 'tool', 'set_mode'] | FAIL |
| tool:goto_waypoints | - | actual_sequence=['orbit', 'tool', 'set_mode'] | FAIL |
| tool:return_to_home | - | actual_sequence=['orbit', 'tool', 'set_mode'] | FAIL |
| photos==12 | - | actual=0 | FAIL |
| mission_state:completed | - | actual=None | FAIL |
| no_rejection | - | rejected=2 | FAIL |

## 指标

- LLM 调用: 4；工具调用: 3；拒绝: 2
- 错误码: `['E_STATE', 'E_UNKNOWN_TOOL']`
- 照片数: 0；mission_sim_s: None；wall_s: 7.43
- tokens: {'prompt': 13962, 'completion': 264}

## 最终回答（节选）

```text
无人机当前状态良好：电量充足（98.82%），GPS 信号稳定（3 个固定解，24 颗卫星），遥控
```

## 证据文件

- [request.md](request.md) — 847 bytes
- [transcript.md](transcript.md) — 3862 bytes
- [llm_events.jsonl](llm_events.jsonl) — 6783 bytes
- [tool_calls.jsonl](tool_calls.jsonl) — 823 bytes
- [agent_audit.jsonl](agent_audit.jsonl) — 7706 bytes
- [mission.json](mission.json) — 4324 bytes
- [mission_record.json](mission_record.json) — 2 bytes
- [photos_metadata.json](photos_metadata.json) — 377 bytes
- [metrics.json](metrics.json) — 2656 bytes

## Agent 审计关键行（拒绝/强制返航）

- agent_audit.jsonl:8 — `{"ts": "2026-11-08T22:03:45.483+08:00", "seq": 8, "run_id": "20261108_220342_P2", "event": "safety_check", "tool": "goto_waypoints", "command_id": "c-0001", "decision": "reject", "reasons": ["goto_waypoints 需要 state=hove`
- agent_audit.jsonl:9 — `{"ts": "2026-11-08T22:03:45.483+08:00", "seq": 9, "run_id": "20261108_220342_P2", "event": "command_rejected", "tool": "goto_waypoints", "command_id": "c-0001", "error_code": "E_STATE", "reasons": ["goto_waypoints 需要 sta`
- agent_audit.jsonl:18 — `{"ts": "2026-11-08T22:03:49.285+08:00", "seq": 18, "run_id": "20261108_220342_P2", "event": "safety_check", "tool": "set_mode", "command_id": "c-0002", "decision": "allow", "reasons": [], "error_code": null}`
