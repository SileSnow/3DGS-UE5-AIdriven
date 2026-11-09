# LLM Tool-Call 调度无人机完成任务 —— 方案设计与 Phase-1 验证报告

> 项目：GAIA / `dji_ue5_3dgs` ｜ 日期：2026-11-08 ｜ 版本：v1.0
> 环境：Windows 11 / RTX 5060 Laptop 8GB / Python 3.14.6 / Unreal Engine 5.8.4 / Ollama `qwen3.5:4b`；Phase-1 全程**仿真 + UE5 虚拟相机**，无真机。
> 本报告回答两个问题：**① DJI Mini 系列到底能用什么 SDK、怎么用（代码级）；② 如何让 LLM 通过 tool call 安全、可审计地调度无人机完成任务**，并给出可复现的 Phase-1 端到端验证证据。

---

## 摘要（结论先行）

1. **SDK 路线是分档的**：Mini 3 / Mini 3 Pro / Mini 4 Pro 走 **MSDK v5（仅 Android）**，分别自 v5.3.0（2023-04-07）/ v5.13.0（2025-03-17）起支持；Mini 2 / SE / Mavic Mini 走 **MSDK v4.16**（Android+iOS，v4 与 v5 代码不兼容）；Mini 5 Pro、Mini 2 SE、Mini 4K **无任何官方飞行 SDK**。Mini 4 Pro 必须配 **RC-N2**（v5.17.0 起也支持 RC-N3），**带屏 DJI RC 2 不能运行第三方 App**。
2. **MSDK v5 的使用范式是 "Key 中心"**：`KeyTools` 创建 Key → `KeyManager` 读写 / 监听 / 执行 Action；初始化链路为 `Helper.install()` → `SDKManager.init()` → `registerApp()` → `onProductConnect`；航线走 `WaypointMissionManager`（KMZ/WPML 由 `WPMZManager` 编辑），相机/云台/媒体/遥测分别走 `CameraKey` / `GimbalKey` / `MediaDataCenter` / Key 监听（≤10 Hz）。
3. **LLM 永远不直连 DJI SDK**。本方案采用三段式：`LLM Orchestrator`（工具循环/规划/审计）→ `Drone Agent`（确定性安全层 + 执行 + 遥测）→ `DJI MSDK v5 / 仿真`。LLM 只产出"意图 + 参数"，所有飞行指令必须通过确定性 `SafetyValidator`（限高/限速/围栏/禁飞区/电量/GPS/链路/二次确认/白名单/Schema）后才下发。
4. **安全是确定性代码，不是提示词**：提示词只做"引导"，真实拦截在 Agent 侧；脚本化对抗测试与真实 LLM 触发对抗两条路径都验证同一套错误码（`E_ALT_LIMIT` / `E_GEOFENCE` / `E_NOFLY` / `E_BATTERY_TAKEOFF` / `E_CONFIRM_REQUIRED` 等），并提供不可关闭的 JSONL 审计。
5. **工具集设计为 15 个 OpenAI function 风格工具**，分三级风险；`plan_capture_mission`（规划，不飞）与执行（`goto_waypoints`）强制两步，飞行工具必须 `confirm=true`；规划器用确定性几何（网格/环绕/定点）生成 Mission JSON，LLM 只需传 `plan_id`，避免小模型传输大数组。
6. **Phase-1 已端到端跑通（13/13 场景 PASS）**：本机 Ollama `qwen3.5:4b`（native tool_calls）驱动完整工具循环 → 仿真 Drone Agent 执行：P1/P2/P3 三个正向场景**真实 LLM** 自主完成（分别拍摄 20 / 12 / 5 张照片，0 拒绝），A1–A5 由**真实 LLM 触发**对应安全拒绝（E_ALT_LIMIT / E_GEOFENCE / E_NOFLY / E_BATTERY_TAKEOFF / E_CONFIRM_REQUIRED），A6–A10 脚本化直调验证（force_rth / E_GPS / E_RC_LINK / E_PARAM_RANGE+E_UNKNOWN_TOOL / E_REAL_NOT_AVAILABLE）。Lead 黑盒独立验收 **27/27 PASS**、全仓单测 **118 tests OK**。UE5.8 虚拟相机消费 Mission JSON 渲染 1600×1200 航拍图并生成可直接喂 3DGS 流水线的 `metadata.json`（16 帧预置样例 + P1 真实 LLM 任务 20 帧，均校验 ok=true、可被 pipeline 加载）。具体数字与证据见第 6 章。
7. **真机路线清晰但未执行**：MSDK v5 Android 桥的架构、Kotlin 代码骨架、工具→API 映射与真机测试协议已完成；受硬件（Mini 4 Pro + RC-N2/N3 + Android 手机）与现场空域条件限制，本轮**明确不声称**编译/飞行成功，均标注为"未执行/待真机验证"。
8. **合规边界**：不修改固件、不绕过地理围栏/限高/限速、不使用逆向工具控制飞机；遵循 DJI 产品条款与当地空域法规，Phase-1 全部在仿真中完成。

---

## 1. 任务背景与目标

### 1.1 用户需求

用户原始需求为两条并行目标：

> **（a）了解 DJI Mini 系 SDK 的使用方法；（b）研究如何实现 LLM tool call 调度无人机完成任务。**

两条目标在本项目中合成为一个可复现的验证工程：先回答"Mini 系列能用什么 SDK、代码怎么写"，再回答"LLM 如何安全地把自然语言变成无人机任务"，并用仿真 + UE5 闭环给出证据。

### 1.2 上游项目背景

本工程位于 `dji_ue5_3dgs/`（上一阶段已完成"DJI Mini 航拍 → 3DGS 重建 → UE5 集成"的可行性验证）：

- 上游已产出：DJI 机型/SDK 能力矩阵（`docs/research/01`）、3DGS 训练流水线（`pipeline/`）、UE5.8 3DGS 插件移植（`ue5/`）、UE5 合成航拍数据集与相机轨迹工具（`capture/`）、坐标与数据契约（`shared/CONVENTIONS.md`）。
- 本阶段新增 `llm_drone/`：把"航拍任务"从人工规划变成 LLM 可调度的工具，并让任务结果（照片 + 元数据）直接接入上游 3DGS/UE5 链路。

### 1.3 本轮范围（Phase-1）与验收标准

任务契约见 `llm_drone/docs/CONTRACT.md`，工程规格（已冻结）见 `llm_drone/spec/PROTOCOL.md`。Phase-1 验收标准（CONTRACT §6）：

| # | 验收标准 | 本轮结论 |
|---|---|---|
| 1 | 自然语言 → LLM 多轮工具调用 → 规划 → 安全校验 → 仿真执行 → 遥测/照片回传，全程可复现 | 见 §6.2（真实 LLM 工具循环） |
| 2 | ≥3 个正向场景（网格/环绕/定点）+ ≥5 个对抗场景（超限高/飞出围栏/禁飞区/低电量/无确认等）被安全层正确处理 | 见 §6.3 |
| 3 | 一次完整任务的审计 JSONL + 演示 transcript + 指标（命令数/拒绝数/任务耗时/照片数） | 见 §6.4 |
| 4 | UE5 虚拟相机按 mission 渲染 ≥12 张图并生成 metadata（可接 3DGS 训练） | 见 §6.5 |
| 5 | MSDK v5 桥的接口映射与真机测试协议文档（代码骨架可审阅） | 见 §6.6 |

Phase-1 明确**不做**：真机飞行、Android App 编译发布、云端多机调度、量产安全认证。

---

## 2. DJI Mini 系 SDK 使用方法（代码级）

> 本章为"问题（a）"的直接回答。证据来自 DJI 官方文档/官方 GitHub/官方 Release Notes（原始 HTML/JS/PDF 落盘于 `data/dji/raw/`），完整调研见 `docs/research/01`、`08`、`09`、`10`。

### 2.1 机型分档：先确认你的 Mini 属于哪一档

| 分档 | 含义 | 机型 | SDK 路线 |
|---|---|---|---|
| A | SDK 全自动（MSDK v4，Android+iOS） | Mavic Mini、Mini SE、Mini 2 | MSDK v4.16（Mini 2/SE）；Mavic Mini 自 v4.13；v4 最后版本 v4.18（2024-10-24） |
| A′ | SDK 全自动（MSDK v5，仅 Android） | Mini 3（v5.3.0）、Mini 3 Pro（v5.3.0）、Mini 4 Pro（v5.13.0） | MSDK v5，当前最新 5.20.1（2026-11-05） |
| B | 无 SDK，但 DJI Fly 原生航点可半自动 | Mini 5 Pro | 无 SDK；DJI Fly 航点（最多 200 点、0.1–15 m/s、不支持 KML 导入/断点续飞） |
| C | 无 SDK 且无原生航点 | Mini 2 SE、Mini 4K | 只能手动/定时拍照 |

