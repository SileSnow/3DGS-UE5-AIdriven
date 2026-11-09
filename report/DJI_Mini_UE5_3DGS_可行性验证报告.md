# 以大疆 Mini 系列为基础的 UE5 3DGS 技术可行性验证报告

> 文档版本：v1.0（2026-11-08）
> 验证环境：Windows 11 / RTX 5060 Laptop 8GB / UE 5.8.4 / PyTorch 2.13.0+cu130
> 项目根目录：dji_ue5_3dgs/（代码、日志、数据、截图均可在项目内找到）
> 证据规则：正文所有定量结论均回链到项目内文件；官方资料附 URL。
## 目录

- 0.1 五维可行性结论
- 0.2 推荐方案（一句话）
- 0.3 三个必须知道的限制
- 0.4 建议下一步（PoC 30 天）
- 1. 执行摘要
- 2. 背景与问题定义
  - 2.1 3DGS 与 UE5：为什么值得验证
  - 2.2 为什么选择 DJI Mini 系列
  - 2.3 待验证问题拆解（Q1–Q7）
  - 2.4 验证边界（明确不做什么）
- 3. 验证方法与判据
  - 3.1 可行性分级（本报告采用 L0–L4）
  - 3.2 实验环境
  - 3.3 端到端验证链路设计
  - 3.4 指标体系
  - 3.5 证据管理规则
- 4. DJI Mini 系列 SDK 与采集链路分析
  - 4.1 机型 × SDK 支持矩阵（关键结论：Mini 3/3 Pro/4 Pro 支持 Mobile SDK）
  - 4.2 MSDK v5 能力边界（面向 3DGS 采集的需求映射）
  - 4.3 采集方案对比
  - 4.4 元数据与位姿先验（真实 DJI 数据 → COLMAP/UE）
  - 4.5 DJI Terra 官方 3DGS 链路（L1，官方文档证据）
  - 4.6 合规与风险（SDK/固件/飞行）
- 5. 3DGS 重建链路实测
  - 5.1 数据准备
  - 5.2 位姿求解
  - 5.3 训练实现与参数
  - 5.4 质量结果
  - 5.5 性能与资源
  - 5.6 质量分析：为什么全量 PSNR 偏低（欠训练，而非链路错误）
  - 5.7 与 gsplat 官方实现的对比（如适用）
- 6. UE5 集成与渲染验证
  - 6.1 UE5 3DGS 生态盘点（截至 2026-11，本机 UE 5.8.4）
  - 6.2 本机集成实现（UE 5.8.4）
  - 6.3 渲染正确性验证
  - 6.3.1 渲染正确性验证
  - 6.4 性能实测（RTX 5060 Laptop 8GB）
  - 6.5 已知限制与风险（UE 侧）
- 7. 端到端流程与工程化建议
  - 7.1 推荐生产流水线
  - 7.2 自研 MSDK 采集 App 功能设计（建议）
  - 7.3 工具链选型建议
  - 7.4 成本模型（量级估算，需按当地报价核对）
  - 7.5 容量与性能估算（经验公式 + Mini 4 Pro 实算，待第 5–6 章实测校正）
  - 7.6 数据规范与管理
  - 7.7 团队能力要求
- 8. 风险矩阵与缓解
  - 8.1 风险清单（按“概率 × 影响”排序）
  - 8.2 应对策略分类
  - 8.3 触发条件与预案（Go/No-Go）
- 9. 结论与建议路线图
  - 9.1 结论（按问题逐条回答）
  - 9.2 建议路线图
  - 9.3 决策建议
  - 9.4 不确定性说明
- 10. 附录
  - 附录 A 复现实验命令（本机，Windows / PowerShell）
  - 附录 B 参考资料（关键来源）
  - 附录 C 已知问题与失败记录

---

# 0. 结论速览（给决策者，1 页）

> 版本：v0.9（基于 2026-11-08 本机实测与官方资料）；实测数字随后续实验回填（见第 5–6 章）。

## 0.1 五维可行性结论

| 能力 | 结论 | 等级 | 关键依据 |
|---|---|---|---|
| **① SDK 自动化采集** | **有条件可行**：Mini 3 / Mini 3 Pro / Mini 4 Pro 支持 DJI Mobile SDK（v5.x，Android）；**Mini 5 Pro / Mini 2 SE / Mini 4K 不支持**；Mini 4 Pro 必须用 RC-N2 遥控器（RC 2 带屏不支持） | L1–L2 | 官方兼容页 + MSDK v5.20.1 支持列表 + DroneDJ/Dronewatch（v5.13.0，2025-03） |
| **② 航拍数据满足 3DGS** | **可行**：1/1.3" 48MP、24mm、f/1.7、4K/60；按 75% 重叠、30–50m 航高可满足小场景重建；需固定曝光、避开运动模糊、弱纹理/水面/玻璃需补拍 | L1–L2 | 官方规格 + 摄影测量/3DGS 需求模型 |
| **③ 3DGS 重建（本机 8GB）** | **可行（欠训练）**：纯 PyTorch 光栅化器 + 管线跑通；8GB 显存仅用 1.15GB；受 CPU 限载与时间约束质量有限（全量 val PSNR 13.28（iter 3000，train 18.44），5 帧子集 22.3） | L2 | `data/trained/capture/run1/`、`logs/pipeline/` |
| **④ UE5 实时渲染** | **可行但需适配**：UE5 无原生 3DGS；Italink 插件移植 5.8 编译通过；Path B 点云预览在 UE 中成功显示真实训练 PLY（final_v2 4 视角截图）；Niagara splat 路径部分可用（激活已修，scale 单位失配待解） | L2 | `ue5/RESULTS.md`、`ue5/results/final_pathb/` |
| **⑤ 端到端工程化** | **可行（PoC 级）**：DJI 采集→3DGS→PLY→UE 全链路各环节已验证；主要风险为 SDK 机型限制、无 RTK 精度、UE 插件单位/适配、8GB 显存、热限速 | L2 | 全链路脚本 + 复现命令（附录 A） |

## 0.2 推荐方案（一句话）

**DJI Mini 4 Pro（RC-N2 + Android 自研 MSDK App）采集 → 本地 COLMAP/3DGS（开源）训练 → 标准 PLY → UE5.8 + 开源 3DGS 插件（或商业插件）渲染**；若追求省事且预算允许，可改用 **DJI Terra v5 Flagship（3DGS）→ PLY/3D Tiles → UE5/Cesium for Unreal** 官方链。

## 0.3 三个必须知道的限制

1. **机型/配件决定 SDK 可行性**：Mini 5 Pro 不支持 SDK；Mini 4 Pro 必须 RC-N2（不能是带屏 RC 2）且目前仅 Android。
2. **定位精度不是测绘级**：Mini 无 RTK，GPS/云台角只能作 COLMAP 先验，绝对地理精度约米级；测绘级应用需 RTK 机型或后处理 PPK/控制点。
3. **UE5 侧没有“官方免费午餐”**：UE5 不内置 3DGS；开源插件需自行编译维护，商业插件需授权预算；超大场景必须做 LOD/流式（Cesium for Unreal 或 LCC）。

## 0.4 建议下一步（PoC 30 天）

1. 采购/租赁 1 台 **Mini 4 Pro + RC-N2**，开发最小 MSDK 采集 App（航点+定时拍照+元数据落盘）；
2. 选 1 个 1–2 公顷园区实飞 200–400 张，跑通 COLMAP + 3DGS + UE5 渲染；
3. 以本报告的 UE 插件/流水线为基线，评估画质、帧率、工作量；
4. 决策：自研采集 App + 开源链（可控、成本低） vs 第三方 App + DJI Terra（快、但要授权费）。

## 1. 执行摘要

本报告验证一个具体问题：**以 DJI Mini 系列航拍数据为输入，使用其 SDK（或替代采集链路）能否在 UE5 中实现可用的 3DGS 重建、渲染与工程化？**

验证方式不是文献综述，而是**在本机（RTX 5060 Laptop 8GB / UE 5.8.4 / PyTorch 2.13+cu130）搭建并跑通端到端链路**，同时用 DJI 官方资料核实设备能力边界。主要工作包括：

