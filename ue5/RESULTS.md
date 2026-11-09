# UE 5.8.4 × 3DGS 渲染集成与性能验证（RESULTS，最终版）

> 执行：ue5-splat，2026-11-08。环境：Windows 11 26200 / AMD Ryzen 9 8945HX (16C/32T) / 16GB RAM /
> NVIDIA RTX 5060 Laptop 8GB (sm_120) / UE 5.8.4 (CL 58902052) / VS 2026 MSVC 14.50。
> 所有数字可在 logs/ue5/ 与 ue5/results/ 找到原始出处；UE 运行全程限制 4 逻辑核 + BelowNormal 优先级。

## 1. 结论摘要

| 项 | 状态 | 证据 |
|---|---|---|
| 开源插件移植到 UE 5.8.4 并编译通过 | ✅ 成功 | UnrealEditor-GaussianSplattingRuntime.dll / -GaussianSplattingEditor.dll；构建日志 logs/ue5/build_ue5_8_editor2.log（Result: Succeeded，增量 147.7s） |
| 运行时 PLY 解析（标准 3DGS 字段，含 f_rest） | ✅ 成功 | 自研 C++ parser，50k=6.4ms(nanrhi)/65ms; 109k=53ms; 与 Python numpy 逐字段一致 |
| gs-pipeline 真实训练 PLY 互操作 | ✅ 成功 | 109,376 splats / 25.9MB，属性顺序非标准（f_rest 在 opacity 前）仍正确解析（见第 5 节） |
| UE 中显示 PLY 内容（Path B：点云预览） | ✅ 成功 | ue5/results/final_v2/（v2 鲁棒取景：近景/中景/俯视/环绕 + UE vs CPU 对比图）；ue5/results/final/（v1） |
| Niagara 3DGS splat 渲染 | ⚠️ 部分成功（可见但尺度错） | ue5/results/final/niagara_attempt_best.png；scale 失配未解决（见第 6 节） |
| 性能测试（Niagara 路径吞吐） | ✅ 有数据（口径见 7 节） | perf_50k/200k metrics.json |
| 环绕视频帧 / 真实 PLY 视频 | ⏳ 功能已编译（-SplatOrbitFrames），本轮时间盒内未跑成片 | — |

**一句话**：3DGS PLY 可以在 UE 5.8 中"进得来、看得见"（Path B 已验证并出图）；Italink 的 Niagara GPU splat 渲染器
在 5.8 下能运行（粒子/数据接口/着色器链路打通），但 **splat 尺寸/单位与我们的数据不匹配**导致画面呈巨大覆盖，
该问题已定位到单位换算层，未在本次时间盒内解决。

## 2. 交付物

~~~
ue5/DJI3DGS_UE/          UE 5.8.4 C++ 工程（Source/DJI3DGS_UE + 移植插件 Plugins/GaussianSplattingForUnrealEngine）
ue5/Scripts/             build.ps1 / run_headless.ps1 / bench.ps1 / gen_test_ply.py / render_ply_reference.py /
                         compose_final_figures.py / env_check.ps1
