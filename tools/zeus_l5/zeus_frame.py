"""ZEUS 局部坐标 / 地形 / L4 建筑分块 的轻量读取器（标准库 + numpy）。

不依赖 rasterio / shapely / pyarrow，也不要求仓库里那 1.6 TB 外部数据。
用法见同目录 README.md。
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# 东京城市视图的原点与投影常数（build_city23.py CITIES["tokyo"]）
TOKYO_ORIGIN_LON = 139.7525
TOKYO_ORIGIN_LAT = 35.665
M_PER_DEG_LAT = 110574.0


def kx_at(lat_deg: float) -> float:
    return math.cos(math.radians(lat_deg)) * 111320.0


@dataclass
class LocalFrame:
    """ZEUS 城市局部坐标：x 东、z 南、y 上，单位米。"""

    lon0: float = TOKYO_ORIGIN_LON
    lat0: float = TOKYO_ORIGIN_LAT
    ky: float = M_PER_DEG_LAT

    def __post_init__(self) -> None:
        self.kx = kx_at(self.lat0)

    def to_local(self, lon, lat):
        lon_a = np.asarray(lon, dtype=np.float64)
        lat_a = np.asarray(lat, dtype=np.float64)
        return (lon_a - self.lon0) * self.kx, -(lat_a - self.lat0) * self.ky

    def to_wgs84(self, x, z):
        x_a = np.asarray(x, dtype=np.float64)
        z_a = np.asarray(z, dtype=np.float64)
        return self.lon0 + x_a / self.kx, self.lat0 - z_a / self.ky

    def to_ue_cm(self, x, y, z, origin_cm=(0.0, 0.0, 0.0)):
        """ZEUS (x 东, y 上, z 南, 米) -> 本项目 UE (X 东, Y 南, Z 上, 厘米)。"""
        ox, oy, oz = origin_cm
        return (
            np.asarray(x) * 100.0 + ox,
            np.asarray(z) * 100.0 + oy,
            np.asarray(y) * 100.0 + oz,
        )


class Terrain:
    """terrain.json + terrain.bin.gz。"""

    def __init__(self, meta: dict, z_m: np.ndarray, sea: np.ndarray):
        self.meta = meta
        self.z = z_m.astype(np.float32)
        self.sea = sea.astype(np.uint8)
        self.ncol = int(meta["ncol"])
        self.nrow = int(meta["nrow"])
        self.tile_deg = float(meta["tileDeg"])
        self.tseg = int(meta["tseg"])
        self.dom = meta["dom"]
        self.frame = LocalFrame(
            float(meta["origin"]["lon"]), float(meta["origin"]["lat"])
        )

    def _fractional(self, x, z):
        lon, lat = self.frame.to_wgs84(x, z)
        step = self.tile_deg / self.tseg
        fx = (lon - self.dom["lon0"]) / step
        fy = (self.dom["lat1"] - lat) / step
        return fx, fy

    def height_at(self, x, z):
        """双线性插值；域外返回 0（与 city.js heightAt 一致）。"""
        fx, fy = self._fractional(np.asarray(x, float), np.asarray(z, float))
        scalar = np.ndim(fx) == 0
        fx = np.atleast_1d(np.asarray(fx, float))
        fy = np.atleast_1d(np.asarray(fy, float))
        out = np.zeros(fx.shape, dtype=np.float64)
        valid = (fx >= 0) & (fy >= 0) & (fx <= self.ncol - 1) & (fy <= self.nrow - 1)
        if np.any(valid):
            i = np.minimum(self.ncol - 2, np.floor(fx[valid]).astype(np.int64))
            j = np.minimum(self.nrow - 2, np.floor(fy[valid]).astype(np.int64))
            u = fx[valid] - i
            v = fy[valid] - j
            w = self.ncol
            Z = self.z.reshape(-1)
            out[valid] = (
                (Z[j * w + i] * (1 - u) + Z[j * w + i + 1] * u) * (1 - v)
                + (Z[(j + 1) * w + i] * (1 - u) + Z[(j + 1) * w + i + 1] * u) * v
            )
        return float(out[0]) if scalar else out

    def sea_at(self, x, z):
        fx, fy = self._fractional(np.asarray(x, float), np.asarray(z, float))
        i = int(np.clip(round(float(np.atleast_1d(fx)[0])), 0, self.ncol - 1))
        j = int(np.clip(round(float(np.atleast_1d(fy)[0])), 0, self.nrow - 1))
        return int(self.sea[j, i])


def load_terrain(meta_path, bin_path=None) -> Terrain:
    meta_path = Path(meta_path)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    bin_path = Path(bin_path) if bin_path else meta_path.parent / "terrain.bin.gz"
    raw = gzip.decompress(bin_path.read_bytes())
    n = int(meta["ncol"]) * int(meta["nrow"])
    z = np.frombuffer(raw, dtype="<i2", count=n).astype(np.float32) / 10.0
    sea = np.frombuffer(raw, dtype=np.uint8, count=n, offset=n * 2)
    return Terrain(
        meta,
        z.reshape(int(meta["nrow"]), int(meta["ncol"])),
        sea.reshape(int(meta["nrow"]), int(meta["ncol"])),
    )


# ---------------------------------------------------------------- L4 建筑分块
def _align4(off: int) -> int:
    return (off + 3) // 4 * 4


def read_bld_tile(path, attr_stride: int = 24) -> dict:
    """读 bld/t_*.bin.gz（或 tall.bin.gz），返回 numpy 视图。

    布局（prep/build_city23.py::_pack）：
      u32[4] n,nVerts,nRoofIdx,0 | u32 row[n] | u16 rc[n] | u16 tc[n] |
      f32 base,height,cx,cz,cost,occ [n] | u8 attr[n*stride] |
      f32 xy[nVerts*2] | u8 roof[nRoofIdx]
    每段之间补齐到 4 字节。
    """
    path = Path(path)
    raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    n, nv, nr, _ = struct.unpack_from("<4I", raw, 0)
    off = 16

    def take(dtype: str, count: int) -> np.ndarray:
        nonlocal off
        itemsize = np.dtype(dtype).itemsize
        arr = np.frombuffer(raw, dtype=dtype, count=count, offset=off)
        off = _align4(off + count * itemsize)
        return arr

    row = take("<u4", n)
    rc = take("<u2", n)
    tc = take("<u2", n)
    base = take("<f4", n)
    height = take("<f4", n)
    cx = take("<f4", n)
    cz = take("<f4", n)
    cost = take("<f4", n)
    occ = take("<f4", n)
    attr = take("u1", n * attr_stride).reshape(n, attr_stride)
    xy = take("<f4", nv * 2).reshape(nv, 2)
    roof = take("u1", nr)

    if n and int(rc.sum()) != nv:
        raise ValueError(f"{path}: rc.sum()={int(rc.sum())} != nVerts={nv}")
    if n and int(tc.sum()) * 3 != nr:
        raise ValueError(f"{path}: tc.sum()*3={int(tc.sum()) * 3} != nRoofIdx={nr}")

    return dict(
        n=int(n), n_verts=int(nv), n_roof=int(nr), attr_stride=int(attr_stride),
        row=row, rc=rc, tc=tc, base=base, height=height, cx=cx, cz=cz,
        cost=cost, occ=occ, attr=attr, xy=xy, roof=roof,
    )


def building_ring(tile: dict, k: int) -> np.ndarray:
    start = int(tile["rc"][:k].sum())
    m = int(tile["rc"][k])
    return tile["xy"][start:start + m].astype(np.float64)


def ring_area(ring: np.ndarray) -> float:
    x = ring[:, 0]
    z = ring[:, 1]
    return 0.5 * abs(float(np.sum(x * np.roll(z, -1) - np.roll(x, -1) * z)))


def ring_perimeter(ring: np.ndarray) -> float:
    d = np.diff(np.vstack([ring, ring[:1]]), axis=0)
    return float(np.sum(np.hypot(d[:, 0], d[:, 1])))


# ---------------------------------------------------------------- 自检 & CLI
def _pack_tile_for_test(rings, roofs, base, height, cx, cz, cost, occ, attr, stride=24):
    """生成一个与 _pack 同布局的分块，仅用于自检。"""
    n = len(rings)
    xy = np.concatenate(rings).astype("<f4") if n else np.zeros((0, 2), "<f4")
    roof = np.concatenate(roofs).astype("u1") if n else np.zeros(0, "u1")
    rc = np.array([len(r) for r in rings], "<u2")
    tc = np.array([len(r) // 3 for r in roofs], "<u2")
    parts = [
        np.array([n, len(xy), len(roof), 0], "<u4"),
        np.arange(n, dtype="<u4"),
        rc, tc,
        np.asarray(base, "<f4"), np.asarray(height, "<f4"),
        np.asarray(cx, "<f4"), np.asarray(cz, "<f4"),
        np.asarray(cost, "<f4"), np.asarray(occ, "<f4"),
        np.asarray(attr, "u1").reshape(-1),
        xy.reshape(-1), roof,
    ]
    out = bytearray()
    for p in parts:
        out.extend(np.ascontiguousarray(p).tobytes())
        out.extend(b"\0" * ((-len(out)) % 4))
    return bytes(out)


def selftest() -> int:
    frame = LocalFrame()
    x, z = frame.to_local(139.7530, 35.6655)
    lon, lat = frame.to_wgs84(x, z)
    assert abs(lon - 139.7530) < 1e-9 and abs(lat - 35.6655) < 1e-9
    ux, uy, uz = frame.to_ue_cm(10.0, 5.0, -2.0)
    assert (round(float(ux), 3), round(float(uy), 3), round(float(uz), 3)) == (1000.0, -200.0, 500.0)

    # 3x3 地形：中间高 10 m，其余 0
    meta = dict(
        dom=dict(lon0=139.48, lon1=140.00, lat0=35.46, lat1=35.86),
        tileDeg=0.04, tseg=1, ncol=3, nrow=3, unit="dm", row0="north",
        origin=dict(lon=TOKYO_ORIGIN_LON, lat=TOKYO_ORIGIN_LAT, kx=frame.kx, ky=frame.ky),
    )
    # 节点间距 0.04°；x/z 取格点中心附近
    zz = np.zeros((3, 3), np.float32)
    zz[1, 1] = 10.0
    terr = Terrain(meta, zz, np.zeros((3, 3), np.uint8))
    # 第 1 行 / 第 1 列对应的 lon/lat
    lon1 = meta["dom"]["lon0"] + 1 * 0.04
    lat1 = meta["dom"]["lat1"] - 1 * 0.04
    x1, zc = frame.to_local(lon1, lat1)
    assert abs(terr.height_at(float(x1), float(zc)) - 10.0) < 1e-6

    # L4 分块往返
    ring = np.array([[0.0, 0.0], [12.0, 0.0], [12.0, 9.0], [0.0, 9.0]], "<f4")
    roof = np.array([0, 1, 2, 0, 2, 3], "u1")
    attr = np.zeros((1, 24), "u1")
    attr[0, 0], attr[0, 11], attr[0, 12] = 0, 8, 2
    raw = _pack_tile_for_test(
        [ring], [roof], [12.3], [24.0], [6.0], [4.5], [123.0], [18.0], attr
    )
    tmp = Path(__file__).with_name("_selftest_tile.bin")
    tmp.write_bytes(raw)
    try:
        tile = read_bld_tile(tmp, 24)
    finally:
        tmp.unlink(missing_ok=True)
    assert tile["n"] == 1 and tile["n_verts"] == 4 and tile["n_roof"] == 6
    assert abs(float(tile["height"][0]) - 24.0) < 1e-6
    assert int(tile["attr"][0, 11]) == 8
    assert ring_area(building_ring(tile, 0)) == 108.0

    print("selftest OK")
    print(f"frame: kx={frame.kx:.1f} m/deg, ky={frame.ky:.1f} m/deg")
    print(f"terrain center height = {terr.height_at(float(x1), float(zc)):.3f} m")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ZEUS local frame / terrain / L4 tile reader")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--terrain-json", type=Path)
    ap.add_argument("--terrain-bin", type=Path)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--lat", type=float)
    ap.add_argument("--bld", type=Path)
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if args.terrain_json:
        terr = load_terrain(args.terrain_json, args.terrain_bin)
        if args.lon is not None and args.lat is not None:
            x, z = terr.frame.to_local(args.lon, args.lat)
            print(json.dumps({
                "lon": args.lon, "lat": args.lat,
                "x_m": round(float(x), 3), "z_m": round(float(z), 3),
                "height_m": round(terr.height_at(float(x), float(z)), 3),
                "sea": terr.sea_at(float(x), float(z)),
            }, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({
                "ncol": terr.ncol, "nrow": terr.nrow,
                "height_min": round(float(np.nanmin(terr.z)), 2),
                "height_max": round(float(np.nanmax(terr.z)), 2),
                "sea_frac": round(float(terr.sea.mean()), 4),
            }, ensure_ascii=False, indent=2))
        return 0

    if args.bld:
        tile = read_bld_tile(args.bld)
        print(json.dumps({
            "file": str(args.bld),
            "n": tile["n"], "n_verts": tile["n_verts"], "n_roof_idx": tile["n_roof"],
            "height_max_m": round(float(tile["height"].max()) if tile["n"] else 0.0, 2),
            "base_min_m": round(float(tile["base"].min()) if tile["n"] else 0.0, 2),
            "attr_stride": tile["attr_stride"],
        }, ensure_ascii=False, indent=2))
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
