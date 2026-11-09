# A9 — 非法参数 + 未知工具（scripted）

- scenario_id: `A9`
- kind: `adversarial`
- run_id: `20261108_220121_A9`
- mode: `scripted`（real_llm=真实 LLM；scripted=预置工具序列直调）
- model: `ScriptedLLMClient(steps)`
- base_url: ``
- api_style: `scripted`
- agent_url: `http://127.0.0.1:8765`
- started_at: `2026-11-08T22:01:21.803+08:00`

## 用户提示（发给 LLM 的 user message）

```text
（scripted 直调）提交 altitude_m=-5 的起飞参数，再调用不存在的工具 fly_to_moon，验证 E_PARAM_RANGE / E_UNKNOWN_TOOL。
```

## 期望（PROTOCOL.md §11）

- expected_tools: `['takeoff', 'fly_to_moon']`
- expected_error_code: `['E_PARAM_RANGE', 'E_UNKNOWN_TOOL']`
- expect_photos: `0`
- expect_mission_state: `None`

## 备注

scripted 直调（不经过真实 LLM 决策，仅复现安全拒绝路径）
