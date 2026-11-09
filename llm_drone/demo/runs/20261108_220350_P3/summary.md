# P3 运行小结

- run_id: `20261108_220350_P3`
- kind: `positive`
- mode: `real_llm`（model: `qwen3.5:4b`）
- **结论: FAIL ❌**

## 期望 vs 实际

| 项 | 期望 | 实际 | 判定 |
|---|---|---|---|
| tool:plan_capture_mission | - | actual_sequence=['get_telemetry', 'get_telemetry', 'get_telemetry', 'get_telemetry'] | FAIL |
| tool:takeoff | - | actual_sequence=['get_telemetry', 'get_telemetry', 'get_telemetry', 'get_telemetry'] | FAIL |
| tool:goto_waypoints | - | actual_sequence=['get_telemetry', 'get_telemetry', 'get_telemetry', 'get_telemetry'] | FAIL |
| tool:land | - | actual_sequence=['get_telemetry', 'get_telemetry', 'get_telemetry', 'get_telemetry'] | FAIL |
| photos==5 | - | actual=0 | FAIL |
| mission_state:completed | - | actual=None | FAIL |
| no_rejection | - | rejected=0 | PASS |
| final_state:['idle'] | - | actual=idle | PASS |

## 指标

- LLM 调用: 12；工具调用: 4；拒绝: 0
- 错误码: `[]`
- 照片数: 0；mission_sim_s: None；wall_s: 7.22
- tokens: {'prompt': 48255, 'completion': 117}

## 最终回答（节选）

```text
（达到最大工具调用轮次，任务未完成）
```

## 证据文件

- [request.md](request.md) — 831 bytes
- [transcript.md](transcript.md) — 5644 bytes
- [llm_events.jsonl](llm_events.jsonl) — 13171 bytes
- [tool_calls.jsonl](tool_calls.jsonl) — 839 bytes
- [agent_audit.jsonl](agent_audit.jsonl) — 2956 bytes
- [mission.json](mission.json) — 2 bytes
- [mission_record.json](mission_record.json) — 2 bytes
- [photos_metadata.json](photos_metadata.json) — 377 bytes
- [metrics.json](metrics.json) — 2820 bytes
