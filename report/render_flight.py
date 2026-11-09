# -*- coding: utf-8 -*-
"""render_flight.py -- UE5 in-editor cinematic flight renderer (demo video asset).

Runs inside UnrealEditor via -ExecutePythonScript (see report/run_flight.ps1).
Builds the proven capture campus scene, flies a smooth Catmull-Rom camera path
around/over the campus (safe altitudes 30-43 m), renders N frames (1600x1200),
and writes report/flight_plan.json with per-frame pose + telemetry for the HUD.
"""
import json
import math
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))          # <repo>/report
REPO = os.path.dirname(HERE)                                # <repo>
CAPTURE_SCRIPTS = os.path.join(REPO, "capture", "scripts")
if CAPTURE_SCRIPTS not in sys.path:
    sys.path.insert(0, CAPTURE_SCRIPTS)

import unreal  # noqa: E402
import synth_common as C  # noqa: E402

OUT_DIR = os.path.join(REPO, "report", "flight_raw")
PLAN_PATH = os.path.join(REPO, "report", "flight_plan.json")
FRAMES = 540
FPS = 30

# 相机控制点（UE 厘米，场景半径约 45 m）
CTRL = [
    (-5200.0, -4800.0, 3000.0),
    (-1800.0, -5400.0, 3300.0),
    (1400.0, -4000.0, 3900.0),
    (2600.0, -900.0, 4300.0),
    (1600.0, 2400.0, 4200.0),
    (-900.0, 4100.0, 3900.0),
    (-3800.0, 2500.0, 3500.0),
]
# 每段的起止俯仰角（度）
PITCH_SEG = [(-14.0, -22.0), (-22.0, -32.0), (-32.0, -50.0),
             (-50.0, -42.0), (-42.0, -30.0), (-30.0, -18.0)]


def catmull_rom(points, u):
    n = len(points) - 1
    s = min(max(u, 0.0), 1.0) * n
    i = min(int(s), n - 1)
    t = s - i
    p0 = points[max(i - 1, 0)]
    p1 = points[i]
    p2 = points[i + 1]
    p3 = points[min(i + 2, n)]
    def cr(a, b, c, d):
        return 0.5 * ((2 * b) + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t * t
                      + (-a + 3 * b - 3 * c + d) * t * t * t)
    return (cr(p0[0], p1[0], p2[0], p3[0]),
            cr(p0[1], p1[1], p2[1], p3[1]),
            cr(p0[2], p1[2], p2[2], p3[2]))


def wrap_deg(a):
    while a > 180.0:
        a -= 360.0
    while a < -180.0:
        a += 360.0
    return a


def pitch_at(u):
    n = len(PITCH_SEG)
    s = min(max(u, 0.0), 1.0) * n
    i = min(int(s), n - 1)
    t = s - i
    a, b = PITCH_SEG[i]
    return a + (b - a) * t


def build_path():
    poses = []
    raw = []
    for k in range(FRAMES):
        u = k / float(FRAMES - 1)
        x, y, z = catmull_rom(CTRL, u)
        # 机头朝向 = 路径切线（前后差分）
        u2 = min(u + 0.004, 1.0)
        u1 = max(u - 0.004, 0.0)
        x1, y1, _ = catmull_rom(CTRL, u1)
        x2, y2, _ = catmull_rom(CTRL, u2)
        yaw = math.degrees(math.atan2(y2 - y1, x2 - x1))
        raw.append({"u": u, "loc": (x, y, z), "yaw": yaw, "pitch": pitch_at(u)})
    # 平滑坡度（bank）：用 12 帧窗口的航向变化
    for k, item in enumerate(raw):
        a = max(0, k - 6)
        b = min(FRAMES - 1, k + 6)
        dyaw = wrap_deg(raw[b]["yaw"] - raw[a]["yaw"])
        roll = max(-8.0, min(8.0, dyaw * 1.1))
        item["roll"] = round(roll, 2)
    # 速度（cm/s -> m/s）
    for k, item in enumerate(raw):
        if k == 0:
            d = math.dist(raw[0]["loc"], raw[1]["loc"])
        elif k == FRAMES - 1:
            d = math.dist(raw[-2]["loc"], raw[-1]["loc"])
        else:
            d = 0.5 * (math.dist(raw[k - 1]["loc"], raw[k]["loc"]) +
                       math.dist(raw[k]["loc"], raw[k + 1]["loc"]))
        item["speed_mps"] = round(d * FPS / 100.0, 2)
        item["gps"] = C.ue_to_wgs84(item["loc"])
        item["index"] = k + 1
        item["timestamp"] = k / float(FPS)
    return raw


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name in os.listdir(OUT_DIR):
        if name.lower().endswith(".png"):
            try:
                os.remove(os.path.join(OUT_DIR, name))
            except OSError:
                pass
    C.log("=== render_flight start frames=%d out=%s ===" % (FRAMES, OUT_DIR))
    poses = build_path()
    C.log("path built: %.1f m loop, speed %.1f-%.1f m/s, alt %.1f-%.1f m" % (
        sum(1 for _ in poses),
        min(p["speed_mps"] for p in poses), max(p["speed_mps"] for p in poses),
        min(p["loc"][2] for p in poses) / 100.0, max(p["loc"][2] for p in poses) / 100.0))

    t0 = time.perf_counter()
    world = C.ensure_scene(rebuild=True, sun_intensity=22.0)
    C.log("scene ready in %.2fs (%d actors)" % (time.perf_counter() - t0, C.count_generated()))
    actor, component, render_target = C.create_capture_rig(world, exposure=0.6)

    rendered = []
    t0 = time.perf_counter()
    for i, pose in enumerate(poses):
        rp = {"index": pose["index"], "loc": pose["loc"], "yaw": pose["yaw"],
              "pitch": pose["pitch"], "roll": pose["roll"], "prefix": "f"}
        ok, elapsed, file_name, full_path = C.render_pose(
            world, actor, component, render_target, rp, OUT_DIR)
        if not ok:
            C.log_warn("frame %s failed" % file_name)
        rendered.append({"file": file_name, "pose": pose})
        if (i + 1) % 30 == 0 or i == FRAMES - 1:
            C.log("rendered %d/%d (avg %.3fs/frame)" % (
                i + 1, FRAMES, (time.perf_counter() - t0) / (i + 1)))

    plan = {
        "schema": "dji_ue5_3dgs/flight_plan/v1",
        "frames": FRAMES, "fps": FPS,
        "width": C.WIDTH, "height": C.HEIGHT, "fx": round(float(C.FX), 4),
        "origin_wgs84": C.ORIGIN_WGS84,
        "scene": "UE5Synth campus (capture/UE5Synth), 805 actors",
        "poses": [{"index": p["index"], "loc_cm": list(p["loc"]), "yaw": round(p["yaw"], 3),
                   "pitch": round(p["pitch"], 3), "roll": p["roll"],
                   "speed_mps": p["speed_mps"], "gps": p["gps"],
                   "timestamp": round(p["timestamp"], 3)} for p in poses],
        "files": [r["file"] for r in rendered],
    }
    with open(PLAN_PATH, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=1)
    C.log("=== render_flight done %d frames, total %.1fs ===" % (FRAMES, time.perf_counter() - t0))
    C.log("plan -> %s" % PLAN_PATH)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        C.log_err(traceback.format_exc())
        raise
