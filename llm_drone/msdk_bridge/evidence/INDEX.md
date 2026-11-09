# evidence 索引（证据目录）

> 本目录保存 task-10（MSDK v5 桥）的**可复核证据**。原则：只放“一手来源可回溯”的内容；无法回溯的推断一律标注未验证。

## 文件

| 文件 | 内容 | 证据来源 |
|---|---|---|
| API_SYMBOLS_VERIFIED.md | MSDK v5.20.1 类/方法/Key 泛型签名/枚举/Listener 签名/机型能力清单逐项核验；未验证项清单；官方 sample 参考文件表 | E1–E5（见下） |
| INDEX.md | 本索引 + 来源编号总表 + 复现命令 | — |
| SELF_CHECK.md | 交付物自动自查（文件完整性/15 工具映射覆盖/Kotlin 类声明/文档端点与错误码），本轮静态检查通过 | python 脚本扫描（命令见文末） |
| `../_tmp_api/`（原始 HTML 快照） | developer.dji.com API Reference 页面快照 28 个（fc/camera/gimbal/keymanager/waypointmgr/mediacenter/mediamanager/virtualstick/sdkmanager/flyzone/intelligent/wpmz 等），供人工复核类/方法名 | developer.dji.com（官方一手） |

## 来源编号总表（与 mapping.json 的 source 字段对应）

| ID | 来源 | 类型 | 用途 |
|---|---|---|---|
| E1 / S4 | `com.dji:dji-sdk-v5-aircraft-provided:5.20.1`（Maven Central，JAR 20,609,447 B） | 官方构件 | 编译期 API 符号（Key 常量/泛型签名/Manager 接口/枚举/Listener） |
| E2 | `com.dji:dji-sdk-v5-aircraft:5.20.1`（AAR 133,651,350 B） | 官方构件 | Mini 4 Pro 能力清单 `assets/ProductCapability/DJIMini4Pro/*.json`（supportedMSDKVersion/固件下限/Key 子集） |
| E3 / S12–S16 | 官方 sample `dji-sdk/Mobile-SDK-Android-V5@dev-sdk-main`（SampleCode-V5/android-sdk-v5-sample） | 官方代码 | 真实调用写法（SDKManager init/registerApp、KeyStartTakeoff、KMZ 上传/startMission、相机、媒体下载、虚拟摇杆、POI） |
| E4 / S11 | 官方 sample `android-sdk-v5-as/dependencies.gradle` | 官方代码 | 依赖坐标 5.20.1 + wpmzsdk 1.0.5.2 + 仓库 URL |
| E5 | `data/dji/raw/text/relnotes_all.txt`（前序调研落盘官方 Release Notes 全文） | 官方一手（落盘） | 版本-机型-固件对应（Mini 4 Pro 自 v5.13.0；RC-N2/RC-N3；RC 2 不支持） |
| S1–S3, S5–S10 | developer.dji.com V5 API Reference（`_tmp_api/` 快照） | 官方文档 | Key 列表、Manager 方法、KeyTools/错误码语义 |
| S17 | 官方 sample `AndroidManifest.xml` | 官方代码 | `com.dji.sdk.API_KEY`、USB accessory、extractNativeLibs |
| S18–S20 | 官方教程（wayline / virtual-stick / WPML overview） | 官方文档 | KMZ/WPML 结构、断点续飞机型限制、虚拟摇杆频率与 N 档前提 |

## 复现命令（无需真机）

```powershell
# E1：拉 provided JAR 并扫描符号（PowerShell + Python 3）
$dir = Join-Path $env:TEMP 'msdkv5api'
New-Item -ItemType Directory -Force $dir | Out-Null
Invoke-WebRequest 'https://repo1.maven.org/maven2/com/dji/dji-sdk-v5-aircraft-provided/5.20.1/dji-sdk-v5-aircraft-provided-5.20.1.jar' -OutFile (Join-Path $dir 'provided.jar')
# 解压后扫描 .class 常量池（方法与结果见 API_SYMBOLS_VERIFIED.md §1）

# E2：拉 AAR（zip）取 Mini 4 Pro 能力清单
Invoke-WebRequest 'https://repo1.maven.org/maven2/com/dji/dji-sdk-v5-aircraft/5.20.1/dji-sdk-v5-aircraft-5.20.1.aar' -OutFile (Join-Path $dir 'aircraft.aar')
Expand-Archive (Join-Path $dir 'aircraft.aar') (Join-Path $dir 'aircraft') -Force
Get-ChildItem (Join-Path $dir 'aircraft/assets/ProductCapability/DJIMini4Pro') -Filter '*.json'

# E3/E4：官方 sample（github.com 直连不可用时用 jsDelivr CDN；API 限流时用 cdn.jsdelivr.net/gh/...）
Invoke-WebRequest 'https://cdn.jsdelivr.net/gh/dji-sdk/mobile-sdk-android-v5@dev-sdk-main/SampleCode-V5/android-sdk-v5-as/dependencies.gradle' -OutFile deps.gradle
```

## 证据强度说明（避免误读）

- ✅ **构件级已验证**：类存在、方法/字段/枚举/泛型签名存在、Mini 4 Pro 能力清单含该 Key。**不等于**真机调用成功。
- ⚠️ **sample 级已验证**：官方 sample 中确实这样调用；**不等于**本桥骨架已编译。
- ❌ **未验证**：KMZ 被 Mini 4 Pro 接受、GimbalAngleRotation 参数语义、媒体下载实际速率、飞行行为、App Key 注册——全部需 `REAL_DRONE_TEST.md` 真机确认。
