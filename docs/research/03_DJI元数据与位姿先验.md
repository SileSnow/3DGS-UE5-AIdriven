# 03 DJI 元数据与位姿先验

> 调研日期 2026-11-08。本文给出 DJI Mini 照片/视频可用的元数据字段、实测值、坐标转换方法与“位姿先验 + COLMAP 精化”的融合方案。
> 实测数据来自 3 个机型的真实样张（Mini 2 / Mini 3 Pro / Mini 4 Pro，详见 04_真实DJI样本元数据验证.md），字段清单同时对照 ExifTool 官方 DJI 标签表。

## 0. 结论速览
1. DJI Mini 照片位姿信息在 **两张表** 里：标准 EXIF（相机/曝光/GPS）与 DJI 私有 XMP（drone-dji:*：GPS、绝对/相对高度、云台三轴角、飞行器姿态、机型序列号）。**必须同时解析，缺一不可**。
2. 无 RTK 的 Mini 系列 GPS 为单点定位，水平误差约 1–5 m、垂直更差（3–10 m）；云台角（尤其偏航）受磁罗盘影响，绝对精度约 1–3°。这些先验适合做 **SfM 初始化/配准**，不能直接当作精确外参。
3. COLMAP 官方已支持 GPS 位姿先验：feature_extractor 自动把 EXIF GPS 存入数据库，pose_prior_mapper 用先验做重建；重建后 model_aligner（--ref_is_gps 1 --alignment_type ecef）可做地理配准。这是“位姿先验 + COLMAP 精化”的官方推荐路径（https://colmap.github.io/faq.html）。
4. 相机-IMU 时间同步、曝光时刻精确时间戳（XMP 的 UTCAtExposure 在实测样张中为空）、原始去畸变参数（DewarpData）在导出/修图后可能丢失——采集流程必须保留 SD 卡原始文件。

## 1. EXIF / XMP 字段清单（实测 + ExifTool 对照）

### 1.1 标准 EXIF（实测示例，Mini 4 Pro / 48MP 原图导出）
| 字段（ExifTool 名） | 实测示例 | 用途 / 注意 |
|---|---|---|
| Make | DJI | 固定 |
| Model | FC8482（Mini 4 Pro）/ FC3582（Mini 3 Pro）/ FC3170（Mini 2） | 机型识别：FC 代码是唯一可靠依据 |
| DateTimeOriginal | 2026:01:29 09:53:08 | 相机本地时间，无时区；批量采集时用于排序 |
| SubSecTimeOriginal | 11（部分样张有） | 亚秒级时间，用于多机/多相机对齐 |
| ExposureTime | 1/640 | 运动模糊评估 |
| FNumber | 17/10 → f/1.7 | 固定光圈机型仍写 EXIF |
| ISOSpeedRatings | 100 | 噪声/曝光一致性 |
| FocalLength | 168/25 = 6.72 mm | **真实焦距**（不是等效焦距），算 GSD/内参必需 |
| FocalLengthIn35mmFilm | 24 | 等效焦距，用于核对 |
| DigitalZoomRatio | 1 | 必须为 1；>1 时内参/视场改变 |
| ExifImageWidth/Height | 8064×6048 | 内参分辨率 |
| ExposureMode / ExposureProgram | Manual Exposure / Manual | 采集一致性检查 |
| GPS GPSLatitude/Ref、GPSLongitude/Ref | 51°49'21.8"N, 7°16'49.1"E | 单点 GPS；部分导出流程会剥离 EXIF GPS（见 04） |
| GPS GPSAltitude / GPSAltitudeRef | 125493/500 m → 251.0 m | 椭球/海拔高度定义需核对；优先用 XMP AbsoluteAltitude |
| GPS GPSStatus | A / V | A=有效定位；V=无效（实测 Mini 3 Pro 样张 GPSStatus=Invalid 但仍有坐标，需业务容错） |

