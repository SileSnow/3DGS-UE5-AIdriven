# CLAUDE.md

> 本文件是给 Claude Code 等读取 `CLAUDE.md` 的 Agent 的入口。
> **权威指南在 [AGENTS.md](AGENTS.md)，请先完整读它**；若两者冲突，以 AGENTS.md 为准。
> 交接提示词：`docs/AGENT_PROMPT.md`（中/英）。

## 最小上手

```powershell
cd llm_drone
python -m unittest discover -s tests -v                 # 基线 ~118 tests OK
python logs/lead/verify_acceptance.py --port 8766       # 黑盒验收 27/27
```

## 三条最重要的约束

1. `llm_drone/spec/PROTOCOL.md`（v1.1）与 `tools.json` 是**冻结契约**，改协议/工具/错误码必须同步 spec + 测试。
2. LLM **永不直连 DJI SDK**；飞行指令必须经 Drone Agent 的确定性 SafetyValidator；飞行工具必须 `confirm=true`。
3. 不提交大数据/构建产物/日志/密钥；`llm_drone/` 只用 Python 标准库。

完整规则、任务 playbook、环境与已知边界见 [AGENTS.md](AGENTS.md)。
