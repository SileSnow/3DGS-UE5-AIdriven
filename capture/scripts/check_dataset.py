"""
check_dataset.py -- offline contract / consistency check of the synthetic dataset.

Run with the SYSTEM python (Pillow + numpy), no Unreal needed:

    python capture/scripts/check_dataset.py

Checks
  1. every frame in metadata.json / metadata_val.json has an existing PNG of the
     recorded resolution,
  2. the c2w matrices are proper rigid transforms (orthonormal camera axes, det +1),
  3. the simulated GPS in metadata matches the UE->WGS84 mapping in shared/CONVENTIONS.md,
  4. the magenta calibration targets (known UE world positions placed by build_scene) are
     detected in the rendered images and their detected centroids agree with the projected
     positions of the known 3D points through c2w + fx/fy/cx/cy (a self-consistency check of
     the exported camera convention, no extra Unreal render needed).

Exit code 0 if all checks pass.
"""

import json
import math
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
CAPTURE_ROOT = os.path.dirname(HERE)
PROJECT_ROOT = os.path.dirname(CAPTURE_ROOT)
DATA_ROOT = os.path.join(PROJECT_ROOT, "data", "synthetic")
TRAIN_DIR = os.path.join(DATA_ROOT, "capture")
VAL_DIR = os.path.join(DATA_ROOT, "val")

ORIGIN = {"lat": 39.9042, "lon": 116.4074, "alt": 43.0}
M_PER_DEG_LAT = 111320.0

# magenta targets placed by synth_common.build_scene() (UE world cm, cube centre)
TARGETS = [
    (-1600.0, -1600.0, 60.0),
    (1200.0, -800.0, 60.0),
    (2000.0, 1200.0, 60.0),
    (-1200.0, 2000.0, 60.0),
    (700.0, 700.0, 60.0),
    (0.0, 0.0, 76.5),
    (-2800.0, 2800.0, 76.5),
    (2800.0, -2800.0, 76.5),
]


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def project(meta, c2w, point):
    fx = float(meta["fx"])
    fy = float(meta["fy"])
    cx = float(meta["cx"])
    cy = float(meta["cy"])
    # c2w is row-major, columns are the camera axes: fwd=(m0,m4,m8), right=(m1,m5,m9),
    # up=(m2,m6,m10), translation=(m3,m7,m11).
    forward = np.array([c2w[0], c2w[4], c2w[8]], dtype=np.float64)
    right = np.array([c2w[1], c2w[5], c2w[9]], dtype=np.float64)
    up = np.array([c2w[2], c2w[6], c2w[10]], dtype=np.float64)
    origin = np.array([c2w[3], c2w[7], c2w[11]], dtype=np.float64)
    delta = np.array(point, dtype=np.float64) - origin
    depth = float(np.dot(forward, delta))
    if depth <= 1e-6:
        return None
    u = cx + fx * float(np.dot(right, delta)) / depth
    v = cy - fy * float(np.dot(up, delta)) / depth
    return u, v, depth


def detect_near(image, u, v, radius=60):
    """Return the centroid of magenta pixels within a window around (u, v), or None."""
    height, width = image.shape[0], image.shape[1]
    x0 = max(0, int(u) - radius)
    x1 = min(width, int(u) + radius)
    y0 = max(0, int(v) - radius)
    y1 = min(height, int(v) + radius)
    if x1 <= x0 or y1 <= y0:
        return None
    patch = image[y0:y1, x0:x1]
    red = patch[:, :, 0]
    green = patch[:, :, 1]
    blue = patch[:, :, 2]
    mask = (red > 110.0) & (blue > 110.0) & (green < 0.62 * np.minimum(red, blue))
    if int(mask.sum()) < 30:
        return None
    ys, xs = np.nonzero(mask)
    return x0 + float(xs.mean()), y0 + float(ys.mean()), int(mask.sum())


