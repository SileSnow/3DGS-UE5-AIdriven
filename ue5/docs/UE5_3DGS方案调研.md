# UE5 3DGS（Gaussian Splatting）渲染集成方案调研

> 调研/实测执行：ue5-splat（2026-11-08）；环境：Windows 11 26200 / RTX 5060 Laptop 8GB / UE 5.8.4 / VS 2026 (MSVC 14.5)。
> 所有"可得性/许可/版本"结论均给出仓库或官方链接；本机实测部分见 `ue5/RESULTS.md`。

## 0. 结论摘要（TL;DR）

1. **UE 5.8.4 没有内置 3DGS 渲染能力**（本机核验 + Epic 官方论坛 2025-10-23 表态）。UE 里要显示 3DGS，必须"插件/第三方方案/自研"三选一。
2. 开源可移植路径里，**Italink/GaussianSplattingForUnrealEngine（MIT、218★、UE 5.5+、Niagara GPU 粒子）** 是工程量/可维护性最优的候选：C++ 约 51 个文件、Content 仅 7 个 uasset（约 1.2MB），本团队已实际移植到 **UE 5.8.4 编译并运行通过**（见 RESULTS.md）。
3. 想要"生产级、带正确深度/遮挡、十亿点"的方案：开源看 **yags（Yandex，UE 5.5–5.7）**，商业看 **xgrids LCC（声明支持 UE 5.1–5.8、DX11/12/Vulkan）**；两者都未在本机实测（本任务时间盒内只做了 Italink 移植）。
4. 如果数据来自 **DJI Terra v5（3DGS 输出 3D Tiles + PLY）**，另一条 UE 路线是 **Cesium for Unreal 的 3DGS 3D Tiles（2026-04 起支持，带层级 LOD）**；该路线与"PLY + 原生插件"并列，适合大范围/流式场景，但依赖 Cesium 生态与 Terra 的旗舰版能力。
5. 对 DJI Mini 系列（消费级航拍 + 3DGS 后处理）的可行性结论：**在 UE5 中"显示"3DGS 完全可行且成本可控；"高质量工业生产"仍依赖商业插件或 Cesium/第三方管线**。详见第 6 节与本目录 RESULTS.md。

## 1. UE 原生支持现状（本机核验）

- 本机 UE 5.8.4 引擎目录 `C:/Program Files/Epic Games/UE_5.8/Engine/Plugins` 共 **895 个 .uplugin**，文件名含 Gauss/Splat 的为 **0**；相关但非 3DGS 的实验性插件只有 `Experimental/NeuralRendering`、`Experimental/Volumetrics`。
- Epic 官方论坛回复（2025-10-23）："We don't currently have plans to provide built-in gaussian splatting support."
  <https://forums.unrealengine.com/t/gaussian-splatting-support-out-of-the-box/2677693>
- 因此任何 UE5 3DGS 方案 = 插件（开源/商业）+ 数据（PLY/SOG/SPZ/3D Tiles）。UE 官方在 5.7/5.8 的渲染器（Nanite/Lumen/TSR）没有为高斯泼溅做原生光栅化或排序。

## 2. 开源插件对比

搜索方式：GitHub Search API（`q=3dgs+unreal`、`gaussian+splat+UE5`），元数据经 `api.github.com` 核验、源码经 `cdn.jsdelivr.net` 获取（本机 github.com 直连不可用）。结果缓存于 `ue5/_research/`。

