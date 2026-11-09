# pipeline/ENV.md -- 3DGS 重建流水线环境记录（实测）

记录时间: 2026-11-08
主机: Windows 11 26200 / 32 核 / 16 GB RAM / NVIDIA RTX 5060 Laptop 8 GB (sm_120)
Python: 3.14.6（全局安装，torch 已预装）
项目 venv: dji_ue5_3dgs/pipeline/.venv（python -m venv --system-site-packages，复用全局 torch，避免重复下载）

## 1. 环境搭建（可复现）

```powershell
# 项目根目录
powershell -ExecutionPolicy Bypass -File pipeline\setup_env.ps1
# 或强制重建 venv
powershell -ExecutionPolicy Bypass -File pipeline\setup_env.ps1 -Force
```

setup_env.ps1 动作：
1. 用全局 python 创建 `pipeline/.venv»（--system-site-packages）
2. `pip install -r requirements.txt»（pycolmap / plyfile / scipy / tqdm）
3. 导入自检并打印各库版本（本文件第 2 节即实测输出）

## 2. 实测版本（`.venv\Scripts\python.exe» 自检输出）

| 组件 | 版本 | 来源 |
|---|---|---|
| Python | 3.14.6 | 全局 pythoncore-3.14-64 |
| torch | 2.13.0+cu130 | 全局 site-packages（复用） |
| torch CUDA | 13.0，`torch.cuda.is_available()=True» | 实测 |
| GPU | NVIDIA GeForce RTX 5060 Laptop GPU (8 GB, sm_120) | nvidia-smi |
| numpy | 2.4.4 | 全局 |
| scipy | 1.18.1 | venv 安装 |
| opencv-python | 5.0.0（cv2 5.0.0） | 全局 |
| Pillow | 12.2.0 | 全局 |
| matplotlib | 3.11.2 | 全局 |
| imageio-ffmpeg | 0.6.0 | 全局（提供 ffmpeg 可执行文件，视频抽帧用） |
| exifread | 3.5.1 | 全局（EXIF 解析） |
| pycolmap | 4.2.1（cp314 win_amd64 wheel） | venv 安装 |
| plyfile | 1.1.5 | venv 安装 |
| tqdm | 4.70.1 | venv 安装 |
| 系统 ffmpeg / exiftool | 无 | 用 imageio-ffmpeg / exifread 替代 |

自检命令与输出（原始）：

```
.venv\Scripts\python.exe -c "import torch,pycolmap,scipy,cv2;print(torch.__version__, pycolmap.__version__, scipy.__version__, cv2.__version__)"
2.13.0+cu130 4.2.1 1.18.1 5.0.0
```

## 3. gsplat（可选 CUDA 光栅化器后端）探测结论

* `pip install gsplat==1.5.3» 成功（py3-none-any wheel，运行期用 torch.utils.cpp_extension JIT 编译 CUDA 扩展）。
* 本机没有系统级 CUDA Toolkit（无 nvcc、无 CUDA_HOME）；通过 pip 安装了 CUDA 13 工具链：
  `nvidia-cuda-nvcc 13.5.37 / nvidia-cuda-runtime 13.5.37 / nvidia-cuda-cccl 13.3.5.0.6 / nvidia-nvvm 13.5.37»
  实体位于 `<venv>/Lib/site-packages/nvidia/cu13/»（含 bin/nvcc.exe、include/、lib/x64/cudart.lib、nvvm/bin/cicc.exe），
  该目录可直接作为 CUDA_HOME。
* 状态：`import gsplat» 成功但 `gsplat.cuda._backend._C is None»（gsplat 自身检测不到 CUDA toolkit → 禁用），
  torch cpp_extension 冒烟（load_inline CUDA）在 vcvars64 环境下未跑通（MSVC 14.51 + nvcc 13.5 组合），
  3 次尝试的日志见 `logs/pipeline/gsplat_attempt*.log»。
* 结论（如实记录）：本机 gsplat 路线未验证成功（受限于无系统 CUDA Toolkit 与 MSVC/nvcc 组合），
  因此训练默认走纯 PyTorch 光栅化器（`pipeline/puretorch_splatting/»，无需编译），gsplat 保留为可选后端
  （`--backend gsplat»），若后续补齐 CUDA Toolkit 可直接切换。

## 4. 资源使用

* 训练分辨率 480x360（res-scale 0.5）/ 640x480（capture 数据 res-scale 0.4）：显存峰值 < 1.5 GB
  （Ollama 卸载后可用 ~7 GB；`POST http://localhost:11434/api/generate {"model":"qwen35-16k:latest","keep_alive":0}» 为非破坏性释放方式）。
* 纯 PyTorch 光栅化器在 480x360 / 6 万高斯 / 64 tile 候选下：forward ~52 ms，fwd+bwd ~225 ms（含首次 warmup，实测有波动），
  显存峰值 ~0.56 GB（见 RESULTS.md 基线表）。
