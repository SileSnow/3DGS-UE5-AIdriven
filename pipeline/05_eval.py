"""05_eval.py -- held-out 验证视角 PSNR/SSIM 评测 + 渲染保存。

用法:
  python pipeline/05_eval.py --run data/trained/campus/run1 --val data/synthetic/val --out <run>
  python pipeline/05_eval.py --run <run> --val data/sample/synthetic_campus_v1 --res-scale 0.5
  python pipeline/05_eval.py --ply data/trained/campus/run1/gaussians.ply --data data/synthetic/val --res-scale 0.5
输出: <out>/eval.json、<out>/renders/（val_XXX.png 预测 + gt_XXX.png 真值），控制台打印平均 PSNR/SSIM。
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
from dataset import load_dataset, load_val, views_to_ply_world  # noqa: E402
from ply_io import load_3dgs_ply  # noqa: E402
from puretorch_splatting.renderer import GaussianModel, render_from_view  # noqa: E402
from utils import psnr, save_png, ssim, to_numpy_img  # noqa: E402


def estimate_background(image_uint8, patch=16):
    h, w = image_uint8.shape[:2]
    p = min(patch, h // 4, w // 4)
    patches = [image_uint8[0:p, 0:p], image_uint8[0:p, w - p:w],
               image_uint8[h - p:h, 0:p], image_uint8[h - p:h, w - p:w]]
    return np.concatenate([q.reshape(-1, 3) for q in patches], axis=0).mean(axis=0) / 255.0


def load_model(args, device):
    if args.run:
        ck = torch.load(os.path.join(args.run, "checkpoint.pt"), map_location="cpu", weights_only=False)
        st = ck["state"]
        t = lambda k: st[k].detach().to(device)  # noqa: E731
        model = GaussianModel(t("means"), t("quats"), t("scales"), t("opacity"), t("sh"),
                              sh_degree=int(st.get("sh_degree", 0)))
        return model, ck.get("world", "colmap")
    if args.ply:
        d = load_3dgs_ply(args.ply)
        # PLY 可能是 UE LHS cm；内部用右手世界
        means = d["means"].astype(np.float64)
        if args.ply_world == "ue_rh_cm":
            means = means.copy()
            means[:, 1] = -means[:, 1]
        model = GaussianModel(
            torch.as_tensor(means, dtype=torch.float32, device=device),
            torch.as_tensor(d["quats"], dtype=torch.float32, device=device),
            torch.as_tensor(d["scales_log"], dtype=torch.float32, device=device),
            torch.as_tensor(d["opacity_logit"], dtype=torch.float32, device=device),
            torch.as_tensor(d["sh"], dtype=torch.float32, device=device),
            sh_degree=d["sh_degree"])
        return model, args.ply_world
    raise SystemExit("需要 --run 或 --ply")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None)
    ap.add_argument("--ply", default=None)
    ap.add_argument("--ply-world", default="ue_rh_cm", choices=["ue_rh_cm", "raw"],
                    help="PLY 的坐标系（ue_rh_cm: UE LHS cm，内部翻转 y）")
    ap.add_argument("--val", default=None, help="验证集根目录；缺省用 --data 或 run 内记录")
    ap.add_argument("--data", default=None, help="显式数据集根目录（COLMAP/transforms 验证集）")
    ap.add_argument("--out", default=None, help="输出目录（默认 run 目录）")
    ap.add_argument("--res-scale", type=float, default=0.5)
    ap.add_argument("--tile-size", type=int, default=16)
    ap.add_argument("--max-per-tile", type=int, default=64)
    ap.add_argument("--max-radius", type=float, default=16.0)
    ap.add_argument("--backend", default="auto", choices=["auto", "puretorch", "gsplat"])
    ap.add_argument("--no-renders", action="store_true")
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model, world = load_model(args, device)
    val_root = args.val or args.data
    if not val_root:
        raise SystemExit("需要 --val 或 --data 指定验证数据集")
    data = load_val(val_root, res_scale=args.res_scale, load_images=True)
    if data is None:
        data = load_dataset(val_root, res_scale=args.res_scale, load_images=True)
    views = data["views"]
    out = args.out or args.run or os.path.dirname(args.ply)
    os.makedirs(out, exist_ok=True)
    render_dir = os.path.join(out, "renders")
    if not args.no_renders:
        os.makedirs(render_dir, exist_ok=True)

    psnrs, ssims, per_view = [], [], []
    cloud_stats = None
    if args.run:
        ck = torch.load(os.path.join(args.run, "checkpoint.pt"), map_location="cpu", weights_only=False)
        cloud_stats = {"n_splats": int(ck["state"]["means"].shape[0]),
                       "iter": ck.get("iter")}
    with torch.no_grad():
        for i, v in enumerate(views):
            if args.run:
                from puretorch_splatting.renderer import viewmat_from_view
                R = torch.as_tensor(v["R_cw"], dtype=torch.float32, device=device)
                t = torch.as_tensor(v["t_cw"], dtype=torch.float32, device=device)
                view = dict(v)
            bg = estimate_background(v["image"])
            res = render_from_view(model, v, backend=args.backend, tile_size=args.tile_size,
                                   max_per_tile=args.max_per_tile, max_radius=args.max_radius,
                                   background=bg, device=device)
            img = res["image"].clamp(0, 1)
            gt = torch.from_numpy(v["image"].astype(np.float32) / 255.0).to(device)
            p, s = psnr(img, gt), ssim(img, gt, device=str(device))
            psnrs.append(p); ssims.append(s)
            per_view.append({"name": v["name"], "psnr": p, "ssim": s})
            if not args.no_renders:
                save_png(to_numpy_img(img), os.path.join(render_dir, "val_%03d.png" % i))
                save_png(v["image"], os.path.join(render_dir, "gt_%03d.png" % i))
    result = {"dataset_views": len(views), "psnr": float(np.mean(psnrs)),
              "ssim": float(np.mean(ssims)), "per_view": per_view,
              "resolution": [views[0]["width"], views[0]["height"]],
              "res_scale": args.res_scale, "world": world, "cloud": cloud_stats,
              "source": args.run or args.ply}
    with open(os.path.join(out, "eval.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: result[k] for k in ["dataset_views", "psnr", "ssim", "cloud"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