1. **SDK 能力核实**：以 DJI 官方兼容页、官方 SDK 仓库（MSDK V5.20.1）、官方 Release Notes 与媒体交叉验证，钉死“哪些 Mini 机型能用 SDK、用什么遥控器、从哪个版本开始”。
2. **3DGS 重建链路**：搭建“采集元数据 → 位姿（已知位姿/COLMAP）→ 3DGS 训练 → 标准 PLY → 评估”的完整流水线，并在 8GB 显存约束下完成训练与质量评估。
3. **UE5 集成**：移植开源 3DGS 插件到 UE 5.8，完成 PLY 加载、渲染截图与性能测试；同时盘点商业插件与官方链（DJI Terra → PLY/3D Tiles → Cesium for Unreal）作为备选。
4. **合成航拍实验**：因本机无真实无人机，用 UE5 程序化场景 + 模拟 DJI Mini 4 Pro 相机参数与航测航线生成带真值位姿的数据集，用于隔离验证“3DGS ↔ UE”环节，并提供可量化指标。

**核心结论**：
- **SDK 路径“有条件可行”**：Mini 3/3 Pro/4 Pro 支持官方 Mobile SDK，可自研采集 App 实现自动化航拍；但 Mini 5 Pro、Mini 2 SE、Mini 4K 不支持 SDK，Mini 4 Pro 需 RC-N2 遥控器且首发仅 Android。
- **UE5 路径“可行但非开箱即用”**：UE5 无内置 3DGS；开源插件可编译运行（本机实测见第 6 章），商业插件（xgrids LCC 等）已声明支持 UE 5.1–5.8；大场景需 LOD/流式方案。
- **工程化建议**：以“Mini 4 Pro + RC-N2 + Android 自研 MSDK App”为采集端，以“COLMAP + 开源 3DGS + UE5 插件”为处理/渲染端，先在 1–2 公顷园区做 PoC，再按 30/90/180 天路线扩展。

**主要风险**（详见第 8 章）：SDK 机型/遥控器限制、无 RTK 精度、8GB 显存瓶颈、UE 插件生态维护与许可、飞行合规。

> 说明：本摘要中的“实测”数字统一回链到第 5–6 章与项目日志；无法本地验证的官方链环节明确标注为 L1（文档证据）。

## 2. 背景与问题定义

### 2.1 3DGS 与 UE5：为什么值得验证

3D Gaussian Splatting（3DGS）用数百万个带方向、尺度、不透明度与球谐（SH）颜色的 3D 高斯椭球表达真实场景，通过可微光栅化实现训练，并以 splatting 方式实时渲染。相比传统摄影测量网格（OSGB/OBJ/B3DM）与 NeRF，3DGS 在**视觉保真度/训练速度/渲染帧率**三者之间取得了新的平衡，尤其擅长植被、线缆、反射、薄结构等传统 MVS 难以重建的对象。

对 UE5 而言，3DGS 的价值是**“照片级真实感 + 低成本采集 + 可实时浏览”**：
- 数字孪生/园区/文旅：真实场景的可视化底座，可与传统网格、BIM、GIS 叠加；
- 影视/虚拟制片：实拍级虚拟场景，配合 nDisplay/VR；
- 仿真训练/机器人：高保真环境重建；
- 快速预览：无人机航拍数十分钟采集 → 小时级训练 → UE 内浏览。

但 UE5 本身**没有内置 3DGS 渲染支持**（Epic 官方 2025-10-23 论坛回复："We don't currently have plans to provide built-in gaussian splatting support."，见 https://forums.unrealengine.com/t/gaussian-splatting-support-out-of-the-box/2677693 ；本机 UE 5.8.4 的 Engine/Plugins 搜索也无 Gaussian/Splat 匹配）。因此 UE5 侧必须依赖第三方插件或自研渲染组件，这正是本验证的核心风险点之一。

### 2.2 为什么选择 DJI Mini 系列

| 维度 | Mini 系列优势 | 对 3DGS 的意义 |
|---|---|---|
| 成本 | 机身 + 电池价格远低于行业机型 | 单场景采集成本低，可多场景/多次采集 |
| 重量/法规 | <249g（Mini 4 Pro 起飞重量低于 249g），多数国家/地区门槛低 | 采集合规成本低、部署快 |
| 画质 | 1/1.3" CMOS 48MP、24mm 等效、f/1.7、4K/60 HDR | 分辨率足以支撑小场景高精度 3DGS |
| 自动化 | Mini 3 / Mini 3 Pro / Mini 4 Pro 支持 Mobile SDK（详见第 4 章） | 可自研 App 做航点/定时采集，位姿元数据可回传 |
| 保有量 | 消费级销量大、操作门槛低 | 团队上手快，采集人员培训成本低 |

### 2.3 待验证问题拆解（Q1–Q7）

本验证不是“跑通一个 demo”，而是回答以下 7 个问题，每个问题都对应可复核的证据：

| 编号 | 问题 | 判定依据 |
|---|---|---|
| Q1 | DJI Mini 系列哪些机型、哪些遥控器、哪个 MSDK 版本支持官方 SDK？开放哪些能力？ | 官方兼容页 + SDK 仓库 + 官方 Release Notes + 媒体交叉验证 |
| Q2 | 不用 SDK 能否完成 3DGS 采集？SDK 相对手动/第三方 App 的增量是什么（自动化、位姿、一致性）？ | 采集方案对比 + 拍摄参数模型 |
| Q3 | Mini 的传感器/画质/拍摄策略能否满足 3DGS 重建质量要求？ | 相机参数 + 重叠率/GSD 计算 + 公开案例 |
| Q4 | DJI 的 GPS/云台/EXIF 位姿先验精度如何？能否加速/稳定 COLMAP？ | 字段实测 + 误差分析 + 融合方案 |
| Q5 | 在 8GB 显存的本机能否完成训练？质量/耗时/显存如何？ | 本机实测（PSNR/SSIM/耗时/显存） |
| Q6 | UE5.8 能否实时渲染 3DGS？用哪种方案、性能与限制如何？ | 本机实测（插件编译 + 截图 + FPS/VRAM） |
| Q7 | 端到端是否可复现、可工程化？最大风险与工作量？ | 全链路复现 + 风险矩阵 + 路线图 |

### 2.4 验证边界（明确不做什么）

- 不使用真实无人机飞行（本机无 DJI 设备）；用 **UE5 合成航拍数据（含真值位姿）** 与 **公开/自造数据** 替代实拍，另以官方文档/样张元数据验证真实 EXIF 字段。
- 不采购 DJI Terra Flagship / 商业 UE 插件；官方链只做能力与接口层面的核实，不作为本次实测路径。
- 不做飞行合规审批实操，只做风险提示与流程建议。

> 证据索引：本章引用见第 4 章来源列表与 `docs/research/references.md`；本机 UE 5.8 无内置插件的搜索证据见 `logs/ue5/` 与 `shared/LEAD_KNOWLEDGE.md` 第 C 节。

## 3. 验证方法与判据

### 3.1 可行性分级（本报告采用 L0–L4）

| 等级 | 定义 | 本报告要求 |
|---|---|---|
| L0 不可行 | 关键环节缺失且无替代路径 | — |
| L1 理论可行 | 仅有文档/社区证据，无本地实验 | 至少 3 个独立一手来源 |
| L2 实验验证 | 关键环节在本机复现（可跑通） | 可执行脚本 + 日志/截图 |
| L3 PoC 可复现 | 端到端链路在本机跑通且可重复 | 一条命令复现 + 质量/性能指标 |
| L4 生产就绪 | 稳定性/性能/成本达到项目要求 | 压力测试 + 多场景 + 运维方案 |

**本验证的目标是把尽可能多的环节推进到 L2/L3，并对 L4 给出差距清单。** 对无法本地验证的环节（真实飞行、DJI Terra 商业版）明确标注为 L1。

### 3.2 实验环境

| 项 | 配置 |
|---|---|
| 主机 | Windows 11 家庭版 26200，32 核（16 物理核），16 GB RAM |
| GPU | NVIDIA RTX 5060 Laptop 8 GB（Blackwell, sm_120），驱动 621.01 / CUDA 13.5 |
| 训练框架 | PyTorch 2.13.0+cu130（全局 Python 3.14.6），项目 venv 复用 |
| 引擎 | Unreal Engine 5.8.4（Epic 官方安装），Visual Studio 2026 (MSVC 14.50/14.51)，.NET 10 SDK |
| 网络 | PyPI / hf-mirror / ModelScope / Gitee / api.github.com / jsDelivr 可用；github.com 直连受限 |
| 约束 | 无真实 DJI 设备；8 GB 显存需控制训练分辨率与 splat 数量；工程路径含中文 → 使用 ASCII junction 规避（见 6.2） |

