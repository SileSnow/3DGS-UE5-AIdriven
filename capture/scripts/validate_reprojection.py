"""
validate_reprojection.py -- independent reprojection check of the synthetic dataset contract.

Run with the SYSTEM python (needs Pillow + numpy), NOT inside Unreal:

    python capture/scripts/validate_reprojection.py

It consumes the dedicated calibration render produced by

    run_capture.ps1 -Mode calib

i.e. capture/validation/metadata_calib.json + the calib_*.png images + markers_calib.json.

For every near-nadir calibration frame it:
  1. detects the magenta calibration cube in the rendered PNG (colour threshold),
  2. projects the 8 known 3D corners of that cube (UE world cm) through the recorded
     c2w matrix and recorded fx/fy/cx/cy -> predicted 2D bounding box,
  3. compares the predicted bbox against the detected bbox (for a convex cube the image
     silhouette bbox equals the bbox of the projected corners), and also reports the
     centroid error.

A sub-pixel bbox error proves that the exported c2w row-major convention, the fx/fy
derived from the DJI Mini 4 Pro field of view, and the rendered pixels are mutually
consistent, i.e. gs-pipeline / COLMAP conversion (shared/CONVENTIONS.md section 3) can
consume the metadata directly.

Output: capture/validation/reprojection_check.json + console summary.
"""

import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
CAPTURE_ROOT = os.path.dirname(HERE)
VALIDATION_DIR = os.path.join(CAPTURE_ROOT, "validation")
BBOX_TOLERANCE_PX = 2.0   # antialiasing / silhouette edge tolerance


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def camera_axes(c2w):
    # c2w is row-major, columns are the camera axes: fwd=(m0,m4,m8), right=(m1,m5,m9),
    # up=(m2,m6,m10), translation=(m3,m7,m11).
    forward = np.array([c2w[0], c2w[4], c2w[8]], dtype=np.float64)
    right = np.array([c2w[1], c2w[5], c2w[9]], dtype=np.float64)
    up = np.array([c2w[2], c2w[6], c2w[10]], dtype=np.float64)
    origin = np.array([c2w[3], c2w[7], c2w[11]], dtype=np.float64)
    return forward, right, up, origin


def project_points(meta, c2w, points_ue):
    fx = float(meta["fx"])
    fy = float(meta["fy"])
    cx = float(meta["cx"])
    cy = float(meta["cy"])
    forward, right, up, origin = camera_axes(c2w)
    out = []
    for point in points_ue:
        delta = np.array(point, dtype=np.float64) - origin
        depth = float(np.dot(forward, delta))
        if depth <= 1e-6:
            out.append((None, None, depth))
            continue
        u = cx + fx * float(np.dot(right, delta)) / depth
        v = cy - fy * float(np.dot(up, delta)) / depth
        out.append((u, v, depth))
    return out


def cube_corners(center, size):
    cx, cy, cz = center
    half = size * 0.5
    return [(cx + sx * half, cy + sy * half, cz + sz * half)
            for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]


def detect_magenta(image_path):
    image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.float32)
    red = image[:, :, 0]
    green = image[:, :, 1]
    blue = image[:, :, 2]
    mask = (red > 110.0) & (blue > 110.0) & (green < 0.62 * np.minimum(red, blue))
    count = int(mask.sum())
    if count < 40:
        return None
    ys, xs = np.nonzero(mask)
    return {
        "count": count,
        "u": float(xs.mean()),
        "v": float(ys.mean()),
        "bbox": [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())],
    }


def main():
    meta_path = os.path.join(VALIDATION_DIR, "metadata_calib.json")
    if not os.path.isfile(meta_path):
        print("missing calibration metadata:", meta_path)
        print("run:  powershell -ExecutionPolicy Bypass -File capture\\run_capture.ps1 -Mode calib")
        return 2
    meta = load_json(meta_path)
    frames = meta.get("frames", [])
    report = {
        "metadata": meta_path,
        "intrinsics": {"fx": meta["fx"], "fy": meta["fy"], "cx": meta["cx"], "cy": meta["cy"],
                       "width": meta["width"], "height": meta["height"]},
        "bbox_tolerance_px": BBOX_TOLERANCE_PX,
        "frames": [],
        "max_bbox_error_px": None,
        "mean_bbox_error_px": None,
        "max_centroid_error_px": None,
        "ok": False,
    }
    bbox_errors = []
    centroid_errors = []
    for frame in frames:
        image_path = os.path.join(VALIDATION_DIR, frame["file"])
        target = frame.get("target_ue_cm")
        size = float(frame.get("target_size_cm", 0.0))
        if target is None or size <= 0.0:
            continue
        corners = cube_corners(target, size)
        projected = project_points(meta, frame["c2w"], corners)
        valid = [(u, v) for (u, v, depth) in projected if u is not None]
        detected = detect_magenta(image_path) if os.path.isfile(image_path) else None
        entry = {
            "file": frame["file"],
            "target_ue_cm": target,
            "target_size_cm": size,
            "predicted_bbox": None,
            "detected": detected,
        }
        if len(valid) == 8:
            us = [p[0] for p in valid]
            vs = [p[1] for p in valid]
            predicted_bbox = [min(us), min(vs), max(us), max(vs)]
            entry["predicted_bbox"] = [round(v, 3) for v in predicted_bbox]
            if detected is not None:
                errors = [abs(predicted_bbox[i] - detected["bbox"][i]) for i in range(4)]
                entry["bbox_error_px"] = [round(e, 3) for e in errors]
                entry["bbox_error_max_px"] = round(max(errors), 3)
                bbox_errors.append(max(errors))
                cu = 0.5 * (predicted_bbox[0] + predicted_bbox[2])
                cv = 0.5 * (predicted_bbox[1] + predicted_bbox[3])
                centroid_error = float(np.hypot(detected["u"] - cu, detected["v"] - cv))
                entry["centroid_error_px"] = round(centroid_error, 3)
                centroid_errors.append(centroid_error)
        report["frames"].append(entry)
        print("%-22s predicted_bbox=%s detected_bbox=%s err_max=%s px" % (
            frame["file"],
            ("(%7.2f,%7.2f,%7.2f,%7.2f)" % tuple(entry["predicted_bbox"])) if entry["predicted_bbox"] else "n/a",
            ("(%7.2f,%7.2f,%7.2f,%7.2f)" % tuple(detected["bbox"])) if detected else "MISSING",
            ("%.3f" % entry["bbox_error_max_px"]) if "bbox_error_max_px" in entry else "n/a"))
    if bbox_errors:
        report["max_bbox_error_px"] = round(max(bbox_errors), 4)
        report["mean_bbox_error_px"] = round(float(np.mean(bbox_errors)), 4)
        report["max_centroid_error_px"] = round(max(centroid_errors), 4) if centroid_errors else None
        report["ok"] = report["max_bbox_error_px"] < BBOX_TOLERANCE_PX
    out_path = os.path.join(VALIDATION_DIR, "reprojection_check.json")
    os.makedirs(VALIDATION_DIR, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    print("")
    print("frames=%d  mean_bbox_error=%.4f px  max_bbox_error=%.4f px  ok=%s" % (
        len(bbox_errors), report["mean_bbox_error_px"] or -1.0,
        report["max_bbox_error_px"] or -1.0, report["ok"]))
    print("wrote", out_path)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
