# ue5/ — UE 5.8 3DGS 渲染集成与性能验证

> 负责人：ue5-splat。任务：把 3DGS（Gaussian Splatting）PLY 在 UE 5.8.4 中渲染出来，并给出可复现的性能数据。

## 目录结构

```
ue5/
  DJI3DGS_UE/                     # UE 5.8.4 C++ 工程（从 Templates/TP_Blank 复制改造）
    Source/DJI3DGS_UE/            #   项目模块：自研 PLY parser + 测试 Actor + GameMode
    Plugins/GaussianSplattingForUnrealEngine/  # 移植的 Italink 开源插件（MIT，UE 5.5 → 5.8）
    Config/DefaultEngine.ini      #   GameDefaultMap=/Engine/Maps/Entry + SplatTestGameMode
  Scripts/
    build.ps1                     # UBT 编译（必须走 ASCII junction C:\UEW）
    run_headless.ps1              # 无头 -game 跑一个 PLY：截图 + metrics.json + 显存采样
    bench.ps1                     # 50k/200k/500k/1M 性能扫，汇总 summary.md
    gen_test_ply.py               # 生成合成 3DGS PLY（球/地形/坐标轴校验）
    env_check.ps1                 # 环境自检（引擎/插件/DLL/GPU/进程）
  test_data/                      # 合成测试 PLY（sphere_50k ... sphere_1000k, terrain_200k, axis_6k）
  results/<run>/                  # metrics.json + frames.csv + gpu_samples.csv + screenshots/*.png
  docs/UE5_3DGS方案调研.md         # 开源/商业/DJI 官方链路/Cesium 方案调研
  RESULTS.md                      # 实际实测结果、命令、日志路径、能力边界与已知伪影
  _vendor/ItalinkGsplat/          # 从 jsDelivr 拉取的原始插件源码快照（可追溯）
  _research/                      # GitHub API 搜索结果与仓库文件树缓存
```

## 关键约束：非 ASCII 路径

工作目录 `C:\Users\<user>\Desktop\GAIA项目\...` 含中文，MSVC 14.5 / Unreal Build Accelerator 会把
`C:/Users/.../GAIA` 与 `项目/...` 拆断报 `C1083`。因此**编译与运行 UE 必须走 ASCII junction**：

```
C:\UEW  ->  C:\Users\<user>\Desktop\GAIA项目
```

源码仍然编辑 workspace 里的真实文件（junction 是同一份文件，无副本）。

## 快速开始

```powershell
# 0) 环境自检（引擎版本、插件、DLL、test_data、GPU、其它 UE 进程）
pwsh -File ue5/Scripts/env_check.ps1

# 1) 编译（首次全量约 2-4 分钟；增量 ~1 分钟）
pwsh -File ue5/Scripts/build.ps1
pwsh -File ue5/Scripts/build.ps1 -Clean      # 需要彻底重编时

# 2) 生成合成 PLY（已生成过可跳过）
python ue5/Scripts/gen_test_ply.py --all --outdir ue5/test_data

# 3) 单次运行：加载 PLY → 环绕相机 → 截图 + metrics
pwsh -File ue5/Scripts/run_headless.ps1 -Ply C:/UEW/dji_ue5_3dgs/ue5/test_data/sphere_50k.ply
#    注意：UE RHI 渲染必须串行；脚本发现其它 UnrealEditor 进程会拒绝启动（-Force 可覆盖）

# 4) 性能扫（50k/200k/500k/1M）
pwsh -File ue5/Scripts/bench.ps1 -RunName bench_1
```

## 运行时 harness（Source/DJI3DGS_UE）

- `SplatPLYLoader`：纯 C++ 运行时 PLY 解析（`binary_little_endian`，标准 3DGS 字段
  `x y z nx ny nz f_dc_0..2 f_rest_0..44 opacity scale_0..2 rot_0..3`）。
  两种坐标模式：`-SplatUECoords=1`（PLY 已是 UE 坐标/厘米，见 `shared/CONVENTIONS.md`）或
  `-SplatUECoords=0`（COLMAP/graphdeco 米制，自动转 UE：`pos=(x,-z,-y)*100`）。
  解码：`scale=exp(log_s)`，`rot=(w,x,y,z)=(rot_0,rot_1,rot_2,rot_3)` 归一化，
  `color=sRGB→Linear(SH_C0*f_dc+0.5)`，`alpha=sigmoid(opacity)`；SH 高阶（f_rest）解析但暂不使用。
- `ASplatTestActor`：运行时建 `UGaussianSplattingPointCloud` → 加载插件 Niagara 系统
  `/GaussianSplattingForUnrealEngine/Niagara/NS_GaussianSplattingPointCloud` → 覆盖 `PointCloud`/`FeatureCurve`
  数据接口 → GPU 粒子渲染。环绕相机、SceneCapture2D 出 PNG、帧时间/CPU 前端/深度排序计时、metrics.json 落盘。
- `ASplatTestGameMode`：把 `ASplatTestActor` 设为 ViewTarget；DefaultPawnClass=null。

命令行参数（`run_headless.ps1` 已封装）：

| 参数 | 默认 | 说明 |
|---|---|---|
| `-SplatPly=` | 必填 | 输入 PLY |
| `-SplatOutDir=` | `<Project>/Results/<runId>` | 输出目录（metrics/frames/screenshots） |
| `-SplatUECoords=` | 1 | 1=UE 坐标/厘米；0=COLMAP/米 |
| `-SplatScale=` | 0（不额外缩放） | 统一缩放系数 |
| `-SplatWarmup=` / `-SplatMeasure=` | 6 / 8 | 预热/测量秒数 |
| `-SplatShots=` | 2 | 截图数量（环绕不同角度） |
| `-SplatOrbitSpeed=` | 12 | 环绕角速度（度/秒） |
| `-SplatSortIters=` | 5 | CPU 深度排序 benchmark 迭代次数 |
| `-SplatResX=` / `-SplatResY=` | 1280 / 720 | 截图分辨率 |

## 移植改动清单（UE 5.5 → 5.8.4）

1. `UPackage::SavePackage` 9 参重载在 5.8 已改为 4 参 + `FSavePackageArgs`（5 处：EditorLibrary 558/672、EditorModule 108/146、Step 913）。
2. `UHLODBuilderSettings::GetCRC` 在 5.8 被标 `final`，插件 override 改名 `GetGaussianSplattingCRC`（不影响渲染）。
3. `.uplugin` 增加 `EngineVersion: 5.8.0`；Runtime 模块依赖 `Niagara/NiagaraShader`，Editor 模块启用。
4. 编译/运行路径改走 `C:\UEW` ASCII junction。
5. 其余为 C4996 弃用警告（`UStaticMesh::ImportVersion`、`FHLODBuildContext::World`），不影响功能。
