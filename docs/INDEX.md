# 文档索引（docs/）

> 从 [项目主页](../README.md) 进入；本页按“读者目的”组织全部文档。

## 1. 快速了解项目

| 文档 | 内容 |
|---|---|
| [../README.md](../README.md) | 项目总览、架构、快速开始、验证结果摘要、数据策略 |
| [QUICKSTART.md](QUICKSTART.md) | **从 0 跑通**：基线 / 演示 / 3DGS / UE5 / 常见坑 |
| [RESULTS.md](RESULTS.md) | 全部量化结论与证据索引（可复核） |
| [KNOWN_ISSUES.md](KNOWN_ISSUES.md) | **动手前必读**：规格/代码差异、文档漂移、环境限制 |
| [GITHUB_ABOUT.md](GITHUB_ABOUT.md) | 仓库描述 / topics / 首次发布说明（上传用） |
| [SETUP.md](SETUP.md) | 环境搭建（Python / Ollama / UE5 / 真机前置） |
| [../AGENTS.md](../AGENTS.md) | **AI Agent 权威指南**（仓库地图/基线命令/硬约束/playbook/已知边界） |
| [AGENT_PROMPT.md](AGENT_PROMPT.md) | **复制给其他 Agent 的交接提示词**（中/英） |
| [../llm_drone/README.md](../llm_drone/README.md) | Phase-1 工程使用说明 |
| [../pipeline/README.md](../pipeline/README.md) | Phase-0 3DGS 流水线说明 |
| [../capture/README.md](../capture/README.md) | Phase-0 UE5 合成航拍数据生成说明 |

## 2. Phase-1：LLM Tool-Call 调度无人机

| 文档 | 内容 | 状态 |
|---|---|---|
| [../llm_drone/docs/LLM调度无人机方案与验证报告.md](../llm_drone/docs/LLM调度无人机方案与验证报告.md) | **最终报告**：DJI Mini SDK 使用方法 + LLM 调度方案 + Phase-1 实测 | ✅ |
| [../llm_drone/docs/ACCEPTANCE.md](../llm_drone/docs/ACCEPTANCE.md) | 验收报告：CONTRACT §6 五条验收对照、关键数字、复现命令 | ✅ |
| [../llm_drone/docs/CONTRACT.md](../llm_drone/docs/CONTRACT.md) | 任务契约（架构/工具/安全/验收标准） | ✅ |
| [../llm_drone/spec/PROTOCOL.md](../llm_drone/spec/PROTOCOL.md) | **冻结工程规格**：HTTP API / mission JSON / c2w / 审计 / 安全规则 / 错误码 | ✅ v1.1 |
| [../llm_drone/spec/tools.json](../llm_drone/spec/tools.json) | 15 个 LLM 工具定义（OpenAI function schema） | ✅ |
| [../llm_drone/logs/orchestrator/SUMMARY.md](../llm_drone/logs/orchestrator/SUMMARY.md) | 13/13 场景验收表、失败重试说明、4B 模型适配要点 | ✅ |
| [../llm_drone/msdk_bridge/README.md](../llm_drone/msdk_bridge/README.md) | Phase-2 Android MSDK v5 桥（设计/构建/边界） | ✅ 设计层 |
| [../llm_drone/msdk_bridge/DESIGN.md](../llm_drone/msdk_bridge/DESIGN.md) | 桥接层详细设计（模块/线程/状态机/降级） | ✅ |
| [../llm_drone/msdk_bridge/test_protocol.md](../llm_drone/msdk_bridge/test_protocol.md) | 真机测试协议（24 用例，**本轮未执行**） | ✅ |
| [../llm_drone/msdk_bridge/REVIEW_vs_research.md](../llm_drone/msdk_bridge/REVIEW_vs_research.md) | 与 SDK 调研的 47 项交叉复核（一致/修正/TODO） | ✅ |

## 3. Phase-0：DJI Mini × UE5 × 3DGS 可行性

