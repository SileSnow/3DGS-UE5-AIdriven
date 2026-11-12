# AGENTS.md — 给 AI 编码 Agent 的仓库指南

> 本仓库由「人类 + AI Agent」协作维护。**开始任务前先读完本文件**：它告诉你在哪改、怎么跑、什么不能碰、怎么证明改对了。
> 权威规格：`llm_drone/spec/PROTOCOL.md`（v1.1）+ `tools.json`。发现本文件与代码冲突时，以规格为准并报告差异。
> 交接提示词（可直接复制给其他 Agent）：[docs/AGENT_PROMPT.md](docs/AGENT_PROMPT.md)。
> 当前状态（2026-11-12）：Phase-0 / Phase-1 均已完成；3DGS 演示片 v6 已用 gsplat CUDA 后端重训（40k iter / 199,298 splat / val PSNR 16.62 dB）。
> 建议阅读顺序：本文件 → [docs/QUICKSTART.md](docs/QUICKSTART.md) → [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) → [docs/RESULTS.md](docs/RESULTS.md)。

## 0. TL;DR

- **核心代码**：`llm_drone/`（Phase-1：LLM tool-call 调度无人机）；`orchestrator/sim/safety/tests` **仅标准库**，`ue5_mission/` 另用 numpy/PIL/UE Python。
- **两阶段**：Phase-0 = DJI Mini 航拍→3DGS→UE5 可行性（`pipeline/ capture/ ue5/ report/`）；Phase-1 = LLM 安全调度（`llm_drone/`）。
- **不可违反**：冻结契约；LLM 永不直连 DJI SDK；飞行命令必须过确定性安全层 + `confirm=true`。
- **改动后必跑**：`cd llm_drone && python -m unittest discover -s tests -v`（基线 ~118 tests OK）。
- **禁止提交**：大数据、UE 构建产物、venv、运行日志、密钥、个人绝对路径（见 §3）。
- **默认不需要**：GPU / UE5 / 真机 / 网络（Phase-1 单测离线可跑；真实 LLM 需本机 Ollama）。

## 1. 仓库地图（先读哪个）

| 路径 | 是什么 | 何时读 |
|---|---|---|
| [README.md](README.md) | 项目总览 + 快速开始 | 第一次接手 |
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | 从 0 跑通（基线/演示/3DGS/UE5/常见坑） | 第一次跑 |
| [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) | 已知问题 / 文档漂移 / 环境限制 | **动手前必读** |
| [docs/RESULTS.md](docs/RESULTS.md) | 量化结论与证据索引 | 复核结论 |
| [llm_drone/README.md](llm_drone/README.md) | Phase-1 使用说明 | 改 Phase-1 前 |
| [llm_drone/spec/PROTOCOL.md](llm_drone/spec/PROTOCOL.md) | **冻结规格**：HTTP/mission/安全/错误码/审计 | 一切 Phase-1 改动的唯一事实源 |
| [llm_drone/spec/tools.json](llm_drone/spec/tools.json) | 15 个 LLM 工具 schema | 改工具/提示词前 |
| [llm_drone/docs/CONTRACT.md](llm_drone/docs/CONTRACT.md) | 任务契约 | 理解需求边界 |
| [llm_drone/docs/ACCEPTANCE.md](llm_drone/docs/ACCEPTANCE.md) | 验收报告 | 交付前核对 |
| [docs/INDEX.md](docs/INDEX.md) / [docs/SETUP.md](docs/SETUP.md) | 文档导航 / 环境搭建 | 找资料、环境问题 |
| [pipeline/README.md](pipeline/README.md)、[capture/README.md](capture/README.md)、[ue5/](ue5/) | Phase-0（3DGS/UE5） | 改 Phase-0 |
| [shared/CONVENTIONS.md](shared/CONVENTIONS.md) | 数据契约（metadata/PLY/坐标） | 改数据格式 |
| [data/README.md](data/README.md) | 大数据说明与生成命令 | 需要数据 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 贡献流程（Agent 同样适用） | 提交前 |
| [docs/AGENT_PROMPT.md](docs/AGENT_PROMPT.md) | **复制给其他 Agent 的提示词**（中/英） | 交接任务 |

## 2. 基线命令（先跑通再动手）

```powershell
cd llm_drone
python -m unittest discover -s tests -v                 # 基线 ~118 tests OK
python logs/lead/verify_acceptance.py --port 8766       # 黑盒验收 27/27（自动起仿真 Agent）

# 可选：跑一个确定性演示（无需 LLM）
python -m sim.server --port 8765 --time-scale 20        # 终端 A
python -m orchestrator.run_demo --agent-url http://127.0.0.1:8765 --scenario P1 --scripted-for P1 --out demo/runs  # 终端 B
```

> 真实 LLM（可选）：Ollama + `qwen3.5:4b`，请求必须显式 `options={num_ctx:16384, num_predict:1024, temperature:0.1}`；否则默认 4096 上下文会截断多轮工具结果、产生空响应。

## 3. 硬约束（违反即返工）

