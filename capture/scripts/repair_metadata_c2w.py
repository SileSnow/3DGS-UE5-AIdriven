"""
repair_metadata_c2w.py -- offline fix of the c2w rotation blocks in the exported metadata.

The rendered PNGs are correct (they were captured with the real UE camera transforms), but
an early version of synth_common.rotator_axes() produced a non-orthonormal 'up' axis, so the
c2w matrices written to metadata.json / metadata_val.json had a wrong rotation part.  This
tool recomputes c2w from the (unchanged, correct) translation plus gimbal yaw/pitch and
rewrites the metadata files in place, keeping the original files as *.bak.json.

    python capture/scripts/repair_metadata_c2w.py

Run with the SYSTEM python (only the stdlib is needed).
"""

import json
import math
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CAPTURE_ROOT = os.path.dirname(HERE)
PROJECT_ROOT = os.path.dirname(CAPTURE_ROOT)
DATA_ROOT = os.path.join(PROJECT_ROOT, "data", "synthetic")


def fix_axes(yaw_deg, pitch_deg):
    y = math.radians(yaw_deg)
    p = math.radians(pitch_deg)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    forward = (cp * cy, cp * sy, sp)
    right = (-sy, cy, 0.0)
    up = (-sp * cy, -sp * sy, cp)
    return forward, right, up


def c2w_from_frame(frame):
    t = [float(frame["c2w"][3]), float(frame["c2w"][7]), float(frame["c2w"][11])]
    gimbal = frame.get("gimbal_deg", {})
    forward, right, up = fix_axes(float(gimbal.get("yaw", 0.0)), float(gimbal.get("pitch", 0.0)))
    return [
        forward[0], right[0], up[0], t[0],
        forward[1], right[1], up[1], t[1],
        forward[2], right[2], up[2], t[2],
        0.0, 0.0, 0.0, 1.0,
    ]


def process(meta_path):
    with open(meta_path, "r", encoding="utf-8") as handle:
        meta = json.load(handle)
    frames = meta.get("frames", [])
    changed = 0
    max_delta = 0.0
    for frame in frames:
        old = [float(v) for v in frame["c2w"]]
        new = c2w_from_frame(frame)
        delta = max(abs(old[i] - new[i]) for i in range(16))
        max_delta = max(max_delta, delta)
        if delta > 1e-9:
            frame["c2w"] = new
            changed += 1
    if changed:
        backup = meta_path + ".bak.json"
        if not os.path.isfile(backup):
            shutil.copyfile(meta_path, backup)
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(meta, handle, indent=2, ensure_ascii=False)
    print("%s: %d/%d frames updated, max element delta %.6f" % (
        os.path.basename(meta_path), changed, len(frames), max_delta))
    return changed


def main():
    total = 0
    train = os.path.join(DATA_ROOT, "capture", "metadata.json")
    val = os.path.join(DATA_ROOT, "val", "metadata_val.json")
    for path in (train, val):
        if os.path.isfile(path):
            total += process(path)
        else:
            print("missing", path)
    print("done, %d frames repaired" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
