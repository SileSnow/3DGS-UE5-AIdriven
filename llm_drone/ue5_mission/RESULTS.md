# ue5_mission RESULTS — Mission JSON → UE5 航拍渲染实测结果与证据

> 更新：2026-11-08 22:10（Asia/Shanghai）。本文件记录 **spec v1.0 交付**（sample_mission 16 帧）与
> **P1 集成证据**（orchestrator 真实任务 m-001 → `data/synthetic/mission_llm`，91 帧，见 §8）。
> 所有数字都能在 `llm_drone/logs/ue5-mission/`、`llm_drone/ue5_mission/results/validation*.json` 找到原始出处。
> 补充：Lead 已独立核验本产物（16 张 1600×1200、非黑、c2w/GPS/gimbal 真值误差 0、contact_sheet 目视正确），
> 并用上游 `pipeline/.venv` 的 `dataset.load_dataset('data/synthetic/mission')` 成功加载 16 views+图像
> （kind=conventions）→「可接 3DGS 训练」已由 Lead 独立证明。

## 1. 最终交付数据（spec sample_mission，16 帧）

| 项 | 值 |
|---|---|
| 输入 mission | `llm_drone/spec/sample_mission.json`（`sample-grid-16`，16 个 `action=photo` 航点，v1 schema） |
| 任务几何 | 4×4 网格，±28 m（UE x∈[-2800,2800] cm、y∈[-2800,2800] cm），航高 40 m（z=4000 cm），云台 -45°，heading 0/180 → UE yaw -90/90 |
| 输出 | `data/synthetic/mission/images/0001-0016.png`（**16 帧**，1600×1200）+ `metadata.json` + `poses_mission.json` |
| 分辨率 / 格式 | 1600×1200 PNG（RGBA8 RenderTarget → PNG），单帧 2.24–3.09 MB，合计 **45.22 MB** |
| 内参 | fx = fy = **1148.3429 px**，cx = 800.0，cy = 600.0（FOV_h=69.7265°、FOV_v=55.1734°，与 capture 完全一致） |
| 坐标系 | `UE_LHS_Zup_cm`；c2w = 4×4 行主序，列 = forward/right/up（UE 相机轴），平移 cm |
| 模拟 GPS | 原点 39.9042 / 116.4074 / 43 m；UE +X=东、+Y=南、+Z=天；帧 GPS alt = 83.0 m |
| 帧时间戳 | 0.0–63.5 s（按航点速度 5 m/s 巡航 + 每拍照点 0.5 s 悬停的仿真任务时间） |
| 元数据 | `metadata.json` 19,688 B（16 帧）；`poses_mission.json` 14,769 B |
| 渲染参数 | Exposure 0.6，Sun 22 lux（与 capture 最终数据一致），场景 seed 20261108，805 actors |

## 2. 渲染运行记录（UE 5.8.4，一次只开一个 UE，4 核限载）

命令（`llm_drone/ue5_mission/run_mission.ps1`）：

~~~powershell
cd C:\UEW\dji_ue5_3dgs
powershell -ExecutionPolicy Bypass -File llm_drone\ue5_mission\run_mission.ps1 ^
    -Mission llm_drone\spec\sample_mission.json -Out data\synthetic\mission -Exposure 0.6 -Sun 22
~~~

| 项 | 值 |
|---|---|
| UE 进程总耗时 | **80.5 s**（冷启动：编辑器启动+退出 ≈73 s；脚本返回后 PythonScriptPlugin 自动 QUIT_EDITOR） |
| 脚本内总耗时 | **7.32 s** |
| 其中：场景生成 | 3.328 s（805 actors，2 母材质同步编译） |
| 其中：相机 rig | 0.064 s（1600×1200、FOV 69.726°、fx=fy=1148.3429） |
| 其中：渲染 | 16 帧 / **3.913 s**（avg **0.2446 s/帧**） |
| CPU / GPU 始温 | 56.9 °C / 42.8 °C（远低于 80 °C 阈值） |
| 4 核限载 | `applied affinity=0x000F priority=BelowNormal`（BelowNormal） |
| 引擎版本 / UE python | 5.8.4-58902052+++UE5+Release-5.8 / 3.11.8 |
| c2w 与 capture 公式交叉校验 | **max diff = 0.0** |
| 编辑器自动退出 | 是（日志尾部 `[SYNTH] DONE elapsed=7.3s`，无残留进程） |

