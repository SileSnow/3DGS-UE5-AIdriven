# 05 DJI Terra 与生态 3DGS 能力

> 调研日期 2026-11-08。核心问题：DJI Terra 是否支持 3DGS、哪个版本、输出什么格式、如何与 UE5 衔接，以及官方链与开源链如何取舍。
> 主要证据：DJI Terra Release Notes v5.0.2 PDF（官方 CDN，56 页，本地 data/dji/raw/terra_rn_5.0.2.pdf / .txt）、DJI Terra 官方产品页（data/dji/raw/terra_product_cn.html）、DJI Terra 官方用户手册（terra.dji.com/user-manual）。

## 0. 结论速览
1. **支持**：DJI Terra 自 **v5.0.0（2025-07-18 发布）** 起支持可见光重建的 **Gaussian Splatting（3DGS）**，官方 Release Notes 原文：Now supports Gaussian splatting for visible light reconstruction projects, providing both 2D and 3D outputs.
2. **输出格式**（官方原文）：**3DTiles（DJI Terra LOD format, compatible with Cesium）+ PLY 通用三维格式 + GeoTIFF 通用二维 GIS 格式**；结果保存在 **<ProjectName>/3dgs/results**。
3. **版本/收费**：Terra 5.0 起分为 **Standard / Flagship** 两个版本，**3DGS 仅旗舰版（Flagship）包含**；旧 Survey/Pro/Electricity/Cluster 授权可免费升级到对应新版本（官方 Notes）。
4. **硬件要求**：Windows 10 64-bit 及以上、**≥32 GB RAM**、NVIDIA 显卡 **Compute Capability ≥6.1**（最低 4 GB VRAM，推荐 8 GB VRAM 并更新驱动）；已支持 RTX 50 系列（Blackwell）。
5. **限制**：3DGS 暂不支持集群重建、应用内标注与量测；Cesium 插件在后续版本发布；**Terra v5.0.0 仅支持 Detailed Inspection 与 Agricultural Applications 两类航飞任务**，其它航飞任务需用 4.5.0（而 4.5 无 3DGS）。
6. **与 UE5 衔接**：3DGS 的 PLY 需 UE5 第三方 3DGS 渲染插件（项目 ue5-splat 验证）；3DTiles/B3DM 可走 Cesium for Unreal 生态；OSGB 不在 Terra 5.0 官方 3DGS 输出清单中（传统摄影测量链另论）。
7. **本机可行性**：GPU RTX 5060 Laptop 8 GB（CC 12.0，满足 ≥6.1 与推荐 8 GB），但**本机 RAM 16 GB < 官方要求的 32 GB** → 本机跑 Terra 3DGS 有 OOM 风险，建议开源链（COLMAP+3DGS，8 GB 显存可跑）或换 ≥32 GB 机器。

## 1. DJI Terra 3DGS 官方证据链

### 1.1 Release Notes v5.0.0（2025-07-18，官方 PDF 原文摘录）
- What's New：
  - Now supports **Gaussian splatting for visible light reconstruction projects**, providing both **2D and 3D outputs**. Outputs are available in **3DTiles format (DJI Terra LOD format, compatible with Cesium)**, **PLY universal 3D format**, and **GeoTIFF universal 2D GIS format**.
  - Gaussian splatting currently does not support cluster reconstruction or annotation and measurement within the application. The results of Gaussian splatting reconstruction are located in the local folder at the path **<ProjectName>/3dgs/results**.
  - Version 5.0 introduces a completely redesigned interface.
  - **Standard and Flagship versions are now offered. The Flagship version includes support for visible light Gaussian splatting reconstruction.**
  - Supports NVIDIA's latest **RTX 50 series** (Blackwell architecture) graphics cards.
  - 新增 FBX 三维网格导出、LAZ 点云导出、Matrice 4T 正射 2D 建图、日本 JPGEO2024 高程基准等。
