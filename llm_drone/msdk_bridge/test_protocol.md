# 真机测试协议（MSDK v5 桥 x DJI Mini 4 Pro）

> **状态：本轮未执行。** 本机无真机/遥控器/Android SDK，本文是「可执行清单」，不是测试结果。
> 执行人须逐项勾选，并在 llm_drone/logs/msdk-bridge/fieldtest_<YYYYMMDD>.md 留档；任一项未通过不得进入下一阶段。
> 期望值以 llm_drone/spec/PROTOCOL.md 为准；错误码见 spec §8.2 与 PROTOCOL_COMPLIANCE §4。

## 0. 安全总则（先读）

1. 空载（不挂载/不改装）、空旷无人群、视距内（VLOS）、风速 <5 m/s、无降水。
2. 起降点远离人群/道路/高压线；操作员手持遥控器，随时可切换手动/一键返航（硬件开关优先级高于 App）。
3. 高度 <=120m（本桥默认限高 120m，且当地法规优先）；全程开启 DJI Fly 的 GEO 提示作为第二参考。
4. 每轮测试前确认 App Key、固件、遥控器电量（RC >=80%）、飞机电量（起飞 >=30%，建议 >=80%）、手机电量 >=50%。
5. 异常立即 abort（悬停）或按遥控器暂停/返航；不以「再试一次」代替排查。
6. 双人制：飞手 + 安全员；任何一人可中止。

## 1. 前置条件清单（全部满足才可开始）

| # | 条件 | 验证方式 | 记录字段 |
|---|---|---|---|
| 1 | DJI 开发者账号 + Android App 已创建，App Key 与包名/签名 SHA256 绑定 | developer.dji.com 控制台截图 | Key 后 4 位 + 包名 |
| 2 | 手机 arm64、Android 10+、USB 调试开、未 root、关闭电池优化 | adb devices、设置截图 | 机型/系统版本 |
| 3 | 遥控器 RC-N2（或 v5.17.0+ 的 RC-N3）；RC/RC 2 带屏不支持 | 遥控器型号铭牌 | 型号 + RC 固件 |
| 4 | 飞机 Mini 4 Pro，机身固件与 MSDK 版本配套（v5.13.0 记录：机身 01.00.0800 / RC-N2 01.01.0300；本项目按 5.20.1 设计） | DJI Fly 固件界面 | 机身/RC 固件号 |
| 5 | 空域：已完成当地报备/许可（如需）、非禁飞区、场地已勘察 | 报备回执/截图 | 空域状态、场地坐标 |
| 6 | App 构建成功并安装；adb forward tcp:8765 tcp:8765 后 curl http://127.0.0.1:8765/v1/health 返回 backend:"msdk" | curl 输出 | health JSON |
| 7 | MSDK 注册成功（App 联网、账号校验通过）；product_connected=true | /v1/health 的 device 字段 | 注册/连接状态 |
| 8 | 电池 >=80%（首飞）、SD 卡剩余 >=16GB、镜头清洁 | 现场检查 | 电量/容量 |
| 9 | 场地围栏/禁飞区参数与 SafetyConfig 一致（默认圆心 39.9042,116.4074 / R=300m） | 现场 GPS 核对 | 围栏参数 |
| 10 | 风速/能见度满足飞行条件 | 风速计/气象 App | 风速/能见度 |
| 11 | KMZ/WPML 已在 T0 阶段通过官方 WPML 规范或 WPMZ SDK 静态校验 | 校验输出日志 | 校验结论 |

## 2. 用例矩阵（步骤 -> 预期 -> 记录 -> 安全护栏）

> 记录字段统一：用例 ID、时间戳、command_id、请求 JSON、响应 JSON、遥测快照、审计 seq 区间、照片文件名、是否通过、备注。

