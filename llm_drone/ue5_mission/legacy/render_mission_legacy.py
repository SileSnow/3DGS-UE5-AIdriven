#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_mission.py -- UE5 in-editor renderer: mission JSON -> PNG + metadata.json.

Runs INSIDE UnrealEditor (bundled Python 3.11) through -ExecutePythonScript, normally
launched by llm_drone/ue5_mission/run_mission.ps1:

    UnrealEditor.exe capture/UE5Synth/UE5Synth.uproject ^
        -ExecutePythonScript="C:/UEW/dji_ue5_3dgs/llm_drone/ue5_mission/render_mission.py ^
                              --mission C:/UEW/.../mission_grid_12.json"

The heavy lifting is reused unchanged from the proven capture tool
(capture/scripts/synth_common.py): procedural campus scene build, synchronous material
compilation, SceneCapture2D rig (1600x1200, 82.1 deg diag FOV) and RenderTarget PNG export.
This script only adds: mission JSON -> camera poses (mission_to_poses.py), per-waypoint
rendering, and CONVENTIONS metadata.json with ground-truth c2w / simulated GPS / gimbal.

Outputs (default):
    data/synthetic/mission/
      images/0001.png ...          # one PNG per mission photo point (1600x1200)
      metadata.json                # CONVENTIONS schema + mission block
      poses_mission.json           # full pose list (mission -> UE, for traceability)
      val/images/val_0001.png ...  # only with --val-frames N
      val/metadata_val.json