ue5/test_data/           合成 PLY：sphere 50k/200k/500k/1M、terrain 200k、axis 6k
ue5/results/final/       ★ 最终交付图（见第 3 节）
ue5/results/*/           各次运行：metrics.json + frames.csv + gpu_samples.csv + screenshots/
ue5/docs/UE5_3DGS方案调研.md  开源/商业/DJI Terra/Cesium 方案调研（带来源链接）
ue5/_vendor/ItalinkGsplat/     jsDelivr 拉取的原始插件源码快照（可追溯）
ue5/_research/           GitHub API 搜索结果与仓库文件树缓存
logs/ue5/                编译/运行日志
~~~

## 3. 最终图（ue5/results/final/）

| 文件 | 内容 | 说明 |
|---|---|---|
| pathb_real_ply_view_00..03.png | 真实训练 PLY（109,376 splats）在 UE viewport 的 4 个环绕视角 | Path B：debug point 点云预览（非 splatting 光栅化） |
| pathb_real_ply_4views_grid.png | 上述 4 视角 2x2 拼图 | 报告用 |
| pathb_sphere_50k_debug.png | 合成球 50k splats 的点云预览（彩色球面） | 与 CPU 参考渲染颜色/形状一致 |
| comparison_ue_vs_reference.png | 左：UE Path B 截图；右：CPU 参考投影（numpy） | 同机位对比，验证坐标/颜色/尺度正确 |
| reference_real_capture_cpu_yaw0.png | CPU 参考渲染（109k PLY） | 由 Scripts/render_ply_reference.py 生成 |
| niagara_attempt_best.png | Niagara splat 渲染尝试（scale×0.1） | 可见金色高斯团，但 splat 尺寸/位置错误 |
| niagara_attempt_small_scale.png | Niagara scale×0.01 | 散点状，证明粒子确实在渲染 |


### 3.1 v2 最终图（鲁棒取景，报告核心图）

首版 4 视角因 PLY 含离群点（min/max bounds radius=16585cm）导致相机过远（36487cm）、画面很小。
v2 改为 **2%-98% 分位数鲁棒取景 + 相机距离 clamp 12000-16000cm**，并按"近景/中景/俯视/环绕"四个预设机位重跑
（gs-pipeline 最终 PLY，109,376 splats，mtime 16:49）：

- ue5/results/final_v2/screenshots/view_00..03.png（1280x720，近景/中景/俯视/环绕）
- ue5/results/final_v2/ue_pathb_4views_grid_v2.png（2x2 拼图）
- ue5/results/final_v2/comparison_ue_vs_reference_v2.png（左 UE vs 右 CPU 参考，同机位）
- ue5/results/final_v2/reference/ref_view_00..03.png（numpy 参考渲染）
- 同步副本：ue5/results/final/v2_view_00..03.png、comparison_ue_vs_reference_v2.png、ue_pathb_4views_grid_v2.png

鲁棒取景结果：center=(258.1,-21.8,1378.8)、robustRadius=9325.9、cameraDistance=16000（clamp），
109,376 splats 解析 28.2ms / SetPoints，4 核下端 30.8fps @1280x720。
注：场景本身颜色偏白（capture-synth 合成场景的材质/曝光所致），UE 与参考渲染一致。

## 3.2 v1 图（保留）

## 4. 编译与移植（UE 5.5 → 5.8.4）

### 4.1 编译结果

- 命令：Build.bat DJI3DGS_UEEditor Win64 Development -Project=C:/UEW/dji_ue5_3dgs/ue5/DJI3DGS_UE/DJI3DGS_UE.uproject -WaitMutex
- 首次全量（UBA，多核）：Result: Succeeded，147.7s；增量：33.3s / 11.5s
- 产物：Binaries/Win64/UnrealEditor-DJI3DGS_UE.dll；Plugins/.../Binaries/Win64/UnrealEditor-GaussianSplattingRuntime.dll、-GaussianSplattingEditor.dll

### 4.2 UE 5.8 API 适配（3 类改动）

1. UPackage::SavePackage 9 参重载在 5.8 改为 4 参 + FSavePackageArgs（插件 5 处：
   GaussianSplattingEditorLibrary.cpp:558/672、GaussianSplattingEditorModule.cpp:108/146、GaussianSplattingStep.cpp:913）。
2. UHLODBuilderSettings::GetCRC 在 5.8 被标 final，插件的 override 改名 GetGaussianSplattingCRC。
3. .uplugin 增加 EngineVersion 5.8.0；Runtime 模块 Niagara/NiagaraShader 依赖保持。

其余为 C4996 警告（UStaticMesh::ImportVersion、FHLODBuildContext::World），不影响。

### 4.3 两个关键环境坑（都已解决，写进复现脚本）

1. **非 ASCII 路径**：工作目录含中文（GAIA项目），MSVC 14.5/UBA 把路径拆断报 C1083。
   解决：ASCII junction C:\UEW → C:\Users\<user>\Desktop\GAIA项目，编译/运行一律用 C:/UEW/...
   （证据：logs/ue5/build_blank.log 失败 vs build_ue5_8_editor2.log 成功）。
2. **UE 5.8 命令行工程路径必须在第一个 token**：UnrealEditor.exe -game <uproject> 会报
   "Running engine without a game"；正确为 UnrealEditor.exe "<uproject>" -game ...（LaunchEngineLoop.cpp
   ParseGameProjectFromCommandLine 只看第一个 token）。证据：results/run_sphere50k_first/ue5_run.log。

## 5. 运行时 PLY 解析器与互操作性

自研 FSplatPLYLoader（Source/DJI3DGS_UE/Private/SplatPLYLoader.cpp）：

- 解析 binary_little_endian 1.0，按 header 的 property **名字**建字段索引（不假设顺序），
  要求 x y z scale_0..2 rot_0..3 opacity f_dc_0..2；f_rest_0..44 解析但暂不使用（仅 SH DC 颜色）。
- 解码：scale=exp(log_s)，rot=(w,x,y,z)=(rot_0..3) 归一化，color=Linear(SH_C0*f_dc+0.5)，alpha=sigmoid(opacity)。
- 两种坐标模式：-SplatUECoords=1（UE 坐标/厘米，本次全程使用）或 0（COLMAP/graphdeco 米制 → UE：pos=(x,-z,-y)*100）。

### 5.1 调试记录：ReadFloat stride bug（重要）

首次 nullrhi 冒烟 bounds 异常（1e37）→ dump 原始字节对比发现：ReadFloat(Base, Index, Stride) 把"属性个数 62"
当字节 stride 传入（应为 4），导致 x 之后所有字段读偏移。修复为 Row + Index*sizeof(float) 后，
point0 pos=(260.987,134.650,383.036) scale=(4.098,5.450,8.707) 与 Python 原始字节完全一致。
证据：results/smoke_nullrhi*/smoke.log 的 [SPLATLOAD] 行。

