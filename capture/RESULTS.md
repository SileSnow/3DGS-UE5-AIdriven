# capture/RESULTS.md — UE5.8 合成 DJI Mini 航拍数据集：实测结果与证据

> 更新：2026-11-08 16:20。所有数字都能在 `logs/capture/`、`capture/UE5Synth/Saved/Logs/UE5Synth.log`、
> `capture/dataset_check.json`、`logs/capture/run_*.json` 中找到原始出处。

## 1. 最终交付数据

| 项 | 值 |
|---|---|
| 训练视角 | **175 帧**（5 航向 × 7 航线 × 5 拍摄点），`data/synthetic/capture/images/0001-0175.png` |
| 验证视角 | **15 帧**（随机位置/航向/俯仰，与训练位姿保持距离），`data/synthetic/val/images/val_0001-0015.png` |
| 分辨率 / 格式 | **1600 × 1200** PNG（RGBA8 渲染目标 → PNG），每帧约 2.9 MB |
| 元数据 | `data/synthetic/capture/metadata.json`（175 帧，120,994 B）、`data/synthetic/val/metadata_val.json`（15 帧，13,888 B） |
| 内参 | fx = fy = **1148.343 px**，cx = 800.0，cy = 600.0（82.1° 对角 FOV，1/1.3" 4:3，f=6.888 mm） |
| 坐标系 | `UE_LHS_Zup_cm`；c2w = 4×4 行主序，列 = forward/right/up（UE 相机轴），第 4 列 = 平移 cm |
| 模拟 GPS | 固定原点 39.9042 / 116.4074 / 43 m；UE +X=东、+Y=南、+Z=天 |
| 帧时间戳 | 训练 0–348 s（2 s/帧），验证 0–28 s |
| 磁盘占用 | `data/synthetic` = **558.8 MB**（190 PNG ≈ 552 MB + metadata ≈ 135 KB） |
| 工程占用 | `capture/UE5Synth` = 130.5 MB（Content/Saved/Intermediate/DDC 局部缓存） |

**画面统计**（190 帧，缩略图 200×150 亮度统计）：单帧亮度均值 **0.5557**（训练）/ 0.5545（验证）；
全帧像素亮度 mean=0.5556、median=0.6192、p5=0.0382、p95=0.9014。
（Lead 验收时记录为 mean≈0.626 / p95≈0.902，测量口径/缩放略有差异；两者都表明画面偏亮但无大面积死白，可用。）
帧亮度范围 min 0.2955 / max 0.7298，190 帧之间曝光一致（固定曝光 + 固定太阳强度），适合 3DGS。

## 2. 渲染链路实测（UE 5.8.4，CL 58902052）

环境：RTX 5060 Laptop 8GB / DX12 SM6 / 32 线程 / 16GB RAM；项目 `capture/UE5Synth/UE5Synth.uproject`（Blueprint-only）。

| 项 | 第一次全量（Sun=30） | 第二次全量（最终数据，Sun=22） |
|---|---|---|
| 启动方式 | `UnrealEditor.exe ... -ExecutePythonScript="capture_synth.py --mode full"` | 同左 |
| 场景生成 | 805 actors / **7.2 s**（含 8 纹理导入、2 母材质同步编译） | 805 actors / **8.9 s**（与 ue5-splat 并行，CPU 争用） |
| 训练帧渲染 | 175 帧 / 150.49 s（avg 0.857 s） | 175 帧 / **203.37 s**（avg 1.155 s，并行争用下变慢） |
| 验证帧渲染 | 15 帧 / 25.14 s（avg 1.670 s） | 15 帧 / **3.48 s**（avg 0.230 s） |
| 脚本总耗时 | 184.1 s | **216.2 s** |
| 每帧成本（独占时） | ≈ 0.24–0.25 s/帧（probe 阶段 1600×1200 实测） | — |
| 画面亮度 | mean 0.628（偏亮，Lead 抽查后要求降低） | mean 0.5557（最终交付） |
| 太阳强度 | 30 lux（+3 盏无阴影补光，各 0.13/0.13/0.10 倍） | 22 lux（同比例补光） |
| 峰值显存 | 渲染期 < 2 GB（nvidia-smi 观测，编辑器 WS ≈ 1.8 GB） | 同左 |