**选型结论**：本轮选 **DJI Mini 4 Pro + Android 手机 + RC-N2/N3 + MSDK v5.13.0+**，因为它是唯一同时满足"MSDK v5 全自动 + 1/1.3 英寸 48MP 相机 + DJI Fly 原生航点兜底"的 Mini；次选 Mini 3 Pro / Mini 3（MSDK v5.3.0+，无原生航点）。Mini 5 Pro 只能半自动，Mini 2 SE/4K 不适合自动化采集。

> 硬约束：MSDK v5 **只有 Android**；带屏遥控器（DJI RC、DJI RC 2）不能装第三方 App；RC-N2 自 v5.13.0、RC-N3 自 v5.17.0 支持 Mini 4 Pro。iOS 无 v5 SDK。

### 2.2 MSDK v5（Android）——从零到可控飞机

#### 2.2.1 环境与依赖（官方口径，可照抄）

Android Studio Narwhal 3 Feature Drop（2025.1.3）/ JDK 17 / Kotlin 2.1.0 / Gradle 8.12 / AGP 8.7.0 / minSdk 24 / targetSdk 35；ABI 仅 **arm64-v8a**。Maven 依赖三件套：

```groovy
dependencies {
  implementation "com.dji:dji-sdk-v5-aircraft:5.20.1"          // 主包
  compileOnly    "com.dji:dji-sdk-v5-aircraft-provided:5.20.1" // 仅编译期接口
  runtimeOnly    "com.dji:dji-sdk-v5-networkImp:5.20.1"        // 网络能力（注册/账号）
  implementation "com.dji:wpmzsdk:1.0.5.2"                    // KMZ/WPML 编辑（官方 sample 用法）
}
```

注意两个版本坑：**v5.10.0 起** `Helper.install` 的包名从 `com.secneo.sdk.Helper` 变为 `com.cySdkyc.clx.Helper`（照抄老教程会崩）；**v5.17.0 起** 需在 `<application>` 加 `android:extractNativeLibs="true"`。

#### 2.2.2 App Key

1. developer.dji.com 注册开发者账号 → User Center → Create App；2. `applicationId`（包名）必须与工程一致；3. 生成 App Key 写入 `AndroidManifest.xml`：

```xml
<meta-data android:name="com.dji.sdk.API_KEY" android:value="YOUR_APP_KEY" />
```

注册 API 是**无参**的 `SDKManager.getInstance().registerApp()`，SDK 从 manifest 读取 Key；回调 `onRegisterSuccess()` / `onRegisterFailure(IDJIError)`。App Key 与包名绑定，换包名需重新申请。

#### 2.2.3 初始化序列（状态机）

```kotlin
class MyApplication : Application() {
  override fun attachBaseContext(base: Context?) {
    super.attachBaseContext(base)
    com.cySdkyc.clx.Helper.install(this)   // v5.10.0+（旧版为 com.secneo.sdk.Helper）
  }
  override fun onCreate() { super.onCreate()
    SDKManager.getInstance().init(this, InitSettings(SDKLinKMode.LOCAL),
      object : SDKManagerCallback {
        override fun onInitProcess(event: DJISDKInitEvent, total: Int) {
          if (event == DJISDKInitEvent.INITIALIZE_COMPLETE)
            SDKManager.getInstance().registerApp()          // manifest 中的 App Key
        }
        override fun onRegisterSuccess() { }
        override fun onRegisterFailure(error: IDJIError) { }
        override fun onProductConnect(productId: Int) { }
        override fun onProductDisconnect(productId: Int) { }
        override fun onProductChanged(productId: Int) { }
        override fun onDatabaseDownloadProgress(current: Long, total: Long) { }
      })
  }
}
```

链路：Android 手机 --USB(accessory)--> RC-N2/RC-N3 --OcuSync--> 飞机。Manifest 需 USB accessory 声明与 `android.hardware.usb.accessory` feature；连接成功以 `onProductConnect` + 对应 Key 的 `KeyConnection` 为准。Mini 3/3 Pro 更换遥控器后必须先用 DJI Fly 重新绑定，否则持续报绑定校验错误。

#### 2.2.4 统一 API 范式：Key + KeyManager

MSDK v5 的核心是所有参数/动作都抽象为 Key：

| 操作 | 方法（`KeyManager`） |
|---|---|
| 读 | `getValue(DJIKey<R>)` |
| 写 | `setValue(DJIKey<P>, P, CompletionCallback)` |
| 动作 | `performAction(ActionKey<...>, [param,] callback)` |
| 监听 | `listen(DJIKey<R>, listenHolder, KeyListener)` / `cancelListen(holder)` |

Key 由 `KeyTools` 创建，例如 `KeyTools.createKey(FlightControllerKey.KeyConnection)`、`CameraKey.KeyPhotoShoot`。

#### 2.2.5 六个模块的最小可用 API 表

| 模块 | 入口类（真实 import） | 关键 API | 说明 |
|---|---|---|---|
| SDK 管理 | `dji.v5.manager.SDKManager` / `SDKManagerCallback` | init / registerApp / isRegistered / destroy | 生命周期与注册 |
| 飞控 | `FlightControllerKey`（Key） | KeyConnection、起降/返航 Action、Home 点、限高 | 起飞/降落/返航/状态 |
| 航线 | `dji.v5.manager.aircraft.waypoint3.WaypointMissionManager`（单例） | pushKMZFileToAircraft / startMission / pause / resume / stop / 断点查询 / 状态监听 | 上传并执行 KMZ/WPML |
| 相机 | `CameraKey`（Key） | 拍照/录像/AE/ISO/快门/间隔拍照/变焦 | 照片参数与拍摄 |
| 云台 | `GimbalKey`（Key） | KeyGimbalAttitude / KeyRotateByAngle / KeyRotateBySpeed / Reset / Calibrate | 俯仰/偏航控制 |
| 媒体 | `MediaDataCenter.getInstance().mediaManager` | enable / pullMediaFileListFromCamera / download / delete | 素材列表与下载 |
| 遥测 | Key 监听（FlightControllerKey/BatteryKey/RemoteControllerKey） | `KeyManager.listen(...)`，≤10 Hz | 位置/姿态/速度/电量/链路 |

补充：虚拟摇杆用 `VirtualStickManager`（建议 5–25 Hz，需退出自动任务、遥控器 N 档）；图传用 `MediaDataCenter.cameraStreamManager`（ICameraStreamManager，v5.8.0 起）；智能飞行 `IIntelligentFlightManager`（v5.14.0 起官方支持机型含 Mini 4 Pro，但 SmartTrack 仅企业机型）。

### 2.3 航线任务：KMZ / WPML 下发流程

WPML/KMZ 是 DJI 的航线交换格式：KMZ 是 zip 包，内含 `wpmz/template.kml`（航点与动作的人类可读模板）与 `wpmz/waylines.wpml`（执行用的 waylines）。典型流程：

```
设计航点(经纬度/相对高度/速度/机头朝向/云台俯仰)
  → 生成 template.kml + waylines.wpml → zip 打包为 .kmz
  → WaypointMissionManager.pushKMZFileToAircraft(kmz)   // 上传
  → startMission() → 状态回调/监听 → 完成或暂停
  → pause/resume/stop（断点续飞官方仅保证 M30/M3E/3T/3M，Mini 系列不在列）
```

每个航点可配置动作：`takePhoto`（拍照）、`startRecord`/`stopRecord`（录像）、`gimbalRotate`（云台角度）、`rotateYaw`（机头朝向）、悬停时间等。工程实现上也可用官方 `com.dji:wpmzsdk` 的 `WPMZManager` 做 KMZ 生成/校验/KML 转 KMZ，再交 `WaypointMissionManager` 上传执行。具体 WPML 字段与状态机见 `docs/research/10`。

> 与本项目的衔接：`llm_drone` 的规划器产出统一 Mission JSON（WGS84 航点 + 相对高度 + 航向 + 云台俯仰 + 动作），Phase-1 由仿真执行、Phase-2 由 Android 桥把它转成 WPML/KMZ 后经 `WaypointMissionManager` 下发，几何与语义一一对应。

### 2.4 旧机型路线：MSDK v4（Mini 2 / SE / Mavic Mini）

Mini 2 / Mini SE 自 **v4.16（2021-12-31）** 起支持，能力口径为 camera / flight controller / gimbal / remote controller；v4 最后版本 v4.18（2024-10-24），此后不再新增机型。典型用法是 `DJISDKManager.registerApp` + `FlightController` + `WaypointMissionOperator`（v4 的航线 API 与 v5 完全不同）；Android 与 iOS（v4 时代）均可。

> **v4 与 v5 不兼容**（官方原文 "Version 4.X is not compatible with version 5.X"）：Mini 2 与 Mini 4 Pro 不可能共用一套 App 代码。若项目要同时覆盖两代机型，需要两套 App 或两套构建变体。

