"""make_synthetic_scene.py -- 程序化生成多视角"校园"小场景（DJI 航拍风格相机轨迹），
输出 schema 与 shared/CONVENTIONS.md §1 完全一致（UE LHS / cm / metadata.json + c2w）。

用途:
  1) capture-synth 的 UE 合成数据就绪前，验证 基础位姿直通 -> 3DGS 训练 -> PLY 导出 -> 评测 全链路；
  2) 作为 pipeline/ 的可复现基线数据（结果见 pipeline/RESULTS.md）。
渲染器为纯 numpy 光线投射（平面 + AABB 建筑 + 球体树），2x2 SSAA，无外部依赖。

用法:
  python pipeline/make_synthetic_scene.py --out data/sample/synthetic_campus_v1 \
      --width 960 --height 720 --n-train 24 --n-val 6 --seed 0
"""
from __future__ import annotations

import argparse
import json
import math
import os

import numpy as np
from PIL import Image

SKY = np.array([0.56, 0.72, 0.92], np.float32)
SUN = np.array([0.35, -0.55, 0.75], np.float32)
SUN /= np.linalg.norm(SUN)
ORIGIN_WGS84 = {"lat": 39.9042, "lon": 116.4074, "alt": 43.0}


# --------------------------------------------------------------------------- #
# 场景定义（单位: cm, UE 世界: +X 北, +Y 东, +Z 上）
# --------------------------------------------------------------------------- #
def build_scene():
    boxes = [
        {"min": [-1800, -1200, 0], "max": [-200, 400, 1600],
         "color": [0.74, 0.71, 0.66], "windows": True},
        {"min": [600, -600, 0], "max": [1800, 900, 2400],
         "color": [0.66, 0.63, 0.58], "windows": True},
        {"min": [-1200, 1600, 0], "max": [100, 2900, 1000],
         "color": [0.79, 0.75, 0.63], "windows": True},
        {"min": [2200, 1200, 0], "max": [3200, 2400, 3000],
         "color": [0.60, 0.66, 0.72], "windows": True},
        {"min": [-3200, -2400, 0], "max": [-2000, -1000, 700],
         "color": [0.76, 0.62, 0.56], "windows": True},
        {"min": [2400, -2600, 0], "max": [3400, -1500, 1100],
         "color": [0.68, 0.70, 0.66], "windows": True},
    ]
    spheres = [
        {"center": [300, 1400, 300], "radius": 300, "color": [0.20, 0.42, 0.16]},
        {"center": [-1600, 950, 260], "radius": 260, "color": [0.22, 0.45, 0.18]},
        {"center": [1500, -1200, 320], "radius": 320, "color": [0.18, 0.40, 0.15]},
        {"center": [-2600, -300, 280], "radius": 280, "color": [0.24, 0.47, 0.19]},
        {"center": [2000, 2600, 350], "radius": 350, "color": [0.21, 0.43, 0.17]},
    ]
    return {"boxes": boxes, "spheres": spheres}


def _lambert(n, base, ambient=0.35):
    d = np.clip((n * SUN[None, :]).sum(axis=1), 0.0, 1.0)
    shade = ambient + (1.0 - ambient) * d
    return base[None, :] * shade[:, None]


def shade_ground(P):
    x, y = P[:, 0], P[:, 1]
    n = P.shape[0]
    col = np.empty((n, 3), np.float32)
    checker = (np.floor(x / 350.0) + np.floor(y / 350.0)).astype(np.int32) % 2
    c0 = np.array([0.26, 0.42, 0.20], np.float32)
    c1 = np.array([0.32, 0.48, 0.24], np.float32)
    col[:] = np.where(checker[:, None] == 0, c0[None, :], c1[None, :])
    # 主干道（沿 x 方向，宽 8m，中心 y=0）
    road = np.abs(y) < 400
    col[road] = np.array([0.22, 0.22, 0.25], np.float32)
    lane = road & (np.abs(y) < 25) | road & (np.abs(np.abs(y) - 200) < 12)
    col[lane] = np.array([0.86, 0.84, 0.70], np.float32)
    # 人行道
    walk = (np.abs(y) >= 400) & (np.abs(y) < 640)
    col[walk] = np.array([0.62, 0.60, 0.56], np.float32)
    # 细微纹理
    tex = 0.95 + 0.05 * np.sin(x * 0.012 + y * 0.017) * np.cos(y * 0.009)
    col *= tex[:, None]
    nrm = np.tile(np.array([0.0, 0.0, 1.0], np.float32), (n, 1))
    return _lambert(nrm, col)


