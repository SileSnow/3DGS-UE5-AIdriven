# references —— DJI Mini × SDK × 3DGS 调研引用清单

> 访问日期：2026-11-08（Asia/Shanghai）。状态列：OK=成功抓取并落盘；SPA=页面为单页应用，正文经站点 JS bundle 提取；FAIL=访问失败（记录替代来源）；SEC=二级来源（媒体/论坛/第三方，已标注）。
> 本地证据目录：dji_ue5_3dgs/data/dji/raw/ 与 dji_ue5_3dgs/data/dji/samples/。所有一手结论均可回溯到对应原始文件。

## A. DJI 官方一手来源

| # | 标题/内容 | URL | 状态 | 本地证据 | 用于 |
|---|---|---|---|---|---|
| A1 | 《DJI 大疆产品 SDK 支持情况介绍》（官方 SDK 兼容表，中文） | https://support.dji.com/help/content?customId=01700000763&spaceId=17&re=CN&lang=zh-CN | OK | data/dji/raw/sdk_compat_cn.html | 01 机型兼容矩阵 |
| A2 | DJI Product SDK Compatibility（英文版同一文章） | https://support.dji.com/help/content?customId=01700000763&documentType&lang=en&paperDocType=ARTICLE&re=US&spaceId=17 | OK | data/dji/raw/sdk_compat_en.html | 01 |
| A3 | DJI Mobile SDK V5 官方产品页（Supported Products / Supported Platform） | https://developer.dji.com/mobile-sdk/ | OK | data/dji/raw/dev_msdk_en.html | 01 Mini3/3Pro/4Pro 支持、Android-only |
| A4 | DJI Mobile SDK V5 中文产品页 | https://developer.dji.com/cn/mobile-sdk/ | OK | data/dji/raw/dev_msdk_cn.html | 01 |
| A5 | MSDK V5 下载页（Release notes 入口） | https://developer.dji.com/mobile-sdk/downloads/ | OK | data/dji/raw/dev_msdk_downloads_en.html | 01 |
| A6 | MSDK V5 官方文档/Release Notes（页面标题 Mobile SDK；正文经站点 JS bundle 提取） | https://developer.dji.com/doc/mobile-sdk-tutorial/en/ | SPA | data/dji/raw/msdkv5_chunks/、data/dji/raw/text/relnotes_all.txt、en_release_notes.txt | 01 版本-机型-固件对应、能力清单 |
| A7 | MSDK v4 产品页（Supported Products 分类） | https://developer.dji.com/mobile-sdk-v4/ | OK | data/dji/raw/msdk_v4_landing.html | 01 |
| A8 | MSDK v4 文档 Hardware Introduction（Supported Products 表，2020-05-23 版） | https://developer.dji.com/mobile-sdk/documentation/introduction/product_introduction.html | OK | data/dji/raw/msdk_v4_product_intro.html | 01（说明 v4 文档未更新 Mini 系列） |
| A9 | MSDK V5 官方 GitHub 仓库 README（V5.20.1，支持机型清单） | https://github.com/dji-sdk/Mobile-SDK-Android-V5 | OK（经 api.github.com 拉取） | data/dji/raw/（README 文本） | 01 |
| A10 | MSDK V5 官方 GitHub Releases（版本+日期） | https://github.com/dji-sdk/Mobile-SDK-Android-V5/releases | OK（api.github.com） | 会话记录/01 时间轴 | 01 |
| A11 | MSDK v4 官方 GitHub Releases（v4.16=2021-12-31 … v4.18=2024-10-24） | https://github.com/dji-sdk/Mobile-SDK-Android/releases | OK（api.github.com） | 01 时间轴 | 01 |
| A12 | DJI Fly 航点飞行功能介绍（官方帮助，含支持机型与能力边界） | https://support.dji.com/help/content?customId=01700007343&spaceId=17&lang=zh-CN&documentType&paperDocType=ARTICLE&re=CN | OK | data/dji/raw/（2026-11-08 抓取） | 01/02 |
| A13 | DJI Mini 3 官方规格页 | https://www.dji.com/cn/mini-3/specs | OK | data/dji/raw/spec_mini-3_cn.html | 02 相机参数 |
| A14 | DJI Mini 4 Pro 官方规格页 | https://www.dji.com/cn/mini-4-pro/specs | OK | data/dji/raw/spec_mini-4-pro_cn.html | 02 |
| A15 | DJI Mini 5 Pro 官方规格页 | https://www.dji.com/cn/mini-5-pro/specs | OK | data/dji/raw/spec_mini-5-pro_cn.html | 02 |
| A16 | DJI Mini 2 SE / Mini 4K 官方规格页 | https://www.dji.com/cn/mini-2-se/specs | OK | data/dji/raw/spec_mini-2-se_cn.html | 02 |
| A17 | DJI Mini 2 官方支持产品页（旧规格页 302 跳转目标） | https://www.dji.com/cn/support/product/mini-2 | OK | data/dji/raw/spec_mini2_cn.html/.txt | 02 |
| A18 | DJI Mini 3 Pro 官方支持产品页（旧规格页 302 跳转目标） | https://www.dji.com/cn/support/product/mini-3-pro | OK | data/dji/raw/spec_mini3pro_cn.html/.txt | 02 |
| A19 | DJI Mini SE / Mavic Mini 官方支持产品页 | https://www.dji.com/cn/support/product/mini-se ；https://www.dji.com/cn/support/product/mavic-mini | OK | data/dji/raw/spec_minise_cn.html、spec_mavicmini_cn.html | 02 |
| A20 | DJI Terra 官方产品页（3DGS 能力/硬件/版本） | https://www.dji.com/cn/dji-terra | OK | data/dji/raw/terra_product_cn.html | 05 |
| A21 | DJI Terra Release Notes v5.0.2 PDF（含 v5.0.0 3DGS 新增功能与限制） | https://terra-1-g.djicdn.com/263b7ee0f1fe477c91b7ca44348166fe/releasenotes/DJI%20Terra%20Release%20Notes%20v5.0.2.pdf | OK | data/dji/raw/terra_rn_5.0.2.pdf / .txt | 05 |
| A22 | DJI Terra Release Notes（最新版 PDF） | https://terra-1-g.djicdn.com/263b7ee0f1fe477c91b7ca44348166fe/releasenotes/DJI%20Terra%20Release%20Notes.pdf | OK | data/dji/raw/terra_rn_latest.pdf | 05 |
| A23 | DJI Terra 用户手册 — 可见光链 Gaussian Splatting 章节 | https://terra.dji.com/user-manual/en/visible-light-reconstruction/gaussian-splatting.html | SPA | data/dji/raw/terra_um_chunks/（章节结构） | 05 |
| A24 | DJI Terra 用户手册 — LiDAR 链 Gaussian Splatting 章节 | https://terra.dji.com/user-manual/en/lidar/gaussian-splatting.html | SPA | 同上 | 05 |
| A25 | dji-sdk 官方组织（iOS 仓库无 V5 对应项，供交叉核对） | https://github.com/dji-sdk | OK（api.github.com） | — | 01 iOS 现状 |
| A26 | DJI Cloud API 文档产品支持页（SPA，未逐字抓取；Cloud API 支持范围以 A1 表2“上云 API”列为准） | https://developer.dji.com/doc/cloud-api-tutorial/en/overview/product-support.html | SPA/未取正文 | — | 01（标注） |
| A27 | 《DJI 飞行器产品使用条款》（更新 2024-07-12；第 3 条禁止修改/反向编译/解锁/改造、解除地理围栏与限高） | https://www.dji.com/cn/terms | OK | data/dji/raw/dji_terms_cn.html / .txt | 01 第 7 节合规风险（一手原文） |

