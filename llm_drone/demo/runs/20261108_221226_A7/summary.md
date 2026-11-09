# A7 运行小结

- run_id: `20261108_221226_A7`
- kind: `adversarial`
- mode: `scripted`（model: `ScriptedLLMClient(steps)`）
- **结论: PASS ✅**

## 期望 vs 实际

| 项 | 期望 | 实际 | 判定 |
|---|---|---|---|
| tool:takeoff | - | actual_sequence=['takeoff'] | PASS |
| error_code:E_GPS | - | actual=['E_GPS'] | PASS |
| photos==0 | - | actual=0 | PASS |
| final_state:['idle'] | - | actual=idle | PASS |

## 指标

- LLM 调用: 2；工具调用: 1；拒绝: 1
- 错误码: `['E_GPS']`
- 照片数: 0；mission_sim_s: None；wall_s: 0.02
- tokens: {'prompt': 0, 'completion': 0}

## 最终回答（节选）

```text
安全层拒绝：E_GPS（fix=1<3 / sats=6<10）。
```

## 证据文件

- [request.md](request.md) — 861 bytes
- [transcript.md](transcript.md) — 2010 bytes
- [llm_events.jsonl](llm_events.jsonl) — 3234 bytes
- [tool_calls.jsonl](tool_calls.jsonl) — 238 bytes
- [agent_audit.jsonl](agent_audit.jsonl) — 1242 bytes
- [mission.json](mission.json) — 2 bytes
- [mission_record.json](mission_record.json) — 2 bytes
- [photos_metadata.json](photos_metadata.json) — 377 bytes
- [metrics.json](metrics.json) — 2025 bytes

## Agent 审计关键行（拒绝/强制返航）

- agent_audit.jsonl:5 — `{"ts": "2026-11-08T22:12:26.578+08:00", "seq": 5, "run_id": "20261108_221226_A7", "event": "safety_check", "tool": "takeoff", "command_id": "c-0001", "decision": "reject", "reasons": ["GPS 质量不足：fix=1（需>=3）、satellites=6（需`
- agent_audit.jsonl:6 — `{"ts": "2026-11-08T22:12:26.578+08:00", "seq": 6, "run_id": "20261108_221226_A7", "event": "command_rejected", "tool": "takeoff", "command_id": "c-0001", "error_code": "E_GPS", "reasons": ["GPS 质量不足：fix=1（需>=3）、satellite`