| ID | 用例 | 步骤 | 预期 | 安全护栏 |
|---|---|---|---|---|
| C-01 | 健康检查 | 启动 App -> adb forward -> GET /v1/health | backend=msdk、ok=true、version=0.1.0 | 不涉及飞行 |
| C-02 | 连接/遥测 | GET /v1/telemetry | state=idle、battery_pct 合理、gps.fix>=3、rc.connected=true | 地面 |
| C-03 | preflight | POST command preflight_check | can_fly=true 且 checks 全 pass | 不启动电机 |
| C-04 | 仿真专属端点 | POST /v1/reset、POST /v1/sim/config | E_NOT_SUPPORTED | 地面 |
| F-01 | 起飞 | takeoff {altitude_m:10, confirm:true} | 返回 taking_off；10s 后 telemetry state=hovering、alt_rel_m 约 10 且偏差 <=1m | 手放遥控器暂停键；高度 10m |
| F-02 | 云台 | set_gimbal {pitch_deg:-30} | gimbal.pitch 约 -30 且偏差 <=3 度 | 悬停中 |
| F-03 | 拍照 | capture_photo {count:2,interval_s:1} | 任务记录新增照片文件名；媒体列表出现新文件 | 悬停中 |
| F-04 | 录像 | start_video -> 约 3s -> stop_video | 媒体列表出现 MP4；KeyIsRecording 状态正确 | 悬停中 |
| W-01 | 航点任务（核心） | goto_waypoints {mission: 5 航点/3 拍照点, confirm:true} | mission_id 返回；state=mission；完成后 GET missions/{id} 为 completed、photos 含 3 条 | 航线在围栏内、视距内；先空载试飞 |
| W-02 | 任务中止 | W-01 执行中 abort {reason:"test"} | 任务停止、飞机悬停；mission state=aborted；state=hovering | 手动可接管 |
| R-01 | 返航 | return_to_home | state=returning；GoHomeStatus=RETURNING_TO_HOME；到点降落后 idle | 返航高度 >= 障碍物高度（预检设 GoHomeHeight） |
| R-02 | 降落 | land（空中） | state=landing -> idle，电机停止 | 降落区空旷 |
| A-01 | 超限高 | takeoff {altitude_m:150, confirm:true} | ok=false、E_ALT_LIMIT；无起飞动作 | 地面；不实际飞 |
| A-02 | 飞出围栏 | goto_waypoints 含 800m 外航点 | E_GEOFENCE；飞机不动 | 地面 |
| A-03 | 禁飞区 | 航点位于默认禁飞多边形 | E_NOFLY | 地面 |
| A-04 | 低电量 | 地面等待电量 <30%（或测试模式改阈值）-> takeoff | E_BATTERY_TAKEOFF | 地面；不真飞 |
| A-05 | 无确认 | takeoff 不带 confirm | E_CONFIRM_REQUIRED | 地面 |
| A-06 | 并发 | 任务执行中发 takeoff | E_BUSY | 飞行中只发只读 |
| A-07 | 未知工具 | {"tool":"fly_to_moon"} | E_UNKNOWN_TOOL | 地面 |
| A-08 | 多余参数 | takeoff 带 {"foo":1} | E_SCHEMA | 地面 |
| L-01 | 低电量 RTH（高风险，单独评审） | 飞行中让电量降至 20% 以下（不建议真机做，优先地面配置验证） | 飞控默认低电量 RTH；桥接层审计 force_rth/returning | 仅安全员+开阔场地；优先用 DJI Fly 自身策略验证 |
| L-02 | 链路中断（高风险，单独评审） | 飞行中关闭遥控器/拔手机 | 飞控按 fail-safe RTH；App 记录失联；恢复后重连 | 必须有第二操作员与安全预案；仅空旷场地 |

## 3. 每例执行模板（复制到 fieldtest 文件）

```markdown
### <用例 ID> <名称> — <通过/失败/阻塞>
- 时间：
- 环境：场地/天气/风速/温度
- 请求：<command_id / tool / args / confirm>
- 响应：<完整 JSON>
- 遥测：<关键字段>
- 审计：<seq 区间 / audit 文件>
- 照片：<文件名列表>
- 预期 vs 实际：
- 安全事件：无 / <描述>
- 备注/后续动作：
```

## 4. 异常处置（按优先级）

1. **飞机不响应/行为异常**：立即遥控器接管（暂停/返航），App 侧 abort；不要连续重发命令。
2. **App 崩溃/HTTP 无响应**：遥控器接管返航；重启 App 后先 GET /v1/health 与 telemetry 再操作。
3. **KMZ 上传失败**：stopMission 后按 mapping.json/error 日志排查；不得反复上传同一 KMZ 覆盖。
4. **误判状态**（App 显示 idle 但飞机在飞）：以遥控器与 DJI Fly 显示为准；App 不得作为飞行状态唯一依据。
5. **安全拒绝但用户坚持**：拒绝是设计行为（spec §8），记录审计与原因，不绕过 SafetyGuard。
6. **媒体下载失败**：不阻塞任务完成；记录 download_error，任务后重试 get_mission_status 再下载。

## 5. 阶段门禁（T0 -> T4）

| 阶段 | 内容 | 通过标准 |
|---|---|---|
| T0 离线 | 代码审阅 + spec 对照 + KMZ 静态校验 | PROTOCOL_COMPLIANCE 全绿；KMZ 通过官方校验 |
| T1 地面拆桨 | 上电连接、遥测、云台、拍照、媒体下载、中止演练（不启动电机） | 无异常码；照片落盘；abort 1.5s 内 state 合理 |
| T2 室内悬停 | 5m 悬停 30s、RTH、降落（需教练/安全员） | 高度/速度限内；RTH 完整 |
| T3 空旷场地 | 1 个 2x2 网格任务、4 张照片、自动 RTH | mission completed；照片元数据完整 |
| T4 故障演练 | 低电量/链路丢失/任务中 abort/相机忙 | 按 DESIGN §8 正确处置，审计齐全 |

## 6. 留档与复盘

- 留档：llm_drone/logs/msdk-bridge/fieldtest_<YYYYMMDD>.md + 原始 JSONL（adb pull /sdcard/Android/data/com.gaia.llmdrone.bridge/files/audit/）+ mission record JSON + 照片清单（含文件大小/SHA256）。
- 复盘：逐例统计通过率；记录所有 E_* 实际分布；KMZ 接受性、遥测字段单位、照片对账准确率作为「文档待修正项」回写 README §6。
- **本轮（2026-11-08）未执行任何真机测试**；本文件仅为协议与清单。