## B. 二级来源（媒体/论坛/第三方 App 官方页；正文中已标注[二级]）

| # | 标题/内容 | URL | 状态 | 用于 |
|---|---|---|---|---|
| B1 | dronedj：DJI Mobile SDK now supports Mini 2, Mini SE, Air 2S（2022-01-03，转述 MSDK 4.16 Release Notes） | https://dronedj.com/2022/01/03/dji-sdk-mini-2-se-air-2s/ | OK | 01 Mini 2 走 v4.16 的能力口径与已知缺口 |
| B2 | dronedj：DJI Mini 4 Pro drone gains MSDK support（2025-03-21，RC-N2 only、Android 首发） | https://dronedj.com/2025/03/21/dji-mini-4-pro-msdk/ | OK | 01 Mini 4 Pro 支持细节（与官方 v5.13.0 互证） |
| B3 | dronewatch.nl：Mini 4 Pro 获外部 App 支持（2025-03-19，v5.13.0） | https://www.dronewatch.nl/2025/03/19/dji-mini-4-pro-krijgt-ondersteuning-voor-externe-apps-dankzij-nieuwe-sdk/ | OK | 01（二级佐证 v5.13.0） |
| B4 | DJI 官方论坛帖：Mavic Mini supported on 4.13 version of MSDK & UX SDK | https://forum.dji.com/forum.php?mod=viewthread&tid=213824 | FAIL（正文抓取仅 157 字节，疑反爬） | 01（标注论坛证据，建议人工复核） |
| B5 | Litchi 官方帮助（兼容列表，2026-03-31 更新；Mini 3+ 需 Litchi Pilot） | https://flylitchi.com/help | OK | 02 第三方 App 兼容性 |
| B6 | Litchi 官网 | https://flylitchi.com/ | OK | 02 |
| B7 | Dronelink 官方 Supported Drones（Mini 4 Pro/Mini 5 Pro 的支持方式与遥控器限制） | https://www.dronelink.com/supported-drones | OK | 02 第三方 App 兼容性 |
| B8 | Grey Arrows 论坛：DJI have dropped support for their iOS SDK | https://greyarro.ws/t/dji-have-dropped-support-for-their-ios-sdk/70771/4 | 部分（正文 859 字节） | 01 iOS 现状（仅社区说法，未采信为结论） |

