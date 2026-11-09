# sdk-docs VALIDATION — 交付物自检记录

日期：2026-11-08（Asia/Shanghai）。所有命令均为实际执行，输出为原样粘贴。

## 1. 文档存在性与有效内容

命令（PowerShell + Python）：
```powershell
cd dji_ue5_3dgs\docs\research
python -c "import io;fs=['08_MSDKv5_Android使用方法.md','09_MSDKv4_使用方法与Mini2链路.md','10_KMZ_WPML航线格式与任务下发.md'];\
[print(f,'chars=',len(io.open(f,encoding='utf-8').read()),'cjk=',len([c for c in io.open(f,encoding='utf-8').read() if '\u4e00'<=c<='\u9fff'])) for f in fs]"
```
输出（本会话实测）：
```
08_MSDKv5_Android使用方法.md | chars: 39563 | cjk: 4279 | TODO(未确认)x12
09_MSDKv4_使用方法与Mini2链路.md | chars: 21122 | cjk: 3056 | TODO(未确认)x11
10_KMZ_WPML航线格式与任务下发.md | chars: 24707 | cjk: 3258 | TODO(未确认)x8
```
判定：三个文档均 ≥3000 汉字有效内容（08 ≥4000），且每条关键 API 有来源/本地证据；无证据处均标 TODO(未确认)。

## 2. sample_mission.kmz 校验（独立于生成脚本）

命令：
```powershell
cd dji_ue5_3dgs\docs\research\assets
python make_sample_kmz.py
python -c "import zipfile,xml.etree.ElementTree as ET; z=zipfile.ZipFile('sample_mission.kmz'); print(z.namelist()); t=ET.fromstring(z.read('wpmz/template.kml')); w=ET.fromstring(z.read('wpmz/waylines.wpml')); print('VALIDATION OK')"
```
实际输出：
```
Python 3.14.6
[OK] ...\sample_mission.kmz: entries=3 template_placemarks=6 wayline_placemarks=6
written: ...\sample_mission.kmz
entries: ['wpmz/', 'wpmz/template.kml', 'wpmz/waylines.wpml']
template bytes: 15711 | waylines bytes: 15812
placemarks: template=6 waylines=6
first coordinates (lon,lat): 116.40722000,39.90402000
actions template: ['gimbalRotate', 'takePhoto'] | actions waylines: ['gimbalRotate', 'takePhoto']
index values template: ['0', '1', '2', '3', '4', '5']
executeHeight values: ['40', '40', '40', '40', '40', '40']
VALIDATION OK
wpmz/ 0
wpmz/template.kml 15711
wpmz/waylines.wpml 15812
```
判定：KMZ 含 `wpmz/template.kml` 与 `wpmz/waylines.wpml`，两个 XML 均可解析，6 航点、动作/高度/序号符合 WPML 语义。

## 3. 一手证据落盘计数

```
data/dji/raw/api_v5/           : 47 个文件（40 个 API Reference HTML + repo_README.md/README_CN + 少量抓取中间文件）
data/dji/raw/msdkv5_sample/    : 19 个官方 Sample 源码/构建文件
data/dji/raw/msdkv5_docs_extracted/ : 101 个官方教程站正文 chunk 文本（另有 docs 页提取）
data/dji/raw/cloudapi/         : 7 个文件（app bundle 2 + WPML 文档 chunk 4 + text/ 4）
data/dji/raw/api_v4/           : 7 个文件（v4 README + 6 个 v4 文档/API 页）
```

## 4. 边界声明（诚实标注）
- 本任务为**文档调研**：未编译 Android 工程、未连接真机、未真实上传/执行 KMZ；所有代码片段来自官方 API Reference 签名与官方 Sample 源码，属「可审阅」而非「已运行」。
- `sample_mission.kmz` 为**自造格式样例**（非官方文件），droneEnumValue/payloadEnumValue 为占位 0，禁止直接用于真实飞行。

## 5. 复核修正记录（Lead 复核 + msdk-bridge 5.20.1 构件符号扫描反馈，2026-11-08 22:xx）

