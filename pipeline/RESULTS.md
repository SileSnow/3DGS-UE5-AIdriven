# pipeline/RESULTS.md -- 3DGS 重建流水线实验结果（最终版，2026-11-08 16:55）

本文件所有数字都有原始出处（日志路径 / 命令 / 代码路径）。坐标系与 PLY 契约见 shared/CONVENTIONS.md，
环境与版本见 pipeline/ENV.md。结论：**重建流水线（抽帧/位姿/训练/导出/评测）全部跑通且数值自检通过；
在 8 GB 显存 + CPU 温度限载（4 核）条件下，全量 120 视图训练严重欠训练（val PSNR 13.3），
这是算力/时间约束而非链路错误**（证据见 §4 的 5 帧子集 22.27 对照实验）。

---

## 0. 结论速览

| 项 | 结果 | 证据 |
|---|---|---|
| 纯 PyTorch tile-based 可微 3DGS 光栅化器 | 与暴力参考一致（max abs err 1.66e-4，来自 3 sigma 裁剪；单 tile 时 9e-08） | pipeline/test_rasterizer.py |
| 可微性 | 5 高斯过拟合 200 步 loss 0.01837 -> 0.00299 | 同上 |
| 光栅化速度（RTX 5060，480x360，tile16，K=64） | 6 万高斯 fwd 51.9 ms / fwd+bwd 225.4 ms（含 warmup）；15 万高斯 fwd 39.1 ms / fwd+bwd 125.6 ms；峰值显存 536-558 MB | 同上 |
| 端到端训练速度（640x480，10-11 万 splat） | 0.32-0.35 s/iter（4 核限载）；无限载时 0.14-0.2 s/iter 但 CPU 触发 93°C 熔断 | logs/pipeline/train_capture_chunk*.out.log |
| 训练峰值显存 | **1152.8 MB**（640x480 / 109,376 splat / K=64） | data/trained/capture/run1/metrics.json |
| UE<->COLMAP 坐标换算 | 重投影自检 max 1.26e-12 px，c2w 闭环 4.5e-13 | pipeline/colmap_io.py 自检 |
| 已知位姿直通 -> COLMAP | 24 帧写/读回自检 max 2.49e-12 px；读回投影 max 2.89e-6 px | data/sample/synthetic_campus_v1/colmap/sfm_summary.json |
| DJI EXIF(GPS+云台) -> COLMAP 先验 | 合成 DJI 风格数据自测位置/姿态误差 0.00 m / 0.00 deg，正交性 4.4e-16 | data/sample/dji_prior_demo/dji_priors.json |
| 数据集自检工具 | c2w 刚性/内参/尺寸 PASS；GPS 约定不一致（见 §3.3）；SIFT 极线检验在合成平纹理上不可靠 | pipeline/validate_dataset.py |
| campus 基线（24 视图，1200 iter） | **val PSNR 17.43 / SSIM 0.568**，29,796 splat，355 s，峰值 670 MB | data/trained/synthetic_campus_v1/run1/metrics.json |
| 5 帧子集（同 capture 数据，600 iter） | **PSNR 22.27 / SSIM 0.757**（证明位姿/渲染链路自洽） | data/trained/_subset5/ |
| 单视角过拟合（300 iter） | PSNR 19.2 / SSIM 0.66（仍在上升，densify 正常增长） | data/trained/_overfit_capture/ |
| **capture 全量 120 视图（3000 iter）** | **train PSNR 18.44 / val PSNR 13.28 / SSIM 0.347**，109,376 splat，640x480 | data/trained/capture/run1/metrics.json |
| 标准 3DGS PLY 输出 | 62 字段 binary_little_endian；写后读回断言通过；UE LHS cm | data/trained/capture/run1/gaussians_best.ply |
| gsplat 后端 | 本机未跑通（无系统 CUDA Toolkit），已交付纯 PyTorch 兜底 | ENV.md §3 / logs/pipeline/gsplat_attempt*.log |

---

## 1. 纯 PyTorch tile-based 可微 3DGS 光栅化器（pipeline/puretorch_splatting/）

