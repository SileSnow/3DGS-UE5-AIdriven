"""02_sfm.py -- 位姿/稀疏重建：已知位姿直通 / pycolmap 增量 SfM / DJI EXIF 先验。

三种模式:
  known : CONVENTIONS metadata.json（c2w 已知）-> COLMAP cameras/images（UE<->COLMAP 换算 + 重投影自检）
  sfm   : 图像目录 -> pycolmap 特征提取/匹配/增量重建 -> COLMAP sparse + 统计
  dji   : DJI 照片 EXIF(GPS+云台) -> COLMAP 粗位姿先验（调用 dji_exif_to_colmap.py；--refine 做精化）
  auto  : 有 metadata.json -> known；有 sparse -> 跳过；否则 -> sfm

用法:
  python pipeline/02_sfm.py --mode known --data data/synthetic/capture --out data/synthetic/capture/colmap
  python pipeline/02_sfm.py --mode sfm --images data/dji/photos --out data/dji/colmap
  python pipeline/02_sfm.py --mode dji --photos data/dji/photos --out data/dji/colmap_prior --refine
输出: <out>/sparse/0/{cameras,images,points3D}.[txt|bin]、<out>/sfm_summary.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from colmap_io import (frames_from_metadata, load_metadata, reprojection_selfcheck,  # noqa: E402
                       verify_colmap_write, write_colmap_text)


def _write_summary(out, summary):
    os.makedirs(out, exist_ok=True)
    p = os.path.join(out, "sfm_summary.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("[02_sfm] " + json.dumps(summary, ensure_ascii=False)[:600])
    print("[02_sfm] -> " + p)
    return summary


def mode_known(data_root, metadata, out, image_root=None):
    data_root = os.path.abspath(data_root)
    meta_path = metadata or os.path.join(data_root, "metadata.json")
    meta = load_metadata(meta_path)
    img_root = image_root or data_root
    frames = frames_from_metadata(meta, image_root=img_root, check_images=True)
    t0 = time.time()
    # 1) UE -> COLMAP 换算自检（同一点两条独立投影路径）
    max_err, mean_err, n = reprojection_selfcheck(
        [f["c2w_ue"] for f in frames], [f["K"] for f in frames], n_points=48)
    # 2) 写 COLMAP text + 读回校验
    sparse_dir = os.path.join(out, "sparse", "0")
    write_colmap_text(sparse_dir, frames)
    verify = verify_colmap_write(sparse_dir, frames)
    summary = {"mode": "known", "dataset": meta.get("dataset", os.path.basename(data_root)),
               "metadata": meta_path, "image_root": img_root,
               "num_images": len(frames), "width": int(meta["width"]), "height": int(meta["height"]),
               "fx": float(meta["fx"]), "fy": float(meta["fy"]),
               "reproj_selfcheck": {"max_px": max_err, "mean_px": mean_err, "n": n,
                                    "pass": bool(max_err < 1.0)},
               "colmap_readback_check": verify,
               "sparse_dir": sparse_dir, "seconds": round(time.time() - t0, 2)}
    return _write_summary(out, summary)


def mode_sfm(images_dir, out, matcher="exhaustive", max_image_size=1600):
    import pycolmap
    images_dir = os.path.abspath(images_dir)
    out = os.path.abspath(out)
    os.makedirs(out, exist_ok=True)
    db = os.path.join(out, "database.db")
    if os.path.exists(db):
        os.remove(db)
    t0 = time.time()
    # pycolmap 4.x 不能直接构造 Database，需用 Database.open(path) 创建/打开（上下文管理器自动 close）
    with pycolmap.Database.open(db) as _db:   # noqa: F841
        pass
    pycolmap.import_images(db, images_dir, pycolmap.CameraMode.SINGLE)
    print("[02_sfm] import_images done (%.1fs)" % (time.time() - t0))
    opts = pycolmap.FeatureExtractionOptions()
    try:
        opts.sift.max_image_size = int(max_image_size)
    except Exception:  # noqa: BLE001
        pass
    pycolmap.extract_features(db, images_dir, camera_mode=pycolmap.CameraMode.SINGLE,
                              extraction_options=opts)
    print("[02_sfm] extract_features done (%.1fs)" % (time.time() - t0))
    if matcher == "sequential":
        pycolmap.match_sequential(db)
    else:
        pycolmap.match_exhaustive(db)
    print("[02_sfm] match_%s done (%.1fs)" % (matcher, time.time() - t0))
    sparse_root = os.path.join(out, "sparse")
    os.makedirs(sparse_root, exist_ok=True)
    recs = pycolmap.incremental_mapping(db, images_dir, sparse_root)
    if not recs:
        raise RuntimeError("pycolmap incremental_mapping 未产生任何 reconstruction")
    best_id = max(recs.keys(), key=lambda k: recs[k].num_reg_images())
    best = recs[best_id]
    sparse_dir = os.path.join(sparse_root, "0")
    os.makedirs(sparse_dir, exist_ok=True)
    best.write(sparse_dir)
    try:
        best.write_text(os.path.join(out, "sparse_text"))
    except Exception as e:  # noqa: BLE001
        print("[02_sfm] write_text 失败（可忽略）:", e)
    summary = {"mode": "sfm", "images_dir": images_dir, "num_models": len(recs),
               "num_reg_images": int(best.num_reg_images()),
               "num_points3D": int(best.num_points3D()),
               "mean_reproj_err_px": float(best.compute_mean_reprojection_error()),
               "sparse_dir": sparse_dir, "matcher": matcher,
               "seconds": round(time.time() - t0, 2)}
    return _write_summary(out, summary)


def mode_dji(photos, out, metadata=None, refine=False):
    import subprocess
    cmd = [sys.executable, os.path.join(HERE, "dji_exif_to_colmap.py"), "--out", out]
    if photos:
        cmd += ["--photos", photos]
    if metadata:
        cmd += ["--metadata", metadata]
    if refine:
        cmd.append("--refine")
    print("[02_sfm] RUN " + " ".join(cmd))
    p = subprocess.run(cmd, text=True, encoding="utf-8", errors="replace",
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(p.stdout[-4000:])
    if p.returncode != 0:
        raise RuntimeError("dji_exif_to_colmap.py 失败 rc=%d" % p.returncode)
    pri_path = os.path.join(out, "dji_priors.json")
    pri = {}
    if os.path.isfile(pri_path):
        with open(pri_path, "r", encoding="utf-8") as f:
            pri = json.load(f)
    return _write_summary(out, {"mode": "dji", "photos": photos, "refine": bool(refine),
                                "n_frames": pri.get("n_frames"), "sparse_dir": pri.get("sparse_dir"),
                                "gt_check": pri.get("gt_check")})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="auto", choices=["auto", "known", "sfm", "dji"])
    ap.add_argument("--data", default=None, help="数据集根目录（known/auto）")
    ap.add_argument("--images", default=None, help="图像目录（sfm）")
    ap.add_argument("--photos", default=None, help="DJI 照片目录（dji）")
    ap.add_argument("--metadata", default=None, help="显式 metadata.json 路径")
    ap.add_argument("--image-root", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--matcher", default="exhaustive", choices=["exhaustive", "sequential"])
    ap.add_argument("--max-image-size", type=int, default=1600)
    ap.add_argument("--refine", action="store_true")
    args = ap.parse_args()

    mode = args.mode
    data = os.path.abspath(args.data) if args.data else None
    if mode == "auto":
        if data and os.path.isfile(os.path.join(data, "metadata.json")):
            mode = "known"
        elif data and (os.path.isfile(os.path.join(data, "sparse", "0", "cameras.bin"))
                       or os.path.isfile(os.path.join(data, "sparse", "0", "cameras.txt"))):
            print("[02_sfm] 检测到已有 COLMAP sparse，auto 模式跳过")
            return
        elif args.images or (data and os.path.isdir(os.path.join(data, "images"))):
            mode = "sfm"
        elif args.photos:
            mode = "dji"
        else:
            raise SystemExit("auto 模式无法识别数据，请显式指定 --mode")
    out = args.out or (os.path.join(data or args.images or args.photos, "colmap"))
    if mode == "known":
        if not data:
            raise SystemExit("--mode known 需要 --data")
        mode_known(data, args.metadata, out, image_root=args.image_root)
    elif mode == "sfm":
        images = args.images or (os.path.join(data, "images") if data else None)
        if not images:
            raise SystemExit("--mode sfm 需要 --images")
        mode_sfm(images, out, matcher=args.matcher, max_image_size=args.max_image_size)
    else:
        mode_dji(args.photos, out, metadata=args.metadata, refine=args.refine)


if __name__ == "__main__":
    main()
