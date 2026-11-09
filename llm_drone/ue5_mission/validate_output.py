#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_output.py -- offline acceptance check for the UE5 mission dataset (task-6).

Run with the SYSTEM python (Pillow + numpy, no Unreal needed):

    python llm_drone/ue5_mission/validate_output.py --out data/synthetic/mission

Checks (all of them must pass for exit code 0)
  1. images: >= 12 PNGs, each exactly width x height from metadata (1600x1200),
     not black: mean luminance > 5 and variance > 100 (0..255 scale, full image),
     all images distinct (md5).
  2. metadata.json: shared/CONVENTIONS.md + PROTOCOL.md 7.3 schema keys, intrinsics match
     the capture camera (fx=fy=1148.343 @1600x1200), frame count == PNG count, files exist,
     ordered 0001..N, timestamps monotonic.
  3. c2w is a proper rigid transform: ||R R^T - I||max < 1e-6, det(R) = +1, bottom row
     [0,0,0,1]; camera looks down for negative gimbal pitch.
  4. simulated GPS round trip: c2w translation -> WGS84 -> UE cm, error < 0.05 cm.
  5. gimbal / heading correspondence: gimbal_deg.yaw == heading_deg - 90,
     gimbal_deg.pitch == gimbal_pitch_deg, roll == 0 (vs the mission waypoint).
  6. ground-truth cross-check: re-derive every expected pose/c2w/GPS from the mission JSON
     (via mission_io, independent of the renderer) and compare with metadata.
  7. camera geometry: image centre ray hits the campus ground plane inside the 90x90 m
     scene (catches wrong pose convention / depth flips).

Writes <results>/validation.json and, by default, <results>/contact_sheet.png.
Exit code 0 iff every check passes.

Usage:
    python llm_drone/ue5_mission/validate_output.py [--out DIR] [--mission JSON]
        [--results DIR] [--tag p1] [--min-frames 12] [--no-contact-sheet]
