# P2 — 环绕拍摄（真实 LLM）

- scenario_id: `P2`
- kind: `positive`
- run_id: `20261108_220454_P2`
- mode: `real_llm`（real_llm=真实 LLM；scripted=预置工具序列直调）
- model: `qwen3.5:4b`
- base_url: `http://127.0.0.1:11434`
- api_style: `ollama`
- agent_url: `http://127.0.0.1:8765`
- started_at: `2026-11-08T22:04:54.829+08:00`

## 用户提示（发给 LLM 的 user message）

```text
环绕目标 (39.90435, 116.40755) 半径 30 米、高度 50 米拍 12 张照片，云台 -30°，拍完返航。
```

## 期望（PROTOCOL.md §11）

- expected_tools: `['plan_capture_mission', 'takeoff', 'goto_waypoints', 'return_to_home']`
- expected_error_code: `None`
- expect_photos: `{'exact': 12}`
- expect_mission_state: `completed`

## 备注

真实 LLM（Ollama qwen3.5:4b）工具调用循环