## C. 工具/方法学引用

| # | 标题 | URL | 状态 | 用于 |
|---|---|---|---|---|
| C1 | ExifTool DJI 标签表（DJI XMP/Info 标签官方逆向清单） | https://exiftool.org/TagNames/DJI.html | OK | 03 字段清单 |
| C2 | COLMAP FAQ（pose priors with GPS / pose_prior_mapper / model_aligner） | https://colmap.github.io/faq.html | OK | 03 位姿先验+精化方案 |
| C3 | OpenDroneMap 飞行文档（航测飞行规划参考） | https://docs.opendronemap.org/flying/ | OK | 02 航线设计参考 |
| C4 | o-gs/dji-firmware-tools（DUML 固件工具，GPL-3.0，README 说明可改固件/参数） | https://github.com/o-gs/dji-firmware-tools | OK（api.github.com） | 01 逆向合规风险 |

## D. 真实样本照片（04，Wikimedia Commons，CC 许可）

| # | 文件 | Commons 文件页 | 许可/作者 | 本地 |
|---|---|---|---|---|
| D1 | Dülmen, Sportzentrum Süd, Parkplatz -- 2026 -- 0223.jpg（Mini 4 Pro） | https://commons.wikimedia.org/wiki/File:Dülmen,_Sportzentrum_Süd,_Parkplatz_--_2026_--_0223.jpg | CC BY-SA 4.0 / Dietmar Rabich | data/dji/samples/FC8482_Mini4Pro.jpg |
| D2 | Dülmen, Kirchspiel, Dernekamp, Getreidefeld -- 2024 -- 0003.jpg（Mini 4 Pro） | https://commons.wikimedia.org/wiki/File:Dülmen,_Kirchspiel,_Dernekamp,_Getreidefeld_--_2024_--_0003.jpg | CC BY-SA 4.0 / Dietmar Rabich | data/dji/samples/FC8482_Mini4Pro_b.jpg |
| D3 | Ostuni col drone.jpg（Mini 3 Pro） | https://commons.wikimedia.org/wiki/File:Ostuni_col_drone.jpg | CC BY 4.0 / ParisTaras | data/dji/samples/FC3582_Mini3Pro.jpg |
| D4 | Karpniki wschód słońca.jpg（Mini 3 Pro） | https://commons.wikimedia.org/wiki/File:Karpniki_wschód_słońca.jpg | CC BY-SA 4.0 / Gswito | data/dji/samples/FC3582_Mini3Pro_b.jpg |
| D5 | Lighthouse Aniva.jpg（Mini 2） | https://commons.wikimedia.org/wiki/File:Lighthouse_Aniva.jpg | CC BY 4.0 / Pavelappps | data/dji/samples/FC3170_Mini2.jpg |

## E. 访问失败/受限记录（透明记录，已用替代来源）
1. forum.developer.dji.com：DNS 解析失败（getaddrinfo ENOTFOUND）→ 用 support.dji.com 帮助文章与官方文档替代。
2. web.archive.org（Wayback API）：连接超时 → Mini 2 / Mini 3 Pro 旧规格页无法通过快照获取；改用官方 /support/product/ 支持页（A17/A18）。
3. github.com / raw.githubusercontent.com 直连：超时 → 全部改用 api.github.com（官方内容）与本地已下载资料；未使用 jsDelivr（本任务不需要）。
4. developer.dji.com 文档站为 VuePress SPA：正文需从站点 JS bundle 提取（已落盘 A6）；直接 URL 在浏览器可正常阅读。
5. terra.dji.com 用户手册为 SPA：正文未逐字抓取，结论以官方 Release Notes PDF 与产品页为准（A21/A22/A20）。
6. flylitchi.com/pilot 与 /whats_new：404（Litchi Pilot 具体页面路径未公开在帮助页），兼容性结论以 flylitchi.com/help 为准。
7. 已取得 DJI 官方使用条款原文（A27，2024-07-12 版）；仍未取得：Mini 系列 SD 卡原片（04 用 Lightroom 导出样本）、真实 DJI 视频 SRT 样本（03 标注为样板）、MSDK v4 iOS Release Notes。