| 项目 | 许可 | UE 版本 | 渲染方式 | 数据格式 | 可得性 | 优点 | 缺点 |
|---|---|---|---|---|---|---|---|
| **Italink/GaussianSplattingForUnrealEngine** | MIT | 5.5+（本团队实测移植到 **5.8.4**） | **Niagara GPU 粒子**（billboard，Splat 材质）+ 可选静态网格体 | PLY（标准 3DGS 字段）、SPZ 压缩资产 | 源码完整、体积小（56 文件 / 1.38MB，无二进制大资源） | 代码最少、编译最快；自带编辑器捕获→COLMAP→训练工作流；有 LOD/深度裁剪；本机已跑通 | 半透明排序靠 Niagara/深度近似；无运动模糊/TAA 正确深度；SH 高阶项未用（仅 DC 颜色）；日式英文文档 |
| **yandex/yags** | 开源（Yandex） | 5.5/5.6/5.7（filmxr 有预编译） | billboard quads，**Mesh Shader / Vertex Shader 双后端** | PLY、SOG | 源码 + filmxr/yags 预编译 Win64 | 深度写入正确（支持 DoF/运动模糊/TAA）、实例化、性能设计好 | 尚未官方支持 5.8；需自编译/适配 |
| **mlslabs/MLSLabsGaussianSplattingRenderer-UE** | Apache-2.0 | 5.5（分支 `Pro_2.0_ue5.5`） | 自研渲染器（3DGS + 4DGS 体积视频） | 自有格式 + PLY 导入 | 仓库 1.28GB、604 文件（526 在 Plugins/） | 功能最全（3DGS+4DGS、管理/流式）；288★ | 体积巨大、拉取/编译成本高；5.8 需适配 |
| **DazaiStudio/SplatRenderer-UEPlugin** | Apache-2.0 | 5.5+ | 自定义 RHI 渲染（Compute Shader 排序 + VS/PS 绘制） | PLY/4DGS | **仓库只有预编译 DLL + 着色器 + 蓝图**，无 C++ 源码 | 开箱即用（若版本匹配）；Blueprint/Seguencer 集成 | 无源码不可移植到 5.8；仅 Win64 预编译 |
| **notno/ue5-splat-rhi** | MIT | **5.7** | RHI 级 3DGS 渲染器 + splat 粒子系统 | PLY | 66 文件（32 源码 + 30 着色器），2★ | 版本最接近 5.8、纯 C++/shader 结构清晰 | 新项目、文档/验证少 |
| **xgrids/LCC-3DGS-Unreal-Plugin** | 商业（Free + Pro） | 5.1–5.8（README 声明） | 自研 RHI（DX11/12/Vulkan） | LCC/LCC2/PLY/SOG/SPZ | 免费版可下载；Pro 收费 | 官方声明十亿点、nDisplay/VR/VP、Cesium/CARLA；版本覆盖 5.8 | 闭源、Pro 收费；Free 版功能受限 |
| Pico-Developer/splat_unreal | 21★ | 5.x | — | PLY | 源码 | 参考实现 | 社区小项目 |
| YuanBaoSMadLab/OpenSplat4D | 15★ | 5.x | cluster LOD + GPU sort | 4DGS | 源码 | 4DGS/时空高斯研究 | 成熟度低 |
| SenseSpace-AI3D/3DGS-UE-SDK | MIT | 5.x | — | — | **仅文档**（7 个 doc 文件） | 商汤生态 | 无实际源码，不可用 |

来源：
- Italink: <https://github.com/Italink/GaussianSplattingForUnrealEngine>（MIT；README 说明 UE 5.5+、GPU 粒子/静态网格体、深度修剪、屏幕尺寸 LOD）
- yags: <https://github.com/yandex/yags>；预编译 <https://github.com/filmxr/yags>；报道 <https://radiancefields.com/yags-yandex-open-sources-a-3dgs-plugin-for-unreal-engine-5.5%e2%80%935.7>
- MLSLabs: <https://github.com/mlslabs/MLSLabsGaussianSplattingRenderer-UE>；<https://radiancefields.com/platforms/mlslabs>
- DazaiStudio: <https://github.com/DazaiStudio/SplatRenderer-UEPlugin>（Apache-2.0；Releases 提供预编译）
- notno: <https://github.com/notno/ue5-splat-rhi>
- xgrids LCC: <https://github.com/xgrids/LCC-3DGS-Unreal-Plugin>

## 3. 商业/闭源方案对比

