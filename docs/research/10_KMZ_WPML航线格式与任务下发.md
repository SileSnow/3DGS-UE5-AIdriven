# 10 KMZ / WPML 航线格式与任务下发（Mini 3 / 3 Pro / 4 Pro）

> 调研日期：2026-11-08（Asia/Shanghai，断电恢复后续写）。目标：让本项目能**自己生成 KMZ**（不依赖 DJI Pilot 手工画航线），通过 MSDK v5 下发给 Mini 系飞机执行，并清楚知道格式边界、状态机、错误面与断点续飞限制。
> 一手来源：DJI Cloud API 官方文档 WPML 章节（https://developer.dji.com/doc/cloud-api-tutorial/en/api-reference/dji-wpml/overview.html ，SPA 正文经站点 JS chunk 提取，本地 `data/dji/raw/cloudapi/text/`）；MSDK v5 API Reference（`data/dji/raw/api_v5/`）；官方 Sample（`data/dji/raw/msdkv5_sample/`）。

## 0. 一页速查

| 项 | 结论 |
|---|---|
| 什么是 WPML | WayPoint Markup Language，DJI 公开的航线文件格式标准，基于 KML 扩展 |
| 文件形态 | `.kmz` = ZIP 归档；解压后必须有 `wpmz/template.kml`、`wpmz/waylines.wpml`，可选 `wpmz/res/`（辅助资源） |
| template.kml | "模板文件"：业务属性/全局参数，便于人快速编辑（如测绘模板只需区域+重叠率） |
| waylines.wpml | "执行文件"：明确的飞行与负载动作指令，飞机直接执行 |
| 命名硬约束 | KMZ 包名 = 航线名；内部 `wpmz`、`template.kml`、`waylines.wpml` 名称与层级不可改，否则读取失败 |
| 命名空间 | `xmlns:wpml="http://www.dji.com/wpmz/1.0.2"` |
| 下发链路 | KMZ 文件 → `WaypointMissionManager.pushKMZFileToAircraft()` → `getAvailableWaylineIDs()` → `startMission(kmzPath, waylineIds)` |
| 断点续飞 | 官方只保证 Matrice 30/30T、Mavic 3E/3T/3M；**Mini 系不在列** |
| 与 DJI Fly 航点 | 两套体系：DJI Fly 的航点存于 App/机内、不支持 KML 导入；MSDK 走 KMZ 文件。不能直接把 DJI Fly 航点导出成 WPML |

## 1. 格式总览

官方原文（overview 页）：
- "WPML 航线文件均以 '.kmz' 后缀结尾，实质是使用 ZIP 格式打包的归档文件。"
- 解压后结构：`template.kml`（模板文件）、`waylines.wpml`（执行文件）、`res` 资源文件夹（如精准复拍的参考目标物照片）。
- "template.kml 定义业务属性，方便用户进行快速调整编辑。waylines.wpml 定义执行细节。res 文件夹存储辅助资源文件。"
- 注意："航线文件内部各文件或文件夹的命名请遵循此规范，否则可能导致航线文件读取失败。航线名称即航线文件的文件名。如 new_waypoints.kmz 的航线名称是 new_waypoints。"

结构示意（与官方图示一致）：

```
waypoints_name.kmz                # 包名即航线名
└── wpmz/
    ├── template.kml              # 模板：全局参数 + 航点模板定义
    ├── waylines.wpml             # 执行：每条可执行航线的航点/动作
    └── res/                      # 可选：辅助资源（照片等）
```

证据：`data/dji/raw/cloudapi/text/v-7ee37f75.2732d711.js.txt`（overview 中文正文）；`data/dji/raw/text/waypoint.txt`（MSDK 侧同段结构说明）。

## 2. template.kml 结构

