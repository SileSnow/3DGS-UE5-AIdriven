# UE5 虚拟相机执行 Mission JSON → 航拍 PNG + 真值 metadata（llm_drone/ue5_mission）

> 一句话：把 LLM 编排层（orchestrator）产出的 **Mission JSON** 变成 UE5.8 虚拟相机的 1600×1200 航拍图
> + 真值 c2w / GPS / 云台 / 时间戳元数据，直接喂 3DGS 流水线，打通
> **自然语言 → LLM 规划 → mission JSON → UE5 虚拟飞行渲染 → 3DGS 重建** 的闭环（Phase-1 验收 #4）。
> 本目录只新增脚本，**不改 capture/ 上游代码**（只读 import 复用其场景/相机/RT 导出能力）。

## 0. 状态（2026-11-08 22:0x）

- **spec 交付已实测通过**：`llm_drone/spec/sample_mission.json`（16 个 action=photo 航点）→
  `data/synthetic/mission/images/0001-0016.png`（1600×1200）+ `metadata.json` + `poses_mission.json`；
  离线校验 `llm_drone/ue5_mission/results/validation.json` **ok=true**（16 PASS / 0 FAIL / 1 SKIP / 4 WARN）。
- 实测耗时：UE 进程 **80.5 s**（编辑器启动+退出 ≈73 s，冷启动）、脚本内 7.32 s
  （场景 3.33 s + 16 帧渲染 3.91 s ≈ 0.245 s/帧）。详细数字见 [RESULTS.md](RESULTS.md)。
- **P1 集成证据已实测（2026-11-08 21:55–21:56，现行工具链）**：orchestrator 产出的真实 LLM 任务
  `llm_drone/demo/mission_grid_campus.json`（m-001，91 个拍照航点，grid）→
  `data/synthetic/mission_llm/`（**91 训练帧 + val 8 帧**，1600×1200，255.68 MB）；
  `results/validation_mission_llm.json` **ok=true**（16 PASS / 0 FAIL / 1 SKIP / 0 WARN），
  `data/synthetic/mission_llm/validate_report.json` ok=true（91+8 帧）。
  UE 进程 **74.5 s**（热启动）、脚本内 31.6 s = 场景 4.06 s + 91 帧渲染 27.36 s（**0.3007 s/帧**）；
  亮度（全图 RGB 均值）平均 **0.648**（0.492–0.739），无全黑/过曝。详见 RESULTS.md §8。
- **P1 真实 LLM run 集成证据（2026-11-08 22:04）**：orchestrator 真实 LLM run
  `llm_drone/demo/runs/20261108_220309_P1/mission.json`（qwen3.5:4b，4 次工具调用，20 拍照点，
  自然语言请求「半径 28 m / 40 m 高 / 重叠 70% / 云台 -45°」被完整执行）→
  `data/synthetic/mission_p1/`（**20 帧** 1600×1200 + metadata + poses，57.63 MB）；
  `results/validation_p1.json` **ok=true**（16 PASS / 0 FAIL / 1 SKIP / 8 WARN）；
  UE 进程 **46.3 s**（热启动）、脚本内 7.533 s = 场景 2.859 s + 20 帧渲染 4.606 s（**0.2303 s/帧**）。
  详见 RESULTS.md §9。

## 1. 数据流

```
llm_drone/spec/sample_mission.json        （spec v1：16 拍照点网格）
llm_drone/demo/mission_<scenario>.json    （orchestrator 产出的 demo mission，可选）
        │
        │  mission_io.py  —— 纯 stdlib；CPU/离线；也可被 UE 内脚本 import
        ▼
渲染计划：photo waypoint → UE 位姿 {loc_cm, yaw_ue = heading_deg-90, pitch_ue = gimbal_pitch, roll=0}
          WGS84 → UE 世界 cm（+X 东 / +Y 南 / +Z 天）、c2w（PROTOCOL §7.2）、模拟 GPS
        │
        │  run_mission.ps1（ASCII junction C:\UEW + UnrealEditor.exe -ExecutePythonScript）
        ▼
render_mission.py（UE 内置 Python 3.11）
        ├─ 复用 capture/scripts/synth_common.py：build_scene（805 actors 程序化园区）
        │  / create_capture_rig（1600×1200, fov 69.726°, fx=fy=1148.3429）/ render_pose
        ▼
data/synthetic/mission/
  images/0001.png … 0016.png   1600×1200 PNG
  metadata.json                shared/CONVENTIONS.md 数据集格式 + 真值 c2w/GPS/云台/时间戳
  poses_mission.json           渲染计划全量记录（可追溯）
        │
        │  python llm_drone/ue5_mission/validate_output.py --out data/synthetic/mission
        ▼
llm_drone/ue5_mission/results/validation.json + contact_sheet.png
        │
        ▼
pipeline/dataset.py（kind=conventions）→ 03_train_3dgs.py → gaussians.ply → ue5-splat
```

