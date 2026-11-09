# ue5-mission 收尾报告（task-6 / Phase-1 验收 #4）

> 更新时间：2026-11-08 21:5x（Asia/Shanghai）。任务：UE5.8 虚拟相机执行 Mission JSON →
> 渲染 ≥12 张 1600×1200 PNG + 真值 metadata（可接 3DGS）。
> 状态：**spec 交付已完成并实测通过**（16 帧主产物 + validation ok=true）。
> 待办：等 Lead 给 P1 demo mission 路径后渲染 `data/synthetic/mission_p1/` 作为「LLM 规划→UE5 出图」集成证据。

## 1. 交付物清单

| 交付 | 路径 | 状态 |
|---|---|---|
| 主产物：16 帧 PNG + metadata + poses | `data/synthetic/mission/{images/0001-0016.png, metadata.json, poses_mission.json}` | ✅ 实测 16 帧 / 1600×1200 / 45.22 MB |
| Mission→计划/metadata converter | `llm_drone/ue5_mission/mission_io.py` | ✅ 系统 python 干跑 16 帧通过；UE 内复用 |
| UE 内渲染器 | `llm_drone/ue5_mission/render_mission.py` | ✅ 实跑成功（805 actors、16 帧、0.2446 s/帧） |
| 一键启动脚本 | `llm_drone/ue5_mission/run_mission.ps1` | ✅ 实跑成功（ASCII junction、4 核限载、温度预检、看门狗、日志入本目录） |
| 离线验收校验 | `llm_drone/ue5_mission/validate_output.py` | ✅ 17 checks = 16 PASS / 0 FAIL / 1 SKIP / 4 WARN，ok=true |
| 校验报告 + 缩略图 | `llm_drone/ue5_mission/results/validation.json`、`contact_sheet.png` | ✅ |
| 文档 | `llm_drone/ue5_mission/README.md`、`RESULTS.md` | ✅ |
| 历史原型（保留证据） | `mission_to_poses.py` / `check_mission_dataset.py` / `render_mission_legacy.py` / `run_mission_legacy.ps1` / `missions/` | ✅ 不删，主流程不再调用 |

## 2. 复现命令

~~~powershell
cd C:\UEW\dji_ue5_3dgs

# 离线干跑（无 GPU）
python llm_drone\ue5_mission\mission_io.py --mission llm_drone\spec\sample_mission.json --out llm_drone\ue5_mission\results

# 启动命令行自检（不启动 UE）
powershell -ExecutionPolicy Bypass -File llm_drone\ue5_mission\run_mission.ps1 -DryRun

# 正式渲染（一次只开一个 UE）
powershell -ExecutionPolicy Bypass -File llm_drone\ue5_mission\run_mission.ps1 -Mission llm_drone\spec\sample_mission.json -Out data\synthetic\mission -Exposure 0.6 -Sun 22

# 离线验收
python llm_drone\ue5_mission\validate_output.py --out data\synthetic\mission
~~~

## 3. 实测结果（2026-11-08 21:53）

| 项 | 值 |
|---|---|
| 输入 | `llm_drone/spec/sample_mission.json`（sample-grid-16，16 个拍照点） |
| 输出 | 16 张 1600×1200 PNG + metadata.json（19,688 B）+ poses_mission.json（14,769 B），45.22 MB |
| UE 进程总耗时 | **80.5 s**（冷启动 ≈73 s；脚本返回后自动退出，无残留进程） |
| 脚本内耗时 | **7.32 s** = 场景 3.33 s + 16 帧渲染 3.91 s（**0.2446 s/帧**）+ rig 0.064 s + 元数据 |
| 渲染参数 | Exposure 0.6、Sun 22 lux、场景 seed 20261108、805 actors、1600×1200、fov 69.7265°、fx=fy=1148.3429 |
| 机器状态 | CPU/GPU 始温 56.9/42.8 °C；affinity=0x000F + BelowNormal；单 UE 实例 |
| 校验 | **ok=true**：16 PASS / 0 FAIL / 1 SKIP / 4 WARN；c2w 正交误差 0、GPS 往返 0 cm、真值 c2w 误差 0、gimbal 误差 0° |
| 非黑检查 | 亮度均值最小 96.738/255、方差最小 3802.744、p95 最大 231.0（阈值 mean>5、var>100） |
| 3DGS 兼容 | `pipeline/dataset.py` 只读加载 16 views（kind=conventions, 800×600 @0.5）；Lead 用 `dataset.load_dataset` 独立复验通过 |
| 目视抽查 | `images/0001.png`（园区核心：建筑/道路/树木/车辆/阴影）、`images/0008.png`（西北街区）均正常，40 m 高度 -45° 俯视关系正确 |

## 4. 校验语义说明（Lead 要求）

- checks 有三种状态：**PASS / FAIL / SKIP**；**只有 FAIL 判失败**（`ok = n_fail == 0`）。
- `warnings[]` 记录预期现象，不影响结论。本次 4 条 WARN：
  `frame[3]/[7]/[11]/[15]`（0004/0008/0012/0016.png）图像中心视线落点为 (-2800,-6800)/(-933,6800)/(933,-6800)/(2800,6800) cm，
  在 mission 足迹（±2800 cm + 25 m 扩展 = ±5300 cm）之外、但仍在 400 m 地面内 —— 这是 -45° 前视相机的正常几何
  （中心视线 ≈ 40 m 前方），不是渲染错误；若落点完全离开 400 m 地面或射线朝上则为 FAIL。
