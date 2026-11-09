# Phase-1 验收报告（Lead 独立核验）

> 日期：2026-11-08 ｜ 验收人：Team Lead ｜ 对象：`llm_drone/` Phase-1（仿真 + UE5，无真机）
> 结论：**CONTRACT §6 五条验收标准全部通过**（第 5 条为"设计层通过、真机未执行"，如实标注）。

## 1. 验收方法（三条独立证据链，互不复用实现）

| 证据链 | 方法 | 结果 | 证据文件 |
|---|---|---|---|
| A. Lead 黑盒 HTTP 验收 | 独立脚本只走 HTTP（不 import 被测代码），自起 sim server（端口 8766/8767） | **27/27 PASS** | `llm_drone/logs/lead/acceptance_20261108_221327.{json,md}` |
| B. 单元/集成测试 | 全仓 unittest（sim/safety/orchestrator/geo） | **Ran 118 tests, OK** | 命令见 §4；`logs/drone-sim/`、`logs/orchestrator/SUMMARY.md` |
| C. 真实 LLM 演示 run | 真实 drone-sim + Ollama qwen3.5:4b + spec §12 run 目录 | **13/13 场景 PASS** | `llm_drone/demo/runs/`；`logs/orchestrator/SUMMARY.md` |

## 2. CONTRACT §6 验收对照

| # | 验收标准 | 结论 | 关键证据 |
|---|---|---|---|
| 1 | 自然语言→LLM 多轮工具调用→规划→安全校验→仿真执行→遥测/照片回传，全程可复现 | ✅ 通过 | P1/P2/P3 真实 LLM run（`20261108_220309_P1`、`20261108_220829_P2`、`20261108_220729_P3`）；`run_demo` 一条命令复现；报告 §6.2 |
| 2 | ≥3 正向 + ≥5 对抗被安全层正确处理 | ✅ 通过 | 3 正向（20/12/5 张照片）+ 10 对抗全部正确；`tests/safety` 45 tests；Lead 27/27（A1–A10 全覆盖）；报告 §6.3 |
| 3 | 一次完整任务审计 JSONL + transcript + 指标 | ✅ 通过 | 每个 run 十件套（transcript/llm_events/tool_calls/agent_audit/metrics 等）；Agent 审计 JSONL 逐行可解析；报告 §6.4 |
| 4 | UE5 虚拟相机按 mission 渲染 ≥12 图 + metadata（可接 3DGS） | ✅ 通过 | `data/synthetic/mission/`（16 帧）+ `data/synthetic/mission_p1/`（P1 真实 LLM 任务 20 帧）；`validation.json`/`validation_p1.json` ok=true；`pipeline` 加载 16/20 views；报告 §6.5 |
| 5 | MSDK v5 桥接口映射 + 真机测试协议 + 代码骨架可审阅 | ✅ 设计层通过（真机未执行） | `llm_drone/msdk_bridge/`：README/DESIGN/app(23 Kotlin)/mapping.json(v1.1)/PROTOCOL_COMPLIANCE/test_protocol/REVIEW_vs_research；未编译/未真机已明确标注；报告 §6.6 |

## 3. 关键数字

| 项目 | 数值 |
|---|---|
| 正向场景（真实 LLM） | 3/3 PASS：P1=20 张、P2=12 张、P3=5 张；llm_calls 7/5/5；tool_calls 4/4/4；wall 24.8/37.0/32.2 s |
| 对抗场景 | 10/10 正确处理：A1–A5 真实 LLM 触发；A6–A10 scripted 直调（标注） |
| 演示 run 目录 | 25 个（13 个最终 PASS + 12 个失败重试过程 run，全部保留） |
| Lead 黑盒验收 | 27 项检查全部 PASS（含正向链路 + A1–A10 + 审计字段） |
| 单元测试 | 118 tests OK（sim 21 + safety 45 + orchestrator 42 + 兼容 geo 10） |
| UE5 渲染 | 16 帧样例（0.2446 s/帧）+ 20 帧真实 LLM 任务（0.2303 s/帧）；1600×1200；c2w/GPS/云台误差 0 |
| 3DGS 兼容 | `dataset.load_dataset`：mission=16 views、mission_p1=20 views（kind=conventions，含图像） |
| MSDK 桥 | 23 Kotlin 文件 + mapping 15/15 工具 + 47 项交叉复核（一致 24/已修 16/TODO 7）；未编译未真机 |

## 4. 复现命令

```powershell
cd dji_ue5_3dgs\llm_drone
# 1) 仿真 Agent
python -m sim.server --port 8765 --time-scale 20
# 2) 演示（真实 LLM；A6-A10 自动 scripted）
python -m orchestrator.run_demo --agent-url http://127.0.0.1:8765 --scenario all --out demo/runs
# 3) 全量单测
python -m unittest discover -s tests -v
# 4) Lead 黑盒验收
python logs\lead\verify_acceptance.py --port 8766
# 5) UE5 校验（产物已存在）
python ue5_mission\validate_output.py --out ..\data\synthetic\mission
python ue5_mission\validate_output.py --out ..\data\synthetic\mission_p1
```

## 5. 未完成/未验证项（如实列出）

1. **真机零执行**：MSDK v5 桥未编译、未连接飞控、未飞行；KMZ/WPML 是否被 Mini 4 Pro 接受为最高风险未验证项（`msdk_bridge/test_protocol.md` 已定义 T0–T4 真机门禁）；
2. **A6–A10 为脚本化验证**：非真实 LLM 触发；但 Agent 单测与 Lead 黑盒验收独立覆盖相同错误码；
3. **真实 LLM 依赖工程辅助**：qwen3.5:4b 需要 num_ctx=16384 + 阶段感知续跑提醒 + 只读熔断；更大模型的稳定性未系统评测；
4. **UE5 为仿真场景数据**：证明数据/坐标/契约链路，不等价于真机航拍质量；
5. **docs/research/08/09 仍有少量 TODO(未确认)**（官方 API 站未收录的枚举/构造器签名，共 20 处 / 08+09），不影响本方案结论。

## 6. 证据索引

| 类别 | 路径 |
|---|---|
| 最终报告 | `llm_drone/docs/LLM调度无人机方案与验证报告.md` |
| 冻结规格 | `llm_drone/spec/{PROTOCOL.md,tools.json,sample_mission.json}` |
| 正向证据 | `llm_drone/demo/runs/20261108_220309_P1/`、`..._220829_P2/`、`..._220729_P3/` |
| 对抗证据 | `llm_drone/demo/runs/20261108_221237_A1/` 等 A1–A10；`logs/orchestrator/SUMMARY.md` §2 |
| 黑盒验收 | `llm_drone/logs/lead/acceptance_20261108_221327.{json,md}` |
| 单测日志 | `llm_drone/logs/drone-sim/selftest_*.log`、`logs/orchestrator/SUMMARY.md` §6 |
| UE5 产物 | `data/synthetic/mission/`、`data/synthetic/mission_p1/`、`ue5_mission/results/validation*.json` |
| MSDK 桥 | `llm_drone/msdk_bridge/`（含 REVIEW_vs_research.md） |
| SDK 调研 | `docs/research/08`（MSDK v5）、`09`（v4）、`10`（KMZ/WPML）、`01`（能力矩阵） |

*验收脚本可复跑；所有数字均可在对应 JSON/日志中复核。*
