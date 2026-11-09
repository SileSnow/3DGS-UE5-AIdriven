"""dji_exif_to_colmap.py -- 真实 DJI 照片 EXIF( GPS + 云台角) -> COLMAP 粗位姿先验。

定位: 这是"粗位姿先验 + COLMAP 精化"链路的第一半。GPS 误差 1-3 m、云台角有噪声，
      不能替代 COLMAP/SfM；只用于给 SfM 一个初始位姿（COLMAP 的 pose prior / 已知位姿三角化）。

输入（任选其一）:
  --metadata <json>   01_extract_frames.py 输出（frames 含 gps + gimbal_deg），或 CONVENTIONS 风格
                      （同时含 c2w 时可自动量化"先验误差"，见 --report-gt）
  --photos <dir>      直接扫描照片 EXIF/XMP（复用 01_extract_frames 解析）
  --json <json>       离线自测: {"width","height","frames":[{file,gps:{lat,lon,alt},gimbal_deg:{yaw,pitch,roll}}]}
输出:
  <out>/sparse/0/{cameras.txt,images.txt,points3D.txt}   COLMAP text 格式（可被 pycolmap / colmap 读取）
  <out>/dji_priors.json                                  先验摘要（世界系 ENU RH 米、origin、误差说明）
  --refine 时再用 pycolmap 做 feature/match + 已知位姿三角化（COLMAP 精化，得到稀疏点云）

用法:
  python pipeline/dji_exif_to_colmap.py --metadata data/dji/photos_index/metadata.json \
      --photos data/dji/photos --out data/dji/colmap_prior --refine
  # 自测（用合成 campus 数据的 GPS+云台角，等价于 DJI 风格 EXIF）:
  python pipeline/dji_exif_to_colmap.py --metadata data/sample/synthetic_campus_v1/metadata.json \
      --photos data/sample/synthetic_campus_v1/images --out data/sample/dji_prior_demo --report-gt
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from colmap_io import intrinsics_matrix, rotmat_to_qvec, write_colmap_text  # noqa: E402

EARTH_R = 6378137.0


# --------------------------------------------------------------------------- #
# 几何
# --------------------------------------------------------------------------- #
def enu_from_wgs84(lat, lon, alt, origin):
    lat0, lon0, alt0 = origin["lat"], origin["lon"], origin["alt"]
    east = math.radians(lon - lon0) * EARTH_R * math.cos(math.radians(lat0))
    north = math.radians(lat - lat0) * EARTH_R
    up = alt - alt0
    return np.array([east, north, up], np.float64)


def camera_pose_from_gimbal(gps, gimbal, origin):
    """DJI gimbal (yaw 顺时针自北, pitch 上正/下负, roll) + GPS -> (R_cw, t_cw, C_enu)。

    ENU 右手世界: x=east, y=north, z=up；COLMAP 相机: x 右, y 下, z 前。
    """
    yaw = math.radians(float(gimbal.get("yaw", 0.0)))
    pitch = math.radians(float(gimbal.get("pitch", 0.0)))
    roll = math.radians(float(gimbal.get("roll", 0.0)))
    # 相机前向（ENU, RH）
    fwd = np.array([math.sin(yaw) * math.cos(pitch),
                    math.cos(yaw) * math.cos(pitch),
                    math.sin(pitch)], np.float64)
    fwd /= np.linalg.norm(fwd)
    up_world = np.array([0.0, 0.0, 1.0])
    if abs(float(fwd @ up_world)) > 0.999:
        up_world = np.array([1.0, 0.0, 0.0])
    right = np.cross(fwd, up_world)
    right /= np.linalg.norm(right)
    up_cam = np.cross(right, fwd)
    # roll: 绕 fwd 旋转 right/up_cam
    c, s = math.cos(roll), math.sin(roll)
    right_r = c * right + s * up_cam
    up_r = -s * right + c * up_cam
    R_cw = np.stack([right_r, -up_r, fwd], axis=0)      # 行 = 相机轴在 ENU 中
    C = enu_from_wgs84(gps["lat"], gps["lon"], gps.get("alt", origin["alt"]), origin)
    t_cw = -R_cw @ C
    return R_cw, t_cw, C


def _orthonormal_error(R):
    return float(np.abs(R @ R.T - np.eye(3)).max())


# --------------------------------------------------------------------------- #
# 输入解析
# --------------------------------------------------------------------------- #
def load_frames_metadata(path):
    with open(path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    frames = []
    for fr in meta.get("frames", []):
        if not fr.get("gps") or not fr.get("gimbal_deg"):
            continue
        frames.append({"file": fr["file"], "gps": fr["gps"], "gimbal_deg": fr["gimbal_deg"],
                       "c2w": fr.get("c2w"), "timestamp": fr.get("timestamp")})
    return meta, frames


def load_frames_photos(photos_dir, metadata_path=None):
    """直接读照片 EXIF/XMP（复用 01_extract_frames 的解析函数）。"""
    sys.path.insert(0, HERE)
    import importlib.util
    spec = importlib.util.spec_from_file_location("extract01", os.path.join(HERE, "01_extract_frames.py"))
    m01 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m01)
    exts = (".jpg", ".jpeg", ".png", ".tif", ".tiff")
    names = sorted(n for n in os.listdir(photos_dir) if n.lower().endswith(exts))
    frames = []
    exif0 = {}
    for n in names:
        p = os.path.join(photos_dir, n)
        exif = m01.read_exif(p)
        xmp = m01.read_dji_xmp(p)
        if not exif0:
            exif0 = exif
        gps = xmp.get("gps") or exif.get("gps")
        gimbal = xmp.get("gimbal_deg")
        if gps and gimbal:
            frames.append({"file": n, "gps": {"lat": gps["lat"], "lon": gps["lon"], "alt": gps.get("alt", 0.0)},
                           "gimbal_deg": gimbal})
    meta = {"width": exif0.get("width"), "height": exif0.get("height"),
            "camera_model": exif0.get("camera_model"), "frames": frames}
    return meta, frames


# --------------------------------------------------------------------------- #
# 主
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metadata", default=None)
    ap.add_argument("--photos", default=None, help="照片目录（--metadata 缺省时从此读 EXIF/XMP）")
    ap.add_argument("--json", default=None, help="离线自测 JSON（DJI 风格 frames）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--origin-lat", type=float, default=None)
    ap.add_argument("--origin-lon", type=float, default=None)
    ap.add_argument("--origin-alt", type=float, default=None)
    ap.add_argument("--refine", action="store_true", help="用 pycolmap 做 feature/match + 已知位姿三角化（COLMAP 精化）")
    ap.add_argument("--report-gt", action="store_true", help="metadata 含 c2w 时量化先验误差（自测）")
    args = ap.parse_args()

    if args.json:
        with open(args.json, "r", encoding="utf-8") as f:
            meta = json.load(f)
        frames = [{"file": fr["file"], "gps": fr["gps"], "gimbal_deg": fr["gimbal_deg"],
                   "c2w": fr.get("c2w")} for fr in meta["frames"]]
        width = int(meta.get("width", 4000)); height = int(meta.get("height", 3000))
        fx = float(meta.get("fx", 0.667 * width)); fy = float(meta.get("fy", fx))
        cx = float(meta.get("cx", width / 2)); cy = float(meta.get("cy", height / 2))
    elif args.metadata:
        meta, frames = load_frames_metadata(args.metadata)
        width = int(meta.get("width") or 0); height = int(meta.get("height") or 0)
        fx = float(meta.get("fx") or 0); fy = float(meta.get("fy") or fx)
        cx = float(meta.get("cx") or width / 2); cy = float(meta.get("cy") or height / 2)
        if (not width or not height) and args.photos:
            import cv2
            n0 = sorted(os.listdir(args.photos))[0]
            im = cv2.imread(os.path.join(args.photos, n0))
            if im is not None:
                height, width = im.shape[:2]
    elif args.photos:
        meta, frames = load_frames_photos(args.photos)
        width = int(meta.get("width") or 4000); height = int(meta.get("height") or 3000)
        exif = {}
        fx = 0.0
        if meta.get("frames"):
            # 用第一帧 EXIF 焦距估计（无则按 0.667*width）
            pass
        fx = fy = 0.667 * width; cx, cy = width / 2.0, height / 2.0
    else:
        raise SystemExit("需要 --metadata / --photos / --json 之一")

    if not frames:
        raise SystemExit("没有可用帧（缺 gps 或 gimbal_deg）；请检查 EXIF/XMP 解析")
    if fx <= 0:
        fx = fy = 0.667 * width
    if fy <= 0:
        fy = fx
    if width <= 0 or height <= 0:
        width, height = int(round(4 * fx / 2.0)), int(round(3 * fx / 2.0))

    # origin 优先级: 显式参数 > metadata.origin_wgs84（CONVENTIONS 合成数据）> 首帧 GPS
    meta_origin = (meta.get("origin_wgs84") if isinstance(meta, dict) else None) or {}
    origin = {"lat": args.origin_lat if args.origin_lat is not None else meta_origin.get("lat", frames[0]["gps"]["lat"]),
              "lon": args.origin_lon if args.origin_lon is not None else meta_origin.get("lon", frames[0]["gps"]["lon"]),
              "alt": args.origin_alt if args.origin_alt is not None else meta_origin.get("alt", frames[0]["gps"].get("alt", 0.0))}
    K = intrinsics_matrix(fx, fy, cx, cy)
    out = os.path.abspath(args.out)
    sparse_dir = os.path.join(out, "sparse", "0")
    os.makedirs(sparse_dir, exist_ok=True)

    cf_frames = []
    priors = []
    for i, fr in enumerate(frames):
        R_cw, t_cw, C = camera_pose_from_gimbal(fr["gps"], fr["gimbal_deg"], origin)
        name = os.path.basename(fr["file"])
        cf_frames.append({"name": name, "K": K, "R_cw": R_cw, "t_cw": t_cw,
                          "width": width, "height": height,
                          "gps": fr["gps"], "gimbal_deg": fr["gimbal_deg"]})
        priors.append({"name": name, "C_enu_m": C.tolist(),
                       "gps": fr["gps"], "gimbal_deg": fr["gimbal_deg"],
                       "R_cw": R_cw.tolist(), "t_cw": t_cw.tolist(),
                       "orthonormal_err": _orthonormal_error(R_cw)})

    write_colmap_text(sparse_dir, cf_frames)
    max_orth = max(p["orthonormal_err"] for p in priors)

    # 先验误差量化（若 metadata 带 c2w：合成数据自测 / 真实数据可无）
    gt_report = None
    if args.report_gt:
        from colmap_io import ue_c2w_to_colmap
        # UE-RH 世界(x=north,y=-east,z=up) -> ENU(x=east,y=north,z=up) 的坐标变换矩阵
        A = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
        pos_err, ang_err = [], []
        for i, fr in enumerate(frames):
            if fr.get("c2w") is None:
                continue
            M = np.asarray(fr["c2w"], np.float64).reshape(4, 4)
            R_gt_rh, t_gt, C_gt_rh = ue_c2w_to_colmap(M)
            C_gt_enu = A @ (C_gt_rh / 100.0)     # cm -> m
            R_gt_enu = R_gt_rh @ A.T             # 行向量 = 相机轴；世界基变换作用在右侧
            C_pr = np.asarray(priors[i]["C_enu_m"], np.float64)
            R_pr = np.asarray(cf_frames[i]["R_cw"], np.float64)
            pos_err.append(float(np.linalg.norm(C_pr - C_gt_enu)))
            cosang = (np.trace(R_pr.T @ R_gt_enu) - 1.0) / 2.0
            ang_err.append(float(math.degrees(math.acos(max(-1.0, min(1.0, cosang))))))
        if pos_err:
            gt_report = {"n": len(pos_err), "pos_err_mean_m": float(np.mean(pos_err)),
                         "pos_err_max_m": float(np.max(pos_err)),
                         "rot_err_mean_deg": float(np.mean(ang_err)),
                         "rot_err_max_deg": float(np.max(ang_err))}

    summary = {
        "n_frames": len(frames), "width": width, "height": height,
        "intrinsics": {"fx": fx, "fy": fy, "cx": cx, "cy": cy},
        "origin_wgs84": origin, "world_frame": "ENU_RH_m (x=east,y=north,z=up)",
        "camera_convention": "OpenCV/COLMAP (x right, y down, z forward)",
        "sparse_dir": sparse_dir, "orthonormal_err_max": max_orth,
        "gps_noise_note": "GPS 水平 1-3 m（DJI Mini 系列典型值），云台角 ~0.1-0.5 deg；"
                          "该位姿仅作 COLMAP 粗先验，需 SfM/BA 精化",
        "gt_check": gt_report, "frames": priors,
    }
    with open(os.path.join(out, "dji_priors.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("[dji_prior] %d 帧 -> %s (orthonormal_err_max=%.2e)" % (len(frames), sparse_dir, max_orth))
    if gt_report:
        print("[dji_prior] 合成数据自测(先验 vs GT): 位置误差 mean %.2fm max %.2fm, 姿态误差 mean %.2fdeg max %.2fdeg"
              % (gt_report["pos_err_mean_m"], gt_report["pos_err_max_m"],
                 gt_report["rot_err_mean_deg"], gt_report["rot_err_max_deg"]))

    # ---------------- COLMAP 精化（已知位姿三角化） ----------------
    if args.refine:
        if not args.photos:
            print("[dji_prior] --refine 需要 --photos 提供图像目录，跳过")
        else:
            try:
                import pycolmap
                ref_dir = os.path.join(out, "refined")
                os.makedirs(ref_dir, exist_ok=True)
                db = os.path.join(ref_dir, "database.db")
                if os.path.exists(db):
                    os.remove(db)
                pycolmap.import_images(db, os.path.abspath(args.photos),
                                       pycolmap.CameraMode.SINGLE)
                pycolmap.extract_features(db, os.path.abspath(args.photos))
                pycolmap.match_exhaustive(db)
                rec = pycolmap.Reconstruction(sparse_dir)
                out_sparse = os.path.join(ref_dir, "sparse", "0")
                os.makedirs(out_sparse, exist_ok=True)
                rec2 = pycolmap.triangulate_points(rec, db, os.path.abspath(args.photos), out_sparse)
                stats = {"num_images": rec2.num_reg_images(), "num_points3D": rec2.num_points3D(),
                         "mean_reproj_err_px": float(rec2.compute_mean_reprojection_error())}
                with open(os.path.join(ref_dir, "refine_stats.json"), "w", encoding="utf-8") as f:
                    json.dump(stats, f, ensure_ascii=False, indent=2)
                print("[dji_prior] COLMAP 精化(已知位姿三角化): " + json.dumps(stats, ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                print("[dji_prior] COLMAP 精化失败（记录原因）: %s: %s" % (type(e).__name__, e))
    print("[dji_prior] 写出 %s/dji_priors.json" % out)


if __name__ == "__main__":
    main()