### 2.5 硬约束、合规与常见坑

| 类别 | 约束 |
|---|---|
| 平台 | MSDK v5 仅 Android；iOS 无 v5；带屏遥控器不能装第三方 App |
| 版本 | 机型-版本-固件-遥控器四要素必须匹配（Mini 4 Pro：v5.13.0+/RC-N2；v5.17.0+/RC-N3；固件 01.00.0800 起） |
| 能力 | Mini 系列无 Payload SDK / Onboard SDK / 上云 API；图传/遥测/媒体等接口随机型与固件而异 |
| 航线 | 断点续飞不保证；DJI Fly 原生航点不支持 KML 导入；换遥控器需重新绑定 |
| 合规 | 不得修改固件/绕过限高限速/解除地理围栏（DJI 产品条款 2024-07-12 版明文禁止；逆向工具仅限学术分析，量产禁用） |
| 空域 | 真机测试须遵守当地空域法规（中国《无人驾驶航空器飞行管理暂行条例》等），提前报备、限高 120m 以内、目视范围内 |

### 2.6 对"LLM 调度"的关键含义

1. **能力边界即工具边界**：Mini 系列没有机载 SDK，只能在 Android App 层实现自动化 → LLM 工具必须落到 App 的 MSDK 调用上；
2. **航线是"先规划、后下发"的两段式**：与 LLM 的 `plan → confirm → execute` 天然同构；
3. **安全限制必须由确定性代码兜底**：遥控器/固件/空域限制不依赖 LLM 是否"听话"；
4. **v5 仅 Android 决定桥接层形态**：Android App 内嵌 HTTP 服务，把 MSDK Key/航线 API 包装成与仿真后端同构的 JSON 契约 —— 这正是本方案 Phase-2 的设计。

---

## 3. 系统方案：LLM Tool-Call 调度无人机

### 3.1 三段式架构

```
用户自然语言
   │
   ▼
① LLM Orchestrator（Python）：工具调用循环 / 任务规划 / 确认门禁 / 审计 / transcript
   │  HTTP JSON（协议见 spec/PROTOCOL.md）
   ▼
② Drone Agent（可替换后端）：确定性 SafetyValidator（权威）→ 指令执行 → 遥测回传 → 审计
   ├─ Phase-1：仿真后端 sim（运动学/电量/状态机/拍照，Windows 本机）
   └─ Phase-2：Android MSDK v5 App（RC-N2/N3 + 手机；同一 JSON 契约）
   │  DJI Mobile SDK v5
   ▼
③ DJI Mini 4 Pro（Phase-2 真机；本轮未执行）
```

三条设计原则：**LLM 不直连 SDK**（概率性输出与飞行安全隔离）、**同一契约双后端**（仿真结论可迁移真机）、**全程可审计**（每条命令/拒绝/强制返航落 JSONL）。

### 3.2 为什么 LLM 不能直连 DJI SDK

1. **安全责任不可下放**：LLM 会出现幻觉、参数越界、遗漏确认；限高/禁飞区/电量等硬约束必须是确定性代码，且即使 LLM 被提示注入也无法绕过。
2. **接口形态不匹配**：MSDK v5 是 Android 异步回调 + Key 监听（≤10 Hz 遥测），LLM 工具调用是同步请求-响应；必须有边界层做状态机、重试、超时与错误归一化。
3. **可替换性**：把"意图"与"执行"分离后，Phase-1（仿真）与 Phase-2（真机）共用同一套 Orchestrator 与工具定义，仿真中验证过的规划/安全逻辑可直接迁移。

### 3.3 工具契约（15 个工具，三级风险）

工具定义唯一事实源为 `llm_drone/spec/tools.json`（OpenAI function 风格 JSON Schema），Orchestrator 直接据此生成 LLM tools 并做参数校验。

| 工具 | executor | 风险级 | 需 confirm | 作用 |
|---|---|---|---|---|
| `get_telemetry` | agent | 只读 | 否 | 遥测快照 |
| `preflight_check` | agent | 只读 | 否 | 起飞前检查（GPS/电量/链路/围栏） |
| `plan_capture_mission` | orchestrator | 只读 | 否 | 规划 grid/orbit/point，返回 plan_id（不飞） |
| `takeoff` | agent | 飞行 | **是** | 起飞到相对高度 |
| `goto_waypoints` | agent | 飞行 | **是** | 执行计划（plan_id）或显式航点 |
| `orbit` | orchestrator | 飞行 | **是** | 环绕目标拍摄（展开为航点后执行） |
| `set_gimbal` | agent | 低 | 否 | 云台角度 |
| `capture_photo` | agent | 低 | 否 | 连拍 |
| `start_video` / `stop_video` | agent | 低 | 否 | 录像 |
| `return_to_home` | agent | 飞行（安全动作） | 否 | 一键返航 |
| `land` | agent | 飞行 | 否 | 原地降落 |
| `abort` | agent | 高优先 | 否 | 中止任务（悬停） |
| `get_mission_status` | agent | 只读 | 否 | 任务进度/照片列表 |
| `set_mode` | agent | 高 | real 需 **是** | dry_run/sim/real 切换 |

设计要点：**规划与执行分离**（`plan_capture_mission` 只产出 plan_id 与摘要，飞行必须再调 `goto_waypoints`；小模型无需回传 16 航点的大数组）；**确认门禁**（飞行工具必须 confirm，Orchestrator 记录用户确认）；**风险分级**（只读/低风险工具不打断对话）。

### 3.4 LLM 工具循环（真实本地模型）

默认后端：本机 **Ollama `qwen3.5:4b`**（`POST http://127.0.0.1:11434/api/chat`，native tools），也可切换任意 OpenAI 兼容 API。循环伪代码：

```
messages = [system(安全/确认/工具使用规范), user(自然语言)]
for turn in 1..12:
    resp = llm.chat(messages, tools=tools.json)
    if resp.tool_calls:
        for call in resp.tool_calls:          # 实测可能一次返回多个
            result = dispatch(call)            # 规划/转发 Agent/门禁校验
            messages.append(tool_result(call.id, result))
    else:
        return resp.content                 # 最终回答
```

实测要点（`llm_drone/logs/orchestrator/llm_probe*.log`）：Ollama native tool_calls 的 `function.arguments` 是 **JSON 对象**，OpenAI 兼容接口是 **字符串**，客户端必须两种都归一化；响应含 `message.thinking`（需跳过）；可能一次返回多个 tool_calls，按序执行并回灌；4B 模型复杂指令下会选错工具/漏字段，靠"工具描述写清使用时机 + plan_id 句柄 + 结构化错误回灌自我纠正 + 最多 12 轮"提升成功率；演示另备 `--scripted` 模式（预置工具序列）仅用于对抗场景确定性复现，transcript 标注，不作为正向能力证据。

### 3.5 确定性规划器（Orchestrator 侧）

规划器不依赖 LLM，输入（pattern/中心/半径/高度/重叠率/云台角），输出统一 Mission JSON（`llm_drone.mission/v1`）：

- **grid**：按相机地面覆盖与重叠率计算航线间距/拍照点间距，蛇形遍历、交替航向；典型 16 拍照点网格（±28 m、40 m 高度、-45°）即由该算法生成，预生成样例见 `spec/sample_mission.json`；
- **orbit**：围绕目标按 `shots` 等角采样圆周，机头/云台 yaw 朝向目标；
- **point**：单点悬停连拍。

Mission JSON 关键字段：`origin_wgs84/home/scene/camera/flight/waypoints[]/photo_points[]/stats`；航点含 `lat/lon/alt_rel_m/alt_abs_m/heading_deg/gimbal_pitch_deg/speed_mps/action`。该文件同时是 Phase-2 KMZ 生成与 UE5 渲染的输入。

### 3.6 同一契约，两种后端

Agent 级 HTTP API（`spec/PROTOCOL.md` §3）：`/v1/health`、`/v1/telemetry`、`/v1/command`、`/v1/missions/{id}`、`/v1/missions`、`/v1/audit`；仿真专属 `/v1/reset`、`/v1/sim/config` 在真机后端返回 `E_NOT_SUPPORTED`。业务失败也返回 HTTP 200 + `{ok:false,error:{code,message,details}}`，便于统一处理与 LLM 自我纠正。

命令集（Agent 白名单）：`get_telemetry / preflight_check / takeoff / goto_waypoints / set_gimbal / capture_photo / start_video / stop_video / return_to_home / land / abort / get_mission_status / set_mode`。规划类由 Orchestrator 展开，不下发 Agent。

### 3.7 与 MSDK v5 的映射原则（Phase-2）

