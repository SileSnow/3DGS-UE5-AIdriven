# 01 DJI Mini 系列 SDK 能力矩阵与自动化可行性

> 调研日期：2026-11-08（Asia/Shanghai）。证据优先官方一手（developer.dji.com / support.dji.com / dji.com / dji-sdk 官方 GitHub），二级来源显式标注[二级]。抓取到的原始 HTML/JS/文本/PDF 全部落盘于 dji_ue5_3dgs/data/dji/raw/，可复核。
> 本文件服务于“DJI Mini 航拍 → 3DGS 重建 → UE5”技术路线选型：明确哪些机型能 SDK 全自动采集、哪些只能半自动/手动。

## 0. 一页结论

### 0.1 机型分档（本文档核心结论）

| 分档 | 含义 | 机型 | SDK 路线 |
|---|---|---|---|
| A | SDK 全自动（MSDK v4，Android+iOS） | Mavic Mini、Mini SE、Mini 2 | MSDK v4.16（Mini 2/Mini SE）；Mavic Mini 自 v4.13 |
| A-prime | SDK 全自动（MSDK v5，仅 Android） | Mini 3、Mini 3 Pro、Mini 4 Pro | MSDK v5.3.0（Mini 3/3 Pro）、v5.13.0（Mini 4 Pro） |
| B | 无 SDK，但 DJI Fly 原生航点可自动执行（半自动） | Mini 5 Pro | 无；DJI Fly 航点（官方支持列表含） |
| C | 无 SDK 且无原生航点，只能手动/定时拍照 | Mini 2 SE、Mini 4K | 无 |

### 0.2 全量矩阵（官方兼容表 + MSDK 文档/仓库/Release Notes 交叉核对）

| 机型 | 上市 | 官方“支持 SDK” | 具体 Mobile SDK 版本 | SDK 平台 | Payload SDK | Onboard SDK | DJI Fly 原生航点 | 第三方 app 现状 | 分档 |
|---|---|---|---|---|---|---|---|---|---|
| Mavic Mini | 2019-11 | 支持 | MSDK v4（论坛称 4.13 起）[二级] | Android / iOS(v4) | 不支持 | 不支持 | 无 | Litchi、Dronelink 支持 | A |
| Mini SE | 2020-11 | 支持 | MSDK v4.16（2021-12-31） | Android / iOS(v4) | 不支持 | 不支持 | 无 | Litchi、Dronelink 支持 | A |
| Mini 2 | 2020-11 | 支持 | MSDK v4.16（2021-12-31） | Android / iOS(v4) | 不支持 | 不支持 | 无 | Litchi、Dronelink 支持 | A |
| Mini 2 SE | 2023-02 | 不支持 | — | — | 不支持 | 不支持 | 无 | 无 | C |
| Mini 4K | 2024-05 | 不支持 | — | — | 不支持 | 不支持 | 无 | 无 | C |
| Mini 3 | 2023-04 | 支持 | MSDK v5.3.0（2023-04-07） | 仅 Android | 不支持 | 不支持 | 无（官方航点列表不含） | Litchi Pilot / Dronelink | A-prime |
| Mini 3 Pro | 2022-05 | 支持 | MSDK v5.3.0（2023-04-07） | 仅 Android | 不支持 | 不支持 | 无 | Litchi Pilot / Dronelink（RC-N1/RC Pro） | A-prime |
| Mini 4 Pro | 2023-09 | 支持 | MSDK v5.13.0（2025-03-17） | 仅 Android，需 RC-N2（v5.17.0 起加 RC-N3） | 不支持 | 不支持 | 有（官方列表） | Dronelink（Android）；Litchi Pilot | A-prime |
| Mini 5 Pro | 2025-09 | 不支持 | — | — | 不支持 | 不支持 | 有（官方列表） | Dronelink 仅 Onboard KMZ 方式 | B |