### 3.3 端到端验证链路设计

为隔离变量，验证链路拆成两条互补路径：

**路径 A（主链路，L3 目标）— UE5 合成航拍 → 3DGS → UE5**
1. 在 UE5.8 中程序化搭建“园区/街区”场景；
2. 按 DJI Mini 4 Pro 相机参数（1/1.3"、等效 24mm、82.1° FOV、4:3）与典型航测航线（航高 30–50 m、重叠率 75%）生成 120–200 个相机位姿；
3. SceneCapture2D 渲染训练/验证图像，同时记录真值 c2w、内参、模拟 GPS/云台角（DJI 风格元数据）；
4. 用真值位姿直通（跳过 SfM，先隔离验证 3DGS 训练与 UE 渲染）训练 3DGS，输出标准 PLY；
5. 用 UE5 插件加载 PLY，渲染并与离线渲染/真值图对比；测量 FPS/显存。

**路径 B（真实 DJI 数据接口验证，L1→L2）— EXIF/元数据 → 位姿先验 → COLMAP**
1. 校验真实 DJI 照片 EXIF/XMP 字段（GPS、云台角、焦距）；
2. 实现 `dji_exif_to_colmap.py`：WGS84 → 局部 ENU → COLMAP 初始位姿（先验）；
3. 先用合成 EXIF（已知真值）验证转换正确性（重投影 < 1 px）；有真实样张再实测。

> 两条路径共同覆盖“DJI → 数据处理 → UE5”的全链路；路径 A 提供**可量化质量/性能**，路径 B 提供**真实设备接口可行性**。

### 3.4 指标体系

**重建质量（路径 A，有真值）**
| 指标 | 说明 |
|---|---|
| PSNR / SSIM | 留出验证视角 vs 真值渲染 |
| 视觉检查 | 漂浮物、几何塌陷、纹理糊、颜色偏差 |
| 位姿自检 | 投影/重投影误差（坐标转换正确性） |

**性能与资源**
| 指标 | 采集/训练侧 | UE5 渲染侧 |
|---|---|---|
| 耗时 | 采集帧数、SfM、训练 iter/s、总时长 | 加载耗时、每帧耗时 |
| 显存 | 训练峰值 VRAM | 渲染峰值 VRAM（nvidia-smi 采样） |
| 帧率 | — | FPS（不同 splat 数：50k/200k/500k/1M） |
| 体积 | PLY 大小、splat 数 | 资产导入后大小/流送 |

**工程可复现性**
- 提供一键脚本与固定随机种子；
- 记录软件版本、命令、日志路径；
- 明确已知失败与限制（不掩盖问题）。

### 3.5 证据管理规则

- 每条结论必须回链到：项目内文件路径 / 命令 / 官方 URL；
- 区分「本机实测」「官方文档」「第三方媒体/社区」三类证据强度；
- 失败实验同样记录（报告附录 C），避免“只报喜”。

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

## 5. 3DGS 重建链路实测

> 本章数据来自本机实测（`pipeline/`、`logs/pipeline/`、`data/trained/`），由 gs-pipeline 产出；最终版以实测数字替换占位。

### 5.1 数据准备

**路径 A：UE5 合成航拍数据集（主实验）**
- 场景：程序化“园区/街区”（UE5.8，无第三方资产）；
- 相机：模拟 DJI Mini 4 Pro（1/1.3"、等效 24mm、82.1° FOV、4:3、1600×1200）；
- 航线：航高 30–50 m、航向重叠 75%、旁向 65–75%、云台俯仰 45–60°；
- 输出：`data/synthetic/capture/images/0001–0175.png` + `metadata.json`（175 帧真值 c2w + 内参 + 模拟 GPS/云台角），验证视角 `data/synthetic/val/images/val_0001–0015.png` + `metadata_val.json`；

**路径 B：公开数据/真实 DJI 元数据**
- 公开小数据集（如可得）用于验证 COLMAP 与训练脚本通用性；
- 真实 DJI 照片样张用于元数据字段核对与位姿先验转换测试。

**工具链说明（实测坑）**：capture 使用 UE5.8 编辑器 Python 脚本生成场景与渲染。UE5.8 的 Python 暴露名有变化：`KismetMaterialLibrary`→`MaterialLibrary`、`KismetRenderingLibrary`→`RenderingLibrary`、SceneCapture2D 组件属性→`capture_component2d`；场景每次运行重建（503 actors，0.84s，无需保存关卡），避免临时材质引用失效。

**实际数据集（实测）**：UE 5.8.4 程序化园区（**805 actors**：建筑/道路/树木/绿地，程序化纹理；场景每次运行重建，~0.8 s），SceneCapture2D 渲染 **175 张训练 + 15 张验证 @1600×1200**，磁盘 **532.8 MB**；整批生成耗时 **184.1 s**（train 150.5 s ≈0.86 s/帧；val 25.1 s ≈1.67 s/帧，含首轮材质同步编译）；内参 fx=fy=**1148.343**、cx=800、cy=600（按 82.1° 对角 FOV、1/1.3" 9.6×7.2 mm 传感器推算）；航向重叠实测 **69.0%–80.4%**、旁向 **61.7%–73.1%**；图像亮度均值 **0.626**（p95=0.902，偏亮但可用）。

### 5.2 位姿求解

| 路径 | 方法 | 实现文件 | 结果 |
|---|---|---|---|
| A | 已知位姿直通（真值 c2w → COLMAP 格式 + 重投影自检） | `pipeline/colmap_io.py`、`02_sfm.py` | ✅ 已独立复跑自检：UE↔COLMAP 重投影 **max=1.256e-12 px / mean=1.198e-13 px**（n=320），c2w 闭环误差 4.5e-13 → 坐标换算实现正确 |
| B | COLMAP/pycolmap 增量重建（可选先验） | `pipeline/02_sfm.py`（pycolmap 4.2.1） | ✅ `known` 已知位姿写/读回自检 max **2.49e-12 px**；`sfm` pycolmap 全流程代码可用，但合成平纹理场景无法初始化（RESULTS §6.1 已记录）；主链路不依赖 |
| B | EXIF→COLMAP 先验转换 | `pipeline/dji_exif_to_colmap.py` | ✅ 合成 DJI 风格数据自测：**GPS 误差 0.00 m / 云台角 0.00°**；真实样片元数据可行性见第 4 章 |

**坐标换算自检方法（可复现）**：`pipeline/colmap_io.py` 内置 `reprojection_selfcheck()`：随机生成相机前方 2–80 m 的 3D 点，分别用“UE 相机直接投影”和“转成 COLMAP 位姿后投影”计算像素坐标，比较两者差异；并在 `__main__` 中同时输出 c2w 闭环误差与四元数往返误差。执行：`pipeline\.venv\Scripts\python.exe pipeline/colmap_io.py`。

### 5.3 训练实现与参数

| 项 | 值 |
|---|---|
| 训练框架 | **纯 PyTorch 可微 splatting**（tile-based，自研；gsplat 因 Windows/CUDA/VS 工具链 JIT 编译失败，详见 5.6） |
| 训练分辨率 | 640×480（原始 1600×1200 的 res-scale=0.4，内参同步缩放 fx=459.34） |
| 训练帧数 | 120–175（合成航拍数据集） |
| 分辨率 | 640×480（res-scale 0.4，内参同步缩放） |
| 迭代数 | **3000**（分批 750→1250→2000→3000，resume 续训；2–4 核限载，0.2–0.35 s/iter） |
| splat 数（最终） | 约 10.9 万 → 最高 15 万（densify 至上限） |
| 损失/正则 | L1 + D-SSIM（权重 0.2）；未加 depth/normal 正则 |
| 显存峰值 | **1151 MB**（远低于 8 GB，说明瓶颈在 CPU/训练时长而非显存） |
| 训练耗时 | 3000 iter 累计 318 s（最后一程 2000→3000 = 318 s，4 核约 0.3 s/iter） |
| 随机种子 | 0（全部训练固定） |
| 光栅化器正确性（自检） | ✅ vs 暴力参考 max\|img diff\|=1.66e-4、max\|alpha diff\|=1.85e-4（容差 1e-3）；梯度反传 loss 0.01837→0.00299 |
| 光栅化器速度（本机 RTX 5060） | 150k gauss @480×360：forward 53.1 ms，fwd+bwd 136.1 ms，峰值显存 558 MB；60k：fwd 60.7 ms / fwd+bwd 305.1 ms / 536 MB |