官方示例（航点飞行模板，原文照录，`v-26f525b7.ef20ee2f.js.txt` 的代码块）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:wpml="http://www.dji.com/wpmz/1.0.2">
  <Document>
    <wpml:author>Name</wpml:author>
    <wpml:createTime>1637600807044</wpml:createTime>
    <wpml:updateTime>1637600875837</wpml:updateTime>
    <wpml:missionConfig>
      <wpml:flyToWaylineMode>safely</wpml:flyToWaylineMode>
      <wpml:finishAction>goHome</wpml:finishAction>
      <wpml:exitOnRCLost>goContinue</wpml:exitOnRCLost>
      <wpml:executeRCLostAction>hover</wpml:executeRCLostAction>
      <wpml:takeOffSecurityHeight>20</wpml:takeOffSecurityHeight>
      <wpml:takeOffRefPoint>23.98057,115.987663,100</wpml:takeOffRefPoint>
      <wpml:globalTransitionalSpeed>8</wpml:globalTransitionalSpeed>
      <wpml:droneInfo>
        <wpml:droneEnumValue>67</wpml:droneEnumValue>
        <wpml:droneSubEnumValue>0</wpml:droneSubEnumValue>
      </wpml:droneInfo>
      <wpml:payloadInfo>
        <wpml:payloadEnumValue>52</wpml:payloadEnumValue>
        <wpml:payloadPositionIndex>0</wpml:payloadPositionIndex>
      </wpml:payloadInfo>
    </wpml:missionConfig>
    <Folder>
      <wpml:templateType>waypoint</wpml:templateType>
      <wpml:templateId>0</wpml:templateId>
      <wpml:waylineCoordinateSysParam>
        <wpml:coordinateMode>WGS84</wpml:coordinateMode>
        <wpml:heightMode>EGM96</wpml:heightMode>
        <wpml:positioningType>GPS</wpml:positioningType>
      </wpml:waylineCoordinateSysParam>
      <wpml:autoFlightSpeed>7</wpml:autoFlightSpeed>
      <wpml:gimbalPitchMode>usePointSetting</wpml:gimbalPitchMode>
      <wpml:globalWaypointHeadingParam>
        <wpml:waypointHeadingMode>followWayline</wpml:waypointHeadingMode>
      </wpml:globalWaypointHeadingParam>
      <wpml:globalWaypointTurnMode>toPointAndStopWithDiscontinuityCurvature</wpml:globalWaypointTurnMode>
      <wpml:globalUseStraightLine>0</wpml:globalUseStraightLine>
      <Placemark>
        <Point><coordinates>longitude,latitude</coordinates></Point>
        <wpml:index>0</wpml:index>
        <wpml:ellipsoidHeight>90.2</wpml:ellipsoidHeight>
        <wpml:height>100</wpml:height>
        <wpml:useGlobalHeight>1</wpml:useGlobalHeight>
        <wpml:useGlobalSpeed>1</wpml:useGlobalSpeed>
        <wpml:useGlobalHeadingParam>1</wpml:useGlobalHeadingParam>
        <wpml:useGlobalTurnParam>1</wpml:useGlobalTurnParam>
        <wpml:gimbalPitchAngle>0</wpml:gimbalPitchAngle>
      </Placemark>
      <!-- 第 2 个 Placemark 内含 actionGroup，见第 4 节 -->
    </Folder>
  </Document>
