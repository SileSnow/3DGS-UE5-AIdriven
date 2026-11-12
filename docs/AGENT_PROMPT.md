# 给其他 AI Agent 的提示词（AGENT_PROMPT）

> 用途：把下面整段 prompt 粘贴给你同事的 Agent（Claude Code / Codex / Cursor / Aider / Copilot / 自研 Agent），
> 让它快速理解本仓库并安全开始工作。把 `<REPO_PATH>` 替换成本地仓库绝对路径。
> 更完整的仓库规则见根目录 [AGENTS.md](../AGENTS.md)；本文件是"交接用的一页纸"。

## 中文版（推荐直接复制）

```text
你是被派来协作 GitHub 仓库 dji-ue5-3dgs 的 AI 编码 Agent。仓库已 clone 到 <REPO_PATH>。
请先读根目录 AGENTS.md（权威指南），然后按下面信息快速上手；不要凭猜测改代码。

【项目是什么】
两个阶段的可复现验证工程：
- Phase-0：DJI Mini 航拍 → 3DGS 重建 → UE5.8 渲染（pipeline/、capture/、ue5/、report/）；
- Phase-1：LLM tool-call 安全调度无人机（llm_drone/）：LLM Orchestrator → Drone Agent（确定性安全层）
  → 仿真后端 / Android MSDK v5 桥；UE5 虚拟相机按 mission 渲染。真机仅设计、未执行。
核心开发目录：llm_drone/；冻结规格：llm_drone/spec/PROTOCOL.md 与 tools.json。

【第一步：跑基线，确认环境 OK】
cd <REPO_PATH>/llm_drone
python -m unittest discover -s tests -v               # 期望 ~118 tests OK
python logs/lead/verify_acceptance.py --port 8766     # 期望 27/27 PASS
若失败，先读 docs/SETUP.md 排查；不要假设"环境正常"就继续改。

【硬约束（绝对不要违反）】
1) llm_drone/spec/PROTOCOL.md（v1.1）与 tools.json 是冻结契约；改协议/工具/错误码/字段语义必须同步更新 spec + 单测 + 文档，并在提交说明写兼容性。
2) LLM 永不直连 DJI SDK；所有飞行指令必须经 Drone Agent 的确定性 SafetyValidator；
   takeoff/goto_waypoints/orbit/set_mode(real) 必须 confirm=true；审计 JSONL 不可关闭。
3) 错误码必须与 spec/PROTOCOL.md §8.2 逐字一致（如 E_ALT_LIMIT）；不得用 MAX_ALTITUDE 等内部名替换。
4) llm_drone/ 只用 Python 标准库，不新增 pip 依赖。
5) 不提交：data/{synthetic,trained,dji,sample}、UE Binaries/Intermediate/Saved、pipeline/.venv、
   运行日志、report/flight_raw、report/audio、*.mp4；新文件 < 2MB；样例放 data/samples/ 并更新其中 README。
6) 不写密钥/个人绝对路径；不修改历史证据文件（demo/runs/、acceptance JSON），只能新增。
7) msdk_bridge/ 是未编译、未真机的设计层：禁止声称已编译/已飞行；改动须同步 PROTOCOL_COMPLIANCE.md 与 test_protocol.md。
8) 真实 LLM 演示用 Ollama qwen3.5:4b，并显式 options={num_ctx:16384, num_predict:1024, temperature:0.1}；
   无 LLM 时用 --scripted 并在结果中如实标注。

【常用命令】
# 终端 A：起仿真 Agent
cd <REPO_PATH>/llm_drone && python -m sim.server --port 8765 --time-scale 20
# 终端 B：跑演示（P1 单场景 + scripted 确定性；不依赖 LLM）
python -m orchestrator.run_demo --agent-url http://127.0.0.1:8765 --scenario P1 --scripted-for P1 --out demo/runs
# 全量演示（真实 LLM；A6-A10 默认 scripted）
python -m orchestrator.run_demo --agent-url http://127.0.0.1:8765 --scenario all --out demo/runs

【改动方法】
- 先按 AGENTS.md §4 的 playbook 定位要改的文件（工具 / 场景 / 安全规则 / 规划器 / UE5 渲染 / Phase-0）。
- 每次改动后跑单测与黑盒验收；新增场景必须落 demo/runs/<run_id>/ 全文件（transcript/审计/metrics/mission 等）。
- 交付时给出：改了什么、怎么验证（命令 + 关键输出）、风险与回滚；量化结论必须有落盘证据。

【停下来问人的情况】
改冻结契约、删除/重写证据、增加依赖、修改真机协议或安全阈值、许可证、引入大文件/大数据 —— 先问，不要自行决定。

开始前请先输出：①你读到的仓库当前状态（分支/提交/测试结果）；②本次任务计划（不超过 8 行）；然后等我确认或直接开始最小改动。
```

