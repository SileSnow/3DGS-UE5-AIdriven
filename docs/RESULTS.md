# RESULTS — 量化结论与证据索引

> 原则：每个数字都能回溯到仓库内的文件；没有落盘证据的数字不写。
> 大体积产物（数据 / PLY / 视频 / 渲染帧）不入库，只保留“命令 + 指标 + 小样例”。

## 1. Phase-1：LLM 安全调度无人机

| 结论 | 数字 | 证据 | 复核命令 |
|---|---|---|---|
| 演示场景 | **13/13 PASS** | `llm_drone/demo/runs/`（25 run = 13 PASS + 12 历史失败重试） | `python llm_drone/logs/orchestrator/_verify_runs.py` → `ALL_OK True` |
| Lead 独立黑盒验收 | **27/27 PASS** | `llm_drone/logs/lead/acceptance_20261108_221327.json` | `python llm_drone/logs/lead/verify_acceptance.py --port 8766` |
| 单元测试 | **118 tests OK** | `llm_drone/tests/` | `cd llm_drone && python -m unittest discover -s tests -v` |
| 真实 LLM 正向 | P1/P2/P3 分别拍 **20 / 12 / 5** 张，0 拒绝 | `demo/runs/20261108_2203xx_P1` 等 metrics.json | 读 `metrics.json` 的 `mode=real_llm` |
| 真实 LLM 对抗 | A1–A5 由真实 LLM 触发 `E_ALT_LIMIT / E_GEOFENCE / E_NOFLY / E_BATTERY_TAKEOFF / E_CONFIRM_REQUIRED` | `demo/runs/20261108_2212xx_A*` | 同上 |
| scripted 对抗 | A6–A10（force_rth / E_GPS / E_RC_LINK / E_PARAM_RANGE+E_UNKNOWN_TOOL / E_REAL_NOT_AVAILABLE） | `demo/runs/*_A6..A10`、`demo/scenarios.json` | 场景文件 `mode: scripted` 标注 |
| UE5 任务渲染 | 16 帧样例 + 20 帧真实 LLM 任务（1600×1200） | `llm_drone/ue5_mission/results/validation*.json` | `python llm_drone/ue5_mission/validate_output.py --out <data>` |
| MSDK v5 桥 | 23 Kotlin / 15 工具映射 / 24 用例协议（未编译、未飞） | `llm_drone/msdk_bridge/` | 文档复核 |

## 2. Phase-0：DJI Mini × UE5 × 3DGS

| 结论 | 数字 | 证据 |
|---|---|---|
| 合成航拍数据集 | 175 train + 15 val @1600×1200，fx=fy=1148.34 | `data/synthetic/capture/`（本地）、`capture/RESULTS.md`、`logs/capture/`（本地） |
| 3DGS 训练 | 109,376 splat / 3000 iter / val PSNR 13.28 / 峰值显存 1.15 GB | `data/trained/capture/run1/metrics.json`（本地）、`pipeline/RESULTS.md` |
| UE5 插件 | 编译 Succeeded（3 个 DLL）；Path B 109k splat 30.8 fps @1280×720；Path A 未闭环 | `ue5/RESULTS.md`、`ue5/results/final_v2/`（本地） |
| 交付报告 | 68 KB 报告 / 13 页 PPTX / 5 图 / 4 条视频（视频本地） | `report/` |

## 3. 3DGS 演示片 v4 → v6（同一 v3 场景、同一任务 91 拍点）

| 指标 | v4 | v5 | **v6** |
|---|---|---|---|
| 后端 | puretorch | puretorch | **gsplat** |
| 迭代 | 3,000 | 10,000 | **40,000** |
| 训练视角 | 83 任务帧 | 83 + 168 斜视 = 251 | 同左 |
| 训练分辨率 | 640×480 | 640×480 | **960×720** |
| splat 数 | 54,812 | 54,812 | **199,298** |
| val PSNR / SSIM（训练分辨率） | 13.92 / 0.43* | 13.30 / 0.43 | **16.62 / 0.61** |
| val PSNR / SSIM（1600×1200） | — | 12.34 / 0.47 | **16.34 / 0.65** |
| 峰值显存 | 1.12 GB | 1.12 GB | **260 MB** |
| 每 iter（960×720/199k splat） | — | 189 ms（640×480/199k） | **4.5 ms** |
| 演示视频 | `report/..._v4.mp4`（本地） | `..._v5.mp4`（本地） | `..._v6.mp4`（本地） |

> *v4 的 val 是“仅任务帧”验证集，与 v5/v6 的 20 帧混合验证集口径不同，不可直接横比。
> 复现命令与数据构造见 [QUICKSTART.md](QUICKSTART.md) §6；v6 全过程记录见本地 `report/scene_v3/RERUN_GSPlat_V6_20261112.md`。

## 4. 证据分层（哪些在仓库内、哪些要本地生成）

| 类型 | 在仓库 | 说明 |
|---|---|---|
| Phase-1 demo 十件套、验收 JSON、单测 | ✅ | 体积小，可直接复核 |
| Phase-0 报告 / PPTX / 图表 / 小样例 | ✅ | 报告为最终版；图表 < 200 KB |
| 合成数据集 / PLY / 渲染帧 / 视频 | ❌ | 体积大，按命令本地生成 |
| 运行日志 / 审计 JSONL / 训练日志 | ❌ | `.gitignore` 排除，避免仓库膨胀 |

## 5. 如何判断“结论是否可信”

1. 找数字对应的落盘文件（上表“证据”列）；
2. 用“复核命令”重跑一次（单测 / 验收 / `_verify_runs.py`）；
3. 若文件不在仓库（大数据），按 QUICKSTART 的命令重新生成并对照 `RESULTS.md`；
4. 文档与代码冲突时：以 `llm_drone/spec/PROTOCOL.md`（冻结规格）与代码为准，并参考 [KNOWN_ISSUES.md](KNOWN_ISSUES.md)。