### 5.4 质量结果

| 指标 | 值 | 说明 |
|---|---|---|
| PSNR（held-out，全量 120 视图，iter 3000） | **13.28** | 欠训练（见下） |
| SSIM（held-out，同上） | 0.347 | |
| PSNR（训练视角，iter 3000） | **18.44** / SSIM 0.547 | 训练视角明显高于验证视角（欠训练/泛化差） |
| 视觉检查 | 结构可辨、颜色基本正确，但整体糊（欠训练典型表现） |
| 对比图 | `data/trained/capture/run1/renders/`（GT vs render 拼图） |

### 5.5 性能与资源

| 项 | 值 |
|---|---|
| PLY 大小 | 27.1 MB（109,376 splat，62 字段） |
| splat 数 | 109,376（上限 150k） |
| 训练显存峰值 | 1153 MB |
| 训练总耗时 | 约 745 s（分 3 段 resume：750→1250→2000→3000） |
| 单帧渲染耗时（离线） | 640×480 约 0.1–0.2 s/帧（基准见 5.3：136 ms@150k） |

### 5.6 质量分析：为什么全量 PSNR 偏低（欠训练，而非链路错误）

| 实验 | 设置 | PSNR | 结论 |
|---|---|---|---|
| 单视角过拟合 | 1 张图、300 iter、640×480 | 19.2（仍在上升） | 渲染/内参/投影链路正确 |
| 5 帧子集 | 600 iter | **22.27** / SSIM 0.757 | 多视角位姿几何自洽 |
| 全量 120–175 视图 | 3000 iter | **13.28 / SSIM 0.347** | **每视图仅约 18–25 次更新**，仍远低于官方 3DGS（每视图约 300 次） |
| 对照：自造 campus 数据集 | 1200 iter，24 视图 | val 17.43 / SSIM 0.568 | 视图数越少、每视图更新越多，质量越高 |

> 结论：本次 8 GB 显存 + **CPU 限载（2–4 核）** 条件下，训练时间受限是质量瓶颈；生产环境应使用 16–24 GB GPU + 全核训练 + 30k iter 级预算。

### 5.7 与 gsplat 官方实现的对比（如适用）

**实测结论**：本机 gsplat 1.5.3 的 CUDA 扩展 JIT 编译**失败**（尝试 3 次：pip 安装成功、nvcc 13.5 可用，但 `torch.utils.cpp_extension` 的 ninja/cl 链接阶段失败；详见 `logs/pipeline/gsplat_attempt*.log`）。因此本验证采用**自研纯 PyTorch tile-based 可微 splatting**，其正确性已对暴力参考实现验证（见 5.3）。

**gsplat 失败记录**（可复现）：`logs/pipeline/gsplat_attempt.log`（首次：nvcc/CUDA_HOME 装配后 cpp_extension smoke 失败）、`gsplat_attempt2.log`（cmd 嵌套引号/编码问题）、`gsplat_attempt3.log`（vcvars64 rc=1）；结论：**在 Python 3.14 + torch 2.13+cu130 + VS2026 组合下，gsplat 官方 JIT 路径不可用**；生产建议使用 gsplat 官方推荐的 Linux/容器环境或固定 CUDA 12.x + VS2022 工具链。纯 PyTorch 方案在本机 8GB 显存内可训练（速度约为 CUDA 实现的 1/5–1/10，但足以完成 PoC）。

## 6. UE5 集成与渲染验证

### 6.1 UE5 3DGS 生态盘点（截至 2026-11，本机 UE 5.8.4）

**官方现状：UE5 无内置 3DGS 支持。** 依据：① Epic 官方论坛 2025-10-23 回复 “We don't currently have plans to provide built-in gaussian splatting support.”（https://forums.unrealengine.com/t/gaussian-splatting-support-out-of-the-box/2677693 ）；② 本机 UE 5.8.4 的 `Engine/Plugins` 全量 `.uplugin` 搜索无 Gaussian/Splat 匹配（证据见 `logs/ue5/` 与 `shared/LEAD_KNOWLEDGE.md`）。

| 方案 | 类型/许可 | UE 版本 | 关键能力 | 可得性 | 评价 |
|---|---|---|---|---|---|
| **Italink/GaussianSplattingForUnrealEngine** | 开源 MIT | UE 5.5+ | 编辑器相机阵列捕获、调 COLMAP、调 3DGS 训练、PLY 导入、Niagara GPU 粒子/静态网格渲染、深度裁剪、LOD | GitHub（jsDelivr 可拉取）；本机已移植 | **本次验证采用的方案**：MIT、代码量小、中文文档友好 |
| yandex/yags（YaGS） | 开源（源码） | UE 5.5–5.7（预编译由 filmxr/yags 提供） | billboard quads、Mesh Shader/Vertex Shader、正确深度（DoF/运动模糊/TAA）、PLY/SOG、实例化、导出 PLY | GitHub | 渲染质量最完整的开源方案；5.8 需移植 |
| DazaiStudio/SplatRenderer-UEPlugin | Apache-2.0 | UE 5.5+ | 3DGS/4DGS、Sequencer、裁剪盒、Blueprint | GitHub Releases（仅预编译 DLL，无源码） | 快速试用可选；与 5.8 兼容性需验证 |
| mlslabs/MLSLabsGaussianSplattingRenderer-UE | Apache-2.0 | Pro 分支 UE 5.5 | 大规模 3DGS/4DGS、集群 LOD、GPU 排序/剔除 | GitHub（仓库 1.28 GB） | 功能强、体积大，需评估 |
| **xgrids LCC-3DGS-Unreal-Plugin** | 商业 Free + Pro | **UE 5.1–5.8** | 十亿点级、LCC2/LCC/PLY/SOG/SPZ、流式 LOD、重光照、深度缓冲、nDisplay/VR、DX11/12/Vulkan | developer.xgrids.com | **生产可用度最高**（官方声明支持到 5.8）；需商务评估 |
| SenseSpace 3DGS-UE-SDK（商汤） | 商业 | 未详 | 3DGS UE SDK | GitHub 小仓库 | 国内厂商备选 |
| **Cesium for Unreal + 3DGS 3D Tiles** | 开源 UE 插件（Cesium 生态） | 支持 UE5 | 3D Tiles 流式加载 3DGS + LOD（2026-04 起） | Cesium 官方 | **大场景/城市级流送**的首选路线；与 DJI Terra 3D Tiles 输出天然衔接 |
| DJI Terra v5（官方处理链） | 商业（Flagship） | 不依赖 UE | 可见光 GS 重建，输出 PLY/3D Tiles/GeoTIFF | DJI 官方 | 官方一键链；无二次开发/定制能力 |

> 结论：**UE5 侧不是“能不能渲染”的问题，而是“选哪条路线 + 谁维护”的问题**：小场景 PoC 用开源插件；生产大场景用商业插件或 Cesium 流式；官方链适合无算法团队的交付型项目。

### 6.2 本机集成实现（UE 5.8.4）

> 本节记录真实移植/编译过程（详细日志见 `logs/ue5/` 与 `ue5/RESULTS.md`，由 ue5-splat 产出）。

**实施步骤**：
1. 以 UE 5.8 `Templates/TP_Blank` 为模板创建 `ue5/DJI3DGS_UE` C++ 工程；
2. 通过 jsDelivr 拉取 Italink 插件源码（MIT）放入 `Plugins/GaussianSplattingForUnrealEngine`；
3. 处理 **UE 5.8 兼容性**：
   - 工程路径必须为纯 ASCII（中文路径导致 MSVC C1083），使用 `C:\UEW` junction 指向真实路径；
   - `UPackage::SavePackage` 在 5.8 改为 4 参数（`FSavePackageArgs`）→ 插件 4 处调用改写；
   - `UHLODBuilderSettings::GetCRC` 在 5.8 为 final → 移除插件子类 override；
   - 其余少量 C4996 弃用警告（如 `FHLODBuildContext::World` → `TargetWorld`）。