## 2. 目录内容

| 文件 | 作用 |
|---|---|
| `mission_io.py` | **Mission JSON → 渲染计划 / metadata**（纯 stdlib，系统 python 与 UE python 3.11 共用）：读+校验 mission、WGS84↔UE cm、c2w、§7.3 metadata、`plan_summary`、离线干跑 CLI |
| `render_mission.py` | **UE 编辑器内入口**：建场景（复用 synth_common）→ 逐 photo 航点渲染 PNG → 写 metadata.json / poses_mission.json / 运行摘要 |
| `run_mission.ps1` | 一键启动 UE：ASCII junction 路径映射、单 UE 检查、温度预检、4 核限载 + BelowNormal、超时看门狗、日志写 `llm_drone/logs/ue5-mission/`、`-DryRun` 只打印命令行 |
| `validate_output.py` | **离线验收校验**（PIL+numpy）：≥12 张 1600×1200 非黑（亮度均值>5、方差>100）、metadata schema/帧数、c2w 正交性<1e-6、GPS 往返<0.05 cm、gimbal/heading 对应、与 mission 独立重算真值对比；输出 validation.json + contact_sheet.png |
| `results/validation.json` | 最近一次校验报告（ok / checks / warnings / problems / per-frame 证据） |
| `results/contact_sheet.png` | 16 帧缩略图拼图（4×4，带帧号），供人工目视 |
| `results/validation_mission_llm.json` | **P1 数据集（mission_llm，91 帧）校验报告**：ok=true、16 PASS/0 FAIL/1 SKIP/0 WARN，含逐帧亮度/几何/真值证据 |
| `results/contact_sheet_mission_llm.png` | P1 数据集 91 帧缩略图拼图（带帧号），供人工目视 |
| `results/validation_p1.json` | **P1 真实 LLM run（mission_p1，20 帧）校验报告**：ok=true、16 PASS/0 FAIL/1 SKIP/8 WARN |
| `results/contact_sheet_p1.png` | P1 真实 LLM run 20 帧缩略图拼图（带帧号），供人工目视 |
| `results/mission_plan.json` | `mission_io.py` 离线干跑产物（16 位姿的 loc/c2w/GPS/时间戳） |
| `missions/` | 原型期生成的测试 mission（12/36 帧网格）与字段说明，保留供复核 |
| `legacy/mission_to_poses.py` / `legacy/check_mission_dataset.py` / `legacy/render_mission_legacy.py` / `legacy/run_mission_legacy.ps1` | **历史原型**（17:17–17:28 的第一版，宽容解析 + 旧渲染入口）。现行交付路径已改为 mission_io.py + 新版 render_mission.py/run_mission.ps1/validate_output.py；旧文件保留只为证据追溯，不再被主流程调用 |

## 3. 环境（本机实测）

| 项 | 值 |
|---|---|
| Unreal Engine | 5.8.4（`C:\Program Files\Epic Games\UE_5.8`，CL 58902052） |
| UE 工程 | `capture/UE5Synth/UE5Synth.uproject`（Blueprint-only，PythonScriptPlugin 已启用，复用未改） |
| ASCII 启动路径 | junction `C:\UEW` → `C:\Users\<user>\Desktop\GAIA项目`（UE 对非 ASCII 路径有已知问题） |
| 系统 Python | 3.14.6 + Pillow 12.2.0 + numpy 2.4.4（离线校验/干跑用；mission_io 只用 stdlib） |
| UE 内 Python | 3.11.8（只用 stdlib + unreal） |
| GPU | RTX 5060 Laptop 8GB / DX12 SM6；UE 渲染独占串行（本工具启动前检查是否已有 UE 实例） |

