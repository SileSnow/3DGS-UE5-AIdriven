# msdk-bridge SUMMARY（task-3：MSDK v5 桥设计 + Android 骨架 + 映射 + 真机协议）

> 完成时间：2026-11-08（断电恢复后收尾）。环境事实：本机无 Android Studio、无 Android SDK（ANDROID_HOME 为空）、JDK 21、**无 DJI 真机/遥控器**。
> 因此本任务**未编译、未安装、未真机飞行**；所有"已验证"仅指 MSDK v5 类/方法/回调来自官方一手资料，不是运行结果。

## 1. 交付文件清单

| 文件 | 内容 | 状态 |
|---|---|---|
| llm_drone/msdk_bridge/README.md | 总览：架构数据流、与 sim 同构 HTTP 契约、Android 组件、构建部署、已验证/未验证边界表、限制、风险合规 | 完成（约 1.15 万字符） |
| llm_drone/msdk_bridge/DESIGN.md | 详细设计：线程模型、遥测管线、KMZ 字段对照、失败降级总表、验证策略 | 完成（恢复后已与 app/ 实际文件对齐） |
| llm_drone/msdk_bridge/LIMITS.md | 能力边界：平台硬限制、飞行/相机/媒体边界、合规（配套 DESIGN） | 完成 |
| llm_drone/msdk_bridge/REAL_DRONE_TEST.md | 真机验证协议：通过标准、应急方案、硬件/账号/环境前置（与 test_protocol.md 互补） | 完成（本轮未执行） |
| llm_drone/msdk_bridge/PROTOCOL_COMPLIANCE.md | 与 spec v1.0 逐条对照：8 端点、15 工具、21 错误码、real 模式 E_NOT_SUPPORTED、3 处待确认差异、5 项未实现 | 完成 |
| llm_drone/msdk_bridge/test_protocol.md | 真机测试协议：安全总则、11 项前置条件、24 个用例（C/F/W/R/A/L）、记录模板、异常处置、T0-T4 门禁、留档复盘 | 完成（明确标注本轮未执行） |
| llm_drone/msdk_bridge/mapping.json | 工具→MSDK v5 类/方法/回调 + 官方来源 S1-S20 + 状态（verified-from-docs/unverified）+ 端点映射 + 错误映射 | 完成，python json.load 校验通过 |
| llm_drone/msdk_bridge/evidence/API_SYMBOLS_VERIFIED.md | 5.20.1 Maven 构件符号扫描（E1/E2）+ 官方 sample（E3）+ 依赖坐标（E4）+ Release Notes（E5） | 完成 |
| llm_drone/msdk_bridge/app/ | Gradle KTS x4 + Manifest + 资源 + 24 个 Kotlin 源文件（入口/MSDK/桥接/飞行/任务/相机/云台/媒体/安全/DTO） | 完成骨架，未编译 |
| llm_drone/logs/msdk-bridge/SUMMARY.md | 本文件 | 完成 |

## 2. 关键设计决策

1. **三段式与职责边界**：LLM 只产出工具调用；Orchestrator 负责规划（plan_capture_mission/orbit）与对话；桥接层只执行 13 个 agent 工具并回传遥测/任务记录。plan_id 必须由 Orchestrator 展开为 mission/waypoints 后才进入桥接层（仅 plan_id 返回 E_SCHEMA）。
2. **同构 HTTP 契约**：桥接层实现 spec §3.2 前 6 个端点；/v1/reset、/v1/sim/config 返回 E_NOT_SUPPORTED；/v1/health 返回 backend="msdk"、mode="real"、time_scale=1.0。
3. **飞行命令异步接受**：安全校验通过即返回 state（taking_off/mission/landing/returning），后台协程执行；满足 Orchestrator 单请求 10s 超时，进度靠 /v1/telemetry 与 /v1/missions/{id} 轮询。低风险动作（云台/拍照/录像）同样异步接受。
4. **mission 执行 = KMZ/WPML 航点任务**：mission JSON → MissionKmzBuilder 生成 KMZ（wpmz/template.kml + waylines.wpml）→ WaypointMissionManager.pushKMZFileToAircraft → getAvailableWaylineIDs → startMission；断点续飞官方只保证 M30/M3E 系列，不依赖。
5. **takeoff 到指定高度**：MSDK KeyStartTakeoff 无高度参数 → 先自动起飞，再虚拟摇杆 advanced mode 垂直爬升（10Hz，官方建议 5–25Hz），到点关闭虚拟摇杆悬停。
6. **设备端 SafetyGuard 权威**：严格按 spec §4 顺序（schema→whitelist→mode→confirm→state→battery→gps→rc→范围→围栏→禁飞区→返航能量），并附加 Phase2 就绪检查（MSDK 注册/产品与 RC 连接/机型白名单 Mini 4 Pro）。
7. **照片对账与位姿**：real 模式无 UE 真值，photos[].c2w 由计划航点+云台角按 spec §7.2 推算（estimated）；文件名从 MediaDataCenter 列表按时间回填；原图经 MediaDownloader 下载到 App external files dir，adb pull 回收供 3DGS。
8. **默认只绑定 127.0.0.1**：桥接 HTTP 无鉴权，避免暴露局域网；双机/token/WS 属设计预留（DESIGN.md）。
9. **审计不可关闭**：所有命令/拒绝/安全检查写 JSONL（App external files dir），并可用 /v1/audit?since_seq 增量拉取；已知偏差：real 模式 /v1/reset 不可用→审计固定 audit_default.jsonl（PROTOCOL_COMPLIANCE §5.3）。
10. **静态证据优先**：API 名称来自 developer.dji.com API Reference、官方 GitHub sample、Maven Central 5.20.1 构件符号扫描（evidence/API_SYMBOLS_VERIFIED.md），不依赖记忆或二手博客。

