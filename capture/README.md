# capture/ — UE5.8 合成 DJI Mini 航拍数据集（场景 + 相机轨迹 + 渲染 + 元数据）

本目录是**可复现的一键工具链**：在 UE 5.8 里程序化生成“园区/街区”场景，按 DJI Mini 4 Pro 的相机参数
与五向倾斜摄影航线渲染 **1600×1200** PNG 序列，并为每帧输出 c2w / 模拟 GPS / 云台姿态 / 时间戳，
供 3DGS（gs-pipeline）训练与 UE5（ue5-splat）集成验证使用。

数据集写入 `dji_ue5_3dgs/data/synthetic/`（数据契约见 `shared/CONVENTIONS.md`），
实测结果与踩坑记录见 [RESULTS.md](RESULTS.md)。

---

## 1. 环境（本机实测）

| 项 | 值 |
|---|---|
| Unreal Engine | 5.8.4（`C:\Program Files\Epic Games\UE_5.8`，Build.version: 5 / 8 / 4 / CL 58902052） |
| 项目 | `capture/UE5Synth/UE5Synth.uproject`（Blueprint-only，无 C++ 模块；启用 PythonScriptPlugin / EditorScriptingUtilities / ModelingToolsEditorMode） |
| 编辑器 | `UnrealEditor.exe`（渲染）；`UnrealEditor-Cmd.exe -run=pythonscript`（无 GPU 自检） |
| 编辑器内 Python | UE 自带 3.11.8（脚本只用 stdlib + `unreal` 模块） |
| 系统 Python | 3.14.6 + Pillow/numpy（仅用于生成纹理、离线校验、metadata 修复） |
| GPU | RTX 5060 Laptop 8GB（sm_120），DX12 / SM6 |
| 路径 | UE 对非 ASCII 路径有已知问题 ⇒ 启动用 ASCII junction **`C:\UEW\dji_ue5_3dgs\...`**（`C:\UEW` → `C:\Users\<user>\Desktop\GAIA项目`，同一份文件） |

## 2. 运行方式

PowerShell 默认执行策略禁止 .ps1，用下面方式（或双击/运行 `run_capture.cmd`）：

```powershell
cd C:\UEW\dji_ue5_3dgs\capture

# ① 程序化纹理（系统 python，只需一次；纹理已随仓库提供）
python scripts\gen_textures.py

# ② 无 GPU 自检：完整场景生成（0.8-3 s，805 actors），验证脚本/资产不占渲染窗口
$ue = "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
& $ue C:/UEW/dji_ue5_3dgs/capture/UE5Synth/UE5Synth.uproject -run=pythonscript `
    -script="C:/UEW/dji_ue5_3dgs/capture/scripts/headless_build.py" -nullrhi -unattended -stdout -log

# ③ 灯光/曝光/构图探针（10 帧左右，含同步材质编译，约 30-60 s）
powershell -ExecutionPolicy Bypass -File .\run_capture.ps1 -Mode probe

# ④ 全量数据（175 train + 15 val，1600×1200；独占 GPU 时约 2 分钟，含启动）
powershell -ExecutionPolicy Bypass -File .\run_capture.ps1 -Mode full -Sun 22

# ⑤ 数据契约自检（系统 python，离线；c2w 正交性 + GPS 往返 + 品红标靶重投影）
cd C:\UEW\dji_ue5_3dgs
python capture\scripts\check_dataset.py

# ⑥ 可选：专门的校准帧 + 亚像素重投影校验（需再占一次 GPU 窗口）
powershell -ExecutionPolicy Bypass -File capture\run_capture.ps1 -Mode calib
python capture\scripts\validate_reprojection.py
```

编辑器命令行（由 `run_capture.ps1` 生成）：

```
UnrealEditor.exe <uproject> -ExecutePythonScript="C:/UEW/.../capture_synth.py --mode full --exposure 0.6 --sun 22"
  -windowed -resx=960 -resy=540 -nosplash -unattended -nopause -stdout -FullStdOutLogOutput -log
