"""从 ZEUS L4 白模生成 L5 的 180,000 高斯规范草稿。

两种输入：
  --demo                 造 12 栋合成街区（无需任何外部数据）
  --bld PATH             读 ZEUS 前端建筑分块 bld/t_*.bin.gz（真实数据）

输出：
  l5_scene.json          规范（含 inferred_facades / trained_radiance_field）
  gaussians.ply          3DGS 标准 PLY（字段见 dji_ue5_3dgs/shared/CONVENTIONS.md）
  l4_block.json          L4 子集（便于评审/复现）

本脚本只做「摆放 + 启发式颜色」，不训练；因此 trained_radiance_field 永远是 false。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# 允许从任意工作目录直接运行：以本文件所在目录定位同目录的 zeus_frame.py
sys.path.insert(0, str(Path(__file__).resolve().parent))

from zeus_frame import (
    LocalFrame,
    building_ring,
    read_bld_tile,
    ring_area,
    ring_perimeter,
)

USE_COLORS = {
    "RES": (0.62, 0.58, 0.52),
    "COM": (0.55, 0.60, 0.66),
    "IND": (0.60, 0.52, 0.45),
    "OTHER": (0.58, 0.58, 0.58),
}
SH_C0 = 0.28209479177387814


@dataclass
class Building:
    bldg_id: str
    ring: np.ndarray
    base: float
    height: float
    use: str
    storeys: int
    material: str
    footprint_m2: float
    floor_area_m2: float
    repl_cost_usd: float
    night_occupants: float


def _normalize(v):
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else np.array([0.0, 1.0, 0.0])


def quat_from_z_to(n):
    """四元数 (w,x,y,z)，把局部 +Z 旋到 n。"""
    n = _normalize(np.asarray(n, dtype=np.float64))
    d = float(n[2])
    if d > 0.999999:
        return np.array([1.0, 0.0, 0.0, 0.0])
    if d < -0.999999:
        return np.array([0.0, 1.0, 0.0, 0.0])
    axis = np.cross(np.array([0.0, 0.0, 1.0]), n)
    s = math.sqrt(2.0 * (1.0 + d))
    return np.array([0.5 * s, axis[0] / s, axis[1] / s, axis[2] / s])


def demo_buildings(count: int = 12) -> list[Building]:
    rng = np.random.default_rng(20261120)
    heights = [9, 12, 15, 18, 22, 26, 31, 36, 42, 12, 19, 24]
    uses = ["RES", "RES", "COM", "RES", "COM", "RES", "IND", "RES", "COM", "RES", "OTHER", "RES"]
    mats = ["W", "RC", "RC", "W", "S", "RC", "S", "RC", "RC", "W", "CR", "RC"]
    out = []
    cols = 4
    for k in range(count):
        r, c = divmod(k, cols)
        x0 = -110.0 + c * 55.0
        z0 = -80.0 + r * 50.0
        w = 22.0 + float(rng.integers(-3, 4))
        d = 14.0 + float(rng.integers(-2, 3))
        ring = np.array([[x0, z0], [x0 + w, z0], [x0 + w, z0 + d], [x0, z0 + d]], dtype=np.float64)
        out.append(
            Building(
                bldg_id=f"bldg_demo_{k:04d}",
                ring=ring,
                base=0.0,
                height=float(heights[k % len(heights)]),
                use=uses[k % len(uses)],
                storeys=int(max(1, round(heights[k % len(heights)] / 3.2))),
                material=mats[k % len(mats)],
                footprint_m2=float(w * d),
                floor_area_m2=float(w * d * max(1, round(heights[k % len(heights)] / 3.2))),
                repl_cost_usd=float((w * d) * heights[k % len(heights)] * 120.0),
                night_occupants=float(rng.integers(0, 40)),
            )
        )
    return out


def buildings_from_tile(path, attr_stride=24) -> list[Building]:
    tile = read_bld_tile(path, attr_stride)
    uses = ["RES", "COM", "IND", "OTHER"]
    mats = ["W", "CR", "SRC", "S", "UNK"]
    out = []
    for k in range(tile["n"]):
        ring = building_ring(tile, k)
        if len(ring) < 3:
            continue
        attr = tile["attr"][k]
        use = uses[int(attr[0])] if int(attr[0]) < len(uses) else "OTHER"
        mat = mats[int(attr[12])] if int(attr[12]) < len(mats) else "UNK"
        fp = float(attr[18] | (attr[19] << 8))
        fa = float(attr[20] | (attr[21] << 8)) * 10.0
        out.append(
            Building(
                bldg_id=f"bldg_{int(tile['row'][k]):07d}",
                ring=ring,
                base=float(tile["base"][k]),
                height=float(tile["height"][k]),
                use=use,
                storeys=int(attr[11]),
                material=mat,
                footprint_m2=fp,
                floor_area_m2=fa,
                repl_cost_usd=float(tile["cost"][k]),
                night_occupants=float(tile["occ"][k]),
            )
        )
    return out


def crop(buildings, center, size_m):
    cx, cz = center
    half = size_m / 2.0
    out = []
    for b in buildings:
        mx = float(b.ring[:, 0].mean())
        mz = float(b.ring[:, 1].mean())
        if abs(mx - cx) <= half and abs(mz - cz) <= half:
            out.append(b)
    return out


def _points_in_polygon(x, z, ring):
    inside = np.zeros(x.shape, dtype=bool)
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, zi = ring[i]
        xj, zj = ring[j]
        cond = ((zi > z) != (zj > z)) & (x < (xj - xi) * (z - zi) / (zj - zi + 1e-12) + xi)
        inside ^= cond
        j = i
    return inside


def _roof_samples(b, n, rng):
    x0, z0 = b.ring[:, 0].min(), b.ring[:, 1].min()
    x1, z1 = b.ring[:, 0].max(), b.ring[:, 1].max()
    if n <= 0:
        return np.zeros((0, 3))
    out = []
    need = n
    for _ in range(6):
        cand = np.column_stack([
            rng.uniform(x0, x1, need * 3),
            rng.uniform(z0, z1, need * 3),
        ])
        mask = _points_in_polygon(cand[:, 0], cand[:, 1], b.ring)
        got = cand[mask][:need]
        out.append(got)
        need -= len(got)
        if need <= 0:
            break
    pts = np.vstack(out) if out else np.zeros((0, 2))
    if len(pts) < n:  # 极窄多边形兜底：质心抖动
        cx, cz = b.ring[:, 0].mean(), b.ring[:, 1].mean()
        extra = np.column_stack([cx + rng.normal(0, 0.3, n - len(pts)), cz + rng.normal(0, 0.3, n - len(pts))])
        pts = np.vstack([pts, extra])
    y = np.full((n, 1), b.base + b.height)
    # 2026-11-22 修复：屋面原先返回 (x, z_south, y_up)，与墙面的 (x, y_up, z_south) 不一致；
    # 统一为 ZEUS 局部 (x 东, y 上, z 南)，这样 --unit cm 的 [0,2,1] 对屋面/墙面都成立。
    return np.column_stack([pts[:n, 0], y[:, 0], pts[:n, 1]])


def _wall_samples(b, n, rng):
    if n <= 0:
        return np.zeros((0, 3)), np.zeros((0, 3))
    ring = b.ring
    nxt = np.roll(ring, -1, axis=0)
    d = nxt - ring
    length = np.hypot(d[:, 0], d[:, 1])
    total = float(length.sum())
    if total <= 0:
        return np.zeros((0, 3)), np.zeros((0, 3))
    edge = rng.choice(len(ring), size=n, p=length / total)
    t = rng.random(n)
    pos = ring[edge] + t[:, None] * d[edge]
    normal = np.column_stack([d[edge, 1], -d[edge, 0]])
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
    mid = pos - ring[edge]
    centroid = ring.mean(axis=0)
    to_out = (ring[edge] + 0.5 * d[edge]) - centroid
    flip = np.sum(normal * to_out, axis=1) < 0
    normal[flip] *= -1.0
    pos = pos + normal * 0.05
    y = b.base + rng.random(n) * b.height
    return np.column_stack([pos[:, 0], y, pos[:, 1]]), np.column_stack([normal[:, 0], np.zeros(n), normal[:, 1]])


def allocate(buildings, count):
    weights = np.array([
        max(1.0, ring_area(b.ring) + ring_perimeter(b.ring) * b.height) for b in buildings
    ])
    raw = count * weights / weights.sum()
    counts = np.maximum(6, np.round(raw).astype(np.int64))
    diff = int(count - counts.sum())
    while diff > 0:
        counts[int(np.argmin(counts))] += 1
        diff -= 1
    while diff < 0:
        idx = int(np.argmax(counts))
        if counts[idx] <= 6:
            break
        counts[idx] -= 1
        diff += 1
    return counts


def sample(buildings, count, seed=20261120):
    rng = np.random.default_rng(seed)
    counts = allocate(buildings, count)
    pos_all, nrm_all, scale_all, color_all, quat_all, bid_all = [], [], [], [], [], []
    for k, (b, n) in enumerate(zip(buildings, counts)):
        roof_area = max(1e-6, ring_area(b.ring))
        wall_area = max(1e-6, ring_perimeter(b.ring) * b.height)
        n_roof = int(round(n * roof_area / (roof_area + wall_area)))
        n_wall = n - n_roof
        rp = _roof_samples(b, n_roof, rng)
        wp, wn = _wall_samples(b, n_wall, rng)

        base_rgb = np.array(USE_COLORS.get(b.use, USE_COLORS["OTHER"]))
        roof_rgb = np.clip(base_rgb + 0.06 + rng.normal(0, 0.015, (len(rp), 3)), 0, 1)
        wall_rgb = np.clip(base_rgb + rng.normal(0, 0.025, (len(wp), 3)), 0, 1)

        pos = np.vstack([rp, wp])
        nrm = np.vstack([np.tile([0.0, 1.0, 0.0], (len(rp), 1)), wn])
        rgb = np.vstack([roof_rgb, wall_rgb])
        scale = np.vstack([
            np.tile([0.24, 0.24, 0.08], (len(rp), 1)),
            np.tile([0.25, 0.30, 0.05], (len(wp), 1)),
        ])
        quat = np.array([quat_from_z_to(v) for v in nrm])
        pos_all.append(pos)
        nrm_all.append(nrm)
        scale_all.append(scale)
        color_all.append(rgb)
        quat_all.append(quat)
        bid_all.append(np.full(len(pos), k, dtype=np.int32))

    return (
        np.vstack(pos_all).astype(np.float64),
        np.vstack(nrm_all).astype(np.float64),
        np.vstack(scale_all).astype(np.float64),
        np.vstack(color_all).astype(np.float64),
        np.vstack(quat_all).astype(np.float64),
        np.concatenate(bid_all),
        counts,
    )


def write_ply(path: Path, pos, nrm, rgb, scale, quat, unit="m"):
    n = len(pos)
    if unit == "cm":
        # ZEUS (x 东, y 上, z 南, m) -> UE (X 东, Y 南, Z 上, cm)
        pos = pos[:, [0, 2, 1]] * 100.0
        nrm = nrm[:, [0, 2, 1]]
        scale = scale[:, [0, 2, 1]] * 100.0
        quat = np.array([quat_from_z_to(v) for v in nrm])

    sh_dc = (rgb - 0.5) / SH_C0
    opacity = np.full(n, math.log(0.85 / 0.15))
    data = np.zeros((n, 62), dtype="<f4")
    data[:, 0:3] = pos
    data[:, 3:6] = nrm
    data[:, 6:9] = sh_dc
    data[:, 9:54] = 0.0
    data[:, 54] = opacity
    data[:, 55:58] = np.log(np.maximum(scale, 1e-4))
    data[:, 58:62] = quat

    header = [
        "ply",
        "format binary_little_endian 1.0",
        f"element vertex {n}",
        "property float x", "property float y", "property float z",
        "property float nx", "property float ny", "property float nz",
        "property float f_dc_0", "property float f_dc_1", "property float f_dc_2",
    ]
    header += [f"property float f_rest_{i}" for i in range(45)]
    header += [
        "property float opacity",
        "property float scale_0", "property float scale_1", "property float scale_2",
        "property float rot_0", "property float rot_1", "property float rot_2", "property float rot_3",
        "end_header",
    ]
    path.write_bytes(("\n".join(header) + "\n").encode("ascii") + data.tobytes())
    return path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="L4 -> L5 180k Gaussian spec generator")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--bld", type=Path)
    ap.add_argument("--attr-stride", type=int, default=24)
    ap.add_argument("--count", type=int, default=180000)
    ap.add_argument("--out", type=Path, default=Path("out/l5_demo"))
    ap.add_argument("--scene-id", default=None)
    ap.add_argument("--seed", type=int, default=20261120)
    ap.add_argument("--center-x", type=float, default=None)
    ap.add_argument("--center-z", type=float, default=None)
    ap.add_argument("--size-m", type=float, default=300.0)
    ap.add_argument("--unit", choices=["m", "cm"], default="m")
    ap.add_argument("--no-ply", action="store_true")
    args = ap.parse_args(argv)

    if not args.demo and not args.bld:
        ap.error("需要 --demo 或 --bld 之一")

    if args.demo:
        buildings = demo_buildings()
        center = (0.0, 0.0)
    else:
        buildings = buildings_from_tile(args.bld, args.attr_stride)
        if args.center_x is None or args.center_z is None:
            allx = np.concatenate([b.ring[:, 0] for b in buildings])
            allz = np.concatenate([b.ring[:, 1] for b in buildings])
            center = (float((allx.min() + allx.max()) / 2), float((allz.min() + allz.max()) / 2))
        else:
            center = (args.center_x, args.center_z)
        buildings = crop(buildings, center, args.size_m)
        if not buildings:
            ap.error("裁剪后没有建筑；检查 --center-x/--center-z/--size-m")

    if not buildings:
        ap.error("没有可用的建筑")

    t0 = time.time()
    pos, nrm, rgb, scale, quat, bid, counts = sample(buildings, args.count, args.seed)
    if len(pos) != args.count:
        ap.error(f"采样数 {len(pos)} != {args.count}")

    args.out.mkdir(parents=True, exist_ok=True)
    scene_id = args.scene_id or ("tokyo_demo_300m" if args.demo else f"tokyo_{int(args.size_m)}m")
    ply_path = args.out / "gaussians.ply"
    if not args.no_ply:
        write_ply(ply_path, pos, nrm, rgb, scale, quat, args.unit)
        ply_sha = sha256(ply_path)
    else:
        ply_sha = None

    frame = LocalFrame()
    l4 = {
        "schema": "zeus.l4_block/v0.1",
        "frame": {
            "crs": "local_metric",
            "origin_wgs84": {"lon": frame.lon0, "lat": frame.lat0, "alt_m": 0.0},
            "axes": {"x": "east", "y": "up", "z": "south"},
            "units": "m",
            "handedness": "right",
        },
        "source": {"world": "demo" if args.demo else str(args.bld), "city": "tokyo", "tile": "0.02deg"},
        "buildings": [
            {
                "bldg_id": b.bldg_id,
                "ring": [[round(float(x), 3), round(float(z), 3)] for x, z in b.ring],
                "base_m": round(b.base, 3),
                "height_m": round(b.height, 3),
                "use": b.use,
                "storeys": b.storeys,
                "material": b.material,
                "footprint_m2": round(b.footprint_m2, 2),
                "floor_area_m2": round(b.floor_area_m2, 2),
                "repl_cost_usd": round(b.repl_cost_usd, 2),
                "night_occupants": round(b.night_occupants, 2),
            }
            for b in buildings
        ],
    }
    (args.out / "l4_block.json").write_text(
        json.dumps(l4, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    anchors = []
    for b in buildings[:200]:
        cx = float(b.ring[:, 0].mean())
        cz = float(b.ring[:, 1].mean())
        lon, lat = frame.to_wgs84(cx, cz)
        anchors.append({
            "bldg_id": b.bldg_id,
            "local": [round(cx, 3), round(cz, 3)],
            "wgs84": [round(float(lon), 7), round(float(lat), 7)],
        })

    spec = {
        "schema": "zeus.l5_scene/v0.1",
        "level": "L5",
        "viewport": "map3dview",
        "scene_id": scene_id,
        "version": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "frame": l4["frame"],
        "extent": {"center": [round(center[0], 3), round(center[1], 3)], "size_m": [args.size_m, args.size_m]},
        "gaussians": {
            "count": args.count,
            "file": "gaussians.ply" if not args.no_ply else None,
            "format": "3dgs_ply_v1",
            "sh_degree": 3,
            "scale_unit": "m" if args.unit == "m" else "cm",
            "coordinate_system": "zeus_local_m" if args.unit == "m" else "ue_lhs_zup_cm",
            "sha256": ply_sha,
            "ue_import": {"scale": 100, "axis_map": ["x", "z", "y"]},
        },
        "l4_source": {
            "file": "l4_block.json",
            "building_count": len(buildings),
            "tile_ids": [] if args.demo else [args.bld.stem],
        },
        "provenance": {
            "sources": [
                {"id": "bld_world", "license": "GBA/Overture/OSM", "url": "https://github.com/YonganZhang/yz-global-city-resilience-paper3"},
                {"id": "ortho_gsi", "license": "国土地理院 シームレス空中写真", "url": "https://maps.gsi.go.jp/"},
                {"id": "dem_fabdem", "license": "CC BY-NC-SA 4.0", "url": "https://data.bris.ac.uk/"},
            ],
            "inferred_facades": True,
            "trained_radiance_field": False,
            "observed_facade_ratio": 0.0,
            "training_views": 0,
            "val_psnr_db": None,
            "val_ssim": None,
            "color_source": "heuristic_by_use",
            "notes": "Gaussians sampled from L4 extrusion; not optimized against images. "
                     "Replace color_source with ortho when the real block is used.",
        },
        "quality": {
            "floaters_above_roof": None,
            "roof_coverage": None,
            "height_mae_m": None,
        },
        "anchors": anchors,
    }
    (args.out / "l5_scene.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps({
        "scene_id": scene_id,
        "out": str(args.out),
        "buildings": len(buildings),
        "gaussians": args.count,
        "counts_min_max": [int(counts.min()), int(counts.max())],
        "ply_bytes": ply_path.stat().st_size if ply_path.exists() else 0,
        "unit": args.unit,
        "seconds": round(time.time() - t0, 2),
        "flags": {"inferred_facades": True, "trained_radiance_field": False},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