关键差异：
- 官方兼容表里，“支持 SDK”不等于“支持 MSDK v5”。Mini 2/SE/Mavic Mini 的“Mobile SDK”指的是 v4 时代 SDK；Mini 3/3 Pro/4 Pro 指 v5。v4 与 v5 互不兼容（官方文档原文：Version 4.X is not compatible with version 5.X）。
- 截至目前（2026-11），MSDK V5 只有 Android 发布：官方产品页只列 Android 平台与 Android API Reference，Release Notes 页只收录 Android MSDK。iOS 侧无 V5 SDK，第三方 App 对 Mini 3/4/5 实际为 Android 专供。
- Mini 5 Pro 虽无任何官方 SDK，但 DJI Fly 自带航点飞行（官方支持列表含 Mini 5 Pro），因此“完全手动”不准确，应归为半自动（B）。

## 1. 官方一手证据

### 1.1 《DJI 大疆产品 SDK 支持情况介绍》（官方兼容总表）
- URL（中文）：https://support.dji.com/help/content?customId=01700000763&spaceId=17&re=CN&lang=zh-CN
- URL（英文）：https://support.dji.com/help/content?customId=01700000763&documentType&lang=en&paperDocType=ARTICLE&re=US&spaceId=17
- 本地证据：data/dji/raw/sdk_compat_cn.html（341,730 bytes，SSR 表格，可 grep 复核）
- 表列：飞行器型号 | 是否支持 SDK | SDK 类型（Windows SDK / Mobile SDK / Onboard SDK）
- 原文关键行（消费级表）：DJI Mini 4 Pro=支持/Mobile SDK 勾选；DJI Mini 3、DJI Mini 3 Pro=支持/Mobile SDK；DJI Mini 2=支持；DJI Mini SE=支持；Mavic Mini=支持；DJI Mini 2 SE 与 DJI Mini 4K=不支持；DJI Mini 5 Pro=不支持；DJI Air 3/3S、DJI Mavic 3/3 Pro/3 Classic、Mavic 4 Pro、Neo/Neo 2、Flip、Avata 系列=不支持。
- 行业级表（同一页面表2）：Mobile SDK 列支持 Mavic 3E/3T/3M、Matrice 4 系列、M30 系列、M300/M350 RTK 等；Payload SDK 列支持上述行业机型与 FlyCart；上云 API 列支持 Matrice 4 系列、M400、M30、M300/M350、Mavic 3E/3T（Mavic 3M 不支持）。消费级 Mini 系列不在上云 API / Payload SDK 支持范围内。

### 1.2 DJI Mobile SDK V5 官方页面（支持机型 + 平台）
- URL：https://developer.dji.com/mobile-sdk/ （English），https://developer.dji.com/cn/mobile-sdk/ （中文）
- 本地证据：data/dji/raw/dev_msdk_en.html（24,331 bytes）
- Supported Products 原文列表：Matrice 4D/4TD、Matrice 4E/4T、Matrice 300 RTK、Matrice 30 Series、DJI Mavic 3 Enterprise Series、DJI Mavic 3M、DJI Mini 4 Pro、DJI Mini 3、DJI Mini 3 Pro、Matrice 350 RTK。
- Supported Platform 原文：DJI Smart Controller（Android 5.0）、配合 Smart Controller 的外部 Android 设备（Android 5.0+）、Android 10.0。页面导航只有 Android API Reference，无 iOS API Reference。

### 1.3 官方 GitHub 仓库（支持机型清单的代码级证据）
- 仓库：https://github.com/dji-sdk/Mobile-SDK-Android-V5
- README（V5.20.1，仓库发布 2026-11-05）：Supported Product 列表含 DJI Mini 4 PRO、DJI Mini 3 Pro、DJI Mini 3，以及 Matrice 4 系列/M4D/M3E/M30/M300/M350/M3TA/Matrice 400/M5T/H30 等；不含 Mini 5 Pro、Mini 2 SE、Mini 4K、Mini 2。
- 本地证据：data/dji/raw/（README 经 api.github.com 拉取，2026-11-08）。

