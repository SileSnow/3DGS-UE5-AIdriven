# KNOWN_ISSUES — 已知问题、文档漂移与限制

> 目的：避免维护者/Agent 把“已知问题”当 bug 修错，或把旧文档数字当最新事实。
> 处理原则：**冻结规格与代码为准**；历史报告/证据不改数字，只在这里记录口径。

## A. Phase-1 规格 vs 代码（冻结契约优先，仅记录，不擅自改语义）

| # | 问题 | 依据 |
|---|---|---|
| A1 | `takeoff` 在 spec §4 允许 `idle/landed`，但 validator 只接受 `idle`，且全代码无 `landed` 状态 | `llm_drone/spec/PROTOCOL.md` §4 vs `safety/validator.py` |
| A2 | `set_mode` 的 `confirm` 范围：spec 只要求 `set_mode(real)`；tools.json/代码对所有 `set_mode` 都要求 | `spec/tools.json`、`orchestrator/tools_runtime.py` |
| A3 | spec §8.2 写 `speed>15 → E_PARAM_RANGE`，§8 规则 2 写 `E_SPEED_LIMIT`；代码返回 `E_SPEED_LIMIT` | `spec/PROTOCOL.md` §8/§8.2、`safety/validator.py` |
| A4 | Orchestrator 会把非 spec 错误码当顶层码：`E_PLAN_NOT_FOUND` / `E_MISSION_*` / `E_AGENT_*` / `E_LLM*`（AGENTS §3.3 要求只顶层 spec 错误码） | `orchestrator/tools_runtime.py`、`agent_client.py`、`orchestrator.py` |
| A5 | 第二套工具 schema：`orchestrator/tool_schemas.py` 与 `spec/tools.json` 冲突（plan 参数名、orbit target、capture interval 上限 60 vs 10），仅在 LLM JSON 降级模式使用 | `orchestrator/tool_schemas.py` |
| A6 | 审计事件 `user_confirm` 是“LLM 自带 confirm=true 且 Agent 接受”后自动写入，**不是人工确认** | `orchestrator/orchestrator.py`、`orchestrator/audit.py` |
| A7 | `photos_metadata.json` 的 `timestamp` 用航点序号兜底（实测 P1 为 0..19），与 UE metadata 的秒数语义不同 | `sim/export.py` |
| A8 | planner 产出的 Mission 无 `mission_id`（spec §6 样例含该字段；UE5 侧按 warning 处理） | `orchestrator/planner.py`、`ue5_mission/README.md` |
| A9 | `gimbal yaw` 仅记录，不参与 c2w/照片位姿 | `sim/simulator.py` |
| A10 | 飞行状态 `aborted/failsafe` 从未被赋值（死代码） | `sim/simulator.py` |
| A11 | `agent_client` 的 `/v1/sim/inject` 回退分支不可达（未知端点返回 E_SCHEMA 而非 404） | `orchestrator/agent_client.py`、`sim/server.py` |
| A12 | `llm_drone/demo/README.md` 称“A6/A9/A10 默认 scripted”，实际 A7/A8 也是 scripted | `demo/scenarios.json` |
| A13 | `msdk_bridge/SUMMARY.md` 称 spec 错误码 19 种，实为 **20** 个（已在本仓库修正为 20） | `safety/errors.py`、`spec/PROTOCOL.md` §8.2 |
| A14 | 真实 LLM 的成功依赖“场景 expected_tools 提示 + 只读工具熔断 + 阶段感知续跑提醒”；不是纯裸模型能力 | `orchestrator/orchestrator.py`、`logs/orchestrator/SUMMARY.md` |
| A15 | “`llm_drone/` 仅标准库”的表述不准确：`orchestrator/sim/safety` 是标准库，但 `ue5_mission/` 用 numpy/PIL/unreal；AGENTS.md 已改为按目录声明 | `AGENTS.md` |

## B. Phase-0 文档与实测漂移

1. **报告正文数字为中间版本**：`report/DJI_Mini_UE5_3DGS_可行性验证报告.md` 的 actors/亮度/光栅化速度/部分 FPS 与最终实测不一致，**以 `pipeline/RESULTS.md` + 本地 `data/trained/*/metrics.json` 为准**；本次未回填历史报告（避免改证据），如需引用请标注“报告初稿数字”。
2. `pipeline/README.md` 原写“梯度阈值 2e-4”，代码默认是 `1e-8`（已修正 README）；实际阈值由 `--grad-thresh` 控制。
3. `shared/CONVENTIONS.md` 原示例 `fx=1234.5` 与实测 `1148.3429` 不一致（已修正示例）；`f_rest` 在导出 PLY 中固定写满 45 项（不是“可省略”）。
4. `report/README.md` 原把 `flight_raw/` 称为“真实 DJI 飞行原始素材”，实为 **UE 渲染帧**（已修正措辞）；仓库内不存在真实 DJI 飞行素材。
5. 报告曾引用 `shared/LEAD_KNOWLEDGE.md`（仓库中不存在），已改为只引用 `logs/ue5/`。
6. 根 README 旧版“附录 C 四条遗留”与报告附录 C 不一致；以本文件 E 节与报告 §8.3 为准。
7. `data/synthetic/capture/colmap/` 目录不存在；`02_sfm.py --mode known` 直接用真值位姿，不依赖 COLMAP 输出。