</kml>
```

字段要点（官方元素表，节选；完整表见 `data/dji/raw/cloudapi/text/v-26f525b7.ef20ee2f.js.txt`）：

| 元素 | 类型/单位 | 取值与说明 | 必填 |
|---|---|---|---|
| `wpml:author` | 字符串 | 创建作者 | 否 |
| `wpml:createTime` / `updateTime` | 整型 ms | Unix 时间戳（毫秒） | 否 |
| `wpml:flyToWaylineMode` | 枚举 | `safely`（安全起飞到航线）/其它 | 是（示例值 safely） |
| `wpml:finishAction` | 枚举 | `goHome` 返航 / `noAction` 等 | 是 |
| `wpml:exitOnRCLost` / `executeRCLostAction` | 枚举 | 失联策略；示例 `goContinue`+`hover` | 是 |
| `wpml:takeOffSecurityHeight` | 浮点 m | 起飞安全高度 | 是 |
| `wpml:globalTransitionalSpeed` | 浮点 m/s | 全局过渡速度 | 是 |
| `wpml:droneInfo.droneEnumValue` | 整型 | 机型枚举（示例 M30=67） | 是 |
| `wpml:payloadInfo.payloadEnumValue` | 整型 | 负载枚举（示例 M30 负载=52） | 是 |
| `wpml:templateType` | 枚举-string | `waypoint` / `mapping2d` / `mapping3d` / `mappingStrip` | 是 |
| `wpml:templateId` | 整型 [0,65535] | 模板 ID；template 与 waylines 用它关联 | 是 |
| `wpml:autoFlightSpeed` | 浮点 m/s [1,15] | 全局航线速度，可被航点局部覆盖 | 是 |
| `wpml:waylineCoordinateSysParam.coordinateMode` | 枚举 | 固定 `WGS84` | 是 |
| `wpml:heightMode` | 枚举 | `EGM96` 海拔 / `relativeToStartPoint` 相对起飞点 / `aboveGroundLevel`（司空2） / `realTimeFollowSurface`（仿地，仅 M3E 系） | 是 |
| `wpml:autoFlightSpeed` 等 | — | 见上行 | — |
| `Folder` | — | 航点飞行模板的全局元素 | 是 |
| `wpml:globalWaypointTurnMode` | 枚举 | `coordinateTurn` / `toPointAndStopWithDiscontinuityCurvature` / `toPointAndStopWithContinuityCurvature` / `toPointAndPassWithContinuityCurvature` | 是 |
| `wpml:globalUseStraightLine` | 0/1 | 航段是否贴合直线（弯转模式为连续性时必需） | 条件 |
| `wpml:gimbalPitchMode` | 枚举 | `manual` / `usePointSetting` | 是 |
| `wpml:globalHeight` | 浮点 m | 全局航线高度（相对起飞点） | 是（模板） |
| `Placemark/Point/coordinates` | 经度,纬度 | 航点位置（WGS84） | 是 |
| `wpml:index` | 整型 [0,65535] | 航点序号，必须从 0 连续递增 | 是 |
| `wpml:ellipsoidHeight` / `wpml:height` | 浮点 m | 同一位置在不同高程基准下的表达；relative 模式下二者相同 | 条件 |
| `wpml:useGlobalHeight` | 0/1 | 航点高度是否用全局 | 是 |
| `wpml:useGlobalSpeed` | 0/1 | 航点速度是否用全局 | 是 |
| `wpml:waypointSpeed` | 浮点 m/s [1,15] | useGlobalSpeed=0 时必需 | 条件 |
| `wpml:useGlobalHeadingParam` | 0/1 | 偏航角模式是否用全局 | 是 |
| `wpml:useGlobalTurnParam` | 0/1 | 转弯模式是否用全局 | 是 |
| `wpml:gimbalPitchAngle` | 浮点 ° | gimbalPitchMode=usePointSetting 时必需 | 条件 |

## 3. waylines.wpml 结构

官方示例（原文照录，`v-46bb6ba2.c911fcd4.js.txt`）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:wpml="http://www.dji.com/wpmz/1.0.2">
  <Document>
    <wpml:missionConfig>
      <wpml:flyToWaylineMode>safely</wpml:flyToWaylineMode>
      <wpml:finishAction>goHome</wpml:finishAction>
      <wpml:exitOnRCLost>goContinue</wpml:exitOnRCLost>
      <wpml:executeRCLostAction>hover</wpml:executeRCLostAction>
      <wpml:takeOffSecurityHeight>20</wpml:takeOffSecurityHeight>
      <wpml:globalTransitionalSpeed>10</wpml:globalTransitionalSpeed>
      <wpml:droneInfo><wpml:droneEnumValue>67</wpml:droneEnumValue><wpml:droneSubEnumValue>0</wpml:droneSubEnumValue></wpml:droneInfo>
      <wpml:payloadInfo><wpml:payloadEnumValue>52</wpml:payloadEnumValue><wpml:payloadPositionIndex>0</wpml:payloadPositionIndex></wpml:payloadInfo>
    </wpml:missionConfig>
    <Folder>
      <wpml:templateId>0</wpml:templateId>
      <wpml:executeHeightMode>WGS84</wpml:executeHeightMode>
      <wpml:waylineId>0</wpml:waylineId>
      <wpml:autoFlightSpeed>10</wpml:autoFlightSpeed>
      <Placemark>
        <Point><coordinates>longitude,latitude</coordinates></Point>
        <wpml:index>0</wpml:index>
        <wpml:executeHeight>116.57</wpml:executeHeight>   <!-- 官方示例笔误：高度不应是经度值，见下 -->
        <wpml:waypointSpeed>10</wpml:waypointSpeed>
        <wpml:waypointHeadingParam><wpml:waypointHeadingMode>followWayline</wpml:waypointHeadingMode></wpml:waypointHeadingParam>
        <wpml:waypointTurnParam>
          <wpml:waypointTurnMode>toPointAndStopWithDiscontinuityCurvature</wpml:waypointTurnMode>
          <wpml:waypointTurnDampingDist>0</wpml:waypointTurnDampingDist>
        </wpml:waypointTurnParam>
      </Placemark>
      <!-- 第 2 个 Placemark 带 actionGroup -->
    </Folder>
  </Document>
</kml>
```

⚠️ 官方 waylines 示例里 `<wpml:executeHeight>116.57</wpml:executeHeight>` 与经度示例值相同，是文档笔误：`executeHeight` 的类型/单位是"浮点 m"（官方元素表原文），值应填高度（如 40）。本项目生成器已按正确语义填写（见第 10 节），**不要照抄官方示例的 116.57**。

waylines 与 template 的差异：
- Folder 少 `templateType`/`waylineCoordinateSysParam`/`gimbalPitchMode` 等模板元素，多 `wpml:waylineId`、`wpml:executeHeightMode`、`wpml:distance`/`wpml:duration`（示例未列但官方元素表存在，`TODO(未确认)` 精确必填性）。
- 航点用 `wpml:executeHeight`（执行高度）替代 template 的 `height/ellipsoidHeight`；高程基准由 `executeHeightMode` 声明。
- 多个 `Folder` = 多条可执行航线（倾斜摄影模板会生成 5 条）。

参考 URL：https://developer.dji.com/doc/cloud-api-tutorial/en/api-reference/dji-wpml/waylines-wpml.html

## 4. 航点动作（actionGroup / action）

官方 common-element 页给出的 `wpml:actionActuatorFunc` 枚举全集（原文）：`takePhoto`（单拍）、`startRecord`、`stopRecord`、`focus`、`zoom`、`customDirName`、`gimbalRotate`、`rotateYaw`、`hover`、`gimbalEvenlyRotate`、`accurateShoot`（已暂停维护）、`orientedShoot`、`panoShot`（支持 M30/M30T、M3D/M3TD、M4D/M4TD、M4E/M4T）、`recordPointCloud`。
证据：`data/dji/raw/cloudapi/text/v-5c018cb4.796b233b.js.txt`。

