# Copilot / AI 编程助手说明

本仓库是 **DJI Mini × UE5 × 3DGS 可行性验证 + LLM Tool-Call 调度无人机** 的技术验证工程。

**详细 Agent 指南见根目录 [AGENTS.md](../AGENTS.md)**（唯一权威）；本文件只列最高频约束。

## 关键路径

- Phase-1（LLM 调度）代码：`llm_drone/`；冻结规格：`llm_drone/spec/PROTOCOL.md` + `tools.json`
- Phase-0（3DGS/UE5）：`pipeline/`、`capture/`、`ue5/`
- 文档索引：`docs/INDEX.md`；环境：`docs/SETUP.md`

## 必须遵守

1. 修改前先读 `llm_drone/spec/PROTOCOL.md`；协议/工具/错误码变更必须同步 spec + 测试。
2. LLM 不直连 DJI SDK；飞行命令必须经确定性安全层；错误码必须逐字匹配 spec §8.2。
3. `llm_drone/` 只用 Python 标准库；不要提交 `data/` 大数据、UE `Binaries/Intermediate/Saved`、`.venv`、日志、密钥、个人绝对路径。
4. `msdk_bridge/` 是未编译/未真机的设计层，禁止声称已飞行/已编译。
5. 改动后运行：`cd llm_drone && python -m unittest discover -s tests -v`（~118 tests）。

## 问答/生成建议

- 需要新增工具/场景/安全规则时，先看 `AGENTS.md` §4 的 playbook。
- 需要给其他 Agent 的交接提示词：`docs/AGENT_PROMPT.md`（中/英）。