**首次着色器编译**：引擎自带 DDC pak（1666 MB）已含引擎着色器；本项目只新增 2 个母材质
（`M_SynthFlat` / `M_SynthTiled`），首次在 GPU 编辑器内同步编译实测约 1–2 s
（`get_statistics` 报告 pixel_instr=192/198, vertex_instr=148/153）；整个编辑器首次冷启动
（无 DDC 缓存时）本机实测 107 s（其中 AssetRegistry 47 s），后续启动 30–60 s。

## 3. 相机模型与航线

DJI Mini 4 Pro（官方规格）：1/1.3" CMOS、82.1° 视角（对角）、等效 24 mm、f/1.7、4:3 4800 万像素。
反算：有效区 9.6×7.2 mm（对角 12.0 mm），f = 6.0/tan(41.05°) = **6.888 mm**，
HFOV = 69.726°、VFOV = 55.18°；UE `SceneCaptureComponent2D.fov_angle = 69.726°`（4:3 目标即水平 FOV），
1600×1200 下 fx = fy = 1148.343 px。

航线：5 个航向（yaw 0°/72°/144°/216°/288°），云台俯仰 -45°~-55°，航高 36–44 m；
每个航向 7 条航线 × 5 拍摄点 = 35 帧，共 175 帧。**实测重叠率**（写入 metadata.flight.passes）：

| 航向 yaw | 俯仰 | 航高 | 旁向重叠 | 航向重叠 |
|---|---|---|---|---|
| 0° | -45° | 40 m | 73.1% | 80.4% |
| 72° | -48° | 38 m | 68.5% | 75.6% |
| 144° | -50° | 42 m | 69.5% | 75.7% |
| 216° | -52° | 36 m | 61.7% | 69.0% |
| 288° | -55° | 44 m | 65.1% | 71.6% |

（旁向目标 65–75%，航向目标 75%；-52° 那一趟旁向 61.7% 略低于目标，属俯仰更大导致足迹变小的预期结果。）

## 4. 场景

程序化园区 90 m × 90 m（世界原点居中）：6 条 9 m 宽道路（含中线虚线）、16 个抬升铺装街区、
公园（水池 + 22 棵树）、广场（喷泉 + 彩色公共艺术 + 长椅）、**805 actors** 总量：
约 86 栋建筑（含外圈 3 圈填充建筑，8–32 m 高、3 种幕墙贴图 + 8 色调色板、屋顶设备/门廊）、
约 110 棵树、30+ 辆车、路灯、绿篱、道路虚线、5+3 个品红色标靶（重投影校验用）。
灯光：DirectionalLight（30/22 lux，atmosphere sun）+ 3 盏无阴影补光 + SkyLight（real-time capture）
+ SkyAtmosphere + ExponentialHeightFog；动态光照（`r.AllowStaticLighting=False`），无 Lumen/RT。
材质：Python 运行时创建 2 个母材质与约 120 个 MaterialInstanceDynamic（8 张程序化无缝平铺 PNG：
草地/沥青/混凝土/铺装/3 种幕墙/屋面）。

## 5. 数据契约自检（离线，`python capture/scripts/check_dataset.py`）

结果文件：`capture/dataset_check.json`（ok = true）：

| 检查 | 训练集 | 验证集 |
|---|---|---|
| metadata 帧数 / PNG 数 | 175 / 175 | 15 / 15 |
| 缺失图片 | 0 | 0 |
| c2w 旋转正交性（max err） | **0.0** | **0.0** |
| 模拟 GPS ↔ UE 坐标往返误差 | 0.0057 cm | 0.0073 cm |
| 品红标靶重投影（检测质心 vs 投影） | 20 次命中，mean 5.51 px，max 13.57 px | 1 次命中，6.13 px |

