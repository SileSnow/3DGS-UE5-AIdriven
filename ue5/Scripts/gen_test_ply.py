#!/usr/bin/env python3
"""Generate synthetic standard-3DGS PLY files for UE5 renderer / performance tests.

Layouts follow graphdeco-inria/gaussian-splatting save_ply():
  x y z nx ny nz f_dc_0..2 opacity scale_0..2 rot_0..3 [f_rest_0..44]
binary_little_endian 1.0, float32.

Positions are written directly in the UE coordinate system used by shared/CONVENTIONS.md
(X forward, Y right, Z up, centimetres), so the UE loader must be run with -SplatUECoords=1.

Usage:
  python gen_test_ply.py --kind sphere --count 50000 --out test_data/sphere_50k.ply
  python gen_test_ply.py --all --outdir test_data
"""
import argparse
import os
import struct
import time

import numpy as np

SH_C0 = 0.28209479177387814


def make_dtype(with_rest=True):
    props = [
        "x", "y", "z", "nx", "ny", "nz",
        "f_dc_0", "f_dc_1", "f_dc_2",
        "opacity", "scale_0", "scale_1", "scale_2",
        "rot_0", "rot_1", "rot_2", "rot_3",
    ]
    if with_rest:
        props += [f"f_rest_{i}" for i in range(45)]
    return props, np.dtype([(p, "<f4") for p in props])


def random_quaternions(n, rng):
    q = rng.normal(size=(n, 4))
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    return q  # w,x,y,z order


def write_ply(path, data, props):
    n = len(data)
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {n}"]
    header += [f"property float {p}" for p in props]
    header.append("end_header")
    with open(path, "wb") as f:
        f.write(("\n".join(header) + "\n").encode("ascii"))
        data.tofile(f)


def sph_dc(srgb_rgb):
    """sRGB [0,1] -> SH DC coefficients (what the UE loader decodes back to sRGB)."""
    return (srgb_rgb - 0.5) / SH_C0


def build_record_array(n, props):
    return np.zeros(n, dtype=np.dtype([(p, "<f4") for p in props]))


def gen_sphere(n, rng, props):
    d = build_record_array(n, props)
    # points on a slightly noisy sphere, radius 300cm, centre at (0,0,300)
    u = rng.normal(size=(n, 3))
    u /= np.linalg.norm(u, axis=1, keepdims=True)
    radius = 300.0 * (1.0 + rng.normal(0, 0.02, size=(n, 1)))
    pos = u * radius + np.array([0.0, 0.0, 300.0])
    d["x"], d["y"], d["z"] = pos[:, 0], pos[:, 1], pos[:, 2]
    # colour from direction: r = +x, g = +y, b = +z (torus-like palette)
    srgb = np.clip((u + 1.0) * 0.5, 0.0, 1.0)
    dc = sph_dc(srgb)
    d["f_dc_0"], d["f_dc_1"], d["f_dc_2"] = dc[:, 0], dc[:, 1], dc[:, 2]
    # anisotropic log scales: 2..8 cm, random axis compress
    base = rng.uniform(2.0, 8.0, size=(n, 3))
    aniso = rng.uniform(0.4, 1.0, size=(n, 1))
    sizes = base * np.concatenate([aniso, np.ones((n, 1)), 1.0 / aniso], axis=1)
    d["scale_0"], d["scale_1"], d["scale_2"] = np.log(sizes).T
    q = random_quaternions(n, rng)
    d["rot_0"], d["rot_1"], d["rot_2"], d["rot_3"] = q.T
    d["opacity"] = rng.uniform(2.0, 5.0, size=n)  # sigmoid -> ~0.88..0.99
    return d