### 5.2 真实训练 PLY 兼容性（gs-pipeline 产出）

文件 data/trained/_densify_test/gaussians_best.ply（29,895 splats / 7.07MB）属性顺序为
x,y,z,nx,ny,nz,f_dc_0..2,**f_rest_0..44,opacity,scale_0..2,rot_0..3**（opacity 索引 54、scale_0 索引 55，
与 graphdeco 常见顺序不同）。按名字索引的解析器**前 10 个 splat 的 xyz/opacity/scale 与 Python numpy 逐值一致**，
bounds 完全一致：(-5291.5,-5234.8,-2080.3)..(4894.9,5452.3,3985.8)，center=(-198.3,108.8,952.8)。
判定数据为 UE 坐标/厘米 → 使用 -SplatUECoords=1。证据：results/real_ply_nullrhi/smoke.log。

最新训练产物 data/trained/capture/run1/gaussians_best.ply（109,376 splats / 25.9MB）同样解析通过：
parse 53.3ms、SetPoints 37.0ms、可见 splat 21,874（屏幕尺寸剔除后）。

## 6. 渲染路径状态

### 6.1 移植插件（Italink，Niagara GPU 粒子）——部分工作

已打通：插件 Runtime/Editor 模块加载；Niagara 资产 NS_GaussianSplattingPointCloud 加载；
自定义 DataInterface 覆盖（PointCloud + FeatureCurve）；系统编译（needsCompile→ready=1）；
late activation 修复（等 system ready 后 Activate+ReinitializeSystem）后 compActive=1、instanceCtrl=1；
**Niagara 粒子确实渲染出画面**（scale 调整实验中可见金色高斯团/散点）。

未解决：默认数据下 splats **尺寸/单位失配**——画面被巨大的半透明 splat 覆盖（整屏橄榄色）。
对照实验：-SplatScaleMul=0.1 / 0.01、-SplatPosMul=0.01 均能看到粒子但形态不正确
（疑似插件 NS 期望输入单位为米，而我们的 PLY 是厘米；或粒子 sprite 尺寸换算与 3DGS scale 语义不一致）。
这属于"资产内部单位契约"问题，需要反编译/可视化 NS 图或重保存插件资产后继续调，本次时间盒内未完成。

### 6.2 Path B（回退方案）——成功

用 UE 的 DrawDebugPoint 按 splat 中心 + 颜色绘制点云（一次性持久化），用 viewport 截图（FScreenshotRequest）
出图：真实训练 PLY 109k splats 在 UE 中 4 个视角可见，形状/颜色与 CPU 参考渲染一致；
合成 50k 球与参考渲染一致。明确标注：这是**点云预览，不是 3DGS splatting 光栅化**。

另发现两个截图管线事实（对后续工作有用）：
- SceneCapture2D + RT 读回可以渲染有材质的几何与 Niagara，但**不包含 DrawDebug 线批**；
- FScreenshotRequest viewport 截图可以包含 debug 几何，适合 Path B 交付。

## 7. 性能数据

> 口径：-game + RHI（DX12 SM6），1280x720，4 逻辑核 + BelowNormal，warmup 5s 后测 5s 帧时间；
> GPU 显存由 nvidia-smi 500ms 采样（本轮 gpu 字段未合并进 metrics，见各目录 gpu_samples.csv）。
> 注意：perf_50k/200k 的 FPS 是在 **Niagara splat 尺寸失配（画面不可用）** 状态下测得，只代表该管线吞吐，
> 不能当作"3DGS 正确渲染"的性能。