## 4. 快速开始（复现命令）

```powershell
cd C:\UEW\dji_ue5_3dgs

# 1) 离线干跑：mission -> 渲染计划（不启动 UE，不占 GPU）
python ./llm_drone/ue5_mission/mission_io.py --mission ./llm_drone/spec/sample_mission.json --out ./llm_drone/ue5_mission/results

# 2) 启动命令行自检（不启动 UE）
powershell -ExecutionPolicy Bypass -File ./llm_drone/ue5_mission/run_mission.ps1 -DryRun

# 3) 正式渲染（先确认没有别的 UE 实例；GPU 独占，约 40-90 s 含启动）
powershell -ExecutionPolicy Bypass -File ./llm_drone/ue5_mission/run_mission.ps1 -Mission llm_drone/spec/sample_mission.json -Out data/synthetic/mission -Exposure 0.6 -Sun 22

# 4) 离线验收校验（>=12 张 1600x1200 非黑 / c2w 正交 / GPS 往返 / gimbal-heading / 真值对比）
python ./llm_drone/ue5_mission/validate_output.py --out data/synthetic/mission

# 5) 只读验证可被 3DGS 流水线加载（可选，不训练）
pipeline\.venv\Scripts\python.exe pipeline\dataset.py --data data/synthetic/mission --scale 0.5
```

P1 集成证据（真实 orchestrator demo mission m-001，91 帧；2026-11-08 21:55 已跑通）：

```powershell
powershell -ExecutionPolicy Bypass -File ./llm_drone/ue5_mission/run_mission.ps1 -Mission llm_drone/demo/mission_grid_campus.json -Out data/synthetic/mission_llm -Exposure 0.6 -Sun 22
python ./llm_drone/ue5_mission/validate_output.py --out data/synthetic/mission_llm --mission llm_drone/demo/mission_grid_campus.json --results llm_drone/ue5_mission/results --tag mission_llm
```

输出 `data/synthetic/mission_llm/images/0001-0091.png` + `metadata.json` + `poses_mission.json` + `val/`（8 帧留出验证）；校验报告为 `results/validation_mission_llm.json`。

## 5. 输入：Mission JSON（两种格式都支持）

1. **`llm_drone.mission/v1`（FROZEN spec，PROTOCOL.md §6）** —— 主交付格式，样例
   `llm_drone/spec/sample_mission.json`：`schema/mission_id/type/origin_wgs84/camera/flight/waypoints[]`，
   waypoint 含 `lat/lon/alt_abs_m(或 alt_rel_m)/heading_deg/gimbal_pitch_deg/speed_mps/action`；
   只有 `action == "photo"` 的航点会出图。
2. **orchestrator demo mission**（`llm_drone/demo/mission_<scenario>.json`）—— 集成证据用：
   `{mission_id, pattern, origin_wgs84, defaults{alt_rel_m, gimbal_pitch, yaw, speed_mps},
   waypoints[{lat, lon, alt_rel_m, gimbal{pitch,yaw,roll}, take_photo}]}`；
   `{"args": {...}}` / `{"mission": {...}}` 包装、drone-sim mission record（photos[{gps, gimbal_deg, pose_enu}]）会自动展开
   （record 无 `origin_wgs84` 时从首张照片 gps+pose_enu 反推，1 条 warning 记录）；
   waypoint 缺 gimbal yaw 时按飞行方向推断（记录在 `yaw_source`）。
   离线已验证可解析：v1 sample（16 帧）、demo plan multi_angle/orbit_building/grid_campus（5/24/91 帧）、
   mission record multi_angle/orbit_building（5/24 帧）。

坐标约定（两种格式统一，PROTOCOL.md §2/§7.2）：
- UE 世界：左手系 cm，`+X = East，+Y = South（北 = -Y），+Z = Up`；原点 `origin_wgs84`（默认 39.9042/116.4074/43 m）。
- 航向：`heading_deg` 为罗盘航向（0=北，顺时针）→ UE yaw = `heading_deg - 90`；云台 pitch -90=正下、0=水平。
- 每帧 c2w（PROTOCOL §7.2）：4×4 行主序，列 = `[forward, right, up]`（UE 相机轴），第 4 列 = 相机位置 cm。