def shade_box(P, axis, box):
    n = P.shape[0]
    base = np.array(box["color"], np.float32)
    col = np.empty((n, 3), np.float32)
    vertical = axis != 2
    col[:] = base[None, :]
    # 立面 u 坐标
    u = np.where(axis == 0, P[:, 1], P[:, 0])
    v = P[:, 2]
    if box.get("windows", True):
        wu = np.mod(u, 280.0)
        wv = np.mod(v, 190.0)
        win = vertical & (wu > 70) & (wu < 210) & (wv > 40) & (wv < 140) & (v > 120)
        glass = 0.16 + 0.10 * np.sin(u * 0.013) * np.cos(v * 0.021)
        gcol = np.stack([glass * 0.9, glass * 1.25, glass * 1.8], axis=1)
        col[win] = gcol[win]
    # 屋顶
    roof = ~vertical
    col[roof] = np.array([0.50, 0.50, 0.52], np.float32)
    # 立面污渍/明暗
    col[vertical] *= (0.88 + 0.12 * np.sin(u[vertical] * 0.01))[:, None]
    # 法向朝向相机（= -D 的对应轴分量）
    nrm = np.zeros((n, 3), np.float32)
    nrm[np.arange(n), axis] = -1.0
    return _lambert(nrm, col, ambient=0.40)


def shade_sphere(P, C, sph):
    c = np.array(sph["center"], np.float32)
    nrm = P - c[None, :]
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-6)
    base = np.array(sph["color"], np.float32)
    col = _lambert(nrm, base, ambient=0.30)
    # 树冠轻微色斑
    col *= (0.9 + 0.1 * np.sin(P[:, 0] * 0.03 + P[:, 1] * 0.02))[:, None]
    return col


def trace(scene, C, D):
    """C: (3,) ray origin; D: (N,3) unit dirs -> RGB (N,3)。"""
    n = D.shape[0]
    t_best = np.full(n, np.inf, np.float32)
    kind = np.full(n, -1, np.int32)
    axis_best = np.zeros(n, np.int8)
    inv = 1.0 / np.where(np.abs(D) < 1e-8, 1e-8, D)

    # 地面平面 z=0
    t = -C[2] / np.where(np.abs(D[:, 2]) < 1e-8, 1e-8, D[:, 2])
    hit = (D[:, 2] < -1e-6) & (t > 0)
    t_best[hit] = t[hit]
    kind[hit] = 0

    # 建筑 AABB
    for bi, box in enumerate(scene["boxes"]):
        bmin = np.asarray(box["min"], np.float32)
        bmax = np.asarray(box["max"], np.float32)
        t1 = (bmin[None, :] - C[None, :]) * inv
        t2 = (bmax[None, :] - C[None, :]) * inv
        tlo = np.minimum(t1, t2)
        thi = np.maximum(t1, t2)
        tn = tlo.max(axis=1)
        tf = thi.min(axis=1)
        ax = tlo.argmax(axis=1)
        h = (tf >= np.maximum(tn, 0.0)) & (tn > 0.0) & (tn < t_best)
        t_best[h] = tn[h]
        kind[h] = bi + 1
        axis_best[h] = ax[h]

    # 球体
    for si, sph in enumerate(scene["spheres"]):
        oc = C[None, :] - np.asarray(sph["center"], np.float32)[None, :]
        b = 2.0 * (D * oc).sum(axis=1)
        c = (oc * oc).sum(axis=1) - float(sph["radius"]) ** 2
        disc = b * b - 4.0 * c
        ok = disc > 0
        if not ok.any():
            continue
        sq = np.sqrt(np.maximum(disc, 0.0))
        t = (-b - sq) / 2.0
        h = ok & (t > 0.0) & (t < t_best)
        t_best[h] = t[h]
        kind[h] = 1000 + si

    col = np.tile(SKY[None, :], (n, 1))
    finite = np.isfinite(t_best)
    P = np.zeros((n, 3), np.float32)
    P[finite] = C[None, :] + t_best[finite, None] * D[finite]

    m = kind == 0
    if m.any():
        col[m] = shade_ground(P[m])
    for bi, box in enumerate(scene["boxes"]):
        m = kind == bi + 1
        if m.any():
            col[m] = shade_box(P[m], axis_best[m], box)
    for si, sph in enumerate(scene["spheres"]):
        m = kind == 1000 + si
        if m.any():
            col[m] = shade_sphere(P[m], C, sph)
    return np.clip(col, 0.0, 1.0)