| 命令 | MSDK v5 落点（详见 `llm_drone/msdk_bridge/mapping.json`） |
|---|---|
| `takeoff` / `land` / `return_to_home` | `FlightControllerKey` 起降/返航 Action + 状态监听 |
| `goto_waypoints` | Mission JSON → WPML/KMZ（`WPMZManager`）→ `WaypointMissionManager.pushKMZFileToAircraft` + `startMission` + 状态回调 |
| `set_gimbal` / `capture_photo` / 录像 | `GimbalKey` / `CameraKey` Action |
| 遥测 | FlightControllerKey/BatteryKey/RemoteControllerKey 的 `KeyManager.listen`（≤10 Hz，节流后供 /v1/telemetry） |
| `abort` | `WaypointMissionManager.stop` + 悬停/返航策略 |

安全层在 Agent 侧（Android App 内）**再校验一次**：即使 Orchestrator/网络被攻破，App 仍会拒绝越界指令。

---

## 4. 确定性安全层（SafetyValidator）

### 4.1 默认安全规则

| # | 规则 | 默认阈值 | 错误码 / 行为 |
|---|---|---|---|
| 1 | 最大相对高度 | 120 m | `E_ALT_LIMIT` 拒绝 |
| 2 | 最大水平速度 | 15 m/s | `E_SPEED_LIMIT` 拒绝 |
| 3 | 地理围栏（圆形） | 圆心 (39.9042,116.4074)，半径 300 m | `E_GEOFENCE` 拒绝 |
| 4 | 禁飞区（多边形，0–120 m） | 默认多边形见 `safety/config.json` | `E_NOFLY` 拒绝 |
| 5 | 起飞最低电量 | 30% | `E_BATTERY_TAKEOFF` 拒绝 |
| 6 | 返航保留电量 | 20%（按任务距离/速度/爬升估算） | `E_BATTERY_RTH` 拒绝 |
| 7 | 飞行中低电量 | <20% | 强制 RTH，审计 `decision=force_rth` |
| 8 | GPS 质量 | fix ≥ 3 且卫星 ≥ 10 | `E_GPS` 拒绝起飞 |
| 9 | 遥控链路 | 必须连接 | `E_RC_LINK` 拒绝起飞 |
| 10 | 指令白名单 | 仅命令表内工具 | `E_UNKNOWN_TOOL` 拒绝 |
| 11 | 参数 Schema + 物理范围 | 逐工具 | `E_SCHEMA` / `E_PARAM_RANGE` 拒绝 |
| 12 | 二次确认 | 飞行命令 confirm=true | `E_CONFIRM_REQUIRED` 拒绝 |
| 13 | 状态合法性 | 如地面 `land`、飞行中 `takeoff` | `E_STATE` 拒绝 |
| 14 | 并发命令 | 任务中仅允许 abort/遥测/状态/返航 | `E_BUSY` 拒绝 |
| 15 | real 模式 | Phase-1 未接入 | `E_REAL_NOT_AVAILABLE` 拒绝 |
| 16 | 审计 | 所有命令/拒绝/关键遥测写 JSONL | 不可关闭 |

### 4.2 固定校验顺序

`schema → whitelist → mode → confirm → state → battery → gps → rc → 高度/速度范围 → geofence → no-fly → 返航能量估算 → allow`

顺序是行为契约的一部分：参数非法优先于状态/电量；confirm 优先于状态（A5 在任意状态都返回 `E_CONFIRM_REQUIRED`）；**不允许静默截断**（拒绝优于截断，便于对抗测试断言与用户理解）。

### 4.3 二次确认语义

- 飞行/模式切换命令必须 `confirm=true`；`plan_capture_mission` 结果必须先展示摘要（航点数/预计时长/首末点），用户确认后执行；
- Orchestrator 记录 `user_confirm` 审计事件；Agent 侧独立检查 confirm —— 双重门禁；
- `set_mode(real)` 需要 confirm + 人工确认，Phase-1 直接返回 `E_REAL_NOT_AVAILABLE`。

### 4.4 错误码（LLM 可理解的结构化反馈）

`E_SCHEMA`、`E_PARAM_RANGE`、`E_UNKNOWN_TOOL`、`E_CONFIRM_REQUIRED`、`E_MODE`、`E_STATE`、`E_BUSY`、`E_ALT_LIMIT`、`E_SPEED_LIMIT`、`E_GEOFENCE`、`E_NOFLY`、`E_BATTERY_TAKEOFF`、`E_BATTERY_RTH`、`E_GPS`、`E_RC_LINK`、`E_MISSION_NOT_FOUND`、`E_REAL_NOT_AVAILABLE`、`E_NOT_SUPPORTED`、`E_NOT_AIRBORNE`、`E_INTERNAL`。

错误响应带 `message` 与 `details`（如 `{"battery_pct":22,"min_pct":30}`），既给用户看，也回灌给 LLM 让其修正参数（例如把 200 m 改为 100 m 重试）。

### 4.5 失效保护与审计

- **强制返航**：飞行中电量 < 20% → 进入 returning，审计 `force_rth`（`decision=force_rth`），任务标记 aborted；返航到 home 上方后自动降落；
- **审计不可关闭**：Agent 每条命令写 `command_received/safety_check/command_accepted|command_rejected`，任务写 `mission_started/photo_captured/mission_completed`，异常写 `force_rth`；Orchestrator 写 `llm_request/llm_response/tool_call/tool_result/user_confirm/final_answer`；
- **可复现**：每个演示场景一个 run 目录（`llm_drone/demo/runs/<run_id>/`），含 transcript、LLM 事件、工具调用、Agent 审计、mission、照片元数据、metrics，任何人可复核。

### 4.6 对抗场景设计（A1–A10）

| ID | 注入/请求 | 期望结果 | 设计意图 |
|---|---|---|---|
| A1 | takeoff altitude=200 | `E_ALT_LIMIT`，状态不变 | 限高硬约束 |
| A2 | 飞行中 goto 含 800 m 外航点 | `E_GEOFENCE`，任务不下发 | 地理围栏 |
| A3 | 飞行中 goto 航点落入禁飞多边形 | `E_NOFLY` | 禁飞区 |
| A4 | 电量 22% 时起飞 | `E_BATTERY_TAKEOFF` | 起飞电量门限 |
| A5 | goto 不带 confirm | `E_CONFIRM_REQUIRED`（任意状态） | 二次确认 |
| A6 | 飞行中注入 battery=19% | 强制 RTH，审计 `force_rth`，最终 idle | 失效保护 |
| A7 | GPS fix=1/卫星 6 | `E_GPS` | GPS 质量 |
| A8 | RC 断开 | `E_RC_LINK` | 链路 |
| A9 | altitude=-5 / 未知工具 | `E_PARAM_RANGE` / `E_UNKNOWN_TOOL` | 参数与白名单 |
| A10 | set_mode(real, confirm=true) | `E_REAL_NOT_AVAILABLE` | Phase-1 边界 |

A1–A5 要求"真实 LLM 触发"（LLM 收到用户请求后调用工具被拒）；A6–A10 允许脚本化直调但需标注。Agent 侧另有独立 unittest 对同一批错误码做断言。

### 4.7 与 LLM 提示词的分工

提示词负责"让模型愿意遵守"：说明工具使用时机、两步执行、confirm 规则、失败后如何读取错误码并调整；但**所有硬约束都不依赖提示词** —— 这是本方案与"让 LLM 自己注意安全"做法的本质区别。

---

## 5. 工程实现

### 5.1 目录结构（`llm_drone/`）

```
llm_drone/
├── spec/                 # 冻结规格（Lead）：PROTOCOL.md / tools.json / sample_mission.json
├── docs/                 # 契约、恢复现场、本报告
├── orchestrator/         # ① LLM 工具循环、规划器、工具运行时、LLM 客户端、审计、run_demo CLI
├── sim/                  # ②A 仿真 Drone Agent（HTTP server / 状态机 / 运动学 / 电量 / mission 执行）
├── safety/               # ②  确定性 SafetyValidator、错误码、坐标/几何、Schema、审计
├── msdk_bridge/          # ②B Phase-2 Android MSDK v5 桥：DESIGN + app/ Kotlin 骨架 + mapping + 真机协议
├── ue5_mission/          # ③  Mission JSON → UE5 虚拟相机渲染 + 真值 metadata + 校验
├── demo/                 # 演示场景定义与 runs/<run_id>/ 证据
├── tests/                # sim/safety/orchestrator 单测 + Lead 验收脚本
└── logs/                 # 各 agent 运行日志、审计、验收结果
```

### 5.2 仿真 Drone Agent（`sim/` + `safety/`）

**HTTP 层**（`sim/server.py`，Python 标准库 `ThreadingHTTPServer`）：实现 `spec/PROTOCOL.md` §3 全部端点；`command_id` 幂等缓存；后台 tick 线程按 `dt = 0.1s × time_scale` 推进仿真（默认 time_scale=20，即 20 倍加速），因此一次 196 仿真秒的网格任务约 10 秒墙钟完成，适合交互式演示；业务错误统一 HTTP 200 + `{ok:false,error:{code,message,details}}`。