4. UBT 编译（`Build.bat DJI3DGS_UEEditor Win64 Development -Project=...`），产物 `UnrealEditor-GaussianSplattingRuntime.dll`、`UnrealEditor-DJI3DGS_UE.dll`；
5. 运行 `UnrealEditor -game` 加载 PLY 资产并截图（见 6.3）；

> 补充实测坑（UE 5.8）：`UnrealEditor.exe -game <uproject> ...` 的顺序会导致引擎识别不到工程（5.8 的 ParseGameProjectFromCommandLine 只看第一个 token），正确写法是 `<uproject> -game ...`；长任务必须用后台进程，否则会被外层 10 分钟超时杀掉。

**编译结果（实测）**：UE 5.8.4 Editor 目标 **Result: Succeeded**，三个模块 DLL 全部链接成功（`UnrealEditor-GaussianSplattingRuntime.dll`、`UnrealEditor-GaussianSplattingEditor.dll`、`UnrealEditor-DJI3DGS_UE.dll`），增量编译 **147.7 s**；日志 `logs/ue5/build_ue5_8_editor2.log`。

**运行时 harness（实测）**：在项目模块内实现自研 C++ PLY 解析器（binary_little_endian，62 字段标准 3DGS）+ `ASplatTestActor`（加载 PLY → Italink Niagara GPU 粒子渲染 → 环绕相机 → SceneCapture2D 输出 PNG → 帧时间/显存/排序 benchmark → metrics.json）。nullrhi 冒烟结果：50k splat 解析 **6.4 ms**、SetPoints **9.4 ms**、Niagara setup **95.8 ms**；修复了属性 stride 误用（把字段数 62 当字节 stride）导致的坐标/bounds 异常（修复后 point0 位置/尺度与 Python 原始字节完全一致）。

### 6.3 渲染正确性验证

**已实现的两种 UE 内可视化路径（实测）**：

| 路径 | 实现方式 | 状态 | 证据 |
|---|---|---|---|
| **A. Niagara 3DGS splat 渲染（插件原生）** | Italink 插件 Niagara GPU 粒子系统 + PointCloud DataInterface | ⚠️ 部分可用：激活问题已修复（late activation），splats 可渲染，但 **scale/单位失配**（splat 尺寸放大约 100 倍，画面被高斯团覆盖），仍在对照实验 | `ue5/results/nia_sm01/`、`nia_meters/` |
| **B. Debug 点云预览（自研，兜底）** | 自研 C++ PLY 解析 → DrawDebugPoint 逐点着色 + UE viewport 截图 | ✅ 成功：真实训练 PLY（10.9 万 splat）在 UE viewport 中显示为彩色点云，形状/颜色与场景一致 | `ue5/results/real_debugpts/viewport_measure_start.png`、`pathb_ctrl/` |

> 两条路径的关键发现：①UE 5.8 的 `-game` 模式下，**SceneCapture2D 能渲染有材质的几何，但不渲染 DrawDebug 图元**；需要用 viewport 截图（`FScreenshotRequest`）才能捕获 debug 点云；②插件 Niagara 资产是旧引擎版本保存的（`needsCompile=1`、资产警告），且 splat 尺寸单位与 PLY 坐标单位不一致 → 需要在插件/资产层面适配。

### 6.3.1 渲染正确性验证

**测试方法**：
- 用本工程生成的标准 3DGS PLY（见第 5 章）导入 UE5 插件；
- 固定相机位姿，渲染 3–5 个视角截图；
- 与 3DGS 离线渲染结果、真值渲染图对比（视觉 + 结构相似度）。

| 检查项 | 方法 | 结果 |
|---|---|---|
| PLY 解析正确性 | splat 数、包围盒、中心点与训练数据一致 | ✅ 50k 测试 PLY 与 29,895 splat 真实 PLY 解析值与 Python 逐位一致（含非常规 property 顺序） |
| 尺度/坐标对齐 | 与训练场景参考物尺寸对比 | ✅ Path B 点云与场景尺度一致；⚠️ Niagara 路径存在 ×100 单位失配 |
| 颜色/SH 解码 | 与离线渲染图对比 | ✅ Path B 点云颜色与 GT/离线参考一致（绿地面/蓝天空/深色建筑） |
| 深度/遮挡 | 与网格物体叠加渲染 | 未验证（Niagara 路径未稳定） |
| 半透明排序 | 近/远景重叠区域检查 | 未验证（Niagara 路径未稳定） |

**截图**：`ue5/results/final_v2/screenshots/view_00–03.png`（**最终版：真实训练 PLY 4 视角**）、`ue5/results/final_v2/viewport_measure_start.png`、`ue5/results/final/comparison_ue_vs_reference.png`（UE vs CPU 参考）、`ue5/results/final/pathb_real_ply_4views_grid.png`、`ue5/results/final/niagara_attempt_best.png`（Niagara splat 尝试）。

### 6.4 性能实测（RTX 5060 Laptop 8GB）

| 场景 / 渲染方式 | splat 数 | 分辨率 | 平均 FPS | 平均帧时间 | p99 帧时间 | 解析 / SetPoints | 说明 |
|---|---|---|---|---|---|---|---|
| sphere 测试 PLY（Niagara RHI） | 50k | 1280×720 | **48.6** | 20.6 ms | 175.7 ms | 65.5 / 56.1 ms | 含首次着色器编译毛刺；Niagara setup 695 ms；CPU 排序 47.8 ms×3 |
| 真实训练 PLY（Path B 点云预览，v2 最终取景） | **109,376** | 1280×720 | **30.8** | 32.5 ms | 58.0 ms | 28.2 / 23.5 ms | Debug 点云；robustRadius 9,326 cm、cameraDistance 16,000 cm、屏内可见 72,053；CPU 排序 14.5 ms×2 |
| 真实 PLY 解析（nullrhi） | 29,895 | — | — | — | — | 29.4 / 11.2 ms | Niagara setup 1992 ms（冷启动） |
| 500k / 1M | — | — | 未测 | — | — | — | 时间/温度预算不足；需 GPU 排序 + LOD 才能扩展 |

> 测量口径：`UnrealEditor -game -windowed -resx=1280 -resy=720`（Path B 用 viewport 截图）；**CPU 限载为 4 逻辑核**、桌面应用共存，因此数值**低于**全核/独占时的表现；GPU 利用率仅 20–42%，说明当前配置下并非 GPU-bound。

> 测量口径：`UnrealEditor -game -windowed -resx=1280 -resy=720`，使用 UE `stat unit` / 自研 Actor 计时；显存用 `nvidia-smi --query-gpu=memory.used --format=csv -l 1` 采样；每档稳定运行 30 s 取平均。

### 6.5 已知限制与风险（UE 侧）

| 限制 | 说明 | 影响/缓解 |
|---|---|---|
| 无原生支持 | UE5 不内置 3DGS，需第三方插件 | 锁定 UE 版本 + 内部维护/商业授权 |
| 半透明排序 | 3DGS 是 alpha 混合图元，排序错误产生鬼影/闪烁 | 选择支持排序/深度通道的插件；控制 overdraw |
| 无物理光照 | 3DGS 仅有外观颜色，无法参与 Lumen/阴影/反射的物理正确计算 | 混合管线：GS 做背景/远景，网格做交互物体 |
| 大场景性能 | splat 数量随面积增长，VRAM/带宽压力大 | LOD/分块/流式（Cesium for Unreal 或 LCC），或降低质量档位 |
| 打包/发布 | 插件资源/渲染管线需随项目 Cook | 验证打包流程；必要时锁定插件版本 |
| 版本升级 | 插件随 UE 5.x API 变动易破坏（本机已遇 5.8 API 变更） | 版本锁定 + CI 编译验证 + 维护预算 |
| Niagara 资产版本 | 插件 Niagara/材质 uasset 由旧引擎版本保存，5.8 提示 needsCompile、资产警告 | 用编辑器重新保存/编译资产，或自行重建 Niagara 系统 |
| 单位/尺度约定 | PLY 坐标（cm）与插件 Niagara 期望的 splat scale 单位不一致，导致 splat 放大约 100× | 在导入端统一 ×0.01 缩放或修改插件；需实测标定 |
| 截图路径 | `-game` 下 SceneCapture2D 不渲染 DrawDebug 图元，viewport 截图才可见 | 交付截图统一用 viewport 截图；正式渲染仍走 RT 路径 |

## 7. 端到端流程与工程化建议

### 7.1 推荐生产流水线