### 1.4 MSDK V5 官方 Release Notes（版本-机型-固件对应关系的最终依据）
- URL：https://developer.dji.com/doc/mobile-sdk-tutorial/en/ （页面标题 Mobile SDK，左栏 Release Note；内容由站点 JS bundle 渲染）
- 本地证据：data/dji/raw/text/relnotes_all.txt（56 个版本条目全文，来自官方站点 bundle v-2d0a870d / v-2d0a7f8b）
- 全量版本时间轴（官方发布日期）：V5.0.0 2022-07-08；V5.1.0 2022-09-27；5.1.1 2022-11-16；V5.2.0 2022-12-16；V5.3.0 2023-04-07；V5.4.0 2023-05-18；V5.5.0 2023-07-20；V5.6.0 2023-09-18；V5.7.0 2023-10-30；V5.7.2 2023-12-27；V5.8.0 2023-12-28；V5.9.0 2024-05-16；V5.9.1 2024-06-11；V5.9.2 2024-07-18；V5.10.0 2024-08-15；V5.11.0 2024-11-07；V5.12.0 2025-01-08；V5.13.0 2025-03-17；V5.14.0 2025-04-16；V5.15.0 2025-06-10；V5.16.0 2025-09-16；V5.17.0 2025-11-04；V5.18.0 2026-05-22；V5.20.1 2026-11-05。
- v5.3.0（2023-04-07）原文：Add supported aircraft: DJI Mini 3、DJI Mini 3 Pro。并特别提示：更换遥控器后须先用 DJI Fly 重新绑定，否则 Mini 3/3 Pro 会持续上报绑定校验错误。
- v5.13.0（2025-03-17）原文：Add supported aircraft: DJI Matrice 4D and DJI Matrice 4TD、DJI Mini 4 Pro；同版固件表：DJI Mini 4 Pro 01.00.0800，DJI RC N2 01.01.0300（该版仅 RC-N2）。
- v5.17.0（2025-11-04）原文：Add supported for DJI Mini 4 Pro Smart Controller: DJI RC N3。
- v5.14.0（2025-04-16）原文：IntelligentFlightManager（track / POI / spotlight / fly to target）支持机型列表包含 DJI Mini 4 Pro。

### 1.5 MSDK v4 证据
- v4 产品页（Supported Products 分类）：https://developer.dji.com/mobile-sdk-v4/ ；本地 data/dji/raw/msdk_v4_landing.html
- 官方 GitHub 仓库发布记录（版本+日期）：https://github.com/dji-sdk/Mobile-SDK-Android/releases
  - v4.16：2021-12-31；v4.16.1：2022-03-18；v4.16.2：2022-08-01；v4.16.3：2022-10-26；v4.16.4：2022-11-11；v4.17：2023-11-10；v4.18：2024-10-24（v4 线最后一版）。
- v4 文档 Hardware Introduction 的 Supported Products 表（2020-05-23 版）：仅列 Mavic 2 系列、Mavic Air、Mavic Pro、Phantom 3/4、Inspire、Matrice 等，不含任何 Mini 系列；说明该文档页未随 2021 年新增机型更新，不能据此否认 Mini 2 支持（以官方兼容表+Release Notes 为准）。本地 data/dji/raw/msdk_v4_product_intro.html。
- 二级证据（转载官方 Release Notes 内容）：https://dronedj.com/2022/01/03/dji-sdk-mini-2-se-air-2s/ —— MSDK 4.16 新增 Mini 2、Mini SE、Air 2S；能力口径为 camera / flight controller / gimbal / remote controller functions；该版本已知缺口：全景拍照模式暂不支持、云台高度数据因固件问题暂不可得、FlyZoneManager 暂不可用（后续版本修复）。
- 官方论坛帖（Mavic Mini 与 MSDK 4.13）：https://forum.dji.com/forum.php?mod=viewthread&tid=213824 （标题即 “Mavic Mini supported on 4.13 version of MSDK & UX SDK”，[二级/官方论坛]）。
- dronedj 关于 Mini 4 Pro：https://dronedj.com/2025/03/21/dji-mini-4-pro-msdk/ （2025-03-21）[二级]：确认 2025-03 更新使 Mini 4 Pro 获得 MSDK 支持；必须使用 DJI RC-N2 遥控器，DJI RC 2（带屏）不支持 MSDK；首发仅 Android。与 v5.13.0 Release Notes 一致。