## 3. 本轮自查命令与输出（可复现）

```text
# 1) mapping.json JSON 合法性 + 工具覆盖（python 3.14.6 系统 python）
python -c "import json;d=json.load(open('llm_drone/msdk_bridge/mapping.json',encoding='utf-8'));t=json.load(open('llm_drone/spec/tools.json',encoding='utf-8'));names=[x['name'] for x in d['tools']];missing=[x['name'] for x in t['tools'] if x['name'] not in names];print('mapping tools=',len(names),'spec tools=',len(t['tools']),'missing=',missing)"

# 2) 交付文件存在性
Get-ChildItem -Recurse -File llm_drone/msdk_bridge | Measure-Object

# 3) TODO(未确认) 统计（诚实标注未验证点）
Select-String -Path llm_drone/msdk_bridge/app/**/*.kt -Pattern 'TODO\(未确认\)' | Measure-Object
```

本轮实跑输出（2026-11-08 恢复后，PowerShell + python 3.14.6）：

```text
A. python json.load(mapping.json) -> OK；mapping tools=15 / spec tools=15 / missing=[]
B. statuses = [verified-from-docs, unverified, unverified（字段构造待确认）, unverified（构造参数顺序未从文档确认...）]
C. README.md: chinese chars=3115（要求 >=3000）, total chars=14636, lines=158
D. app/ Kotlin 源文件 23 个；TODO(未确认) 标注 20 处（诚实未验证点）
E. 必需文件全部存在：README/PROTOCOL_COMPLIANCE/test_protocol/mapping/DESIGN/LIMITS/REAL_DRONE_TEST/evidence/logs-SUMMARY
F. _tmp_api 临时目录已删除（关键结论保留在 evidence/API_SYMBOLS_VERIFIED.md）
```

## 4. 未决问题 / 风险（真机前必须处理）

1. **KMZ/WPML 可行性（最高风险，T9 已部分处理）**：WaypointConverter.kt 已按 docs/research/10 + 参考生成器 make_sample_kmz.py 重写（template/waylines 必填字段、actionGroup、takeOffSecurityHeight、droneInfo/payloadInfo 占位）；仍未经 Mini 4 Pro 飞控接受验证。真机 T0 必须用官方 WPML 规范或 WPMZManager.checkValidation 静态校验，失败则改用 WPMZManager.generateKMZFile。剩余 TODO：droneEnumValue/payloadEnumValue 官方取值、per-waypoint heading 落地、multipleTiming 支持性、executeHeightMode/EGM96。
2. **代码 API 细节（T9 已修一部分）**：GimbalAngleRotation 已改无参+apply（E1 字段表）；VirtualStickFlightControlParam 已改 value 包并显式控制模式（08 §6.7）；WaypointMissionController 三个 Listener 已改 object 具名方法（08 §6.2）；MediaDownloader 已加 enable()（08 §6.5）；TelemetryPublisher listen 已改双参。仍待编译验证的：Attitude/Velocity3D 构造参数、WaylineExecutingInfo 字段可空性、AirlinkKey/机型 Key 名。
3. **未编译**：本机无 Android SDK；Gradle 依赖（nanohttpd/appcompat/core-ktx）已补，但属性名/语法未经过编译验证。
4. **未实现 spec 项**：飞行中低电量主动 force RTH、真机开关 UI 与 E_MODE、WS 推送、审计 per-run 文件（PROTOCOL_COMPLIANCE §5.4）。
5. **已由 spec v1.1 §15 裁决**：real 模式 sim_time_s 允许 null；photos[].c2w 允许 estimated + pose_source + pose_accuracy_m（3.0m），遥测缺失 c2w=null + unavailable；设备就绪 E_RC_LINK + details.reason（not_registered/not_connected）、机型不符 E_STATE + aircraft_mismatch。代码与文档已对齐。
6. **照片对账**：MediaFile 时间戳字段未核实，当前会取全部非视频文件；真机阶段可能需按 KeyNewlyGeneratedMediaFile 或媒体列表序号匹配。