动作组结构（官方 template 示例，第 2 个 Placemark 内）：

```xml
<wpml:actionGroup>
  <wpml:actionGroupId>0</wpml:actionGroupId>
  <wpml:actionGroupStartIndex>1</wpml:actionGroupStartIndex>
  <wpml:actionGroupEndIndex>1</wpml:actionGroupEndIndex>
  <wpml:actionGroupMode>sequence</wpml:actionGroupMode>
  <wpml:actionTrigger>
    <wpml:actionTriggerType>reachPoint</wpml:actionTriggerType>
  </wpml:actionTrigger>
  <wpml:action>
    <wpml:actionId>0</wpml:actionId>
    <wpml:actionActuatorFunc>gimbalRotate</wpml:actionActuatorFunc>
    <wpml:actionActuatorFuncParam>
      <wpml:gimbalRotateMode>absoluteAngle</wpml:gimbalRotateMode>
      <wpml:gimbalPitchRotateEnable>0</wpml:gimbalPitchRotateEnable>
      <wpml:gimbalPitchRotateAngle>0</wpml:gimbalPitchRotateAngle>
      <wpml:gimbalRollRotateEnable>0</wpml:gimbalRollRotateEnable>
      <wpml:gimbalRollRotateAngle>0</wpml:gimbalRollRotateAngle>
      <wpml:gimbalYawRotateEnable>1</wpml:gimbalYawRotateEnable>
      <wpml:gimbalYawRotateAngle>30</wpml:gimbalYawRotateAngle>
      <wpml:gimbalRotateTimeEnable>0</wpml:gimbalRotateTimeEnable>
      <wpml:gimbalRotateTime>0</wpml:gimbalRotateTime>
      <wpml:payloadPositionIndex>0</wpml:payloadPositionIndex>
    </wpml:actionActuatorFuncParam>
  </wpml:action>
  <wpml:action>
    <wpml:actionId>1</wpml:actionId>
    <wpml:actionActuatorFunc>takePhoto</wpml:actionActuatorFunc>
    <wpml:actionActuatorFuncParam>
      <wpml:fileSuffix>point1</wpml:fileSuffix>
      <wpml:payloadPositionIndex>0</wpml:payloadPositionIndex>
    </wpml:actionActuatorFuncParam>
  </wpml:action>
</wpml:actionGroup>
```

动作触发器 `wpml:actionTriggerType`（原文）：
- `reachPoint`：到达航点时执行（最常用；本项目每个航点拍照用这个）。
- `betweenAdjacentPoints`：航段触发，均匀转云台（需配 `gimbalEvenlyRotate`）。
- `multipleTiming`：等时触发，配 `takePhoto` = 等时间隔拍照；参数 `wpml:actionTriggerParam` 单位 s。
- `multipleDistance`：等距触发，配 `takePhoto` = 等距离间隔拍照；参数单位 m。
→ 对 3DGS 采集，**等距/等时连续拍照**可以直接放在 waylines 里，不需要在 App 层发 `KeyStartShootPhoto` 循环；但 Mini 系对 `multipleTiming/multipleDistance` 的支持未在支持机型列表中明确（官方元素表支持机型列均为行业机型），`TODO(未确认)`：Mini 4 Pro 需真机验证，保守做法是"每航点 reachPoint + takePhoto"。

其他动作参数（`rotateYaw` 示例，官方原文）：`wpml:aircraftHeading`（相对地理北，[-180,180]）、`wpml:aircraftPathMode`（clockwise/counterClockwise）。`hover`：`wpml:hoverTime`（s>0）。`zoom`：`wpml:focalLength`（`TODO(未确认)` 字段名以 common-element 页 zoom 小节为准）。

SDK 侧的等价物（供对照）：MSDK v5 的 `WaylineActionType` 枚举含 `TAKE_PHOTO/START_RECORD/STOP_RECORD/GIMBAL_ROTATE/HOVER/ZOOM`，官方 Sample 的 `KMZTestUtil.java` 用 `WaylineActionInfo` + `ActionTakePhotoParam/ActionGimbalRotateParam/ActionAircraftHoverParam/ActionZoomParam` 构造，正是这些 actionActuatorFunc 的对象模型（证据：`data/dji/raw/msdkv5_sample/.../KMZTestUtil.java`）。

## 5. 航点参数与约束（速查）

- `wpml:index`：0 起连续递增，不能跳号（官方原文"必须从0开始单调连续递增"）。
- `wpml:autoFlightSpeed/waypointSpeed`：范围 [1,15] m/s（官方表）；Mini 4 Pro 的 DJI Fly 全局速度上限 12 m/s（01 §1.6），WPML 侧实际可执行上限 `TODO(未确认)`，建议 ≤10。
- 高度：`heightMode=relativeToStartPoint` 时 `wpml:height` 即相对起飞点高度；EGM96 时是海拔。Mini 4 Pro 法定/固件限高 120m（CONTRACT 安全规则同口径）。
- 偏航：`waypointHeadingMode` 支持 `followWayline/manually/fixed/smoothTransition/towardPOI`；`towardPOI` 配 `waypointPoiPoint`（格式"纬度,经度,高度"）。
- 转弯：`waypointTurnMode` 4 种；`waypointTurnDampingDist` 单位 m，需"航段长度 > 两航点阻尼距离之和"。
- 航点动作依赖机型/固件；Mini 系不支持全景（panoShot 支持列表无 Mini）。
- 官方 `checkValidation` 只校验部分字段（"The static field checks of KMZ does not encompass all the fields"），**不能替代真机试飞**。