## 3. 离线验收校验（`python llm_drone/ue5_mission/validate_output.py --out data/synthetic/mission`）

结果文件：`llm_drone/ue5_mission/results/validation.json`（**ok = true**），
缩略图拼图：`llm_drone/ue5_mission/results/contact_sheet.png`（16 帧 4×4，带帧号）。

**结论：17 项 checks = 16 PASS / 0 FAIL / 1 SKIP；4 条 WARN（预期几何现象，不影响结论）。**

| 检查 | 结果 | 证据 |
|---|---|---|
| PNG 数量 ≥12 且 = metadata 帧数 | PASS | 16 / 16 |
| 分辨率 1600×1200 | PASS | 全部 16 张 |
| 非黑（亮度均值 >5 且方差 >100，0–255 全图口径） | PASS | 亮度均值最小 **96.738**、方差最小 **3802.744**、p95 最大 231.0 |
| 图像互不相同（md5） | PASS | 16 个唯一 md5 |
| metadata schema（CONVENTIONS + PROTOCOL §7.3） | PASS | 顶层/每帧必需键齐全，`coord_system=UE_LHS_Zup_cm` |
| 内参与 mission camera / capture 相机模型一致 | PASS | fx=fy=1148.3429、cx=800、cy=600 |
| 与 capture 常量直接对比 | **SKIP** | `skipped: unreal unavailable (ModuleNotFoundError: No module named 'unreal')`——系统 python 无法导入 UE 模块，按设计记 SKIP 不判 FAIL |
| c2w 正交性 `||R Rᵀ−I||<1e-6` + det=+1 + 底行 | PASS | max err **0.0** |
| GPS 往返（c2w 平移 → WGS84 → UE cm <0.05 cm） | PASS | max **0.0 cm** |
| gimbal 与 heading 对应（yaw==heading−90、pitch==gimbal_pitch、roll=0） | PASS | max err **0.0°** |
| 与 mission 独立重算真值对比（c2w/GPS/timestamp/waypoint） | PASS | max c2w diff **0.0**、GPS 0、timestamp 0 |
| 时间戳单调 | PASS | 0.0→63.5 s |
| 相机几何（图像中心视线落在 400 m 地面内 / 相机高度 40 m） | PASS + 4 WARN | 4 个“前视”角点（0004/0008/0012/0016）中心视线落点在 mission 足迹+25 m 外、但仍在 400 m 地面内——-45° 前视相机的正常几何，不是渲染错误 |
| 运行摘要一致（帧数/曝光/太阳/耗时） | PASS | run_sample-grid-16_*.json：16 帧、7.32 s、0.6/22 lux |
| contact_sheet 生成 | PASS | results/contact_sheet.png |

## 4. 与上游 3DGS 流水线兼容性（只读加载，不训练）

~~~powershell
pipeline\.venv\Scripts\python.exe pipeline\dataset.py --data data\synthetic\mission --scale 0.5
~~~

实测输出（节选）：

~~~
kind=conventions world=ue_rh_cm n_views=16 size=800x600
scene: {"center": [0, 0, 4000], "extent": 5902.9, "n_views": 16, ...}
view0 name=images/0001.png K=[[574.17,0,399.75],[0,574.17,299.75],[0,0,1]]
R_cw=[[1,0,0],[-0.7071,0,-0.7071],[0.7071,0,-0.7071]]  t_cw=[2800.00, 848.53, 4808.33]
~~~

=> metadata.json 被识别为 CONVENTIONS 数据集，16 视角全部加载，c2w 成功转 COLMAP 位姿，
可直接作为 `03_train_3dgs.py --data data/synthetic/mission` 的输入（正式训练由 gs-pipeline 负责）。
Lead 也用 `dataset.load_dataset` 独立复验通过（16 views + 图像）。

## 5. 复现命令

~~~powershell
cd C:\UEW\dji_ue5_3dgs

# 1) 离线干跑：mission -> 渲染计划（不启动 UE）
python ./llm_drone/ue5_mission/mission_io.py --mission ./llm_drone/spec/sample_mission.json --out ./llm_drone/ue5_mission/results

# 2) 启动命令行自检（不启动 UE）
powershell -ExecutionPolicy Bypass -File ./llm_drone/ue5_mission/run_mission.ps1 -DryRun

