"""validate_dataset.py -- 数据集/位姿自检（在训练前快速暴露 c2w/内参/元数据 bug）。

检查项:
  1. c2w 旋转刚性: |R R^T - I|max < 1e-6 且 det(R)≈+1（防"非正交 c2w" bug 再次混入）
  2. 内参合理性: fx,fy>0；cx,cy 在图像范围内；图像尺寸与 metadata 一致
  3. GPS 一致性（metadata 同时含 c2w 与 gps/origin_wgs84 时）: c2w 中心换算的 GPS 与 metadata gps 的差
  4. 相机朝向一致性: 各相机前向与场景质心方向夹角 < 90 度
  5. 极线几何自检（最强校验）: 5 帧两两 SIFT 匹配，用已知位姿+内参算 F，Sampson 距离中位数 < 2 px
     （把"3D 点投影到像素"的一致性直接量化；位姿/内参错时该误差会显著变大）

用法:
  python pipeline/validate_dataset.py --data data/synthetic/capture --n-frames 5
输出: <data>/validate_report.json + 控制台摘要；全部检查通过时退出码 0，否则 1。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from colmap_io import frames_from_metadata, load_metadata  # noqa: E402


def rotmat_to_rpy(R):
    """仅用于打印：相机前向（R_cw^T e3）的 yaw/pitch（度）。"""
    fwd = R.T @ np.array([0.0, 0.0, 1.0])
    yaw = math.degrees(math.atan2(fwd[1], fwd[0]))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, fwd[2]))))
    return yaw, pitch


def essential_from_poses(R1, t1, R2, t2):
    R_rel = R2 @ R1.T
    t_rel = t2 - R_rel @ t1
    tx = np.array([[0.0, -t_rel[2], t_rel[1]],
                   [t_rel[2], 0.0, -t_rel[0]],
                   [-t_rel[1], t_rel[0], 0.0]])
    return tx @ R_rel, R_rel, t_rel


def fundamental_from_poses(R1, t1, K1, R2, t2, K2):
    E, _, _ = essential_from_poses(R1, t1, R2, t2)
    F = np.linalg.inv(K2).T @ E @ np.linalg.inv(K1)
    n = np.abs(F).max()
    return F / n if n > 0 else F


def sampson_distance(F, pts1, pts2):
    p1 = np.hstack([pts1, np.ones((len(pts1), 1))])
    p2 = np.hstack([pts2, np.ones((len(pts2), 1))])
    Fx1 = p1 @ F.T
    Ftx2 = p2 @ F
    num = np.sum(p2 * Fx1, axis=1) ** 2
    den = Fx1[:, 0] ** 2 + Fx1[:, 1] ** 2 + Ftx2[:, 0] ** 2 + Ftx2[:, 1] ** 2
    return np.sqrt(num / np.maximum(den, 1e-12))


def sift_match(img1, img2, nfeatures=3000, ratio=0.78):
    g1 = cv2.cvtColor(img1, cv2.COLOR_RGB2GRAY)
    g2 = cv2.cvtColor(img2, cv2.COLOR_RGB2GRAY)
    sift = cv2.SIFT_create(nfeatures=nfeatures)
    k1, d1 = sift.detectAndCompute(g1, None)
    k2, d2 = sift.detectAndCompute(g2, None)
    if d1 is None or d2 is None or len(k1) < 20 or len(k2) < 20:
        return None, None
    bf = cv2.BFMatcher(cv2.NORM_L2)
    matches = bf.knnMatch(d1, d2, k=2)
    good = [m for m, n in matches if m.distance < ratio * n.distance]
    if len(good) < 15:
        return None, None
    pts1 = np.float64([k1[m.queryIdx].pt for m in good])
    pts2 = np.float64([k2[m.trainIdx].pt for m in good])
    return pts1, pts2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--metadata", default=None)
    ap.add_argument("--image-root", default=None)
    ap.add_argument("--n-frames", type=int, default=5)
    ap.add_argument("--rigid-tol", type=float, default=1e-6)
    ap.add_argument("--epipolar-median-threshold", type=float, default=2.0)
    ap.add_argument("--gps-threshold-m", type=float, default=5.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    data = os.path.abspath(args.data)
    meta_path = args.metadata or os.path.join(data, "metadata.json")
    img_root = args.image_root or data
    meta = load_metadata(meta_path)
    frames = frames_from_metadata(meta, image_root=img_root, check_images=False)
    W, H = int(meta["width"]), int(meta["height"])

    rng = np.random.default_rng(0)
    if len(frames) > args.n_frames:
        idx = np.linspace(0, len(frames) - 1, args.n_frames).round().astype(int)
        idx = sorted(set(int(i) for i in idx))
    else:
        idx = list(range(len(frames)))
    sel = [frames[i] for i in idx]
    print("[validate] %s: %d 帧（抽样 %d 帧: %s）" % (meta.get("dataset"), len(frames), len(sel), idx))

    # 1) c2w 刚性
    rigid = []
    for fr in frames:
        R = np.asarray(fr["c2w_ue"], np.float64)[:3, :3]
        rigid.append({"name": fr["name"],
                      "orth_err": float(np.abs(R @ R.T - np.eye(3)).max()),
                      "det": float(np.linalg.det(R))})
    orth_max = max(r["orth_err"] for r in rigid)
    det_min = min(r["det"] for r in rigid)
    det_max = max(r["det"] for r in rigid)

    # 2) 内参 + 图像尺寸
    K = sel[0]["K"]
    intr_ok = K[0, 0] > 0 and K[1, 1] > 0 and 0 < K[0, 2] < W and 0 < K[1, 2] < H
    size_ok, size_bad = True, []
    for fr in sel:
        img = cv2.imread(fr["image_path"], cv2.IMREAD_COLOR)
        if img is None:
            size_ok = False
            size_bad.append(fr["name"] + " (无法读取)")
            continue
        h, w = img.shape[:2]
        if (w, h) != (W, H):
            size_ok = False
            size_bad.append("%s: %dx%d != %dx%d" % (fr["name"], w, h, W, H))

    # 3) GPS 一致性
    gps_err = None
    origin = meta.get("origin_wgs84") or {}
    if origin and all(fr.get("gps") for fr in frames):
        errs = []
        for fr in frames:
            C = np.asarray(fr["c2w_ue"], np.float64)[:3, 3]
            north_m, east_m = C[0] / 100.0, C[1] / 100.0
            lat = origin["lat"] + north_m / 111320.0
            lon = origin["lon"] + east_m / (111320.0 * math.cos(math.radians(origin["lat"])))
            g = fr["gps"]
            dlat = (g["lat"] - lat) * 111320.0
            dlon = (g["lon"] - lon) * 111320.0 * math.cos(math.radians(origin["lat"]))
            dalt = (g.get("alt", 0.0) - (origin["alt"] + C[2] / 100.0))
            errs.append(math.sqrt(dlat * dlat + dlon * dlon + dalt * dalt))
        gps_err = {"mean_m": float(np.mean(errs)), "max_m": float(np.max(errs))}

    # 4) 相机朝向一致性
    centers = np.stack([np.asarray(fr["c2w_ue"], np.float64)[:3, 3] for fr in frames])
    centroid = centers.mean(axis=0)
    angles = []
    for fr in frames:
        M = np.asarray(fr["c2w_ue"], np.float64)
        fwd = M[:3, 0]
        v = centroid - M[:3, 3]
        nv = np.linalg.norm(v)
        if nv > 1e-6:
            angles.append(math.degrees(math.acos(max(-1.0, min(1.0, float(fwd @ (v / nv)))))))

    # 5) 极线几何（SIFT + 已知位姿 F + Sampson）
    epi = []
    for a, b in zip(sel[:-1], sel[1:]):
        img1 = cv2.imread(a["image_path"], cv2.IMREAD_COLOR)
        img2 = cv2.imread(b["image_path"], cv2.IMREAD_COLOR)
        if img1 is None or img2 is None:
            epi.append({"pair": [a["name"], b["name"]], "n_matches": 0, "median_px": None,
                        "note": "图像读取失败"})
            continue
        img1 = cv2.cvtColor(img1, cv2.COLOR_BGR2RGB)
        img2 = cv2.cvtColor(img2, cv2.COLOR_BGR2RGB)
        pts1, pts2 = sift_match(img1, img2)
        if pts1 is None:
            epi.append({"pair": [a["name"], b["name"]], "n_matches": 0, "median_px": None,
                        "note": "匹配不足"})
            continue
        # SIFT 坐标基于原图；若元数据分辨率与图像一致则 K 直接可用
        F = fundamental_from_poses(a["R_cw"], a["t_cw"], a["K"], b["R_cw"], b["t_cw"], b["K"])
        d = sampson_distance(F, pts1, pts2)
        epi.append({"pair": [a["name"], b["name"]], "n_matches": int(len(d)),
                    "median_px": float(np.median(d)), "p90_px": float(np.percentile(d, 90)),
                    "frac_lt_2px": float((d < 2.0).mean())})

    valid_epi = [e for e in epi if e.get("median_px") is not None]
    epi_med = float(np.median([e["median_px"] for e in valid_epi])) if valid_epi else None
    epi_frac2 = float(np.mean([e["frac_lt_2px"] for e in valid_epi])) if valid_epi else None

    checks = {
        "rigid": {"max_orth_err": orth_max, "det_min": det_min, "det_max": det_max,
                  "pass": bool(orth_max < args.rigid_tol and abs(det_min - 1) < 1e-3 and abs(det_max - 1) < 1e-3)},
        "intrinsics": {"K": K.tolist(), "pass": bool(intr_ok)},
        "image_size": {"pass": bool(size_ok), "bad": size_bad[:5]},
        "gps": {"err": gps_err,
                "pass": bool(gps_err is None or gps_err["max_m"] <= args.gps_threshold_m)},
        "orientation": {"mean_angle_deg": float(np.mean(angles)) if angles else None,
                        "max_angle_deg": float(np.max(angles)) if angles else None,
                        "pass": bool(not angles or np.mean(angles) < 90.0)},
        "epipolar": {"pairs": epi, "median_px": epi_med, "frac_lt_2px": epi_frac2,
                     "pass": bool(epi_med is not None and epi_med < args.epipolar_median_threshold)},
    }
    all_pass = all(c["pass"] for c in checks.values() if "pass" in c)
    report = {"data": data, "metadata": meta_path, "n_frames": len(frames),
              "sampled_frames": [f["name"] for f in sel],
              "width": W, "height": H, "checks": checks, "all_pass": bool(all_pass)}
    out = args.out or os.path.join(data, "validate_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("[validate] 1) c2w 刚性: |RR^T-I|max=%.3e, det=[%.6f, %.6f] -> %s" % (
        orth_max, det_min, det_max, "PASS" if checks["rigid"]["pass"] else "FAIL"))
    print("[validate] 2) 内参: K=%s -> %s" % (np.round(K, 1).tolist(), "PASS" if intr_ok else "FAIL"))
    print("[validate] 3) 图像尺寸: %s %s" % ("PASS" if size_ok else "FAIL", size_bad[:2]))
    if gps_err:
        print("[validate] 4) GPS 一致性: mean %.3f m / max %.3f m -> %s" % (
            gps_err["mean_m"], gps_err["max_m"], "PASS" if checks["gps"]["pass"] else "FAIL"))
    print("[validate] 5) 朝向: 平均 %.1f 度 / 最大 %.1f 度" % (
        checks["orientation"]["mean_angle_deg"] or 0, checks["orientation"]["max_angle_deg"] or 0))
    if epi_med is not None:
        print("[validate] 6) 极线几何(Sampson): 中位 %.3f px, <2px 占比 %.2f -> %s" % (
            epi_med, epi_frac2, "PASS" if checks["epipolar"]["pass"] else "FAIL"))
        for e in epi:
            if e.get("median_px") is not None:
                print("    %s <-> %s: matches=%d median=%.3f px p90=%.3f" % (
                    os.path.basename(e["pair"][0]), os.path.basename(e["pair"][1]),
                    e["n_matches"], e["median_px"], e["p90_px"]))
    print("[validate] ALL:", "PASS" if all_pass else "FAIL", "-> " + out)
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
