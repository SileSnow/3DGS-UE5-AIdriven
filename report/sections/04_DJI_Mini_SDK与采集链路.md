## 4. DJI Mini 系列 SDK 与采集链路分析

### 4.1 机型 × SDK 支持矩阵（关键结论：Mini 3/3 Pro/4 Pro 支持 Mobile SDK）

> 本节事实来源：① DJI 官方支持页《DJI 大疆产品 SDK 支持情况介绍》（https://support.dji.com/help/content?customId=01700000763&spaceId=17&re=CN ；数据经页面 SSR 文本核验，2026-11-08）；② DJI 官方 GitHub 仓库 `dji-sdk/mobile-sdk-android-v5` README（MSDK V5.20.1，仓库 2026-11-05 更新，https://github.com/dji-sdk/mobile-sdk-android-v5 ）；③ 媒体交叉验证：DroneDJ 2025-03-21（Mini 4 Pro 获 MSDK 支持）、Dronewatch 2025-03-19（明确 MSDK v5.13.0）。

| 机型 | 官方兼容页“支持 SDK” | Mobile SDK（官方仓库/版本，dji-research 已钉死） | 对 3DGS 采集的意义 |
|---|---|---|---|
| DJI Mini 5 Pro | **不支持** | 不在 MSDK V5 支持列表 | 只能 DJI Fly 手动/机内航点；**SDK 自动化不可行** |
| DJI Mini 4 Pro | 支持 | ✅ MSDK V5 **v5.13.0（2025-03-17）起** | **可自研 Android App 自动化采集**；v5.13 仅 RC-N2，RC-N3 到 v5.17.0（2025-11-04）才支持 |
| DJI Mini 3 Pro | 支持 | ✅ MSDK V5 **v5.3.0（2023-04-07）起** | 可自研 App（详见 4.2） |
| DJI Mini 3 | 支持 | ✅ MSDK V5 **v5.3.0（2023-04-07）起** | 同上 |
| DJI Mini 2 / Mini SE | 支持 | MSDK **v4.16（2021-12-31）**；v4 末版 4.18（2024-10-24） | 可用 MSDK v4 App 自动化（能力较旧，机型已停产） |
| Mavic Mini | 支持 | MSDK **v4.13**（DJI 官方论坛二级证据，Release Notes 正文未取得，标注待复核） | 同上（更早期、能力更有限） |
| DJI Mini 2 SE / Mini 4K | **不支持** | — | 只能手动/第三方非 SDK 方案 |
| Air 3 / Air 3S / Mavic 4 Pro / Mavic 3 (Pro/Classic) | **不支持** | 不在 MSDK V5 列表 | 注意：并非“越贵越支持 SDK” |

**按自动化能力分档（直接用于选型）**：

| 分档 | 含义 | 机型 | SDK 路线 |
|---|---|---|---|
| **A** | SDK 全自动（MSDK v4；**Android 已证实，iOS 待复核**） | Mavic Mini、Mini SE、Mini 2 | MSDK v4.16（Mini 2/Mini SE）；Mavic Mini 自 v4.13（二级证据待复核） |
| **A′** | SDK 全自动（MSDK v5，**仅 Android**） | **Mini 4 Pro、Mini 3 Pro、Mini 3** | v5.13.0 / v5.3.0 / v5.3.0 |
| **B** | 无 SDK，但 DJI Fly 原生航点可自动执行（半自动） | Mini 5 Pro | DJI Fly 航点（官方支持机型列表含） |
| **C** | 无 SDK 且无原生航点，只能手动/定时拍照 | Mini 2 SE、Mini 4K | 无 |

> 补充：行业级 Mavic 3E/3T/3M **支持 MSDK v5**，消费级 Mavic 3/3 Pro/3 Classic **不支持**（容易混淆）。
>
> 选型建议：**生产采集优先 A′ 档的 Mini 4 Pro**（画质最好、版本最新、原生航点+SDK 双保险）；预算极低且接受 1/2.3 英寸画质时选 A 档 Mini 2；Mini 5 Pro 只能半自动（B）；Mini 2 SE/4K 不推荐（C）。