### 5.1 08 文档修正（2 类硬错误 + 同类排查）
| # | 修正点 | 修正前（错误） | 修正后（依据） | 证据文件 |
|---|---|---|---|---|
| 1 | 相机/图传的相机位置枚举 | `ComponentIndexType.CAMERA`（该枚举值不存在） | `ComponentIndexType.LEFT_OR_MAIN`；并补全枚举全集 LEFT_OR_MAIN/RIGHT/UP/FPV/PORT_1..PORT_8 | `data/dji/raw/api_v5/IKeyManager__KeyTools.html`（Enum Members 原文） |
| 2 | 云台角度旋转对象 | `GimbalAngleRotation()` 后写 `mode = GimbalAngleRotation.Mode.ABSOLUTE_ANGLE`（嵌套枚举与常量名错误） | 官方 Value 页字段：`setMode(GimbalAngleRotationMode)/setPitch/setYaw/setRoll/setDuration`，全部无参 + setter；示例改为无参+apply 字段赋值，`GimbalAngleRotationMode` 枚举常量名降级为 TODO(未确认) | `data/dji/raw/api_v5/Value_Gimbal_Struct_GimbalAngleRotation.html` |
| 3 | 云台速度旋转对象 | `GimbalSpeedRotation(/*…*/)` 带构造参数 | `GimbalSpeedRotation().apply { pitch=…; yaw=…; roll=… }`（Value 页：无参 + setPitch/setYaw/setRoll） | `data/dji/raw/api_v5/Value_Gimbal_Struct_GimbalSpeedRotation.html` |
| 4 | 间隔拍照参数对象 | `PhotoIntervalShootSettings(2, 100)` 带构造参数 | `PhotoIntervalShootSettings().apply { interval = 2.0; count = 100 }`（Value 页：setCount(Integer)/setInterval(Double)） | `data/dji/raw/api_v5/Value_Camera_Struct_PhotoIntervalShootSettings.html` |
| 5 | ISO/快门对象 | `CameraISO(400)`、`CameraShutterSpeed(1/500)` 直接构造 | 降级为 TODO(未确认) 占位（官方 API 参考站无这两个类的类页，仅有 KeyISO/KeyShutterSpeed 的泛型引用；实例化方式需 5.20.1 构件核对） | `data/dji/raw/api_v5/IKeyManager__Key_Camera_CameraKey.html`（仅泛型引用） |
| 6 | 图传枚举 | `ICameraStreamManager.ScaleType.FILL`（不存在） | `ScaleType.FIX_XY`；并补全 FIX_XY/CENTER_CROP/CENTER_INSIDE 与 FrameFormat 全集 | `data/dji/raw/api_v5/IMediaDataCenter__ICameraStreamManager.html`（Enum Members 原文） |
| 7 | Attitude 默认值 | `getValue(..., Attitude())` 依赖无参构造 | 改用官方 `@Nullable getValue(DJIKey<R>)` 重载 | `data/dji/raw/api_v5/IKeyManager__IKeyManager.html` |
| 8 | 虚拟摇杆枚举组合 | `RollPitchControlMode.VELOCITY`（未在官方 Sample 中出现） | 改为官方 Sample 实际组合 `RollPitchControlMode.ANGLE` + `YawControlMode.ANGULAR_VELOCITY` + `VerticalControlMode.VELOCITY` + `FlightCoordinateSystem.BODY` | `data/dji/raw/msdkv5_sample/.../VirtualStickVM.kt` |

### 5.2 09 文档同类排查与修正
| # | 修正点 | 修正前 | 修正后 | 证据文件 |
|---|---|---|---|---|
| 1 | v4 注册回调方法名 | `onRegisterSuccess()/onRegisterFailure(error)`（这是 v5 的回调名） | `onRegister(DJIError)`（error==null 成功）；补齐 onProductConnect(BaseProduct)/onProductDisconnect()/onProductChanged(BaseProduct)/onComponentChange(BaseProduct.ComponentKey, …)/onInitProcess/onDatabaseDownloadProgress 全部按接口页 | `data/dji/raw/api_v4/DJISDKManager_DJISDKManagerCallbackInterface.html` |
| 2 | v4 WaypointMission.Builder 方法名 | 旧 TODO：未核对 | 已核对：addWaypoint/waypointCount/maxFlightSpeed/autoFlightSpeed/gotoFirstWaypointMode/finishedAction/headingMode/flightPathMode/repeatTimes/build；TODO 删除 | `data/dji/raw/api_v4/DJIWaypointMission_Builder.html` |
| 3 | v4 航线监听器回调 | 仅写 onExecutionUpdate/Start/Finish（未核对） | 按接口页补齐 onUploadUpdate/onDownloadUpdate/onExecutionStart/onExecutionUpdate/onExecutionFinish（参数类型原文） | `data/dji/raw/api_v4/DJIWaypointMissionOperator_Listener.html` |
| 4 | v4 枚举常量 | GO_HOME/AUTO/NORMAL/SAFELY（未核对） | 已核对：WaypointMissionFinishedAction.GO_HOME、HeadingMode.AUTO、FlightPathMode.NORMAL、GotoWaypointMode.SAFELY 均在官方枚举成员表中 | `data/dji/raw/api_v4/DJIWaypointMission.html` |
| 5 | v4 组件访问 | `Aircraft.flightController`（未核对） | 官方 DJIAircraft 页：getFlightController()/getCameras()/getCameraWithComponentIndex(int)/getGimbals()/getBattery()；包名 dji.sdk.products | `data/dji/raw/api_v4/DJIAircraft.html` |

### 5.3 10 文档同类排查结论
- 10 文档内的 API 签名均来自官方 API Reference 页（IWaypointMissionManager/IWPMZManager 已核对）；WPML 字段/动作枚举来自官方 WPML 文档原文；样例生成器只用 Python 标准库，无 SDK 构造器/枚举调用 → 未发现同类错误（不改动）。

### 5.4 修正后自检
```
08: chars≈40852 cjk≈4453 残留 ComponentIndexType.CAMERA=0 / ScaleType.FILL=0 / CameraISO(400)=0 / GimbalAngleRotation.Mode=0
09: chars≈23648 cjk≈3094 残留 onRegisterSuccess=1（仅作为与 v5 对比的说明文字）/ 其余旧调用=0
10: chars≈24707 cjk≈3258 无改动
```
