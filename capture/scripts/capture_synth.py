"""
capture_synth.py -- main entry point of the UE5.8 synthetic DJI-Mini aerial capture tool.

Invoked from UnrealEditor via:
    UnrealEditor.exe UE5Synth.uproject -ExecutePythonScript="capture_synth.py --mode probe --rebuild"

Modes:
    build   rebuild the procedural campus scene and save the map, then quit
    probe   render a few calibration / composition test frames into capture/probe/
    sample  render a small evenly-spaced sample of the flight plan (default 30 train + 10 val)
    full    render the full flight plan (175 train + 15 val)

The editor exits automatically when the script returns (PythonScriptPlugin behaviour).
"""

import argparse
import json
import os
import sys
import time
import traceback

_THIS = os.path.abspath(__file__)
_SCRIPTS = os.path.dirname(_THIS)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import unreal  # noqa: E402
import synth_common as C  # noqa: E402


def parse_args():
    argv = list(sys.argv[1:]) if sys.argv else []
    parser = argparse.ArgumentParser(prog="capture_synth.py")
    parser.add_argument("--mode", default="sample", choices=["build", "probe", "calib", "sample", "full"])
    parser.add_argument("--train-frames", type=int, default=0)
    parser.add_argument("--val-frames", type=int, default=-1)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--exposure", type=float, default=0.6)
    parser.add_argument("--sun", type=float, default=30.0)
    return parser.parse_args(argv)


def evenly_spaced(items, count):
    if count <= 0 or count >= len(items):
        return list(items)
    step = len(items) / float(count)
    return [items[min(len(items) - 1, int(i * step))] for i in range(count)]


def renumber(poses):
    out = []
    for i, pose in enumerate(poses):
        new_pose = dict(pose)
        new_pose["index"] = i + 1
        new_pose["timestamp"] = float(i * 2.0)
        out.append(new_pose)
    return out


def write_run_info(args, payload):
    C.ensure_dir(C.LOG_DIR)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(C.LOG_DIR, "run_%s_%s.json" % (args.mode, stamp))
    info = {
        "timestamp": stamp,
        "mode": args.mode,
        "argv": list(sys.argv),
        "exposure": args.exposure,
        "sun_intensity": args.sun,
        "width": C.WIDTH,
        "height": C.HEIGHT,
        "fx": round(C.FX, 4),
        "fy": round(C.FY, 4),
        "fov_h_deg": round(C.FOV_H_DEG, 4),
        "fov_v_deg": round(C.FOV_V_DEG, 4),
        "engine_version": C.engine_version(),
        "generated_actors": C.count_generated(),
        "flight": C.overlap_stats(),
    }
    info.update(payload)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(info, handle, indent=2, ensure_ascii=False)
    C.log("wrote run info %s" % path)


def _find_light_component(world, label):
    for actor in C.actor_subsystem().get_all_level_actors():
        try:
            if actor.get_actor_label() == label:
                comps = actor.get_components_by_class(unreal.DirectionalLightComponent)
                if comps:
                    return comps[0]
        except Exception:
            continue
    return None