**关键使用限制（决定真实可执行性）**：
1. **遥控器**：Mini 4 Pro 使用 MSDK 必须搭配 **DJI RC-N2**（手机夹持式）；**DJI RC 2（带屏）不支持 MSDK**（DroneDJ 2025-03-21 明确）。RC-N3 的支持要到 MSDK v5.17.0（2025-11-04）才加入。采购/租赁时必须以 RC-N2 为准。
2. **平台：MSDK V5 目前仅 Android**（官方页只列 Android 平台与 Android API Reference；Release Notes 全为 Android；无 iOS V5 仓库）。这意味着采集 App 必须基于 Android 手机/平板开发。
3. **版本**：MSDK 版本与机型能力强相关（Mini 3/3 Pro 自 v5.3.0，Mini 4 Pro 自 v5.13.0）；App 需按目标机型锁定版本并做回归测试。
4. **账号/Key**：MSDK 需 DJI 开发者账号与 App Key（免费注册），打包/上架需遵守 DJI SDK 许可协议。

### 4.2 MSDK v5 能力边界（面向 3DGS 采集的需求映射）

> 已由 dji-research 依据官方 MSDK Release Notes/文档核实（证据：`data/dji/raw/text/relnotes_all.txt`、`missions.txt`、`virtual_stick.txt` 等）。

| 3DGS 采集需求 | MSDK v5 对应能力（预期） | 备注 |
|---|---|---|
| 航点航线自动飞行 | **KMZ/WPML 航线**（WPMZManager 自 MSDK v5.6.0）；**断点续飞官方保证范围仅 M30/30T、Mavic 3E/3T/3M，Mini 未列入**（非明确“不支持”，但不可依赖） | Mini 4 Pro 可用 WPML |
| 定时/等距拍照 | 相机拍照 + 曝光/快门/ISO/白平衡手动控制（已证实）；**“间隔/等距”需 App 侧定时触发**（SDK 无内置间隔拍照 API 证据） | 3DGS 需固定曝光、避免自动曝光跳变 |
| 云台角度控制 | Gimbal 控制（俯仰/横滚/偏航） | 五向/倾斜航线必备 |
| 位姿/遥测回传 | FlightController 状态、Gimbal 角度、**遥测频率 ≤10 Hz**；**虚拟摇杆 5–25 Hz** | 10 Hz 遥测对高速飞行位姿外推有限制 |
| 媒体文件下载 | MediaManager 下载/列表 | 采集后批量回传 |
| 飞行安全/限高 | 已核实：**FlyZoneManager**（限飞区查询/解禁）+ 返航/避障状态读取；限高限距设置接口待验证 | 园区/城市环境必备；限高限距需按机型文档核实 |

**能力缺口提示**：MSDK 不提供“相机曝光时刻的高精度位姿/时间同步”，云台角与 GPS 为消费者级精度；RTK 机型才可达到测绘级定位。因此 3DGS 的最终位姿仍需 COLMAP/BA 精化（见 4.4）。

### 4.3 采集方案对比

| 方案 | 机型要求 | 自动化程度 | 位姿元数据 | 成本/门槛 | 适用建议 |
|---|---|---|---|---|---|
| DJI Fly 手动飞行 + 定时拍照 | 全系 Mini | 低（人工） | 有 EXIF，无航线级一致性 | 零成本 | 小场景/验证期/不支持 SDK 的机型 |
| DJI Fly 机内航点（若有） | 部分机型 | 中 | 有 EXIF | 零成本 | 规则区域快速采集 |
| **自研 MSDK App（Android + RC-N2）** | Mini 3/3 Pro/4 Pro（及 Mini 2 系 v4） | **高（可编程航点+定时+参数锁定）** | 可回传 GPS/云台/时间戳，质量最好 | 开发 1–3 人周；DJI 账号 | **推荐：生产化采集** |
| 第三方 App（**Litchi / Dronelink**，已核实；DroneDeploy/Drone Harmony 未取得一手证据） | 依 MSDK 支持机型 | 高（现成航测任务） | 依 App 导出 | 订阅/买断 | 快速验证/不愿自研 |
| DJI Terra（官方处理，不采集） | 全系（输入照片） | —（后处理） | — | Flagship 授权 | **官方 3DGS 一键链**，见 4.5 |

**官方 DJI Fly 航点能力（不写 App 时的备选，dji-research 已查证）**：
- 官方航点支持机型表包含 **Mini 4 Pro / Mini 5 Pro**，**不包含 Mini 3 / Mini 3 Pro**；
- 单任务航点上限 **200 个**，速度范围 **0.1–15 m/s**，**不支持 KML 导入**、**不支持断点续飞**；
- 因此 Mini 5 Pro 用户虽然无 SDK，但仍可用 DJI Fly 航点做半自动采集；Mini 3/3 Pro 用户则需第三方 App 或手动。