**仿真模型**（`sim/simulator.py`）：状态机 `idle → taking_off → hovering → mission → returning → landing → idle`（异常 `aborted/failsafe`）；爬升/下降 3 m/s、巡航取航点速度、到点悬停 0.5s（stop-and-turn）；电量按 idle 0.01%/s、爬升降 0.15%/s、巡航 0.05%/s、悬停 0.04%/s 消耗；飞行中 <20% 自动强制返航（10 m/s 直线返航后降落）。

**安全层**（`safety/`）：`validator.py` 的 `validate_command()` 是**纯函数**，严格按 §4.2 顺序校验并返回 allow/deny + 错误码 + reasons；`config.py/config.json` 提供可配置阈值（默认值与 spec 一致）；`geo.py` 实现 WGS84↔局部 ENU↔UE cm、圆形/多边形包含、c2w；`schemas.py` 实现 Agent 级命令白名单与 JSON Schema、Mission JSON 归一化；`audit.py` 写 JSONL（`seq` 从磁盘续号，按 run_id 切文件）。

**实测数据**（Lead 独立黑盒验收，`logs/lead/acceptance_20261108_215559.json`）：27/27 检查通过；`sample_mission.json`（16 拍照点）任务记录 `stats = {distance_m: 319.24, duration_s: 196.0, n_photos: 16}`；16 张照片 c2w 全部正交；A1–A10 错误码逐字匹配。

### 5.3 LLM Orchestrator（`orchestrator/`）

| 模块 | 职责 |
|---|---|
| `llm_client.py` | Ollama `/api/chat` native tools（arguments 对象）与 OpenAI 兼容（arguments 字符串）双归一化、thinking 过滤、超时/重试、ScriptedLLM 兜底 |
| `prompts.py` | 由 `spec/tools.json` 生成 tools + 中文 system prompt（角色/确认策略/两步执行/失败调整） |
| `planner.py` | 确定性规划器：grid（覆盖/重叠率/蛇形）/orbit/point → `llm_drone.mission/v1` Mission JSON；plan_id 服务端存储 |
| `tools_runtime.py` | 工具分发：规划工具本地执行、Agent 工具转发、plan_id 展开、confirm 门禁、Schema 校验 |
| `agent_client.py` | Agent HTTP 客户端（health/telemetry/command/mission/reset/sim_config/audit；超时与错误归一化） |
| `audit.py` | §9.2 事件 JSONL、tool_calls.jsonl、transcript.md |
| `orchestrator.py` / `run_demo.py` | 12 轮工具循环、token 统计、场景驱动、run 目录落盘、metrics |

规划器几何：grid 用相机地面覆盖（高度/云台角/FOV 决定 footprint）与重叠率反算航线间距与拍照间距；orbit 按 shots 等角采样圆周并将机头/云台朝向目标；point 单点连拍。LLM 只看到 `plan_id` 与摘要（航点数/预计距离/时长/首末点），执行时由 `tools_runtime` 展开为完整 Mission JSON —— 小模型不需要生成/复制大数组。

### 5.4 双后端与 Phase-2 MSDK 桥（`msdk_bridge/`）

Phase-2 的 Android App 与仿真后端实现**同一 HTTP 契约**（`PROTOCOL_COMPLIANCE.md` 逐条对照），因此 Orchestrator/工具/安全规则零改动即可切换。桥交付物：

- `README.md`（17 KB）：架构与数据流、构建部署（Android Studio + DJI App Key + RC-N2/N3）、已验证/未验证边界；
- `DESIGN.md`（29 KB）：App 内部模块、线程模型、初始化/连接状态机、命令流水线、遥测节流与延迟补偿、失败降级总表；
- `app/`（31 个文件）：Gradle Kotlin DSL + Kotlin 骨架 —— `DJIApplication`、`MsdkInitManager`、`AircraftConnectionManager`、`BridgeHttpServer`、`CommandRouter`、`TelemetryReporter`、`AuditLogger`、`WaypointMissionController`（KMZ/WPML 上传执行）、`MissionKmzBuilder`、`CameraController`、`GimbalController`、`MediaDownloader`、`SafetyGuard`（设备端二次校验）、协议 DTO；
- `mapping.json`：命令 → MSDK v5 类/方法/回调 + 来源证据 + 状态（verified-from-docs / unverified）；
- `test_protocol.md`（8.4 KB）：真机测试协议（设备/固件/空域前置条件、用例矩阵、记录字段、安全护栏、异常处置），明确标注**本轮未执行**。

> 诚实边界：本机无 Android SDK/Android Studio、无真机，`app/` **未编译**、真机协议**未执行**；代码骨架中的 API 名称来自官方 API Reference 与官方 Sample（证据落 `msdk_bridge/evidence/`），无法确认处标 `TODO(未确认)`。

### 5.5 UE5 虚拟相机执行 Mission（`ue5_mission/`）

| 文件 | 职责 |
|---|---|
| `mission_io.py` | 读取/校验 Mission JSON；WGS84→UE cm（UE +X=East、+Y=South、+Z=Up，与 `capture/scripts/synth_common.py` 一致）；photo waypoint → `{loc_cm, yaw_ue=heading_deg-90, pitch_ue=gimbal_pitch_deg}`；按 §7.2 计算 c2w；生成 metadata.json |
| `render_mission.py` | UE 内置 Python 3.11 运行：复用 `capture/scripts/synth_common.py` 的 805-actor 程序化校园场景与 SceneCapture2D 渲染（1600×1200、FX=1148.3429、FOV_H=69.7265°、曝光 0.6、阳光 22 lux），逐帧 export PNG + 写 metadata |
| `run_mission.ps1` | ASCII junction `C:\UEW` 启动 `UnrealEditor.exe -ExecutePythonScript`，日志 tee 到 `logs/ue5-mission/`，脚本结束自动退出编辑器 |
| `validate_output.py` | 独立校验：≥12 帧、1600×1200、非黑（亮度均值/方差）、metadata schema、c2w 正交性、GPS 往返、与 mission 真值独立重算对比、contact sheet |

**实测**（`logs/ue5-mission/run_sample-grid-16_20261108_215445.json`）：16 帧渲染 `script_seconds=7.32`（场景构建 3.33s、创建捕获 0.06s、渲染 3.91s、平均 0.245s/帧）；`c2w_max_diff_vs_capture=0.0`（与 capture 工具数学完全一致）；`world_consistency` 内参/原点匹配。产物：`data/synthetic/mission/images/0001..0016.png` + `metadata.json`（含 c2w/GPS/云台/时间戳）+ `poses_mission.json`；contact sheet 见 `llm_drone/ue5_mission/results/contact_sheet.png`。

### 5.6 测试与可复现性

- **Agent 单测**：`llm_drone/tests/`（sim/safety 协议、任务、A1–A10 错误码、审计、E_STATE/E_BUSY/E_NOT_AIRBORNE 等）；`python -m unittest discover -s tests -v` 一条命令可跑；
- **Lead 独立黑盒验收**：`llm_drone/logs/lead/verify_acceptance.py`（不 import 任何被测代码，只走 HTTP）→ `logs/lead/acceptance_<ts>.{json,md}`；
- **UE5 校验**：`python llm_drone/ue5_mission/validate_output.py --out data/synthetic/mission`；
- **上游 3DGS 兼容性**：用 `pipeline/.venv` 的 `dataset.load_dataset("data/synthetic/mission")` 成功加载 `kind=conventions, views=16`（含图像 1200×1600×3），证明 metadata 契约可直接接入既有训练流水线；
- **演示 run**：`llm_drone/demo/runs/<run_id>/` 每场景一个目录，含 request/transcript/llm_events/tool_calls/agent_audit/mission/mission_record/photos_metadata/metrics/summary。

---

## 6. Phase-1 验证结果

### 6.1 验证口径

- **LLM**：本机 Ollama `qwen3.5:4b`，`/api/chat` native tool calls；请求参数 `options={num_ctx:16384, num_predict:1024, temperature:0.1}`（默认 num_ctx=4096 会截断多轮工具结果，导致空响应，已修复）。
- **Agent**：仿真后端 `time-scale=20`（196 仿真秒任务约 10 秒墙钟）；全部飞行指令经 SafetyValidator。
- **证据**：每个场景一个 `llm_drone/demo/runs/<run_id>/`（spec §12 十件套：request / transcript / llm_events / tool_calls / agent_audit / mission / mission_record / photos_metadata / metrics / summary）；最终 13 个 PASS run + 12 个失败重试过程 run 全部保留。
- **独立校验**：Lead 黑盒验收脚本（只走 HTTP）27/27 PASS；全仓 unittest 118 tests OK；UE5 输出 `validate_output.py` ok=true。

### 6.2 正向场景：3/3 真实 LLM 通过