# 3) 正式渲染（先报备/确认没有别的 UE；4 核限载 + 温度预检由脚本强制）
powershell -ExecutionPolicy Bypass -File ./llm_drone/ue5_mission/run_mission.ps1 -Mission llm_drone/spec/sample_mission.json -Out data/synthetic/mission -Exposure 0.6 -Sun 22

# 4) 离线验收校验
python ./llm_drone/ue5_mission/validate_output.py --out data/synthetic/mission

# 5) 3DGS 训练（可选，gs-pipeline 负责）
pipeline\.venv\Scripts\python.exe pipeline\03_train_3dgs.py --data data/synthetic/mission --out data/trained/mission/run1 --iters 1500 --res-scale 0.4
~~~

## 6. 与验收标准对应

| 验收项（CONTRACT §6.4 / PROTOCOL §13 #4） | 状态 | 证据 |
|---|---|---|
| UE5 虚拟相机按 mission 渲染 ≥12 图 | ✅ | 16 张 PNG（spec sample_mission） |
| **P1**：真实 LLM demo mission（m-001，91 拍照点）渲染 | ✅ | **91 张 PNG + 8 val**（`data/synthetic/mission_llm/`，`validation_mission_llm.json` ok=true） |
| 真值 metadata（c2w/GPS/云台/时间戳，可接 3DGS） | ✅ | metadata.json；c2w 正交误差 0；GPS 往返 0；pipeline 加载 16 views |
| 图像正常（非全黑） | ✅ | 亮度均值最小 96.7/255、方差最小 3802.7；contact_sheet 与 0001/0008 目视确认 |
| 离线校验（c2w/GPS/gimbal/帧数/schema） | ✅ | results/validation.json ok=true（16 PASS/0 FAIL/1 SKIP/4 WARN） |
| README 可复现 | ✅ | README §4 + 本文 §5 |
| 机器安全（一次一个 UE / 4 核限载 / 温度） | ✅ | affinity 0x000F + BelowNormal；冷启动 56.9/42.8 °C；无残留 UE 进程 |

## 7. 证据索引

| 内容 | 路径 |
|---|---|
| UE stdout 渲染日志（[SYNTH] 行） | `llm_drone/logs/ue5-mission/ue_mission_20261108_215343.log` |
| 引擎日志副本 | `llm_drone/logs/ue5-mission/ue_engine_20261108_215343.log` |
| 启动脚本结论 JSON | `llm_drone/logs/ue5-mission/run_20261108_215343.json`（80.5 s、16 帧、温度、命令行） |
| 渲染器摘要 JSON（timing/per-frame/c2w diff） | `llm_drone/logs/ue5-mission/run_sample-grid-16_20261108_215445.json` |
| 离线校验报告 | `llm_drone/ue5_mission/results/validation.json` |
| 缩略图拼图 | `llm_drone/ue5_mission/results/contact_sheet.png` |
| 渲染计划/位姿全量 | `data/synthetic/mission/poses_mission.json`、`llm_drone/ue5_mission/results/mission_plan.json` |
| **P1** UE 渲染日志 | `llm_drone/logs/ue5-mission/ue_mission_20261108_215534.log`（含 `[SYNTH] SUMMARY`，91 帧） |
| **P1** 启动脚本结论 | `llm_drone/logs/ue5-mission/run_20261108_215534.json`（74.5 s、91 帧、温度、命令行） |
| **P1** 渲染器摘要（timing/per-frame/c2w diff） | `llm_drone/logs/ue5-mission/run_m-001_20261108_215639.json` |
| **P1** 离线校验报告（91 帧） | `llm_drone/ue5_mission/results/validation_mission_llm.json`、`data/synthetic/mission_llm/validate_report.json` |
| **P1** 缩略图拼图（91 帧） | `llm_drone/ue5_mission/results/contact_sheet_mission_llm.png` |
| **P1 real-LLM** UE 渲染日志（20 帧） | `llm_drone/logs/ue5-mission/ue_mission_20261108_220429.log` |
| **P1 real-LLM** 启动脚本结论 | `llm_drone/logs/ue5-mission/run_20261108_220429.json`（46.3 s、20 帧、温度、命令行） |
| **P1 real-LLM** 渲染器摘要 | `llm_drone/logs/ue5-mission/run_plan-acd562c360_*.json` |
| **P1 real-LLM** 离线校验报告 / 缩略图 | `llm_drone/ue5_mission/results/validation_p1.json`、`results/contact_sheet_p1.png` |
| 历史原型日志（17:22–17:28 首渲与原型，旧脚本） | `llm_drone/logs/ue5-mission/archive_prototype/` |

