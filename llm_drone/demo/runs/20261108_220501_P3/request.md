# P3 — 定点拍摄 + 降落（真实 LLM）

- scenario_id: `P3`
- kind: `positive`
- run_id: `20261108_220501_P3`
- mode: `real_llm`（real_llm=真实 LLM；scripted=预置工具序列直调）
- model: `qwen3.5:4b`
- base_url: `http://127.0.0.1:11434`
- api_style: `ollama`
- agent_url: `http://127.0.0.1:8765`
- started_at: `2026-11-08T22:05:01.419+08:00`

## 用户提示（发给 LLM 的 user message）

```text
飞到 (39.9045, 116.4070) 30 米高度定点拍 5 张照片，间隔 3 秒，然后原地降落。
```

## 期望（PROTOCOL.md §11）

- expected_tools: `['plan_capture_mission', 'takeoff', 'goto_waypoints', 'land']`
- expected_error_code: `None`
- expect_photos: `{'exact': 5}`
- expect_mission_state: `completed`

## 备注

真实 LLM（Ollama qwen3.5:4b）工具调用循环
