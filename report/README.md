# Phase-0 交付物（report/）

> 阶段主题：**DJI Mini 航拍 → 3DGS 重建 → UE5 集成** 可行性验证（2026-11-08 完成）。

## 主要交付物

| 文件 | 内容 |
|---|---|
| `DJI_Mini_UE5_3DGS_可行性验证报告.md` | 最终可行性报告（约 69 KB） |
| `DJI_Mini_UE5_3DGS_可行性验证_简报.pptx` | 13 页演示简报 |
| `figures/` | 报告图 1-5（PNG） |
| `sections/` | 报告分节源文件（00-10） |
| `00_报告大纲与验收清单.md` | 大纲与验收清单 |
| `build_report.py` / `make_slides.py` / `make_figures.py` 等 | 报告/图表/视频生成脚本 |
| `flight_plan.json` | 飞行任务规划样例 |

## 不随仓库分发的大文件

为控制仓库体积，以下内容**未入库**（本地保留）：

- `flight_raw/`（~1.4 GB）：真实 DJI 飞行原始素材；
- `audio/`（TTS 旁白）、`*.mp4`（演示视频）、`*封面*.png`；
- `flight_logs/`（运行日志）；
- `scene_v3/`（进行中的 v3 场景/视频增强迭代，含生成纹理与预览帧，本地保留、不入库）。

如需复现演示视频：见 `make_demo_video.py` / `make_flight_video_v2.py` 与 `run_flight.ps1`。

## 复现

```powershell
cd dji_ue5_3dgs/report
python build_report.py        # 合并 sections -> 最终报告 md
python make_slides.py         # 生成 PPTX
python make_figures.py        # 生成 figures/
```