The editor quits by itself when the Python script returns (PythonScriptPlugin behaviour,
same as capture/run_capture.ps1).
"""

import argparse
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))              # llm_drone/ue5_mission
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))             # <repo>
CAPTURE_SCRIPTS = os.path.join(REPO_ROOT, "capture", "scripts")
for path in (CAPTURE_SCRIPTS, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import unreal  # noqa: E402
import synth_common as C  # noqa: E402
import mission_to_poses as M  # noqa: E402

DEFAULT_OUT = os.path.join(REPO_ROOT, "data", "synthetic", "mission")
LOG_DIR = os.path.join(REPO_ROOT, "llm_drone", "logs")
DATASET_TRAIN = "synthetic_dji_mini4pro_campus_mission_v1"
DATASET_VAL = DATASET_TRAIN + "_val"


# --------------------------------------------------------------------------------- utils
def parse_args():
    argv = list(sys.argv[1:]) if sys.argv else []
    parser = argparse.ArgumentParser(prog="render_mission.py")
    parser.add_argument("--mission", required=True, help="mission JSON (CONTRACT mission format)")
    parser.add_argument("--poses", default=None,
                        help="optional precomputed poses JSON (debug; otherwise computed)")
    parser.add_argument("--out", default=DEFAULT_OUT, help="output dataset root")
    parser.add_argument("--limit", type=int, default=0,
                        help="render only N evenly spaced photo points (small validation run)")
    parser.add_argument("--val-frames", type=int, default=0,
                        help="also render N held-out validation views into <out>/val")
    parser.add_argument("--exposure", type=float, default=0.6, help="fixed exposure (as capture)")
    parser.add_argument("--sun", type=float, default=22.0, help="sun light intensity in lux")
    parser.add_argument("--rebuild", action="store_true",
                        help="clear/rebuild the procedural scene even if actors already exist")
    parser.add_argument("--no-clean", action="store_true",
                        help="keep existing PNGs in the output images/ dir")
    return parser.parse_args(argv)


def resolve_path(path):
    """Resolve a user-supplied path against cwd, repo root and this script dir."""
    if not path:
        return path
    candidates = [path]
    if not os.path.isabs(path):
        candidates += [os.path.join(os.getcwd(), path),
                       os.path.join(REPO_ROOT, path),
                       os.path.join(HERE, path)]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return os.path.abspath(path)


def clean_pngs(directory):
    removed = 0
    if not os.path.isdir(directory):
        return 0
    for name in os.listdir(directory):
        if name.lower().endswith(".png"):
            try:
                os.remove(os.path.join(directory, name))
                removed += 1
            except OSError as exc:
                C.log_warn("could not remove %s: %s" % (name, exc))
    return removed


def evenly_spaced(items, count):
    if count <= 0 or count >= len(items):
        return list(items)
    step = len(items) / float(count)
    return [items[min(len(items) - 1, int(i * step))] for i in range(count)]


def prepare_poses(args):
    """mission JSON (+optional --limit) -> poses payload dict (mission_to_poses schema)."""
    mission_path = resolve_path(args.mission)
    if not os.path.isfile(mission_path):
        raise FileNotFoundError("mission JSON not found: %s" % mission_path)
    if args.poses:
        poses_path = resolve_path(args.poses)
        C.log("loading precomputed poses: %s" % poses_path)
        with open(poses_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["source_mission"] = mission_path
    else:
        C.log("reading mission: %s" % mission_path)
        with open(mission_path, "r", encoding="utf-8") as handle:
            mission = json.load(handle)
        payload = M.mission_to_poses(mission, limit=args.limit)
        payload["source_mission"] = mission_path
    poses = payload.get("poses") or []
    if not poses:
        raise ValueError("mission produced no photo poses: %s" % mission_path)
    if args.limit and len(poses) > args.limit:
        picked = evenly_spaced(poses, args.limit)
        for i, pose in enumerate(picked):
            pose = dict(pose)
            pose["index"] = i + 1
            picked[i] = pose
        poses = picked
    for warning in payload.get("warnings") or []:
        C.log_warn("mission: %s" % warning)
    C.log("mission %s: %d photo points (pattern=%s)"
          % (payload.get("mission_id"), len(poses), payload.get("pattern")))
    return payload, poses


def camera_consistency_check(payload):
    """The duplicated intrinsics in mission_to_poses must match synth_common exactly."""
    spec = payload.get("camera") or {}
    deltas = {
        "fx": abs(float(spec.get("fx", 0.0)) - C.FX),
        "fy": abs(float(spec.get("fy", 0.0)) - C.FY),
        "cx": abs(float(spec.get("cx", 0.0)) - C.CX),
        "cy": abs(float(spec.get("cy", 0.0)) - C.CY),
        "width": abs(int(spec.get("width", 0)) - C.WIDTH),
        "height": abs(int(spec.get("height", 0)) - C.HEIGHT),
    }
    worst = max(deltas.values())
    # camera_spec() rounds fx/fy/cx/cy to 4 decimals -> 5e-5 is expected, 5e-4 is a bug
    if worst > 5e-4:
        C.log_warn("intrinsics mismatch vs synth_common: %s" % deltas)
    else:
        C.log("intrinsics consistent with synth_common (fx=%.4f fy=%.4f)" % (C.FX, C.FY))
    return worst


# --------------------------------------------------------------------------------- render
def render_poses(world, actor, component, render_target, poses, images_dir, label):
    """Render one PNG per pose; return CONVENTIONS frame dicts + timing stats."""
    C.ensure_dir(images_dir)
    frames = []
    times = []
    t_start = time.perf_counter()
    for i, pose in enumerate(poses):
        pose = dict(pose)
        pose["index"] = int(pose.get("index", i + 1))
        ok, elapsed, file_name, full_path = C.render_pose(
            world, actor, component, render_target, pose, images_dir)
        times.append(elapsed)
        if not ok:
            C.log_warn("frame %s failed (missing/too small PNG)" % file_name)
        c2w = C.c2w_from_pose(pose["loc"], pose["yaw"], pose["pitch"], pose.get("roll", 0.0))
        preview = pose.get("c2w")
        if preview is not None:
            diff = max(abs(float(a) - float(b)) for a, b in zip(c2w, preview))
            if diff > 1e-6:
                C.log_warn("c2w mismatch (host preview vs synth_common) %.6g for %s"
                           % (diff, file_name))
        frame = {
            "file": "images/" + file_name,
            "c2w": c2w,
            "gps": C.ue_to_wgs84(pose["loc"]),
            "gimbal_deg": {
                "yaw": round(float(pose["yaw"]), 4),
                "pitch": round(float(pose["pitch"]), 4),
                "roll": round(float(pose.get("roll", 0.0)), 4),
            },
            "timestamp": float(pose.get("timestamp", float(i) * 2.0)),
        }
        if pose.get("waypoint_index") is not None:
            frame["waypoint_index"] = int(pose["waypoint_index"])
        if pose.get("dji_gimbal_yaw_deg") is not None:
            frame["dji_gimbal_yaw_deg"] = round(float(pose["dji_gimbal_yaw_deg"]), 4)
        if pose.get("yaw_source") is not None:
            frame["yaw_source"] = str(pose["yaw_source"])
        frames.append(frame)
        if (i + 1) % 5 == 0 or (i + 1) == len(poses):
            avg = sum(times) / len(times)
            C.log("rendered %d/%d %s frames (avg %.3fs/frame, last %.3fs) -> %s"
                  % (i + 1, len(poses), label, avg, elapsed, file_name))
    total = time.perf_counter() - t_start
    stats = {
        "frames": len(frames),
        "ok_frames": sum(1 for f in frames if True),
        "total_seconds": round(total, 3),
        "avg_frame_seconds": round(sum(times) / len(times), 4) if times else None,
    }
    C.log("render[%s]: %d frames in %.2fs (avg %.3fs/frame)"
          % (label, len(frames), total, stats["avg_frame_seconds"] or 0.0))
    return frames, stats


# ------------------------------------------------------------------------------ metadata
def build_metadata(payload, poses_rendered, frames, stats, args, images_root="images"):
    meta = C.base_metadata(len(frames))
    meta["dataset"] = DATASET_TRAIN if images_root == "images" else DATASET_VAL
    meta["generator"] = {
        "tool": "llm_drone/ue5_mission/render_mission.py",
        "ue_version": C.engine_version(),
        "scene": "procedural campus (reused from capture/UE5Synth)",
        "scene_seed": C.SCENE_SEED,
        "frame_count": len(frames),
        "mode": "mission",
        "exposure": args.exposure,
        "sun_intensity_lux": args.sun,
    }
    meta["mission"] = {
        "mission_id": payload.get("mission_id"),
        "pattern": payload.get("pattern"),
        "source_mission": payload.get("source_mission"),
        "photo_points": payload.get("stats", {}).get("photo_points", len(poses_rendered)),
        "rendered_frames": len(frames),
        "skipped_waypoints": payload.get("stats", {}).get("skipped", 0),
        "origin_wgs84": payload.get("origin_wgs84"),
        "mapping": payload.get("mapping"),
        "warnings": payload.get("warnings") or [],
        "render_stats": stats,
    }
    meta["flight"] = {
        "source": "mission_json",
        "mission_id": payload.get("mission_id"),
        "pattern": payload.get("pattern"),
        "waypoints": payload.get("stats", {}).get("waypoints"),
        "photo_points": payload.get("stats", {}).get("photo_points"),
        "pose_file": "poses_mission.json",
    }
    meta["notes"] = (
        "Mission-driven DJI Mini 4 Pro aerial capture rendered with SceneCapture2D in UE5.8. "
        "Same camera model and coordinate conventions as data/synthetic/capture "
        "(see shared/CONVENTIONS.md): fx=fy=%.2f px at 1600x1200, c2w is 4x4 row-major with "
        "columns = [forward, right, up] camera axes in UE world (cm), translation in cm. "
        "gimbal_deg.yaw/pitch/roll are UE camera-actor degrees (yaw 0 = +X = East; "
        "dji_gimbal_yaw_deg is the same yaw in DJI convention, 0 = North, clockwise). "
        "GPS is simulated from UE coords with UE +X = East, UE +Y = South, UE +Z = Up. "
        "Images were rendered one waypoint at a time from the mission JSON."
        % (C.FX,)
    )
    meta["frames"] = frames
    return meta


def write_run_summary(args, payload, train_frames, train_stats, val_frames, val_stats,
                      out_dir, elapsed):
    C.ensure_dir(LOG_DIR)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    mission_id = str(payload.get("mission_id") or "mission")
    safe_id = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in mission_id)
    path = os.path.join(LOG_DIR, "ue5_mission_render_%s_%s.json" % (safe_id, stamp))
    info = {
        "timestamp": stamp,
        "argv": list(sys.argv),
        "mission": payload.get("mission_id"),
        "pattern": payload.get("pattern"),
        "source_mission": payload.get("source_mission"),
        "out_dir": out_dir,
        "exposure": args.exposure,
        "sun_intensity_lux": args.sun,
        "limit": args.limit,
        "engine_version": C.engine_version(),
        "generated_actors": C.count_generated(),
        "width": C.WIDTH,
        "height": C.HEIGHT,
        "fx": round(C.FX, 4),
        "fy": round(C.FY, 4),
        "train_frames": len(train_frames),
        "train": train_stats,
        "val_frames": len(val_frames),
        "val": val_stats,
        "elapsed_seconds": round(elapsed, 2),
    }
    C.write_json(path, info)
    return path


# ---------------------------------------------------------------------------- val views
def make_val_poses(mission_poses, count):
    """Held-out validation views: random campus poses at least 5 m / 4 m away from mission."""
    if count <= 0:
        return []
    candidates = C.generate_val_poses(max(count * 8, 40))
    mission_locs = [tuple(float(v) for v in pose["loc"]) for pose in mission_poses]
    picked = []
    for candidate in candidates:
        x, y, z = (float(candidate["loc"][0]), float(candidate["loc"][1]),
                   float(candidate["loc"][2]))
        too_close = False
        for mx, my, mz in mission_locs:
            if (x - mx) ** 2 + (y - my) ** 2 < 500.0 ** 2 and abs(z - mz) < 400.0:
                too_close = True
                break
        if too_close:
            continue
        pose = dict(candidate)
        pose["index"] = len(picked) + 1
        pose["timestamp"] = float(len(picked)) * 2.0
        pose["prefix"] = "val_"
        picked.append(pose)
        if len(picked) >= count:
            break
    C.log("val: picked %d/%d held-out views" % (len(picked), count))
    return picked


# ---------------------------------------------------------------------------------- main
def main():
    args = parse_args()
    started = time.time()
    out_dir = os.path.abspath(args.out)
    images_dir = os.path.join(out_dir, "images")
    val_dir = os.path.join(out_dir, "val")
    C.ensure_dir(images_dir)
    C.log("=== render_mission start argv=%s ===" % sys.argv)
    C.log("out_dir=%s" % out_dir)

    payload, poses = prepare_poses(args)
    camera_consistency_check(payload)

    world = C.ensure_scene(rebuild=args.rebuild, sun_intensity=args.sun)
    actors = C.count_generated()
    C.log("scene ready: %d generated actors" % actors)

    if not args.no_clean:
        removed = clean_pngs(images_dir)
        if removed:
            C.log("cleaned %d stale PNGs in %s" % (removed, images_dir))

    actor, component, render_target = C.create_capture_rig(world, exposure=args.exposure)
    try:
        train_frames, train_stats = render_poses(
            world, actor, component, render_target, poses, images_dir, "mission")
    finally:
        try:
            C.actor_subsystem().destroy_actor(actor)
        except Exception:
            pass

    meta = build_metadata(payload, poses, train_frames, train_stats, args)
    C.write_json(os.path.join(out_dir, "metadata.json"), meta)
    C.write_json(os.path.join(out_dir, "poses_mission.json"), payload)

    val_frames = []
    val_stats = {"frames": 0, "total_seconds": 0.0, "avg_frame_seconds": None}
    if args.val_frames > 0:
        val_poses = make_val_poses(poses, args.val_frames)
        if val_poses:
            val_images = os.path.join(val_dir, "images")
            if not args.no_clean:
                clean_pngs(val_images)
            actor, component, render_target = C.create_capture_rig(world, exposure=args.exposure)
            try:
                val_frames, val_stats = render_poses(
                    world, actor, component, render_target, val_poses, val_images, "val")
            finally:
                try:
                    C.actor_subsystem().destroy_actor(actor)
                except Exception:
                    pass
            val_meta = build_metadata(payload, val_poses, val_frames, val_stats, args,
                                      images_root="val/images")
            val_meta["dataset"] = DATASET_VAL
            val_meta["mission"]["view_set"] = "held_out_validation"
            C.write_json(os.path.join(val_dir, "metadata_val.json"), val_meta)

    elapsed = time.time() - started
    log_path = write_run_summary(args, payload, train_frames, train_stats, val_frames,
                                 val_stats, out_dir, elapsed)
    C.log("wrote run summary %s" % log_path)
    C.log("SUMMARY " + json.dumps({
        "mode": "mission",
        "mission_id": payload.get("mission_id"),
        "frames": len(train_frames),
        "val_frames": len(val_frames),
        "avg_frame_seconds": train_stats.get("avg_frame_seconds"),
        "elapsed_seconds": round(elapsed, 2),
        "generated_actors": actors,
        "out_dir": out_dir,
        "metadata": os.path.join(out_dir, "metadata.json"),
    }))
    C.log("DONE elapsed=%.1fs" % elapsed)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        C.log_err("EXCEPTION in render_mission:\n" + traceback.format_exc())
        raise