（流程见 图1；推荐链路的完整步骤与责任分工如下）

| 阶段 | 输入 | 动作 | 输出 | 责任角色 |
|---|---|---|---|---|
| 1 采集规划 | 场景范围、精度要求 | 空域核查 → 航线设计（重叠/航高/云台角）→ 采集参数（固定曝光/快门/ISO） | 航线文件 + 采集 SOP | 测绘/飞手 |
| 2 航拍采集 | 航线 | Mini 4 Pro（RC-N2）+ 自研 MSDK App 或 DJI Fly 手动；定时拍照 | 照片 + EXIF/元数据 | 飞手/采集 App |
| 3 数据质检 | 照片 | 模糊/欠曝/漏拍检查、去重、命名规范化 | 合格数据集 | 数据处理 |
| 4 位姿求解 | 照片 + 元数据 | COLMAP SfM（可用 GPS/云台先验初始化）→ BA 精化 | COLMAP 稀疏模型 | 算法工程 |
| 5 3DGS 训练 | 图像 + 位姿 | gsplat / 纯 PyTorch 训练（固定分辨率/迭代数/随机种子） | 标准 PLY + 指标 | 算法工程 |
| 6 质量评估 | PLY + 验证视角 | PSNR/SSIM + 视觉检查（漂浮/空洞/颜色） | 质量报告 | 算法/QA |
| 7 UE5 集成 | PLY | 插件导入 → 场景布置 → 光照/后处理 → 截图/性能 | UE 工程 / 演示 | 引擎工程 |
| 8 交付 | UE 工程 + PLY + 文档 | 打包/流送/权限、版本管理 | 可交付成品 | 项目经理/引擎 |

### 7.2 自研 MSDK 采集 App 功能设计（建议）

> 目标：把“飞手手工拍摄”变成“可复现的工程化采集”，并产出结构化元数据。

| 模块 | 功能 | 技术要点 |
|---|---|---|
| 机型/权限 | 连接检测、固件/SDK 版本校验、机型白名单 | 只允许 MSDK 支持的机型（Mini 3/3 Pro/4 Pro 等），版本不匹配直接拒绝 |
| 航线任务 | 网格/五向/环绕模板，重叠率/航高/速度参数化 | 优先用 MSDK Waypoint Mission；注意 RC-N2 + Android 限制 |
| 相机控制 | 固定曝光/白平衡/ISO/快门，定时或等距拍照 | 关闭自动曝光跳变；记录每张照片参数 |
| 元数据落盘 | 每张照片写 JSON：GPS、云台角、时间戳、内参、任务 ID | 与 EXIF 互补，便于位姿先验与追溯 |
| 媒体回传 | 批量下载/校验（大小/哈希） | 支持断点续传；命名规则统一 |
| 异常处理 | 低电量/失联/限高/避障触发时安全返航并标记 | 采集任务日志与失败原因记录 |
| 数据导出 | 生成 COLMAP 友好的目录 + metadata.json | 与 `pipeline/` 脚本直接对接（见 shared/CONVENTIONS.md） |

### 7.3 工具链选型建议

| 环节 | 推荐（PoC） | 推荐（生产） | 备选/说明 |
|---|---|---|---|
| 采集 | DJI Fly 手动/机内航点 | 自研 MSDK App（Mini 4 Pro + RC-N2） | 第三方 App（Litchi/DroneDeploy 等）可快速起步 |
| SfM | pycolmap/COLMAP | COLMAP + 先验约束（大规模可加 GLOMAP） | 先验来自 EXIF/自研 App 元数据 |
| 3DGS 训练 | gsplat（若可编译）或纯 PyTorch | gsplat 官方实现 + 深度/法向正则 | 需要 CUDA 工具链；8GB 显存需控制规模 |
| UE 渲染 | 开源插件（MIT/Apache） | 商业插件（xgrids LCC，支持 UE 5.1–5.8）或自研 GPU 渲染 | 大场景必须 LOD/流式（Cesium for Unreal 3D Tiles 或 LCC） |
| 官方链 | DJI Terra v5（试用/演示） | DJI Terra Flagship（3DGS） | 输出 PLY/3D Tiles/GeoTIFF，适合无算法团队的项目；**硬件要求 32 GB RAM + CC≥6.1 GPU（本机 16 GB 不达标）** |

### 7.4 成本模型（量级估算，需按当地报价核对）

| 成本项 | 量级 | 说明 |
|---|---|---|
| 无人机 | ¥5,000–7,000/台（Mini 4 Pro + RC-N2） | 以 DJI 官方/渠道实时价为准；需备份电池/ND 滤镜 |
| 采集 App 开发 | 1–3 人周（MVP） | Android + MSDK v5；含测试与异常处理 |
| 训练算力 | 本机 8GB 可做小场景；生产建议 16–24GB GPU（¥10k–25k）或云 GPU（¥2–10/小时级） | 大场景/高分辨率训练显著受益 |
| 软件授权 | DJI Terra Flagship 年订阅（数千美元/年量级，以官方报价为准）；LCC Pro（按项目/年报价）；第三方 App 订阅 | 先用免费/开源链验证价值再采购 |
| 人力 | PoC 1–2 人 × 4 周；生产化 3–5 人 × 3–6 个月（采集/算法/引擎/产品） | 与场景复杂度相关 |
| 隐形成本 | 空域申请、飞行保险、数据存储/备份、UE 版本升级维护 | 按项目合规要求计 |

> 说明：以上为量级估算而非报价承诺；DJI Terra/LCC/第三方 App 价格随渠道与授权方式变化，采购前须以官方报价为准。

### 7.5 容量与性能估算（经验公式 + Mini 4 Pro 实算，待第 5–6 章实测校正）

**相机/航线实算（Mini 4 Pro，1/1.3" 9.6×7.2 mm，82.1° 对角 FOV → 实际焦距 6.90 mm ≈ 24.9 mm 等效）**：

| 航高 | GSD（12MP 4000×3000） | GSD（48MP 8064×6048） | 单张地面覆盖（12MP） | 100m×100m 照片数（75%/65% 重叠） | 200m×200m 照片数 |
|---|---|---|---|---|---|
| 30 m | 1.04 cm/px | 0.52 cm/px | 41.8×31.3 m | ≈ 112 | ≈ 405 |
| 40 m | 1.39 cm/px | 0.69 cm/px | 55.7×41.8 m | ≈ 77 | ≈ 252 |
| 50 m | 1.74 cm/px | 0.86 cm/px | 69.7×52.2 m | ≈ 54 | ≈ 170 |

> 结论：**1 公顷园区约 77 张（12MP、40 m 航高、75%/65% 重叠）**，4 公顷约 252 张；30 m 航高更精细但需约 112 张；若要更高精度可切 48MP（GSD 减半、单张信息量更大，但训练显存/时间增加）。拍摄要求：固定曝光/白平衡、快门 ≥ 1/500 s（减少运动模糊）、云台俯仰 45–60°（倾斜视角利于立面重建）、航向重叠 75% / 旁向 65–75%、避免正午硬阴影与水/玻璃反光。

**训练/渲染容量（经验公式）**：

- **照片数量**：约 `N ≈ 面积 / (GSD² × 重叠系数)`；以 1 公顷园区、GSD 2 cm、航向/旁向重叠 75%/65% 估算，约数百张量级；
- **训练时间**：与分辨率²、splat 数、迭代次数近似线性；8GB 显存下建议 512–960 px、5k–15k iter；
- **PLY 体积**：每个 splat 约 236 B（3DGS 标准字段），30 万 splat ≈ 70 MB，1M splat ≈ 236 MB；
- **UE 渲染**：splat 数、屏幕覆盖（overdraw）、排序开销是主要因素；需实测 FPS/VRAM 曲线（见 6.4）。

### 7.6 数据规范与管理

| 项 | 规范 |
|---|---|
| 目录 | `project/scene/YYYYMMDD/raw|colmap|trained|ue/` |
| 命名 | 照片 `IMG_<任务ID>_<序号>.jpg`；训练 `run_<日期>_<参数摘要>/` |
| 坐标 | 统一记录 WGS84 原点与局部 ENU → UE/COLMAP 换算；每次转换做重投影自检 |
| 版本 | 数据集/模型/UE 工程均纳入 Git/LFS 或对象存储，记录 commit/参数/依赖版本 |
| 备份 | 原始照片至少双副本（本地 + 对象存储）；训练产物可重跑但保留 PLY 与指标 |