| 方案 | 形态 | UE 集成方式 | 许可/价格 | 优点 | 缺点/待核实 |
|---|---|---|---|---|---|
| **Luma AI** | 云端 3DGS 重建 + UE 插件 | UE Marketplace 免费代码插件（播放/导入 Luma 场景） | 免费插件 + 云端按量/订阅 | 采集只需手机/无人机视频，重建质量业界标杆；插件官方维护 | 数据需上云；播放器功能受限（编辑/再光照弱）；离线/保密场景不适用 |
| **Postshot（Jawset）** | 桌面训练软件 | 官方 UE 集成（Postshot 用户指南 "Unreal Engine Integration"，v0.5 起支持 UE 5.4–5.5） | 订阅/买断（桌面软件） | 本地训练、质量高、可用自有 GPU；支持导出 PLY/UE 集成 | 训练吃显存（本机 8GB 需小场景）；UE 插件版本需核对 5.8 |
| **Polycam** | 手机/网页采集 + 云重建 | 导出 PLY/SPZ 后用第三方 UE 插件渲染 | 订阅 | 采集门槛最低；适合快速验证 | 重建精度/规模一般；UE 侧仍需插件 |
| **RealityScan 2.0（Epic）** | 免费摄影测量 + 3DGS | 输出网格/点云；3DGS 能力随版本演进 | 免费（Epic 账号） | 免费、与 UE 同生态；可做"照片→3DGS"基线 | 3DGS 输出格式/参数仍在演进；大场景需分块 |
| **Fab（Marketplace）** | 各类 3DGS 插件/资产 | 直接装插件（含免费/付费） | 按插件定价 | 安装最省事、有商业支持 | 质量参差；需逐个核对 UE 5.8 兼容性 |
| **xgrids LCC Pro** | 商业插件 | UE 插件（DX11/12/Vulkan） | Free + Pro 收费 | 十亿点、nDisplay/VR/VP、Cesium；声明支持 5.1–5.8 | 闭源；Pro 授权成本 |
| **WallGS Pro** | 商业 3DGS 重光照 UE 插件 | UE 插件 | 商业 | 3DGS 场景可重光照，接近生产可用 | 新方案，需核实 UE 5.8 支持 |

来源：
- Luma AI UE 插件（Marketplace）：<https://www.unrealengine.com/marketplace/en-US/product/luma-ai>
- Postshot UE 集成文档：<https://www.jawset.com/docs/d/Postshot+User+Guide/Unreal+Engine+Integration>；v1.0 发布报道 <https://radiancefields.com/postshot-launches-v1-0-out-of-beta>
- RealityScan 2.0：<https://radiancefields.com/realityscan-2-0-released>；官方课程 <https://dev.epicgames.com/community/learning/courses/dXK/introducing-realityscan-2-0/XY9J/realityscan-2-0-release-notes>
- WallGS Pro：<https://radiancefields.com/wallgs-pro-brings-gaussian-splat-relighting-to-unreal-engine-5>

> 注：商业方案的具体 UE 版本兼容性需以各家当期 Release Notes 为准；本机未购买/实测，故仅作选型对照。

## 4. DJI 官方链路：DJI Terra v5 的 3DGS 能力

- DJI Terra **v5.0.0（2025-07-18 起）** 支持 **可见光 3DGS 重建**，输出 **3D Tiles + PLY（+ GeoTIFF）**，输出目录 `<ProjectName>/3dgs/results`；属于**旗舰版**功能；要求 NVIDIA Compute Capability ≥ 6.1、**推荐 8GB 显存**、支持 RTX 50 系。
- 官方手册：
  - 可见光 3DGS：<https://terra.dji.com/user-manual/en/visible-light-reconstruction/gaussian-splatting.html>
  - LiDAR 3DGS：<https://terra.dji.com/user-manual/en/lidar/gaussian-splatting.html>
  - Release Notes v5.0.2 PDF：<https://terra-1-g.djicdn.com/263b7ee0f1fe477c91b7ca44348166fe/releasenotes/DJI%20Terra%20Release%20Notes%20v5.0.2.pdf>
- 对本项目的意义：DJI 官方已经打通"Mavic/Mini 采集 → 3DGS 重建"，UE 侧只需消费 **PLY（单机/插件）** 或 **3D Tiles（流式）**。本方案验证的正是 PLY → UE 插件这条最短链路。

### 4.1 与 Cesium for Unreal 的组合路线

- Cesium 于 **2026-04-27** 发布 **3D Gaussian Splats with Hierarchical LOD Using 3D Tiles**，随后 Cesium for Unreal 支持加载带 LOD 的 3DGS 3D Tiles：
  - 博客：<https://cesium.com/blog/2026/04/27/3d-gaussian-splats-lod/>
  - 教程：<https://cesium.com/learn/unreal/3d-gaussian-splat-tilesets-lods/>
  - 相关报道：<https://radiancefields.com/cesium-brings-khr_gaussian_splatting-support-to-cesiumjs-and-unreal-engine>
- 路线对比：
  - **PLY + 原生插件**（本方案）：单文件、离线、可控；适合单场景/整块区域；需要自己做排序/性能优化。
  - **3D Tiles + Cesium for Unreal**：大范围/多瓦片、按需流式 LOD；适合城市级、与 GIS/地形叠加；依赖 Terra 旗舰版 + Cesium 生态。

## 5. 本项目选型与移植落地（摘要）