- 升级政策（Notes）：原 Survey 版（中国大陆）与 Pro 版（中国大陆以外）可免费升级 Standard；Electricity 版可免费升级 Flagship；Cluster 版用户获得全部 Flagship 功能且无需新授权；下载 v5.0.0 自动升级。
- 3DGS 硬件要求（Notes 原文）：Gaussian splatting requires Windows 10 or later (64-bit), at least **32GB RAM**, and an NVIDIA graphics card with **compute capability 6.1 or higher (minimum 4GB VRAM)**. For best results, use a card with **8GB VRAM** or more and update drivers.
- 航飞任务限制（Notes 原文）：**DJI Terra v5.0.0 only supports Detailed Inspection and Agricultural Applications flight tasks. For other flight route features, please use version 4.5.0.**
- 其它限制（Notes 原文）：3DGS does not currently support cluster reconstruction, annotation, or measurement functions within the application; reconstruction output saved locally at project name/3dgs/results; the Gaussian splatting **Cesium plugin will be released in subsequent versions**.
- 官方 PDF URL：https://terra-1-g.djicdn.com/263b7ee0f1fe477c91b7ca44348166fe/releasenotes/DJI%20Terra%20Release%20Notes%20v5.0.2.pdf （另见 v5.0.2 与最新版 PDF 同目录）

### 1.2 产品页文案（官方）
- 官方产品页 https://www.dji.com/cn/dji-terra （及 /specs 页）文案（i18n 原文）：
  - "Terra supports one-click export to mainstream 3D Gaussian Splatting data formats such as **PLY and B3DM (3D Tiles)**."（中文：支持一键输出 PLY、B3DM（3D Tiles）等主流三维高斯泼溅数据格式）
  - "It requires only **4 GB of GPU memory and 32 GB of RAM** for smooth operation"（中文对应“仅需 4GB 显存与 32GB 内存”）。
  - 集成 DJI Reality：支持导入 Mesh、3DGS 与点云模型，无需额外授权费用，形成“重建—浏览—分享”工作流。
  - 中文页面可见：“大疆智图 V5.0.0 版本以前申请过免费试用的用户，可继续申请一次免费试用权限，体验高斯泼溅功能。” → 佐证 3DGS 由 5.0.0 引入。

### 1.3 官方用户手册
- 手册中存在 Gaussian Splatting 章节（章节结构从站点 bundle 提取）：LiDAR 链 https://terra.dji.com/user-manual/en/lidar/gaussian-splatting.html 的章节为 “Gaussian Splatting → 1. Parameter setting / 2. Output Path”；可见光链 https://terra.dji.com/user-manual/en/visible-light-reconstruction/gaussian-splatting.html 同样存在该章节（SPA 渲染，正文未逐字抓取，以上述 Release Notes 与产品页为准）。
- 本地证据：data/dji/raw/terra_um_chunks/（站点 JS bundle 中提取到章节标题与输出路径说明）。

## 2. 收费与版本（官方口径）
| 项目 | 官方口径 | 备注 |
|---|---|---|
| 版本划分（5.0+） | Standard / Flagship | Release Notes v5.0.0 “Standard and Flagship versions are now offered” |
| 3DGS 归属 | 仅 **Flagship（旗舰版）** 包含可见光 3DGS | 同上原文 |
| 旧授权升级 | Survey（中国大陆）/Pro（海外）→ Standard 免费；Electricity → Flagship 免费；Cluster → 全部 Flagship 功能，无需新授权 | 官方 Notes |
| 试用 | V5.0.0 之前申请过试用的用户可再申请一次免费试用（体验高斯泼溅） | 官方产品页文案 |
| 具体价格/授权周期 | 官方页面未公开标价，需走经销商/销售咨询 | 本报告不臆测价格 |

## 3. 官方链（Terra）vs 开源链（COLMAP + 3DGS/gsplat）对比

| 维度 | DJI Terra 5.0 官方链 | 开源链（COLMAP + gaussian-splatting / gsplat） |
|---|---|---|
| 使用门槛 | 一键式 GUI，无需写代码；需 Windows + NVIDIA + 32 GB RAM | 需命令行/环境配置（Python、CUDA、COLMAP） |
| 3DGS 质量可控性 | 参数封装，可调项有限（Parameter setting/Output Path） | 全参数可控（分辨率、迭代、SH 阶数、densify 策略） |
| 输入要求 | 可见光照片/视频（DJI 机型最佳），需要 POS；官方建议按 Terra 支持的航线任务采集 | 任意照片 + 可选 COLMAP 位姿先验；对采集规范性要求高 |
| 输出格式 | 3DTiles（DJI Terra LOD，Cesium 兼容）/PLY/GeoTIFF；传统链另有 FBX/LAZ 等 | PLY（标准 3DGS）+ COLMAP 模型 + 可转 transforms.json/3DTiles |
| 集群/大场景 | 3DGS 不支持集群（官方限制） | 可自建多卡/多机/分块 |
| 与 UE5 衔接 | PLY→第三方 3DGS UE 插件；B3DM/3D Tiles→Cesium for Unreal（官方称 Cesium 插件后续发布，需验证） | PLY→UE 3DGS 插件；COLMAP→可转 3D Tiles/glTF |
| 成本 | 商业授权（旗舰版） | 免费（开源），算力/人力成本 |
| 本机适配 | RAM 16 GB 不达标（官方 32 GB） | 8 GB 显存可跑中等规模（项目 gs-pipeline 验证） |
| 适合场景 | 交付级、少改动、官方支持 | 研究/快速迭代/自定义坐标与 UE 集成 |