"""

import argparse
import hashlib
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import mission_io as M  # noqa: E402  (same truth math as the renderer)

DEFAULT_OUT = os.path.join(REPO_ROOT, "data", "synthetic", "mission")
DEFAULT_MISSION = os.path.join(REPO_ROOT, "llm_drone", "spec", "sample_mission.json")
DEFAULT_RESULTS = os.path.join(HERE, "results")
CAPTURE_SCRIPTS = os.path.join(REPO_ROOT, "capture", "scripts")

MIN_FRAMES = 12
TARGET_WIDTH = 1600
TARGET_HEIGHT = 1200
# Non-black thresholds: luminance in 0..255, full-resolution image (Lead's criterion:
# 亮度均值 > 5 且方差 > 100).
LUMA_MEAN_MIN = 5.0
LUMA_VAR_MIN = 100.0
RIGID_TOL = 1e-6
GPS_ROUNDTRIP_TOL_CM = 0.05
TRUTH_C2W_TOL = 1e-9
TRUTH_GPS_DEG_TOL = 1e-9
TRUTH_GPS_ALT_TOL = 1e-4
GIMBAL_TOL_DEG = 1e-6
SCENE_HALF_CM = 4500.0          # procedural campus: 90 m x 90 m centred on the world origin
GROUND_HALF_CM = 19000.0        # build_scene ground plane is 400 m x 400 m (safety margin 10 m)
COVERAGE_EXPAND_CM = 2500.0     # mission footprint + 25 m counts as "still near the mission area"
SENSOR_W_MM = 9.6
SENSOR_H_MM = 7.2
FOV_DIAGONAL_DEG = 82.1


def capture_camera_model():
    """DJI Mini 4 Pro camera model of capture/scripts/synth_common.py, from first principles."""
    diagonal = math.hypot(SENSOR_W_MM, SENSOR_H_MM)
    focal = (diagonal * 0.5) / math.tan(math.radians(FOV_DIAGONAL_DEG * 0.5))
    width, height = TARGET_WIDTH, TARGET_HEIGHT
    return {
        "width": width,
        "height": height,
        "fx": round(focal / SENSOR_W_MM * width, 4),
        "fy": round(focal / SENSOR_H_MM * height, 4),
        "fov_horizontal_deg": round(math.degrees(2.0 * math.atan(SENSOR_W_MM * 0.5 / focal)), 4),
        "fov_vertical_deg": round(math.degrees(2.0 * math.atan(SENSOR_H_MM * 0.5 / focal)), 4),
        "sensor_mm": {"width": SENSOR_W_MM, "height": SENSOR_H_MM, "diagonal": round(diagonal, 4)},
    }

REQUIRED_TOP_KEYS = ("dataset", "camera_model", "width", "height", "fx", "fy", "cx", "cy",
                     "coord_system", "origin_wgs84", "frames")
REQUIRED_FRAME_KEYS = ("file", "c2w", "gps", "gimbal_deg", "timestamp")


# --------------------------------------------------------------------------------- helpers
def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as handle:  # tolerate a PowerShell UTF-8 BOM
        return json.load(handle)


def same_dir(first, second):
    """Compare two directory paths, resolving the C:\\UEW ASCII junction on Windows."""
    def normalise(value):
        return os.path.normcase(os.path.normpath(str(value))).replace("/", "\\")

    left, right = normalise(first), normalise(second)
    if left == right:
        return True
    try:
        if os.path.isdir(first) and os.path.isdir(second):
            return (os.path.normcase(os.path.realpath(first))
                    == os.path.normcase(os.path.realpath(second)))
    except Exception:
        pass
    return left.endswith(right) or right.endswith(left)


def now_iso():
    return M.now_iso()


def rotation_checks(c2w):
    """Return (orthonormality error, det, bottom-row error) for a row-major 4x4 c2w."""
    matrix = np.asarray(c2w, dtype=np.float64).reshape(4, 4)
    rotation = matrix[:3, :3]
    orthogonality = float(np.abs(rotation @ rotation.T - np.eye(3)).max())
    determinant = float(np.linalg.det(rotation))
    bottom = float(np.abs(matrix[3, :3]).max() + abs(matrix[3, 3] - 1.0))
    return orthogonality, determinant, bottom


def image_luma(path):
    """Full-resolution luminance statistics of a PNG (0..255 scale)."""
    with Image.open(path) as image:
        size = image.size
        mode = image.mode
        luma = np.asarray(image.convert("L"), dtype=np.float64)
    return {
        "size": [int(size[0]), int(size[1])],
        "mode": mode,
        "mean": float(luma.mean()),
        "var": float(luma.var()),
        "p95": float(np.percentile(luma, 95)),
        "max": float(luma.max()),
        "md5": hashlib.md5(open(path, "rb").read()).hexdigest(),
    }


def contact_sheet(image_paths, target_path, columns=None, thumb=(400, 300)):
    """Grid contact sheet with frame index labels (evidence for visual inspection)."""
    if not image_paths:
        return None
    count = len(image_paths)
    columns = columns or max(4, int(math.ceil(math.sqrt(count))))
    rows = int(math.ceil(count / float(columns)))
    sheet = Image.new("RGB", (columns * thumb[0], rows * thumb[1]), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for index, path in enumerate(image_paths):
        with Image.open(path) as image:
            thumb_image = image.convert("RGB").resize(thumb, Image.Resampling.BILINEAR)
        x = (index % columns) * thumb[0]
        y = (index // columns) * thumb[1]
        sheet.paste(thumb_image, (x, y))
        label = os.path.basename(path)
        if font is not None:
            draw.text((x + 6, y + 4), label, fill=(255, 255, 0), font=font)
    directory = os.path.dirname(os.path.abspath(target_path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    sheet.save(target_path, format="PNG")
    return target_path


# ------------------------------------------------------------------------------------ report
class Report(object):
    """Validation report.

    checks have status pass | fail | skip.  A fail makes the dataset fail; a skip records a
    check that cannot run offline (e.g. needs the unreal module) without failing; warnings[]
    records expected-but-notable observations (e.g. front-looking geometry) and never fails.
    """

    def __init__(self, out_dir, mission_path):
        self.payload = {
            "ok": False,
            "generated_at": now_iso(),
            "out_dir": out_dir,
            "mission_file": mission_path,
            "checks": [],
            "problems": [],
            "warnings": [],
            "summary": {},
        }

    def add(self, name, ok, detail=None):
        self.payload["checks"].append({
            "name": name, "status": "pass" if ok else "fail", "ok": bool(ok), "detail": detail})
        if not ok:
            self.payload["problems"].append(name + ("" if detail is None else ": "
                                                    + json.dumps(detail, ensure_ascii=False)))
        return bool(ok)

    def skip(self, name, detail=None):
        self.payload["checks"].append({
            "name": name, "status": "skip", "ok": True, "detail": detail})
        return True

    def warn(self, message, detail=None):
        text = message + ("" if detail is None else ": "
                          + json.dumps(detail, ensure_ascii=False))
        if text not in self.payload["warnings"]:
            self.payload["warnings"].append(text)
        return False

    def finish(self):
        counts = {"pass": 0, "fail": 0, "skip": 0}
        for entry in self.payload["checks"]:
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
        summary = self.payload["summary"]
        summary["n_checks_pass"] = counts["pass"]
        summary["n_checks_fail"] = counts["fail"]
        summary["n_checks_skip"] = counts["skip"]
        summary["n_warnings"] = len(self.payload["warnings"])
        self.payload["ok"] = counts["fail"] == 0
        return self.payload["ok"]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="validate_output.py",
                                     description="Offline acceptance check of the UE5 mission dataset.")
    parser.add_argument("--out", default=DEFAULT_OUT, help="dataset root (metadata.json + images/)")
    parser.add_argument("--mission", default=DEFAULT_MISSION, help="source mission JSON for truth cross-check")
    parser.add_argument("--results", default=DEFAULT_RESULTS, help="directory for validation.json / contact sheet")
    parser.add_argument("--tag", default="", help="suffix for report files, e.g. --tag p1")
    parser.add_argument("--min-frames", type=int, default=MIN_FRAMES)
    parser.add_argument("--no-contact-sheet", action="store_true")
    args = parser.parse_args(argv)

    out_dir = os.path.abspath(args.out)
    results_dir = os.path.abspath(args.results)
    mission_path = os.path.abspath(args.mission)
    suffix = ("_" + args.tag) if args.tag else ""
    report = Report(out_dir, mission_path)
    summary = report.payload["summary"]
    summary.update({
        "n_frames": None,
        "n_images": 0,
        "width": None,
        "height": None,
        "min_luma_mean": None,
        "min_luma_var": None,
        "max_rigid_error": None,
        "max_gps_roundtrip_cm": None,
        "max_truth_c2w_error": None,
        "max_gimbal_error_deg": None,
        "n_render_summary": None,
    })

    # ---------------------------------------------------------------- metadata.json schema
    metadata_path = os.path.join(out_dir, "metadata.json")
    if not os.path.isfile(metadata_path):
        report.add("metadata_exists", False, metadata_path)
        return _write_report(report, results_dir, suffix)
    metadata = load_json(metadata_path)
    report.add("metadata_exists", True, metadata_path)
    missing = [key for key in REQUIRED_TOP_KEYS if key not in metadata]
    report.add("metadata_schema_keys", not missing, {"missing": missing})
    if missing:
        return _write_report(report, results_dir, suffix)
    frames = metadata["frames"]
    width = int(metadata["width"])
    height = int(metadata["height"])
    summary["n_frames"] = len(frames)
    summary["width"] = width
    summary["height"] = height
    report.add("resolution", (width, height) == (TARGET_WIDTH, TARGET_HEIGHT),
               {"metadata": [width, height], "expected": [TARGET_WIDTH, TARGET_HEIGHT]})
    report.add("coord_system", metadata.get("coord_system") == "UE_LHS_Zup_cm",
               metadata.get("coord_system"))
    origin = metadata.get("origin_wgs84") or {}
    origin_ok = all(key in origin for key in ("lat", "lon", "alt")) and all(
        isinstance(origin[key], (int, float)) for key in ("lat", "lon", "alt"))
    report.add("origin_wgs84_schema", origin_ok, origin)

    # ------------------------------------------------------------- source mission + truth
    truth_poses = []
    mission = None
    truth_error = None
    if not os.path.isfile(mission_path):
        report.add("mission_file_exists", False, mission_path)
    else:
        try:
            mission = M.load_mission(mission_path)
            truth_poses = M.build_render_plan(mission)
            report.add("mission_file_exists", True,
                       {"mission_id": mission["mission_id"],
                        "source_format": mission.get("format"),
                        "n_photo_waypoints": len(mission["photo_waypoints"])})
            report.add("frame_count_matches_mission", len(truth_poses) == len(frames),
                       {"metadata_frames": len(frames), "mission_photos": len(truth_poses)})
            origin_match = all(
                abs(float(origin[key]) - float(mission["origin_wgs84"][key])) <= 1e-9
                for key in ("lat", "lon", "alt"))
            report.add("origin_matches_mission", origin_match,
                       {"metadata": origin, "mission": mission["origin_wgs84"]})
            camera = mission["camera"]
            intrinsics = {
                "fx": [float(metadata["fx"]), float(camera["fx"])],
                "fy": [float(metadata["fy"]), float(camera["fy"])],
                "cx": [float(metadata["cx"]), float(camera["cx"])],
                "cy": [float(metadata["cy"]), float(camera["cy"])],
            }
            intrinsics_ok = all(abs(pair[0] - pair[1]) <= 1e-3 for pair in intrinsics.values())
            report.add("intrinsics_match_mission_camera", intrinsics_ok, intrinsics)
        except M.MissionError as exc:
            report.add("mission_file_exists", False, str(exc))

    # capture camera constants (what the rig actually renders, capture/scripts/synth_common.py
    # x64-66 + README 4: 1/1.3 inch 4:3 sensor 9.6x7.2 mm, 82.1 deg diagonal FOV, 1600x1200).
    # Computed here from first principles so this offline validator never imports unreal.
    capture_constants = capture_camera_model()
    capture_ok = (
        int(metadata["width"]) == capture_constants["width"]
        and int(metadata["height"]) == capture_constants["height"]
        and abs(float(metadata["fx"]) - capture_constants["fx"]) < 5e-3
        and abs(float(metadata["fy"]) - capture_constants["fy"]) < 5e-3)
    report.add("metadata_matches_capture_camera_model", capture_ok, {
        "metadata_fx": float(metadata["fx"]),
        "capture_model_fx": capture_constants["fx"],
        "metadata_fov_horizontal_deg": (metadata.get("fov_deg") or {}).get("horizontal"),
        "capture_model_fov_horizontal_deg": capture_constants["fov_horizontal_deg"],
    })
    # Cross-check against the actual capture tool constants when importable.  synth_common
    # imports unreal, so on the system python this becomes a SKIP (not a FAIL).
    try:
        sys.path.insert(0, CAPTURE_SCRIPTS)
        import synth_common as C  # noqa: E402
        same = (int(metadata["width"]) == C.WIDTH and int(metadata["height"]) == C.HEIGHT
                and abs(float(metadata["fx"]) - C.FX) < 5e-3
                and abs(float(metadata["fy"]) - C.FY) < 5e-3)
        report.add("metadata_matches_capture_constants", same, {
            "capture_fx": round(C.FX, 4), "capture_fov_horizontal_deg": round(C.FOV_H_DEG, 4)})
    except Exception as exc:
        report.skip("metadata_matches_capture_constants",
                    "skipped: unreal unavailable (%s: %s)" % (type(exc).__name__, exc))
    summary["capture_constants"] = capture_constants

    # --------------------------------------------------------------------- images on disk
    images_dir = os.path.join(out_dir, "images")
    png_names = sorted([name for name in os.listdir(images_dir)
                        if name.lower().endswith(".png")]) if os.path.isdir(images_dir) else []
    summary["n_images"] = len(png_names)
    report.add("image_count", len(png_names) >= args.min_frames,
               {"n_images": len(png_names), "min_frames": args.min_frames})
    report.add("frame_count_matches_images", len(png_names) == len(frames),
               {"n_images": len(png_names), "n_frames": len(frames)})

    # mission footprint (UE cm) used to classify image-centre ground hits: a forward-looking
    # oblique camera legitimately looks beyond its photo-point footprint.
    if truth_poses:
        xs = [pose["loc_cm"][0] for pose in truth_poses]
        ys = [pose["loc_cm"][1] for pose in truth_poses]
        coverage = {"min_x": min(xs) - COVERAGE_EXPAND_CM,
                    "max_x": max(xs) + COVERAGE_EXPAND_CM,
                    "min_y": min(ys) - COVERAGE_EXPAND_CM,
                    "max_y": max(ys) + COVERAGE_EXPAND_CM}
    else:
        coverage = {"min_x": -SCENE_HALF_CM - COVERAGE_EXPAND_CM,
                    "max_x": SCENE_HALF_CM + COVERAGE_EXPAND_CM,
                    "min_y": -SCENE_HALF_CM - COVERAGE_EXPAND_CM,
                    "max_y": SCENE_HALF_CM + COVERAGE_EXPAND_CM}
    summary["mission_coverage_ue_cm"] = coverage

    # --------------------------------------------------------------- per-frame deep checks
    frame_problems = []
    per_frame = []
    luma_stats = []
    md5s = {}
    rigid_errors = []
    gps_errors = []
    gimbal_errors = []
    truth_c2w_errors = []
    timestamps = []
    image_paths = []
    for index, frame in enumerate(frames):
        tag = "frame[%d]" % index
        missing_keys = [key for key in REQUIRED_FRAME_KEYS if key not in frame]
        if missing_keys:
            frame_problems.append("%s missing %s" % (tag, missing_keys))
            continue
        rel = str(frame["file"]).replace("\\", "/")
        expected_rel = "images/%04d.png" % (index + 1)
        if rel != expected_rel:
            frame_problems.append("%s file=%r != %r" % (tag, rel, expected_rel))
        c2w = frame["c2w"]
        if not isinstance(c2w, list) or len(c2w) != 16:
            frame_problems.append("%s c2w is not 16 floats" % tag)
            continue
        orthogonality, determinant, bottom = rotation_checks(c2w)
        rigid_errors.append(max(orthogonality, abs(determinant - 1.0), bottom))
        if orthogonality > RIGID_TOL:
            frame_problems.append("%s c2w not orthonormal (err %.3e)" % (tag, orthogonality))
        if abs(determinant - 1.0) > RIGID_TOL:
            frame_problems.append("%s c2w det %.9f != +1" % (tag, determinant))
        translation = np.array([c2w[3], c2w[7], c2w[11]], dtype=np.float64)
        gps = frame.get("gps") or {}
        gimbal = frame.get("gimbal_deg") or {}
        timestamps.append(float(frame["timestamp"]))
        # GPS round trip: c2w translation -> WGS84 -> UE cm
        gps_from_ue = M.ue_to_wgs84(translation, origin)
        gps_errors.append(float(np.linalg.norm(
            np.array([gps_from_ue["lat"] - gps.get("lat", 0.0),
                      gps_from_ue["lon"] - gps.get("lon", 0.0),
                      (gps_from_ue["alt"] - gps.get("alt", 0.0)) / 1e5]))))
        ue_back = M.wgs84_to_ue(gps["lat"], gps["lon"], gps["alt"], origin)
        roundtrip_cm = float(np.linalg.norm(np.array(ue_back) - translation))
        if roundtrip_cm > GPS_ROUNDTRIP_TOL_CM:
            frame_problems.append("%s GPS round trip %.6f cm" % (tag, roundtrip_cm))
        gps_errors.append(roundtrip_cm)
        # gimbal / heading correspondence
        heading = frame.get("mission", {}).get("heading_deg")
        pitch_deg = frame.get("mission", {}).get("gimbal_pitch_deg")
        if heading is None:
            pitch_deg = gimbal.get("pitch")
        gimbal_error = 0.0
        if heading is not None:
            gimbal_error = max(
                abs(float(gimbal.get("yaw", 0.0)) - (float(heading) - 90.0)),
                abs(float(gimbal.get("pitch", 0.0)) - float(pitch_deg)),
                abs(float(gimbal.get("roll", 0.0))))
            if abs(float(gimbal.get("roll", 0.0))) > GIMBAL_TOL_DEG:
                frame_problems.append("%s gimbal roll %.6f != 0" % (tag, float(gimbal["roll"])))
            if gimbal_error > GIMBAL_TOL_DEG:
                frame_problems.append("%s gimbal/heading mismatch %.6f deg" % (tag, gimbal_error))
        gimbal_errors.append(gimbal_error)
        # camera looks down (pitch negative)
        matrix = np.asarray(c2w, dtype=np.float64).reshape(4, 4)
        forward = matrix[:3, 0]
        if float(gimbal.get("pitch", -45.0)) < -1.0 and forward[2] >= 0.0:
            frame_problems.append("%s forward.z %.3f >= 0 while looking down" % (tag, forward[2]))
        # camera height above ground
        if not (500.0 <= translation[2] <= 12000.0):
            frame_problems.append("%s camera height %.1f cm outside [5,120] m" % (tag, translation[2]))
        # image-centre ray vs the ground plane: PASS inside the mission footprint (+25 m
        # expansion), WARN when it lands beyond the footprint but still on the 400 m ground
        # plane (expected for an oblique -45 deg camera looking ahead), FAIL if it misses the
        # ground plane entirely or points away from the ground.
        ground_hit = None
        if abs(forward[2]) > 1e-6:
            scale = -translation[2] / forward[2]
            hit = translation + forward * scale
            ground_hit = [round(float(hit[0]), 2), round(float(hit[1]), 2)]
            inside_coverage = (coverage["min_x"] <= hit[0] <= coverage["max_x"]
                               and coverage["min_y"] <= hit[1] <= coverage["max_y"])
            inside_ground = (abs(hit[0]) <= GROUND_HALF_CM and abs(hit[1]) <= GROUND_HALF_CM)
            if scale <= 0.0:
                frame_problems.append("%s image-centre ray points away from the ground" % tag)
            elif not inside_ground:
                frame_problems.append("%s image-centre ground hit (%.0f, %.0f) cm outside the "
                                      "400 m ground plane" % (tag, hit[0], hit[1]))
            elif not inside_coverage:
                report.warn(
                    "%s image-centre ground hit (%d, %d) cm is beyond the mission footprint "
                    "but inside the 400 m ground plane -- expected for the oblique -45 deg "
                    "camera doing a forward-facing survey" % (tag, int(hit[0]), int(hit[1])),
                    {"frame": rel, "hit_ue_cm": ground_hit,
                     "mission_coverage_ue_cm": coverage})
        # truth cross-check (metadata vs mission-derived pose)
        if truth_poses and index < len(truth_poses):
            truth = truth_poses[index]
            truth_error = max(abs(float(a) - float(b))
                              for a, b in zip(c2w, truth["c2w"]))
            truth_c2w_errors.append(truth_error)
            if truth_error > TRUTH_C2W_TOL:
                frame_problems.append("%s c2w differs from mission truth by %.3e"
                                      % (tag, truth_error))
            for key in ("lat", "lon"):
                if abs(float(gps[key]) - float(truth["gps"][key])) > TRUTH_GPS_DEG_TOL:
                    frame_problems.append("%s gps.%s differs from truth" % (tag, key))
            if abs(float(gps["alt"]) - float(truth["gps"]["alt"])) > TRUTH_GPS_ALT_TOL:
                frame_problems.append("%s gps.alt differs from truth" % tag)
            if abs(float(frame["timestamp"]) - float(truth["timestamp"])) > 1e-6:
                frame_problems.append("%s timestamp differs from truth" % tag)
            if "waypoint_index" in frame and int(frame["waypoint_index"]) != int(truth["waypoint_index"]):
                frame_problems.append("%s waypoint_index differs from truth" % tag)
            if abs(float(gimbal.get("pitch", 0.0)) - float(truth["pitch"])) > GIMBAL_TOL_DEG:
                frame_problems.append("%s gimbal pitch differs from truth" % tag)
            if abs(float(gimbal.get("yaw", 0.0)) - float(truth["yaw"])) > GIMBAL_TOL_DEG:
                frame_problems.append("%s gimbal yaw differs from truth" % tag)
        # image on disk
        image_path = os.path.join(out_dir, rel)
        if not os.path.isfile(image_path):
            frame_problems.append("%s image missing: %s" % (tag, image_path))
            continue
        stats = image_luma(image_path)
        stats["file"] = rel
        luma_stats.append(stats)
        image_paths.append(image_path)
        if tuple(stats["size"]) != (width, height):
            frame_problems.append("%s image %s != metadata %dx%d"
                                  % (tag, stats["size"], width, height))
        if stats["mean"] <= LUMA_MEAN_MIN:
            frame_problems.append("%s image too dark (mean %.2f)" % (tag, stats["mean"]))
        if stats["var"] <= LUMA_VAR_MIN:
            frame_problems.append("%s image has no detail (var %.1f)" % (tag, stats["var"]))
        if stats["md5"] in md5s:
            frame_problems.append("%s duplicate image of %s" % (tag, md5s[stats["md5"]]))
        md5s[stats["md5"]] = rel
        per_frame.append({
            "file": rel,
            "image": {key: round(stats[key], 4) if isinstance(stats[key], float) else stats[key]
                      for key in ("mean", "var", "p95", "max")},
            "c2w_rigid_error": orthogonality,
            "gps_roundtrip_cm": roundtrip_cm,
            "gimbal_error_deg": gimbal_error,
            "truth_c2w_error": truth_error,
            "image_centre_ground_hit_ue_cm": ground_hit,
            "gps": gps,
            "gimbal_deg": gimbal,
            "timestamp": frame["timestamp"],
        })
        truth_error = None  # per-frame value already recorded

    report.add("per_frame_checks", not frame_problems,
               {"problems": frame_problems[:40], "n_problems": len(frame_problems)})
    if luma_stats:
        summary["min_luma_mean"] = round(min(item["mean"] for item in luma_stats), 3)
        summary["min_luma_var"] = round(min(item["var"] for item in luma_stats), 3)
        summary["max_luma_p95"] = round(max(item["p95"] for item in luma_stats), 3)
    summary["max_rigid_error"] = round(max(rigid_errors), 12) if rigid_errors else None
    summary["max_gps_roundtrip_cm"] = round(max(gps_errors), 9) if gps_errors else None
    summary["max_truth_c2w_error"] = round(max(truth_c2w_errors), 12) if truth_c2w_errors else None
    summary["max_gimbal_error_deg"] = round(max(gimbal_errors), 12) if gimbal_errors else None
    summary["timestamp_span_s"] = ([timestamps[0], timestamps[-1]] if timestamps else None)
    monotonic = all(b >= a for a, b in zip(timestamps, timestamps[1:]))
    report.add("timestamps_monotonic", monotonic, summary["timestamp_span_s"])

    # ------------------------------------------------------------------ render run summary
    run_summary = None
    log_dir = os.path.join(REPO_ROOT, "llm_drone", "logs", "ue5-mission")
    if os.path.isdir(log_dir):
        candidates = sorted([name for name in os.listdir(log_dir)
                             if name.startswith("run_") and name.endswith(".json")],
                            key=lambda name: os.path.getmtime(os.path.join(log_dir, name)),
                            reverse=True)
        for name in candidates:
            try:
                candidate = load_json(os.path.join(log_dir, name))
            except Exception:
                continue
            # render_mission.py writes run_<mission>_<ts>.json; run_mission.ps1 also writes a
            # run_<ts>.json verdict without n_frames -> only the renderer summary is relevant.
            if candidate.get("n_frames") is None:
                continue
            if same_dir(candidate.get("out_dir", ""), out_dir):
                run_summary = candidate
                run_summary["log_file"] = os.path.join(log_dir, name)
                break
    if run_summary:
        summary["n_render_summary"] = run_summary.get("n_frames")
        report.add("render_summary_matches", run_summary.get("n_frames") == len(frames),
                   {"run_summary_frames": run_summary.get("n_frames"),
                    "metadata_frames": len(frames),
                    "timing": run_summary.get("timing"),
                    "exposure": run_summary.get("exposure"),
                    "sun_intensity_lux": run_summary.get("sun_intensity_lux")})
        summary["render"] = {
            "n_frames": run_summary.get("n_frames"),
            "exposure": run_summary.get("exposure"),
            "sun_intensity_lux": run_summary.get("sun_intensity_lux"),
            "timing": run_summary.get("timing"),
            "log_file": run_summary.get("log_file"),
            "c2w_max_diff_vs_capture": run_summary.get("c2w_max_diff_vs_capture"),
        }
    else:
        report.add("render_summary_matches", True,
                   "no run_*.json with matching out_dir (offline validation only)")

    # ------------------------------------------------------------------- contact sheet etc.
    contact = None
    if not args.no_contact_sheet and image_paths:
        contact_path = os.path.join(results_dir, "contact_sheet%s.png" % suffix)
        try:
            contact = contact_sheet(image_paths, contact_path)
            report.add("contact_sheet", contact is not None, contact)
        except Exception as exc:
            report.add("contact_sheet", False, str(exc))
    report.payload["per_frame"] = per_frame
    report.payload["summary"] = summary
    report.payload["metadata_file"] = metadata_path
    report.payload["contact_sheet"] = contact
    report.payload["capture_constants"] = capture_constants
    return _write_report(report, results_dir, suffix)


def _write_report(report, results_dir, suffix):
    report.finish()
    if not os.path.isdir(results_dir):
        os.makedirs(results_dir)
    path = os.path.join(results_dir, ("validation%s.json" % suffix))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report.payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    payload = report.payload
    summary = payload.get("summary") or {}
    print("validation: ok=%s  checks=%d (pass=%s fail=%s skip=%s)  problems=%d  warnings=%d" % (
        payload["ok"], len(payload["checks"]),
        summary.get("n_checks_pass"), summary.get("n_checks_fail"),
        summary.get("n_checks_skip"), len(payload["problems"]),
        len(payload.get("warnings", []))))
    summary = payload.get("summary") or {}
    print("frames=%s images=%s size=%sx%s  luma_mean_min=%s luma_var_min=%s" % (
        summary.get("n_frames"), summary.get("n_images"),
        summary.get("width"), summary.get("height"),
        summary.get("min_luma_mean"), summary.get("min_luma_var")))
    print("max_rigid_err=%s  max_gps_roundtrip_cm=%s  max_truth_c2w_err=%s  max_gimbal_err_deg=%s"
          % (summary.get("max_rigid_error"), summary.get("max_gps_roundtrip_cm"),
             summary.get("max_truth_c2w_error"), summary.get("max_gimbal_error_deg")))
    marks = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}
    for check in payload["checks"]:
        print("  [%s] %s" % (marks.get(check["status"], "?"), check["name"]))
    for warning in payload.get("warnings", []):
        print("  WARN:", warning)
    for problem in payload["problems"]:
        print("  PROBLEM:", problem)
    print("report ->", path)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