### 1.6 DJI Fly 原生航点功能（无 SDK 机型的自动化来源）
- 官方帮助页（中文）：https://support.dji.com/help/content?customId=01700007343&spaceId=17&lang=zh-CN&documentType&paperDocType=ARTICLE&re=CN
- 本地证据：data/dji/raw/（2026-11-08 抓取）
- 适用产品原文：DJI Air 3S、DJI Air 3、DJI Mavic 4 Pro、DJI Mavic 3 Pro、DJI Mavic 3 Classic、DJI Mavic 3、DJI Mini 4 Pro、DJI Mini 5 Pro、DJI Lito X1。注意：不含 Mini 3 / Mini 3 Pro / Mini 2 / Mini SE。
- 能力边界原文：单航线最多 200 航点；速度 0.1–15.0 m/s（默认 2.5）；航点高度默认 50 m（相对起飞点）；悬停 0–30 s；每航点可设相机动作（拍照/开始或结束录像）、高度、速度、机头朝向、云台俯仰、变焦；全局速度上限因机型不同（Mini 4 Pro / Air 3 为 12 m/s）；不支持 KML 航线导入；不支持断点续飞；起飞点与首航点距离需在 10 km 内。

## 2. 逐 SDK 矩阵（含非 Mobile SDK）

| SDK/平台 | 定位 | 对 Mini 系列支持 | 一手证据 |
|---|---|---|---|
| Mobile SDK v4 | 旧版移动端 SDK（DJI GO 时代），Android+iOS | Mavic Mini / Mini SE / Mini 2 支持；Mini 3 及以后不支持（v4 已停止新增机型） | 官方兼容表；GitHub v4 releases；dronedj[二级] |
| Mobile SDK v5 | 现役移动端 SDK，Android only | Mini 3 / Mini 3 Pro / Mini 4 Pro 支持；Mini 2/SE/Mavic Mini 不支持；Mini 5 Pro/2 SE/4K 不支持 | 官方产品页支持列表；GitHub README V5.20.1；Release Notes |
| Payload SDK（PSDK） | 机载负载 SDK（云台相机、喊话器等） | 不支持（消费级 Mini 无 PSDK 负载接口；兼容表 Payload SDK 列为空） | 官方兼容表 |
| Onboard SDK（OSDK） | 旧机载 SDK，PDSK v3 起合并入 PSDK | 不支持 | 官方兼容表；MSDK v5 虚拟摇杆文档“OSDK 即当前 PSDK” |
| 上云 API（Cloud API v1/v2） | 企业级机队/机场云接入 | 不支持（支持 M4 系列、M400、M30、M300/M350、M3E/3T 等） | 官方兼容表“上云 API”列 |
| DJI Terra | 离线摄影测量/3DGS 重建软件，非飞行 SDK | 不限机型（输入照片/视频），Mini 可直接用 | 见 05_DJI_Terra与生态3DGS能力.md |
| FlightHub / FlightHub 2 | 企业级云机队管理 | 不支持消费级 Mini | 官方兼容表与产品定位 |

## 3. 重点核实 1：Mini 2 与 MSDK v4 的支持关系

结论：**官方支持，自 MSDK v4.16（2021-12-31 发布）起**，属于 v4 时代最后一批新增消费级机型；到 v4.18（2024-10-24）仍在维护，但 v4 已不再新增机型。