**推荐组合（生产）**：Mini 4 Pro + RC-N2 + 自研 MSDK App（航点+定时拍照+固定曝光+元数据落盘）→ 回传 → COLMAP/3DGS 训练 → UE5 插件渲染；若工期紧，先用第三方 App 或 DJI Fly 手动采集验证画质与流程。

### 4.4 元数据与位姿先验（真实 DJI 数据 → COLMAP/UE）

**照片元数据（EXIF/XMP）典型字段**：
- GPS：`GPSLatitude/GPSLatitudeRef`、`GPSLongitude/GPSLongitudeRef`、`GPSAltitude/GPSAltitudeRef`；
- 相对高度：`RelativeAltitude`（DJI XMP）；
- 云台姿态：`GimbalYawDegree`、`GimbalPitchDegree`、`GimbalRollDegree`（DJI XMP 命名空间 `drone-dji`）；
- 相机：`FocalLength`、`FocalLengthIn35mmFormat`、`DigitalZoomRatio`、图像宽高；
- 时间：`DateTimeOriginal`、`SubSecTimeOriginal`；
- 视频：同名信息在配套 `.SRT` 字幕/遥测文件中逐帧记录（**本次未取得真实 SRT 样板**，字段以官方文档为准）。

**精度与局限**：
| 项 | 典型精度 | 对 3DGS 的影响 |
|---|---|---|
| GPS 水平定位（无 RTK） | 官方悬停精度 ±0.5 m（GNSS）；**绝对定位工程经验 1–5 m**（需 GCP 校验，无官方实测数据） | 只能做初始化/约束，不能直接当外参 |
| 云台角 | 偏航约 1–3°、俯仰/横滚约 0.5–2°（工程估算；官方 ±0.01° 为增稳精度、非绝对角度精度） | 可作旋转先验，仍需 BA 精化 |
| 相机曝光时刻 vs 遥测时间 | 无严格同步（消费者机型） | 高速飞行时位姿外推误差增大 |
| 内参 | EXIF 焦距 + 数码变焦字段 | 需按实际分辨率换算 fx/fy；变焦/裁切要校正 |

**转换链路（本工程实现）**：`WGS84 → 局部 ENU（以首帧为原点）→ UE 世界（cm，X前Y右Z上）↔ COLMAP 世界（右手系）`；相机轴系 UE(X前,Y右,Z上,左手) 与 COLMAP(X右,Y下,Z前,右手) 的换算需翻转 Y 轴并做基变换，转换后必须通过**重投影自检（<1 px）**。

**真实样张实测（dji-research，5 张 CC 许可照片：Mini 4 Pro×2 / Mini 3 Pro×2 / Mini 2）**：
- 5 张样片（Lightroom/Photoshop 导出，**非 SD 卡原始文件**）中：**XMP 云台字段完整**（`drone-dji:GimbalYawDegree/PitchDegree/RollDegree` 等），其中 2 张的 EXIF GPS 被导出流程剥离但 XMP 仍保留 GPS；`AbsoluteAltitude`、`RelativeAltitude`、`GpsStatus` 等字段可见。**SD 卡原片未取得实测**，结论需实飞原片复核；
- **修图/导出/社交软件转存会剥离 GPS**；`GpsStatus` 可能为 `Invalid`、`AltitudeType` 出现 `RtkAlt`、`UTCAtExposure` 可能为空、全景拼接会改写云台角；
- 结论：**位姿先验必须使用相机原始文件**（或 MSDK 采集 App 自己落盘的元数据），并且 **EXIF 与 XMP 双解析**（云端/第三方库常漏 XMP）。

**融合方案（推荐）**：
1. 用 EXIF/GPS/云台角构造 COLMAP 初始位姿（或作为先验约束）；
2. 跑 COLMAP 特征匹配 + BA 精化（可用 GPS 先验缩小匹配搜索范围、提升弱纹理场景稳定性）；
3. 3DGS 训练直接用精化后的 COLMAP 位姿；
4. 若场景大/纹理弱，增加控制点或使用 RTK 机型/后处理 PPK 提升绝对精度。

### 4.5 DJI Terra 官方 3DGS 链路（L1，官方文档证据）

> 来源：DJI Terra Release Notes v5.0.2 PDF（官方，已下载至 `shared/terra_release_notes_5.0.2.pdf`，56 页，可用 pypdf 复现提取）。