| 文档 | 内容 |
|---|---|
| [../report/DJI_Mini_UE5_3DGS_可行性验证报告.md](../report/DJI_Mini_UE5_3DGS_可行性验证报告.md) | Phase-0 最终可行性报告 |
| [../report/DJI_Mini_UE5_3DGS_可行性验证_简报.pptx](../report/DJI_Mini_UE5_3DGS_可行性验证_简报.pptx) | 13 页演示简报 |
| [../report/README.md](../report/README.md) | report 目录说明与复现命令 |
| [../pipeline/RESULTS.md](../pipeline/RESULTS.md) / [../capture/RESULTS.md](../capture/RESULTS.md) | 两条子链路实测结果 |
| [../ue5/](../ue5/) | UE5.8 工程、插件、渲染结果 |

## 4. DJI 一手调研（带来源）

| 文档 | 内容 |
|---|---|
| [research/01_DJI_Mini_SDK能力矩阵.md](research/01_DJI_Mini_SDK能力矩阵.md) | 机型分档 / SDK 版本 / 遥控器 / 平台硬约束 |
| [research/02_航拍采集方案对比.md](research/02_航拍采集方案对比.md) | 采集方案对比 |
| [research/03_DJI元数据与位姿先验.md](research/03_DJI元数据与位姿先验.md) | EXIF/XMP 与位姿先验 |
| [research/04_真实DJI样本元数据验证.md](research/04_真实DJI样本元数据验证.md) | 真实样片元数据实测 |
| [research/05_DJI_Terra与生态3DGS能力.md](research/05_DJI_Terra与生态3DGS能力.md) | DJI Terra / 生态 3DGS |
| [research/06_Mini4Pro_3DGS采集SOP.md](research/06_Mini4Pro_3DGS采集SOP.md) | Mini 4 Pro 采集 SOP |
| [research/07_复核_报告第4章差异清单.md](research/07_复核_报告第4章差异清单.md) | 对报告第 4 章的复核与修正清单 |
| [research/08_MSDKv5_Android使用方法.md](research/08_MSDKv5_Android使用方法.md) | **MSDK v5 代码级使用指南** |
| [research/09_MSDKv4_使用方法与Mini2链路.md](research/09_MSDKv4_使用方法与Mini2链路.md) | MSDK v4 / Mini 2 链路 |
| [research/10_KMZ_WPML航线格式与任务下发.md](research/10_KMZ_WPML航线格式与任务下发.md) | KMZ/WPML 航线格式与下发 |
| [research/SUMMARY.md](research/SUMMARY.md) / [research/references.md](research/references.md) | 调研结论速览 / 证据索引 |

## 5. 数据契约与校验

| 文档/脚本 | 内容 |
|---|---|
| [../shared/CONVENTIONS.md](../shared/CONVENTIONS.md) | 数据集 metadata / 3DGS PLY / 坐标系契约 |
| [../shared/VERIFY_CHECKLIST.md](../shared/VERIFY_CHECKLIST.md) | 上游阶段验收清单 |
| [../data/README.md](../data/README.md) | 数据目录说明与重新生成命令 |
| [../data/samples/README.md](../data/samples/README.md) | 仓库内小样例说明 |

## 6. 图片素材

| 文件 | 内容 |
|---|---|
| [assets/p1_mission_contact_sheet.jpg](assets/p1_mission_contact_sheet.jpg) | P1 真实 LLM 任务的 UE5 渲染 20 帧拼图 |
| [assets/mission16_contact_sheet.jpg](assets/mission16_contact_sheet.jpg) | 16 帧 Mission 样例渲染拼图 |
| [assets/phase0_ue_vs_reference.jpg](assets/phase0_ue_vs_reference.jpg) | Phase-0 UE5 渲染 vs 参考图 |
| [assets/capture_contact_sheet.jpg](assets/capture_contact_sheet.jpg) | Phase-0 合成航拍五向倾斜摄影拼图 |
| [assets/sdk_tiers.jpg](assets/sdk_tiers.jpg) | DJI Mini 机型/SDK 分档图 |
