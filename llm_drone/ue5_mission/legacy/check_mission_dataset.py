#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_mission_dataset.py -- offline contract check for data/synthetic/mission.

Pure standard library + Pillow (system Python, no UE needed).  Verifies:
  * metadata.json exists / parses and matches the CONVENTIONS schema keys
  * every frame file exists and is a valid 1600x1200 PNG
  * c2w is a proper rigid transform (orthonormal rotation, det +1, bottom row)
  * simulated GPS round-trips from the c2w translation (UE -> WGS84)
  * image exposure is sane: not all-black, not blown out (mean/p99 on a thumbnail)
  * scene coverage: camera positions inside a plausible area, gimbal pitch negative
Writes <data>/validate_report.json and exits 0/1.

Usage:
    python ./llm_drone/ue5_mission/check_mission_dataset.py
    python ./llm_drone/ue5_mission/check_mission_dataset.py --data ./data/synthetic/mission
"""

import argparse
import json
import math
import os
import struct
import sys

try:
    from PIL import Image
except Exception:  # pragma: no cover - Pillow is expected but optional
    Image = None

M_PER_DEG_LAT = 111320.0
ORIGIN_WGS84 = {"lat": 39.9042, "lon": 116.4074, "alt": 43.0}
REQUIRED_TOP_KEYS = ("dataset", "camera_model", "width", "height", "fx", "fy", "cx", "cy",
                     "coord_system", "origin_wgs84", "frames")
REQUIRED_FRAME_KEYS = ("file", "c2w", "gps", "gimbal_deg", "timestamp")


def png_size(path):
    """Read width/height from a PNG header without decoding the image."""
    with open(path, "rb") as handle:
        head = handle.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    width, height = struct.unpack(">II", head[16:24])
    return width, height


def ue_to_wgs84(x_cm, y_cm, z_cm, origin):
    east_m = float(x_cm) / 100.0
    north_m = -float(y_cm) / 100.0
    up_m = float(z_cm) / 100.0
    lat = origin["lat"] + north_m / M_PER_DEG_LAT
    lon = origin["lon"] + east_m / (M_PER_DEG_LAT * math.cos(math.radians(origin["lat"])))
    return {"lat": lat, "lon": lon, "alt": origin["alt"] + up_m}


def rotation_error(c2w):
    """Max |R^T R - I| plus |det(R) - 1|; R columns = camera axes in UE world."""
    m = [float(v) for v in c2w]
    cols = [[m[0], m[4], m[8]], [m[1], m[5], m[9]], [m[2], m[6], m[10]]]
    worst = 0.0
    for i in range(3):
        for j in range(3):
            dot = sum(cols[i][k] * cols[j][k] for k in range(3))
            target = 1.0 if i == j else 0.0
            worst = max(worst, abs(dot - target))
    det = (cols[0][0] * (cols[1][1] * cols[2][2] - cols[1][2] * cols[2][1])
           - cols[0][1] * (cols[1][0] * cols[2][2] - cols[1][2] * cols[2][0])
           + cols[0][2] * (cols[1][0] * cols[2][1] - cols[1][1] * cols[2][0]))
    worst = max(worst, abs(det - 1.0))
    bottom = max(abs(m[12]), abs(m[13]), abs(m[14]), abs(m[15] - 1.0))
    return worst, bottom


def image_stats(path):
    """Thumbnail luminance histogram stats: mean / min / max / p99 (no getdata deprecation)."""
    if Image is None:
        return None
    with Image.open(path) as img:
        gray = img.convert("RGB")
        gray.thumbnail((200, 150))
        gray = gray.convert("L")
        hist = gray.histogram()
    total = sum(hist)
    if total <= 0:
        return None
    weighted = sum(index * count for index, count in enumerate(hist))
    accumulate = 0
    p99_value = 255
    for index, count in enumerate(hist):
        accumulate += count
        if accumulate >= total * 0.99:
            p99_value = index
            break
    low = next(index for index, count in enumerate(hist) if count)
    high = next(index for index in range(255, -1, -1) if hist[index])
    return {
        "mean": round(weighted / float(total) / 255.0, 4),
        "min": round(low / 255.0, 4),
        "max": round(high / 255.0, 4),
        "p99": round(p99_value / 255.0, 4),
    }


def check_metadata_dir(data_dir, report, label, metadata_name="metadata.json"):
    meta_path = os.path.join(data_dir, metadata_name)
    if not os.path.isfile(meta_path):
        report["errors"].append("%s: missing %s" % (label, metadata_name))
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as handle:
            meta = json.load(handle)
    except Exception as exc:
        report["errors"].append("%s: metadata.json is not valid JSON: %s" % (label, exc))
        return None
    missing = [key for key in REQUIRED_TOP_KEYS if key not in meta]
    if missing:
        report["errors"].append("%s: metadata.json missing keys %s" % (label, missing))
    if meta.get("coord_system") != "UE_LHS_Zup_cm":
        report["errors"].append("%s: unexpected coord_system %r"
                                % (label, meta.get("coord_system")))
    width = int(meta.get("width", 0))
    height = int(meta.get("height", 0))
    origin = meta.get("origin_wgs84") or dict(ORIGIN_WGS84)
    frames = meta.get("frames") or []
    report.setdefault("sets", {})[label] = {
        "metadata": meta_path,
        "frames": len(frames),
        "width": width,
        "height": height,
        "fx": meta.get("fx"),
        "fy": meta.get("fy"),
        "mission": (meta.get("mission") or {}).get("mission_id"),
    }
    if not frames:
        report["errors"].append("%s: no frames in metadata" % label)
        return meta

    files_seen = set()
    max_rot_err = 0.0
    max_bottom_err = 0.0
    max_gps_err = 0.0
    brightness = []
    bad_images = []
    for index, frame in enumerate(frames):
        tag = "%s[%d]" % (label, index)
        frame_missing = [key for key in REQUIRED_FRAME_KEYS if key not in frame]
        if frame_missing:
            report["errors"].append("%s: frame missing keys %s" % (tag, frame_missing))
            continue
        rel = str(frame["file"]).replace("\\", "/")
        if rel in files_seen:
            report["errors"].append("%s: duplicate file %s" % (tag, rel))
        files_seen.add(rel)
        path = os.path.join(data_dir, rel)
        if not os.path.isfile(path):
            report["errors"].append("%s: missing image %s" % (tag, path))
            continue
        size = os.path.getsize(path)
        if size < 1024:
            report["errors"].append("%s: image too small (%d B) %s" % (tag, size, path))
            continue
        try:
            w, h = png_size(path)
        except Exception as exc:
            report["errors"].append("%s: bad PNG %s (%s)" % (tag, path, exc))
            continue
        if (w, h) != (width, height):
            report["errors"].append("%s: PNG %dx%d != metadata %dx%d"
                                    % (tag, w, h, width, height))
        c2w = frame["c2w"]
        if not isinstance(c2w, list) or len(c2w) != 16:
            report["errors"].append("%s: c2w is not 16 floats" % tag)
            continue
        rot_err, bottom_err = rotation_error(c2w)
        max_rot_err = max(max_rot_err, rot_err)
        max_bottom_err = max(max_bottom_err, bottom_err)
        gps = frame["gps"]
        expected = ue_to_wgs84(c2w[3], c2w[7], c2w[11], origin)
        gps_err = max(abs(gps["lat"] - expected["lat"]),
                      abs(gps["lon"] - expected["lon"]),
                      abs(gps["alt"] - expected["alt"]) / 1e5)
        max_gps_err = max(max_gps_err, gps_err)
        pitch = frame.get("gimbal_deg", {}).get("pitch")
        if pitch is not None and float(pitch) > 1.0:
            report["errors"].append("%s: gimbal pitch %.1f looks up-facing" % (tag, float(pitch)))
        stats = image_stats(path)
        if stats is not None:
            brightness.append(stats)
            if stats["mean"] < 0.05:
                bad_images.append({"file": rel, "issue": "all-black", "stats": stats})
            elif stats["mean"] > 0.95 or stats["p99"] > 0.999:
                bad_images.append({"file": rel, "issue": "over-exposed", "stats": stats})
    for bad in bad_images:
        report["errors"].append("%s: suspicious exposure %s" % (label, bad))
    report["sets"][label].update({
        "png_count": len(files_seen),
        "max_rotation_error": round(max_rot_err, 9),
        "max_bottom_row_error": round(max_bottom_err, 9),
        "max_gps_roundtrip_error": round(max_gps_err, 12),
        "image_stats": {
            "mean_of_means": round(sum(s["mean"] for s in brightness) / len(brightness), 4)
            if brightness else None,
            "mean_min": round(min((s["mean"] for s in brightness), default=0.0), 4),
            "mean_max": round(max((s["mean"] for s in brightness), default=0.0), 4),
            "p99_max": round(max((s["p99"] for s in brightness), default=0.0), 4),
        } if brightness else None,
    })
    if meta.get("width") != 1600 or meta.get("height") != 1200:
        report["errors"].append("%s: expected 1600x1200, got %sx%s"
                                % (label, meta.get("width"), meta.get("height")))
    return meta


def main(argv=None):
    parser = argparse.ArgumentParser(prog="check_mission_dataset.py")
    parser.add_argument("--data", default=None,
                        help="dataset root (default: <repo>/data/synthetic/mission)")
    parser.add_argument("--report", default=None,
                        help="report path (default: <data>/validate_report.json)")
    args = parser.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(here))
    data_dir = os.path.abspath(args.data or os.path.join(repo, "data", "synthetic", "mission"))
    report = {"dataset_dir": data_dir, "errors": [], "warnings": [], "ok": False}
    if not os.path.isdir(data_dir):
        print("dataset dir not found: %s" % data_dir)
        return 1
    meta = check_metadata_dir(data_dir, report, "mission")
    val_dir = os.path.join(data_dir, "val")
    if os.path.isfile(os.path.join(val_dir, "metadata_val.json")):
        check_metadata_dir(val_dir, report, "val", metadata_name="metadata_val.json")
    else:
        report["warnings"].append("no held-out validation set (val/metadata_val.json)")
    if meta is not None:
        mission = meta.get("mission") or {}
        if not mission.get("mission_id"):
            report["warnings"].append("metadata.mission.mission_id is missing")
        if int((report.get("sets", {}).get("mission", {}) or {}).get("frames", 0)) < 12:
            report["warnings"].append("fewer than 12 frames (acceptance target is >= 12)")
    report["ok"] = len(report["errors"]) == 0
    report_path = args.report or os.path.join(data_dir, "validate_report.json")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("report -> %s" % report_path)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
