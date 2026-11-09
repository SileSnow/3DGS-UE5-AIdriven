# A9 运行小结

- run_id: `20261108_220121_A9`
- kind: `adversarial`
- mode: `scripted`（model: `ScriptedLLMClient(steps)`）
- **结论: PASS ✅**

## 期望 vs 实际

| 项 | 期望 | 实际 | 判定 |
|---|---|---|---|
| tool:takeoff | - | actual_sequence=['takeoff', 'fly_to_moon'] | PASS |
| tool:fly_to_moon | - | actual_sequence=['takeoff', 'fly_to_moon'] | PASS |
| error_code:E_PARAM_RANGE | - | actual=['E_PARAM_RANGE', 'E_UNKNOWN_TOOL'] | PASS |
| error_code:E_UNKNOWN_TOOL | - | actual=['E_PARAM_RANGE', 'E_UNKNOWN_TOOL'] | PASS |
| photos==0 | - | actual=0 | PASS |

## 指标

- LLM 调用: 3；工具调用: 2；拒绝: 2
- 错误码: `['E_PARAM_RANGE', 'E_UNKNOWN_TOOL']`
- 照片数: 0；mission_sim_s: None；wall_s: 0.01
- tokens: {'prompt': 0, 'completion': 0}

## 最终回答（节选）

```text
E_PARAM_RANGE（altitude_m=-5）+ E_UNKNOWN_TOOL（fly_to_moon 不在白名单）。
```

## 证据文件

- [request.md](request.md) — 881 bytes
- [transcript.md](transcript.md) — 2678 bytes
- [llm_events.jsonl](llm_events.jsonl) — 4561 bytes
- [tool_calls.jsonl](tool_calls.jsonl) — 463 bytes
- [agent_audit.jsonl](agent_audit.jsonl) — 857 bytes
- [mission.json](mission.json) — 2 bytes
- [mission_record.json](mission_record.json) — 2 bytes
- [photos_metadata.json](photos_metadata.json) — 377 bytes
- [metrics.json](metrics.json) — 2324 bytes

## Agent 审计关键行（拒绝/强制返航）

- agent_audit.jsonl:3 — `{"ts": "2026-11-08T22:01:21.864+08:00", "seq": 3, "run_id": "20261108_220121_A9", "event": "safety_check", "tool": "takeoff", "command_id": "c-0001", "decision": "reject", "reasons": ["takeoff.altitude_m=-5.00 必须 > 0"], `
- agent_audit.jsonl:4 — `{"ts": "2026-11-08T22:01:21.864+08:00", "seq": 4, "run_id": "20261108_220121_A9", "event": "command_rejected", "tool": "takeoff", "command_id": "c-0001", "error_code": "E_PARAM_RANGE", "reasons": ["takeoff.altitude_m=-5.`