## 8. P1 集成证据：真实 LLM demo mission m-001（`data/synthetic/mission_llm`，91 帧）

> orchestrator 产出的真实任务 `llm_drone/demo/mission_grid_campus.json`（mission_id=m-001、pattern=grid、
> **91 个拍照航点**）经本工具渲染为独立数据集 `data/synthetic/mission_llm/`，用于证明
> **LLM 规划 → mission JSON → UE5 虚拟无人机拍摄** 闭环；spec 交付数据集 `data/synthetic/mission/`（16 帧）保持不变。

### 8.1 交付数据

| 项 | 值 |
|---|---|
| 输入 mission | `llm_drone/demo/mission_grid_campus.json`（`m-001`，source_format=orchestrator-demo，n_photos=91） |
| 输出（训练/任务） | `data/synthetic/mission_llm/images/0001-0091.png`，**91 帧** 1600×1200 |
| 输出（留出验证） | `data/synthetic/mission_llm/val/images/val_0001-0008.png`，**8 帧** + `metadata_val.json`(8,286 B) |
| 元数据 | `metadata.json` 88,720 B（91 帧，`mission` 块含 plan_id/source_format/n_photos/flight/scene）；`poses_mission.json` 75,198 B |
| 磁盘占用 | `data/synthetic/mission_llm` = **255.68 MB**（99 PNG + 3 JSON） |
| 任务几何 | x ∈ [−6000, 6000] cm、y ∈ [−6976, 6000] cm、z = 5000 cm（alt_rel 50 m）；gimbal pitch **−90°（nadir 正下）**；heading 90°（DJI yaw 90 → UE yaw 0） |
| 内参 / 坐标系 | fx=fy=**1148.3429**、cx=800、cy=600；`UE_LHS_Zup_cm`；c2w 列 = forward/right/up，cm |
| 帧时间戳 | 0.0–382.9 s（orchestrator 仿真任务时间，按 5 m/s 巡航 + 拍照悬停） |
| 渲染参数 | Exposure 0.6、Sun 22 lux、场景 seed 20261108、805 actors（与 capture 最终数据一致） |

### 8.2 渲染运行记录（现行工具链，2026-11-08 21:55–21:56）

~~~powershell
cd C:/UEW/dji_ue5_3dgs
powershell -ExecutionPolicy Bypass -File ./llm_drone/ue5_mission/run_mission.ps1 -Mission llm_drone/demo/mission_grid_campus.json -Out data/synthetic/mission_llm -Exposure 0.6 -Sun 22
~~~

| 项 | 值 |
|---|---|
| UE 进程总耗时 | **74.5 s**（热启动；脚本返回后 PythonScriptPlugin 自动 QUIT_EDITOR，无残留进程） |
| 脚本内总耗时 | **31.645 s** |
| 其中：场景生成 | 4.062 s（805 actors，材质同步编译） |
| 其中：相机 rig | 0.089 s（1600×1200、FOV 69.726°、fx=fy=1148.3429） |
| 其中：渲染 | 91 帧 / **27.36 s**（avg **0.3007 s/帧**） |
| CPU / GPU 温度 | 始温 59.9 / 49.3 °C；渲染窗口峰值 **66.9 °C / 49.1 °C**（远低于 80 °C） |
| 4 核限载 | `affinity=0x000F + BelowNormal` 已生效 |
| c2w 与 capture 公式交叉校验 | **max diff = 0.0** |
| 引擎 / UE python | 5.8.4-58902052+++UE5+Release-5.8 / 3.11.8 |

### 8.3 离线验收校验

- 现行校验器：`python llm_drone/ue5_mission/validate_output.py --out data/synthetic/mission_llm --mission llm_drone/demo/mission_grid_campus.json --results llm_drone/ue5_mission/results --tag mission_llm`
  → `results/validation_mission_llm.json` **ok = true**：17 项 checks = **16 PASS / 0 FAIL / 1 SKIP**、**0 WARN**；
  缩略图拼图 `results/contact_sheet_mission_llm.png`（91 帧）。