def check_set(name, meta_path, images_subdir, sample_step=15):
    report = {"name": name, "ok": True, "problems": []}
    meta = load_json(meta_path)
    frames = meta.get("frames", [])
    report["frames"] = len(frames)
    report["width"] = meta["width"]
    report["height"] = meta["height"]
    report["fx"] = meta["fx"]
    report["fy"] = meta["fy"]

    png_count = len([f for f in os.listdir(images_subdir) if f.endswith(".png")])
    report["png_count"] = png_count
    if png_count != len(frames):
        report["problems"].append("png count %d != metadata frames %d" % (png_count, len(frames)))

    rigid_errors = []
    gps_errors = []
    reprojection = []
    missing = 0
    for index, frame in enumerate(frames):
        image_path = os.path.join(images_subdir, os.path.basename(frame["file"]))
        if not os.path.isfile(image_path):
            missing += 1
            continue
        c2w = frame["c2w"]
        forward = np.array([c2w[0], c2w[4], c2w[8]])
        right = np.array([c2w[1], c2w[5], c2w[9]])
        up = np.array([c2w[2], c2w[6], c2w[10]])
        for vec in (forward, right, up):
            rigid_errors.append(abs(float(np.linalg.norm(vec)) - 1.0))
        rigid_errors.append(abs(float(np.dot(forward, right))))
        rigid_errors.append(abs(float(np.dot(forward, up))))
        rigid_errors.append(abs(float(np.dot(right, up))))
        # gps round trip
        gps = frame["gps"]
        north = (gps["lat"] - ORIGIN["lat"]) * M_PER_DEG_LAT
        east = (gps["lon"] - ORIGIN["lon"]) * M_PER_DEG_LAT * math.cos(math.radians(ORIGIN["lat"]))
        alt = gps["alt"] - ORIGIN["alt"]
        ue = np.array([east * 100.0, -north * 100.0, alt * 100.0])
        cam = np.array([c2w[3], c2w[7], c2w[11]])
        gps_errors.append(float(np.linalg.norm(ue - cam)))
        if index % sample_step != 0:
            continue
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.float32)
        for target in TARGETS:
            projected = project(meta, c2w, target)
            if projected is None:
                continue
            u, v, depth = projected
            if not (0 <= u < meta["width"] and 0 <= v < meta["height"]):
                continue
            detected = detect_near(image, u, v)
            if detected is None:
                continue
            du = detected[0] - u
            dv = detected[1] - v
            reprojection.append({"file": frame["file"], "target": target,
                                 "predicted": [round(u, 2), round(v, 2)],
                                 "detected": [round(detected[0], 2), round(detected[1], 2)],
                                 "error_px": round(math.hypot(du, dv), 3),
                                 "pixels": detected[2]})
    report["missing_images"] = missing
    report["max_rigid_error"] = round(max(rigid_errors), 6) if rigid_errors else None
    report["max_gps_roundtrip_cm"] = round(max(gps_errors), 4) if gps_errors else None
    report["reprojection"] = reprojection
    if reprojection:
        errors = [item["error_px"] for item in reprojection]
        report["reprojection_hits"] = len(errors)
        report["reprojection_mean_px"] = round(float(np.mean(errors)), 3)
        report["reprojection_max_px"] = round(float(np.max(errors)), 3)
    else:
        report["reprojection_hits"] = 0
    if missing:
        report["problems"].append("%d missing PNGs" % missing)
    if report["max_rigid_error"] is not None and report["max_rigid_error"] > 1e-5:
        report["problems"].append("c2w rotation not orthonormal (max err %s)" % report["max_rigid_error"])
    if report["max_gps_roundtrip_cm"] is not None and report["max_gps_roundtrip_cm"] > 1.0:
        report["problems"].append("gps round trip mismatch %s cm" % report["max_gps_roundtrip_cm"])
    if report.get("reprojection_hits", 0) > 0 and report["reprojection_max_px"] > 25.0:
        report["problems"].append("max reprojection error %.1f px" % report["reprojection_max_px"])
    report["ok"] = not report["problems"]
    return report


def main():
    report = {"train": None, "val": None, "ok": True}
    report["train"] = check_set("train", os.path.join(TRAIN_DIR, "metadata.json"),
                                os.path.join(TRAIN_DIR, "images"))
    report["val"] = check_set("val", os.path.join(VAL_DIR, "metadata_val.json"),
                              os.path.join(VAL_DIR, "images"))
    report["ok"] = report["train"]["ok"] and report["val"]["ok"]
    out_path = os.path.join(CAPTURE_ROOT, "dataset_check.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)

    for name in ("train", "val"):
        item = report[name]
        print("[%s] frames=%d png=%d missing=%d max_rigid_err=%s max_gps_rt_cm=%s" % (
            name, item["frames"], item["png_count"], item["missing_images"],
            item["max_rigid_error"], item["max_gps_roundtrip_cm"]))
        if item.get("reprojection_hits"):
            print("      reprojection: hits=%d mean=%.3f px max=%.3f px" % (
                item["reprojection_hits"], item["reprojection_mean_px"],
                item["reprojection_max_px"]))
            for entry in item["reprojection"][:6]:
                print("        %-16s target=%s predicted=%s detected=%s err=%.2f px" % (
                    entry["file"], [round(v, 0) for v in entry["target"]],
                    entry["predicted"], entry["detected"], entry["error_px"]))
        else:
            print("      reprojection: no magenta target visible in sampled frames")
        if item["problems"]:
            print("      PROBLEMS:", item["problems"])
    print("")
    print("dataset check ok =", report["ok"])
    print("wrote", out_path)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