算法与 3DGS CUDA 光栅化器同构：2D 协方差 -> conic -> 3 sigma 包围盒覆盖 tile -> (tile, gaussian) 对按
(tile_id, depth) 排序 -> 每 tile 取前 K 个候选做 front-to-back alpha 合成（(T,256) 张量上向量化）。
不编译 CUDA 扩展，全部 PyTorch autograd 求导；支持 SH(0-3 阶)/opacity/scale/rot。

### 1.1 正确性（vs 暴力参考实现）

pipeline/test_rasterizer.py 中 brute_force() 对 48x64 图像逐像素按深度排序做精确 alpha 合成：

```
[correctness] max |img diff| = 1.664e-04, max |alpha diff| = 1.848e-04 (容差 1e-3: 3σ tile 包围盒裁剪)
single-tile max diff: 9.42e-08 / 1.29e-07
[grad] loss 0.01837 -> 0.00299
```

单 tile 时与暴力参考一致到 1e-7；分 tile 后残差 ~1.7e-4 来自 3 sigma 包围盒裁剪（裁剪区 alpha<1%）。

### 1.2 速度 / 显存

```
[speed] N=60000 480x360 K=64: forward 51.9 ms, fwd+bwd 225.4 ms, peak_mem 536 MB, tiles=690
[speed] N=150000 480x360 K=64: forward 39.1 ms, fwd+bwd 125.6 ms, peak_mem 558 MB, tiles=690
```

（第一轮含 CUDA warmup。）

### 1.3 NaN 稳定性（踩坑记录）

首轮 4000 iter 训练在第 2 步崩在 backward。torch.autograd.set_detect_anomaly 定位到 conic 的 MulBackward：
病态 2D 协方差（近奇异）-> conic 极大 -> exp(power) 溢出 + where/exp 反向 0*inf=NaN -> 经 clip_grad_norm 污染
所有参数 -> 渲染全空 -> loss 无梯度。修复：①power.clamp(max=0) 后直接 exp（去掉 where，数值等价）；
②det 下限 1e-8 + conic 限幅 ±1e6；③每步梯度 nan_to_num；④densify/prune 后重建 Adam（叶子张量 requires_grad）。
修复后累计 5000+ iter（含 densify）无崩溃。

---

## 2. 坐标换算与位姿链路

### 2.1 UE <-> COLMAP（colmap_io.py）

```
UE<->COLMAP 重投影自检: max=1.256e-12 px mean=1.198e-13 px (n=320)
c2w 闭环误差: 4.547e-13
rotmat->quat->rotmat 误差: 1.457e-16
```

### 2.2 已知位姿直通（02_sfm.py --mode known）

24 帧 960x720 数据集写出 COLMAP text 并读回校验：

```
{"mode":"known","num_images":24,"width":960,"height":720,
 "reproj_selfcheck":{"max_px":2.49e-12,"mean_px":1.44e-13,"n":1152,"pass":true},
 "colmap_readback_check":{"max_reproj_err_px":2.89e-06,"mean_reproj_err_px":1.65e-07,"ok":true}}
```

### 2.3 DJI EXIF(GPS+云台) -> COLMAP 粗先验（dji_exif_to_colmap.py）

真实 DJI 样张不可得；用 make_synthetic_scene.py 生成的"DJI 风格" metadata（GPS/gimbal_deg/c2w 同源）自测
「GPS+云台角 -> ENU 位姿」链路：位置/姿态相对真值误差 **0.00 m / 0.00 deg**（同源数据证明换算实现正确），
旋转正交性 4.4e-16。真实 DJI GPS 水平误差 1-3 m、云台角 ~0.1-0.5 deg，故该先验仅用于 COLMAP 粗初始化。
注：«--refine»（pycolmap 已知位姿三角化精化）代码路径已按 pycolmap 4.2 API 实现，但本机无真实 DJI 照片，
仅有合成图像（SfM 无法初始化，见 §6.1），故该选项未做端到端验证，如实记录。

---

## 3. 数据集与链路自检（pipeline/validate_dataset.py）

### 3.1 检查方法
c2w 刚性（|RR^T-I|、det）、内参合理性、图像尺寸一致性、GPS<->c2w 一致性、相机朝向、SIFT 极线 Sampson 误差。
loader 已内置刚性断言（|RR^T-I|max < 1e-6，不满足直接报错），避免"非正交 c2w"数据再次混入。