证据链：
1. 官方兼容表（1.1）将 Mini 2 标记为“支持 Mobile SDK”。
2. 官方 GitHub v4 仓库 release 记录（1.5）：v4.16 发布于 2021-12-31。
3. 二级媒体转述官方 Release Notes（dronedj 2022-01-03）：MSDK 4.16 新增 Mini 2 / Mini SE / Air 2S，功能口径 camera / flight controller / gimbal / remote controller；Android 首发、iOS 随后；该版缺口：全景模式、云台高度、FlyZoneManager。
4. Litchi 官方帮助（https://flylitchi.com/help）兼容列表明确含 Mini 2、Mini SE（version 1 only）、Mavic Mini 1——第三方 App 的兼容性反证 MSDK v4 路径可用。
5. Dronelink 官方支持页（https://www.dronelink.com/supported-drones）Mini 2 标记 Supported（RC-N1；Android/App Store 双平台）。

实施注意：
- Mini 2/Mini SE 走 v4，只能用 Android/iOS 原生 App 集成 v4 SDK；v4 与 v5 代码完全不兼容，不能与 v5 机型共用一套 App 代码库。
- 采集时遥控器必须是 RC-N1 一类“手机夹持式”遥控器（第三方 App 需手机端运行）；Smart Controller 需查看 Litchi/Dronelink 兼容说明。
- v4 官方文档页（Hardware Introduction）未更新 Mini 系列，属文档滞后；以兼容表 + Release Notes + 第三方 App 兼容列表交叉为准。

## 4. 重点核实 2：Mini 3 / Mini 4 / Mini 5 与 MSDK

结论：
- Mini 3 与 Mini 3 Pro：**MSDK v5.3.0（2023-04-07）起支持**，仅 Android；遥控器支持 RC N1、RC Pro（官方固件表）。
- Mini 4 Pro：**MSDK v5.13.0（2025-03-17）起支持**，首发仅 DJI RC N2；DJI RC N3 于 v5.17.0（2025-11-04）加入；DJI RC 2（带屏）始终不支持 MSDK（[二级] dronedj 2025-03-21，与官方固件表只列 RC-N2/N3 一致）。
- Mini 5 Pro：**官方兼容表明确“不支持 SDK”**；MSDK V5 支持产品列表与官方仓库 README 均无 Mini 5 Pro。但 DJI Fly 原生航点支持 Mini 5 Pro（官方帮助页），可半自动采集。
- Mini 2 SE / Mini 4K：**官方兼容表明确“不支持 SDK”**；DJI Fly 航点支持列表也不含 → 只能手动/定时拍照。

“不支持 MSDK”的官方证据形态（可直接引用）：
1. 官方兼容表对应行“不支持”；
2. MSDK V5 官方产品页 Supported Products 列表无该机型；
3. 官方 GitHub 仓库 README（V5.20.1）Supported Product 列表无该机型；
4. MSDK V5 Release Notes 自 V5.0.0 至 5.20.1 的全部版本中均无该机型“Add supported aircraft”条目。

## 5. Mini 3 / Mini 3 Pro / Mini 4 Pro 在 MSDK v5 下的能力清单（官方文档口径）

| 能力 | 官方入口/类 | 起始版本 | 关键限制 |
|---|---|---|---|
| 航线任务（KMZ/WPML）：上传/执行/暂停/恢复/监控 | IWaypointMissionManager；WPMZManager（KMZ 编辑/导入导出/静态检查/KML 转 KMZ） | 航线基础能力自 v5 早期；WPMZ 编辑 v5.6.0（2023-09-18）；动作回调 v5.8.0 | 断点续飞官方仅保证 M30/M3E/3T/3M，Mini 系列不在列；航点动作依赖固件 |
| 虚拟摇杆（连续速度控制） | IVirtualStickManager | v5 | 需退出自动任务、遥控器在 N 档；建议发送频率 5–25 Hz |
| 相机控制 | CameraKey / IKeyManager：曝光（快门/ISO/光圈/EV）、图像参数、视频分辨率与帧率、拍照/录像、变焦 | v5 | Mini 系列无光圈可调（固定 f/1.7 或 f/2.8），曝光以快门/ISO/EV 为主 |
| 云台控制 | GimbalKey | v5 | 俯仰/横滚范围随机型；Mini 3/4 Pro 支持俯仰与部分横滚 |
| 媒体文件管理 | IMediaManager / IMediaDataCenter：列表、下载、回放 | v5 | 大文件下载速率受图传链路限制 |
| 遥测 | 传感器数据（GPS、姿态、速度、高度等） | v5 | 官方口径“最高 10 Hz” |
| 图传 | ICameraStreamManager | v5.8.0（2023-12-28） | 仅主相机；Mini 系列可用 |
| 智能飞行（POI / FlyTo / SpotLight / SmartTrack） | IIntelligentFlightManager | v5.14.0（2025-04-16） | 官方明确支持机型含 Mini 4 Pro；SmartTrack 仅企业机型 |
| 避障/感知 | PerceptionManager（企业机型为主） | v5 | 消费级 Mini 的感知接口开放程度有限，需按机型 Key 可用性判断 |