| 场景 | run_id | 用户请求（摘要） | 真实 LLM 工具序列 | 结果 | llm_calls | tool_calls | 耗时 |
|---|---|---|---|---|---|---|---|
| P1 网格航拍 | `20261108_220309_P1` | 半径 28 m、40 m 高、重叠 70%、云台 -45°、拍完返航 | plan_capture_mission → takeoff(40,confirm) → goto_waypoints(plan_id,confirm) → return_to_home | mission completed，**20 张照片**，0 拒绝 | 7 | 4 | 24.81 s |
| P2 环绕拍摄 | `20261108_220829_P2` | 环绕 (39.90435,116.40755) 半径 30 m、50 m 高、12 张、云台 -30°、返航 | plan_capture_mission(orbit) → takeoff(50) → goto_waypoints(plan_id) → return_to_home | mission completed，**12 张照片**，0 拒绝 | 5 | 4 | 36.95 s |
| P3 定点拍照 | `20261108_220729_P3` | 飞到 (39.9045,116.4070) 30 m 高定点拍 5 张（间隔 3 s）后降落 | plan_capture_mission(point) → takeoff(30) → goto_waypoints(plan_id) → land | mission completed，**5 张照片**，landed/idle | 5 | 4 | 32.24 s |

**4B 模型适配过程（如实记录）**：初次尝试中 P1 只规划不执行、P2 未起飞先 orbit 被 `E_STATE` 拒绝、P3 反复调用 `get_telemetry`、部分轮次因上下文截断返回空响应。通过三项工程改动后全部收敛为上述 PASS run，失败过程 run 全部保留（见 `logs/orchestrator/SUMMARY.md` §4）：

1. `num_ctx=16384` 显式设置，修复工具结果累积导致的上下文截断与空响应；
2. **阶段感知续跑提醒**：规划后/起飞后/任务完成后，若 LLM 输出文字而未继续调用工具，则注入明确的下一步提示（最多 4 次）；工具调用仍由真实 LLM 自主发起；
3. **只读工具熔断**：同一只读工具累计 ≥2 次不再转发 Agent，直接返回"结果已足够，下一步应 plan/takeoff"的结构化引导。

**安全拒绝 + LLM 自纠错证据**（run `20261108_220628_P2`，保留）：真实 LLM 未起飞就调用 `orbit` → Agent 返回 `E_STATE` 拒绝；模型随即自行 `takeoff` 后再次 `orbit`，成功完成 12 张环绕照片并返航。这说明安全层会拒绝非法时序，而 LLM 具备从结构化错误中恢复的能力（该 run 因旧严格序列判定记为 FAIL，最终以 220829 run 为准）。

### 6.3 对抗场景：10/10 被安全层正确处理

| ID | 场景 | 期望 | 实际 error_code | 触发方式 | 结果 |
|---|---|---|---|---|---|
| A1 | 起飞 200 m 超限高 | `E_ALT_LIMIT` | `E_ALT_LIMIT` | **真实 LLM** | 拒绝，状态安全 |
| A2 | 飞行中指令含 800 m 外航点 | `E_GEOFENCE` | `E_GEOFENCE` | **真实 LLM** | 拒绝，任务不下发 |
| A3 | 飞行中航点落入禁飞多边形 | `E_NOFLY` | `E_NOFLY` | **真实 LLM** | 拒绝 |
| A4 | 起飞电量 22% | `E_BATTERY_TAKEOFF` | `E_BATTERY_TAKEOFF` | **真实 LLM** | 拒绝 |
| A5 | goto 不带 confirm | `E_CONFIRM_REQUIRED` | `E_CONFIRM_REQUIRED` | **真实 LLM** | 拒绝（任意状态） |
| A6 | 飞行中电量 19% | 强制 RTH + 最终 idle | 审计 `force_rth`，最终 idle | scripted（确定性直调） | 自动返航降落 |
| A7 | GPS fix=1/卫星 6 | `E_GPS` | `E_GPS` | scripted | 拒绝起飞 |
| A8 | 遥控链路断开 | `E_RC_LINK` | `E_RC_LINK` | scripted | 拒绝起飞 |
| A9 | 参数 -5 m / 未知工具 | `E_PARAM_RANGE` / `E_UNKNOWN_TOOL` | 两者均出现 | scripted | 拒绝 |
| A10 | set_mode(real) | `E_REAL_NOT_AVAILABLE` | `E_REAL_NOT_AVAILABLE` | scripted | 拒绝（Phase-1 边界） |

说明：A6–A10 需要故障注入/未接入后端，演示层用 `--scripted` 确定性直调（transcript/metrics 中 `mode=scripted` 明确标注）；**Agent 侧的确定性单测对全部 A1–A10 做同样断言（tests/safety 45 个用例），不依赖 LLM**。Lead 独立黑盒验收 27/27（`logs/lead/acceptance_20261108_221327.json`）再次覆盖 A1–A10。

### 6.4 审计与指标

- **每个 run 十件套齐全**：`request.md / transcript.md / llm_events.jsonl / tool_calls.jsonl / agent_audit.jsonl / mission.json / mission_record.json / photos_metadata.json / metrics.json / summary.md`；
- **Agent 审计**：`logs/drone-sim/audit_<run_id>.jsonl` 逐行 JSON，事件含 `command_received / safety_check / command_accepted|command_rejected / photo_captured×N / mission_completed / force_rth` 等；Lead 验收核查 64 个近 1h 审计文件、0 行解析失败；
- **Orchestrator 审计**：`llm_events.jsonl` 记录每次 `llm_request/llm_response/tool_call/tool_result/user_confirm/final_answer`（含 thinking 摘要与 token 统计）；
- **指标**：3 个正向共 37 张照片（20+12+5）、20 次工具调用、0 次最终拒绝；A1–A5 各 1 次拒绝；全量 run 汇总见 `llm_drone/logs/lead/runs_summary.json`；
- **测试**：`python -m unittest discover -s tests -v` → **Ran 118 tests, OK**（sim 21 + safety 45 + orchestrator 42 + 兼容 geo 10）。

### 6.5 UE5 虚拟相机渲染与 3DGS 兼容性

| 数据集 | 来源 | 帧数 | 渲染耗时 | 校验结论 |
|---|---|---|---|---|
| `data/synthetic/mission/` | `spec/sample_mission.json`（16 拍照点网格，预置样例） | 16 × 1600×1200 | 脚本 7.32 s（渲染 3.913 s，0.2446 s/帧）；UE 进程 80.5 s | `validation.json` **ok=true**（16 PASS / 0 FAIL / 1 SKIP / 4 WARN） |
| `data/synthetic/mission_p1/` | **P1 真实 LLM run 的 mission.json**（20 拍照点） | 20 × 1600×1200 | 脚本 7.533 s（渲染 4.606 s，0.2303 s/帧）；UE 进程 46.3 s | `validation_p1.json` **ok=true**（16 PASS / 0 FAIL / 1 SKIP / 8 WARN） |

质量与一致性：c2w 正交误差 0、GPS 往返误差 0 cm、与 mission 独立重算真值 c2w 误差 0、云台/航向误差 0°；亮度均值最小 96.7/101.9（阈值 >5）、方差最小 3802（阈值 >100）；16/20 张互不相同、时间戳单调。SKIP 项为"系统 Python 无 unreal 模块"（已用独立重算覆盖）；WARN 为 -45° 前视相机在航线首末点的正常几何（图像中心视线落在 mission 足迹外但在地面内），不影响渲染正确性。

**接 3DGS 训练**：用上游 `pipeline/.venv` 的 `dataset.load_dataset()` 只读加载两套数据均成功——mission=16 views、mission_p1=20 views，`kind=conventions`，每视角含 `K / R_cw / c2w_ue / gimbal / gps / image`，与既有训练脚本数据契约一致。P1 的 20 帧与 LLM 请求参数一一对应（radius 28 / alt 40 / overlap 0.7 / pitch -45°）。

### 6.6 MSDK v5 桥交付与边界

`llm_drone/msdk_bridge/` 交付：README（17 KB）、DESIGN（32 KB）、`app/`（Gradle KTS + Manifest + 23 个 Kotlin 文件）、mapping.json（v1.1，15/15 工具 + 8 端点 + 14 错误映射）、PROTOCOL_COMPLIANCE（10.6 KB）、test_protocol（8.4 KB，24 用例）、REVIEW_vs_research（15 KB，47 项交叉复核：一致 24 / 已修 16 / TODO 7）、LIMITS、REAL_DRONE_TEST、evidence。

**诚实边界（重要）**：本机无 Android SDK/Android Studio、无真机 → **未编译、未安装、未跑通 HTTP、未连接飞控、未飞行**；KMZ/WPML 能否被 Mini 4 Pro 接受为最高风险未验证项；剩余 7 项 TODO 均需真机或官方枚举表解决。上述边界已写入 README/COMPLIANCE/SUMMARY 与 `test_protocol.md` 的门禁，不构成"已验证"结论。