```

- 脚本结束时 PythonScriptPlugin 自动 defer `QUIT_EDITOR`，编辑器自行退出（无需手动关闭）。
- 实时进度看 `capture/UE5Synth/Saved/Logs/UE5Synth.log` 的 `[SYNTH]` 行；`run_capture.ps1` 的
  `logs/capture/ue_<mode>_<ts>.log` 因 PowerShell `Tee-Object` 缓冲，进程结束后才完整落盘。
- 脚本运行摘要：`logs/capture/run_<mode>_<timestamp>.json`。

### 脚本职责

| 文件 | 作用 |
|---|---|
| `scripts/gen_textures.py` | 系统 python：生成 8 张无缝平铺 PNG（草地/沥青/混凝土/铺装/3 种幕墙/屋面）→ `assets/textures/` |
| `scripts/synth_common.py` | UE 内：材质/网格/场景搭建、灯光天空、航线与 c2w/GPS 数学、SceneCapture2D 渲染、元数据 |
| `scripts/capture_synth.py` | UE 内入口：`--mode build/probe/calib/sample/full`，参数 `--exposure --sun --train-frames --val-frames --rebuild` |
| `scripts/headless_build.py` | 无 GPU（`-nullrhi` 命令列）完整场景生成自检 |
| `scripts/check_dataset.py` | 离线契约校验：帧数/分辨率/c2w 正交性/GPS 往返/标靶重投影（输出 `capture/dataset_check.json`） |
| `scripts/validate_reprojection.py` | 离线：`-Mode calib` 校准帧的立方体 8 角点 bbox 重投影校验（阈值 2 px） |
| `scripts/repair_metadata_c2w.py` | 离线：按 gimbal yaw/pitch 重算 c2w 旋转部分（保持位移/GPS 不变），原文件备份为 `*.bak.json` |
| `scripts/diag_*.py` | 无 GPU 的 UE Python API / 材质状态诊断（开发用） |
| `run_capture.ps1` / `run_capture.cmd` | 一键启动 UE 编辑器（ASCII 路径 + 日志 + 自动退出） |

## 3. 场景（程序化，无第三方资产）

- 90 m × 90 m 园区：6 条 9 m 宽道路（含中线虚线）、16 个抬升铺装街区、公园（水池 + 22 棵树）、
  广场（喷泉 + 彩色公共艺术 + 长椅）、**共 805 actors**：约 86 栋建筑（8–32 m 高，3 种幕墙贴图 +
  8 色调色板，屋顶设备/门廊；含外圈 3 圈填充建筑）、约 110 棵树、30+ 辆车、路灯、绿篱、道路虚线、
  5+3 个品红标靶（校验用）。
- 灯光：DirectionalLight（`-Sun` 默认 22 lux，视作“物理亮度旋钮”）+ 3 盏无阴影补光（近似天空环境光，
  避免死黑）+ SkyLight（real-time capture）+ SkyAtmosphere + ExponentialHeightFog；动态光照
  （`r.AllowStaticLighting=False`，关 Lumen/RT），8 GB 显存下稳定。
- 材质：Python 运行时创建 2 个母材质（`M_SynthFlat` / `M_SynthTiled`）与约 120 个
  MaterialInstanceDynamic；`M_SynthTiled` = 贴图(BaseTex) × Tint，UVScale 控制平铺密度。
- 场景布置全部在 `synth_common.build_scene()`，固定 seed = 20261108，可重复运行。
  **不保存/加载关卡**：`MaterialInstanceDynamic` 是 transient，存盘重载会丢引用；每次运行在当前
  world 重建（805 actors 约 7–9 s）。

## 4. 相机模型（DJI Mini 4 Pro 模拟）

| 参数 | 值 | 依据 |
|---|---|---|
| 传感器 | 1/1.3" CMOS，4:3，有效区 9.6 × 7.2 mm（对角 12.0 mm） | DJI 官方 1/1.3"、4800 万像素 8064×6048（≈1.2 µm 像素） |
| 视场角 | 82.1°（对角） | DJI 官方 “视角 82.1°” |
| 实际焦距 | f = 6.0 / tan(82.1°/2) ≈ **6.888 mm**（等效 24 mm） | 由对角 FOV 反算 |
| 水平/垂直 FOV | 69.726° / 55.18° | 由 9.6×7.2 mm 与 f 计算 |
| 输出分辨率 | **1600 × 1200**（4:3） | gs-pipeline/3DGS 建议 ≤1600 |
| fx = fy | **1148.343 px**（= 6.888 / (9.6/1600)） | 与 82.1° 对角 FOV 自洽 |
| cx, cy | 800.0, 600.0 | 主点居中 |
| 光圈 | f/1.7（不参与渲染，仅记录） | DJI 官方 |

UE 端：`SceneCaptureComponent2D.fov_angle = 69.726°`（UE 的 FOVAngle 对 4:3 目标即水平 FOV），
`capture_source = SCS_FinalColorLDR`，手动 `capture_scene()` + `RenderingLibrary.export_render_target()` 存 PNG。

## 5. 航线（五向倾斜摄影）

- 面积 ±45 m（90×90 m），5 个航向 yaw = 0°/72°/144°/216°/288°，云台俯仰 -45°~-55°，
  航高 36–44 m（3600–4400 cm）。
- 每个航向 7 条航线 × 5 拍摄点 = 35 帧 ⇒ **175 训练视角**。
- 实测重叠率（不同俯仰角不同，数值写在 metadata 的 `flight.passes`）：
  旁向 **61.7%–73.1%**（目标 65–75%），航向 **69.0%–80.4%**（目标 75%）。
- 额外 **15 个留出验证视角**（随机位置/航向/俯仰，与训练位姿保持 ≥5 m 水平距离或 ≥4 m 高度差），
  写入 `data/synthetic/val/`，不参与训练。

## 6. 输出格式（与 `shared/CONVENTIONS.md` 一致）

```
data/synthetic/capture/
  images/0001.png ... 0175.png      # 训练视角 1600x1200 PNG
  metadata.json                     # 175 帧