## 6. 输出格式（shared/CONVENTIONS.md）

```
data/synthetic/mission/
  images/0001.png … 0016.png     1600×1200 PNG（RGBA8 RenderTarget → PNG）
  metadata.json                  数据集契约 + 真值
  poses_mission.json             渲染计划全量（frame → waypoint/loc/c2w/gps/timestamp）
```

`metadata.json` 顶层（与 capture 数据集同 schema，额外扩展字段不改变既有语义）：
`dataset / camera_model / width / height / fx / fy / cx / cy / coord_system(=UE_LHS_Zup_cm) /
origin_wgs84 / sensor_mm / focal_mm / equivalent_focal_mm / fov_deg / units / generator /
mission(source_format, flight, n_photos, …) / validation{warnings} / frames / notes`。

每帧：
```json
{
  "file": "images/0001.png",
  "c2w": [16 floats, 行主序, 列 = forward/right/up(UE 相机轴), 平移 cm],
  "gps": {"lat": 39.903948473, "lon": 116.407072114, "alt": 83.0},
  "gimbal_deg": {"yaw": -90.0, "pitch": -45.0, "roll": 0.0},
  "timestamp": 0.0,
  "waypoint_index": 0,
  "dji_gimbal_yaw_deg": 0.0,
  "yaw_source": "mission_heading_deg",
  "mission": {"mission_id": "sample-grid-16", "waypoint_index": 0, "heading_deg": 0.0,
              "gimbal_pitch_deg": -45.0, "alt_rel_m": 40.0}
}
```

- `gimbal_deg` 是 **UE 相机 actor 角度**（yaw 0 = +X = 东），与 capture 数据集语义一致；
  `dji_gimbal_yaw_deg` 是同一朝向的 DJI 习惯表示（0=北，顺时针）。
- `gps` 由 UE 坐标按 PROTOCOL §2 反算；`timestamp` 是仿真任务秒（按航点速度巡航 + 每个拍照点 0.5 s 悬停）。
- `c2w` 与 capture 的 `capture/scripts/synth_common.py::c2w_from_pose` 逐帧交叉校验（本次 max diff = 0.0）。

运行证据（每次渲染）：
`llm_drone/logs/ue5-mission/ue_mission_<ts>.log`（UE stdout，含 `[SYNTH] SUMMARY`）、
`ue_engine_<ts>.log`（引擎日志副本）、`run_<ts>.json`（启动脚本结论：帧数/温度/耗时/命令行）、
`run_<mission_id>_<ts>.json`（渲染器摘要：timing/per-frame/c2w diff）。

## 7. 设计要点

1. **唯一真值实现**：WGS84↔UE、c2w、metadata 只在 `mission_io.py` 实现一次，系统 python 与 UE 内
   python 共用；`capture/scripts/synth_common.py` 的同名公式在渲染时逐帧比对（diff 必须为 0）。