# --------------------------------------------------------------------------- #
# 相机
# --------------------------------------------------------------------------- #
def look_at_ue(C, target):
    fwd = np.asarray(target, np.float64) - np.asarray(C, np.float64)
    fwd /= np.linalg.norm(fwd)
    up_ref = np.array([0.0, 0.0, 1.0])
    if abs(float(fwd @ up_ref)) > 0.98:
        up_ref = np.array([1.0, 0.0, 0.0])
    right = np.cross(up_ref, fwd)
    right /= np.linalg.norm(right)
    up = np.cross(fwd, right)
    M = np.eye(4)
    M[:3, :3] = np.stack([fwd, right, up], axis=1)   # UE 相机轴: x=fwd, y=right, z=up
    M[:3, 3] = C
    return M


def gimbal_from_c2w(M):
    fwd = M[:3, 0]
    yaw = math.degrees(math.atan2(float(fwd[1]), float(fwd[0])))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, float(fwd[2])))))
    return {"yaw": round(yaw, 3), "pitch": round(pitch, 3), "roll": 0.0}


def gps_from_ue(C):
    lat0, lon0, alt0 = ORIGIN_WGS84["lat"], ORIGIN_WGS84["lon"], ORIGIN_WGS84["alt"]
    north_m, east_m, up_m = C[0] / 100.0, C[1] / 100.0, C[2] / 100.0
    lat = lat0 + north_m / 111320.0
    lon = lon0 + east_m / (111320.0 * math.cos(math.radians(lat0)))
    return {"lat": round(lat, 8), "lon": round(lon, 8), "alt": round(alt0 + up_m, 3)}


