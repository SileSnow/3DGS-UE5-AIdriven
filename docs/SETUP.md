# 环境搭建（SETUP）

> 本项目验证环境：**Windows 11**，但在 Linux/macOS 上 Phase-1 的 Python 部分可原样运行（纯标准库）。
> 详细版本事实见 [pipeline/ENV.md](../pipeline/ENV.md) 与 [capture/README.md](../capture/README.md)。

## 1. 基础环境

| 项 | 要求 | 备注 |
|---|---|---|
| OS | Windows 11（Phase-0 UE5/capture 需要） | Phase-1 Python 跨平台 |
| Python | 3.12+（本项目 3.14.6 验证） | `llm_drone/` **仅标准库**，无需 pip install |
| GPU | NVIDIA（3DGS 训练 + UE5 渲染） | 本项目 RTX 5060 Laptop 8GB / sm_120 / torch 2.13+cu130；CUDA Toolkit 13.5 可选（见 §3.1） |
| 内存 | 16 GB+ | 3DGS 训练与 UE5 同时跑较紧张，建议串行 |
| Unreal Engine | **5.8.4** | Phase-0/UE5 任务渲染；需 Visual Studio 2026 (MSVC 14.51) 编译 C++ |
| DJI 手机 App 开发 | Android Studio + JDK 17 + Android SDK 35 | 仅 Phase-2 真机桥需要 |

## 2. Phase-1（LLM 调度无人机）

```powershell
# 1) 验证 Python（无需安装第三方包）
python --version                       # 3.12+
cd dji_ue5_3dgs/llm_drone
python -m unittest discover -s tests -v    # 应输出 ~118 tests OK

# 2)（可选）安装 Ollama + 拉取模型（真实 LLM 演示）
#    https://ollama.com/download
ollama pull qwen3.5:4b
ollama list

# 3) 运行仿真 Agent
python -m sim.server --port 8765 --time-scale 20
```

> LLM 调用参数建议：`options={num_ctx:16384, num_predict:1024, temperature:0.1}`。
> 默认 4096 上下文会截断多轮工具结果，导致空响应（见 [orchestrator SUMMARY](../llm_drone/logs/orchestrator/SUMMARY.md) §5）。

## 3. Phase-0（3DGS 流水线）

```powershell
cd dji_ue5_3dgs

# 1) 创建 pipeline venv（--system-site-packages 复用全局 torch，见 pipeline/ENV.md）
powershell -ExecutionPolicy Bypass -File pipeline\setup_env.ps1

# 2) 3DGS 训练（示例：合成数据集）
pipeline\.venv\Scripts\python.exe pipeline\03_train_3dgs.py ^
  --data data/synthetic/capture --out data/trained/capture/run1 ^
  --iters 3000 --res-scale 0.5 --backend puretorch
```

### 3.1 可选：CUDA 后端（gsplat，约 40× 加速）

- 推荐安装 **CUDA Toolkit 13.5**（本机 2026-11-13 实测）：
  ```powershell
  winget install --id Nvidia.CUDA --exact --silent --accept-package-agreements --accept-source-agreements
  ```
  标准路径 `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.5` 是 ASCII 路径，可直接作为 `CUDA_HOME`；
- 实测：安装 4.71 GB，`nvcc 13.5.37`；`torch 2.13.0+cu130` 的 `load_inline` CUDA 扩展编译 79 s 并在 GPU 上跑通；
- 只跑 puretorch 后端则**不需要** CUDA；gsplat 编译还要处理中文路径（源码放 ASCII 目录）和 1.5.3 的两个未用 API，
  详见 [KNOWN_ISSUES.md](KNOWN_ISSUES.md) §C。

## 4. Unreal Engine 5.8.4（Phase-0 + UE5 任务渲染）

1. 安装 UE 5.8.4（Epic Games Launcher）。
2. **中文路径必须用 ASCII junction**，否则 MSVC 会报 C1083：
   ```powershell
   New-Item -ItemType Junction -Path C:\UEW -Target 'C:\Users\<you>\Desktop\GAIA项目'
   ```
   之后所有 UE 工程都通过 `C:\UEW\dji_ue5_3dgs\...` 访问。
3. Phase-0 合成数据：`capture\run_capture.ps1 -Mode full`（详见 [capture/README.md](../capture/README.md)）。
4. Phase-1 Mission 渲染：`llm_drone/ue5_mission\run_mission.ps1 -Mission llm_drone\spec\sample_mission.json -Out data\synthetic\mission`（详见 [ue5_mission/README.md](../llm_drone/ue5_mission/README.md)）。
5. UE 渲染独占 GPU，串行执行，不要同时开多个 UE 实例。

> 本项目 UE5.8.4 侧实现：Blueprint-only 工程 + PythonScriptPlugin；渲染用 SceneCapture2D，导出 1600×1200 PNG。

## 5. Phase-2 真机（未执行，仅前置清单）

| 项 | 要求 |
|---|---|
| 机型 | DJI Mini 4 Pro（推荐）/ Mini 3 / Mini 3 Pro |
| 遥控器 | RC-N2（MSDK v5.13.0+）或 RC-N3（v5.17.0+）；**带屏 RC 2 不支持 MSDK** |
| Android | Android 10+、arm64-v8a、USB Host/Accessory |
| 工具链 | Android Studio Narwhal 3+ / JDK 17 / Gradle 8.12 / AGP 8.7 / targetSdk 35 |
| DJI 开发者 | developer.dji.com 注册 App（包名一致）→ App Key |
| 空域 | 合法空域、限高 120 m、目视范围、当地报备 |

详细步骤：`llm_drone/msdk_bridge/README.md` 与 `test_protocol.md`。

## 6. 网络与环境注意事项

- Phase-1 全部离线可跑；真实 LLM 需本机 Ollama。
- `data/dji/raw/` 的一手调研证据不入库；如需复核，按 `docs/research/references.md` 的 URL 重新抓取。
- 所有命令均为 UTF-8；Windows 下建议 `chcp 65001`。