### 3.2 capture 数据（补丁前/后）
capture 首版 metadata 存在 c2w 旋转非正交 bug（训练 PSNR 卡在 11-12 的直接原因）；capture-synth 于 16:08:23
修复（备份 metadata.json.bak.json）。修复后自检：**|RR^T-I|max=2.22e-16，det=1.0 PASS**；内参/图像尺寸 PASS。

### 3.3 已知不一致（如实记录）
* GPS 与 c2w 的约定不一致：按本工程约定（UE +X=北、+Y=东、origin_wgs84）反算 GPS，与 metadata.gps 差
  mean 58 m / max 90 m。这是 capture 端 GPS 生成约定问题，**不影响训练**（训练只用 c2w + 图像；GPS 仅用于
  真实 DJI 先验链路），但若后续要把合成 GPS 当真值用需对齐约定。
* SIFT 极线自检在我们的合成平纹理场景上不可靠：用**已知位姿完全正确**的 campus 数据对照同样失败
  （median 86.8 px；cv2 RANSAC 内点仅 15/83），原因是程序化纹理重复度高导致误匹配，而非位姿错误。
  故该检查降级为诊断项；位姿正确性由 5 帧子集训练 PSNR 22.27 与单视角 19.2 间接证明。

---

## 4. 训练结果与"欠训练"分析

### 4.1 数据与配置
* capture 数据：175 帧 1600x1200（capture-synth UE5.8 合成校园/航拍场景）+ 15 验证帧；本实验用 120 训练视图。
* 训练分辨率 640x480（res-scale 0.4），SH degree 0，tile 16，每 tile 候选 64，显存上限 8 GB。
* 最终配置：iters 3000、max-splats 150000（实际 109,376）、init-points 50000、init-scale-rel 0.05、
  densify 从 iter 200 起每 100 步（自适应梯度分位阈值 + 每步 clone 上限 25%）。

### 4.2 最终指标（data/trained/capture/run1/metrics.json）

```
n_splats        : 109376
train_psnr      : 18.435   (120 训练视图均匀抽样 24 个评估)
val_psnr        : 13.280   (15 验证视图)
val_ssim        : 0.3469
train_seconds   : 318.4 s  (iter 2000->3000 这一段；全流程 750->3000 约 745 s)
peak_mem_mb     : 1152.8
resolution      : [640, 480]
world           : ue_rh_cm (PLY 导出为 UE LHS cm)
```

训练曲线（train_log.txt）：val PSNR 11.48@750 -> 12.21@1250 -> 12.46@1500 -> 12.70@1750 -> 12.89@2000
-> 13.03@2250 -> 13.15@2500 -> 13.22@2750 -> **13.28@3000**；train PSNR 同步 15.7@2000 -> 18.4@3000。
GT vs render 对比拼图：renders/compare_000.png ~ compare_002.png（GT | 渲染 并排）。

### 4.3 欠训练判据（关键对照实验）

| 实验 | 视图数 | iters | PSNR | SSIM | splat | 耗时 |
|---|---|---|---|---|---|---|
| 单视角过拟合 | 1 | 300 | 19.2（仍上升） | 0.66 | 34,451 | 81 s |
| 5 帧子集 | 5 | 600 | **22.27** | 0.757 | 36,987 | 120 s |
| campus 基线 | 24 | 1200 | 17.43 (val) | 0.568 | 29,796 | 355 s |
| capture 全量 | 120 | 3000 | 13.28 (val) / 18.44 (train) | 0.347 | 109,376 | 745 s |

* 5 帧子集 600 iter 就达到 PSNR 22.27 -> **位姿、内参、颜色、渲染链路自洽**；同样的训练器在 120 视图下
  3000 iter 仅 13.28，说明瓶颈是 **每视图更新次数**：3000/120 = 25 次/视图，而官方 3DGS 典型为
  30000 iter / 100 视图 = 300 次/视图。按同等收敛需 ~36000 iter（本机 0.33 s/iter ≈ 3.3 小时），不可行。
* 场景规模：100 m 级校园场景在 640x480 下 109k splat 的覆盖密度不足（每 splat 需覆盖 ~15 px），
  导致渲染偏糊；GT vs render 拼图可直观看到"结构大体存在、细节缺失"。