## 6. 生成方式与"上传-执行"状态机

### 6.1 两条生成路线

| 路线 | 做法 | 优缺点 | 本项目 |
|---|---|---|---|
| A. Server/脚本生成 | Python/JS 直接按 WPML 拼 XML → zip 成 KMZ | 完全可控、可单测、无 Android 依赖 | ✅ 采用（`docs/research/assets/make_sample_kmz.py`） |
| B. App 内 WPMZ 库生成 | MSDK v5 的 `IWPMZManager.generateKMZFile(kmzPath, WaylineMission, WaylineMissionConfig, Template)`（`com.dji:wpmzsdk:1.0.5.2`） | 字段有类型检查；但绑定 Android 与 SDK 版本 | 备选（若要在 App 内动态改航线） |

`IWPMZManager` 原文签名（`data/dji/raw/api_v5/IWaypointMissionManager__IWPMZManager.html`）：
```java
KMZInfo getKMZInfo(String kmzPath)
void generateKMZFile(String kmzPath, WaylineMission mission, WaylineMissionConfig config, Template template)
void generateKMZFile(String kmzPath, WaylineMission mission, WaylineMissionConfig config, Wayline wayline)
WaylineCheckErrorMsg checkValidation(String kmzPath)
boolean transKMLtoKMZ(String kmlImportPath, String kmzOutPath)
boolean transKMLtoKMZ(String kmlImportPath, String kmzOutPath, HeightMode transParams)
```
注意：`generateKMZFile` 传 `Template` 时生成"template.kml 有效 + waylines.wpml 有效（可被 DJI Pilot 编辑）"；传 `Wayline` 时 template.kml 无效、仅 waylines.wpml 有效（官方 waypoint 文档原文）。`transKMLtoKMZ` 用于把非 DJI 来源 KML 转 KMZ，必须给高度模式（WGS84/EGM96/RELATIVE）。

### 6.2 下发与执行状态机（MSDK v5）

```
本地生成 KMZ
   │
   ├─(可选) IWPMZManager.checkValidation(kmzPath) ── 失败 → 修字段
   ▼
WaypointMissionManager.pushKMZFileToAircraft(kmzPath, CompletionCallbackWithProgress<Double>)
   │  onProgressUpdate(0.0~1.0) / onSuccess / onFailure(IDJIError)
   ▼
getAvailableWaylineIDs(kmzPath) → List<Int>（KMZ 内可执行航线 id，对应 Folder/waylineId）
   ▼
startMission(kmzPath, waylineIds, CompletionCallback)  ──►  飞机执行
   │
   ├─ pauseMission(cb)    暂停（悬停）
   ├─ resumeMission(cb)   恢复
   ├─ stopMission(kmzPath, cb)  中止
   └─ 监听：
        WaypointMissionExecuteStateListener.onUpdate(WaypointMissionExecuteState)
        WaylineExecutingInfoListener.onWaylineExecutingInfoUpdate(WaylineExecutingInfo)
        WaypointActionListener.onExecutionStart/onExecutionFinish(actionId, IDJIError?)
```
证据：`api_v5/IWaypointMissionManager__IWaypointMissionManager.html` 签名；官方 waypoint 文档 `data/dji/raw/text/waypoint.txt`；Sample `WayPointV3VM.kt`（上述方法逐一出现）。
- 状态枚举：`WaypointMissionExecuteState`（READY/EXECUTING/PAUSED/FINISHED 等；页面 `IWaypointMissionManager_WaypointMissionExecuteStateListener.html`，`TODO(未确认)` 全集顺序）。
- 上传进度回调是 `CompletionCallbackWithProgress<Double>`（0~1），与本项目 HTTP 层 `progress_pct` 可直接映射。
- 执行前飞机必须满足：已连接、GPS 良好、电机未异常、任务已上传完成（状态 READY 才能 startMission，Sample 用 `curMissionExecuteState == WaypointMissionExecuteState.READY` 判断按钮可用性）。

## 7. 错误码与失败模式