**选型**：Italink/GaussianSplattingForUnrealEngine（MIT）→ 移植到 UE 5.8.4；自研 runtime PLY parser + 测试 Actor（不依赖编辑器导入流程）。

**为什么不是 yags / MLSLabs / Dazai**：
- yags 官方最高 5.7，5.8 适配风险与工作量不可控（渲染器含 Mesh Shader 后端）；
- MLSLabs 仓库 1.28GB、模块多，拉取/编译时间盒内不可控；
- Dazai 仓库无 C++ 源码（仅预编译 DLL），无法移植到 5.8；
- xgrids LCC 为商业方案，Free 版能力边界需商务确认。

**移植到 UE 5.8 的改动（实测）**：
1. 历史 API：`UPackage::SavePackage` 9 参重载在 5.8 变为 4 参 + `FSavePackageArgs`（插件内 5 处）。
2. `UHLODBuilderSettings::GetCRC` 在 5.8 被标 `final`，插件的 override 改名为 `GetGaussianSplattingCRC`（PoC 不使用 HLOD，不影响渲染）。
3. 路径：工程位于含中文的 `.../GAIA项目/...`，MSVC 14.5 / UBA 会拆断非 ASCII 路径（C1083），编译与运行统一走 ASCII junction `C:\UEW`。
4. 其他为 C4996 弃用警告（`UStaticMesh::ImportVersion`、`FHLODBuildContext::World` 等），不影响编译。

**验证结果**：编译、运行、截图、性能数据见 `ue5/RESULTS.md`（含命令、日志路径与 metrics.json）。

## 6. 对"Dji Mini → UE5 → 3DGS"可行性的判断

| 维度 | 判断 | 依据 |
|---|---|---|
| 采集 | 消费级无人机可采集 | DJI Mini 系列航拍视频/照片；DJI Terra 官方支持 3DGS 可见光重建 |
| 重建 | 成熟（DJI Terra v5 或开源 3DGS） | Terra v5 旗舰版；开源 gaussian-splatting 生态成熟 |
| UE5 显示 | **可行**，开源插件移植成本可控（本任务已跑通） | 本机 UE 5.8.4 + Italink 移植编译/运行 |
| 生产级质量 | 需要商业插件或 Cesium 流式路线 | 排序/深度/大规模 LOD 是开源方案主要短板 |
| 风险 | ① 8GB 显存限制 3DGS 规模；② 非 ASCII 路径/工具链坑；③ 插件对 UE 版本敏感 | 本机 CPU/GPU 与构建日志 |

## 7. 参考来源清单

1. Epic 论坛（无内置 GS 计划，2025-10-23）：<https://forums.unrealengine.com/t/gaussian-splatting-support-out-of-the-box/2677693>
2. Italink 插件（MIT）：<https://github.com/Italink/GaussianSplattingForUnrealEngine>
3. yags（Yandex）：<https://github.com/yandex/yags>；预编译 <https://github.com/filmxr/yags>
4. MLSLabs：<https://github.com/mlslabs/MLSLabsGaussianSplattingRenderer-UE>
5. DazaiStudio SplatRenderer：<https://github.com/DazaiStudio/SplatRenderer-UEPlugin>
6. notno/ue5-splat-rhi：<https://github.com/notno/ue5-splat-rhi>
7. xgrids LCC-3DGS：<https://github.com/xgrids/LCC-3DGS-Unreal-Plugin>
8. Cesium 3DGS 3D Tiles（2026-04-27）：<https://cesium.com/blog/2026/04/27/3d-gaussian-splats-lod/>；教程 <https://cesium.com/learn/unreal/3d-gaussian-splat-tilesets-lods/>
9. DJI Terra 可见光 3DGS 手册：<https://terra.dji.com/user-manual/en/visible-light-reconstruction/gaussian-splatting.html>
10. DJI Terra LiDAR 3DGS 手册：<https://terra.dji.com/user-manual/en/lidar/gaussian-splatting.html>
11. DJI Terra Release Notes v5.0.2：<https://terra-1-g.djicdn.com/263b7ee0f1fe477c91b7ca44348166fe/releasenotes/DJI%20Terra%20Release%20Notes%20v5.0.2.pdf>
12. Luma AI UE 插件：<https://www.unrealengine.com/marketplace/en-US/product/luma-ai>
13. Postshot UE 集成：<https://www.jawset.com/docs/d/Postshot+User+Guide/Unreal+Engine+Integration>
14. RealityScan 2.0：<https://radiancefields.com/realityscan-2-0-released>