## 4. 与 UE5 的衔接路径
1. **3DGS PLY → UE5**：UE5 无原生 3DGS 渲染，需要第三方 3DGS 插件/自定义渲染器（项目 ue5-splat 负责验证与性能测试）；PLY 契约见 shared/CONVENTIONS.md（binary_little_endian 1.0，含 f_dc/f_rest/opacity/scale/rot）。
   - 注意坐标系与尺度：Terra 输出为地理/局部坐标（米级），进入 UE 需按项目约定换算（cm、左手系），并统一 Z-up。
2. **3DTiles / B3DM → UE5**：使用 **Cesium for Unreal** 加载 3D Tiles（B3DM/glTF）；Terra 的 3DGS 3DTiles 为“DJI Terra LOD 格式，兼容 Cesium”，但官方说明 3DGS 的 Cesium 插件将后续发布 → 需实测是否为标准 3D Tiles 1.1/glTF 扩展；若不兼容，退回 PLY 路径。
3. **OSGB → UE5**：OSGB 是 Smart3D/ContextCapture 生态的倾斜摄影格式，Terra 5.0 官方 Release Notes/产品页的 3DGS 输出清单中未出现 OSGB；如使用历史版本/Terra 4.x 的传统三维重建输出，需先 OSGB→glTF/FBX（工具转换）再导入 UE5。**本项目建议优先 PLY（3DGS）或 3D Tiles（Cesium）路线，避开 OSGB 转换链。**
4. **GeoTIFF（2D）**：可作为 UE5 地形/底图纹理（配合 Landscape/GeoReferencing 插件），与 3DGS 几何分开管理。
5. **FBX（网格）**：Terra 5.0 新增 FBX 三维网格导出，可直接导入 UE5 作为对照/碰撞体（非 3DGS 表示）。

## 5. 对本项目的建议
1. 先跑**开源链**（项目 gs-pipeline 的 COLMAP+3DGS）：8 GB 显存可完成中小场景，避免 Terra 32 GB RAM 的门槛；同时便于按 CONVENTIONS.md 控制坐标系与 PLY 契约。
2. Terra 作为**官方对照链**：若后续有 ≥32 GB RAM + NVIDIA 的机器，可用 Mini 4 Pro 五向数据跑 Terra 旗舰版 3DGS，对比 PLY/3DTiles 输出质量与耗时。
3. 采集端按 02 的航线规范执行（五向/重叠/固定曝光），因为 Terra 官方 3DGS 的航飞任务限制（仅 Detailed Inspection / Agricultural）意味着消费级自由航线数据可能需要额外验证输入兼容性。
4. UE5 端按 ue5-splat 的插件选型结果走 PLY；3DTiles 作为备选（依赖 Cesium for Unreal 与 Terra LOD 兼容性实测）。

## 6. 证据文件
| 证据 | 路径/URL |
|---|---|
| Terra Release Notes v5.0.2 PDF（56 页） | data/dji/raw/terra_rn_5.0.2.pdf；文本 data/dji/raw/terra_rn_5.0.2.txt；官方 URL 见 1.1 |
| Terra 产品页（中/英 i18n JSON） | data/dji/raw/terra_product_cn.html |
| Terra 用户手册 Gaussian Splatting 章节 | https://terra.dji.com/user-manual/en/visible-light-reconstruction/gaussian-splatting.html ；…/lidar/gaussian-splatting.html |
| 官方仓库站点章节结构 | data/dji/raw/terra_um_chunks/ |