## 6. 遥控器与平台限制（直接决定采集工程可行性）

| 遥控器 | Mini 3 / 3 Pro | Mini 4 Pro | 证据 |
|---|---|---|---|
| DJI RC N1 | 支持 | — | MSDK v5.13.0 固件表（Mini 3/3 Pro 行） |
| DJI RC Pro | 支持 | — | 同上 |
| DJI RC（带屏） | 不支持 | — | Dronelink 官方支持页“DJI RC Not supported” |
| DJI RC N2 | — | 支持（v5.13.0 起） | v5.13.0 固件表；dronedj[二级] |
| DJI RC N3 | — | 支持（v5.17.0 起） | v5.17.0 Release Notes |
| DJI RC 2（带屏） | — | 不支持 | dronedj[二级]；官方固件表未列 |
| iOS 设备 | 不支持（无 MSDK v5 iOS） | 不支持（无 MSDK v5 iOS） | 官方产品页/Release Notes 仅 Android |

推论：若要做“自研 MSDK 采集 App”，必须采购 **RC-N2/RC-N3（Mini 4 Pro）或 RC-N1/RC Pro（Mini 3/3 Pro）+ Android 手机**；带屏遥控器（DJI RC / RC 2）无法装第三方 App，是常见踩坑点。

## 7. 第三方逆向（dji-firmware-tools / DUML）的合法合规风险

对象：https://github.com/o-gs/dji-firmware-tools（GPL-3.0，约 2.3k stars）。其 README 明示能力包括：固件解包/重打包、参数修改、解除参数上限、启用未使用硬件、修改固件二进制、DUML 报文与设备通信。本地证据：data/dji/raw/（api.github.com 拉取的仓库元数据与 README）。

风险分级：
1. **违反许可/用户协议（高，已取得官方原文）**：《DJI 飞行器产品使用条款》（更新日期 2024-07-12，https://www.dji.com/cn/terms ，本地 data/dji/raw/dji_terms_cn.html）明确禁止：
   - 第 3 条(3)：不得对本产品或 DJI 应用程序进行修改、解锁、解码、复制、公开传播、反向编译或导出代码等行为；
   - 第 3 条(4)：不得以非 DJI 官方指导或未经授权的方式改造本产品及 DJI 应用程序，亦不得使用未经许可的周边软硬件连接/控制本产品；
   - 第 3 条(5)：不得解除或修改地理围栏、飞行高度限制，不得修改飞行安全功能；
   - 前言与第 3 条违约后果：DJI 有权限制/停用账号、停止产品使用、终止增值服务，并可能通知监管机构。
   使用 DUML 工具修改固件/飞行参数、绕过 GEO 或限高，直接落在此条款禁止范围内。
2. **著作权与反规避（高）**：固件属受保护计算机程序；美国 DMCA §1201、欧盟 2009/24/EC 第 6 条、中国《著作权法》关于避开技术措施的规定均可能适用；GPL-3.0 仅授予其代码本身的复制/修改权，不授予对 DJI 固件的任何权利。
3. **保修与安全责任（高）**：修改固件/参数会失去官方保修；改变限高、限速、禁飞区逻辑可能导致炸机、伤人或空域违规，责任由操作者承担。
4. **航空法规（高）**：绕过 GEO 禁飞/限高在中国、欧盟、美国均可能违反无人机飞行管理法规（如中国《无人驾驶航空器飞行管理暂行条例》）。
5. **账号/供应链风险（中）**：固件签名校验（README 明确部分固件包使用非对称签名）导致变砖风险；DJI 账号与设备绑定可能异常。