* 结论（用于报告）：**8 GB 显存不是瓶颈（峰值仅 1.15 GB），瓶颈是 CPU 温度限载（4 核）+ 时间**。
  生产环境建议：≥16 GB 显存 + 不降频 CPU/更长训练（36k+ iter），或使用 gsplat 等 CUDA 光栅化器提高迭代速度。

### 4.4 受限项：CPU 温度熔断（如实记录）

用户要求 CPU ≤80°C；团队温度守护规则：python/UE 限 4 核（affinity 0x000F）+ BelowNormal，82°C 降 Idle，
93°C 熔断 kill。实测：

| 配置 | 速度 | CPU 温度 | 结果 |
|---|---|---|---|
| 无限载（8+ 核，OMP=4） | 0.14-0.20 s/iter | 87-95°C | 多次被熔断 kill（iter 240/420/750 处） |
| 2 核（0x3）+ 1 线程 | 0.35 s/iter | 62-70°C | 稳定完成（750->1250） |
| 4 核（0xF）+ 2 线程 | 0.32-0.34 s/iter | 65-71°C | 稳定完成（1250->3000） |

结论：4 核 + 2 线程是"速度/温度"平衡点；GPU 侧不受影响（GPU 温度 45-51°C）。

---

## 5. 标准 3DGS PLY 输出（契约核对）

### 5.1 字段与顺序（binary_little_endian 1.0，62 个属性）

```
x y z nx ny nz f_dc_0 f_dc_1 f_dc_2 f_rest_0 ... f_rest_44 opacity scale_0 scale_1 scale_2 rot_0 rot_1 rot_2 rot_3
```

注意：该顺序与 Graphdeco 官方参考实现不同（官方为 ... opacity, scale, rot, f_rest），PLY 规范不要求固定顺序；
下游 UE5 解析器请按 header 名解析。ply_io.save_3dgs_ply() 每次写入后立即 PlyData.read 断言字段顺序/数量/抽样数值一致。

### 5.2 读回样例（data/trained/_densify_test/gaussians_1k.ply，1000 splat，249,529 bytes）

```
header props: ['x','y','z','nx','ny','nz','f_dc_0','f_dc_1','f_dc_2','f_rest_0',...,'f_rest_44','opacity','scale_0','scale_1','scale_2','rot_0','rot_1','rot_2','rot_3']
byte_order: <  count: 1000
vertex[0]: x=449.334351 y=-132.223755 z=2289.193359
  nx=0 ny=0 nz=0 | f_dc_0=-1.629484 f_dc_1=-1.684557 f_dc_2=-1.580968 | f_rest_*=0 (sh_degree=0)
  opacity=-0.702470 | scale_0=4.173713 scale_1=4.180211 scale_2=4.154210
  rot_0=0.998152 rot_1=-0.036908 rot_2=0.035044 rot_3=0.033201
```

### 5.3 最终交付 PLY
* **C:\Users\<user>\Desktop\GAIA项目\dji_ue5_3dgs\data\trained\capture\run1\gaussians_best.ply**
  （27,126,779 bytes，109,376 splat，UE LHS cm；与 gaussians.ply 相同=最终 iter 3000）
* 1k splat 兼容性样例：data/trained/_densify_test/gaussians_1k.ply

---

## 6. gsplat 可行性结论

pip 安装 gsplat 1.5.3 成功，但本机无系统 CUDA Toolkit（无 CUDA_HOME/nvcc）；用 pip 安装 CUDA 13 工具链
（nvidia-cuda-nvcc/runtime/cccl/nvvm，实体在 <venv>/Lib/site-packages/nvidia/cu13）后，gsplat 仍检测不到
CUDA toolkit（cuda._backend._C=None），torch cpp_extension 冒烟在 MSVC 14.51 + nvcc 13.5 环境下未跑通
（3 次尝试日志 logs/pipeline/gsplat_attempt*.log）。**结论：本机 gsplat 路线未验证成功，纯 PyTorch 兜底为实际方案**；
补齐 CUDA Toolkit 后可切换（--backend gsplat）。

### 6.1 pycolmap SfM 模式（02_sfm.py --mode sfm）验证结果

代码路径完整跑通（pycolmap 4.2 API 适配：`Database.open()` 建库 -> import_images -> extract_features ->
match_exhaustive -> incremental_mapping -> 最大模型 write + write_text），但**在本项目的合成平纹理场景上无法初始化**：