data/synthetic/val/
  images/val_0001.png ... val_0015.png
  metadata_val.json                 # 15 帧
```

`metadata.json` 顶层字段：`dataset / camera_model / width / height / fx / fy / cx / cy /
coord_system / origin_wgs84 / frames`，另附说明性字段 `sensor_mm / focal_mm / equivalent_focal_mm /
fov_deg / units / generator / flight / notes`（不改变既有字段语义）。每帧：

```json
{
  "file": "images/0001.png",
  "c2w": [16 floats, row-major],
  "gps": {"lat": 39.9042, "lon": 116.4074, "alt": 83.0},
  "gimbal_deg": {"yaw": 0.0, "pitch": -45.0, "roll": 0.0},
  "timestamp": 0.0
}
```

**坐标约定（关键）**

- UE 世界：左手系，+X 前、+Y 右、+Z 上，单位 cm。
- 相机坐标系（c2w 的**列**）：**forward / right / up**（+X 前 / +Y 右 / +Z 上），与 UE 相机轴一致。
- `c2w` = 4×4 **行主序**（row-major, 16 个数）：
  ```
  [ fwd.x  right.x  up.x  t.x ]
  [ fwd.y  right.y  up.y  t.y ]
  [ fwd.z  right.z  up.z  t.z ]
  [ 0      0        0     1   ]
  ```
  即 `P_world = R_c2w · P_cam + t`；`c2w[i]` 展平后索引为 `[fwd.x, right.x, up.x, t.x, fwd.y, ...]`。
- 投影公式（本仓库 `check_dataset.py` / `validate_reprojection.py` 使用）：
  `d = (dx,dy,dz) = (forward·(P−t), right·(P−t), up·(P−t))`，
  `u = cx + fx·dy/dx`，`v = cy − fy·dz/dx`。
- 模拟 GPS：固定 WGS84 原点（39.9042, 116.4074, 43 m），**UE +X → 东**、**UE +Y → 南**、
  **UE +Z → 天**（北 = −Y）。`alt = 43 + z_cm/100`。
- 与 COLMAP 的换算（右手系 X 右/Y 下/Z 前）见 `shared/CONVENTIONS.md` §3：世界先翻 Y
  `p_w = (x, −y, z)`，相机轴 `fwd=(1,0,0), right=(0,−1,0), up=(0,0,1)`，再组 `R_wc/R_cw`。
- `gimbal_deg.pitch` 为 DJI 习惯的负值（向下为负），与 UE 相机 Actor 的 pitch 相同。

## 7. 关键实现注意（踩坑，详见 RESULTS.md §6）

1. 启动 UE 时 `-ExecutePythonScript=` 的值必须用**正斜杠**路径（UE 会吃掉反斜杠转义）。
2. UNREAL 5.8 的 Python 类名受 `ScriptName` 影响：`unreal.MaterialLibrary` / `unreal.RenderingLibrary`；
   `ASceneCapture2D` 组件属性名 `capture_component2d`。
3. **必须先 `unreal.MaterialEditingLibrary.get_statistics(material)` 同步编译材质再渲染**，
   否则同 tick 内渲染会用默认灰材质（纯色无纹理）。
4. SceneCapture 的自动/手动曝光参数不生效（EyeAdaptation flag 关闭时被强制），画面亮度用**灯光强度**控制。
5. PowerShell 执行策略需 `-ExecutionPolicy Bypass`；`Tee-Object` 缓冲日志。

## 8. 已知限制

- 单帧光栅、无 TAA 历史、无镜头畸变参数（DJI 直出已做镜头校正）。
- 画面偏亮（mean≈0.556 / p95≈0.90）；部分地面接近高光；低模程序化几何，窗户为贴图。
- 无 Lumen/GI，阴影区用补光近似环境光；未输出深度/法线图。
- 验证集与训练集同场景不同位姿（留出评估用），非独立场景。
- 场景每次运行重建（不保存 .umap），保证确定性但重复运行时多花约 7–9 s。
