# P3 运行小结

- run_id: `20261108_220501_P3`
- kind: `positive`
- mode: `real_llm`（model: `qwen3.5:4b`）
- **结论: FAIL ❌**

## 期望 vs 实际

| 项 | 期望 | 实际 | 判定 |
|---|---|---|---|
| tool:plan_capture_mission | - | actual_sequence=[] | FAIL |
| tool:takeoff | - | actual_sequence=[] | FAIL |
| tool:goto_waypoints | - | actual_sequence=[] | FAIL |
| tool:land | - | actual_sequence=[] | FAIL |
| photos==5 | - | actual=0 | FAIL |
| mission_state:completed | - | actual=None | FAIL |
| no_rejection | - | rejected=0 | PASS |
| final_state:['idle'] | - | actual=idle | PASS |

## 指标

- LLM 调用: 5；工具调用: 0；拒绝: 0
- 错误码: `[]`
- 照片数: 0；mission_sim_s: None；wall_s: 9.16
- tokens: {'prompt': 20287, 'completion': 193}

## 最终回答（节选）

```text
（模型未返回有效回答）
```

## 证据文件

- [request.md](request.md) — 831 bytes
- [transcript.md](transcript.md) — 1732 bytes
- [llm_events.jsonl](llm_events.jsonl) — 4071 bytes
- [tool_calls.jsonl](tool_calls.jsonl) — 0 bytes
- [agent_audit.jsonl](agent_audit.jsonl) — 3565 bytes
- [mission.json](mission.json) — 2 bytes
- [mission_record.json](mission_record.json) — 2 bytes
- [photos_metadata.json](photos_metadata.json) — 377 bytes
- [metrics.json](metrics.json) — 2433 bytes
