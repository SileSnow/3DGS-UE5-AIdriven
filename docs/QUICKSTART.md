# QUICKSTART — 从 0 跑通这个仓库

> 目标：30 分钟内跑通基线、看到一个确定性无人机任务、跑一次 3DGS 训练；再按需进入 UE5 与 v6/gsplat 复现。
> 先读：[README.md](../README.md)（项目是什么）、[KNOWN_ISSUES.md](KNOWN_ISSUES.md)（已知坑）。

## 0. 环境矩阵

| 用途 | 需要 | 本项目实测 |
|---|---|---|
| Phase-1 单测 / demo / 验收 | Python 3.12+（标准库，零第三方依赖） | Python 3.14.6 / Windows 11 |
| 真实 LLM demo | Ollama + `qwen3.5:4b`（可选） | 本机 Ollama，`num_ctx=16384` |
| 3DGS 训练（puretorch） | pipeline venv（torch 2.13+cu130、numpy、Pillow） | RTX 5060 Laptop 8 GB |
| 3DGS 训练（gsplat，可选） | CUDA 工具链（见 §6）+ gsplat 1.5.3 | CUDA 13.5（pip 包） |
| UE5 渲染 / 插件 | UE 5.8.4（Epic 安装）、NVIDIA GPU、ASCII 路径 | UE 5.8.4 + `C:\UEW` junction |

## 1. 基线（3 分钟，必做）

```powershell
cd dji_ue5_3dgs/llm_drone
python -m unittest discover -s tests -v            # 期望：Ran 118 tests ... OK（约 15 s）
python logs\lead\verify_acceptance.py --port 8766  # 期望：27/27 PASS（脚本自动起仿真 Agent）
```

若失败：先看 [docs/SETUP.md](SETUP.md) 与 [KNOWN_ISSUES.md](KNOWN_ISSUES.md)，不要假设环境正常。

## 2. 确定性无人机 demo（不需要 LLM）

```powershell
cd dji_ue5_3dgs/llm_drone
# 终端 A：仿真无人机（127.0.0.1:8765，20 倍时间加速）
python -m sim.server --port 8765 --time-scale 20

# 终端 B：P1 网格航拍（预置工具序列，可离线复现）
python -m orchestrator.run_demo --agent-url http://127.0.0.1:8765 --scenario P1 --scripted-for P1 --out demo/runs
```

产物在 `llm_drone/demo/runs/<run_id>/`：request / transcript / llm_events / tool_calls / audit / mission / mission_record / photos_metadata / metrics / summary（“十件套”）。

## 3. 真实 LLM demo（可选）

```powershell
# 1) 启动 Ollama 并拉模型
ollama serve
ollama pull qwen3.5:4b
# 2) 验证工具调用能力（需要显式 num_ctx，否则默认 4096 会截断多轮工具结果）
python -m orchestrator.llm_client --probe
# 3) 跑全部场景（P1-P3 真实 LLM；A1-A5 真实 LLM 触发拒绝；A6-A10 默认 scripted）
python -m orchestrator.run_demo --agent-url http://127.0.0.1:8765 --scenario all --out demo/runs
```

没有 Ollama 就用 `--scripted-for <场景>` 做确定性演示；**不要**把 scripted 结果当成“真实 LLM 能力”证据。

## 4. 复核已有证据（不重跑）

```powershell
cd dji_ue5_3dgs/llm_drone
python logs/orchestrator/_verify_runs.py   # 13 个最终 run 十件套齐全、error_codes 对齐 → ALL_OK True
# 黑盒验收的历史 JSON
Get-Content logs\lead\acceptance_20261108_221327.json | ConvertFrom-Json | Select checks_total,checks_passed,passed
```

## 5. 3DGS 训练（最小样例，不需要 UE）

```powershell
cd dji_ue5_3dgs
pipeline\setup_env.ps1          # 建 pipeline\.venv（torch/numpy/Pillow 等；详见 pipeline/ENV.md）
pipeline\.venv\Scripts\python.exe pipeline\03_train_3dgs.py ^
  --data data/samples/synthetic_campus_v1 --out data/trained/sample_campus/run1 ^
  --iters 1500 --res-scale 0.5 --backend puretorch
# 评估 + 导出 PLY
pipeline\.venv\Scripts\python.exe pipeline\05_eval.py --run data/trained/sample_campus/run1 --val data/samples/synthetic_campus_v1 --res-scale 0.5
```

全量合成数据集需要 UE 渲染：`capture\run_capture.ps1 -Mode full`（175+15 帧，~900 MB）。

## 6. v4–v6 演示片复现（进阶，需本机大文件）