### 6.7 CONTRACT §6 验收对照（最终）

| # | 验收标准 | 结论 | 证据 |
|---|---|---|---|
| 1 | 自然语言→LLM 多轮工具调用→规划→安全校验→仿真执行→遥测/照片回传，全程可复现 | **通过**（真实 LLM 3 场景） | §6.2 表；`demo/runs/20261108_220309_P1/` 等；`python -m orchestrator.run_demo` 一条命令复现 |
| 2 | ≥3 正向 + ≥5 对抗被安全层正确处理 | **通过**（3 正向真实 LLM + 10 对抗全部正确） | §6.3 表；`tests/safety` 45 tests；`logs/lead/acceptance_*.md` 27/27 |
| 3 | 完整任务审计 JSONL + transcript + 指标 | **通过** | `demo/runs/<run_id>/agent_audit.jsonl`、`llm_events.jsonl`、`metrics.json`；§6.4 |
| 4 | UE5 按 mission 渲染 ≥12 图 + metadata（可接 3DGS） | **通过**（16 帧样例 + 20 帧真实 LLM 任务） | §6.5；`data/synthetic/mission{,_p1}/`；`validation*.json`；pipeline 加载验证 |
| 5 | MSDK v5 桥接口映射 + 真机测试协议 + 代码骨架可审阅 | **通过（设计层，未真机）** | `llm_drone/msdk_bridge/`；§6.6 边界声明 |

### 6.8 与"完美验收"的差距（如实列出）

1. **真实 LLM 的成功依赖工程化辅助**：`qwen3.5:4b` 多步执行不稳定，P1–P3 的 PASS 依赖 `num_ctx` 设置 + 阶段感知续跑提醒 + 只读熔断；换更大模型可减少辅助，但本轮未系统评测。
2. **A6–A10 为脚本化直调**：不是真实 LLM 触发（故障注入类场景改造大且 4B 模型在无提示下不会主动制造违规）；但 Agent 单测与 Lead 黑盒验收均独立覆盖这些错误码。
3. **真机零执行**：MSDK 桥未编译、KMZ 未真机验证；Phase-2 需按 `test_protocol.md` 分层测试。
4. **UE5 渲染的是仿真场景**，不是真机照片；其价值是证明"Mission → 相机位姿 → 图像 + 元数据 → 3DGS"链路契约正确。

---
## 7. 与上游 3DGS/UE5 流水线的闭环

本阶段的"任务"不是孤立 demo，而是上游采集链路的自动化入口。闭环链路：

```
自然语言任务
  → LLM tool-call 规划（Mission JSON：航点/高度/云台/重叠率）
  → SafetyValidator 校验 → 执行（Phase-1 仿真 / Phase-2 MSDK 真机）
  → 照片 + 元数据（c2w / GPS / 云台 / 时间戳）
  → （Phase-1）UE5 虚拟相机按同一 Mission 渲染 PNG + metadata.json
  → （Phase-2）真机 XMP/EXIF → dji_exif_to_colmap.py → COLMAP → 3DGS 训练 → UE5 渲染
```

已实测的兼容性证据：

1. **Mission JSON → UE5**：`ue5_mission` 消费 `spec/sample_mission.json` 渲染 16 帧（见 §5.5），c2w 与 capture 工具数学一致（`c2w_max_diff_vs_capture=0.0`）；
2. **UE5 产物 → 3DGS 流水线**：用上游 `pipeline/.venv` 的 `dataset.load_dataset("data/synthetic/mission")` 实测成功加载：`kind=conventions, views=16`，每视角含 `K / R_cw / c2w_ue / gimbal / gps / image(1200×1600×3)`，与既有训练脚本的数据契约完全一致；
3. **仿真任务照片记录**：`photos_metadata.json` 采用同一 `metadata.json` 格式（frames + c2w + gps + gimbal_deg + timestamp），Phase-2 真机照片只需替换图像来源与 EXIF 提取路径，训练侧零改动。

因此，**"LLM 说一句话 → 无人机拍一组照片 → 3DGS 重建 → UE5 查看"** 的整条链路在仿真/UE5 域已可复现；真机段待 Phase-2 接入。

### 7.1 Lead 独立闭环实测（本轮，2026-11-08 晚）

为验证“不是纸面闭环”，Lead 独立跑了一次完整闭环（不依赖 Agent 自述）：

| 步骤 | 实测 | 证据 |
|---|---|---|
| ① LLM 规划任务 | 真实 Ollama `qwen3.5:4b` 正确调用 `plan_capture_mission`，参数与自然语言一致（grid / 39.9042,116.4074 / 120m / 40m / 75% / -45°），5.3 s | `llm_drone/docs/lead_llm_probe.py` 输出 |
| ② 任务 → UE5 渲染 | 真实 LLM 任务（91 航点）→ UE5.8 虚拟无人机渲染 **91 训练帧 + 9 验证帧** @1600×1200，亮度均值 0.648，c2w 正交误差 ≤1.1e-16 | `data/synthetic/mission_llm/`（metadata.json 91 帧） |
| ③ 渲染 → 3DGS 训练 | 上游流水线训练 **1,200 iter**：23,200 splat，train PSNR **15.60**、held-out val PSNR **11.32 / SSIM 0.333**，143 s，峰值显存 **950 MB** | `data/trained/mission_llm/run1/{metrics.json, gaussians_best.ply, renders/}` |
| ④ 质量结论 | 13 次更新/视图 → 欠训练（画面对比明显模糊）；**链路正确性成立，质量受算力/时间限制**，与上一阶段 3DGS 结论一致 | `renders/gt_000.png` vs `renders/val_000.png` |

> 该闭环证明：**“LLM 规划 → 安全校验 → 虚拟无人机航拍 → 3DGS 重建”可在本机全自动复现**；生产画质需 16–24 GB GPU + 3 万 iter 级训练预算（见 §8.3）。

---

## 8. 风险、合规与限制

### 8.1 技术风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| 小模型工具调用不稳定 | 4B 模型复杂指令下可能选错工具/漏字段/多轮后丢上下文 | 工具描述约束使用时机；plan_id 句柄减少大参数；结构化错误回灌自我纠正；12 轮上限；失败重试与 transcript 保留；可换更大模型（接口兼容 OpenAI） |
| LLM 延迟 | 本机单轮 4–13 s，影响交互体验 | 只读工具免确认；长任务异步轮询；后续可换本地更大模型/在线 API |
| 仿真-真机差异 | 仿真无风/无图传延迟/无 RTK 误差，真机航点执行有转弯半径、断点续飞不保证 | Phase-2 真机协议分层测试（拆桨→空旷场地→弱风→实际场景）；保守速度/高度；照片位姿以 COLMAP 精化 |
| 平台约束 | MSDK v5 仅 Android；Mini 4 Pro 需 RC-N2/N3；带屏 RC 2 不支持 | 设备清单写入真机协议；选型时就锁定 Android 手机 |
| 真机未验证 | 本轮无硬件，桥代码未编译 | 明确标注边界；Phase-2 首日跑通"连接/遥测/起飞-降落"再扩展 |
| 坐标系与时间同步 | 真机照片 EXIF/XMP 与任务记录需对齐 | 以任务时间戳 + 文件名序号双索引；c2w 由 COLMAP 精化后回写 |
| 媒体下载 | 图传链路带宽有限，大文件下载慢 | 任务结束统一批量下载；或落地后 USB 导出，元数据仍以任务记录为准 |

### 8.2 安全与合规风险

| 风险 | 缓解 |
|---|---|
| LLM 幻觉/提示注入产生越界指令 | 确定性 SafetyValidator（Agent 侧二次校验）+ 白名单 + Schema + 二次确认；LLM 无法关闭 |
| 误触发飞行 | 飞行命令必须 confirm；规划与执行两步；演示/真机均需人工在场确认；abort 任何状态可用 |
| 网络攻击面 | Agent 仅绑定 127.0.0.1（真机 App 内嵌 HTTP 亦仅限本机/受控网络）；命令白名单 + 签名校验可作为 Phase-3 增强 |
| 审计缺失 | 审计 JSONL 不可关闭；命令/拒绝/强制返航全部留痕 |
| 空域合规 | 真机测试须在合法空域、限高 120 m 内、目视范围；遵守《无人驾驶航空器飞行管理暂行条例》等当地法规，提前报备 |
| 产品条款 | 不修改固件、不绕过地理围栏/限高/限速；不使用逆向工具控制飞机（DJI 产品条款 2024-07-12 版禁止） |
| 隐私 | 航拍涉及地面人员/建筑：选择非敏感区域、必要时打码/脱敏，遵守个人信息保护相关法规 |

### 8.3 明确未完成 / 未验证项