| run | splats | PLY MB | parse ms | SetPoints ms | avg FPS | avg frame ms | p99 ms | CPU 深度排序 ms | 说明 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| final_pathb（点云预览） | 109,376 | 25.9 | 53.3 | 37.0 | 28.6 | 34.9 | 47.6 | 21.8 | 109k debug 点云，4 核 |
| perf_50k（Niagara 吞吐） | 50,000 | 11.8 | 65.5 | 9.8 | 95.4 | 10.5 | 21.6 | 6.1 | 画面不可用（splat 过大） |
| perf_200k（Niagara 吞吐） | 200,000 | 47.3 | 108.8 | 38.6 | 104.7 | 9.6 | 17.0 | 30.4 | 同上 |
| nullrhi 功能冒烟（参考） | 50,000 | 11.8 | 6.4 | 9.4 | — | — | — | 4.2 | 无 RHI，仅功能验证 |

原始数据：ue5/results/{final_pathb,perf_50k,perf_200k}/metrics.json、frames.csv、gpu_samples.csv。

## 8. 能力边界与已知限制

1. **Niagara splat 尺度失配**（最关键）：插件 NS/材质期望的尺度单位与我们的 PLY（UE 厘米）不匹配，
   splat 渲染过大/位置发散；修复需要重存插件资产（完整编辑器）或改 NS 内部模块。
2. **颜色仅 SH DC**：不使用 f_rest（SH 1-3 阶），无视角相关高光；Path B 点云预览颜色已与参考一致。
3. **Path B 是点云预览**（DrawDebugPoint），非 3DGS 光栅化：无各向异性/透明度混合，仅验证"数据进 UE + 坐标/颜色正确"。
4. **场景截图口径**：SceneCapture2D 不含 debug 线批；本次交付图用 viewport 截图（FScreenshotRequest）。
5. **性能口径**：4 核限载下测得；Niagara perf 两档画面不可用，仅作吞吐参考；1M 档未跑（时间盒）。
6. **未实现**：环绕视频成片（orbit 帧功能已编译进 C++，未跑；gs 新 PLY 的最终截图待补一次）。

## 9. 复现命令

~~~powershell
# 环境自检（引擎/插件/DLL/test_data/GPU/进程）
pwsh -File ue5/Scripts/env_check.ps1
# 编译（必须存在 C:\UEW junction）
pwsh -File ue5/Scripts/build.ps1
# Path B：真实训练 PLY 点云预览（4 视角 viewport 截图）
pwsh -File ue5/Scripts/run_headless.ps1 -Ply C:/UEW/dji_ue5_3dgs/data/trained/capture/run1/gaussians_best.ply -OutDir C:/UEW/dji_ue5_3dgs/ue5/results/final_pathb -NoNiagara 1 -DebugPoints 1 -ViewportShots 4 -Shots 0
# Niagara 路径（当前 scale 失配，仅用于复现问题）
pwsh -File ue5/Scripts/run_headless.ps1 -Ply C:/UEW/dji_ue5_3dgs/ue5/test_data/sphere_50k.ply -ViewportShots 2 -Shots 0
# 性能扫（50k/200k/500k/1M）
pwsh -File ue5/Scripts/bench.ps1 -RunName bench_1
# 最终交付图重生成
python ue5/Scripts/compose_final_figures.py
~~~

## 10. 日志索引

| 路径 | 内容 |
|---|---|
| logs/ue5/build_blank.log | 中文路径 C1083 失败证据 |
| logs/ue5/build_ue5_8_editor.log / build_ue5_8_editor2.log | 5.8 适配后编译成功（147.7s） |
| logs/ue5/build_*.log | 各轮增量编译 |
| ue5/results/smoke_nullrhi*/ | 功能冒烟 + ReadFloat stride bug 定位 |
| ue5/results/real_ply_nullrhi/ | 真实 PLY 解析互操作验证 |
| ue5/results/pathb_ctrl/ | Path B 首次成功（球 + 文字 + debug 点） |
| ue5/results/final_pathb/ | 109k 真实 PLY 四视角 + metrics |
| ue5/results/perf_50k, perf_200k/ | Niagara 吞吐性能档 |
| ue5/results/ctrl2, splat2, nia_*/ | 黑屏排查、单位对照实验 |