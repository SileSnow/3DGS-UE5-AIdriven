"""01_extract_frames.py -- 视频抽帧 / 照片目录索引 + 清晰度筛选 + EXIF(DJI) 元数据 -> metadata.json

用法:
  # 视频抽帧（imageio-ffmpeg 提供 ffmpeg 可执行文件）
  python pipeline/01_extract_frames.py --video DJI_0001.MP4 --out data/dji/video1 --fps 2 --sharpness-rel 0.4
  # 照片目录索引（真实 DJI 样张）
  python pipeline/01_extract_frames.py --photos data/dji/photos --out data/dji/photos_index
  # 只筛选不复制（照片模式默认不复制原图，metadata 记录相对路径）

输出:
  <out>/images/0001.png ...   视频模式：筛选后的帧转 PNG；照片模式：不复制（除非 --copy）
  <out>/metadata.json         frames: file/timestamp/sharpness/gps/gimbal_deg/exif；无 c2w（无位姿）
                             后续 dji_exif_to_colmap.py / 02_sfm.py --mode dji 由此构造先验位姿
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys

import cv2
import numpy as np

DJI_XMP_KEYS = {
    "GPSLatitude": "gps_lat", "GPSLongitude": "gps_lon", "AbsoluteAltitude": "abs_alt",
    "RelativeAltitude": "rel_alt", "GimbalYawDegree": "gimbal_yaw",
    "GimbalPitchDegree": "gimbal_pitch", "GimbalRollDegree": "gimbal_roll",
    "FlightYawDegree": "flight_yaw", "FlightPitchDegree": "flight_pitch",
    "FlightRollDegree": "flight_roll",
}
_XMP_PATTERNS = {k: re.compile((rb"(?:drone-dji:|Camera:|DJI:)" + k.encode() + rb'="([^"]+)"'))
                 for k in DJI_XMP_KEYS}


# --------------------------------------------------------------------------- #
# EXIF / XMP
# --------------------------------------------------------------------------- #
def _ratio_to_float(x):
    try:
        if hasattr(x, "num") and hasattr(x, "den"):
            return float(x.num) / float(x.den) if x.den else 0.0
        if isinstance(x, (list, tuple)):
            if not x:
                return 0.0
            return float(x[0])
        return float(x)
    except Exception:  # noqa: BLE001
        return 0.0


def _gps_dms_to_deg(values, ref):
    d = [_ratio_to_float(v) for v in values]
    deg = d[0] + (d[1] / 60.0 if len(d) > 1 else 0.0) + (d[2] / 3600.0 if len(d) > 2 else 0.0)
    if str(ref).upper().startswith("S") or str(ref).upper().startswith("W"):
        deg = -deg
    return deg


def read_dji_xmp(path):
    """直接扫描文件字节提取 DJI XMP 字段（exifread 不解析 XMP；DJI 的云台角只在 XMP 里）。"""
    try:
        with open(path, "rb") as f:
            data = f.read(4 * 1024 * 1024)
    except OSError:
        return {}
    out = {}
    for key, pat in _XMP_PATTERNS.items():
        m = pat.search(data)
        if m:
            try:
                out[DJI_XMP_KEYS[key]] = float(m.group(1))
            except ValueError:
                pass
    if "gps_lat" in out and "gps_lon" in out:
        out["gps"] = {"lat": out["gps_lat"], "lon": out["gps_lon"],
                      "alt": out.get("abs_alt", 0.0) or out.get("rel_alt", 0.0)}
    if "gimbal_yaw" in out:
        out["gimbal_deg"] = {"yaw": out.get("gimbal_yaw", 0.0),
                             "pitch": out.get("gimbal_pitch", 0.0),
                             "roll": out.get("gimbal_roll", 0.0)}
    return out


def read_exif(path):
    """exifread 读标准 EXIF：机型/焦距/等效焦距/尺寸/GPS。"""
    import exifread
    info = {}
    try:
        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    def tag(name):
        t = tags.get(name)
        return t.values if t is not None else None
    make = tag("Image Make"); model = tag("Image Model")
    if make or model:
        info["camera_model"] = " ".join(str(x) for x in [make, model] if x).strip()
    fl = tag("EXIF FocalLength")
    if fl is not None:
        info["focal_mm"] = _ratio_to_float(fl)
    f35 = tag("EXIF FocalLengthIn35mmFilm")
    if f35 is not None:
        info["focal_35mm"] = _ratio_to_float(f35)
    w = tag("EXIF ExifImageWidth") or tag("Image ImageWidth")
    h = tag("EXIF ExifImageLength") or tag("Image ImageLength")
    if w is not None and h is not None:
        try:
            info["width"], info["height"] = int(_ratio_to_float(w)), int(_ratio_to_float(h))
        except Exception:  # noqa: BLE001
            pass
    lat, lat_ref = tag("GPS GPSLatitude"), tag("GPS GPSLatitudeRef")
    lon, lon_ref = tag("GPS GPSLongitude"), tag("GPS GPSLongitudeRef")
    if lat is not None and lon is not None:
        try:
            info["gps"] = {"lat": _gps_dms_to_deg(lat, lat_ref), "lon": _gps_dms_to_deg(lon, lon_ref)}
            alt = tag("GPS GPSAltitude")
            alt_ref = tag("GPS GPSAltitudeRef")
            if alt is not None:
                a = _ratio_to_float(alt)
                if alt_ref is not None and int(_ratio_to_float(alt_ref)) == 1:
                    a = -a
                info["gps"]["alt"] = a
        except Exception:  # noqa: BLE001
            pass
    return info


def estimate_intrinsics(exif, width, height):
    """由 EXIF 焦距估计针孔内参（无标定）。DJI 常用 35mm 等效焦距。"""
    fx = fy = None
    if exif.get("focal_35mm"):
        f = exif["focal_35mm"] / 36.0 * width
        fx = fy = f
    elif exif.get("focal_mm"):
        # 无传感器宽度时按 DJI Mini 1/1.3" (~9.6mm 宽) 估计
        f = exif["focal_mm"] / 9.6 * width
        fx = fy = f
    if fx is None:
        fx = fy = 0.67 * width
    return {"fx": fx, "fy": fy, "cx": width / 2.0, "cy": height / 2.0}


# --------------------------------------------------------------------------- #
# 清晰度
# --------------------------------------------------------------------------- #
def sharpness(path):
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    return float(cv2.Laplacian(img, cv2.CV_64F).var())


# --------------------------------------------------------------------------- #
# 视频抽帧
# --------------------------------------------------------------------------- #
def extract_video_frames(video, work_dir, fps=None, every_n=None, max_frames=0):
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    os.makedirs(work_dir, exist_ok=True)
    pattern = os.path.join(work_dir, "raw_%06d.png")
    vf = []
    if fps:
        vf = ["-vf", "fps=%g" % fps]
    elif every_n:
        vf = ["-vf", "select=not(mod(n\\,%d))" % int(every_n), "-vsync", "vfr"]
    cmd = [ffmpeg, "-y", "-i", video] + vf + ["-qscale:v", "2", pattern]
    print("[extract] " + " ".join(cmd))
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError("ffmpeg 抽帧失败: " + (p.stdout or "")[-2000:])
    frames = sorted([f for f in os.listdir(work_dir) if f.startswith("raw_")])
    if max_frames and len(frames) > max_frames:
        idx = np.linspace(0, len(frames) - 1, max_frames).round().astype(int)
        frames = [frames[i] for i in sorted(set(int(i) for i in idx))]
    return ffmpeg, frames, work_dir


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default=None)
    ap.add_argument("--photos", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fps", type=float, default=2.0, help="视频抽帧帧率（默认 2 fps）")
    ap.add_argument("--every-n", type=int, default=0, help="或每 N 帧取一帧（与 --fps 二选一）")
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--sharpness-rel", type=float, default=0.0,
                    help="保留 Laplacian 方差 >= rel*median 的帧（0=全保留；航拍建议 0.3-0.6）")
    ap.add_argument("--sharpness-abs", type=float, default=0.0, help="绝对阈值（方差），与 rel 取 max")
    ap.add_argument("--copy", action="store_true", help="照片模式复制原图到 out/images/")
    args = ap.parse_args()

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    frames_out = []

    if args.video:
        work = os.path.join(out, "_raw")
        ffmpeg, raw_names, work = extract_video_frames(
            args.video, work, fps=(None if args.every_n else args.fps),
            every_n=args.every_n, max_frames=args.max_frames)
        metas = []
        for i, name in enumerate(raw_names):
            p = os.path.join(work, name)
            metas.append({"src": p, "sharpness": sharpness(p), "timestamp": i / float(args.fps or 1.0)})
        sharp = np.array([m["sharpness"] for m in metas], np.float64)
        thr = max(args.sharpness_abs, args.sharpness_rel * float(np.median(sharp)))
        keep = [i for i, m in enumerate(metas) if m["sharpness"] >= thr]
        if not keep:
            keep = list(range(len(metas)))
        img_dir = os.path.join(out, "images")
        os.makedirs(img_dir, exist_ok=True)
        xmp_info = read_dji_xmp(args.video)
        exif_info = {}
        for k, i in enumerate(keep, start=1):
            src = metas[i]["src"]
            dst = os.path.join(img_dir, "%04d.png" % k)
            if os.path.exists(dst):
                os.remove(dst)
            shutil.copy2(src, dst)
            frames_out.append({"file": "images/%04d.png" % k, "timestamp": metas[i]["timestamp"],
                               "sharpness": round(metas[i]["sharpness"], 3), "source": os.path.basename(src)})
        shutil.rmtree(work, ignore_errors=True)
        width = height = 0
        if frames_out:
            im = cv2.imread(os.path.join(out, frames_out[0]["file"]))
            if im is not None:
                height, width = im.shape[:2]
        meta = {"dataset": "video_extract_" + os.path.splitext(os.path.basename(args.video))[0],
                "source_video": os.path.abspath(args.video), "ffmpeg": ffmpeg,
                "width": width, "height": height, "frames_total": len(raw_names),
                "frames_kept": len(frames_out), "sharpness_threshold": round(float(thr), 3),
                "coord_system": "unknown_no_pose",
                "frames": frames_out}
        print("[extract] 视频 %d 帧 -> 保留 %d 帧 (threshold=%.1f)" % (
            len(raw_names), len(frames_out), thr))

    elif args.photos:
        photos = os.path.abspath(args.photos)
        exts = (".jpg", ".jpeg", ".png", ".dng", ".tif", ".tiff")
        names = sorted(n for n in os.listdir(photos) if n.lower().endswith(exts))
        if not names:
            raise SystemExit("照片目录为空: %s" % photos)
        img_dir = os.path.join(out, "images") if args.copy else None
        if img_dir:
            os.makedirs(img_dir, exist_ok=True)
        sharp = []
        for n in names:
            sharp.append(sharpness(os.path.join(photos, n)))
        sharp = np.array(sharp, np.float64)
        thr = max(args.sharpness_abs, args.sharpness_rel * float(np.median(sharp)))
        keep = [i for i, s in enumerate(sharp) if s >= thr] or list(range(len(names)))
        if args.max_frames and len(keep) > args.max_frames:
            keep = keep[:: max(1, len(keep) // args.max_frames)][: args.max_frames]
        first_exif = {}
        for k, i in enumerate(keep, start=1):
            src = os.path.join(photos, names[i])
            exif = read_exif(src)
            xmp = read_dji_xmp(src)
            if not first_exif:
                first_exif = exif
            if args.copy:
                dst = os.path.join(img_dir, "%04d%s" % (k, os.path.splitext(names[i])[1].lower()))
                shutil.copy2(src, dst)
                rel = "images/" + os.path.basename(dst)
            else:
                rel = os.path.relpath(src, out).replace("\\", "/")
            gps = xmp.get("gps") or exif.get("gps")
            gimbal = xmp.get("gimbal_deg")
            frames_out.append({"file": rel, "timestamp": float(k - 1),
                               "sharpness": round(float(sharp[i]), 3),
                               "gps": gps, "gimbal_deg": gimbal,
                               "exif": {kk: vv for kk, vv in exif.items() if kk != "gps"}})
        width = first_exif.get("width") or 0
        height = first_exif.get("height") or 0
        if frames_out:
            im = cv2.imread(os.path.join(photos, names[keep[0]]))
            if im is not None:
                height, width = im.shape[:2]
        K = estimate_intrinsics(first_exif, width or 1, height or 1)
        meta = {"dataset": "photos_" + os.path.basename(photos),
                "source_dir": photos, "camera_model": first_exif.get("camera_model"),
                "width": width, "height": height,
                "fx": K["fx"], "fy": K["fy"], "cx": K["cx"], "cy": K["cy"],
                "coord_system": "unknown_no_pose",
                "frames_total": len(names), "frames_kept": len(frames_out),
                "sharpness_threshold": round(float(thr), 3), "frames": frames_out}
        print("[extract] 照片 %d 张 -> 保留 %d 张 (threshold=%.1f), 机型=%s" % (
            len(names), len(frames_out), thr, first_exif.get("camera_model")))
    else:
        raise SystemExit("需要 --video 或 --photos")

    with open(os.path.join(out, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print("[extract] 写出 %s/metadata.json" % out)
    print(json.dumps({k: meta[k] for k in ["dataset", "width", "height", "frames_total", "frames_kept"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