- 契约校验器（旧原型）：`python llm_drone/ue5_mission/legacy/check_mission_dataset.py --data data/synthetic/mission_llm`
  → `data/synthetic/mission_llm/validate_report.json` **ok = true**（91 训练 + 8 验证帧；c2w 正交误差 0、GPS 往返 0、亮度/曝光正常）。

| 检查 | 结果 | 证据 |
|---|---|---|
| 帧数 / PNG 数 = mission 拍照点数 | PASS | 91 / 91（mission `n_photos`=91） |
| 分辨率 1600×1200、内参与 capture 相机一致 | PASS | 全部 91 张；fx=fy=1148.3429、cx=800、cy=600 |
| 非黑 / 曝光正常（全图） | PASS | 单帧 RGB 均值 **0.492–0.739**（平均 **0.648**）、方差最小 2348.3、p95 最大 231（0–255 口径）；无全黑/过曝 |
| 图像互不相同（md5） | PASS | 91 个唯一 md5 |
| c2w 刚性（正交 + det=+1 + 底行） | PASS | max err **0.0** |
| GPS 往返（c2w 平移 → WGS84 → UE cm） | PASS | max **0.0 cm** |
| 与 mission 独立重算真值（mission_io 重解 mission vs metadata） | PASS | c2w/GPS/gimbal/timestamp 误差均 **0** |
| 图像中心视线几何 / 时间戳单调 | PASS | 中心视线落在地面内；timestamp 单调 0→382.9 s |
| 与 capture 常量直接对比 | **SKIP** | 系统 python 无 `unreal` 模块（设计内 SKIP，不判 FAIL） |

### 8.4 与 3DGS 流水线兼容性

~~~powershell
pipeline\.venv\Scripts\python.exe pipeline\dataset.py --data data\synthetic\mission_llm --scale 0.5
~~~

实测：`kind=conventions world=ue_rh_cm n_views=91 size=800x600`，91 视角全部加载，
c2w 成功转 COLMAP 位姿 → 可直接作为 `03_train_3dgs.py --data data/synthetic/mission_llm` 的输入
（可据此跑 gs-pipeline 短训练，形成「LLM 规划→UE5 虚拟拍摄→3DGS」完整闭环证据）。

### 8.5 QA 备注（规划一致性）

- mission 实际参数为 **alt=50 m / gimbal pitch=−90°（nadir）/ heading=90°**，来自 orchestrator planner 默认值；
  而最初自然语言请求是 **40 m / −45° 倾斜**。渲染侧忠实执行 mission JSON（§5 交叉校验证明 c2w/GPS/云台与 mission 完全一致），
  该差异属于 **LLM 规划一致性**问题，由 QA/报告记录，不是渲染链路问题。
- 留出验证集 8 帧由 17:26 原型渲染器生成（与主集同 schema/同坐标系/同相机参数，校验 c2w 正交 0、GPS 往返 0），
  主集 91 帧由现行工具链于 21:55 重渲。

## 9. P1 真实 LLM run 集成渲染（`data/synthetic/mission_p1`，20 帧，2026-11-08 22:04）

> 与 §8 的区别：§8 是 orchestrator **demo mission**（m-001，91 帧，planner 默认参数 alt=50 m/nadir）；
> 本节是 **真实 LLM 工具循环（qwen3.5:4b，real_llm）** 产出的 P1 任务，完整走
> 「自然语言 → LLM 工具调用 → plan_capture_mission → mission JSON → UE5 出图」链路。