- `metadata_matches_capture_constants` 在系统 python 里因无法 import unreal（synth_common 依赖 unreal）记 **SKIP**
  （detail=`skipped: unreal unavailable (ModuleNotFoundError: No module named 'unreal')`）；
  另有一项 `metadata_matches_capture_camera_model` 用同一套官方参数（1/1.3" 9.6×7.2 mm、82.1° 对角 FOV）
  本地重算相机模型做 PASS 校验。

## 5. 现场与踩坑记录

1. 断电恢复后 `data/synthetic/mission` 不存在（旧原型产物已由其他会话整理为 `data/synthetic/mission_llm/`，
   是 17:27 用旧脚本渲染的 m-001（91 帧，source `llm_drone/demo/mission_grid_campus.json`），非本任务 spec 产物，
   保留不动；本任务用新版工具链重新渲染干净 16 帧）。
2. 断电前已落盘的 `mission_io.py`（严格 v1 + orchestrator demo 适配）、新 `render_mission.py` 恢复后 smoke test 通过；
   本轮新写 `validate_output.py` 与新版 `run_mission.ps1`。旧版 `render_mission.py`/`run_mission.ps1` 已备份为 `*_legacy.*`。
3. `-ExecutePythonScript` 值必须正斜杠 + 整体加引号（UE FParse 会吃反斜杠）——ps1 已处理。
4. 渲染前必须 `C.ensure_scene`（内含材质同步编译），否则默认灰材质。
5. SceneCapture 自动曝光参数不生效，亮度靠太阳强度：Sun 22 与 capture 最终数据一致（mean≈0.56）。
6. `llm_drone/logs` 根下 17:22–17:28 的 11 个 `ue5_mission_*.log/json` 探测日志已全部移入
   `llm_drone/logs/ue5-mission/archive_prototype/`（根目录已清理干净）。
7. 新版 ps1 写 run JSON 用 BOM-less UTF-8（旧 PowerShell `Set-Content -Encoding UTF8` 会带 BOM，
   影响下游 `json.load` 默认编码）；validator 读 JSON 用 `utf-8-sig` 兼容既有 BOM 文件。

## 6. 证据索引

| 内容 | 路径 |
|---|---|
| UE stdout 日志（[SYNTH] SUMMARY/DONE） | `llm_drone/logs/ue5-mission/ue_mission_20261108_215343.log` |
| 引擎日志副本 | `llm_drone/logs/ue5-mission/ue_engine_20261108_215343.log` |
| 启动结论 JSON（80.5 s/16 帧/温度/命令行） | `llm_drone/logs/ue5-mission/run_20261108_215343.json` |
| 渲染器摘要（timing/per-frame/c2w diff） | `llm_drone/logs/ue5-mission/run_sample-grid-16_20261108_215445.json` |
| 校验报告 | `llm_drone/ue5_mission/results/validation.json` |
| 缩略图拼图 | `llm_drone/ue5_mission/results/contact_sheet.png` |
| 历史原型日志（17:22–17:28） | `llm_drone/logs/ue5-mission/archive_prototype/` |

## 7. P1 真实 LLM run 集成渲染（已完成，2026-11-08 22:04）

真实 LLM run `llm_drone/demo/runs/20261108_220309_P1/mission.json`（qwen3.5:4b，real_llm，
7 次 LLM 调用 / 4 次工具调用 `plan_capture_mission→takeoff→goto_waypoints→return_to_home`，
20 照片、mission completed、metrics passed=true）→ 渲染到 `data/synthetic/mission_p1/`：

| 项 | 值 |
|---|---|
| 输入 | run 的 `mission.json`（v1，plan_id=plan-acd562c360，20 photo 航点，40 m/-45°，4×5 网格；无 mission_id → 以 plan_id 作数据集 mission_id 并 warning） |
| 输出 | 20 张 1600×1200 PNG + metadata.json + poses_mission.json（22 文件 / 57.63 MB） |
| UE 进程耗时 | **46.3 s**（热启动，自动退出）；脚本内 **7.533 s** = 场景 2.859 s + 渲染 4.606 s（**0.2303 s/帧**）+ rig/元数据 |
| 参数 | Exposure 0.6 / Sun 22 / 805 actors / CPU 58.9 °C、GPU 44.0 °C 始温 / affinity 0x000F |
| 校验 | `llm_drone/ue5_mission/results/validation_p1.json` **ok=true**：17 checks = 16 PASS / 0 FAIL / 1 SKIP / 8 WARN；c2w 正交/GPS 往返/真值 c2w/gimbal 误差全 0；亮度均值最小 101.93、方差最小 3802.74 |
| 对应关系 | 渲染帧 1..20 ↔ mission photo_points 0..19 一一对应（metrics n_photos=20 / mission_record 20 张一致）；LLM 规划参数与自然语言请求（radius 28 / alt 40 / overlap 0.7 / -45°）一致 |
| 目视 | `mission_p1/images/0001.png` 正常（园区建筑/道路/树木，40 m/-45° 俯视） |
| 证据 | `logs/ue5-mission/ue_mission_20261108_220429.log`、`run_20261108_220429.json`、`run_plan-acd562c360_*.json`、`results/contact_sheet_p1.png` |

- 8 条 WARN 同主产物：航线首/末拍照点朝外前视，中心视线落点在 mission 足迹+25 m 外、400 m 地面内（预期几何）。
- [x] P1 前离线预验证（不占 GPU，已完成）：`mission_io.py` 可解析 demo plan
      `mission_multi_angle`(5 帧) / `orbit_building`(24 帧) / `grid_campus`(91 帧)，
      以及 drone-sim mission record `missions/multi_angle_m-001`(5) / `orbit_building_m-001`(24)
      （record 无 origin 时从 gps+pose_enu 反推，warning 记录，已验证）；主产物校验回归仍 ok=true。