## C. 工具链 / 环境（复现前先看）

1. **中文路径**：UE / MSVC / pip CUDA 工具链都不能直接吃 `项目\GAIA项目` 这样的路径；UE 侧统一走 ASCII junction `C:\UEW`，Python/CUDA 侧用 ASCII 副本（见下条）。
2. **gsplat 1.5.3 在 Windows + CUDA 13.5 + MSVC 14.51** 的可用配方（v6 实测）：
   - `CUDA_HOME` 指向 ASCII 路径（可用 `C:\UEW\...\nvidia\cu13`）；
   - `_CL_=/Zc:preprocessor`、`NVCC_PREPEND_FLAGS="-allow-unsupported-compiler -Xcompiler=/Zc:preprocessor"`；
   - gsplat 的 `from-world 3DGS` 与 `2DGS backward` 两个 API 在本工具链有 nvcc↔MSVC 模板符号不匹配（LNK2019）；本项目不用它们，需在 ASCII 源码副本中 `#if 0` 掉实现并注释 `ext.cpp` 绑定；
   - 编译产物 + `gsplat/csrc.py` shim 放在 ASCII 目录（如 `C:\cuda_work`），**不入库**；
   - 本项目 `pipeline/puretorch_splatting/renderer.py` 的 gsplat 分支已适配：线性尺度、`packed=False` 保留 `means2d` 稠密梯度。
   - **2026-11-13 更新（更简单的路径）**：本机已安装标准 **CUDA Toolkit 13.5**（winget `Nvidia.CUDA`，4.71 GB，`nvcc 13.5.37`，
     `CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.5`）。该路径本身是 ASCII，可直接作为 `CUDA_HOME`，
     不必再用 pip 的 `nvidia-cuda-nvcc` 包或 `C:\UEW\...\nvidia\cu13` 间接路径；`torch 2.13.0+cu130` 的 `load_inline`
     CUDA 扩展已实测（编译 79 s、GPU 运行结果正确）。gsplat 源码仍需放 ASCII 副本目录（MSVC 中文路径限制不变）。
3. **UE 渲染独占 GPU**：同一时间只能跑一个 UnrealEditor；脚本有 one-UE + 温度守门（≥80 °C 拒绝启动）。
4. **puretorch 光栅化是 CPU 单线程瓶颈**：960×720/199k splat 约 189 ms/iter；同配置 gsplat 约 4.5 ms/iter（40×）。
5. 本机 RTX 5060 Laptop 8 GB 可跑本项目全部流程；更大场景/更高分辨率建议 16 GB+。
6. 训练默认 4 线程（`DSH_TORCH_THREADS=4`）；4 核以上机器可调大，但本仓库验证均按 4 逻辑核。

## D. 上传前清理说明（本仓库已做）

1. **个人绝对路径**：tracked 文本中 `C:\Users\<user>\...` 已替换为 `<repo>` / `<repo-parent>` / `<user>` 占位符；可执行脚本改为从 `__file__`/`$PSScriptRoot` 推导路径。少数历史证据 JSON 的路径字段因此变为占位符（内容语义不变）。
2. **敏感文件**：已移除引用 `.dsh/.credentials.yaml` 的 3 个本地评审脚本（`kimi_review*.py`，已移出仓库）。
3. **git 历史**：原第二个提交误带入 540 张 v3 原始帧（1.65 GB）。本仓库历史已重建为初始提交 + 一次 agent 文档提交，`git ls-files` ~708 文件 / ~15.8 MB；原 1.5 GB bundle 保留在仓库外作为回滚点。
4. **演示产物**：v4/v5/v6 视频、PLY、渲染帧均在 `.gitignore` 内，上传后不包含；复现见 [QUICKSTART.md](QUICKSTART.md) §6。
5. `report/scene_v3/logs/verify_*.png` 被 v4/v5/v6 合成脚本同名覆盖（各版 mp4 本体未动）。

## E. 明确未验证 / 未完成

- Phase-2 真机：桥未编译、未连接飞控、未飞行；KMZ 是否被 Mini 4 Pro 接受未验证；
- UE 侧 Niagara Path A（真 splat 渲染）单位/尺度未闭环；当前演示用 Path B 点云预览；
- COLMAP 精化位姿未在本仓库实测（仅有真值位姿直通路径）；
- DJI EXIF→COLMAP 转换脚本已有但未做端到端真实样片验证；
- A6–A10 为 scripted 直调；真实 LLM 只在 P1-P3、A1-A5 覆盖；
- 3DGS 重建细节仍偏软（训练视角/迭代受限），非生产级画质。

---

*发现新问题：优先在 `llm_drone/spec` + 测试中落规则（Phase-1），Phase-0 问题记录到本文件与 `pipeline/RESULTS.md`。*
