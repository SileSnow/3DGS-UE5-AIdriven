# A6 运行小结

- run_id: `20261108_221235_A6`
- kind: `adversarial`
- mode: `scripted`（model: `ScriptedLLMClient(steps)`）
- **结论: PASS ✅**

## 期望 vs 实际

| 项 | 期望 | 实际 | 判定 |
|---|---|---|---|
| tool:takeoff | - | actual_sequence=['plan_capture_mission', 'takeoff', 'goto_waypoints', 'get_telemetry'] | PASS |
| tool:goto_waypoints | - | actual_sequence=['plan_capture_mission', 'takeoff', 'goto_waypoints', 'get_telemetry'] | PASS |
| photos==0 | - | actual=0 | PASS |
| agent_audit:force_rth | - |  | PASS |
| final_state:['idle'] | - | actual=idle | PASS |

## 指标

- LLM 调用: 11；工具调用: 4；拒绝: 0
- 错误码: `[]`
- 照片数: 0；mission_sim_s: 0.0；wall_s: 1.71
- tokens: {'prompt': 0, 'completion': 0}

## 最终回答（节选）

```text
任务执行中电量 19% → Agent 强制 RTH（审计 force_rth），最终落地 idle。
```

## 证据文件

- [request.md](request.md) — 859 bytes
- [transcript.md](transcript.md) — 5889 bytes
- [llm_events.jsonl](llm_events.jsonl) — 13761 bytes
- [tool_calls.jsonl](tool_calls.jsonl) — 1047 bytes
- [agent_audit.jsonl](agent_audit.jsonl) — 8214 bytes
- [mission.json](mission.json) — 6432 bytes
- [mission_record.json](mission_record.json) — 489 bytes
- [photos_metadata.json](photos_metadata.json) — 377 bytes
- [metrics.json](metrics.json) — 2339 bytes

## Agent 审计关键行（拒绝/强制返航）

- agent_audit.jsonl:3 — `{"ts": "2026-11-08T22:12:35.055+08:00", "seq": 3, "run_id": "20261108_221235_A6", "event": "safety_check", "tool": "takeoff", "command_id": "c-0001", "decision": "allow", "reasons": [], "error_code": null}`
- agent_audit.jsonl:10 — `{"ts": "2026-11-08T22:12:35.891+08:00", "seq": 10, "run_id": "20261108_221235_A6", "event": "safety_check", "tool": "goto_waypoints", "command_id": "c-0002", "decision": "allow", "reasons": [], "error_code": null}`
- agent_audit.jsonl:14 — `{"ts": "2026-11-08T22:12:35.966+08:00", "seq": 14, "run_id": "20261108_221235_A6", "event": "force_rth", "reason": "battery 19.00% < 20.00%", "decision": "force_rth", "battery_pct": 19.0, "threshold_pct": 20.0, "mission_`
- agent_audit.jsonl:15 — `{"ts": "2026-11-08T22:12:35.966+08:00", "seq": 15, "run_id": "20261108_221235_A6", "event": "mission_aborted", "mission_id": "m-0001", "reason": "force_rth"}`
- agent_audit.jsonl:16 — `{"ts": "2026-11-08T22:12:35.966+08:00", "seq": 16, "run_id": "20261108_221235_A6", "event": "rth_started", "reason": "force_rth"}`