## 5. 证据 URL 清单（一手）

- MSDK v5 API Reference：https://developer.dji.com/api-reference-v5/android-api/Components/IKeyManager/Key_FlightController_FlightControllerKey.html
- WaypointMissionManager：https://developer.dji.com/api-reference-v5/android-api/Components/IWaypointMissionManager/IWaypointMissionManager.html
- IKeyManager：https://developer.dji.com/api-reference-v5/android-api/Components/IKeyManager/IKeyManager.html
- IMediaManager：https://developer.dji.com/api-reference-v5/android-api/Components/IMediaDataCenter/IMediaManager.html
- IFlyZoneManager：https://developer.dji.com/api-reference-v5/android-api/Components/IFlyZoneManager/IFlyZoneManager.html
- IVirtualStickManager：https://developer.dji.com/api-reference-v5/android-api/Components/IVirtualStickManager/IVirtualStickManager.html
- SDKManager（ISDKManager）：https://developer.dji.com/api-reference-v5/android-api/Components/SDKManager/DJISDKManager.html
- 官方 GitHub sample（V5.20.1）：https://github.com/dji-sdk/Mobile-SDK-Android-V5（raw 关键文件：MSDKManagerVM.kt、WayPointV3VM.kt、MediaVM.kt、VirtualStickVM.kt、BasicAircraftControlVM.kt）
- 官方 README / 依赖坐标：https://raw.githubusercontent.com/dji-sdk/Mobile-SDK-Android-V5/dev-sdk-main/README.md
- Wayline/KMZ 教程：https://developer.dji.com/doc/mobile-sdk-tutorial/en/tutorials/waypoint.html
- WPML 规范：https://developer.dji.com/doc/cloud-api-tutorial/en/api-reference/dji-wpml/overview.html
- 虚拟摇杆教程：https://developer.dji.com/doc/mobile-sdk-tutorial/en/tutorials/virtual-stick.html

## 6. 恢复/交接要点

- spec 已 FROZEN v1.0 + **v1.1 §15 补充决议**（sim_time_s=null、c2w pose_source/pose_accuracy_m、设备就绪 details.reason），PROTOCOL_COMPLIANCE/README/代码已对齐。
- app/ 骨架按包 com.gaia.llmdrone.bridge 组织；DESIGN.md 已加"概念名→实际文件"对照，避免评审混淆。
- 下一阶段（真机）顺序：Android Studio 编译修 API 细节 → WPMZ/KMZ 静态校验 → T0/T1 地面拆桨 → T2 室内 → T3 空旷航点 → T4 故障演练（见 test_protocol.md）。
- 本任务范围内的临时抓取目录 _tmp_api/ 已在收尾时删除（约 4MB 原始 API HTML）；关键结论保留在 evidence/API_SYMBOLS_VERIFIED.md。

## 7. T9 复核结论（2026-11-08，与 docs/research/08、10 交叉核对）

- 新增交付：**llm_drone/msdk_bridge/REVIEW_vs_research.md**（11KB，47 项逐条：一致 24 / 需修正 16 / TODO 7）；mapping.json 升 **v1.1**（sources 22 个含 S21/S22，新增 `research_review` 块，类名统一为 WaypointConverter/TelemetryPublisher/DroneBridgeServer/CommandExecutor）。
- 代码修正（未编译）：①WaypointConverter.kt 按 research/10 逐字段重写并删除重复的 MissionKmzBuilder.kt；②WaypointMissionController 三个 Listener 改 object 具名方法 + KMZ 路径语义；③MissionExecutor 传 kmz.absolutePath 且照片带 pose_source/pose_accuracy_m；④GimbalAngleRotation 无参+apply + createKey 去 componentIndex；⑤FlightController VirtualStickFlightControlParam 改 value 包 + 显式 4 个控制模式；⑥MediaDownloader 增加 IMediaManager.enable()；⑦TelemetryPublisher listen 双参回调。
- 文档修正：README 增 §13 T9 复核结论 + 边界表第 12/13 行 + spec v1.1 表述；PROTOCOL_COMPLIANCE 增 §8 T9 结论；mapping 与文档中的组件名统一。
- 08 文档自身需修正 2 处：ComponentIndexType.CAMERA（与 5.20.1 构件扫描不符，应为 LEFT_OR_MAIN 等）；GimbalAngleRotation 构造写法（以构件字段表为准）。
- 仍存 TODO 7 项（T1-T7）：Mini 4 Pro WPML droneEnum/payload enum、per-waypoint heading 落地、multipleTiming 支持性、executeHeightMode/EGM96、MediaFile 时间戳、AirlinkKey/机型 Key 名、全部 Kotlin 编译与真机行为。
- **诚实边界不变**：本轮仍未编译、未真机；T9 只提高文档/静态一致性。