### 1.2 DJI 私有 XMP（drone-dji:*，实测值）
| 字段 | 实测示例 | 含义 / 精度 |
|---|---|---|
| drone-dji:GpsLatitude / GpsLongitude | +51.822733319 / +7.280250929 | 十进制度；Mini 4 Pro GpsStatus=Normal |
| drone-dji:AbsoluteAltitude | +250.986 m | 绝对高度（海拔/椭球，取决于 AltitudeType） |
| drone-dji:RelativeAltitude | +81.000 m | 相对起飞点高度（与 DJI Fly 高度一致） |
| drone-dji:AltitudeType | GpsFusionAlt（Mini 4 Pro）；RtkAlt（Mini 3 Pro 样张） | 高度来源；无 RTK 机型出现 RtkAlt 说明字段语义不严格，**不能当作 RTK 精度** |
| drone-dji:GimbalYawDegree | +39.90° | 云台相对**真北**偏航（0=北，顺时针为正），实测值 |
| drone-dji:GimbalPitchDegree | -90.00° | 云台俯仰（-90=垂直向下） |
| drone-dji:GimbalRollDegree | 0.00（个别 -89.90 为竖拍/横滚异常案例） | 云台横滚 |
| drone-dji:FlightYawDegree / FlightPitchDegree / FlightRollDegree | -46.70 / +4.30 / +6.70 | 飞行器机体姿态（非相机） |
| drone-dji:FlightXSpeed/YSpeed/ZSpeed | 0.0 | 悬停/移动状态，可用于运动模糊筛选 |
| drone-dji:CamReverse / GimbalReverse | 0 / 0 | 云台/相机反向安装标志 |
| drone-dji:ProductName / DroneModel | “Mini4 Pro” / “Mini 3 Pro” | 机型（两种字段名在不同固件出现） |
| drone-dji:DroneSerialNumber / CameraSerialNumber | 1581F4XFC233L0 / 53HFL280M608ZC | 设备追溯 |
| drone-dji:Version | 1.6（Mini 4 Pro）/ 1.5（Mini 3 Pro） | XMP schema 版本 |
| drone-dji:ShutterType | Electronic | 卷帘快门（rolling shutter）来源 |
| drone-dji:UTCAtExposure | 空字符串（实测样张） | 曝光 UTC 时刻；**为空时只能用本地时间+架次日志** |
| drone-dji:SensorTemperature / WhiteBalanceCCT / SensorFPS | 10.0 / 7087 / 1500/100 | 影像一致性/质量诊断 |
| drone-dji:SurveyingMode | 0 | 测绘模式标志（0=普通拍照） |
| drone-dji:CalibratedFocalLength / CalibratedOpticalCenterX/Y / DewarpData / DewarpFlag | ExifTool DJI XMP 标签表列出（原片通常有；Lightroom 导出后可能丢失） | 机内标定/去畸变参数，对内参初始化极有价值 |

字段来源：实测（data/dji/samples/exif_results.json）+ ExifTool DJI 标签表（https://exiftool.org/TagNames/DJI.html，2026-11-08 抓取）。ExifTool 同时列出若干在部分固件中出现的字段（RtkFlag/RtkStdLat/RtkStdLon/RtkStdHgt 等），**Mini 系列一般没有 RTK 数据**。

### 1.3 文件命名与时间
- Mini 4 Pro 原片命名：DJI_YYYYMMDDHHMMSS_NNNN_D.DNG / .JPG（实测 crs:RawFileName = DJI_20240530063649_0003_D.DNG），可作为时间戳交叉校验。
- DateTimeOriginal 无时区；跨设备/跨架次对齐时用拍摄顺序 + GPS 轨迹。

## 2. 视频 SRT 遥测（格式说明）

DJI Fly 拍摄视频时会生成同名 .SRT 字幕文件，逐帧（约 1 帧/条）记录飞行与相机状态。典型结构（**样板，字段名来自 DJI app 输出惯例与社区解析器，需以实拍视频核对；本项目暂未获取到真实 SRT 样本**）：

    1
    00:00:00,000 --> 00:00:00,033
    <lat> <lon> <rel_alt> <abs_alt> <gb_yaw> <gb_pitch> <gb_roll> <iso> <shutter> <fnum> <ev> <ct> <focal_len>

对应字段含义：
| SRT 字段 | 含义 | 备注 |
|---|---|---|
| latitude / longitude | 十进制度 | 单点 GPS，精度同照片 |
| rel_alt / abs_alt | 相对起飞点高度 / 绝对高度（m） | 与照片 RelativeAltitude / AbsoluteAltitude 对应 |
| gb_yaw / gb_pitch / gb_roll | 云台三轴角（°） | 0=北、顺时针为正；-90=垂直向下 |
| iso / shutter / fnum / ev / ct | 曝光参数/色温 | 可用于逐帧曝光一致性检查 |
| focal_len | 等效焦距（mm） | 变焦时变化 |
| 时间戳 | 视频内时间 | 与视频帧号对齐；与照片的相机时间需用同一时钟 |

用途：视频帧抽帧做 3DGS 时，用 SRT 给每帧提供位姿先验（精度同照片 GPS/云台角）；注意视频为 **卷帘快门 + 电子防抖裁切**（部分机型/模式），内参可能与照片不同。

## 3. 坐标转换：WGS84 → 局部 ENU → COLMAP → UE5