## English version（for English-speaking agents）

```text
You are an AI coding agent joining the GitHub repo "dji-ue5-3dgs" (cloned at <REPO_PATH>).
Read AGENTS.md at the repo root first (the authoritative guide), then follow this quick start. Do not guess.

WHAT THIS REPO IS
Two reproducible validation phases:
- Phase-0: DJI Mini aerial capture -> 3DGS reconstruction -> UE5.8 rendering (pipeline/, capture/, ue5/, report/)
- Phase-1: LLM tool-call orchestration of drone missions (llm_drone/): LLM Orchestrator -> Drone Agent
  with a deterministic SafetyValidator -> simulator / Android MSDK v5 bridge; UE5 virtual-camera mission
  rendering. Real drone is design-only, not executed.
Core dev dir: llm_drone/. Frozen contract: llm_drone/spec/PROTOCOL.md and tools.json.

BASELINE (run first)
cd <REPO_PATH>/llm_drone
python -m unittest discover -s tests -v               # expect ~118 tests OK
python logs/lead/verify_acceptance.py --port 8766     # expect 27/27 PASS
If this fails, read docs/SETUP.md first. Do not assume the environment is fine.

HARD CONSTRAINTS (never violate)
1) PROTOCOL.md (v1.1) and tools.json are frozen. Changing protocol, tools, error codes or field semantics
   requires updating the spec, unit tests and docs, plus a compatibility note in the commit message.
2) The LLM never talks to the DJI SDK directly. All flight commands go through the Drone Agent deterministic
   SafetyValidator. takeoff/goto_waypoints/orbit/set_mode(real) require confirm=true. The JSONL audit cannot be disabled.
3) Rejection codes must match spec section 8.2 verbatim (e.g. E_ALT_LIMIT).
4) llm_drone/ is stdlib-only. Do not add pip dependencies.
5) Never commit: data/{synthetic,trained,dji,sample}, UE Binaries/Intermediate/Saved, pipeline/.venv, runtime logs,
   report/flight_raw, report/audio, *.mp4. New files must stay under 2 MB. Samples go to data/samples/ with its README updated.
6) No secrets or personal absolute paths. Do not rewrite historical evidence (demo/runs/, acceptance JSON); only add.
7) msdk_bridge/ is an unverified design layer (never compiled, never flown). Never claim otherwise. Sync
   PROTOCOL_COMPLIANCE.md and test_protocol.md when changing it.
8) Real-LLM demos use Ollama qwen3.5:4b with explicit options={num_ctx:16384, num_predict:1024, temperature:0.1}.
   Without an LLM use --scripted and label results honestly.

COMMON COMMANDS
# terminal A: simulator agent
cd <REPO_PATH>/llm_drone && python -m sim.server --port 8765 --time-scale 20
# terminal B: deterministic demo (no LLM needed)
python -m orchestrator.run_demo --agent-url http://127.0.0.1:8765 --scenario P1 --scripted-for P1 --out demo/runs
# full demo (real LLM; A6-A10 scripted by default)
python -m orchestrator.run_demo --agent-url http://127.0.0.1:8765 --scenario all --out demo/runs

HOW TO CHANGE THINGS
- Follow the playbooks in AGENTS.md section 4 (tools / scenarios / safety rules / planner / UE5 rendering / Phase-0).
- After each change run unit tests and black-box acceptance. New scenarios must write full demo/runs/<run_id>/ evidence.
- Deliver: what changed, how verified (commands + key output), risks/rollback. Every quantitative claim needs a file artifact.

ASK THE HUMAN FIRST BEFORE
Changing frozen contracts, deleting or rewriting evidence, adding dependencies, touching real-drone protocols or
safety thresholds, licensing, or introducing large data/files.

Before starting, print: (1) the repo state you observed (branch/commit/test results), (2) a plan of at most 8 lines;
then proceed with the smallest safe change.
```

## 使用小技巧

1. **先跑基线再把输出贴给 Agent**：避免它在错误环境里"盲改"。
2. **让它先输出计划再动手**：提示词最后一条就是"先输出计划"，便于你控制改动范围。
3. **UE5 / Phase-0 任务**：额外提醒它读 `capture/README.md`、`docs/SETUP.md` 中的 ASCII junction 与 GPU 独占要求。
4. **多 Agent 并行**：按 `AGENTS.md` §4 的 playbook 给每个 Agent 分配不重叠目录（如 A 改 `sim/`、B 改 `ue5_mission/`），避免同时写同一文件。
5. **交接前**：把 `git log -1 --oneline` 与基线测试结果一起发过去，Agents 会更快进入状态。
