# P1 运行小结

- run_id: `20261108_220132_P1`
- kind: `positive`
- mode: `real_llm`（model: `qwen3.5:4b`）
- **结论: FAIL ❌**

## 期望 vs 实际

| 项 | 期望 | 实际 | 判定 |
|---|---|---|---|
| tool:plan_capture_mission | - | actual_sequence=['plan_capture_mission'] | PASS |
| tool:takeoff | - | actual_sequence=['plan_capture_mission'] | FAIL |
| tool:goto_waypoints | - | actual_sequence=['plan_capture_mission'] | FAIL |
| tool:return_to_home | - | actual_sequence=['plan_capture_mission'] | FAIL |
| photos>=12 | - | actual=0 | FAIL |
| mission_state:completed | - | actual=None | FAIL |
| no_rejection | - | rejected=0 | PASS |

## 指标

- LLM 调用: 2；工具调用: 1；拒绝: 0
- 错误码: `[]`
- 照片数: 0；mission_sim_s: None；wall_s: 4.37
- tokens: {'prompt': 7718, 'completion': 168}

## 最终回答（节选）

```text
网格航拍任务已规划完成：中心 (39.9042,116.4074)，区域 56m×56m，航高 40m，
```

## 证据文件

- [request.md](request.md) — 858 bytes
- [transcript.md](transcript.md) — 1983 bytes
- [llm_events.jsonl](llm_events.jsonl) — 4068 bytes
- [tool_calls.jsonl](tool_calls.jsonl) — 356 bytes
- [agent_audit.jsonl](agent_audit.jsonl) — 1941 bytes
- [mission.json](mission.json) — 6432 bytes
- [mission_record.json](mission_record.json) — 2 bytes
- [photos_metadata.json](photos_metadata.json) — 377 bytes
- [metrics.json](metrics.json) — 2500 bytes