v4/v5/v6 的流程一致，只是数据源与后端不同：

```powershell
cd dji_ue5_3dgs
# (a) UE5 渲染 91 帧 LLM 任务（v3 场景）——需要 C:\UEW junction + UE 5.8.4
powershell -ExecutionPolicy Bypass -File .\llm_drone\ue5_mission\run_mission.ps1 ^
  -Mission llm_drone/demo/mission_grid_campus.json -Out data/synthetic/mission_llm_v3 ^
  -Sun 18 -Exposure 0.55 -ExtraArgs "--scene-detail v3 --gpu-duty 0.25"
# (b) 斜视帧 + 数据集合并
powershell -ExecutionPolicy Bypass -File .\report\scene_v3\run_oblique_v3.ps1 -Out data/synthetic/oblique_v3 -Count 180 -GpuDuty 1.0
python report\scene_v3\build_combined_dataset.py --oblique-val 12 --force
# (c) 训练：puretorch（v5）或 gsplat（v6，需 CUDA 工具链）
$env:DSH_TORCH_THREADS='4'
pipeline\.venv\Scripts\python.exe -m pipeline.03_train_3dgs --data data/synthetic/mission_v3_plus_oblique ^
  --val data/synthetic/mission_v3_plus_oblique/val --out data/trained/mission_v3_gsplat/run1 ^
  --iters 40000 --res-scale 0.6 --backend gsplat --gpu-duty 1.0
# (d) UE5 加载 PLY（Path B 点云预览）+ 合成视频
powershell -ExecutionPolicy Bypass -File .\ue5\Scripts\run_headless.ps1 -Ply C:/UEW/dji_ue5_3dgs/data/trained/mission_v3_gsplat/run1/gaussians_best.ply -OutDir C:/UEW/dji_ue5_3dgs/ue5/results/gsplat_v3_pathb -Warmup 2 -Measure 2 -Shots 0 -SortIters 2 -NoNiagara 1 -DebugPoints 1 -ViewportShots 4 -Exposure 1
python report\scene_v3\compose_ue_pathb_v3.py --dir ue5/results/gsplat_v3_pathb
python report\scene_v3\make_flight_video_v6.py
```

> gsplat 的安装/编译坑较多（中文路径、MSVC 预处理器、CUDA 13.5 模板符号），完整步骤见 [KNOWN_ISSUES.md](KNOWN_ISSUES.md) §C 与 `report/scene_v3/RERUN_GSPlat_V6_20261112.md`（本地证据，不入库）。

## 7. UE5 侧（Phase-0）

```powershell
cd dji_ue5_3dgs
# 中文路径必须建 ASCII junction（管理员或普通用户均可）
cmd /c mklink /J C:\UEW C:\Users\<you>\...\dji_ue5_3dgs_parent
capture\run_capture.ps1 -Mode full          # 合成航拍数据集（GPU 独占，串行）
pwsh -File ue5\Scripts\build.ps1            # 编译 UE5.8 插件（约 2–3 分钟）
pwsh -File ue5\Scripts\run_headless.ps1 -Ply <your.ply>   # 载入 PLY 出截图/metrics
```

细节：`capture/README.md`、`ue5/README.md`、`docs/SETUP.md`。

## 8. 常见坑（按出现频率）

| 现象 | 原因 / 处理 |
|---|---|
| 真实 LLM 多轮后空响应 | Ollama 默认 `num_ctx=4096` 截断；必须传 `num_ctx=16384`（或 `OLLAMA_CONTEXT_LENGTH=16384`） |
| UE 启动报 C1083 / 路径找不到 | 中文路径必须走 `C:\UEW` junction；脚本会自动映射 |
| `gsplat: No CUDA toolkit found` | 需要 CUDA 工具链；见 §6 与 KNOWN_ISSUES §C |
| 训练很慢（>100 ms/iter） | puretorch 是 CPU 单线程瓶颈；换 gsplat 可到 ~4.5 ms/iter |
| 验收脚本端口占用 | 用 `--port 87xx` 换端口；脚本自己起/收 Agent |
| git 里有大文件 | 已用 `.gitignore` 排除 data/、report 视频等；详见 README §9 |

## 9. 给 Agent 的 60 秒上手

1. 读 `AGENTS.md`（权威）与 `docs/KNOWN_ISSUES.md`；
2. 跑基线：`cd llm_drone && python -m unittest discover -s tests -v`（118 OK）与 `python logs/lead/verify_acceptance.py --port 8766`（27/27）；
3. 输出“当前状态 + 计划（≤8 行）”，再开始最小改动；
4. 改协议/工具/安全阈值/真机文档前**先问人**。