- 所有异步回调失败参数是 `IDJIError`（`dji.v5.common.error.IDJIError`，有 `errorCode()/description()`）。官方 MSDK V5 未公开全量错误码表；`TODO(未确认)`：Mini 系航线失败码需真机抓取。
- 已知可预期失败面（来自官方文档/Sample 逻辑）：
  1. KMZ 字段不合法 → `pushKMZFileToAircraft` onFailure（先 `checkValidation` 可提前发现部分）。
  2. KMZ 内部命名/结构不符合规范（如缺 waylines.wpml）→ 读取失败。
  3. 飞机未连接/GPS 差/正在执行其它任务 → startMission 失败。
  4. 断点续飞参数机型不支持（Mini）→ 相关接口不可用或失败。
  5. 任务被遥控器打断（用户打杆）→ 执行状态变化，官方 `onWaylineExecutingInterruptReasonUpdate`（v5.3.0 新增）可拿中断原因（relnotes 5.3.0 原文）。
- 建议：本项目在 Drone Agent 侧定义自己的错误码（CONTRACT §8.2），把 `IDJIError` 的 code/description 原样放进 `detail`，不要假设 code 稳定。

## 8. 断点续飞限制

官方原文（`data/dji/raw/text/waypoint.txt`）：
- "MSDK supports starting and resuming wayline missions from breakpoints."
- "Resuming flight from breakpoint is supported on Matrice 30/30T, Mavic 3E/3T/3M aircraft models."
- "The retrieval of breakpoint information is possible only after invoking the pause mission interface"（先 pause，再 query）。
- 开发者也可以不查询、手动构造 `BreakPointInfo` 传给 `startMission`/`resumeMission`。

→ **Mini 3 / 3 Pro / 4 Pro 不在官方保证列表**。工程策略：
1. 任务中断后，不依赖断点续飞，重新 `pushKMZFileToAircraft`（KMZ 已在机内通常很快）再从 wayline 0 开始；
2. 若必须"续拍"，由 App 在恢复后从断点航点**重新生成一个新 KMZ**（只含剩余航点），代价是空驶航段；
3. `BreakPointInfo` 构造参数（Sample 中 `BreakPointInfo(0, waypointID, progress, null, resume_type)`，`WayPointV3Fragment.kt`）可作为未来适配参考，但 Mini 上不要写进验收标准。

## 9. 与 DJI Fly 原生航点的对比

| 维度 | DJI Fly 原生航点（Mini 4 Pro / Mini 5 Pro 等） | MSDK v5 + KMZ/WPML（Mini 3/3 Pro/4 Pro） |
|---|---|---|
| 航线存储 | App/机内，界面编辑 | KMZ 文件（可版本管理、程序生成） |
| 最大航点数 | 单航线 ≤200（官方帮助页） | WPML index 上限 65535，实际受机内存储/固件限制 |
| 速度 | 0.1–15.0 m/s（默认 2.5；Mini 4 Pro 全局上限 12 m/s） | WPML [1,15] m/s，实际建议 ≤10 |
| 高度 | 默认 50m（相对起飞点） | `heightMode` 可选 EGM96/relativeToStartPoint/AGL |
| 悬停/相机动作 | 每点可设拍照/录像起止、悬停 0–30s、云台俯仰、变焦 | actionGroup 支持 takePhoto/startRecord/stopRecord/gimbalRotate/rotateYaw/hover/zoom 等 |
| KML/WPML 导入 | **不支持** | 就是文件格式本身 |
| 断点续飞 | 不支持 | 仅 M30/M3E/3T/3M 保证，Mini 不在列 |
| 距离限制 | 起飞点与首航点 ≤10km | WPML 未单列，受链路/固件限制 |
| 适用 | 无 SDK 机型（Mini 5 Pro）或不想写代码 | 有 SDK 机型 + 自研 App + 程序化任务 |

结论：**DJI Fly 原生航点与 MSDK KMZ 是两条互不导入的路线**。对 Mini 4 Pro，两者都可用（Fly 航点适合人工规划；MSDK 适合 LLM 自动生成任务）；对 Mini 3/3 Pro 只有 MSDK（或第三方 Litchi Pilot）路线。证据：01 §1.6 官方帮助页与 §5/§6。

## 10. 最小样例：`assets/sample_mission.kmz`

为让本项目"不依赖 DJI Pilot 也能造出合法 KMZ"，本次新增（自造，非官方文件）：

- 生成脚本：`docs/research/assets/make_sample_kmz.py`（纯标准库：`zipfile` + `xml.etree`；无第三方依赖）。
- 样例产物：`docs/research/assets/sample_mission.kmz`（2,972 bytes）。
- 内容：6 航点网格（北京示例坐标，相对起飞点 40m，5m/s，云台 -45°），每个航点 `gimbalRotate` + `takePhoto` 两个动作；template.kml 与 waylines.wpml 各 6 个 Placemark。
- 高度模式：`relativeToStartPoint`；`droneEnumValue/payloadEnumValue` 置 0 并在文件内注释 `TODO(未确认)`（官方文档未给 Mini 4 Pro 枚举值），**该样例仅用于格式校验，未做真机验证，禁止直接用于真实飞行**。

生成与校验命令（实际执行，2026-11-08 21:5x）：