项目建议：
- 3DGS 采集链路 **不需要** 任何逆向：Mini 3/3 Pro/4 Pro 用官方 MSDK v5 即可完成航点+相机+媒体全自动；Mini 5 Pro 用 DJI Fly 原生航点。
- 逆向工具仅可用于学术性固件分析/维修场景，且不得用于绕过地理围栏、限高、限速或改造飞行器适航状态；量产/商用项目明确禁用。
- 如需引用，建议只引用其“DUML 协议说明”作为协议理解材料，不落地任何修改飞行器行为的工具。

## 8. 对 3DGS 采集链路的选型建议（与本项目直接相关）

1. **优先 Mini 4 Pro**：唯一同时满足“MSDK v5 全自动 + DJI Fly 原生航点 + 1/1.3 英寸 48MP 相机”的 Mini；需 Android + RC-N2/RC-N3。
2. **次选 Mini 3 Pro / Mini 3**：MSDK v5 可全自动，但无 DJI Fly 原生航点（需自研 App 或 Litchi Pilot）；相机同为 1/1.3 英寸 48MP（Mini 3 无 D-Log、无前视避障等差异见 02）。
3. **Mini 2 / Mini SE**：可用 MSDK v4 第三方 App（Litchi/Dronelink）自动采集，成本最低但相机 1/2.3 英寸 12MP，纹理细节弱于 1/1.3 英寸，3DGS 质量受限。
4. **Mini 5 Pro**：无法 SDK 自动化，但 DJI Fly 航点（最多 200 点、0.1–15 m/s）足以完成中小场景采集；适合“不写代码、只验证”的路线。
5. **Mini 2 SE / Mini 4K**：只能手动/定时拍照，不建议作为 3DGS 主采集机型。

## 9. 证据文件索引（本机可复核）

| 证据 | 路径 |
|---|---|
| 官方 SDK 兼容表（中文 SSR HTML） | data/dji/raw/sdk_compat_cn.html |
| 官方 SDK 兼容表（英文） | data/dji/raw/sdk_compat_en.html |
| MSDK V5 官方产品页（支持机型/平台） | data/dji/raw/dev_msdk_en.html |
| MSDK V5 Release Notes 全文（56 版本） | data/dji/raw/text/relnotes_all.txt |
| MSDK V5 文档页：航线/WPML | data/dji/raw/text/waypoint.txt |
| MSDK V5 文档页：虚拟摇杆 | data/dji/raw/text/virtual_stick.txt |
| MSDK V5 文档页：相机/媒体/任务/简介 | data/dji/raw/text/（media_file.txt、missions.txt、msdk_introduction.txt） |
| MSDK v4 文档 Hardware Introduction 支持表 | data/dji/raw/msdk_v4_product_intro.html |
| MSDK v4 产品页 | data/dji/raw/msdk_v4_landing.html |
| DJI Fly 航点官方帮助页 | data/dji/raw/（2026-11-08 抓取，见 references.md） |
| DJI Terra Release Notes v5.0.2（PDF+文本） | data/dji/raw/terra_rn_5.0.2.pdf / .txt |
| DJI 飞行器产品使用条款（官方原文，2024-07-12） | data/dji/raw/dji_terms_cn.html / .txt |

## 10. 未决问题（下一轮补强）
- MSDK v4 iOS 版本是否覆盖 Mini 2（dronedj 称 iOS 随后跟进；需 v4 iOS Release Notes 一手证据）。
- Mini 3/3 Pro 在 MSDK v5 下是否支持航线断点续飞（当前官方仅列 M30/M3E，Mini 未明确）。