### 3.1 DJI 的角度定义
- GimbalYawDegree / FlightYawDegree：**0° = 真北，顺时针为正**（从上方看）。
- GimbalPitchDegree：**0° = 水平，-90° = 垂直向下**。
- GimbalRollDegree：右滚为正（一般接近 0）。
- 注意：机头朝向（FlightYaw）≠ 相机朝向（GimbalYaw）；斜视拍摄时二者不同，位姿先验必须用 Gimbal 角。

### 3.2 局部 ENU 建立
1. 选参考原点（建议用起飞点或场景中心）：(lat0, lon0, h0)。
2. WGS84 经纬度 → ECEF：X=(N+h)cosφcosλ，Y=(N+h)cosφsinλ，Z=((1-e²)N+h)sinφ，N=a/√(1-e²sin²φ)（a=6378137 m，e²=6.69437999014e-3）。
3. ECEF → ENU（东-北-天）：E=-sinλ·dX+cosλ·dY；N=-sinφcosλ·dX-sinφsinλ·dY+cosφ·dZ；U=cosφcosλ·dX+cosφsinλ·dY+sinφ·dZ。
4. 高度基准：DJI AbsoluteAltitude 可能是椭球高或 EGM96 正高（随机型/固件/AltitudeType 变化），与 WGS84 椭球高差可达数十米（中国区域约 10–50 m）。做法：统一用 RelativeAltitude 做局部几何，用 GCP/已知点建立绝对基准；不要混用不同高度基准。

### 3.3 ENU → UE5（与 shared/CONVENTIONS.md 对齐）
项目约定 UE 世界：X 前、Y 右、Z 上，单位 cm，左手系；相机轴 +X 前、+Y 右、+Z 上。
建议映射（摄影测量局部坐标，X=北、Y=东、Z=天）：
- X_ue = N × 100（cm），Y_ue = E × 100（cm），Z_ue = U × 100（cm）；
- 该映射为左手系（N×E=天 → 对应 UE 的 X×Y=Z），需在实现中用投影重投影误差验证（<1 px）。
- 若项目要求“X=东、Y=北、Z=天”，则需翻转 Y 或 Z 保证左手系；**以 CONVENTIONS.md 的第 3 节转换参考实现为准**，本文只给等价坐标定义。

### 3.4 相机位姿构造（用 EXIF/XMP 先验）
1. 相机世界位置 p_w = ENU(相机 GPS 点)（注意：GPS 记录的是飞机位置，云台相机与飞机有杆臂偏移，通常 <0.3 m，3DGS 可忽略）。
2. 相机旋转：先绕 Z 轴 yaw（GimbalYaw，0=北，顺时针+），再绕相机右轴 pitch（GimbalPitch，0=水平，-90=向下），roll 一般取 0。
   - 在“X=北、Y=东、Z=天”的左手系中，前向单位向量 f=(cos yaw·cos pitch, sin yaw·cos pitch, -sin pitch)（pitch 为负时向上计算，注意符号要在代码里用测试固定）。
   - 相机右向量 r 由 f 与世界上方向叉乘归一化得到，再求 up，得到 3×3 旋转矩阵 R_wc；c2w 的旋转部分即 R_wc。
3. 与 COLMAP 的相机系（X 右、Y 下、Z 前，右手）转换：按 CONVENTIONS.md 第 3 节实现，并做重投影验证。
4. 单目尺度：SfM 无尺度，先用 GPS 基线距离做尺度初值：scale = median(||p_prior_i - p_prior_j|| / ||p_sfm_i - p_sfm_j||)，再用 GCP 精化。

### 3.5 估计内参（初值）
- 用 EXIF FocalLength（真实焦距）+ 传感器宽度 + 图像宽度算 fx≈ f/传感器宽 × 图像宽；fy 取同值（方形像素）。
- Mini 4 Pro 48MP 示例：f=6.72 mm、图像宽 8064 px、按官方对角线 FOV 82.1° 反推 fx≈5000/tan(41.05°)≈5790 px（12MP 模式约 2895 px）；cx≈4032、cy≈3024（残差交给 COLMAP 估计）。
- 若原片 XMP 带 CalibratedFocalLength / CalibratedOpticalCenterX/Y / DewarpData，优先用机内标定参数；修图导出后这些字段可能丢失，应保留原片。

## 4. 精度与局限