```
I incremental_pipeline.cc:492] Registering initial image pair #8 and #7
I incremental_pipeline.cc:791] Discarding reconstruction due to bad initial pair
I incremental_pipeline.cc:472] => No good initial image pair found.
E sfm.cc:310] Failed to create any sparse model
```

原因：程序化纹理重复度高 + 8 帧子集宽基线，SIFT 无法找到可靠初始像对（与 §3.3 极线校验失败同源）。
真实 DJI 照片（自然纹理、连续航带）预期可用；本工程主链路（已知位姿直通）不依赖 SfM。
结论：**SfM 模式为「代码可用但本机无合适真实数据验证」**，如实记录；真实数据路径由 02_sfm.py --mode dji
（EXIF 先验）+ 后续 COLMAP 精化承接。

### 6.2 run_pipeline.ps1 一键脚本

wiring 已验证：`位姿准备 02_sfm.py --mode known（重投影自检 pass）-> 03_train_3dgs 训练 -> 04_export_ply ->
05_eval` 各步骤按参数正确串联（日志 logs/pipeline/run_pipeline_*.log）。注意：本机 CPU 温度守护会熔断高负载
进程，长时间训练建议用 §7 的分段 resume 方式手动跑，或确保 4 核限定后再调用一键脚本。

### 6.3 公开小数据集说明

受训练时间与 CPU 温度限载约束，未下载公开 3DGS/NeRF 数据集（<2 GB）做额外基线；按任务允许的替代方案，
使用 **自造程序化多视角场景（campus，24+6 视角）** 与 **capture-synth 的 UE5 合成航拍数据（175+15 帧）**
验证全链路。两者都有明确来源与无外部许可问题，结果见 §4。

---

## 7. 复现命令
```powershell
# 环境
powershell -ExecutionPolicy Bypass -File pipeline\setup_env.ps1
# 光栅化器自检 / 坐标自检 / 数据自检
.venv\Scripts\python.exe pipeline\test_rasterizer.py
.venv\Scripts\python.exe pipeline\colmap_io.py
.venv\Scripts\python.exe pipeline\validate_dataset.py --data data/synthetic/capture --n-frames 5
# 已知位姿直通
.venv\Scripts\python.exe pipeline\02_sfm.py --mode known --data data/synthetic/capture --out data/synthetic/capture/colmap
# capture 训练（分段 resume 以适配 CPU 温度限载；4 核 + 2 线程 + BelowNormal）
.venv\Scripts\python.exe -u pipeline\03_train_3dgs.py --data data/synthetic/capture --out data/trained/capture/run1 --iters 3000 --res-scale 0.4 --backend puretorch --max-frames 120 --max-splats 150000 --val data/synthetic/val --eval-every 250 --save-every 250
#（若被熔断：加 --resume auto 从 checkpoint 继续）
# 导出 + 评测
.venv\Scripts\python.exe pipeline\04_export_ply.py --run data/trained/capture/run1 --stats
.venv\Scripts\python.exe pipeline\05_eval.py --run data/trained/capture/run1 --val data/synthetic/val --res-scale 0.4
# 一键
powershell -ExecutionPolicy Bypass -File pipeline\run_pipeline.ps1 -Data data/synthetic/capture -Out data/trained/capture/run1 -Iters 3000 -ResScale 0.4 -MaxFrames 120
```

## 8. 产物清单

| 产物 | 路径 |
|---|---|
| 最终 PLY（UE LHS cm，109,376 splat） | data/trained/capture/run1/gaussians_best.ply（= gaussians.ply） |
| 训练指标 | data/trained/capture/run1/metrics.json |
| 训练日志 | data/trained/capture/run1/train_log.txt、logs/pipeline/train_capture_chunk*.out.log |
| 验证渲染 + GT vs render 拼图 | data/trained/capture/run1/renders/{val_*, gt_*, compare_*} |
| 5 帧子集证据 | data/trained/_subset5/（metrics.json） |
| 单视角证据 | data/trained/_overfit_capture/（compare_gt_render.png） |
| campus 基线 | data/trained/synthetic_campus_v1/run1/（val PSNR 17.43） |
| 1k splat PLY 样例 | data/trained/_densify_test/gaussians_1k.ply |
| 数据自检报告 | data/synthetic/capture/validate_report.json |