def gen_terrain(n, rng, props):
    d = build_record_array(n, props)
    side = int(np.ceil(np.sqrt(n)))
    xs = np.linspace(-1500, 1500, side)
    ys = np.linspace(-1500, 1500, side)
    gx, gy = np.meshgrid(xs, ys)
    pos = np.stack([gx.ravel()[:n], gy.ravel()[:n], np.zeros(n)], axis=1)
    height = (
        120.0 * np.sin(pos[:, 0] / 420.0) * np.cos(pos[:, 1] / 380.0)
        + 40.0 * np.sin((pos[:, 0] + pos[:, 1]) / 150.0)
    )
    pos[:, 2] = height + 50.0
    d["x"], d["y"], d["z"] = pos[:, 0], pos[:, 1], pos[:, 2]
    h = (height - height.min()) / max(1e-6, (height.max() - height.min()))
    srgb = np.stack([0.15 + 0.55 * h, 0.45 + 0.35 * (1.0 - h), 0.20 + 0.25 * h], axis=1)
    dc = sph_dc(np.clip(srgb, 0, 1))
    d["f_dc_0"], d["f_dc_1"], d["f_dc_2"] = dc[:, 0], dc[:, 1], dc[:, 2]
    sizes = rng.uniform(3.0, 7.0, size=(n, 1)) * np.array([1.0, 1.0, 0.5])
    d["scale_0"], d["scale_1"], d["scale_2"] = np.log(sizes).T
    q = random_quaternions(n, rng)
    d["rot_0"], d["rot_1"], d["rot_2"], d["rot_3"] = q.T
    d["opacity"] = rng.uniform(3.0, 4.5, size=n)
    return d


def gen_axis_check(n, rng, props):
    """Three coloured bars along +X (red), +Y (green), +Z (blue) to verify axis mapping."""
    d = build_record_array(n, props)
    per = n // 3
    parts = []
    for axis, colour in ((0, (0.9, 0.1, 0.1)), (1, (0.1, 0.9, 0.1)), (2, (0.15, 0.2, 0.95))):
        t = rng.uniform(-200.0, 600.0, size=per)
        p = np.zeros((per, 3))
        p[:, axis] = t
        jitter = rng.normal(0, 6.0, size=(per, 3))
        p += jitter
        parts.append((p, colour))
    pos = np.concatenate([p for p, _ in parts], axis=0)[:n]
    colours = np.concatenate([np.tile(c, (len(p), 1)) for p, c in parts], axis=0)[:n]
    d["x"], d["y"], d["z"] = pos[:, 0], pos[:, 1], pos[:, 2]
    dc = sph_dc(np.clip(colours, 0, 1))
    d["f_dc_0"], d["f_dc_1"], d["f_dc_2"] = dc[:, 0], dc[:, 1], dc[:, 2]
    sizes = rng.uniform(2.0, 4.0, size=(n, 3))
    d["scale_0"], d["scale_1"], d["scale_2"] = np.log(sizes).T
    q = random_quaternions(n, rng)
    d["rot_0"], d["rot_1"], d["rot_2"], d["rot_3"] = q.T
    d["opacity"] = rng.uniform(3.0, 5.0, size=n)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="sphere", choices=["sphere", "terrain", "axis"])
    ap.add_argument("--count", type=int, default=50000)
    ap.add_argument("--out", default="")
    ap.add_argument("--outdir", default="test_data")
    ap.add_argument("--no-rest", action="store_true", help="omit f_rest_* (smaller files)")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    rng = np.random.default_rng(1234)
    props, _ = make_dtype(with_rest=not args.no_rest)

    jobs = []
    if args.all:
        for kind, count in (("axis", 6000), ("terrain", 200000),
                            ("sphere", 50000), ("sphere", 200000),
                            ("sphere", 500000), ("sphere", 1000000)):
            name = f"{kind}_{count // 1000}k.ply"
            jobs.append((kind, count, os.path.join(args.outdir, name)))
    else:
        name = args.out or os.path.join(args.outdir, f"{args.kind}_{args.count // 1000}k.ply")
        jobs.append((args.kind, args.count, name))

    os.makedirs(args.outdir, exist_ok=True)
    for kind, count, out in jobs:
        t0 = time.time()
        gen = {"sphere": gen_sphere, "terrain": gen_terrain, "axis": gen_axis_check}[kind]
        data = gen(count, rng, props)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        write_ply(out, data, props)
        size_mb = os.path.getsize(out) / (1024 * 1024)
        print(f"[gen] {kind:8s} {count:>9,d} splats -> {out}  {size_mb:8.1f} MB  {time.time() - t0:6.2f}s")


if __name__ == "__main__":
    main()