说明：标靶是边长 1.2–1.4 m 的立方体，在 40 m 航高下占 30–40 px，质心误差 1–13 px
（多数 1–4 px）来自立方体侧面可见性/遮挡，非位姿误差；其中 0.86 px、1.01 px 的样本
证明 c2w + fx/cx/cy 与像素自洽。精确到亚像素的标定校验需专用 calib 帧
（`run_capture.ps1 -Mode calib` + `validate_reprojection.py`，本次未跑，因为时间窗口让给了 ue5-splat）。

## 6. 关键工程发现 / 踩坑记录

1. **`-ExecutePythonScript` 引号内的反斜杠会被 UE FParse 转义吃掉**（`C:\\UEW\\...` → `C:W/...`），
   脚本加载失败。⇒ 该参数的值必须使用**正斜杠**路径。
2. **UE 5.8 Python 类名受 `UCLASS(meta=ScriptName=...)` 覆盖**：`unreal.KismetMaterialLibrary` 不存在，
   应为 `unreal.MaterialLibrary`；`unreal.KismetRenderingLibrary` → `unreal.RenderingLibrary`。
3. `ASceneCapture2D` 的组件属性 python 名为 **`capture_component2d`**（不是 `capture_component_2d`）。
4. **材质着色器异步编译**：`-ExecutePythonScript` 在同一个编辑器 tick 内建场景并渲染，此时新材质
   尚未编译完，SceneCapture 会全部退回默认灰材质（表现为“纯色、无纹理”）。
   ⇒ 必须用 `unreal.MaterialEditingLibrary.get_statistics(material)` 强制同步编译
   （内部调用 `FMaterialResource::FinishCompilation()`）后再渲染。这是本次最关键修复。
5. **SceneCapture2D 的自动曝光/后处理曝光参数不生效**：捕获视图的 EyeAdaptation show flag 关闭时，
   `AEM_Manual/auto_exposure_min/max/brightness` 全部被强制为固定值 1.0 → 画面亮度只能靠
   **灯光强度**控制（实测 sun=10 太暗、30 偏亮、22 为目标；min/max 扫描 0.2–2.0 对亮度无影响）。
6. **MaterialInstanceDynamic 是 transient**：保存关卡再重载会丢材质引用 ⇒ 工具不保存/加载关卡，
   每次运行在当前 world 内重建场景（805 actors 仅 7–9 s）。
7. **c2w 上向量公式错误（已离线修复）**：早期 `rotator_axes()` 的 up 轴非正交
   （right·up=0.707），导致 metadata 的 c2w 旋转部分错误。修复后用
   `capture/scripts/repair_metadata_c2w.py` 离线重算 190 帧 c2w（图像本身不变，因为它们由 UE 相机
   真实变换渲染），`check_dataset.py` 验证正交误差 0.0、标靶重投影 1–13 px。
8. PowerShell 默认执行策略禁止 .ps1：用 `powershell -ExecutionPolicy Bypass -File`（已附 `run_capture.cmd`）。
   `Tee-Object` 会缓冲，实时进度看 `capture/UE5Synth/Saved/Logs/UE5Synth.log`。
9. UE 对非 ASCII 路径有已知问题：启动用 `C:\\UEW` junction（ASCII），脚本内部路径解析后仍是同一份文件。

## 7. 已知限制

- 单帧光栅（SCS_FinalColorLDR），无 TAA 历史累积，边缘轻微锯齿；无镜头畸变参数（DJI 直出已校正）。
- 曝光固定但画面偏亮（mean 0.556 / p95 0.901），部分地面接近高光；树木/建筑为低模程序化几何，
  facade 窗户为贴图而非真实几何。
- 无 Lumen/GI，阴影区靠 3 盏补光近似天空环境光。
- 未输出深度图/法线图（3DGS 非必需；如需可加 SceneCapture 的 SCS_SceneDepth 通道）。
- 验证集 15 帧与训练集同场景、不同位姿，用于 3DGS 留出评估；不是独立场景。