2. **只读复用 capture/**：场景（805 actors，seed 20261108）、相机 rig（1600×1200、FOV 69.726°、
   fx=fy=1148.3429）、材质同步编译（`get_statistics`）、SceneCapture2D → PNG 导出全部复用，不复制不修改。
3. **校验语义**：checks 有 pass/fail/skip 三种状态；**FAIL 才判失败**；SKIP 用于离线拿不到 unreal 的对比项
   （`metadata_matches_capture_constants`，detail 记 "skipped: unreal unavailable"）；WARN 记录预期现象
   （如 -45° 前视相机图像中心落点在任务覆盖区外但仍落在 400 m 地面内）不影响结论。
4. **可复现**：mission JSON + 固定相机/场景 seed + 固定曝光 0.6 / 太阳 22 → 同一命令可重复渲染。
5. **机器安全**：一次只开一个 UE（启动前进程检查）；CPU 4 核限载（affinity 0x000F + BelowNormal）；
   启动前 CPU/GPU 温度 ≥80 °C 拒绝（`-Force` 覆盖）；`-TimeoutSec` 看门狗 kill 进程树。

## 8. 实测结果（2026-11-08 21:53，详见 RESULTS.md）

| 项 | 值 |
|---|---|
| 输入 | `llm_drone/spec/sample_mission.json`（sample-grid-16，16 个拍照点） |
| 输出 | 16 张 1600×1200 PNG（45.22 MB）+ metadata.json + poses_mission.json |
| UE 进程总耗时 | **80.5 s**（含冷启动；脚本返回后编辑器自动退出） |
| 脚本周转 | 7.32 s = 场景 3.33 s + 16 帧 3.91 s（**0.245 s/帧**）+ rig/元数据 |
| 环境 | 805 actors，Sun 22 lux，Exposure 0.6，CPU/GPU 始温 56.9/42.8 °C，affinity 0x000F |
| 校验 | **ok=true**：16 PASS / 0 FAIL / 1 SKIP / 4 WARN；c2w 正交误差 0、GPS 往返 0、真值 c2w 误差 0、gimbal 误差 0；亮度均值最小 96.7/255、方差最小 3802.7 |
| 3DGS 兼容 | `pipeline/dataset.py` 只读加载 → kind=conventions，16 views（800×600 @scale 0.5），c2w→COLMAP 位姿正常 |

### 8.1 P1 集成证据（真实 orchestrator demo mission → `data/synthetic/mission_llm`，91 帧）

| 项 | 值 |
|---|---|
| 输入 mission | `llm_drone/demo/mission_grid_campus.json`（`m-001`，pattern=grid，**91 个拍照航点**） |
| 输出 | `data/synthetic/mission_llm/images/0001-0091.png`（**91 帧** 1600×1200）+ `metadata.json`(88,720 B) + `poses_mission.json`(75,198 B) + `val/`（8 帧 + metadata_val.json）；合计 **255.68 MB** |
| 任务几何 | x ∈ [−6000, 6000] cm、y ∈ [−6976, 6000] cm、z = 5000 cm（alt 50 m），gimbal pitch **−90°（nadir）**，heading 90° |
| UE 进程总耗时 | **74.5 s**（热启动）；脚本内 **31.645 s** = 场景 4.062 s + rig 0.089 s + 91 帧渲染 27.36 s（**0.3007 s/帧**） |
| 环境 | 805 actors，Sun 22 lux，Exposure 0.6；CPU/GPU 始温 59.9/49.3 °C，窗口峰值 66.9/49.1 °C；affinity 0x000F + BelowNormal |
| 校验 | `results/validation_mission_llm.json` **ok=true**（16 PASS/0 FAIL/1 SKIP/0 WARN）：c2w 刚性误差 0、GPS 往返 0、与 mission 独立重算真值 c2w 误差 0、gimbal 误差 0；`data/synthetic/mission_llm/validate_report.json` ok=true（91+8 帧，c2w 正交 0、GPS 往返 0） |
| 亮度 | 全图 RGB 均值平均 **0.648**（单帧 0.492–0.739），luma 缩略图均值 0.584，p99 ≤ 0.91 —— 无全黑/过曝；91 帧 md5 互不相同 |
| 3DGS 兼容 | `pipeline/dataset.py --data data/synthetic/mission_llm` → kind=conventions，**91 views**（800×600 @scale 0.5），c2w→COLMAP 位姿正常 |
| 备注 | mission 的 alt=50 m / nadir 来自 orchestrator planner 默认值，与最初自然语言请求 40 m/−45° 不一致（规划一致性问题，见 §9） |

### 8.2 P1 真实 LLM run 集成证据（→ `data/synthetic/mission_p1`，20 帧，2026-11-08 22:04）

> 与 §8.1 的区别：§8.1 是 orchestrator **demo mission**（m-001，91 帧，planner 默认参数）；
> 本节是 **真实 LLM 工具循环（Ollama qwen3.5:4b，real_llm）** 产出的 P1 任务，
> 自然语言请求为「对 (39.9042,116.4074) 半径 28 m 区域做 40 m 高度网格航拍、重叠率 70%、云台 -45°、拍完返航」，
> LLM 的 `plan_capture_mission` 参数与请求一致（radius 28 m / alt 40 m / overlap 0.7 / pitch -45°）。

| 项 | 值 |
|---|---|
| 输入 mission | `llm_drone/demo/runs/20261108_220309_P1/mission.json`（v1 schema，`plan_id=plan-acd562c360`，**20 个 action=photo 航点**，4 线 × 5 点网格，40 m / -45°） |
| 来源 run | `llm_drone/demo/runs/20261108_220309_P1/`：real_llm，7 次 LLM 调用 / 4 次工具调用（`plan_capture_mission → takeoff → goto_waypoints → return_to_home`），照片 20、mission completed、拒绝 0、`metrics.json passed=true`；run wall 24.81 s |
| 输出 | `data/synthetic/mission_p1/{images/0001-0020.png, metadata.json, poses_mission.json}`（22 文件 / 57.63 MB） |
| UE 进程总耗时 | **46.3 s**（热启动；脚本返回后自动退出）；脚本内 **7.533 s** = 场景 2.859 s + rig 0.054 s + 20 帧渲染 4.606 s（**0.2303 s/帧**） |
| 环境 | 805 actors，Sun 22 lux，Exposure 0.6；CPU/GPU 始温 58.9/44.0 °C，affinity 0x000F + BelowNormal |
| 校验 | `results/validation_p1.json` **ok=true**：17 checks = 16 PASS / 0 FAIL / 1 SKIP / 8 WARN；c2w 正交 0、GPS 往返 0 cm、真值 c2w 误差 0、gimbal 误差 0°；亮度均值最小 101.93/255、方差最小 3802.74 |
| 帧-航点对应 | 渲染帧 1..20 ↔ mission `photo_points` 0..19 一一对应（`metadata.mission.photo_waypoint_indices`），与 `metrics.json n_photos=20`、`mission_record.json` 20 张照片一致 |
| 备注 | mission 无 `mission_id`（PROTOCOL §6 允许，Agent 执行时分配 m-0001）→ 以 `plan_id` 作数据集 mission_id 并记 warning |

## 9. 已知限制

- 场景是 capture 的程序化园区（805 actors，90 m × 90 m，固定 seed），非真实城市；与 `data/synthetic/capture` 同一场景。
- 单帧光栅（SCS_FinalColorLDR），无 TAA 历史、无镜头畸变参数；画面与 capture 同风格（偏亮，mean≈0.56）。
- 每个 photo 航点渲染 1 张静态图；无视频/连拍/运动模糊/云台运动。
- 输出分辨率/内参固定为 1600×1200 / fx=fy=1148.3429（与 capture 一致）；mission 里的 camera 字段若不同会被拒绝（渲染世界固定）。
- mission 的 `origin_wgs84` 必须与 capture 场景原点（39.9042/116.4074/43）一致，否则拒绝渲染（GPS 真值会不成立）。
- 主要成本是 UE 编辑器启动（冷启动 ~70 s，热启动 ~30 s）；每帧渲染 ~0.25 s。
- 4 条 WARN 是 -45° 前视相机的正常几何现象（图像中心落点在 mission 足迹外 25 m 扩展带之外、400 m 地面内），不是渲染错误。
- **orchestrator planner 默认参数与自然语言请求不一致（QA 发现，2026-11-08）**：`demo/mission_grid_campus.json`
  实际为 alt=50 m、gimbal pitch=−90°（正下/正射）、heading=90°，而最初自然语言请求是 40 m / −45° 倾斜；
  渲染侧按 mission JSON 忠实执行（虚拟相机严格跟随 mission），该差异属于 **LLM 规划一致性**问题，
  由 QA/报告记录，不是渲染链路问题。

## 10. 故障排查

1. `-ExecutePythonScript` 值必须**正斜杠**且整体加引号（UE FParse 会吃掉反斜杠）——`run_mission.ps1` 已处理。
2. 编辑器未自动退出：看 `llm_drone/logs/ue5-mission/ue_mission_<ts>.log` 尾部是否有 `[SYNTH] DONE` / `LogExit: Exiting`；`-TimeoutSec` 到时会 kill 进程树。
3. 画面全灰/无纹理：材质未同步编译（必须走 `C.ensure_scene` → `force_compile_material`，不要绕开）。
4. UE 启动路径必须 ASCII（`C:\UEW` junction）；脚本内部读写仍走真实中文路径（同一份文件）。
5. 若 `validate_output.py` 报 `metadata_matches_capture_constants` 为 SKIP，属正常（系统 python 无 unreal 模块）。
6. `run_mission.ps1` 被 "another UnrealEditor process is already running" 拒绝：确认没有其他 agent/窗口占用 UE 后重试，或 `-Force`（谨慎）。
