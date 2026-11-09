# 小样例数据（data/samples/）

> 单文件均 < 2 MB，随仓库分发，便于快速理解数据契约与文档配图。

| 目录 | 内容 | 来源 | 许可/说明 |
|---|---|---|---|
| `dji_real/` | DJI Mini 4 Pro 公开样片降采样（1600 px）+ EXIF 汇总 JSON | DJI 公开样片 | 版权归 DJI/原作者，仅技术演示，不再分发原图 |
| `ue5_mission_p1/` | P1 真实 LLM 任务的 UE5 渲染 4 帧（1600×1200 JPEG）+ metadata.json（含 c2w/GPS/云台） | 本项目 UE5 程序化场景 | 本项目生成，可自由用于协作 |
| `synthetic_campus_v1/` | 合成校园数据集的 metadata / COLMAP / 预览图（无图像） | 本项目 `capture/` | 同上 |
| `dji_priors/` | DJI 先验位姿 demo（metadata + COLMAP sparse 文本） | 本项目 Phase-0 | 同上 |

## 用法

```powershell
# 用 phase-1 的渲染/元数据逻辑读取 ue5_mission_p1 样例（无图像依赖）
cd dji_ue5_3dgs
python llm_drone\ue5_mission\mission_io.py --help 2>$null

# 用 phase-0 pipeline 读取（需要 pipeline venv）
pipeline\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'pipeline'); from dataset import load_dataset; ds=load_dataset('data/samples/ue5_mission_p1'); print(len(ds['views']))"
```

> 完整渲染数据集请按 [data/README.md](../README.md) 重新生成。
