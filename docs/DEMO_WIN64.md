# Windows 免安装演示包（UE5.8 打包版）

> 给“没有 Unreal Engine、也不想编译”的读者：下载 → 解压 → 双击 `run_demo.bat`，即可在 UE5.8 里实时查看本项目的 v6 3DGS 模型。
> 发布位置：GitHub Release **v1.0** 的资产 `DJI3DGS_UE_Win64_Demo_v1.0.zip`（见 https://github.com/SileSnow/3DGS-UE5-AIdriven/releases ）。

## 1. 包内容

| 内容 | 说明 |
|---|---|
| `Windows/` | UE5.8 packaged build（cooked，DX12 SM6，不含编辑器） |
| `gaussians_best_v6.ply` | v6 模型：199,298 splats / 40k iter / 960×720 / val PSNR 16.62 dB |
| `run_demo.bat` | 交互式环绕预览（1280×720，Path B 调试点） |
| `run_4views.bat` | 4 个固定视角截图 → `_screenshots\` |
| `preview/` | v6 结果页、UE5 Path B 四视角拼图、v6 演示视频（mp4） |
| `README_运行说明.md` | 包内快速说明（中/英） |

## 2. 运行要求

- Windows 10/11 x64；
- DirectX 12 独立显卡（本项目在 RTX 5060 Laptop 8GB 验证；建议 ≥4 GB 显存）；
- 约 1.2 GB 磁盘空间；
- 无需安装 Unreal Engine / CUDA / Python。

## 3. 已知限制

1. **Path B 点云预览**：打包版用调试点绘制 splats，视觉是点云风格（不是最终高斯溅射效果）；
2. **Niagara Path A 在打包版为空**：插件 Niagara 资产已 cook 进包，但其 PointCloud DataInterface 绑定依赖编辑器期 API（`UNiagaraComponent::SetParameterOverride` 是 `WITH_EDITOR`），运行时没有等价公开 API，因此打包版 Niagara 路径不显示 splats（见 [KNOWN_ISSUES.md](KNOWN_ISSUES.md) §E）；编辑器内可用；
3. 模型是工程验证质量（细节偏软），不是生产级重建；
4. 演示包不含 UE 编辑器，二次开发请克隆源码并安装 UE 5.8.4。

## 4. 从源码重新打包（维护者）

```powershell
# 前提：UE 5.8.4 安装于 C:\Program Files\Epic Games\UE_5.8；工程在 ASCII junction 路径下（C:\UEW）
$uat = 'C:/Program Files/Epic Games/UE_5.8/Engine/Build/BatchFiles/RunUAT.bat'
$proj = 'C:/UEW/dji_ue5_3dgs/ue5/DJI3DGS_UE/DJI3DGS_UE.uproject'
& $uat BuildCookRun -project=$proj -noP4 -platform=Win64 -clientconfig=Development `
  -build -cook -stage -pak -archive -archivedirectory=C:/UEW/_pkg_out -unattended -utf8output
```

注意：`ue5/DJI3DGS_UE/Config/DefaultGame.ini` 里必须保留 `+DirectoriesToAlwaysCook=(Path="/GaussianSplattingForUnrealEngine")`，否则运行时 `LoadObject` 的 Niagara 资产不会被 cook 进包（表现为“找不到 NS_GaussianSplattingPointCloud”）。

## 5. 校验信息

- 资产文件名：`DJI3DGS_UE_Win64_Demo_v1.0.zip`
- 大小 / SHA256：见 GitHub Release 页面（下载后可用 `Get-FileHash` 核对）。
