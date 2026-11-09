# 数据说明（data/）

> **大数据不入库**：本目录只保留 `samples/` 小样例；其余数据由脚本生成或保留在作者本地。

## 1. 目录清单

| 路径 | 大小（本机实测） | 是否入库 | 说明 |
|---|---|---|---|
| `data/samples/` | ~3 MB | ✅ | 仓库内小样例（见下） |
| `data/synthetic/` | ~890 MB | ❌ | UE5 合成航拍数据（capture 190 帧 / mission 16 帧 / mission_p1 20 帧） |
| `data/trained/` | ~350 MB | ❌ | 3DGS 训练产物（PLY / renders / 日志） |
| `data/sample/` | ~22 MB | ❌ | Phase-0 开发期小数据集（仅从中抽取元数据到 samples） |
| `data/dji/` | ~144 MB | ❌ | 真实 DJI 样片 + 官方资料抓取证据（版权/体积原因不入库） |

## 2. 仓库内样例（data/samples/）

见 [samples/README.md](samples/README.md)。用途：schema 参考、README 配图、快速验证读取逻辑。

## 3. 如何重新生成大数据

```powershell
cd dji_ue5_3dgs

# ① UE5 合成航拍数据集（~2-3 分钟，需 GPU + UE5.8）
capture\run_capture.ps1 -Mode full

# ② Phase-1 Mission 渲染（需 UE5.8；示例任务）
powershell -ExecutionPolicy Bypass -File llm_drone\ue5_mission\run_mission.ps1 ^
  -Mission llm_drone\spec\sample_mission.json -Out data\synthetic\mission

# ③ 3DGS 训练（需 pipeline venv）
pipeline\.venv\Scripts\python.exe pipeline\03_train_3dgs.py ^
  --data data/synthetic/capture --out data/trained/capture/run1 --iters 3000
```

## 4. 数据契约

- 合成/任务数据的 `metadata.json`（c2w / GPS / 云台 / 时间戳）与 3DGS PLY 格式见
  [shared/CONVENTIONS.md](../shared/CONVENTIONS.md)。
- 任务 Mission JSON 格式见 [llm_drone/spec/PROTOCOL.md](../llm_drone/spec/PROTOCOL.md) §6。
- 演示 run 证据（不依赖大数据，可直接复核）：`llm_drone/demo/runs/`。

## 5. 真实 DJI 数据说明

早期调研使用过 DJI 官方公开样片与网页资料，原始文件保留在作者本地 `data/dji/`（体积大、版权原因不入库）：
- `data/dji/samples/`：公开样片（Mini 4 Pro / Mini 3 Pro / Mini 2）；
- `data/dji/raw/`：SDK 兼容表 / API Reference / Release Notes 等官方页面抓取（证据索引见
  [docs/research/references.md](../docs/research/references.md)）。

## 6. 数据安全与合规

- 真机飞行数据可能包含个人信息/敏感区域：入库前请脱敏或仅保留元数据。
- 不要把未脱敏的原始航拍照片/视频提交到公开仓库。
