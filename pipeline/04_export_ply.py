"""04_export_ply.py -- 从训练 checkpoint 导出标准 3DGS PLY（shared/CONVENTIONS.md §2），独立 CLI。

用法:
  python pipeline/04_export_ply.py --run data/trained/campus/run1 --out data/trained/campus/run1/gaussians.ply
  python pipeline/04_export_ply.py --checkpoint data/trained/campus/run1/checkpoint.pt --out x.ply --stats
  # 坐标系: 训练内部用右手世界（UE x,-y,z），导出时默认转回 UE LHS（x,y,z）以便 UE5 端直接读
  python pipeline/04_export_ply.py --run <run> --out <ply> --world raw   # 不转换（COLMAP/NeRF 数据集）
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ply_io import save_3dgs_ply, ply_stats  # noqa: E402


def export_from_checkpoint(ckpt_path, out_path, world="auto"):
    ck = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    st = ck["state"]
    dataset_world = ck.get("world", "colmap")
    means = st["means"].detach().cpu().numpy().astype(np.float64)
    if world == "ue" or (world == "auto" and dataset_world == "ue_rh_cm"):
        means = means.copy()
        means[:, 1] = -means[:, 1]
        out_world = "ue_lhs_cm"
    else:
        out_world = dataset_world
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    save_3dgs_ply(out_path,
                  means,
                  st["quats"].detach().cpu().numpy(),
                  st["scales"].detach().cpu().numpy(),
                  st["opacity"].detach().cpu().numpy(),
                  st["sh"].detach().cpu().numpy(),
                  int(st.get("sh_degree", 0)))
    return {"out": out_path, "world": out_world, "num_gaussians": int(means.shape[0])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None, help="训练输出目录（含 checkpoint.pt）")
    ap.add_argument("--checkpoint", default=None, help="直接指定 checkpoint.pt")
    ap.add_argument("--out", default=None, help="输出 PLY 路径（默认 <run>/gaussians.ply）")
    ap.add_argument("--world", default="auto", choices=["auto", "ue", "raw"],
                    help="auto: UE 数据集自动转回 UE LHS cm；raw: 不转换")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    ckpt = args.checkpoint or (os.path.join(args.run, "checkpoint.pt") if args.run else None)
    if not ckpt or not os.path.isfile(ckpt):
        raise SystemExit("找不到 checkpoint: %s" % ckpt)
    out = args.out or (os.path.join(args.run, "gaussians.ply") if args.run else None)
    if not out:
        raise SystemExit("需要 --out 或 --run")
    info = export_from_checkpoint(ckpt, out, args.world)
    print(json.dumps(info, ensure_ascii=False))
    if args.stats:
        print(json.dumps(ply_stats(out), ensure_ascii=False))


if __name__ == "__main__":
    main()