```powershell
cd dji_ue5_3dgs\docs\research\assets
python make_sample_kmz.py
# [OK] ...\sample_mission.kmz: entries=3 template_placemarks=6 wayline_placemarks=6
# written: ...\sample_mission.kmz

# 独立校验（不依赖生成脚本）
python -c "import zipfile, xml.etree.ElementTree as ET; p='sample_mission.kmz'; z=zipfile.ZipFile(p); n=z.namelist(); print('entries:', n); t=ET.fromstring(z.read('wpmz/template.kml')); w=ET.fromstring(z.read('wpmz/waylines.wpml')); ns='{http://www.opengis.net/kml/2.2}Placemark'; print('template placemarks:', len(t.findall('.//'+ns))); print('wayline placemarks:', len(w.findall('.//'+ns))); print('template size:', len(z.read('wpmz/template.kml')), 'waylines size:', len(z.read('wpmz/waylines.wpml'))); print('VALIDATION OK')"
```

实际输出：

```
[OK] C:\Users\<user>\Desktop\GAIA项目\dji_ue5_3dgs\docs\research\assets\sample_mission.kmz: entries=3 template_placemarks=6 wayline_placemarks=6
written: C:\Users\<user>\Desktop\GAIA项目\dji_ue5_3dgs\docs\research\assets\sample_mission.kmz
entries: ['wpmz/', 'wpmz/template.kml', 'wpmz/waylines.wpml']
template placemarks: 6
wayline placemarks: 6
template size: 15711 waylines size: 15812
VALIDATION OK
```

## 11. 证据索引

| 内容 | URL | 本地证据 |
|---|---|---|
| WPML 总览（是什么/目录结构/命名规则） | https://developer.dji.com/doc/cloud-api-tutorial/en/api-reference/dji-wpml/overview.html | data/dji/raw/cloudapi/text/v-7ee37f75.2732d711.js.txt |
| template.kml 元素表 + 官方示例 | https://developer.dji.com/doc/cloud-api-tutorial/en/api-reference/dji-wpml/template-kml.html | data/dji/raw/cloudapi/text/v-26f525b7.ef20ee2f.js.txt |
| waylines.wpml 元素表 + 官方示例 | https://developer.dji.com/doc/cloud-api-tutorial/en/api-reference/dji-wpml/waylines-wpml.html | data/dji/raw/cloudapi/text/v-46bb6ba2.c911fcd4.js.txt |
| 公共元素（heading/turn/actionGroup/action/trigger 全集） | https://developer.dji.com/doc/cloud-api-tutorial/en/api-reference/dji-wpml/common-element.html | data/dji/raw/cloudapi/text/v-5c018cb4.796b233b.js.txt |
| KMZ 上传/执行/暂停/恢复/断点（MSDK 侧） | https://developer.dji.com/doc/mobile-sdk-tutorial/en/ | data/dji/raw/text/waypoint.txt |
| IWaypointMissionManager API | https://developer.dji.com/api-reference-v5/android-api/Components/IWaypointMissionManager/IWaypointMissionManager.html | data/dji/raw/api_v5/IWaypointMissionManager__IWaypointMissionManager.html |
| IWPMZManager API（编辑/校验/转换） | https://developer.dji.com/api-reference-v5/android-api/Components/IWaypointMissionManager/IWPMZManager.html | data/dji/raw/api_v5/IWaypointMissionManager__IWPMZManager.html |
| WPMZ 对象模型（WaylineMission 等） | 同上 | data/dji/raw/msdkv5_sample/.../KMZTestUtil.java、WayPointV3Fragment.kt |
| DJI Fly 航点能力边界 | https://support.dji.com/help/content?customId=01700007343&spaceId=17&lang=zh-CN&documentType&paperDocType=ARTICLE&re=CN | 01 文档 §1.6（2026-11-08 抓取，见 references.md） |
| 本样例生成器/样例 | 本仓库 | docs/research/assets/make_sample_kmz.py、sample_mission.kmz |

## 12. 未决问题 / TODO

1. `droneEnumValue/payloadEnumValue` 对 Mini 4 Pro 的官方取值（WPML 元素表只给了 M30 示例）→ 需查 DJI WPML 机型枚举表或真机/云端校验；当前样例用 0 占位。
2. Mini 4 Pro 对 `multipleTiming/multipleDistance` 等距/等时拍照 trigger 的支持未确认（官方支持机型列均为行业机型）→ 保守用每航点 reachPoint 拍照。
3. `wpml:rotateYaw/zoom` 的参数子元素完整名（本次只确认 `rotateYaw.aircraftHeading/aircraftPathMode`、`hover.hoverTime`）→ 补抓 common-element 页子表。
4. Mini 系列执行 KMZ 的实际速度上限、`executeHeightMode` 是否支持 `EGM96`（相对起飞点最稳）→ 真机验证。
5. 官方可执行航线是否要求 `wpml:distance/duration` 必填（元素表列但示例未给）→ 以 `checkValidation` 实际报错为准。

## 13. KMZ 生成后的 12 项自检清单（本项目强制）

