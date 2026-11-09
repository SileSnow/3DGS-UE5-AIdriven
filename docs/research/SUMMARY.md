# SUMMARY —— DJI Mini × SDK × 3DGS 采集可行性（供最终报告直接引用）

> 调研日期 2026-11-08。证据以官方一手为主（support.dji.com 兼容表、developer.dji.com MSDK V5 页面/Release Notes、dji-sdk 官方仓库、dji.com 产品页、DJI Terra Release Notes PDF），二级来源已标注。原始证据落盘 dji_ue5_3dgs/data/dji/raw/。详见 01~05 与 references.md。

## 一、机型分档（核心结论）

| 档 | 含义 | 机型 | SDK 路线 |
|---|---|---|---|
| A | SDK 全自动（MSDK v4，Android+iOS） | Mavic Mini、Mini SE、Mini 2 | v4.16（Mini 2/Mini SE）；Mavic Mini 自 4.13 |
| A' | SDK 全自动（MSDK v5，仅 Android） | Mini 3、Mini 3 Pro、Mini 4 Pro | v5.3.0 / v5.3.0 / v5.13.0 |
| B | 无 SDK，但 DJI Fly 原生航点可自动执行（半自动） | Mini 5 Pro | DJI Fly 航点（官方支持） |
| C | 无 SDK 且无原生航点，只能手动/定时拍照 | Mini 2 SE、Mini 4K | 无 |

## 二、关键事实（每条均有一手证据）

1. 官方《DJI 大疆产品 SDK 支持情况介绍》表：Mini 4 Pro = 支持 Mobile SDK；Mini 3 / Mini 3 Pro = 支持；Mini 2 / Mini SE / Mavic Mini = 支持；Mini 2 SE / Mini 4K = 不支持；Mini 5 Pro = 不支持；Air 3/3S、Mavic 3/3 Pro/3 Classic、Mavic 4 Pro = 不支持。
2. Mini 3 与 Mini 3 Pro 自 **Android MSDK v5.3.0（2023-04-07）** 起被支持；该版 Release Notes 原文 “Add supported aircraft: DJI Mini 3 / DJI Mini 3 Pro”。
3. Mini 4 Pro 自 **Android MSDK v5.13.0（2025-03-17）** 起被支持；首发仅 **DJI RC-N2**（固件 01.00.0800 / RC 01.01.0300），**DJI RC-N3 到 v5.17.0（2025-11-04）** 才加入；**DJI RC 2（带屏）不支持 MSDK**。
4. MSDK V5 目前 **仅 Android**：官方产品页只列 Android 平台与 Android API Reference，Release Notes 全为 “Android MSDK …”，无 iOS V5。
5. Mini 2 / Mini SE 走 **MSDK v4.16（2021-12-31 发布，v4 线末版 4.18 / 2024-10-24）**；能力口径为相机/飞控/云台/遥控器；已知早期缺口：全景模式、云台高度、FlyZoneManager。
6. Mini 5 Pro：无任何官方 SDK，但 **DJI Fly 原生航点飞行支持**（官方帮助页机型列表含 Mini 5 Pro）→ 半自动可行。
7. Mini 2 SE / Mini 4K：官方 SDK 兼容表“不支持”，DJI Fly 航点机型列表也不含 → 只能手动/定时。
8. MSDK v5 对 Mini 3/3 Pro/4 Pro 的能力：KMZ/WPML 航线（WPMZManager，v5.6.0 起可编辑/校检/KML 转 KMZ）、相机曝光/图像/视频参数、云台、媒体下载与回放、图传、遥测（≤10 Hz）、虚拟摇杆（建议 5–25 Hz）；断点续飞官方仅保证 M30/M3E/3T/3M，Mini 不在列。
9. DJI Fly 航点能力边界：最多 200 航点、0.1–15 m/s、高度相对起飞点（默认 50 m）、悬停 0–30 s、每点可设相机动作/云台俯仰/变焦、**不支持 KML 导入、不支持断点续飞**。
10. 第三方 App 现状：Litchi（v4 系）支持 Mini 2/SE/Mavic Mini；Mini 3 及更新机型需 Litchi Pilot（类似 v5 路线）；Dronelink 支持 Mini 2/3/3 Pro/4 Pro（Android 为主，Mini 4 Pro 需 RC-N2/N3，iOS 不支持），Mini 5 Pro 仅“Onboard only”（导出 KMZ 由飞机执行）。
11. DJI Terra v5.0.0（2025-07-18）新增可见光 3DGS：输出 3DTiles（DJI Terra LOD，兼容 Cesium）、PLY、GeoTIFF；需 32 GB RAM、NVIDIA CC≥6.1（最低 4 GB VRAM，推荐 8 GB）；不支持集群重建/标注/量测；旗舰版包含 3DGS；RTX 50 系列已支持。
12. 第三方逆向（DUML/dji-firmware-tools，GPL-3.0）可用于固件分析与维修，但修改固件/参数存在违约、著作权反规避、保修失效、空域违规等风险（DJI《飞行器产品使用条款》2024-07-12 版第 3 条(3)(4)(5) 明文禁止修改/解锁/反向编译/解除地理围栏与限高）；3DGS 采集链路不需要逆向，量产项目禁用。

## 三、结论与建议（可直接进报告）

1. **可行性结论**：DJI Mini 系列中存在可“SDK 全自动采集 → 3DGS 重建 → UE5 集成”的完整可行路径，首选 **Mini 4 Pro（Android + RC-N2/N3 + MSDK v5.13.0+）**；次选 Mini 3 Pro / Mini 3（MSDK v5.3.0+，仅 Android）。
2. **若无法开发 App**：Mini 4 Pro / Mini 5 Pro 用 DJI Fly 原生航点 + 定时/间隔拍照即可完成 3DGS 采集；Mini 3/3 Pro 无原生航点，需 Litchi Pilot/Dronelink/自研 App。
3. **不应选**：Mini 2 SE、Mini 4K（无 SDK 无航点）；Mini 2/Mini SE 仅在预算极低且接受 1/2.3 英寸画质时考虑。
4. **平台约束**：iOS 无 MSDK v5，第三方自动化实际为 Android 专供；带屏遥控器（DJI RC、RC 2）无法运行第三方 App，是选型硬约束。
5. **合规约束**：不得用逆向工具绕过禁飞/限高/限速；采集须遵守当地空域法规，并保留原始 XMP/EXIF 元数据用于位姿先验（见 03/04）。
