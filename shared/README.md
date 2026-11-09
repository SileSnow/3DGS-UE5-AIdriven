# shared/ — 跨阶段共享契约与校验工具

| 文件 | 说明 |
|---|---|
| [CONVENTIONS.md](CONVENTIONS.md) | **数据契约**：数据集 metadata.json 格式、3DGS PLY 格式、UE↔COLMAP 坐标系换算 |
| [VERIFY_CHECKLIST.md](VERIFY_CHECKLIST.md) | 上游阶段交付验收清单 |
| [verify_all.ps1](verify_all.ps1) | Phase-0 交付物一键校验脚本 |
| [check_meta_ortho.py](check_meta_ortho.py) | metadata c2w 正交性检查工具 |
| [extract_terra.py](extract_terra.py) | DJI Terra 输出解包辅助脚本 |
| [thermal_guard*.ps1](.) | 长任务温度/功耗护栏脚本（本机实测用） |

> 新增跨阶段数据格式或修改已有契约时，请同时更新 `CONVENTIONS.md` 与本索引，并在 PR 中说明影响范围
>（该契约同时被 `pipeline/`、`capture/`、`llm_drone/ue5_mission/` 消费）。
