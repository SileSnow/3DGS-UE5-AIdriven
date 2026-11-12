# 贡献指南（Contributing）

> **AI Agent 请先读 [AGENTS.md](AGENTS.md)**（权威 Agent 指南）；本文是面向人类贡献者的流程说明，Agent 同样适用。

感谢参与本项目！本仓库包含两个阶段：**Phase-0（DJI Mini × UE5 × 3DGS 可行性验证）** 与 **Phase-1（LLM Tool-Call 调度无人机）**。提交前请阅读对应子项目的 README 与规格。

## 1. 开发环境

- Windows 11（Phase-0 的 UE5/capture 部分需要）；Phase-1 的 Python 代码跨平台（纯标准库）。
- Python 3.14（`llm_drone` 只用标准库）；Phase-0 pipeline 需要 `pipeline/.venv`（见 `pipeline/ENV.md`）。
- LLM：Ollama + `qwen3.5:4b`（或任意 OpenAI 兼容 API）。
- UE：Unreal Engine 5.8.4（见 `docs/SETUP.md`，中文路径需走 ASCII junction）。
- Phase-2 真机：DJI Mini 4 Pro + RC-N2/N3 + Android（见 `llm_drone/msdk_bridge/test_protocol.md`）。

## 2. 提交前自检（必须）

```powershell
cd dji_ue5_3dgs/llm_drone
python -m unittest discover -s tests -v        # 期望 ~118 tests OK
python logs\lead\verify_acceptance.py --port 8766   # 期望 27/27 PASS
```

- 改动 `sim/`/`safety/`/`orchestrator/` 时，先读 **`llm_drone/spec/PROTOCOL.md`**（冻结规格，唯一事实源）；
  若必须变更协议/工具/错误码，请同时更新 `spec/` 与测试，并在 PR 描述中说明。
- 改动工具/场景时同步更新 `llm_drone/spec/tools.json` 与 `llm_drone/demo/scenarios.json`。
- 不要提交大文件（见 §4 数据策略）；CI 会跑单测（`.github/workflows/tests.yml`）。

## 3. 代码风格

- Python：PEP 8、4 空格、UTF-8；`llm_drone` 保持**仅标准库**（不新增 pip 依赖）；类型注解可选。
- 文档：中文为主，技术术语保留英文；文件名用 ASCII 或既有中文命名风格，保持与相邻文件一致。
- 日志/审计：统一写 JSONL（UTF-8）；不要打印敏感信息或绝对个人路径。
- 提交信息：Conventional Commits（`feat:` / `fix:` / `docs:` / `test:` / `refactor:` / `chore:`）。

## 4. 数据策略（重要）

| 类别 | 是否入库 | 说明 |
|---|---|---|
| 源代码、配置、文档、小样例 | ✅ | `docs/`、`llm_drone/`、`pipeline/*.py`、`capture/scripts/`、`ue5/Source,Config`、`data/samples/` |
| 合成/训练/真机数据 | ❌ | `data/synthetic`、`data/trained`、`data/dji`、`report/flight_raw`（见 `data/README.md` 重新生成） |
| UE 构建产物 | ❌ | `Binaries/`、`Intermediate/`、`Saved/`、`DerivedDataCache/` |
| 运行日志 / 审计原始 JSONL | ❌ | 仅保留摘要（`llm_drone/logs/**/SUMMARY.md` 等） |
| 演示证据 run 目录 | ✅ | `llm_drone/demo/runs/`（小，可直接复核） |

如需新增样例数据：放入 `data/samples/`，单文件 < 2 MB，并在 `data/samples/README.md` 说明来源与许可。

## 5. PR 流程

1. Fork / 新建分支：`feat/<主题>`、`fix/<主题>`、`docs/<主题>`。
2. 本地通过 §2 自检；如涉及 Phase-0 UE 渲染，附上 `validation*.json` 结果。
3. 提交 PR，填写模板（改了什麼 / 怎么验证 / 风险与回滚）。
4. 至少 1 名维护者 review；涉及安全层（`llm_drone/safety/`）需 2 名 review。

## 6. 常用约定

- 不改动 `llm_drone/spec/` 中的冻结语义（v1.x）除非先讨论；新增字段向后兼容。
- 安全规则相关改动必须同时补对抗测试（`llm_drone/tests/safety/`）。
- 提交前检查 `git status`，不要把 `.venv`、`logs`、`data/` 大目录 add 进来。
- 真机相关代码（`msdk_bridge/`）改动必须更新 `PROTOCOL_COMPLIANCE.md` 与真机测试协议。