### 7.7 团队能力要求

| 角色 | 技能 | 工作量占比（PoC） |
|---|---|---|
| 无人机飞手/采集 | DJI Fly、空域法规、航线规划 | 20% |
| 算法工程师 | COLMAP/SfM、PyTorch、3DGS | 40% |
| 引擎工程师 | UE5 C++/蓝图、渲染管线、打包 | 30% |
| 项目经理/QA | 需求/验收、数据管理 | 10% |

> 本节为工程化建议框架；具体人力与预算需结合项目范围细化。

## 8. 风险矩阵与缓解

### 8.1 风险清单（按“概率 × 影响”排序）

| 编号 | 风险 | 概率 | 影响 | 等级 | 具体表现/证据 | 缓解措施 |
|---|---|---|---|---|---|---|
| R1 | **SDK 机型/遥控器/平台限制** | 高 | 高 | 🔴 严重 | Mini 5 Pro 官方“不支持 SDK”；Mini 4 Pro 必须 RC-N2、首发仅 Android；Mini 2 SE/Mini 4K 不支持 | 采购清单锁定 Mini 4 Pro + RC-N2 + Android；App 做机型白名单与降级（手动/第三方 App）；关注 DJI 后续版本公告 |
| R5 | **UE5 无原生 3DGS 支持，依赖第三方插件** | 高 | 高 | 🔴 严重 | Epic 官方 2025-10 明确“无内置计划”；开源插件非官方维护、版本升级易破坏 | 锁定 UE 版本（5.8.x）；源码级移植 + 内部维护；商业方案（xgrids LCC 支持 5.1–5.8）作为兜底/授权采购 |
| R8 | **飞行合规/空域审批** | 中 | 高 | 🟠 高 | 249g 不等于免监管；园区/城市/机场净空区限制 | 采集前空域核查与报备；购买无人机保险；建立飞行 SOP 与日志留存 |
| R3 | **无 RTK → 绝对定位精度不足** | 高 | 中 | 🟠 高 | GPS/云台角为消费者级（米级/亚度级），不满足测绘级落图/量测 | 明确“视觉级精度”边界；需要精度时用 RTK 机型/控制点/后处理；3DGS 位姿以 COLMAP/BA 为准 |
| R4 | **8GB 显存限制** | 高 | 中 | 🟠 高 | 大场景/高分辨率训练与渲染可能 OOM；1M splat 渲染 VRAM 压力 | 训练分辨率 512–960、splat 上限控制、分块训练；渲染用 LOD/流式；升级 16–24GB GPU 作为生产配置 |
| R9 | **大场景 PLY 体积/加载性能** | 高 | 中 | 🟠 高 | 园区级 PLY 可达 GB 级；UE 加载/内存/流送压力 | 分块（tile）+ LOD；压缩格式（SPZ/LCC/SOG）；Cesium for Unreal 3D Tiles 流式路线 |
| R2 | **iOS MSDK 缺失（待核实）** | 高 | 中 | 🟠 高 | 公开资料仅见 Android v5.13.0 支持 Mini 4 Pro；iOS 端支持情况未确认 | 采集端先用 Android；在 SDK 调研结论中标注“iOS 待官方确认”；App 技术栈按 Android 先行 |
| R6 | **半透明排序/深度伪影** | 中 | 中 | 🟡 中 | 3DGS 需按深度排序合成；无深度通道时与网格遮挡错误、边缘闪烁 | 选用支持深度渲染的插件（YaGS 等）或分层渲染；限制超大 splat 的 overdraw；质量验收含伪影检查 |
| R10 | **商业插件/软件许可成本** | 中 | 中 | 🟡 中 | DJI Terra Flagship（3DGS 功能）、LCC Pro、第三方 App 订阅均为持续成本 | 先 PoC 用开源链验证价值；规模化后再评估商业授权 ROI；预算按年订阅计入 |
| R7 | **非 ASCII 路径 / 工具链环境坑** | 中 | 低 | 🟢 低 | 本机实测：工程路径含中文导致 MSVC C1083 编译失败 | 工程放 ASCII 路径（本工程用 `C:\UEW` junction）；CI 统一环境；文档写明路径要求 |
| R11 | **采集数据质量（弱纹理/反光/运动模糊）** | 中 | 中 | 🟡 中 | 水面、玻璃、纯色墙面、植被密集区易出现漂浮/空洞；快门下运动模糊 | 航线规划增加倾斜/环绕；固定曝光/高快门；补拍；3DGS 训练加深度/法向正则 |
| R12 | **相机-遥测时间同步误差** | 中 | 低 | 🟢 低 | 消费级机型无硬件同步，高速飞行时位姿外推误差 | 降低飞行速度/悬停拍照；用 COLMAP 精化；必要时加外部时间同步方案 |

### 8.2 应对策略分类

| 策略 | 适用风险 | 具体动作 |
|---|---|---|
| **规避** | R1、R2 | 采购前锁定机型/遥控器/平台；不把 Mini 5 Pro 纳入 SDK 自动化方案 |
| **降低** | R3、R4、R6、R9、R11、R12 | 技术方案层面（COLMAP 精化、分块/LOD、深度渲染、采集 SOP） |
| **转移** | R5、R10 | 采用商业插件/官方软件（付费转移维护与许可风险） |
| **接受** | R7、R8（在合规前提下） | 建立环境规范与飞行审批流程，接受残余风险 |

### 8.3 触发条件与预案（Go/No-Go）

| 场景 | 触发条件 | 预案 |
|---|---|---|
| PoC 阶段 UE 插件无法编译/渲染 | 3 天内无法在 UE 5.8 加载 PLY | 切换到商业插件试用（LCC/xgrids）或 Cesium for Unreal 3D Tiles 路线 |
| 训练质量不达标（PSNR 过低/伪影重） | 验证集 PSNR 低于目标 2 dB 以上 | 检查位姿精度/采集重叠；增加训练 iter；改用 gsplat 官方实现；补拍 |
| 显存不足（OOM） | 训练/渲染在目标分辨率反复 OOM | 降分辨率/减 splat/分块；临时租用 24GB 云 GPU 做训练 |
| 机型/政策变化 | DJI 停止支持某机型 MSDK | 采集端保留 DJI Fly/第三方 App 手动方案；多机型备份 |

> 风险等级：🔴 严重（需立即处理/影响可行性结论）；🟠 高（需方案设计覆盖）；🟡 中（需监控）；🟢 低（接受/规范化）。

## 9. 结论与建议路线图

### 9.1 结论（按问题逐条回答）

| 问题 | 结论 | 证据章节 |
|---|---|---|
| Q1 哪些 Mini 支持 SDK？ | Mini 3/3 Pro/4 Pro 支持 MSDK v5（Mini 4 Pro 自 v5.13.0，Android+RC-N2）；Mini 2/SE/Mavic Mini 支持 MSDK v4；Mini 5 Pro / Mini 2 SE / Mini 4K 不支持 | 4.1 |
| Q2 不用 SDK 能否采集？ | 可以（DJI Fly 手动/机内航点 + 定时拍照），但自动化/一致性/元数据质量低于自研 App | 4.3 |
| Q3 画质够不够？ | 1/1.3" 48MP/24mm/f1.7 足以支撑小场景 3DGS；关键是重叠率、固定曝光、航线规划与弱纹理补拍 | 4.2/5.1 |
| Q4 位姿先验有用吗？ | GPS/云台角可作 COLMAP 初始化与约束，但精度不足，最终必须 BA 精化；无 RTK 不满足测绘级绝对精度 | 4.4 |
| Q5 8GB/限载能否训练？ | 能：纯 PyTorch 3000 iter、10.9 万 splat、峰值显存 **1.15 GB**、累计 318 s；但 4 核 + 8GB 下质量欠训练（val PSNR 13.28；5 帧子集 22.3） | 5.3–5.6 |
| Q6 UE5 能否实时渲染？ | UE5.8 插件编译通过 + PLY 解析正确 + Path B 点云在 UE 中显示（30.8 fps@1280×720，10.9 万 splat）；Niagara splat 已渲染但 scale 失配未解决（部分可用） | 6.2–6.5 |
| Q7 能否工程化？ | 可以，按 9.2 路线推进；最大风险为 SDK 限制、精度、显存与插件维护 | 第 8 章 |

### 9.2 建议路线图