| 项 | 官方说明 |
|---|---|
| 引入版本 | **DJI Terra v5.0.0（2025-07-18）**："Now supports Gaussian splatting for visible light reconstruction projects, providing both 2D and 3D outputs." |
| 版本档位 | Standard 与 **Flagship**；可见光 Gaussian splatting **仅 Flagship 版包含** |
| 输出格式 | **PLY** + **B3DM（3D Tiles，DJI Terra LOD format，compatible with Cesium）** + GeoTIFF（2D）（dji-research 已核实 B3DM） |
| 输出路径 | `<ProjectName>/3dgs/results` |
| 硬件要求 | Windows 10+ 64-bit、**≥32 GB RAM**、NVIDIA compute capability ≥6.1（最低 4 GB VRAM、推荐 8 GB+）、支持 RTX 50 系 |
| 已知限制 | 暂不支持集群重建、标注与量测；Gaussian splatting 的 Cesium 插件将在后续版本提供 |
| **航飞任务限制** | **Terra v5.0.0 仅支持 Detailed Inspection 与 Agricultural Applications 航飞任务**；其它航线功能需用 v4.5.0（无 3DGS）→ **Mini 常规航测航线能否直接进入 Terra 5 的 3DGS 流程需实测验证** |
| **本机适用性** | ❌ **本机 16 GB RAM 不满足 32 GB 要求** → 官方链在本机不可直接实测（需升级内存或使用更高配工作站）；本次验证主链路因此采用开源链 |

**与 UE5 的衔接方式**：
1. **PLY 路线（最直接）**：Terra 输出 PLY → UE5 3DGS 插件（如本验证采用的 Italink 插件或商业插件）导入渲染；
2. **3D Tiles 路线（待验证）**：Terra 输出 3D Tiles → **Cesium for Unreal**（Cesium 官方 2026-04 博客称已支持 3DGS 3D Tiles + LOD，https://cesium.com/blog/2026/04/27/3d-gaussian-splats-lod/ ；**该引用本次复核 fetch 失败，且与 Terra“Cesium 插件后续版本发布”的表述存在张力，故标为待验证**）→ 大场景流送，适合城市级/园区级；
3. **注意**：Terra 的 3D Tiles 是“DJI Terra LOD format, compatible with Cesium”，与 Cesium 2026 年发布的 3DGS 3D Tiles 规范是否完全一致需实测验证（列为待验证项）。

**官方链 vs 开源链（本次实测）对比框架**：

| 维度 | DJI Terra 官方链 | 开源链（本验证） |
|---|---|---|
| 成本 | Flagship 商业授权 | 免费（COLMAP/gsplat/UE 插件开源） |
| 易用性 | 一键、图形化 | 需搭环境、写脚本 |
| 可控性 | 参数黑盒、扩展有限 | 全流程可改、可集成自研 SDK 采集 |
| 数据合规 | 数据经 DJI 软件处理 | 本地处理、数据不出内网 |
| 输出 | PLY/3D Tiles/GeoTIFF | PLY（自选格式转换） |

### 4.6 合规与风险（SDK/固件/飞行）

| 风险 | 说明 | 建议 |
|---|---|---|
| SDK 许可 | MSDK 使用需遵守 DJI SDK License；App Key 绑定包名/签名 | 走官方注册流程，不做未授权分发 |
| 固件/协议逆向 | DJI《飞行器产品使用条款》（2024-07-12）第 3 条 (3)(4)(5) 明文禁止修改/解锁/反向编译/解除地理围栏与限高；第三方逆向（DUML/dji-firmware-tools）还可能违反许可、影响保修，且新固件易失效 | **生产链路禁用**；报告仅作风险提示 |
| 飞行法规 | 249g 机型在多数地区门槛低但并非“免监管”；中国需实名登记/空域申请；城市/机场净空区禁飞 | 采集前做空域与审批核查，购买保险 |
| 隐私/数据 | 园区/建筑拍摄涉及隐私与保密 | 数据本地化处理，必要时打码/脱敏 |
| 机型供应 | Mini 5 Pro 不支持 SDK、RC 2 不支持 MSDK | 采购清单中明确“Mini 4 Pro + RC-N2 + Android 手机” |

> 本节详细调研文档见 `docs/research/01_DJI_Mini_SDK能力矩阵.md`、`02_航拍采集方案对比.md`、`03_DJI元数据与位姿先验.md`、`05_DJI_Terra与生态3DGS能力.md` 与 `references.md`（dji-research 产出）。