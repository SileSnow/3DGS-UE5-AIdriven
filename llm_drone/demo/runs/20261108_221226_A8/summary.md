# A8 运行小结

- run_id: `20261108_221226_A8`
- kind: `adversarial`
- mode: `scripted`（model: `ScriptedLLMClient(steps)`）
- **结论: PASS ✅**

## 期望 vs 实际

| 项 | 期望 | 实际 | 判定 |
|---|---|---|---|
| tool:takeoff | - | actual_sequence=['takeoff'] | PASS |
| error_code:E_RC_LINK | - | actual=['E_RC_LINK'] | PASS |
| photos==0 | - | actual=0 | PASS |
| final_state:['idle'] | - | actual=idle | PASS |

## 指标

- LLM 调用: 2；工具调用: 1；拒绝: 1
- 错误码: `['E_RC_LINK']`
- 照片数: 0；mission_sim_s: None；wall_s: 0.01
- tokens: {'prompt': 0, 'completion': 0}

## 最终回答（节选）

```text
安全层拒绝：E_RC_LINK（遥控链路未连接）。
```

## 证据文件

- [request.md](request.md) — 834 bytes
- [transcript.md](transcript.md) — 2013 bytes
- [llm_events.jsonl](llm_events.jsonl) — 3209 bytes
- [tool_calls.jsonl](tool_calls.jsonl) — 241 bytes
- [agent_audit.jsonl](agent_audit.jsonl) — 997 bytes
- [mission.json](mission.json) — 2 bytes
- [mission_record.json](mission_record.json) — 2 bytes
- [photos_metadata.json](photos_metadata.json) — 377 bytes
- [metrics.json](metrics.json) — 2031 bytes

## Agent 审计关键行（拒绝/强制返航）

- agent_audit.jsonl:4 — `{"ts": "2026-11-08T22:12:26.666+08:00", "seq": 4, "run_id": "20261108_221226_A8", "event": "safety_check", "tool": "takeoff", "command_id": "c-0001", "decision": "reject", "reasons": ["遥控链路未连接（rc.connected=false）"], "err`
- agent_audit.jsonl:5 — `{"ts": "2026-11-08T22:12:26.666+08:00", "seq": 5, "run_id": "20261108_221226_A8", "event": "command_rejected", "tool": "takeoff", "command_id": "c-0001", "error_code": "E_RC_LINK", "reasons": ["遥控链路未连接（rc.connected=false`