| 误差源 | 量级（无 RTK Mini） | 对 3DGS/重建的影响 | 缓解 |
|---|---|---|---|
| GPS 水平位置 | 1–5 m（单点定位，实测 Mini 4 Pro GpsStatus=Normal） | 地理配准绝对误差；尺度初值误差 | GCP/已知边长校核；只用 GPS 做配准初值 |
| GPS 高度 | 3–10 m，且椭球高/正高不可靠 | 绝对高程错位 | 用 RelativeAltitude + GCP 建立高程基准 |
| 云台偏航 | 绝对约 1–3°（磁罗盘/融合） | 先验外参旋转误差，影响 SfM 初始化 | 以 SfM 精化结果为准；先验仅作初值 |
| 云台俯仰/横滚 | 官方稳定精度 ±0.01°（补偿后），绝对角估计约 0.5–2° | 斜视位姿先验误差 | 同上 |
| 相机-IMU 时间同步 | 无公开同步机制；照片仅 1 s 级时间戳（部分有亚秒） | 视频抽帧位姿错位 | 用视频 SRT 逐帧遥测对齐；照片用顺序约束 |
| 卷帘快门 | 电子快门；高速移动时几何畸变 | 高层建筑立面轻微“倾斜” | 降低速度、提高快门；SfM 可部分吸收 |
| 曝光时刻 | XMP UTCAtExposure 实测为空 | 多机同步不可行 | 单机按文件顺序/GPS 轨迹对齐 |
| 镜头畸变 | 机内去畸变参数可能被修图软件剥离 | 内参/畸变不准 | 保留原片；用 COLMAP 自标定 |

结论：**不要试图用 EXIF/XMP 直接得到精确外参**。正确用法是：先验做初始化/配准/防呆，几何精度由 SfM/BA 与 GCP 决定。

## 5. “位姿先验 + COLMAP 精化”融合方案（推荐落地流程）

### 5.1 总体流程
1. **解析**：EXIF + drone-dji XMP → 每图 {time, GPS lat/lon/alt, gimbal yaw/pitch/roll, focal, digitalzoom}；转 ENU，得到先验位姿（粗）。
2. **筛选**：剔除 DigitalZoomRatio≠1、GPSStatus=Invalid、模糊（速度/快门估算）的帧。
3. **COLMAP 先验重建**（官方支持）：
   - colmap feature_extractor（自动提取 EXIF GPS 并存为数据库中的 pose prior）；
   - colmap exhaustive_matcher（或 sequential_matcher，按时间顺序，适合航带）；
   - colmap pose_prior_mapper（使用 GPS 先验做重建，比纯 incremental 更稳，尤其弱纹理/大场景）。
4. **对齐/配准**：colmap model_aligner --ref_is_gps 1 --alignment_type ecef --alignment_max_error 3.0，把模型用 RANSAC 相似变换对齐到地理坐标（至少 3 张有 GPS 的图）。
5. **精化**：用 GCP/已知边长做尺度与高程残差检查；必要时自写 Ceres/g2o 加“GPS 弱约束 + 云台角弱约束”的全局 BA（先验权重按上表精度设）。
6. **交付**：输出 COLMAP 稀疏模型（cameras/images/points3D）+ 先验 JSON（c2w、时间戳、云台角），供 3DGS 训练以 COLMAP 初始化的方式读取；同时按 CONVENTIONS.md 转 UE 坐标。

### 5.2 不依赖 COLMAP 先验的兜底方案
- 若 COLMAP pose_prior_mapper 不可用（旧版本/平台问题）：先常规 SfM 重建，再用 Umeyama（相似变换）+ RANSAC 把 SfM 相机中心对齐到 GPS 坐标（3σ 剔除），得到尺度与朝向，再喂给 3DGS。
- 若 SfM 因弱纹理失败：用云台角 + 高度构造“航带先验位姿”直接初始化 3DGS（风险较高，只建议合成/补拍验证用）。

### 5.3 与 3DGS 训练衔接
- 3DGS（gaussian-splatting/gsplat）要求 COLMAP 兼容的 images.bin/cameras.bin/points3D.ply 或 transforms.json（NeRF 格式）。
- 推荐：先用 COLMAP 得到精化位姿与稀疏点云 → 转 transforms.json（含 fx/fy/cx/cy、c2w）→ 训练时固定相机位姿（不做位姿优化）或仅微调。
- 验证：留出 10–20% 视角（空间块划分），对比“先验初始化”与“纯 COLMAP”两种输入的 PSNR/SSIM 与几何完整性。

## 6. 参考与证据
- ExifTool DJI 标签表：https://exiftool.org/TagNames/DJI.html（2026-11-08 抓取）
- COLMAP FAQ（pose priors with GPS / model_aligner）：https://colmap.github.io/faq.html（2026-11-08 抓取）
- 实测样张与字段值：data/dji/samples/exif_results.json（详见 04）
- MSDK v5.7.0 支持写入/读取自定义 XMP（setMediaFileXMPCustomInfo / pullXMPFileDataFromCamera）：MSDK V5 Release Notes（data/dji/raw/text/relnotes_all.txt）
- 视频 SRT：DJI Fly 输出格式（样板，待实拍核对；见第 2 节说明）