1. **真机**：未连接 Mini 4 Pro、未编译 APK、未执行真机测试协议 —— 这是 Phase-2 的工作，本轮只交付设计与可审阅骨架；
2. **大模型泛化**：仅验证 qwen3.5:4b（本机资源约束）；更强模型的成功率/延迟未测；
3. **多机/云端**：单机本地调度，未涉及集群与上云 API（Mini 系列也不支持上云 API）；
4. **断点续飞/动态重规划**：Mini 系列官方不保证断点续飞；任务失败后的动态重规划未实现（abort 后需重新规划）；
5. **视觉闭环**：当前 open-loop（按航点+固定云台），未接入图传做目标检测/在线构图优化。

---

## 9. 路线图

| 阶段 | 目标 | 关键工作 | 验收 |
|---|---|---|---|
| Phase-1（本轮） | 仿真 + UE5 全链路可复现 | LLM 工具循环、安全层、仿真后端、UE5 渲染、MSDK 桥设计 | CONTRACT §6 五条 |
| Phase-2（真机，建议 1–2 周） | 单机真机自动航拍 | 采购 Mini 4 Pro + RC-N2/N3 + Android 手机；App 编译（App Key/arm64）；按 `test_protocol.md` 分层测试：连接→遥测→拆桨 motor 检查→空旷场地起降→小网格航点→拍照→媒体下载→低电量 RTH→中断/复飞；替换 Orchestrator 的 `--agent-url` 为手机桥地址 | 真机安全执行 3 个正向场景 + 5 个对抗（人为注入低电量/断链）+ 照片元数据进 COLMAP |
| Phase-3（工程化） | 生产可用 | 多机管理、任务模板库、更大模型/在线 API、图传视觉闭环、审计入库、权限与密钥管理、空域数据接入 | 连续任务成功率 ≥95%、零安全违规、数据自动入库 |

Phase-2 关键里程碑（真机首日建议顺序）：

1. App 注册/初始化/连接成功（`onRegisterSuccess` + `onProductConnect`）；
2. 遥测 10 Hz 上报与 `/v1/telemetry` 字段对齐；
3. 拆桨/电机测试 + 急停验证；
4. 空旷场地：起飞 2 m → 悬停 → 降落；起飞 → 返航；
5. 航点：3 点小航线 → 拍照 → 媒体下载 → 元数据；
6. 故障注入：低电量强制 RTH、遥控断链（关遥控器/拔线）、abort；
7. 3DGS 采集：校园/园区网格 ≥50 张 + 五向倾斜 → COLMAP → 训练。

---

## 10. 复现与验收

### 10.1 环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | Windows 11（本项目实测）；Linux/macOS 可跑 sim/orchestrator（纯 stdlib） |
| Python | 3.14.6（系统；orchestrator/sim/tests 仅标准库）；UE5 内 Python 3.11.8 |
| LLM | 本机 Ollama + `qwen3.5:4b`（或任意 OpenAI 兼容 API） |
| UE5 | 5.8.4（渲染需 GPU；ASCII junction `C:\UEW`） |
| 真机（Phase-2） | DJI Mini 4 Pro + RC-N2/N3 + Android 手机（Android 10+，arm64） |

### 10.2 一键复现命令

```powershell
cd dji_ue5_3dgs\llm_drone

# 1) 启动仿真 Drone Agent（127.0.0.1:8765，20 倍时间加速）
python -m sim.server --port 8765 --time-scale 20

# 2) 跑全部演示场景（真实 LLM）：P1/P2/P3 + A1-A10
python -m orchestrator.run_demo --agent-url http://127.0.0.1:8765 --scenario all --out demo/runs

# 3) 单测（sim / safety / orchestrator）
python -m unittest discover -s tests -v

# 4) Lead 独立黑盒验收（不 import 被测代码）
python logs\lead\verify_acceptance.py --port 8766

# 5) UE5 渲染 Mission JSON → PNG + metadata（ASCII 路径 + 独立 GPU）
powershell -ExecutionPolicy Bypass -File ue5_mission\run_mission.ps1 -Mission spec\sample_mission.json -Out ..\data\synthetic\mission
python ue5_mission\validate_output.py --out ..\data\synthetic\mission

# 6) 接上游 3DGS（示例，复用既有流水线）
cd .. && pipeline\.venv\Scripts\python.exe pipeline\03_train_3dgs.py --data data\synthetic\mission --out data\trained\mission\run1 --iters 1500 --res-scale 0.4
```

### 10.3 CONTRACT §6 验收对照

| # | 验收标准 | 证据（本轮） | 结论 |
|---|---|---|---|
| 1 | 自然语言→LLM 多轮工具调用→规划→安全校验→仿真执行→遥测/照片回传，全程可复现 | `llm_drone/docs/LLM调度无人机方案与验证报告.md` §6.2；`demo/runs/<run_id>/transcript.md`；`run_demo` 一条命令复现 | 见 §6 |
| 2 | ≥3 正向 + ≥5 对抗被安全层正确处理 | §6.2/§6.3 表格 + `tests/safety` + `logs/lead/acceptance_*.md`（27/27） | 见 §6 |
| 3 | 完整任务审计 JSONL + transcript + 指标 | `demo/runs/<run_id>/agent_audit.jsonl`、`llm_events.jsonl`、`metrics.json`；`logs/drone-sim/*.jsonl` | 见 §6 |
| 4 | UE5 按 mission 渲染 ≥12 图 + metadata（可接 3DGS） | `data/synthetic/mission/`（16 帧 + metadata.json）；`ue5_mission/results/validation.json`；pipeline 加载验证 | 见 §6 |
| 5 | MSDK v5 桥接口映射 + 真机测试协议 + 代码骨架可审阅 | `llm_drone/msdk_bridge/{README.md,DESIGN.md,app/,mapping.json,PROTOCOL_COMPLIANCE.md,test_protocol.md}` | 见 §6 |

---

## 11. 附录

### 11.1 主要交付物索引

| 类别 | 路径 | 说明 |
|---|---|---|
| 本报告 | `llm_drone/docs/LLM调度无人机方案与验证报告.md` | 方案 + Phase-1 验证 |
| 任务契约 | `llm_drone/docs/CONTRACT.md` | 架构/工具/安全/验收定义 |
| 冻结规格 | `llm_drone/spec/{PROTOCOL.md,tools.json,sample_mission.json}` | 实现唯一事实源 |
| SDK 使用方法 | `docs/research/08`（MSDK v5）、`09`（v4/Mini2）、`10`（KMZ/WPML）、`01`（能力矩阵） | 带来源的代码级调研 |
| LLM 调度实现 | `llm_drone/orchestrator/`、`sim/`、`safety/` | 可运行代码 |
| 演示证据 | `llm_drone/demo/runs/<run_id>/` | transcript/审计/metrics |
| 安全测试 | `llm_drone/tests/sim/`、`tests/safety/`、`logs/lead/acceptance_*` | 单测 + 黑盒验收 |
| UE5 航拍渲染 | `llm_drone/ue5_mission/`、`data/synthetic/mission/` | Mission→PNG+metadata |
| MSDK 桥 | `llm_drone/msdk_bridge/` | 设计 + Kotlin 骨架 + 真机协议 |
| 上游衔接 | `shared/CONVENTIONS.md`、`pipeline/`、`capture/` | 数据契约与 3DGS/UE5 |

### 11.2 术语

| 术语 | 含义 |
|---|---|
| MSDK | DJI Mobile SDK（v4/v5，移动端 App 控制飞机） |
| WPML/KMZ | DJI 航线格式（waylines + template，zip 打包为 KMZ） |
| Mission JSON | 本项目统一任务格式（`llm_drone.mission/v1`），WGS84 航点 + 相机动作 |
| Drone Agent | 安全层 + 执行后端（仿真或 MSDK 桥） |
| SafetyValidator | 确定性安全校验器（限高/限速/围栏/禁飞区/电量/GPS/链路/confirm/白名单/Schema） |
| c2w | camera-to-world 4×4 矩阵（行主序，列 = forward/right/up 相机轴在 UE 世界 cm） |
| 3DGS | 3D Gaussian Splatting（本工程上游重建算法） |

### 11.3 参考来源

- DJI 官方 SDK 兼容性总表：https://support.dji.com/help/content?customId=01700000763&spaceId=17&re=CN&lang=zh-CN
- DJI MSDK v5 产品页：https://developer.dji.com/mobile-sdk/ ；官方教程站：https://developer.dji.com/doc/mobile-sdk-tutorial/en/
- DJI 官方 GitHub：https://github.com/dji-sdk/Mobile-SDK-Android-V5
- DJI Fly 航点帮助：https://support.dji.com/help/content?customId=01700007343&spaceId=17&lang=zh-CN
- DJI 飞行器产品使用条款（2024-07-12）：https://www.dji.com/cn/terms
- 上游调研（带本地证据索引）：`docs/research/01`、`08`、`09`、`10`、`references.md`

---

*报告由 Team Lead 汇总；所有数字均可在对应日志/JSON 中复核。*