def _pp_apply(comp, spec):
    """Apply a named post-process exposure strategy to the scene capture component."""
    pp = comp.get_editor_property("post_process_settings")

    def sp(name, value):
        try:
            pp.set_editor_property(name, value)
        except Exception as exc:
            C.log_warn("probe pp '%s' failed: %s" % (name, exc))

    # common deterministic settings
    sp("override_auto_exposure_bias", True)
    sp("auto_exposure_bias", float(spec.get("bias", 0.0)))
    sp("override_motion_blur_amount", True)
    sp("motion_blur_amount", 0.0)
    sp("override_bloom_intensity", True)
    sp("bloom_intensity", 0.0)
    sp("override_vignette_intensity", True)
    sp("vignette_intensity", 0.0)
    sp("override_depth_of_field_fstop", True)
    sp("depth_of_field_fstop", 1.7)
    sp("override_camera_iso", True)
    sp("camera_iso", 100.0)
    sp("override_camera_shutter_speed", True)
    sp("camera_shutter_speed", float(spec.get("shutter", 500.0)))
    sp("override_auto_exposure_apply_physical_camera_exposure", True)
    sp("auto_exposure_apply_physical_camera_exposure", bool(spec.get("physical", False)))
    method_name = spec.get("method", "default")
    if method_name == "default":
        sp("override_auto_exposure_method", False)
    else:
        sp("override_auto_exposure_method", True)
        sp("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL if method_name == "manual" else unreal.AutoExposureMethod.AEM_HISTOGRAM)
    if "minmax" in spec:
        sp("override_auto_exposure_min_brightness", True)
        sp("auto_exposure_min_brightness", float(spec["minmax"]))
        sp("override_auto_exposure_max_brightness", True)
        sp("auto_exposure_max_brightness", float(spec["minmax"]))
    comp.set_editor_property("post_process_settings", pp)
    try:
        comp.set_editor_property("post_process_blend_weight", 1.0)
    except Exception:
        pass


def run_probe(world, args):
    """Lighting / exposure calibration sweep (runs in ~10 s after the editor is up)."""
    probe_dir = os.path.join(C.CAPTURE_ROOT, "probe")
    C.ensure_dir(probe_dir)
    C.log("probe: scene actor count = %d" % C.count_generated())
    sun_component = _find_light_component(world, "SYNTH_Sun")
    C.log("probe: sun component found=%s" % (sun_component is not None))
    actor, component, render_target = C.create_capture_rig(world, exposure=args.exposure)
    pose = {
        "loc": (-1800.0, -4500.0, 4000.0),
        "yaw": 20.0,
        "pitch": -45.0,
        "index": 1,
        "timestamp": 0.0,
        "prefix": "",
    }
    results = []
    cases = []
    for sun in (15.0, 22.0, 30.0, 40.0, 55.0):
        cases.append(("sun%05.1f_default" % sun, sun, {"method": "default"}))
    for i, (name, sun, spec) in enumerate(cases):
        if sun_component is not None:
            try:
                sun_component.set_editor_property("intensity", float(sun))
            except Exception as exc:
                C.log_warn("set sun intensity failed: %s" % exc)
        _pp_apply(component, spec)
        probe_pose = dict(pose)
        probe_pose["index"] = i + 1
        probe_pose["prefix"] = "t_%s_" % name
        ok, elapsed, file_name, full_path = C.render_pose(world, actor, component, render_target,
                                                          probe_pose, probe_dir)
        results.append({"file": file_name, "sun": sun, "spec": spec, "ok": ok,
                        "seconds": round(elapsed, 3)})
        C.log("probe case %-34s sun=%-7.0f -> %s (%.3fs)" % (name, sun, file_name, elapsed))
    # composition check at the best-looking candidate scales (analysed offline)
    for i, (name, sun) in enumerate((("demo_a", 30.0), ("demo_b", 30.0), ("demo_c", 40.0))):
        if sun_component is not None:
            try:
                sun_component.set_editor_property("intensity", float(sun))
            except Exception:
                pass
        _pp_apply(component, {"method": "default"})
        demo_poses = (
            (0.0, -4600.0, 4000.0, 0.0, -45.0),
            (-4600.0, 0.0, 3800.0, 90.0, -50.0),
            (0.0, 4600.0, 4200.0, 180.0, -52.0),
        )
        loc_x, loc_y, loc_z, yaw, pitch = demo_poses[i % len(demo_poses)]
        probe_pose = {
            "loc": (loc_x, loc_y, loc_z),
            "yaw": yaw,
            "pitch": pitch,
            "index": i + 1,
            "timestamp": 0.0,
            "prefix": "%s_" % name,
        }
        ok, elapsed, file_name, full_path = C.render_pose(world, actor, component, render_target,
                                                          probe_pose, probe_dir)
        results.append({"file": file_name, "sun": sun, "spec": {"method": "default"}, "ok": ok,
                        "seconds": round(elapsed, 3)})
        C.log("probe %s sun=%.0f -> %s (%.3fs)" % (name, sun, file_name, elapsed))
    try:
        C.actor_subsystem().destroy_actor(actor)
    except Exception:
        pass
    write_run_info(args, {"probe": results})
    C.log("SUMMARY " + json.dumps({"mode": "probe", "cases": len(results)}))


def run_calib(world, args):
    """Render near-nadir frames over the calibration targets for the reprojection check."""
    validation_dir = os.path.join(C.CAPTURE_ROOT, "validation")
    C.ensure_dir(validation_dir)
    poses = C.generate_calib_poses()
    frames, stats = C.render_frames(world, poses, validation_dir, exposure=args.exposure,
                                    label="calib", metadata_prefix="")
    meta = C.base_metadata(len(frames))
    meta["dataset"] = "synthetic_dji_mini4pro_campus_v1_calib"
    meta["frames"] = frames
    C.write_json(os.path.join(validation_dir, "metadata_calib.json"), meta)
    markers = {"coordinate_system": "UE_LHS_Zup_cm", "markers": []}
    for i, (mx, my) in enumerate(C.CALIB_MARKERS):
        markers["markers"].append({
            "id": i,
            "ue_xyz_cm": [mx, my, C.CALIB_MARKER_BASE_Z_CM + C.CALIB_MARKER_SIZE_CM * 0.5],
            "size_cm": C.CALIB_MARKER_SIZE_CM,
        })
    C.write_json(os.path.join(validation_dir, "markers_calib.json"), markers)
    write_run_info(args, {"calib_frames": len(frames), "calib": stats,
                          "validation_dir": validation_dir})
    C.log("SUMMARY " + json.dumps({
        "mode": "calib",
        "frames": len(frames),
        "avg_frame_seconds": stats.get("avg_frame_seconds"),
        "validation_dir": validation_dir,
    }))


def run_dataset(world, args):
    started = time.time()
    if args.mode == "full":
        train_limit = args.train_frames if args.train_frames > 0 else 0
        val_count = args.val_frames if args.val_frames >= 0 else C.VAL_COUNT
    else:
        train_limit = args.train_frames if args.train_frames > 0 else 30
        val_count = args.val_frames if args.val_frames >= 0 else 10
    train_poses = C.generate_train_poses()
    if train_limit:
        train_poses = evenly_spaced(train_poses, train_limit)
    train_poses = renumber(train_poses)
    C.log("flight plan: %d train poses (of %d planned), %d val poses" % (
        len(train_poses), len(C.PASSES) * C.GRID_LINES * C.GRID_SHOTS, val_count))
    for stat in C.overlap_stats():
        C.log("pass yaw=%.0f pitch=%.0f alt=%.0fcm -> side_overlap=%.1f%% heading_overlap=%.1f%%" % (
            stat["yaw_deg"], stat["gimbal_pitch_deg"], stat["altitude_cm"],
            100.0 * (stat["side_overlap"] or 0.0), 100.0 * (stat["heading_overlap"] or 0.0)))

    t0 = time.time()
    frames, stats = C.render_frames(world, train_poses, C.TRAIN_IMAGES_DIR,
                                    exposure=args.exposure, label="train")
    train_seconds = time.time() - t0
    train_meta = C.base_metadata(len(frames))
    train_meta["frames"] = frames
    C.write_json(os.path.join(C.TRAIN_ROOT, "metadata.json"), train_meta)

    val_frames = []
    val_stats = {"frames": 0, "total_seconds": 0.0, "avg_frame_seconds": None}
    if val_count > 0:
        val_poses = renumber(C.generate_val_poses(val_count))
        t0 = time.time()
        val_frames, val_stats = C.render_frames(world, val_poses, C.VAL_IMAGES_DIR,
                                                exposure=args.exposure, label="val")
        val_seconds = time.time() - t0
        val_meta = C.base_metadata(len(val_frames))
        val_meta["dataset"] = "synthetic_dji_mini4pro_campus_v1_val"
        val_meta["frames"] = val_frames
        C.write_json(os.path.join(C.VAL_ROOT, "metadata_val.json"), val_meta)
    total = time.time() - started
    payload = {
        "train_frames": len(frames),
        "val_frames": len(val_frames),
        "train": stats,
        "val": val_stats,
        "train_seconds": round(train_seconds, 3),
        "total_seconds": round(total, 3),
        "train_metadata": os.path.join(C.TRAIN_ROOT, "metadata.json"),
        "val_metadata": os.path.join(C.VAL_ROOT, "metadata_val.json"),
    }
    write_run_info(args, payload)
    C.log("SUMMARY " + json.dumps({
        "mode": args.mode,
        "train_frames": len(frames),
        "val_frames": len(val_frames),
        "total_seconds": round(total, 2),
        "avg_frame_seconds": stats.get("avg_frame_seconds"),
        "width": C.WIDTH,
        "height": C.HEIGHT,
        "fx": round(C.FX, 3),
        "engine": C.engine_version(),
    }))


def main():
    args = parse_args()
    started = time.time()
    C.log("=== capture_synth start mode=%s argv=%s ===" % (args.mode, sys.argv))
    world = C.ensure_scene(rebuild=args.rebuild or args.mode == "build", sun_intensity=args.sun)
    if args.mode == "build":
        write_run_info(args, {"generated_actors": C.count_generated()})
        C.log("SUMMARY " + json.dumps({
            "mode": "build",
            "generated_actors": C.count_generated(),
            "seconds": round(time.time() - started, 2),
        }))
    elif args.mode == "probe":
        run_probe(world, args)
    elif args.mode == "calib":
        run_calib(world, args)
    else:
        run_dataset(world, args)
    C.log("DONE elapsed=%.1fs" % (time.time() - started))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        C.log_err("EXCEPTION in capture_synth:\n" + traceback.format_exc())
        raise