1. ZIP 可打开，且条目名严格为 wpmz/template.kml、wpmz/waylines.wpml（zip 内路径分隔符用 /，不能用反斜杠）。
2. 两个 XML 都能被标准 XML 解析器解析（本项目用 Python ElementTree 验证）。
3. 根元素是 kml，xmlns:wpml 指向 http://www.dji.com/wpmz/1.0.2，xmlns 指向 http://www.opengis.net/kml/2.2。
4. template 与 waylines 的 templateId 对应一致（本项目单航线用 0）。
5. 航点 wpml:index 从 0 连续递增，无跳号、无重复。
6. 每个 Placemark 有 Point/coordinates 且顺序是「经度,纬度」（不能反）。
7. heightMode/executeHeightMode 与高度字段语义一致：相对起飞点模式用 wpml:height/wpml:executeHeight（单位 m），EGM96 用海拔。
8. 高度在安全范围（本项目 5–120m）、速度在 [1,15]m/s 且 ≤10m/s（Mini 建议）。
9. actionGroup 的 startIndex/endIndex 落在航点索引范围内，动作 actionId 在组内唯一。
10. gimbalRotate 的 pitch 在机型云台范围内（Mini 4 Pro -90°~+35°）。
11. actionActuatorFunc 只使用官方枚举值（本文件第 4 节），不要自造；Mini 系避开 panoShot/orientedShoot 等未确认支持的动作。
12. 用 IWPMZManager.checkValidation(kmzPath) 再扫一遍（若在 App 内生成），但记住官方明确说明「静态检查不覆盖全部字段」，真机小航线试飞才是最终验证。

## 14. mission JSON → WPML 的映射规则（与本项目 llm_drone 的衔接）

本项目 Phase-1 的 mission JSON（llm_drone/spec/sample_mission.json）与 WPML 的对应关系建议如下（生成器 make_sample_kmz.py 即按此实现）：

| mission JSON 字段 | WPML 落点 | 说明 |
|---|---|---|
| waypoints[i].lat/lon | Placemark/Point/coordinates（经度,纬度） | WGS84；注意经纬顺序 |
| waypoints[i].alt_rel_m | wpml:height（template）/wpml:executeHeight（waylines） | heightMode=relativeToStartPoint |
| speed_mps | wpml:autoFlightSpeed（全局）+ wpml:waypointSpeed | 均需在 [1,15] |
| gimbal_pitch | 动作 gimbalRotate 的 gimbalPitchRotateAngle，或 wpml:gimbalPitchAngle | usePointSetting 时两者一致 |
| take_photos | 每个航点插入 takePhoto 动作 | fileSuffix 可用航点序号命名 |
| photo_interval_s | 可用 multipleTiming + takePhoto 表达 | Mini 支持性 TODO(未确认)，保守改为每点拍照 |
| mission_id | 生成文件时写入 KMZ 文件名（航线名） | 包名即航线名，需符合命名规范 |
| finish_action | wpml:finishAction（goHome 等） | 与本项目 RTH 语义一致 |

生成器伪代码（与服务端/脚本同构）：

```python
def mission_json_to_kmz(mission, out_path):
    waypoints = mission['waypoints']
    template = render_template(waypoints, mission['speed_mps'], mission['gimbal_pitch'])
    waylines = render_waylines(waypoints, mission['speed_mps'], mission['gimbal_pitch'])
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('wpmz/', b'')
        zf.writestr('wpmz/template.kml', template.encode('utf-8'))
        zf.writestr('wpmz/waylines.wpml', waylines.encode('utf-8'))
    verify_kmz(out_path)   # 第 13 节清单的自动化部分
```

注意：服务端只负责「格式正确 + 安全阈值」；真实飞行的合法性（禁飞区/空域/操作资质）仍由 SafetyValidator + 人工确认 + 法规约束，KMZ 合法不等于可以起飞。

## 15. 生成/下发常见错误与排查

| 现象 | 可能原因 | 排查 |
|---|---|---|
| pushKMZFileToAircraft 立即失败 | 文件路径不可读 / KMZ 结构错 / 未连接飞机 | 先本地 zip+XML 校验；确认 onProductConnect；确认文件在 App 可读目录 |
| 上传进度卡住 | 图传链路差 / 文件过大 / 飞机存储满 | 缩短航线；清理飞机存储；靠近飞机 |
| getAvailableWaylineIDs 为空 | waylines.wpml 缺 Folder 或 templateId 不匹配 | 对照第 3 节结构检查 |
| startMission 失败 | 未上传完成 / GPS 差 / 飞机不在可执行状态 | 先查 WaypointMissionExecuteState 是否 READY；查 GPS 与电机状态 |
| 飞机不动或只起飞不飞航线 | 起飞安全高度/首航点距离不合理，或动作阻塞 | 降低 takeOffSecurityHeight、缩短首段距离、先试纯航点 |
| 相机不拍照 | actionActuatorFunc 拼写错 / payloadPositionIndex 不对 / fileSuffix 非法 | 先用单点航线 + takePhoto 验证 |
| 执行中频繁中断 | 遥控器打杆 / 失联策略 / 避障触发 | 查 onWaylineExecutingInterruptReasonUpdate 回调 |
