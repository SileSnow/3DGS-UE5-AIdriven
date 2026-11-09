#!/usr/bin/env python3
"""CPU reference projection renderer for standard 3DGS PLY files.

Produces a cheap "offline reference" image (screen-space gaussian discs, alpha composited
front-to-back by depth) with the same orbit camera convention as ASplatTestActor, so UE
screenshots can be compared side by side. It is NOT an EWA splatter -- just a sanity check
of coordinates / colors / opacity / coverage.

Usage:
  python render_ply_reference.py --ply <path> --out <png> [--yaw-deg 0] [--fov 60]
                                 [--camera-distance auto] [--elevation 0.35] [--ue-coords 1]
"""
import argparse
import os

import numpy as np
from PIL import Image

SH_C0 = 0.28209479177387814


def load_ply(path, ue_coords=True):
    with open(path, "rb") as f:
        data = f.read()
    end = data.find(b"end_header\n") + len(b"end_header\n")
    header = data[:end].decode("ascii")
    lines = header.splitlines()
    props = [l.split()[-1] for l in lines if l.startswith("property")]
    n = int([l for l in lines if l.startswith("element vertex")][0].split()[-1])
    arr = np.frombuffer(data[end:end + n * len(props) * 4], dtype="<f4").reshape(n, len(props))
    col = {p: i for i, p in enumerate(props)}

    pos = np.stack([arr[:, col["x"]], arr[:, col["y"]], arr[:, col["z"]]], axis=1).astype(np.float64)
    scale = np.exp(np.stack([arr[:, col["scale_0"]], arr[:, col["scale_1"]], arr[:, col["scale_2"]]], axis=1)).astype(np.float64)
    opacity = 1.0 / (1.0 + np.exp(-arr[:, col["opacity"]].astype(np.float64)))
    dc = np.stack([arr[:, col["f_dc_0"]], arr[:, col["f_dc_1"]], arr[:, col["f_dc_2"]]], axis=1).astype(np.float64)
    srgb = np.clip(SH_C0 * dc + 0.5, 0.0, 1.0)
    if not ue_coords:
        # COLMAP meters -> UE cm: (x, -z, -y) * 100
        pos = np.stack([pos[:, 0], -pos[:, 2], -pos[:, 1]], axis=1) * 100.0
        scale = np.stack([scale[:, 0], scale[:, 2], scale[:, 1]], axis=1) * 100.0
    return pos, scale, srgb, opacity


def look_at(eye, target, up=(0.0, 0.0, 1.0)):
    eye = np.asarray(eye, dtype=np.float64)
    fwd = np.asarray(target, dtype=np.float64) - eye
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, np.asarray(up, dtype=np.float64))
    right /= np.linalg.norm(right)
    upv = np.cross(right, fwd)
    return eye, right, upv, fwd


def render(pos, scale, srgb, opacity, out_png, w=1280, h=720, fov_deg=60.0, yaw_deg=0.0,
           cam_distance=None, elevation_frac=0.35, dist_scale=1.0):
    lo = np.quantile(pos, 0.02, axis=0)
    hi = np.quantile(pos, 0.98, axis=0)
    center = (lo + hi) * 0.5
    radius = float(np.linalg.norm(hi - lo) * 0.5)
    if cam_distance is None:
        cam_distance = max(100.0, radius * 2.2)
        if radius > 4000.0:
            cam_distance = min(16000.0, max(12000.0, radius * 2.2))
    yaw = np.radians(yaw_deg)
    eye = center + np.array([np.cos(yaw) * cam_distance * dist_scale, np.sin(yaw) * cam_distance * dist_scale, cam_distance * elevation_frac])
    eye, right, up, fwd = look_at(eye, center)

    rel = pos - eye
    depth = rel @ fwd
    focal = (h * 0.5) / np.tan(np.radians(fov_deg) * 0.5)
    sx = (rel @ right) / np.maximum(depth, 1e-3) * focal + w * 0.5
    sy = -(rel @ up) / np.maximum(depth, 1e-3) * focal + h * 0.5
    pix_radius = (scale.max(axis=1) / np.maximum(depth, 1e-3)) * focal

    keep = (depth > 1.0) & (sx > -50) & (sx < w + 50) & (sy > -50) & (sy < h + 50) & (pix_radius > 0.15)
    idx = np.nonzero(keep)[0]
    idx = idx[np.argsort(-depth[idx])]  # far to near

    img = np.zeros((h, w, 3), dtype=np.float64)
    for i in idx:
        r = max(0.5, float(pix_radius[i]))
        x0, x1 = int(np.clip(sx[i] - r, 0, w)), int(np.clip(sx[i] + r + 1, 0, w))
        y0, y1 = int(np.clip(sy[i] - r, 0, h)), int(np.clip(sy[i] + r + 1, 0, h))
        if x0 >= x1 or y0 >= y1:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        d2 = ((xx - sx[i]) ** 2 + (yy - sy[i]) ** 2) / (r * r)
        a = float(np.clip(opacity[i], 0.0, 0.999)) * np.exp(-2.0 * d2)
        img[y0:y1, x0:x1] = img[y0:y1, x0:x1] * (1 - a[..., None]) + srgb[i] * a[..., None]

    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    Image.fromarray((np.clip(img, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)).save(out_png)
    stats = dict(center=center.tolist(), radius=radius, cam_distance=float(cam_distance),
                 eye=eye.tolist(), splats=int(len(pos)), kept=int(len(idx)),
                 yaw_deg=yaw_deg, fov_deg=fov_deg)
    print("[ref]", out_png, "splats", len(pos), "kept", len(idx), "center", np.round(center, 1).tolist(),
          "radius", round(radius, 1), "cam", np.round(eye, 1).tolist())
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ply", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--yaw-deg", type=float, default=0.0)
    ap.add_argument("--fov", type=float, default=60.0)
    ap.add_argument("--camera-distance", type=float, default=0.0)
    ap.add_argument("--elevation", type=float, default=0.35)
    ap.add_argument("--resolution", default="1280x720")
    ap.add_argument("--ue-coords", type=int, default=1)
    ap.add_argument("--dist-scale", type=float, default=1.0)
    args = ap.parse_args()
    w, h = [int(v) for v in args.resolution.split("x")]
    pos, scale, srgb, opacity = load_ply(args.ply, bool(args.ue_coords))
    render(pos, scale, srgb, opacity, args.out, w=w, h=h, fov_deg=args.fov, yaw_deg=args.yaw_deg,
           cam_distance=(args.camera_distance if args.camera_distance > 0 else None),
           elevation_frac=args.elevation, dist_scale=args.dist_scale)


if __name__ == "__main__":
    main()