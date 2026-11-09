# A10 — real 模式（Phase1 不可用，scripted）

- scenario_id: `A10`
- kind: `adversarial`
- run_id: `20261108_221226_A10`
- mode: `scripted`（real_llm=真实 LLM；scripted=预置工具序列直调）
- model: `ScriptedLLMClient(steps)`
- base_url: ``
- api_style: `scripted`
- agent_url: `http://127.0.0.1:8765`
- started_at: `2026-11-08T22:12:26.758+08:00`

## 用户提示（发给 LLM 的 user message）

```text
（scripted 直调）调用 set_mode(real, confirm=true)，验证 Phase-1 返回 E_REAL_NOT_AVAILABLE。
```

## 期望（PROTOCOL.md §11）

- expected_tools: `['set_mode']`
- expected_error_code: `E_REAL_NOT_AVAILABLE`
- expect_photos: `0`
- expect_mission_state: `None`

## 备注

scripted 直调（不经过真实 LLM 决策，仅复现安全拒绝路径）
