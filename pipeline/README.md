# pipeline/ -- 3DGS 重建流水线（dji_ue5_3dgs）

把「多视角图像 + 相机位姿」变成标准 3DGS PLY，并给出 held-out 评测。设计目标：
在没有系统 CUDA Toolkit 的 Windows 本机也能跑通（纯 PyTorch 可微光栅化器），同时保留 gsplat 可选后端。

## 目录

| 文件 | 作用 |
|---|---|
| setup_env.ps1 / requirements.txt | 项目本地 venv（--system-site-packages 复用 torch）+ 依赖安装；实测版本见 ENV.md |
| 01_extract_frames.py | 视频抽帧（imageio-ffmpeg）+ Laplacian 清晰度筛选；照片目录索引 + EXIF/DJI XMP 读取 -> metadata.json |
| 02_sfm.py | 位姿/稀疏重建：known（CONVENTIONS metadata.json -> COLMAP，UE<->COLMAP 换算 + 重投影自检）/ sfm（pycolmap 增量重建）/ dji（EXIF 先验） |
| dji_exif_to_colmap.py | 真实 DJI 照片 GPS+云台角 -> COLMAP 粗位姿先验（ENU），`--refine» 用 pycolmap 已知位姿三角化精化 |
| 03_train_3dgs.py | 3DGS 训练主脚本（可微光栅化、SH 颜色、Adam、densify/prune），输出 gaussians.ply + train_log.txt + metrics.json + renders/ |
| 04_export_ply.py | 从 checkpoint 导出标准 3DGS PLY（UE LHS cm） |
| 05_eval.py | held-out PSNR / SSIM + 渲染图 |
| run_pipeline.ps1 | 一键端到端（位姿准备 -> 训练 -> 导出 -> 评测） |
| puretorch_splatting/ | 纯 PyTorch tile-based 可微 3DGS 光栅化器（rasterizer.py / renderer.py / sh.py） |
| colmap_io.py | COLMAP 读写 + UE<->COLMAP 坐标换算 + 重投影自检 |
| dataset.py | 统一数据集加载（CONVENTIONS metadata.json / COLMAP sparse / NeRF transforms.json） |
| ply_io.py | 标准 3DGS PLY 读写（含写入后读回断言） |
| make_synthetic_scene.py | 程序化多视角"校园"场景（DJI 航拍风格相机轨迹），用于无真实/合成数据时验证全链路 |
| utils.py | PSNR / SSIM / 图像 IO |
| test_rasterizer.py | 光栅化器正确性（vs 暴力参考）、可微性、速度测试 |

## 快速开始

```powershell
# 0) 环境（一次）
powershell -ExecutionPolicy Bypass -File pipeline\setup_env.ps1

# 1) 已知位姿直通（CONVENTIONS metadata.json -> COLMAP + 重投影自检）
.venv\Scripts\python.exe pipeline\02_sfm.py --mode known --data data/synthetic/capture --out data/synthetic/capture/colmap

# 2) 训练（纯 PyTorch 光栅化器）
.venv\Scripts\python.exe pipeline\03_train_3dgs.py --data data/synthetic/capture --out data/trained/capture/run1 --iters 4000 --res-scale 0.4 --backend puretorch --max-frames 200 --eval-every 500 --save-every 1000

# 3) 导出 PLY + 4) 评测
.venv\Scripts\python.exe pipeline\04_export_ply.py --run data/trained/capture/run1 --stats
.venv\Scripts\python.exe pipeline\05_eval.py --run data/trained/capture/run1 --val data/synthetic/val --res-scale 0.4

# 一键（以上 1-4 合并）
powershell -ExecutionPolicy Bypass -File pipeline\run_pipeline.ps1 -Data data/synthetic/capture -Out data/trained/capture/run1 -Iters 4000 -ResScale 0.4 -MaxFrames 200
```

其他常用入口：

```powershell
# 程序化合成场景（24 训练 + 6 验证视角，960x720，UE cm / CONVENTIONS schema）
.venv\Scripts\python.exe pipeline\make_synthetic_scene.py --out data/sample/synthetic_campus_v1 --width 960 --height 720 --n-train 24 --n-val 6

# 视频抽帧（2 fps + 清晰度筛选保留 >= 0.4*median 的帧）
.venv\Scripts\python.exe pipeline\01_extract_frames.py --video DJI_0001.MP4 --out data/dji/video1 --fps 2 --sharpness-rel 0.4

# DJI 照片 EXIF 先验位姿（真实数据链路）
.venv\Scripts\python.exe pipeline\dji_exif_to_colmap.py --photos data/dji/photos --out data/dji/colmap_prior --refine

# 光栅化器自检（正确性 / 梯度 / 速度）
.venv\Scripts\python.exe pipeline\test_rasterizer.py
```

## 坐标系与 PLY 契约

* 训练数据集若为 CONVENTIONS 合成数据（`coord_system: UE_LHS_Zup_cm»）：内部换算为右手世界 `(x, -y, z) cm» 训练，
  导出 PLY 时转回 UE LHS cm（+X 前/北, +Y 右/东, +Z 上），与 UE5 端直接对接。
* COLMAP/NeRF 数据集：PLY 坐标与训练数据世界系一致（不做 UE 转换），见 `04_export_ply.py --world»。
* PLY 字段（binary_little_endian 1.0，共 62 个属性，顺序如下）：
  `x y z nx ny nz f_dc_0 f_dc_1 f_dc_2 f_rest_0..44 opacity scale_0 scale_1 scale_2 rot_0..3»
  - `rot_*» 为四元数 (w,x,y,z)；`scale_*» 为 log 尺度；`opacity» 为 sigmoid 前 logit；
  - `f_dc» 为原始 SH DC 系数（查看端按 3DGS 标准 rgb = 0.5 + C0*f_dc + ... 解码）；
  - 训练 sh_degree < 3 时 `f_rest_*» 写 0（等价于无高阶 SH 项）。
* 注意：该属性顺序与 Graphdeco 官方参考实现（`... opacity, scale, rot, f_rest»）不同（PLY 规范不要求固定顺序），
  下游解析器请按 header 字段名解析；`ply_io.save_3dgs_ply()» 每次写入后都会读回断言字段顺序/数值一致。

## 训练默认参数（8 GB 显存适配）

* 分辨率：`--res-scale» 相对原图缩放（960x720 -> 480x360 = 0.5；1600x1200 -> 640x480 = 0.4）
* splat 上限：`--max-splats 200000»；tile 候选数 `--max-per-tile 64»；tile 16x16
* 初始点数 `--init-points 30000»；SH 阶数 `--sh-degree 0»（可 0-3）
* densify：iter 500 起、每 100 次、到总迭代数 55% 结束；梯度阈值默认 **1e-8**（像素单位，可用 --grad-thresh 覆盖）；剪枝 opacity<0.005

## 已知限制

* 纯 PyTorch 光栅化器每 tile 最多取 64 个前排候选（与 CUDA 版实现同构但受限），极端密集场景可能出现少量丢样；
  3 sigma 包围盒外的 alpha < 1%，按 `--max-radius» 裁剪（默认 16 px）。
* gsplat 后端未在本机验证成功（见 ENV.md §3），如需速度可补齐 CUDA Toolkit 后切换。
* 无真实 DJI 样张：EXIF/XMP 解析路径用合成 DJI 风格 metadata 自测（见 RESULTS.md）。
