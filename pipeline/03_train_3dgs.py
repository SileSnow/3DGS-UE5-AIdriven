"""03_train_3dgs.py -- 3DGS 训练主脚本（纯 PyTorch 光栅化器，可选 gsplat 后端）。

输入: CONVENTIONS metadata.json 数据集（已知位姿直通）或 COLMAP sparse / NeRF transforms.json
输出: data/trained/<dataset>/<run>/ 下 gaussians.ply（标准 3DGS PLY，UE cm 坐标系）、
      gaussians_best.ply、train_log.txt、metrics.json、renders/

用法示例:
  python pipeline/03_train_3dgs.py --data data/synthetic/capture --out data/trained/capture/run1 \
      --iters 8000 --res-scale 0.5 --max-splats 200000
  # 单视角过拟合自检:
  python pipeline/03_train_3dgs.py --data data/sample/synthetic_campus_v1 --out data/trained/_overfit \
      --iters 600 --single-view 0 --res-scale 0.5
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np
import torch
import torch.nn.functional as F

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from dataset import load_dataset, load_val, scene_info, views_to_ply_world  # noqa: E402
from ply_io import save_3dgs_ply  # noqa: E402
from puretorch_splatting.renderer import GaussianModel, has_gsplat, render_from_view  # noqa: E402
from puretorch_splatting.sh import SH_C0, num_sh_coeffs  # noqa: E402
from utils import psnr, save_png, ssim, to_numpy_img  # noqa: E402

# 限载：用户要求 CPU 不要满载/温度 <=80C（可用环境变量覆盖）
torch.set_num_threads(int(os.environ.get("DSH_TORCH_THREADS", "4")))


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def log_line(log_path, msg):
    print(msg, flush=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def estimate_background(image_uint8, patch=16):
    """用图像四角 patch 的均值估计背景色（天空/背景），用于 alpha 合成。"""
    h, w = image_uint8.shape[:2]
    p = min(patch, h // 4, w // 4)
    patches = [image_uint8[0:p, 0:p], image_uint8[0:p, w - p:w],
               image_uint8[h - p:h, 0:p], image_uint8[h - p:h, w - p:w]]
    return np.concatenate([q.reshape(-1, 3) for q in patches], axis=0).mean(axis=0) / 255.0


def image_to_tensor(img_uint8, device, dtype=torch.float32):
    return torch.from_numpy(img_uint8.astype(np.float32) / 255.0).to(device=device, dtype=dtype)


# --------------------------------------------------------------------------- #
# 高斯初始化
# --------------------------------------------------------------------------- #
def init_gaussians(data, n_points, sh_degree, device, seed=0, init_scale_rel=0.05):
    rng = np.random.default_rng(seed)
    views = data["views"]
    info = scene_info(data)
    center = np.asarray(info["center"], np.float64)
    extent = float(info["extent"])
    means_list, color_list = [], []

    pts = data.get("points")
    if pts is not None and len(pts[0]) > 0:
        xyz, rgb = pts
        n_use = min(n_points, len(xyz))
        keep = rng.choice(len(xyz), size=n_use, replace=False)
        means_list.append(np.asarray(xyz[keep], np.float64))
        color_list.append(np.asarray(rgb[keep], np.float64) / 255.0)
        print("[init] 使用 COLMAP 稀疏点云: %d 点" % n_use)
    n_ray = max(0, n_points - (len(means_list[0]) if means_list else 0))
    if n_ray > 0:
        per_view = max(1, n_ray // len(views))
        for v in views:
            R_cw = np.asarray(v["R_cw"], np.float64)
            t_cw = np.asarray(v["t_cw"], np.float64)
            K = np.asarray(v["K"], np.float64)
            C = -R_cw.T @ t_cw
            d_center = max(float(np.linalg.norm(C - center)), 1e-3)
            n_i = per_view
            us = rng.uniform(0.0, v["width"], n_i)
            vs = rng.uniform(0.0, v["height"], n_i)
            depth = rng.uniform(0.35, 1.05, n_i) * d_center
            dir_cam = np.stack([(us - K[0, 2]) / K[0, 0],
                                (vs - K[1, 2]) / K[1, 1],
                                np.ones(n_i)], axis=1)
            dir_world = dir_cam @ R_cw                      # == R_cw^T @ dir
            dir_world /= np.maximum(np.linalg.norm(dir_world, axis=1, keepdims=True), 1e-9)
            means_list.append(C[None, :] + depth[:, None] * dir_world)
            img = v["image"]
            if img is not None:
                ui = np.clip(us.astype(int), 0, v["width"] - 1)
                vi = np.clip(vs.astype(int), 0, v["height"] - 1)
                color_list.append(img[vi, ui].astype(np.float64) / 255.0)
            else:
                color_list.append(np.full((n_i, 3), 0.5))
    means = np.concatenate(means_list, axis=0)
    colors = np.concatenate(color_list, axis=0)
    # 过滤离群点（超出场景中心 3*extent）
    keep = np.linalg.norm(means - center, axis=1) < 3.0 * extent
    means, colors = means[keep], colors[keep]
    if len(means) < 32:
        raise RuntimeError("初始化点太少: %d" % len(means))

    # kNN 距离 -> 初始尺度
    from scipy.spatial import cKDTree
    tree = cKDTree(means)
    k = min(4, len(means))
    dists, _ = tree.query(means, k=k)
    if dists.ndim == 1:
        dists = dists[:, None]
    nn_dist = dists[:, 1:].mean(axis=1) if k > 1 else dists[:, 0]
    # 初始尺度：过大（>3 sigma 超出 max_radius）会导致 alpha 饱和、梯度消失、densify 永不触发
    scale0 = np.clip(nn_dist * float(init_scale_rel), 2.0, 0.005 * extent)
    scales_log = np.log(scale0)[:, None].repeat(3, axis=1)

    N = len(means)
    quats = np.tile(np.array([1.0, 0.0, 0.0, 0.0]), (N, 1))
    opacity_logit = np.full((N, 1), math.log(0.1 / 0.9))          # sigmoid -> 0.1
    sh = np.zeros((N, num_sh_coeffs(sh_degree), 3), np.float32)
    sh[:, 0, :] = (colors - 0.5) / SH_C0

    def T(a, dtype=torch.float32):
        return torch.as_tensor(a, dtype=dtype, device=device).requires_grad_(True)

    model = GaussianModel(T(means), T(quats), T(scales_log), T(opacity_logit.reshape(-1)),
                          T(sh), sh_degree=sh_degree)
    print("[init] %d 个高斯 (nn_dist median %.2f cm, extent %.0f cm)" % (
        N, float(np.median(nn_dist)), extent))
    return model


# --------------------------------------------------------------------------- #
# 参数 / 优化器 / densify
# --------------------------------------------------------------------------- #
def make_optimizer(model, scene_scale, lr_scale=1.0):
    lrs = {
        "means": 1.6e-4 * scene_scale * lr_scale,
        "scales": 5e-3 * lr_scale,
        "quats": 1e-3 * lr_scale,
        "opacity": 5e-2 * lr_scale,
        "sh": 2.5e-3 * lr_scale,
    }
    groups = [
        {"params": [model.means], "lr": lrs["means"], "name": "means"},
        {"params": [model.quats], "lr": lrs["quats"], "name": "quats"},
        {"params": [model.scales], "lr": lrs["scales"], "name": "scales"},
        {"params": [model.opacity], "lr": lrs["opacity"], "name": "opacity"},
        {"params": [model.sh], "lr": lrs["sh"], "name": "sh"},
    ]
    return torch.optim.Adam(groups, eps=1e-15), lrs


def _cat_params(a, b):
    return torch.cat([a.detach(), b.detach()], dim=0).contiguous().requires_grad_(True)


def densify_and_prune(model, mean2d_grad_norm, scene_extent, opts, log_path):
    """简化版 3DGS densify/prune：clone 小尺度高梯度、split 大尺度高梯度、剪低不透明度/超尺度。"""
    if mean2d_grad_norm is None:
        mean2d_grad_norm = torch.zeros(model.num_gaussians, device=model.means.device)
    device = model.means.device
    with torch.no_grad():
        opacity = torch.sigmoid(model.opacity)
        world_scale = torch.exp(model.scales).max(dim=1).values
        grads = mean2d_grad_norm.reshape(-1)
        if grads.numel() != model.num_gaussians:
            grads = torch.zeros(model.num_gaussians, device=device)
        n = model.num_gaussians
        vis = opacity > 0.01

        def topk_mask(mask, k):
            idx = mask.nonzero(as_tuple=False).squeeze(1)
            if idx.numel() <= k:
                return mask
            order = torch.argsort(grads[idx], descending=True)
            out = torch.zeros_like(mask)
            out[idx[order[:k]]] = True
            return out

        # 自适应阈值：取可见高斯梯度的分位数（不同数据集/损失量级下稳定触发 densify），
        # 同时受绝对下限 grad_thresh 约束；每步 clone 数量受 clone_frac 限制。
        gvals = grads[vis]
        if gvals.numel() > 0:
            dyn = float(torch.quantile(gvals, float(opts.get("clone_quantile", 0.8))))
        else:
            dyn = 0.0
        thresh = max(float(opts["grad_thresh"]), dyn)
        split_thresh = opts["split_scale_frac"] * scene_extent
        clone_mask = vis & (grads > thresh) & (world_scale <= split_thresh)
        split_mask = vis & (grads > thresh) & (world_scale > split_thresh)

        clone_cap = max(1, int(float(opts.get("clone_frac", 0.25)) * n))
        clone_mask = topk_mask(clone_mask, clone_cap)
        split_mask = topk_mask(split_mask, max(1, clone_cap // 4))
        n_clone = int(clone_mask.sum().item())
        n_split = int(split_mask.sum().item())
        budget = opts["max_splats"] - n
        if budget <= 0 or n_clone + 2 * n_split > budget:
            k_total = max(0, budget)
            if n_split * 2 <= k_total:
                split_budget = n_split
                clone_budget = k_total - 2 * n_split
            else:
                split_budget = k_total // 2
                clone_budget = k_total - 2 * split_budget
            clone_mask = topk_mask(clone_mask, max(0, clone_budget))
            split_mask = topk_mask(split_mask, max(0, split_budget))
            n_clone = int(clone_mask.sum().item())
            n_split = int(split_mask.sum().item())

        new_means, new_quats, new_scales, new_opacity, new_sh = [], [], [], [], []
        new_means.append(model.means.detach()); new_quats.append(model.quats.detach())
        new_scales.append(model.scales.detach()); new_opacity.append(model.opacity.detach())
        new_sh.append(model.sh.detach())
        if n_clone > 0:
            new_means.append(model.means.detach()[clone_mask])
            new_quats.append(model.quats.detach()[clone_mask])
            new_scales.append(model.scales.detach()[clone_mask])
            new_opacity.append(model.opacity.detach()[clone_mask])
            new_sh.append(model.sh.detach()[clone_mask])
        if n_split > 0:
            child_means = model.means.detach()[split_mask].repeat(2, 1)
            jitter = (torch.rand_like(child_means) - 0.5) * torch.exp(model.scales.detach()[split_mask]).repeat(2, 1) * 0.6
            child_means = child_means + jitter
            new_means.append(child_means)
            new_quats.append(model.quats.detach()[split_mask].repeat(2, 1))
            new_scales.append((model.scales.detach()[split_mask] - math.log(1.6)).repeat(2, 1))
            new_opacity.append(model.opacity.detach()[split_mask].repeat(2))
            new_sh.append(model.sh.detach()[split_mask].repeat(2, 1, 1))

        means = torch.cat(new_means, 0)
        quats = torch.cat(new_quats, 0)
        scales = torch.cat(new_scales, 0)
        opacity_l = torch.cat(new_opacity, 0)
        sh = torch.cat(new_sh, 0)

        # prune
        op = torch.sigmoid(opacity_l).reshape(-1)
        ws = torch.exp(scales).max(dim=1).values
        bad = (op < opts["prune_opacity"]) | (ws > opts["prune_scale_frac"] * scene_extent) \
              | (~torch.isfinite(means)).any(dim=1) | (~torch.isfinite(scales)).any(dim=1)
        if bad.any():
            keep = ~bad
            means, quats = means[keep], quats[keep]
            scales, opacity_l, sh = scales[keep], opacity_l[keep], sh[keep]
        # 硬上限
        if means.shape[0] > opts["max_splats"]:
            idx = torch.randperm(means.shape[0], device=device)[:opts["max_splats"]]
            means, quats = means[idx], quats[idx]
            scales, opacity_l, sh = scales[idx], opacity_l[idx], sh[idx]

    model.means = means.contiguous().requires_grad_(True)
    model.quats = quats.contiguous().requires_grad_(True)
    model.scales = scales.contiguous().requires_grad_(True)
    model.opacity = opacity_l.contiguous().requires_grad_(True)
    model.sh = sh.contiguous().requires_grad_(True)
    return n_clone, n_split, int(bad.sum().item()) if 'bad' in dir() else 0


# --------------------------------------------------------------------------- #
# 评测
# --------------------------------------------------------------------------- #
@torch.no_grad()
def evaluate(model, views, args, bg_cache, device, save_dir=None, prefix="val"):
    psnrs, ssims, renders = [], [], []
    per_view = []
    for i, v in enumerate(views):
        out = render_from_view(model, v, backend=args.backend, tile_size=args.tile_size,
                               max_per_tile=args.max_per_tile, max_radius=args.max_radius,
                               background=bg_cache[v["name"]], device=device)
        img = out["image"].clamp(0, 1)
        gt = image_to_tensor(v["image"], device)
        p, s = psnr(img, gt), ssim(img, gt, device=str(device))
        psnrs.append(p); ssims.append(s)
        per_view.append({"name": v["name"], "psnr": p, "ssim": s})
        renders.append((v["name"], to_numpy_img(img)))
        if save_dir:
            save_png(to_numpy_img(img), os.path.join(save_dir, "%s_%03d.png" % (prefix, i)))
            save_png(v["image"], os.path.join(save_dir, "gt_%03d.png" % i))
    return {"psnr": float(np.mean(psnrs)), "ssim": float(np.mean(ssims)),
            "per_view": per_view, "renders": renders}


# --------------------------------------------------------------------------- #
# 主训练
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="训练数据集根目录（metadata.json / sparse / transforms.json）")
    ap.add_argument("--val", default=None, help="验证集根目录（默认为 data 内的 val/）")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--iters", type=int, default=8000)
    ap.add_argument("--res-scale", type=float, default=0.5)
    ap.add_argument("--backend", default="auto", choices=["auto", "puretorch", "gsplat"])
    ap.add_argument("--tile-size", type=int, default=16)
    ap.add_argument("--max-per-tile", type=int, default=64)
    ap.add_argument("--max-radius", type=float, default=16.0)
    ap.add_argument("--max-splats", type=int, default=200000)
    ap.add_argument("--init-points", type=int, default=20000)
    ap.add_argument("--init-scale-rel", type=float, default=0.05,
                    help="初始高斯尺度 = init_scale_rel * 初始点云最近邻距离（默认 0.05，防 alpha 饱和）")
    ap.add_argument("--sh-degree", type=int, default=0, choices=[0, 1, 2, 3])
    ap.add_argument("--lr-scale", type=float, default=1.0)
    ap.add_argument("--eval-every", type=int, default=1000)
    ap.add_argument("--save-every", type=int, default=2000)
    ap.add_argument("--densify-start", type=int, default=500)
    ap.add_argument("--densify-end-frac", type=float, default=0.55)
    ap.add_argument("--densify-interval", type=int, default=100)
    ap.add_argument("--grad-thresh", type=float, default=1e-8,
                    help="densify 梯度绝对下限（像素单位）；实际阈值还要取可见高斯梯度的 clone-quantile 分位")
    ap.add_argument("--clone-quantile", type=float, default=0.8)
    ap.add_argument("--clone-frac", type=float, default=0.25, help="每次 densify 最多 clone 的比例")
    ap.add_argument("--scene-extent", type=float, default=0.0, help=">0 时覆盖自动估计的场景尺度（cm）")
    ap.add_argument("--resume", default=None, help="从 checkpoint.pt 继续训练（'auto' = <out>/checkpoint.pt）")
    ap.add_argument("--split-scale-frac", type=float, default=0.01)
    ap.add_argument("--prune-opacity", type=float, default=0.005)
    ap.add_argument("--prune-scale-frac", type=float, default=0.1)
    ap.add_argument("--ssim-weight", type=float, default=0.2)
    ap.add_argument("--single-view", type=int, default=-1, help=">=0 时只用该视角过拟合（自检）")
    ap.add_argument("--max-frames", type=int, default=0, help=">0 时均匀抽样最多 N 个训练视角（capture 先出 sample 时用）")
    ap.add_argument("--min-frames", type=int, default=0, help=">0 时训练视角少于此数则报错退出")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--anomaly", action="store_true", help="torch.autograd.set_detect_anomaly（调试 NaN 用）")
    ap.add_argument("--check-finite-every", type=int, default=0, help=">0 时每 N 步检查参数/梯度有限性")
    ap.add_argument("--gpu-duty", type=float, default=1.0,
                    help="GPU 占空比节流：1.0 不节流；0.25 = 每 iter 后休眠 3x 该 iter 耗时（约束 GPU 平均占用）")
    args = ap.parse_args()
    if not (0.0 < args.gpu_duty <= 1.0):
        ap.error("--gpu-duty 必须在 (0, 1]")
    if args.anomaly:
        torch.autograd.set_detect_anomaly(True)

    if args.backend == "auto":
        args.backend = "gsplat" if has_gsplat() else "puretorch"
    if args.backend == "gsplat" and not has_gsplat():
        print("[warn] gsplat 不可用，回退 puretorch")
        args.backend = "puretorch"
    device = torch.device(args.device if torch.cuda.is_available() or args.device == "cpu" else "cpu")
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    os.makedirs(args.out, exist_ok=True)
    log_path = os.path.join(args.out, "train_log.txt")
    if os.path.exists(log_path) and not args.resume:   # 续训时保留历史日志
        os.remove(log_path)
    t_start = time.time()

    data = load_dataset(args.data, res_scale=args.res_scale, load_images=True)
    views = data["views"]
    if args.min_frames and len(views) < args.min_frames:
        raise SystemExit("[data] 训练视角 %d < --min-frames %d，数据未就绪" % (len(views), args.min_frames))
    if args.max_frames and len(views) > args.max_frames:
        idx = np.linspace(0, len(views) - 1, args.max_frames).round().astype(int)
        idx = sorted(set(int(i) for i in idx))
        views = [views[i] for i in idx]
        print("[data] --max-frames: 均匀抽样 %d/%d 视角" % (len(views), len(data["views"])))
    if args.single_view >= 0:
        views = [views[args.single_view]]
    info = scene_info({"views": views})
    scene_extent = float(info["extent"])
    if args.scene_extent > 0:
        scene_extent = float(args.scene_extent)
    bg_cache = {v["name"]: estimate_background(v["image"]) for v in views}
    train_views = views

    val_root = args.val or args.data
    val = None
    if args.single_view < 0:
        try:
            val = load_val(val_root, res_scale=args.res_scale, load_images=True)
        except Exception as e:  # noqa: BLE001
            print("[warn] 验证集加载失败:", e)
    if val:
        for v in val["views"]:
            bg_cache[v["name"]] = estimate_background(v["image"])
    print("[data] kind=%s world=%s train=%d val=%d res=%dx%d" % (
        data["kind"], data["world"], len(train_views), len(val["views"]) if val else 0,
        train_views[0]["width"], train_views[0]["height"]))

    # ---- 初始化 / 断点续训 ----
    # 说明：本机 CPU 温度受限，训练可能被外部熔断；--resume 允许从最近 checkpoint 继续。
    resume_iter = 0
    resume_path = args.resume
    if resume_path == "auto":
        resume_path = os.path.join(args.out, "checkpoint.pt")
    ckpt = None
    if resume_path and os.path.isfile(resume_path):
        ckpt = torch.load(resume_path, map_location="cpu", weights_only=False)
        resume_iter = int(ckpt.get("iter", 0))
        print("[resume] 从 %s 继续（iter=%d）" % (resume_path, resume_iter))
    model = init_gaussians(data, args.init_points, args.sh_degree, device, seed=args.seed,
                           init_scale_rel=args.init_scale_rel)
    if ckpt is not None:
        st = ckpt["state"]

        def _p(k):
            return st[k].detach().to(device).contiguous().requires_grad_(True)
        model.means = _p("means"); model.quats = _p("quats"); model.scales = _p("scales")
        model.opacity = _p("opacity"); model.sh = _p("sh")
        model.sh_degree = int(st.get("sh_degree", args.sh_degree))
        if ckpt.get("scene_extent"):
            scene_extent = float(ckpt["scene_extent"])
    if args.single_view >= 0:
        # 单视角过拟合时把相机中心当作场景尺度
        scene_extent = max(float(np.linalg.norm(views[0]["K"])), 100.0)
    lrs = None
    optimizer, lrs = make_optimizer(model, scene_extent, args.lr_scale)

    # GT 图片留在 CPU（175 帧 800x600 全放 GPU 约 1GB），逐 iter 拷到 GPU
    gt_cache = {v["name"]: torch.from_numpy(v["image"].astype(np.float32) / 255.0)
                for v in train_views}

    opts = {"grad_thresh": args.grad_thresh, "split_scale_frac": args.split_scale_frac,
            "max_splats": args.max_splats, "prune_opacity": args.prune_opacity,
            "prune_scale_frac": args.prune_scale_frac, "image_width": train_views[0]["width"],
            "clone_quantile": args.clone_quantile, "clone_frac": args.clone_frac}
    densify_end = int(args.iters * args.densify_end_frac)

    best = {"psnr": -1.0, "iter": 0}
    metrics = {"args": vars(args), "lrs": lrs, "scene_extent": scene_extent,
               "n_init": model.num_gaussians, "eval_history": []}
    log_line(log_path, "== 03_train_3dgs backend=%s iters=%d res=%dx%d views=%d sh_deg=%d ==" % (
        args.backend, args.iters, train_views[0]["width"], train_views[0]["height"],
        len(train_views), args.sh_degree))
    log_line(log_path, "config: " + json.dumps(vars(args), ensure_ascii=False))

    order = []
    last_grad_norm = None
    t0 = time.time()
    if resume_iter > 0:
        log_line(log_path, "== resume from iter %d ==" % resume_iter)
    for it in range(resume_iter + 1, args.iters + 1):
        t_iter = time.time()
        if not order:
            order = list(range(len(train_views)))
            np.random.shuffle(order)
        v = train_views[order.pop()]
        out = render_from_view(model, v, backend=args.backend, tile_size=args.tile_size,
                               max_per_tile=args.max_per_tile, max_radius=args.max_radius,
                               background=bg_cache[v["name"]], device=device,
                               retain_mean2d_grad=True)
        img = out["image"].clamp(0, 1)
        if args.check_finite_every and (it % args.check_finite_every == 0 or it < 6):
            with torch.no_grad():
                bad = {nm: int((~torch.isfinite(p)).sum()) for nm, p in
                       [("means", model.means), ("quats", model.quats), ("scales", model.scales),
                        ("opacity", model.opacity), ("sh", model.sh)]}
                print("[finite] iter %d img_finite=%s alpha_sum=%.3f bad=%s" % (
                    it, bool(torch.isfinite(img).all()), float(out["alpha"].sum()), bad), flush=True)
        gt = gt_cache[v["name"]].to(device, non_blocking=True)
        l1 = F.l1_loss(img, gt)
        sv = ssim(img, gt, device=str(device))
        loss = l1 + args.ssim_weight * (1.0 - sv)
        optimizer.zero_grad(set_to_none=True)
        if not loss.requires_grad:
            with torch.no_grad():
                print("[debug] no-grad loss at iter %d view %s: n=%d alpha_sum=%.4f  "
                      "means_finite=%s scales_finite=%s sh_finite=%s quats_norm_min=%.2e"
                      % (it, v["name"], model.num_gaussians, float(out["alpha"].sum()),
                         bool(torch.isfinite(model.means).all()),
                         bool(torch.isfinite(model.scales).all()),
                         bool(torch.isfinite(model.sh).all()),
                         float(model.quats.norm(dim=1).min())), flush=True)
            continue
        loss.backward()
        # densify 需要 2D 位置梯度
        m2d = out.get("mean2d")
        if m2d is not None and m2d.grad is not None:
            last_grad_norm = m2d.grad.detach().norm(dim=1)
        params = [model.means, model.quats, model.scales, model.opacity, model.sh]
        for p in params:
            if p.grad is not None:
                p.grad.nan_to_num_(nan=0.0, posinf=0.0, neginf=0.0)
        torch.nn.utils.clip_grad_norm_(params, max_norm=1e6)
        optimizer.step()
        with torch.no_grad():
            model.quats.data /= model.quats.data.norm(dim=1, keepdim=True).clamp(min=1e-8)

        if args.densify_start <= it <= densify_end and (it - args.densify_start) % args.densify_interval == 0:
            nc, ns, nprune = densify_and_prune(model, last_grad_norm, scene_extent, opts, log_path)
            optimizer, lrs = make_optimizer(model, scene_extent, args.lr_scale)
            log_line(log_path, "iter %5d densify: +%d clone, +%d split, -%d prune -> %d splats (%.0fs)" % (
                it, nc, ns, nprune, model.num_gaussians, time.time() - t0))

        if it % 20 == 0 or it == 1:
            p = psnr(img, gt)
            log_line(log_path, "iter %5d loss %.5f l1 %.5f psnr %.2f ssim %.4f n=%d %.1fs" % (
                it, float(loss.detach()), float(l1.detach()), p, sv, model.num_gaussians, time.time() - t0))

        if val is not None and args.eval_every > 0 and it % args.eval_every == 0:
            ev = evaluate(model, val["views"], args, bg_cache, device)
            metrics["eval_history"].append({"iter": it, "psnr": ev["psnr"], "ssim": ev["ssim"],
                                            "n_splats": model.num_gaussians})
            log_line(log_path, "iter %5d VAL psnr %.3f ssim %.4f" % (it, ev["psnr"], ev["ssim"]))
            if ev["psnr"] > best["psnr"]:
                best = {"psnr": ev["psnr"], "ssim": ev["ssim"], "iter": it}
                save_best(model, args, data, os.path.join(args.out, "gaussians_best.ply"))
                log_line(log_path, "  -> best 更新（iter %d, psnr %.3f），已保存 gaussians_best.ply" % (it, ev["psnr"]))

        if args.save_every > 0 and (it % args.save_every == 0 or it == args.iters):
            torch.save({"state": model.state_dict(), "iter": it, "args": vars(args),
                        "scene_extent": scene_extent, "world": data["world"]},
                       os.path.join(args.out, "checkpoint.pt"))

        if args.gpu_duty < 1.0:
            _dt = time.time() - t_iter
            if _dt > 0:
                time.sleep(_dt * (1.0 / args.gpu_duty - 1.0))

    # 最终：导出 PLY + 评测 + renders
    ply_path = os.path.join(args.out, "gaussians.ply")
    save_best(model, args, data, ply_path)
    # 评测视角：验证集优先；无验证集/训练集评测时取至多 24 个均匀抽样视角（避免全量渲染拖慢）
    def _subset(views_list, k=24):
        if len(views_list) <= k:
            return views_list
        idx = np.linspace(0, len(views_list) - 1, k).round().astype(int)
        return [views_list[int(i)] for i in sorted(set(idx))]

    eval_views = val["views"] if val else _subset(train_views)
    final_eval = evaluate(model, eval_views, args, bg_cache, device,
                          save_dir=os.path.join(args.out, "renders"),
                          prefix="val" if val else "train")
    train_eval = evaluate(model, _subset(train_views), args, bg_cache, device)
    torch.save({"state": model.state_dict(), "iter": args.iters, "args": vars(args),
                "scene_extent": scene_extent, "world": data["world"]},
               os.path.join(args.out, "checkpoint.pt"))
    peak = torch.cuda.max_memory_allocated() / 1e6 if device.type == "cuda" else 0.0
    metrics.update({
        "backend": args.backend,
        "n_splats": model.num_gaussians,
        "train_psnr": train_eval["psnr"], "train_ssim": train_eval["ssim"],
        "val_psnr": final_eval["psnr"], "val_ssim": final_eval["ssim"],
        "best": best, "train_seconds": round(time.time() - t_start, 1),
        "peak_mem_mb": round(peak, 1),
        "resolution": [train_views[0]["width"], train_views[0]["height"]],
        "ply": ply_path, "world": data["world"],
        "final_val_per_view": final_eval["per_view"],
    })
    with open(os.path.join(args.out, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    log_line(log_path, "== done: %d splats, val PSNR %.3f SSIM %.4f, %.0fs, peak %.0f MB ==" % (
        model.num_gaussians, final_eval["psnr"], final_eval["ssim"],
        time.time() - t_start, peak))
    print(json.dumps({k: metrics[k] for k in ["n_splats", "val_psnr", "val_ssim", "best",
                                             "train_seconds", "peak_mem_mb"]}, ensure_ascii=False))


def save_best(model, args, data, path):
    """把高斯参数写为标准 3DGS PLY（导出到与训练数据集相同的坐标系/尺度）。"""
    means = model.means.detach().cpu().numpy()
    means = views_to_ply_world(means, data["world"])
    save_3dgs_ply(path, means,
                  model.quats.detach().cpu().numpy(),
                  model.scales.detach().cpu().numpy(),
                  model.opacity.detach().cpu().numpy(),
                  model.sh.detach().cpu().numpy(), model.sh_degree)


if __name__ == "__main__":
    main()
