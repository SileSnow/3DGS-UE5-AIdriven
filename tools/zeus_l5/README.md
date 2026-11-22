# tools/zeus_l5 · ZEUS L4 → L5 180k 高斯最小链路

把 ZEUS 研究包里已跑通的 L4→L5 小样收进主仓库：读 L4 建筑分块（或合成街区），
采样 180,000 个高斯，导出 3DGS PLY 与 L5 场景 JSON。**只做「摆放」，不做训练。**

三个脚本：
- `inspect_zeus.py`：只读自检（分支/HEAD/关键路径/数据目录/依赖）
- `zeus_frame.py`：坐标往返、地形插值、L4 分块二进制
- `make_l5_spec.py`：L4 → 180k 高斯 → `gaussians.ply` + `l5_scene.json` + `l4_block.json`

## 依赖

- Python 3.10+，仅 **标准库 + numpy**；无需 ZEUS 的 1.6 TB 外部数据。
- `--demo` 完全离线，约 2 秒产出 180k 高斯。
- 脚本按 `__file__` 定位同目录模块，可从任意工作目录运行。

## 三条命令

```powershell
# 1) 只读自检：需要先 clone ZEUS 仓库（只读，不写它）
python inspect_zeus.py --repo <path-to>/yz-global-city-resilience-paper3

# 2) 坐标往返 / 地形插值 / L4 分块二进制 自检（不落盘）
python zeus_frame.py --selftest

# 3) 合成 12 栋街区 → 180,000 高斯（输出写到仓库外的临时目录）
python make_l5_spec.py --demo --count 180000 --out <tmp>/zeus_l5_demo
```

期望：第 1 条打印 branch/head/files 与 MISS/FOUND；第 2 条 `selftest OK`、
`kx≈90440.8 m/deg`、`terrain center height = 10.000 m`；第 3 条 stdout 打印 JSON，
关键字段 `buildings=12`、`gaussians=180000`、`ply_bytes=44641531`、`unit="m"`，
且 `flags.trained_radiance_field=false`。

## 输出文件

```
<tmp>/zeus_l5_demo/
  gaussians.ply     # 3DGS 标准 PLY：180000 点 × 62 property（float32）
  l5_scene.json     # L5 规范 v0.1；gaussians.sha256 为上面的 PLY 摘要
  l4_block.json     # 本街区 L4 子集（建筑环、高度、用途、锚点来源）
```

- PLY = 1531 字节头 + 180000×62×4 = 44,640,000 字节 payload，共 44,641,531 字节。
- 62 个 property 与 `shared/CONVENTIONS.md` 一致（x/y/z、法线、f_dc、45 个 f_rest、
  opacity、scale、rot）；`l5_schema.json` 是字段提案，不是运行时校验器。
- PLY 头部与数据均无时间戳，同一 numpy/种子下 sha256 可复现。

## 已知边界

1. **2026-11-22 修复了屋面/墙面轴序不一致**：屋面原先返回 `(x, z_south, y_up)`，
   墙面返回 `(x, y_up, z_south)`，同一 PLY 混用两套轴序。现已统一为
   `(x 东, y 上, z 南)`；默认米制与 `--unit cm` 均已复测（米制 `y∈[0,42]`、
   cm 制 `Z∈[0,4200]`）。修复前的 sha256 `3c50…` 作废，当前为 `2c25…`（见输出目录 `l5_scene.json` 的 `gaussians.sha256`）。
2. **默认单位是米**：`--unit m` 输出 ZEUS 局部米；`--unit cm` 才 ×100 并转 UE 厘米。
   接 `pipeline` 前必须显式选单位。
3. 正射取色**未实现**：颜色是按用途的启发式灰（`color_source=heuristic_by_use`），
   真实街区应换成 ortho 采样。
4. 脚本只「摆放」高斯，不训练、不评测：`inferred_facades=true`、
   `trained_radiance_field=false`，PSNR/SSIM 保持 `null`。
5. PLY 约 **44.6 MB**，**不入库**；只留在 `<tmp>`，不要放进仓库或提交。
6. 真实数据 `--bld` 需要的 `bld/t_*.bin.gz` 不在本仓库，由
   `prep/build_city23.py` 生成。
7. 尚未加自动化单测（轴序/几何校验目前靠手跑）；属下一步 PR。