| 项 | 值 |
|---|---|
| 自然语言请求 | 「对 (39.9042, 116.4074) 半径 28 米的区域做 40 米高度的网格航拍，重叠率 70%，云台 -45°，拍完返航。」（`runs/20261108_220309_P1/request.md`） |
| LLM 工具链 | `plan_capture_mission{pattern=grid, center=39.9042/116.4074, radius_m=28, altitude_m=40, overlap=0.7, gimbal_pitch_deg=-45}` → `takeoff{40, confirm}` → `goto_waypoints{plan_id=plan-acd562c360, confirm}` → `return_to_home`；7 次 LLM 调用 / 4 次工具调用，拒绝 0，`metrics.json passed=true`（run wall 24.81 s / sim 204 s） |
| 输入 mission | `llm_drone/demo/runs/20261108_220309_P1/mission.json`（v1 schema，`plan_id=plan-acd562c360`，20 个 `action=photo` 航点，4 线 × 5 点，40 m / -45°，heading 0/180） |
| 输出 | `data/synthetic/mission_p1/{images/0001-0020.png, metadata.json, poses_mission.json}`（22 文件 / 57.63 MB） |
| 渲染参数 | 1600×1200、Exposure 0.6、Sun 22、805 actors、seed 20261108；CPU/GPU 始温 58.9/44.0 °C，affinity 0x000F + BelowNormal |
| UE 进程总耗时 | **46.3 s**（热启动；脚本返回后自动退出，无残留进程） |
| 脚本内耗时 | **7.533 s** = 场景 2.859 s + 渲染 4.606 s（**0.2303 s/帧**）+ rig 0.054 s + 元数据 |
| 校验 | `results/validation_p1.json` **ok=true**：17 checks = 16 PASS / 0 FAIL / 1 SKIP / 8 WARN；c2w 正交 0、GPS 往返 0 cm、与 mission 独立重算真值 c2w 误差 0、gimbal/heading 误差 0°；亮度均值最小 101.93/255、方差最小 3802.74 |
| 帧-航点对应 | 渲染帧 i（1..20）↔ `mission.waypoints[i-1]`（photo_points 0..19）一一对应；与 `metrics.json n_photos=20`、`mission_record.json` 20 张照片一致 |
| 目视抽查 | `mission_p1/images/0001.png`：园区建筑/道路/树木/车辆正常，40 m/-45° 俯视关系正确 |
| 3DGS 兼容 | `pipeline/dataset.py --data data/synthetic/mission_p1 --scale 0.5` → `kind=conventions n_views=20 size=800x600`，20 视角全部加载，c2w→COLMAP 位姿正常 |
| 证据 | 日志 `llm_drone/logs/ue5-mission/ue_mission_20261108_220429.log`；启动结论 `run_20261108_220429.json`；渲染摘要 `run_plan-acd562c360_*.json`；contact sheet `results/contact_sheet_p1.png` |

> 说明：P1 mission 未带 `mission_id`（PROTOCOL §6：由 Agent 执行时分配，本例为 m-0001）→
> 渲染以 `plan_id=plan-acd562c360` 作为数据集 mission_id 并记 warning（`metadata.validation.warnings`）。
> 8 条 WARN 为 4 条航线首/末拍照点朝外前视的正常几何（图像中心视线落在 mission 足迹 +25 m 外、
> 400 m 地面内），不影响结论。

## 10. 历史原型记录（保留证据，非本次交付）

- **17:22–17:24**（旧 `mission_to_poses.py + render_mission.py` 原型）：`mission_grid_12` 12 帧（60.3 s）、
  `mission_grid_36` 36 帧 + 8 val 帧（46.3 s，avg 0.254 s/帧；c2w 正交 0、GPS 往返 5e-12°）。
  日志已归档至 `llm_drone/logs/ue5-mission/archive_prototype/`。
- **17:27 首渲 / 21:55 重渲（orchestrator demo mission m-001）**：`data/synthetic/mission_llm/`（91 帧 + val 8 帧）
  即 **P1 集成证据数据集**（见 §8）；17:27 首渲（旧原型，64.4 s）的日志与摘要归档于
  `llm_drone/logs/ue5-mission/archive_prototype/`（`ue5_mission_20261108_172643.log`、
  `ue5_mission_render_m-001_20261108_172738.json`），21:55 用现行工具链重渲并完成校验（74.5 s）。
- 旧原型脚本（已移入 `legacy/`：`mission_to_poses.py` / `check_mission_dataset.py` / `render_mission_legacy.py` / `run_mission_legacy.ps1`）
  仅作证据追溯，主流程不再调用。

## 11. 已知限制

- 场景是 capture 的程序化园区（805 actors，90 m × 90 m），非真实城市；与 `data/synthetic/capture` 同场景不同航线。
- 单帧光栅、无 TAA 历史、无镜头畸变；画面与 capture 同风格（偏亮，mean≈0.56）。
- 16 帧网格（4×4）覆盖低于 capture 的 175 帧五向航线，3DGS 重建质量预计低于 capture 数据集。
- 每个 photo 航点 1 张静态图；无视频/连拍/运动模糊。
- 输出分辨率/内参与场景原点固定（与 capture 一致），mission 的 camera/origin 与 capture 不一致会被拒绝渲染。
- 主要成本是 UE 编辑器冷启动（~70 s）；每帧渲染 ~0.25 s。