def generate_cameras(n, seed, radius_range, z_range, phase=0.0):
    rng = np.random.default_rng(seed)
    cams = []
    for i in range(n):
        az = 2.0 * math.pi * (i + phase) / n + rng.uniform(-0.08, 0.08)
        radius = rng.uniform(*radius_range)
        z = rng.uniform(*z_range)
        C = np.array([radius * math.cos(az), radius * math.sin(az), z])
        target = np.array([rng.uniform(-1200, 1200), rng.uniform(-1200, 1200),
                           rng.uniform(100, 800)])
        cams.append((look_at_ue(C, target), C))
    return cams


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #
def render_view(scene, M, K, W, H, ssaa=2, chunk_rows=48):
    M = np.asarray(M, np.float64)
    C = M[:3, 3]
    R_ue = M[:3, :3]
    Wr, Hr = W * ssaa, H * ssaa
    fx, fy, cx, cy = K[0, 0] * ssaa, K[1, 1] * ssaa, (K[0, 2] + 0.5) * ssaa - 0.5, (K[1, 2] + 0.5) * ssaa - 0.5
    us = (np.arange(Wr, dtype=np.float64) + 0.5 - cx) / fx
    vs = (np.arange(Hr, dtype=np.float64) + 0.5 - cy) / fy
    img = np.empty((Hr, Wr, 3), np.float32)
    for r0 in range(0, Hr, chunk_rows):
        r1 = min(Hr, r0 + chunk_rows)
        u = np.tile(us[None, :], (r1 - r0, 1)).reshape(-1)
        v = np.tile(vs[r0:r1, None], (1, Wr)).reshape(-1)
        dir_cam = np.stack([np.ones_like(u), u, -v], axis=1)      # UE 相机: x fwd, y right, z up
        dir_cam /= np.linalg.norm(dir_cam, axis=1, keepdims=True)
        D = dir_cam @ R_ue.T
        D /= np.linalg.norm(D, axis=1, keepdims=True)
        img[r0:r1] = trace(scene, C, D).reshape(r1 - r0, Wr, 3)
    # box downsample (area average)
    img8 = (np.clip(img, 0, 1) * 255.0).astype(np.uint8)
    if ssaa > 1:
        img8 = img8.reshape(H, ssaa, W, ssaa, 3).mean(axis=(1, 3)).astype(np.uint8)
    return img8


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="输出目录（如 data/sample/synthetic_campus_v1）")
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--n-train", type=int, default=24)
    ap.add_argument("--n-val", type=int, default=6)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ssaa", type=int, default=2)
    ap.add_argument("--fx", type=float, default=0.0, help="0 = 0.79*width (约 64 度 FOV)")
    args = ap.parse_args()

    W, H = args.width, args.height
    fx = args.fx if args.fx > 0 else 0.79 * W
    K = np.array([[fx, 0.0, W / 2.0], [0.0, fx, H / 2.0], [0.0, 0.0, 1.0]])
    scene = build_scene()
    out = os.path.abspath(args.out)
    os.makedirs(os.path.join(out, "images"), exist_ok=True)
    os.makedirs(os.path.join(out, "val", "images"), exist_ok=True)

    def write_split(cams, img_save_dir, prefix, meta_path, time_offset):
        frames = []
        t = 0.0
        for i, (M, C) in enumerate(cams):
            img = render_view(scene, M, K, W, H, ssaa=args.ssaa)
            rel = "images/%s%04d.png" % (prefix, i + 1)       # 相对 image_root
            Image.fromarray(img).save(os.path.join(img_save_dir, "%s%04d.png" % (prefix, i + 1)))
            c2w = M.reshape(-1).tolist()
            frames.append({
                "file": rel,
                "c2w": c2w,
                "gps": gps_from_ue(C),
                "gimbal_deg": gimbal_from_c2w(M),
                "timestamp": round(time_offset + i * 2.0, 2),
            })
            print("  rendered %s" % rel, flush=True)
        meta = {
            "dataset": "synthetic_dji_mini4pro_campus_v1",
            "camera_model": "DJI Mini 4 Pro (simulated, %.0fmm equiv)" % (24.0),
            "width": W, "height": H,
            "fx": float(K[0, 0]), "fy": float(K[1, 1]), "cx": float(K[0, 2]), "cy": float(K[1, 2]),
            "coord_system": "UE_LHS_Zup_cm",
            "origin_wgs84": ORIGIN_WGS84,
            "frames": frames,
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        return frames

    print("[make_synthetic_scene] render train split (%d views) ..." % args.n_train, flush=True)
    train_cams = generate_cameras(args.n_train, args.seed, (4200, 6800), (2200, 4200), phase=0.0)
    write_split(train_cams, os.path.join(out, "images"), "", os.path.join(out, "metadata.json"), 0.0)

    print("[make_synthetic_scene] render val split (%d views) ..." % args.n_val, flush=True)
    val_cams = generate_cameras(args.n_val, args.seed + 100, (4600, 7000), (2500, 4000), phase=0.5)
    write_split(val_cams, os.path.join(out, "val", "images"), "val_", os.path.join(out, "val", "metadata_val.json"), 500.0)

    # 预览拼图（报告用）
    try:
        import glob
        paths = sorted(glob.glob(os.path.join(out, "images", "*.png")))
        tiles = [np.asarray(Image.open(p).resize((240, 180))) for p in paths[:12]]
        if tiles:
            cols = 4
            rows = int(math.ceil(len(tiles) / cols))
            sheet = np.zeros((rows * 180, cols * 240, 3), np.uint8)
            for k, t in enumerate(tiles):
                r, c = divmod(k, cols)
                sheet[r * 180:(r + 1) * 180, c * 240:(c + 1) * 240] = t
            Image.fromarray(sheet).save(os.path.join(out, "preview.png"))
    except Exception as e:  # noqa: BLE001
        print("[make_synthetic_scene] preview failed:", e)

    print("[make_synthetic_scene] done -> %s (%dx%d, %d train + %d val)" % (
        out, W, H, args.n_train, args.n_val))


if __name__ == "__main__":
    main()
