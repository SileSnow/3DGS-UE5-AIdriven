# 04 真实 DJI 样本元数据验证

> 目的：用真实 DJI Mini 照片验证 03 中的 EXIF/XMP 字段清单，并给出“解析管线必须注意什么”的实测证据。
> 方法：从 Wikimedia Commons 下载 5 张由 DJI Mini 系列真实拍摄的照片（非产品宣传图），用 Python exifread 3.5.1 + Pillow 12.2 解析；脚本与原始结果落盘。
> 复现：python data/dji/parse_exif.py；输出 data/dji/samples/exif_results.json；原始照片 data/dji/samples/*.jpg。

## 1. 样本清单（均为 CC 许可，仅用于元数据技术研究）

| # | 本地文件 | 机型（EXIF Model / XMP） | 分辨率 | 大小 | 拍摄时间 | 来源（Commons 文件页） | 许可 |
|---|---|---|---|---|---|---|---|
| 1 | FC8482_Mini4Pro.jpg | FC8482 / “Mini4 Pro” | 8064×6048（48MP） | 38.2 MB | 2026-01-29 09:53:08 | https://commons.wikimedia.org/wiki/File:Dülmen,_Sportzentrum_Süd,_Parkplatz_--_2026_--_0223.jpg | CC BY-SA 4.0（Dietmar Rabich） |
| 2 | FC8482_Mini4Pro_b.jpg | FC8482 / “Mini4 Pro” | 8064×6048 | 54.5 MB | 2024-05-30 06:36:49 | https://commons.wikimedia.org/wiki/File:Dülmen,_Kirchspiel,_Dernekamp,_Getreidefeld_--_2024_--_0003.jpg | CC BY-SA 4.0（Dietmar Rabich） |
| 3 | FC3582_Mini3Pro.jpg | FC3582 / “Mini 3 Pro” | 4521×3391（导出裁剪） | 7.6 MB | 2023-08-23 19:17:59 | https://commons.wikimedia.org/wiki/File:Ostuni_col_drone.jpg | CC BY 4.0（ParisTaras） |
| 4 | FC3582_Mini3Pro_b.jpg | FC3582 / “Mini 3 Pro” | 5181×3454（全景拼接导出） | 12.1 MB | 2024-09-04 06:33:39（SubSec .11） | https://commons.wikimedia.org/wiki/File:Karpniki_wschód_słońca.jpg | CC BY-SA 4.0（Gswito） |
| 5 | FC3170_Mini2.jpg | FC3170（Mini 2） | 2784×1804（导出裁剪） | 4.7 MB | 2022-11-15 10:13:51 | https://commons.wikimedia.org/wiki/File:Lighthouse_Aniva.jpg | CC BY 4.0（Pavelappps） |

说明：5 张样本均经过 Adobe Lightroom/Photoshop 导出（EXIF Software 可见），因此部分字段（尤其 GPS EXIF 与机内标定字段）可能被剥离——这本身就是一个重要实测结论（见第 3 节）。CAR 代码对应关系：FC8482=Mini 4 Pro、FC3582=Mini 3 Pro、FC3170=Mini 2（与 01/02 的机型表一致）。

## 2. 实测字段表

### 2.1 标准 EXIF（有值/无值用“—”表示）
| 字段 | 样本1 Mini4Pro | 样本2 Mini4Pro | 样本3 Mini3Pro | 样本4 Mini3Pro | 样本5 Mini2 |
|---|---|---|---|---|---|
| Image Make | DJI | DJI | DJI | DJI | DJI |
| Image Model | FC8482 | FC8482 | FC3582 | FC3582 | FC3170 |
| DateTimeOriginal | 2026:01:29 09:53:08 | 2024:05:30 06:36:49 | 2023:08:23 19:17:59 | 2024:09:04 06:33:39 | 2022:11:15 10:13:51 |
| SubSecTimeOriginal | — | — | — | 11 | — |
| ExposureTime | 1/640 | 1/200 | 1/120 | 1/500 | 1/320 |
| FNumber | 1.7 | 1.7 | 1.7 | 1.7 | 2.8 |
| ISOSpeedRatings | 100 | 100 | 110 | 110 | 100 |
| FocalLength (mm) | 6.72 | 6.72 | 6.72 | 6.72 | 4.5 |
| FocalLengthIn35mmFilm | 24 | 24 | 24 | 24 | 24 |
| DigitalZoomRatio | 1 | 1 | 1 | 1 | 1 |
| ExposureMode | Manual | Auto | Auto | Auto | Auto |
| ColorSpace | sRGB | sRGB | Uncalibrated | sRGB | sRGB |
| GPS EXIF IFD | 有（lat 51.8227, lon 7.2803, alt 250.99 m） | 有（51.7997, 7.2813, 124.71 m） | 有（40.7327, 17.5758；无 GPSAltitude） | **无（被导出剥离）** | **无（被导出剥离）** |
| Software | Lightroom 14.5.2 (Mac) | Lightroom 13.3 (Mac) | Photoshop 25.0 | Lightroom 13.3.1 | Lightroom 11.2 |

### 2.2 DJI 私有 XMP（drone-dji:*）
| 字段 | 样本1 Mini4Pro | 样本2 Mini4Pro | 样本3 Mini3Pro | 样本4 Mini3Pro | 样本5 Mini2 |
|---|---|---|---|---|---|
| Version | 1.6 | 1.6 | 1.5 | 1.5 | —（导出后未保留 Version） |
| GpsLatitude / GpsLongitude | +51.822733319 / +7.280250929 | +51.799748570 / +7.281265857 | +40.732730234 / +17.575767495 | +50.846132874 / +15.846245292 | +46.0188489 / +143.4140535 |
| GpsStatus | Normal | Normal | **Invalid** | **Invalid** | — |
| AltitudeType | GpsFusionAlt | GpsFusionAlt | **RtkAlt** | **RtkAlt** | — |
| AbsoluteAltitude (m) | +250.986 | +124.711 | +292.361 | +457.020 | +71.80 |
| RelativeAltitude (m) | +81.000 | +14.000 | +113.700 | +119.900 | +71.80 |
| GimbalYawDegree | +39.90 | +8.30 | +169.40 | +8.30 | +29.00 |
| GimbalPitchDegree | -90.00 | -80.10 | -31.70 | -19.60 | -90.00 |
| GimbalRollDegree | +0.00 | +0.00 | +0.00 | **-89.90（全景拼接导出）** | +0.00 |
| FlightYaw/Pitch/Roll | -46.70 / +4.30 / +6.70 | -57.80 / -1.00 / -0.60 | +60.10 / +0.60 / -10.70 | +12.60 / -0.30 / +1.20 | +73.40 / -9.00 / -5.70 |
| FlightX/Y/ZSpeed | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 | — |
| 机型字段 | ProductName=Mini4 Pro | ProductName=Mini4 Pro | DroneModel=Mini 3 Pro | DroneModel=Mini 3 Pro | —（导出丢失） |
| DroneSerialNumber | —（导出后丢失） | —（导出后丢失） | 1581F4XFC233L0 | 1581F4XFC225C0 | — |
| CameraSerialNumber | 6TVQLCS0M202HZ | 6TVQLCS0M202HZ | 53HFL280M608ZC | 53HQK4U0M103C8 | — |
| ShutterType / SurveyingMode | Electronic / 0 | Electronic / 0 | Electronic / 0 | Electronic / 0 | — |
| UTCAtExposure | 字段不存在 | 字段不存在 | **空字符串** | **空字符串** | — |
| SensorTemperature / WB CCT / SensorFPS | 10.0 / 7087 / 15.00 | 28.0 / 5027 / 15.00 | — | — | — |
| 其他 | CamReverse=0, GimbalReverse=0 | 同左 | ImageSource=DefaultCamera | aux:IsMergedHDR=True, IsMergedPanorama=True | CameraSerial/电池等缺失 |

注：“—”表示该样本导出后没有该字段。完整逐字段原始值见 data/dji/samples/exif_results.json。

## 3. 关键实测发现（直接影响 03 的方案）

1. **必须同时解析 EXIF 与 XMP**：样本 4/5 的 EXIF GPS IFD 被修图软件剥离，但 XMP 里仍有 drone-dji GPS；样本 1/2 两者都有。只读 EXIF 会丢一半数据的位姿。
2. **GpsStatus 不能作为唯一有效性判据**：样本 3/4 的 drone-dji:GpsStatus=Invalid，但 GpsLatitude/GpsLongitude 有合理数值且与 EXIF GPS 一致。管线应“坐标范围合理 + 与航迹连续性”做判据。
3. **AltitudeType 语义不可靠**：无 RTK 的 Mini 3 Pro 样张出现 RtkAlt。高度换算应优先用 RelativeAltitude（与 DJI Fly 高度一致），绝对高度只做参考并用 GCP 校正。
4. **修图/拼接会改变云台角语义**：样本 4 是全景拼接导出（aux:IsMergedPanorama=True），GimbalRollDegree=-89.90 明显不是真实云台横滚。**位姿先验必须使用 SD 卡原片**，修图/拼接文件只能做影像发布，不能做几何先验。
5. **UTCAtExposure 在实测中为空**：无法从照片直接获得曝光时刻的 UTC 时间戳；跨设备/多架次同步只能靠文件顺序、GPS 轨迹与架次日志。
6. **机内标定字段（CalibratedFocalLength、CalibratedOpticalCenterX/Y、DewarpData）在 5 张导出样本中均未出现**（ExifTool DJI 标签表中有定义）。说明导出链路会丢字段；内参需用 COLMAP 自标定或保留原片。
7. **文件命名可交叉校验时间**：样本 2 的 crs:RawFileName=DJI_20240530063649_0003_D.DNG 与 DateTimeOriginal 完全对应，可作为原片命名规范（DJI_YYYYMMDDHHMMSS_NNNN_D）。
8. 样本 3 分辨率 4521×3391、样本 5 为 2784×1804：均为导出裁剪，**内参会变**（不能直接用官方 8064×6048 的 fx 估算），再次说明原片重要性。

## 4. 局限与本轮未覆盖
- 未取得 **SD 卡原始 JPG/DNG**（含完整 EXIF GPS、DewarpData、MakerNote）；因此第 1 节字段表只能反映“Lightroom 导出后仍保留”的子集。建议后续用真实原片复测。
- 未取得 **视频 SRT**（本轮无真实视频样本），03 中 SRT 格式标注为“样板/待核对”。
- 样本均来自公开作品，曝光/构图不代表采集规范；仅用于元数据字段验证。
- 许可声明：5 张样本均为 CC BY 4.0 / CC BY-SA 4.0，作者见第 1 节；本地仅用于本技术验证，不再分发。

## 5. 结论
- 真实 DJI Mini 数据确实携带“GPS + 绝对/相对高度 + 云台三轴 + 飞行器姿态 + 机型序列号”的完整位姿先验字段，但**位姿信息的完整度取决于导出链路**。
- 采集与处理规范：**保留原片 → EXIF+XMP 双解析 → 用 RelativeAltitude/GimbalYaw/Pitch 建先验 → 修图/拼接文件不参与几何**。
- 该结论已回写到 03_DJI元数据与位姿先验.md 的第 1、4、5 节。