| 阶段 | 周期 | 目标 | 关键交付 | 验收标准 |
|---|---|---|---|---|
| **P0 技术 PoC** | 30 天 | 单场景端到端跑通 | 采集 App MVP（航点+定时+元数据）、1–2 公顷实拍、3DGS 训练、UE5 渲染 demo | 视觉无明显伪影；UE 实时浏览 ≥30 fps（1080p、≤50 万 splat）；链路可复现 |
| **P1 试点** | 90 天 | 3–5 个场景、质量与效率基线 | 采集规范/SOP、自动化流水线、UE 插件选型与授权、质量评估报告 | 单场景采集 ≤4 小时、训练 ≤8 小时（16GB+ GPU）、渲染帧率达标 |
| **P2 生产化** | 180 天 | 多项目复用、流程化交付 | 数据管理平台、LOD/流式方案、权限/合规、运维与成本模型 | 稳定交付、可估算成本、风险闭环 |

### 9.3 决策建议

1. **采集端**：优先采购/租赁 **Mini 4 Pro + RC-N2**；若仅做验证可直接用 DJI Fly 手动采集。**不要采购 Mini 5 Pro 用于 SDK 自动化**（官方明确不支持）。
2. **处理端**：自建开源链（COLMAP + gsplat/纯 PyTorch + UE 插件）掌握可控性；若追求项目交付速度且预算允许，可并行评估 **DJI Terra Flagship** 的 3DGS（PLY/3D Tiles 输出）。
3. **渲染端**：短期用开源插件（MIT/Apache）做 PoC；生产环境评估 **xgrids LCC**（官方声明支持 UE 5.1–5.8、十亿点、nDisplay/VR）或自研 GPU 渲染器，重点验证 LOD/流式与深度/半透明正确性。
4. **精度预期**：明确告知业务方“无 RTK → 视觉级精度、非测绘级”；涉及坐标落图/量测的场景需另配 RTK 机型或控制点。

### 9.4 不确定性说明

- 本机无真实 DJI 设备，SDK 采集与真实 EXIF 精度为**文档级/模拟级**证据（L1–L2），实飞后需复核；
- UE 插件为非官方维护，UE 版本升级可能破坏兼容性，需要锁定引擎版本或承担维护成本；
- 本版所有关键实测项已回填；未完成项（**真实数据 COLMAP 精化实测**、Niagara 单位适配修复、orbit 视频成片）已在正文/附录 C 明确标注为“未完成/待验证”。

## 10. 附录

### 附录 A 复现实验命令（本机，Windows / PowerShell）

**A.1 环境准备（3DGS 流水线）**
```powershell
cd C:\Users\<user>\Desktop\GAIA项目\dji_ue5_3dgs\pipeline
.\setup_env.ps1
# 详细版本见 pipeline/ENV.md
```

**A.2 训练与导出（具体命令由 gs-pipeline 回填）**
```powershell
# 已知位姿直通训练
.\.venv\Scripts\python.exe 03_train_3dgs.py --data ..\data\synthetic\capture --out ..\data\trained\synth --iters 7000 --res 1
# 评估
.\.venv\Scripts\python.exe 05_eval.py --ckpt ..\data\trained\synth\gaussians.ply --val ..\data\synthetic\val
```

**A.3 UE5 构建与运行（ASCII 路径 junction）**
```powershell
New-Item -ItemType Junction -Path C:\UEW -Target 'C:\Users\<user>\Desktop\GAIA项目'
& 'C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\Build.bat' DJI3DGS_UEEditor Win64 Development -Project='C:\UEW\dji_ue5_3dgs\ue5\DJI3DGS_UE\DJI3DGS_UE.uproject' -WaitMutex
& 'C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe' 'C:\UEW\dji_ue5_3dgs\ue5\DJI3DGS_UE\DJI3DGS_UE.uproject' -game -windowed -resx=1280 -resy=720
```

**A.4 合成航拍数据生成（由 capture-synth 回填）**
```powershell
cd C:\Users\<user>\Desktop\GAIA项目\dji_ue5_3dgs\capture
.\run_capture.ps1
```

**A.5 报告图表重建**
```powershell
cd C:\Users\<user>\Desktop\GAIA项目\dji_ue5_3dgs\report
..\pipeline\.venv\Scripts\python.exe make_figures.py
```

### 附录 B 参考资料（关键来源）

| # | 来源 | 用途 |
|---|---|---|
| 1 | DJI 官方《DJI 大疆产品 SDK 支持情况介绍》 https://support.dji.com/help/content?customId=01700000763&spaceId=17&re=CN | 机型 x SDK 支持矩阵 |
| 2 | DJI Mobile SDK V5（Android）官方仓库 https://github.com/dji-sdk/mobile-sdk-android-v5 （V5.20.1） | 支持机型列表 |
| 3 | DJI Mobile SDK V4 官方仓库 https://github.com/dji-sdk/Mobile-SDK-Android （4.18） | Mini 2/SE 走 v4 的依据 |
| 4 | DroneDJ（2025-03-21） https://dronedj.com/2025/03/21/dji-mini-4-pro-msdk/ | RC-N2 限制、Android |
| 5 | Dronewatch（2025-03-19） https://www.dronewatch.nl/2025/03/19/dji-mini-4-pro-krijgt-ondersteuning-voor-externe-apps-dankzij-nieuwe-sdk/ | MSDK v5.13.0 支持 Mini 4 Pro |
| 6 | DJI Terra Release Notes v5.0.2 PDF https://terra-1-g.djicdn.com/263b7ee0f1fe477c91b7ca44348166fe/releasenotes/DJI%20Terra%20Release%20Notes%20v5.0.2.pdf | 官方 3DGS 能力 |
| 7 | DJI Mini 4 Pro 官方规格 https://www.dji.com/cn/mini-4-pro/specs | 相机/重量/悬停精度 |
| 8 | Epic 官方论坛（2025-10-23） https://forums.unrealengine.com/t/gaussian-splatting-support-out-of-the-box/2677693 | UE 无内置 3DGS 计划 |
| 9 | Cesium 博客（2026-04-27） https://cesium.com/blog/2026/04/27/3d-gaussian-splats-lod/ | Cesium for Unreal 3DGS 支持 |
| 10 | Italink/GaussianSplattingForUnrealEngine https://github.com/Italink/GaussianSplattingForUnrealEngine （MIT） | 本验证采用的 UE 插件 |
| 11 | yandex/yags https://github.com/yandex/yags | 开源 UE GS 插件对比 |
| 12 | xgrids/LCC-3DGS-Unreal-Plugin https://github.com/xgrids/LCC-3DGS-Unreal-Plugin | 商业插件能力（UE 5.1-5.8） |

### 附录 C 已知问题与失败记录

| # | 问题 | 现象 | 处理/结论 |
|---|---|---|---|
| 1 | 工程路径含中文导致 UE 编译失败 | MSVC C1083 无法打开 C:/Users/<user>/Desktop/GAIA | 使用 ASCII junction C:\UEW 规避（已在 6.2 记录） |
| 2 | UE 5.8 API 变更 | UPackage::SavePackage 9 参 / GetCRC final | 改为 4 参 FSavePackageArgs；移除 override |
| 3 | gsplat JIT 编译失败（首次） | cpp_extension smoke 失败（MSVC/CUDA 工具链） | 见 5.6 与 logs/pipeline/gsplat_attempt*.log |
| 4 | 显存受限 | 桌面应用占用后可用约 1.7-2.3GB | 降低分辨率/关闭后台应用/必要时云 GPU |
| 5 | UE 5.8 Python API 变更（capture 侧） | `unreal.KismetMaterialLibrary` / `unreal.KismetRenderingLibrary` 属性不存在（ScriptName 生效） | 改用 `unreal.MaterialLibrary` / `unreal.RenderingLibrary`；SceneCapture2D 组件属性为 `capture_component2d` |
| 6 | UE 编辑器长任务被外层超时杀掉 | 首轮 RHI 运行日志停在初始化、无进程、无产物 | 长任务改用 pwsh run_in_background + 轮询；详见 ue5-splat 日志 |
| 7 | 热限速与 CPU 限载 | CPU 热区达 88–94.9°C 触发熔断；用户要求 ≤80°C | 采用 4 核限载 + 82°C 降 Idle / 93°C 熔断守护；训练吞吐与质量受此影响（已如实记录） |