1. **契约冻结**：`spec/PROTOCOL.md` / `tools.json` / `sample_mission.json`。改协议/工具/错误码/字段语义 → 同步改 spec + 单测 + 文档，并在提交说明写兼容性。
2. **安全不可绕过**：LLM 只产出意图与参数；所有飞行指令经 Drone Agent 的确定性 `SafetyValidator`；`takeoff/goto_waypoints/orbit/set_mode(real)` 必须 `confirm=true`；审计 JSONL 不可关闭。
3. **错误码逐字一致**：拒绝返回 `spec §8.2` 的错误码（如 `E_ALT_LIMIT`），不得把内部规则名（如 `MAX_ALTITUDE`）当顶层错误码。
4. **依赖约束**：`llm_drone/{orchestrator,sim,safety,tests}` 仅标准库，不要新增 pip 依赖；`ue5_mission/` 允许 numpy/PIL 与 UE 自带 Python；Phase-0 一律走 `pipeline/.venv`。
5. **数据策略**：不提交 `data/{synthetic,trained,dji,sample}`、UE `Binaries/Intermediate/Saved`、`pipeline/.venv`、运行日志、`report/flight_raw|audio|*.mp4`；新文件 <2MB；样例放 `data/samples/` 并更新其 README。
6. **不伪造**：`msdk_bridge/` 是"未编译/未真机"的设计层，禁止声称已飞；量化结论必须有落盘证据；不要改历史证据（`demo/runs/`、acceptance JSON），只可新增。
7. **无密钥/隐私**：不写 API Key、Token、个人绝对路径（用 `<repo>` 或约定的 `C:\UEW`）；DJI 原始抓取证据不入库。

## 4. 常见任务 playbook

| 任务 | 改动路径 | 验证 |
|---|---|---|
| 新增 LLM 工具 | `spec/tools.json` → `orchestrator/tool_schemas.py` → `orchestrator/tools_runtime.py` → `safety/schemas.py` + `sim/server.py` → `tests/` → 文档 | 单测 + `run_demo --scripted-for` |
| 新增演示场景 | `demo/scenarios.json`（expected_tools/expected_error_code）→ 测试 → 跑 `demo/runs/<run_id>/` | 场景 PASS + 十件套完整 |
| 改安全规则/阈值 | `safety/config.json` + `safety/validator.py` + `tests/safety/` + `spec §8` + 报告 | 全量单测 + 黑盒验收（A1–A10） |
| 改规划器 | `orchestrator/planner.py` + `tests/orchestrator/test_planner.py` | 单测 + mission 可被 `ue5_mission/mission_io.py` 解析 |
| 改 Mission 渲染 | `llm_drone/ue5_mission/`（`mission_io.py` 离线可测；渲染需 UE5.8.4+GPU，独占串行） | `validate_output.py` ok=true |
| 改 Phase-0 | 先读各自 README；GPU 独占、ASCII junction `C:\UEW` | 对应 RESULTS/validation；大数据不入库 |
| 只改文档 | `docs/` / README / `docs/INDEX.md` | 链接有效、无个人路径 |

## 5. 环境要点

- Windows 11 为主；Phase-1 Python 代码跨平台（Linux/macOS 可跑单测）。
- Python 3.12+（本项目 3.14.6 验证）；`llm_drone` 零第三方依赖。
- Ollama 可选（`qwen3.5:4b`）；无 LLM 用 `--scripted`。
- UE5.8.4 + NVIDIA GPU 仅 Phase-0/UE5 渲染需要；中文路径必须 ASCII junction `C:\UEW`；UE 渲染独占串行。详见 [docs/SETUP.md](docs/SETUP.md)。
- 3DGS 可选 gsplat CUDA 后端（约 40× 加速）；Windows/CUDA 13.5/MSVC 的编译配方与已知坑见 [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) §C。

## 6. 提交与沟通

- Conventional Commits（`feat:`/`fix:`/`docs:`/`test:`/`refactor:`）。
- 每次交付附：改了什么 / 怎么验证（命令+关键输出）/ 风险与回滚。
- **先停下来问人类**：改冻结契约、删除/重写证据、加依赖、动真机协议/安全阈值、许可证、引入大文件。

## 7. 已知边界（不要"修"成错误结论）

- 真机未执行：MSDK v5 桥未编译、未连接飞控、未飞行；KMZ 是否被 Mini 4 Pro 接受未验证。
- A6–A10 演示为 scripted 直调（已标注）；A1–A5 为真实 LLM 触发。
- 4B 模型成功依赖工程辅助（num_ctx / 阶段感知续跑提醒 / 只读熔断）；更大模型未系统评测。
- UE5 渲染是程序化仿真场景，不代表真机画质；Niagara splat 渲染（Path A）仍有尺度问题，演示用 Path B 点云预览。
- gsplat 1.5.3 在 Windows + CUDA 13.5 + MSVC 14.51 需要 ASCII 路径 + 预处理器开关 + 禁用两个未用 API，见 KNOWN_ISSUES §C。
- 上传前已把个人绝对路径替换为 `<repo>`/`<user>` 占位符并重建 git 历史；不要再用本机绝对路径提交。
