#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_mission.py -- UE5 in-editor renderer: Mission JSON -> PNG + metadata.json.

Runs INSIDE UnrealEditor (bundled Python 3.11) through -ExecutePythonScript, normally
launched by llm_drone/ue5_mission/run_mission.ps1:

    UnrealEditor.exe capture/UE5Synth/UE5Synth.uproject ^
        -ExecutePythonScript="C:/UEW/dji_ue5_3dgs/llm_drone/ue5_mission/render_mission.py ^
                              --mission C:/UEW/.../sample_mission.json --out C:/UEW/.../mission"

Heavy lifting is reused read-only from the proven capture tool
(capture/scripts/synth_common.py): procedural campus scene + synchronous material compile,
SceneCapture2D rig (1600x1200, 82.1 deg diagonal FOV -> fx=fy=1148.343 @1600x1200) and the
RenderTarget PNG export.  Mission parsing / truth math / metadata generation come from
mission_io.py (shared with the host-side tool, so there is exactly one implementation).

Outputs:
    <out>/images/0001.png ...          one PNG per mission photo point (1600x1200)
    <out>/metadata.json                PROTOCOL.md 7.3 / shared/CONVENTIONS.md dataset
    <out>/poses_mission.json           full render plan (mission -> UE poses, traceability)
    llm_drone/logs/ue5-mission/run_<mission>_<ts>.json    run summary (evidence)

