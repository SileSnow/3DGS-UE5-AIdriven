# sdk-docs SUMMARY — T1「DJI Mini 系 SDK 使用方法」调研（task-2）

状态：**完成**（2026-11-08，断电恢复后续写；22:xx 按 Lead 复核反馈修正 08 枚举/构造器与 09 v4 回调，详见 VALIDATION.md 第 5 节）；交付 08/09/10 + assets + 本日志。所有 API 均带「官方 URL + 本地证据」；无一手证据处标 TODO(未确认)。

## 一、三条最关键结论
1. **版本/平台硬约束**：Mini 3 / Mini 3 Pro 自 MSDK **v5.3.0**（2023-04-07）、Mini 4 Pro 自 **v5.13.0**（2025-03-17；RC-N3 自 v5.17.0）获官方支持；MSDK v5 **仅 Android**、最新 **5.20.1**、仅 arm64-v8a；带屏 DJI RC 2 不支持。Mini 2 / Mini SE / Mavic Mini 只能走 **MSDK v4.16+**（Android+iOS）。v4 与 v5 包名/类名/任务模型完全不同，**不能共用代码**（官方迁移文档原文映射）。
2. **v5 编程范式 = Key + KMZ**：`KeyTools` 建 Key、`KeyManager.getValue/setValue/performAction/listen`；飞控/相机/云台/电池都是 Key（如 `FlightControllerKey.KeyStartTakeoff`、`CameraKey.KeyStartShootPhoto`、`GimbalKey.KeyRotateByAngle`）；航线是 KMZ/WPML 文件：`pushKMZFileToAircraft → getAvailableWaylineIDs → startMission → pause/resume/stop`，**断点续飞仅 M30/M3E/3T/3M，Mini 不在列**；初始化 `SDKManager.init(context, InitSettings(SDKLinKMode.LOCAL), cb) → INITIALIZE_COMPLETE → registerApp()`，v5.10.0 起 Helper 包名为 `com.cySdkyc.clx.Helper`。
3. **KMZ/WPML 可完全程序化生成**：`wpmz/template.kml`（全局参数/模板）+ `wpmz/waylines.wpml`（执行航点/动作），namespace `http://www.dji.com/wpmz/1.0.2`；已交付纯 Python 标准库生成器 + 自造最小样例，独立校验通过（6+6 Placemark、takePhoto/gimbalRotate、executeHeight=40、index 0–5）。

## 二、文件清单
- `docs/research/08_MSDKv5_Android使用方法.md`（41.0K 字符 / 4471 汉字，15 节：环境与 Maven、App Key、初始化状态机、RC-N2/N3 USB、10 模块 API 表 + Kotlin 代码、常见坑、llm_drone 工具映射、证据索引、TODO、实施清单、能力边界、安全阈值、合规、FAQ）
- `docs/research/09_MSDKv4_使用方法与Mini2链路.md`（24.1K 字符 / 3120 汉字：v4.16→4.18 时间轴、Maven、注册/连接、FlightController、WaypointMissionOperator、iOS 差异、v4/v5 不可共用代码对照、Mini 2 采集 SOP、取舍、常见坑、TODO）
- `docs/research/10_KMZ_WPML航线格式与任务下发.md`（24.7K 字符 / 3258 汉字：结构、template/waylines 字段表、action 全集、上传-执行状态机、错误面、断点续飞限制、DJI Fly 对比、12 项自检、mission JSON→WPML 映射、样例与真实校验输出）
- `docs/research/assets/make_sample_kmz.py`（stdlib，10.7KB）、`docs/research/assets/sample_mission.kmz`（2,972B，校验 OK）
- 新抓一手证据：`data/dji/raw/api_v5/`（47 文件，其中 40 个 API Reference HTML + repo_README.md）、`data/dji/raw/msdkv5_sample/`（官方 Sample 19 文件）、`data/dji/raw/msdkv5_docs_extracted/`（101 个官方教程正文 chunk）、`data/dji/raw/cloudapi/text/`（WPML 4 页正文+XML 样例）、`data/dji/raw/api_v4/`（v4 API/文档 6 页 + README）

## 三、未决问题（不凑数，均已在正文标 TODO）
1. Mini 4 Pro 的 WPML `droneEnumValue/payloadEnumValue` 官方文档未给（样例用 0 占位，禁止直接真机）。
2. `CameraISO/CameraShutterSpeed/GimbalAngleRotation/PhotoIntervalShootSettings` 构造器与枚举字段需补抓 Value_* API 页核对。
3. Mini 系对 KMZ `multipleTiming/multipleDistance` 等距/等时拍照、`EGM96` 高程、速度上限：官方支持列表未含 Mini，需真机验证。
4. 航线失败错误码：官方无全量表，需真机抓 `IDJIError.errorCode/description` 建映射（CONTRACT §8.2 错误码对齐）。
5. App Key 与签名证书指纹绑定规则无官方明文。

## 四、证据索引（本地）
- v5 教程站（VuePress SPA，正文已提取）：`data/dji/raw/msdkv5_docs_extracted/`；官方 URL：https://developer.dji.com/doc/mobile-sdk-tutorial/en/
- v5 API Reference：https://developer.dji.com/api-reference-v5/android-api/ → `data/dji/raw/api_v5/`
- 官方仓库（经 cdn.jsdelivr.net）：https://github.com/dji-sdk/Mobile-SDK-Android-V5 → `repo_README.md` + `msdkv5_sample/`
- WPML 官方文档：https://developer.dji.com/doc/cloud-api-tutorial/en/api-reference/dji-wpml/ → `data/dji/raw/cloudapi/text/`
- v4：https://github.com/dji-sdk/Mobile-SDK-Android 、https://developer.dji.com/api-reference/android-api/ → `data/dji/raw/api_v4/`
- Release Notes（Mini 3/4 Pro、RC N3、固件表）：`data/dji/raw/text/relnotes_all.txt`
- 校验记录：`llm_drone/logs/sdk-docs/VALIDATION.md`
