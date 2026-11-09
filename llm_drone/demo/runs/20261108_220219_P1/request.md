# P1 — 网格航拍（真实 LLM）

- scenario_id: `P1`
- kind: `positive`
- run_id: `20261108_220219_P1`
- mode: `real_llm`（real_llm=真实 LLM；scripted=预置工具序列直调）
- model: `qwen3.5:4b`
- base_url: `http://127.0.0.1:11434`
- api_style: `ollama`
- agent_url: `http://127.0.0.1:8765`
- started_at: `2026-11-08T22:02:19.513+08:00`

## 用户提示（发给 LLM 的 user message）

```text
对 (39.9042, 116.4074) 半径 28 米的区域做 40 米高度的网格航拍，重叠率 70%，云台 -45°，拍完返航。
```

## 期望（PROTOCOL.md §11）

- expected_tools: `['plan_capture_mission', 'takeoff', 'goto_waypoints', 'return_to_home']`
- expected_error_code: `None`
- expect_photos: `{'min': 12}`
- expect_mission_state: `completed`

## 备注

真实 LLM（Ollama qwen3.5:4b）工具调用循环