The editor quits by itself when the Python script returns (PythonScriptPlugin defers
QUIT_EDITOR, same behaviour as capture/run_capture.ps1).
"""

import argparse
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))              # llm_drone/ue5_mission
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))             # <repo>/dji_ue5_3dgs
CAPTURE_SCRIPTS = os.path.join(REPO_ROOT, "capture", "scripts")
for _path in (CAPTURE_SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import unreal  # noqa: E402
import synth_common as C  # noqa: E402  (capture tool, imported read-only)
import mission_io as M  # noqa: E402  (shared truth math + metadata)

DEFAULT_OUT = os.path.join(REPO_ROOT, "data", "synthetic", "mission")
LOG_DIR = os.path.join(REPO_ROOT, "llm_drone", "logs", "ue5-mission")

CAMERA_ABS_TOL = 5e-4
ORIGIN_ANGLE_TOL = 1e-7
ORIGIN_ALT_TOL = 1e-6


def parse_args():
    argv = list(sys.argv[1:]) if sys.argv else []
    parser = argparse.ArgumentParser(prog="render_mission.py")
    parser.add_argument("--mission", required=True, help="mission JSON (spec v1 or orchestrator demo)")
    parser.add_argument("--out", default=DEFAULT_OUT, help="output dataset root")
    parser.add_argument("--exposure", type=float, default=0.6, help="fixed exposure (as capture)")
    parser.add_argument("--sun", type=float, default=22.0, help="sun light intensity in lux")
    parser.add_argument("--limit", type=int, default=0, help="render only the first N photo points")
    parser.add_argument("--no-clean", action="store_true", help="keep existing PNGs in <out>/images")
    parser.add_argument("--scene-detail", default="base", choices=["base", "v3"],
                        help="base = capture campus scene; v3 = campus + report/scene_v3 detail enhancement")
    parser.add_argument("--gpu-duty", type=float, default=1.0,
                        help="GPU duty cycle pacing (1.0 = no sleep; 0.25 = sleep 3x render time per frame)")
    parsed = parser.parse_args(argv)
    if not (0.0 < parsed.gpu_duty <= 1.0):
        parser.error("--gpu-duty must be in (0, 1]")
    return parsed


def resolve_path(path, want_file=False):
    """Resolve a user path against cwd, repo root and this script dir."""
    if not path:
        return path
    candidates = [path]
    if not os.path.isabs(path):
        candidates += [os.path.join(os.getcwd(), path), os.path.join(REPO_ROOT, path),
                       os.path.join(HERE, path)]
    for candidate in candidates:
        if (os.path.isfile(candidate) if want_file else os.path.isdir(candidate)):
            return os.path.abspath(candidate)
    return os.path.abspath(os.path.join(REPO_ROOT, path) if not os.path.isabs(path) else path)


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


def check_world_consistency(mission):
    """The rendered world is the capture/ campus: intrinsics + GPS origin must match exactly."""
    problems = []
    camera = mission["camera"]
    if int(camera["width"]) != int(C.WIDTH) or int(camera["height"]) != int(C.HEIGHT):
        problems.append("camera %dx%d != capture rig %dx%d"
                        % (camera["width"], camera["height"], C.WIDTH, C.HEIGHT))
    for key in ("fx", "fy", "cx", "cy"):
        mission_value = float(camera[key])
        capture_value = float(getattr(C, key.upper()))
        if abs(mission_value - capture_value) > CAMERA_ABS_TOL:
            problems.append("camera.%s=%.6f != capture %s=%.6f"
                            % (key, mission_value, key.upper(), capture_value))
    origin = mission["origin_wgs84"]
    for key in ("lat", "lon"):
        if abs(float(origin[key]) - float(C.ORIGIN_WGS84[key])) > ORIGIN_ANGLE_TOL:
            problems.append("origin_wgs84.%s=%.9f != capture origin %.9f"
                            % (key, float(origin[key]), C.ORIGIN_WGS84[key]))
    if abs(float(origin["alt"]) - float(C.ORIGIN_WGS84["alt"])) > ORIGIN_ALT_TOL:
        problems.append("origin_wgs84.alt=%.6f != capture origin %.6f"
                        % (float(origin["alt"]), C.ORIGIN_WGS84["alt"]))
    if problems:
        raise RuntimeError("mission does not match the capture rig / campus scene origin: "
                           + "; ".join(problems) + " (the UE scene is fixed at "
                           + "origin=%s, camera fx=%.4f)" % (C.ORIGIN_WGS84, C.FX))
    return {
        "intrinsics_match": True,
        "origin_match": True,
        "camera": {"width": C.WIDTH, "height": C.HEIGHT, "fx": round(C.FX, 4),
                   "fy": round(C.FY, 4), "cx": C.CX, "cy": C.CY,
                   "fov_horizontal_deg": round(C.FOV_H_DEG, 4)},
        "origin_wgs84": dict(C.ORIGIN_WGS84),
    }


def render_one(world, actor, component, render_target, pose, images_dir):
    render_pose = {
        "index": int(pose["index"]),
        "loc": pose["loc_cm"],
        "yaw": pose["yaw"],
        "pitch": pose["pitch"],
        "roll": pose["roll"],
        "prefix": "",
    }
    return C.render_pose(world, actor, component, render_target, render_pose, images_dir)


def apply_v3_post_process(component):
    """Match the report/scene_v3 flight look (bloom / vignette / grain / motion blur)."""
    try:
        pp = component.get_editor_property("post_process_settings")
    except Exception as exc:
        C.log_warn("v3 post process settings unavailable: %s" % exc)
        return
    settings = (
        ("override_bloom_intensity", True), ("bloom_intensity", 0.12),
        ("override_vignette_intensity", True), ("vignette_intensity", 0.22),
        ("override_film_grain_intensity", True), ("film_grain_intensity", 0.012),
        ("override_scene_fringe_intensity", True), ("scene_fringe_intensity", 0.0),
        ("override_motion_blur_amount", True), ("motion_blur_amount", 0.12),
    )
    for name, value in settings:
        try:
            pp.set_editor_property(name, value)
        except Exception:
            pass
    try:
        component.set_editor_property("post_process_settings", pp)
    except Exception as exc:
        C.log_warn("could not apply v3 post process settings: %s" % exc)


def main():
    args = parse_args()
    started = time.time()
    started_iso = M.now_iso()
    mission_path = resolve_path(args.mission, want_file=True)
    if not os.path.isfile(mission_path):
        raise FileNotFoundError("mission JSON not found: %s" % mission_path)
    out_dir = resolve_path(args.out)
    images_dir = os.path.join(out_dir, "images")
    C.log("=== render_mission start mission=%s out=%s ===" % (mission_path, out_dir))

    mission = M.load_mission(mission_path)
    for warning in mission.get("warnings", []):
        C.log_warn("mission warning: %s" % warning)
    C.log("mission %s: format=%s type=%s, %d waypoints, %d photo points"
          % (mission["mission_id"], mission.get("format"), mission["type"],
             len(mission["waypoints"]), len(mission["photo_waypoints"])))
    world_checks = check_world_consistency(mission)

    poses = M.build_render_plan(mission, limit=args.limit)
    C.log("render plan: %d frames, timestamps %.2f..%.2f s"
          % (len(poses), poses[0]["timestamp"], poses[-1]["timestamp"]))

    C.ensure_dir(images_dir)
    if not args.no_clean:
        removed = clean_pngs(images_dir)
        C.log("removed %d stale PNGs from %s" % (removed, images_dir))

    t0 = time.perf_counter()
    world = C.ensure_scene(rebuild=True, sun_intensity=float(args.sun))
    scene_seconds = time.perf_counter() - t0
    actors = C.count_generated()
    C.log("scene ready: %d actors in %.2fs (sun=%.1f lux)" % (actors, scene_seconds, args.sun))

    detail_seconds = 0.0
    if args.scene_detail == "v3":
        v3_dir = os.path.join(REPO_ROOT, "report", "scene_v3")
        if v3_dir not in sys.path:
            sys.path.insert(0, v3_dir)
        import scene_detail_v3 as D  # noqa: E402
        t_detail = time.perf_counter()
        D.enhance_scene(world)
        detail_seconds = time.perf_counter() - t_detail
        actors = C.count_generated()
        C.log("v3 scene detail applied: %.2fs, actors=%d" % (detail_seconds, actors))

    t0 = time.perf_counter()
    actor, component, render_target = C.create_capture_rig(world, exposure=float(args.exposure))
    rig_seconds = time.perf_counter() - t0
    if args.scene_detail == "v3":
        apply_v3_post_process(component)

    per_frame = []
    c2w_diffs = []
    failures = []
    t0 = time.perf_counter()
    try:
        for i, pose in enumerate(poses):
            ok, elapsed, file_name, full_path = render_one(
                world, actor, component, render_target, pose, images_dir)
            if args.gpu_duty < 1.0 and elapsed > 0:
                # keep the *time-averaged* GPU utilisation at/below args.gpu_duty
                time.sleep(elapsed * (1.0 / args.gpu_duty - 1.0))
            c2w_capture = C.c2w_from_pose(pose["loc_cm"], pose["yaw"], pose["pitch"], pose["roll"])
            c2w_diff = max(abs(float(a) - float(b))
                           for a, b in zip(pose["c2w"], c2w_capture))
            c2w_diffs.append(c2w_diff)
            if not ok:
                failures.append(file_name)
                C.log_warn("frame %s failed (PNG missing or < 1 KB)" % file_name)
            per_frame.append({
                "index": pose["index"],
                "waypoint_index": pose["waypoint_index"],
                "file": file_name,
                "seconds": round(elapsed, 4),
                "c2w_max_diff_vs_capture": c2w_diff,
            })
            C.log("rendered %d/%d %s (%.3fs, wp=%d, c2w_diff=%.2e)"
                  % (i + 1, len(poses), file_name, elapsed, pose["waypoint_index"], c2w_diff))
    finally:
        try:
            C.actor_subsystem().destroy_actor(actor)
        except Exception as exc:
            C.log_warn("could not destroy capture actor: %s" % exc)
    render_seconds = time.perf_counter() - t0
    avg_frame = render_seconds / len(poses) if poses else 0.0
    if failures:
        raise RuntimeError("%d frame(s) were not written: %s" % (len(failures), failures))

    generator_extra = {
        "ue_version": C.engine_version(),
        "ue_python": sys.version.split()[0],
        "scene_actors": actors,
        "scene_seed": C.SCENE_SEED,
        "exposure": float(args.exposure),
        "sun_intensity_lux": float(args.sun),
        "scene_detail": args.scene_detail,
        "gpu_duty": float(args.gpu_duty),
        "render": {
            "scene_build_seconds": round(scene_seconds, 3),
            "scene_detail_seconds": round(detail_seconds, 3),
            "create_rig_seconds": round(rig_seconds, 3),
            "render_seconds": round(render_seconds, 3),
            "avg_frame_seconds": round(avg_frame, 4),
            "n_frames": len(poses),
        },
        "c2w_cross_check_max_abs_diff_vs_capture": max(c2w_diffs) if c2w_diffs else None,
        "started_at": started_iso,
        "finished_at": M.now_iso(),
        "world_consistency": world_checks,
    }
    metadata = M.build_metadata(mission, poses, generator_extra=generator_extra)
    metadata_path = os.path.join(out_dir, "metadata.json")
    M.write_json(metadata_path, metadata)
    M.write_json(os.path.join(out_dir, "poses_mission.json"), M.plan_summary(mission, poses))
    C.log("wrote %s (%d frames)" % (metadata_path, len(metadata["frames"])))

    summary = {
        "status": "ok",
        "generated_at": M.now_iso(),
        "mission_file": mission_path,
        "mission_id": mission["mission_id"],
        "source_format": mission.get("format"),
        "out_dir": out_dir,
        "images_dir": images_dir,
        "metadata": metadata_path,
        "n_frames": len(poses),
        "width": C.WIDTH,
        "height": C.HEIGHT,
        "fx": round(C.FX, 4),
        "fy": round(C.FY, 4),
        "fov_horizontal_deg": round(C.FOV_H_DEG, 4),
        "exposure": float(args.exposure),
        "sun_intensity_lux": float(args.sun),
        "scene_detail": args.scene_detail,
        "gpu_duty": float(args.gpu_duty),
        "scene_actors": actors,
        "timing": {
            "script_seconds": round(time.time() - started, 3),
            "scene_build_seconds": round(scene_seconds, 3),
            "create_rig_seconds": round(rig_seconds, 3),
            "render_seconds": round(render_seconds, 3),
            "avg_frame_seconds": round(avg_frame, 4),
        },
        "per_frame": per_frame,
        "c2w_max_diff_vs_capture": max(c2w_diffs) if c2w_diffs else None,
        "engine_version": C.engine_version(),
        "ue_python": sys.version.split()[0],
        "world_consistency": world_checks,
        "started_at": started_iso,
        "argv": list(sys.argv),
    }
    C.ensure_dir(LOG_DIR)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_info_path = os.path.join(LOG_DIR, "run_%s_%s.json"
                                 % (str(mission["mission_id"]).replace(" ", "_"), stamp))
    M.write_json(run_info_path, summary)
    C.log("wrote run summary %s" % run_info_path)
    C.log("SUMMARY " + json.dumps({
        "mode": "mission",
        "mission_id": mission["mission_id"],
        "frames": len(poses),
        "width": C.WIDTH,
        "height": C.HEIGHT,
        "avg_frame_seconds": round(avg_frame, 4),
        "elapsed_seconds": round(time.time() - started, 2),
        "scene_actors": actors,
        "out_dir": out_dir,
        "metadata": metadata_path,
    }, ensure_ascii=False))
    C.log("DONE elapsed=%.1fs" % (time.time() - started))
    return 0


if __name__ == "__main__":
    try:
        main()
    except Exception:
        C.log_err("EXCEPTION in render_mission:\n" + traceback.format_exc())
        raise
