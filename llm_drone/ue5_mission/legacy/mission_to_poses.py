#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mission_to_poses.py -- Convert a drone mission JSON into UE5 virtual-camera poses.

Pure standard library (no third-party deps, no unreal import), so it runs both:
  * on the host with system Python (planning / dry-run / self-check), and
  * inside UnrealEditor's bundled Python 3.11 when imported by render_mission.py.

Coordinate mapping (identical to capture/scripts/synth_common.py / shared/CONVENTIONS.md):
  * UE world : left-handed, +X forward (East), +Y right (South), +Z up, units = cm.
  * WGS84    : fixed local origin 39.9042 / 116.4074 / 43 m; +X = East, +Y = South, +Z = Up.
  * Gimbal   : DJI convention -- yaw is clockwise from North (0=N, 90=E), pitch is negative
               when looking down.  UE actor yaw = DJI yaw - 90 deg; pitch/roll pass through.
  * c2w      : 4x4 row-major, columns = camera axes [forward, right, up] in UE world (cm).

Mission JSON accepted by mission_to_poses (all keys except waypoint lat/lon optional; the
parser is deliberately tolerant about aliases -- see missions/MISSION_SCHEMA.md):

    {
      "mission_id": "m-001",
      "pattern": "grid",
      "origin_wgs84": {"lat": 39.9042, "lon": 116.4074, "alt": 43.0},
      "defaults": {"alt_rel_m": 40, "gimbal_pitch": -45, "yaw": 90, "photo_interval_s": 2.0},
      "waypoints": [
        {"lat": 39.9042, "lon": 116.4074, "alt_rel_m": 40,
         "gimbal": {"pitch": -45, "yaw": 90}, "take_photo": true},
        ...
      ]
    }

CLI
---
    # mission -> poses JSON (dry run on the host, no UE)
    python mission_to_poses.py --mission ../demo/mission_grid_campus.json --out poses.json

    # generate a bundled sample grid mission (6 lines x 6 shots = 36 photos)
    python mission_to_poses.py --make-grid --out missions/mission_grid_36.json ^
        --lines 6 --shots 6 --area-half-m 40 --alt-m 40 --pitch -45 --yaw 90

    # quick summary of a mission (no file written)
    python mission_to_poses.py --mission X.json --summary
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

# ------------------------------------------------------------------ constants (kept in sync
# with capture/scripts/synth_common.py; do not change one without the other)
M_PER_DEG_LAT = 111320.0
ORIGIN_WGS84 = {"lat": 39.9042, "lon": 116.4074, "alt": 43.0}

SENSOR_W_MM = 9.6
SENSOR_H_MM = 7.2
SENSOR_DIAG_MM = math.hypot(SENSOR_W_MM, SENSOR_H_MM)
FOV_DIAG_DEG = 82.1
FOCAL_MM = (SENSOR_DIAG_MM * 0.5) / math.tan(math.radians(FOV_DIAG_DEG * 0.5))
WIDTH = 1600
HEIGHT = 1200
FOV_H_DEG = math.degrees(2.0 * math.atan(SENSOR_W_MM * 0.5 / FOCAL_MM))
FOV_V_DEG = math.degrees(2.0 * math.atan(SENSOR_H_MM * 0.5 / FOCAL_MM))
FX = FOCAL_MM / SENSOR_W_MM * WIDTH
FY = FOCAL_MM / SENSOR_H_MM * HEIGHT
CX = WIDTH * 0.5
CY = HEIGHT * 0.5
EQUIV_FOCAL_MM = 24.0

WAYPOINT_KEYS = ("waypoints", "photo_points", "photoPoints", "points", "photos", "shots",
                 "capture_points", "photo_waypoints")


# --------------------------------------------------------------------------- small helpers
def _lookup(mapping, keys, default=None):
    """Return the first present, non-None value among keys in a mapping."""
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def _as_float(value, label, warnings=None, default=None):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        if warnings is not None:
            warnings.append("%s=%r is not numeric, ignored" % (label, value))
        return default


def _as_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "skip")
    return default


def normalize_origin(origin=None):
    merged = dict(ORIGIN_WGS84)
    if isinstance(origin, dict):
        for key in ("lat", "lon", "alt", "alt_m"):
            if key in origin and origin[key] is not None:
                target = "alt" if key == "alt_m" else key
                merged[target] = float(origin[key])
    elif isinstance(origin, (list, tuple)) and len(origin) >= 2:
        merged["lat"] = float(origin[0])
        merged["lon"] = float(origin[1])
        if len(origin) >= 3 and origin[2] is not None:
            merged["alt"] = float(origin[2])
    return merged


# --------------------------------------------------------------- WGS84 <-> UE world (cm)
def wgs84_to_ue(lat, lon, alt_abs_m, origin=None):
    """WGS84 (deg, deg, m) -> UE world (x east cm, y south cm, z up cm)."""
    org = normalize_origin(origin)
    north_m = (float(lat) - org["lat"]) * M_PER_DEG_LAT
    east_m = (float(lon) - org["lon"]) * M_PER_DEG_LAT * math.cos(math.radians(org["lat"]))
    up_m = float(alt_abs_m) - org["alt"]
    return (east_m * 100.0, -north_m * 100.0, up_m * 100.0)


def ue_to_wgs84(x_cm, y_cm, z_cm, origin=None):
    """UE world (cm) -> WGS84 dict {lat, lon, alt} (inverse of wgs84_to_ue)."""
    org = normalize_origin(origin)
    east_m = float(x_cm) / 100.0
    north_m = -float(y_cm) / 100.0
    up_m = float(z_cm) / 100.0
    lat = org["lat"] + north_m / M_PER_DEG_LAT
    lon = org["lon"] + east_m / (M_PER_DEG_LAT * math.cos(math.radians(org["lat"])))
    return {"lat": round(lat, 9), "lon": round(lon, 9), "alt": round(org["alt"] + up_m, 4)}


# ------------------------------------------------------------------ attitude conversions
def dji_yaw_to_ue_yaw(dji_yaw_deg):
    """DJI gimbal yaw (clockwise from North) -> UE actor yaw (0 = +X = East)."""
    return float(dji_yaw_deg) - 90.0


def ue_yaw_to_dji_yaw(ue_yaw_deg):
    """UE actor yaw -> DJI gimbal yaw (clockwise from North)."""
    return (float(ue_yaw_deg) + 90.0) % 360.0


def rotator_axes(yaw_deg, pitch_deg, roll_deg=0.0):
    """Camera axes (forward, right, up) in UE world for a UE rotator (roll = 0).

    Same formula as synth_common.rotator_axes (orthonormal by construction).
    """
    y = math.radians(float(yaw_deg))
    p = math.radians(float(pitch_deg))
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    forward = (cp * cy, cp * sy, sp)
    right = (-sy, cy, 0.0)
    up = (-sp * cy, -sp * sy, cp)
    return forward, right, up


def c2w_from_pose(loc_cm, yaw_deg, pitch_deg, roll_deg=0.0):
    """4x4 row-major camera-to-world matrix (columns = fwd/right/up, cm translation)."""
    forward, right, up = rotator_axes(yaw_deg, pitch_deg, roll_deg)
    tx, ty, tz = (float(loc_cm[0]), float(loc_cm[1]), float(loc_cm[2]))
    return [
        float(forward[0]), float(right[0]), float(up[0]), tx,
        float(forward[1]), float(right[1]), float(up[1]), ty,
        float(forward[2]), float(right[2]), float(up[2]), tz,
        0.0, 0.0, 0.0, 1.0,
    ]


def camera_spec():
    """DJI Mini 4 Pro simulated intrinsics (identical to capture/synth_common.py)."""
    return {
        "camera_model": "DJI Mini 4 Pro (simulated)",
        "width": WIDTH,
        "height": HEIGHT,
        "fx": round(FX, 4),
        "fy": round(FY, 4),
        "cx": round(CX, 4),
        "cy": round(CY, 4),
        "sensor_mm": {"width": SENSOR_W_MM, "height": SENSOR_H_MM,
                      "diagonal": round(SENSOR_DIAG_MM, 4)},
        "focal_mm": round(FOCAL_MM, 4),
        "equivalent_focal_mm": EQUIV_FOCAL_MM,
        "fov_deg": {"diagonal": FOV_DIAG_DEG, "horizontal": round(FOV_H_DEG, 4),
                    "vertical": round(FOV_V_DEG, 4)},
    }


# --------------------------------------------------------------------- mission parsing
def _waypoint_list(mission, warnings):
    """Extract the waypoint/photo list from the various accepted mission envelopes."""
    for key in WAYPOINT_KEYS:
        value = mission.get(key)
        if isinstance(value, list) and value:
            return value, key
    lat_value = _lookup(mission, ("lat", "latitude"))
    if isinstance(lat_value, (int, float)):
        return [mission], "<root>"
    warnings.append("no waypoint list found (looked for %s)" % ", ".join(WAYPOINT_KEYS))
    return [], None


def _default_heading(waypoints, index, warnings):
    """Flight-direction heading (clockwise from North) used when no explicit gimbal yaw."""
    if len(waypoints) < 2:
        return None

    def heading(a, b):
        alat = _lookup(a, ("lat", "latitude"))
        alon = _lookup(a, ("lon", "lng", "longitude"))
        blat = _lookup(b, ("lat", "latitude"))
        blon = _lookup(b, ("lon", "lng", "longitude"))
        if None in (alat, alon, blat, blon):
            return None
        dn = (float(blat) - float(alat)) * M_PER_DEG_LAT
        de = (float(blon) - float(alon)) * M_PER_DEG_LAT * math.cos(math.radians(float(alat)))
        if abs(dn) < 1e-9 and abs(de) < 1e-9:
            return None
        return math.degrees(math.atan2(de, dn))

    if index + 1 < len(waypoints):
        value = heading(waypoints[index], waypoints[index + 1])
        if value is not None:
            return value
    if index > 0:
        return heading(waypoints[index - 1], waypoints[index])
    return None


def _waypoint_alt_abs_m(wp, defaults, origin, warnings, label):
    """Resolve a waypoint altitude to absolute WGS84 metres."""
    org = normalize_origin(origin)
    alt_abs = _lookup(wp, ("alt_abs_m", "absolute_alt_m", "abs_alt_m", "alt_absolute_m"))
    if alt_abs is not None:
        return _as_float(alt_abs, label + ".alt_abs_m", warnings, org["alt"])
    alt_rel = _lookup(wp, ("alt_rel_m", "relative_alt_m", "altitude_rel_m", "height_m",
                           "relative_altitude_m"))
    if alt_rel is None:
        alt_rel = _lookup(defaults, ("alt_rel_m", "relative_alt_m", "altitude_rel_m",
                                     "height_m", "altitude_m", "alt_m", "alt"))
    if alt_rel is not None:
        return org["alt"] + _as_float(alt_rel, label + ".alt_rel_m", warnings, 40.0)
    # generic "alt"/"altitude" is interpreted as height above take-off (DJI MSDK style)
    alt_generic = _lookup(wp, ("alt_m", "altitude_m", "alt", "altitude", "height"))
    if alt_generic is not None:
        warnings.append("%s: generic altitude %r treated as metres above take-off"
                        % (label, alt_generic))
        return org["alt"] + _as_float(alt_generic, label + ".alt", warnings, 40.0)
    warnings.append("%s: no altitude -> default 40 m above take-off" % label)
    return org["alt"] + 40.0


def _resolve_gimbal(wp, defaults, waypoints, index, warnings, label):
    """Return (dji_yaw_deg, pitch_deg, roll_deg, yaw_source)."""
    gimbal = _lookup(wp, ("gimbal", "gimbal_deg", "gimbal_attitude", "camera_gimbal"))
    if not isinstance(gimbal, dict):
        gimbal = {}
    default_gimbal = _lookup(defaults, ("gimbal", "gimbal_deg"))
    if not isinstance(default_gimbal, dict):
        default_gimbal = {}

    def first(keys, *sources):
        for source in sources:
            value = _lookup(source, keys)
            if value is not None:
                return value
        return None

    pitch = first(("pitch", "pitch_deg", "gimbal_pitch", "gimbal_pitch_deg"),
                  gimbal, wp, default_gimbal, defaults)
    if pitch is None:
        pitch = -45.0
        warnings.append("%s: no gimbal pitch -> default -45 deg" % label)
    roll = first(("roll", "roll_deg"), gimbal, wp, default_gimbal, defaults) or 0.0
    yaw = first(("yaw", "yaw_deg", "gimbal_yaw", "gimbal_yaw_deg", "heading", "heading_deg",
                 "camera_yaw", "camera_yaw_deg"), gimbal, wp, default_gimbal, defaults)
    if yaw is not None:
        yaw_source = "explicit"
    else:
        yaw = _default_heading(waypoints, index, warnings)
        if yaw is not None:
            yaw_source = "flight_direction"
        else:
            yaw = 0.0
            yaw_source = "default_north"
            warnings.append("%s: no gimbal yaw and no flight direction -> default 0 deg (N)"
                            % label)
    return (_as_float(yaw, label + ".gimbal.yaw", warnings, 0.0),
            _as_float(pitch, label + ".gimbal.pitch", warnings, -45.0),
            _as_float(roll, label + ".gimbal.roll", warnings, 0.0),
            yaw_source)


def _unwrap_mission(mission):
    """Accept {"args": {...}} / {"mission": {...}} envelopes from the orchestrator log."""
    if not isinstance(mission, dict):
        return mission
    if any(isinstance(mission.get(key), list) and mission.get(key) for key in WAYPOINT_KEYS):
        return mission
    for key in ("args", "mission", "plan", "result", "data", "payload"):
        inner = mission.get(key)
        if isinstance(inner, dict):
            merged = dict(inner)
            for carry in ("mission_id", "id", "pattern", "origin_wgs84", "defaults",
                          "photo_interval_s"):
                if carry in mission and carry not in merged:
                    merged[carry] = mission[carry]
            return merged
    return mission


def mission_to_poses(mission, origin=None, limit=0, default_interval_s=2.0):
    """Mission JSON -> dict with UE camera poses + per-pose metadata (see module docstring).

    limit > 0 keeps that many evenly spaced photo points (small validation missions).
    """
    warnings = []
    if isinstance(mission, list):
        mission = {"waypoints": mission}
    if not isinstance(mission, dict):
        raise TypeError("mission must be a dict or list, got %s" % type(mission).__name__)
    mission = _unwrap_mission(mission)

    org = normalize_origin(mission.get("origin_wgs84") or mission.get("origin") or origin)
    defaults = mission.get("defaults") if isinstance(mission.get("defaults"), dict) else {}
    interval_default = _as_float(
        _lookup(mission, ("photo_interval_s", "interval_s")),
        "photo_interval_s", warnings,
        _as_float(_lookup(defaults, ("photo_interval_s", "interval_s")),
                  "defaults.photo_interval_s", warnings, default_interval_s))

    waypoints, list_key = _waypoint_list(mission, warnings)
    if not waypoints:
        raise ValueError("mission has no waypoints: %s" % warnings)

    photo_poses = []
    skipped = 0
    for index, wp in enumerate(waypoints):
        if not isinstance(wp, dict):
            warnings.append("waypoint[%d] is not an object, skipped" % index)
            skipped += 1
            continue
        label = "waypoint[%d]" % index
        take_photo = _as_bool(_lookup(wp, ("take_photo", "take_photo_flag", "photo", "shoot")), True)
        if not take_photo:
            skipped += 1
            continue

        # position: explicit UE override first, otherwise WGS84 -> UE
        ue_override = _lookup(wp, ("ue_loc_cm", "ue_xyz_cm", "ue_position_cm"))
        if isinstance(ue_override, (list, tuple)) and len(ue_override) >= 3:
            loc = tuple(float(v) for v in ue_override[:3])
            gps = ue_to_wgs84(*loc, origin=org)
        else:
            lat = _lookup(wp, ("lat", "latitude"))
            lon = _lookup(wp, ("lon", "lng", "longitude"))
            if lat is None or lon is None:
                warnings.append("%s has no lat/lon, skipped" % label)
                skipped += 1
                continue
            alt_abs_m = _waypoint_alt_abs_m(wp, defaults, org, warnings, label)
            loc = wgs84_to_ue(lat, lon, alt_abs_m, origin=org)
            gps = ue_to_wgs84(*loc, origin=org)

        dji_yaw, pitch, roll, yaw_source = _resolve_gimbal(
            wp, defaults, waypoints, index, warnings, label)
        # UE overrides for debugging / offline tests
        ue_yaw_deg = _lookup(wp, ("ue_yaw_deg",))
        if ue_yaw_deg is not None:
            ue_yaw = _as_float(ue_yaw_deg, label + ".ue_yaw_deg", warnings, 0.0)
            dji_yaw = ue_yaw_to_dji_yaw(ue_yaw)
            yaw_source = "ue_override"
        else:
            ue_yaw = dji_yaw_to_ue_yaw(dji_yaw)
        ue_pitch = _lookup(wp, ("ue_pitch_deg",))
        if ue_pitch is not None:
            pitch = _as_float(ue_pitch, label + ".ue_pitch_deg", warnings, pitch)

        timestamp = _lookup(wp, ("timestamp", "t_rel_s", "time_s", "time"))
        if timestamp is None:
            timestamp = float(len(photo_poses)) * interval_default
        else:
            timestamp = _as_float(timestamp, label + ".timestamp", warnings,
                                  float(len(photo_poses)) * interval_default)

        photo_index = len(photo_poses) + 1
        entry = {
            "index": photo_index,
            "waypoint_index": index,
            "loc": [round(float(loc[0]), 4), round(float(loc[1]), 4), round(float(loc[2]), 4)],
            "yaw": round(float(ue_yaw), 6),
            "pitch": round(float(pitch), 6),
            "roll": round(float(roll), 6),
            "gimbal_deg": {"yaw": round(float(ue_yaw), 6), "pitch": round(float(pitch), 6),
                           "roll": round(float(roll), 6)},
            "dji_gimbal_yaw_deg": round(float(dji_yaw) % 360.0, 6),
            "yaw_source": yaw_source,
            "gps": gps,
            "mission_gps": {"lat": _lookup(wp, ("lat", "latitude")),
                            "lon": _lookup(wp, ("lon", "lng", "longitude"))},
            "timestamp": round(float(timestamp), 4),
            "take_photo": True,
        }
        # compute the preview c2w from the *rounded* values so it matches bit-for-bit what
        # render_mission.py computes inside the editor (same formula, same inputs).
        entry["c2w"] = c2w_from_pose(entry["loc"], entry["yaw"], entry["pitch"], entry["roll"])
        photo_poses.append(entry)

    if limit and 0 < int(limit) < len(photo_poses):
        total = len(photo_poses)
        step = total / float(limit)
        picked = [photo_poses[min(total - 1, int(i * step))] for i in range(int(limit))]
        for i, pose in enumerate(picked):
            pose["index"] = i + 1
        warnings.append("limit=%d -> kept %d of %d photo points (evenly spaced)"
                        % (limit, len(picked), total))
        photo_poses = picked

    return {
        "schema": "ue5_mission_poses_v1",
        "generated_by": "llm_drone/ue5_mission/mission_to_poses.py",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mission_id": str(_lookup(mission, ("mission_id", "id", "name"), "mission")),
        "pattern": str(_lookup(mission, ("pattern", "mission_type", "type"), "")),
        "source_mission": mission.get("_source_path"),
        "origin_wgs84": org,
        "waypoint_list_key": list_key,
        "mapping": {
            "ue_x": "East", "ue_y": "South", "ue_z": "Up", "units": "cm",
            "ue_yaw": "DJI gimbal yaw - 90 deg (0 = +X = East)",
            "c2w_columns": "forward, right, up (UE camera axes), row-major 4x4",
        },
        "camera": camera_spec(),
        "stats": {
            "waypoints": len(waypoints),
            "photo_points": len(photo_poses),
            "skipped": skipped,
        },
        "warnings": warnings,
        "poses": photo_poses,
    }


# ------------------------------------------------------------------ sample mission builder
def make_grid_mission(mission_id="mission_grid", lines=4, shots=3, area_half_m=40.0,
                      alt_m=40.0, gimbal_pitch=-45.0, heading_deg=90.0, origin=None,
                      pattern="grid", speed_mps=6.0, photo_interval_s=2.0):
    """Build a lawn-mower grid photo mission JSON (lat/lon waypoints) around the origin."""
    org = normalize_origin(origin)
    lines = max(2, int(lines))
    shots = max(2, int(shots))
    area_half_cm = float(area_half_m) * 100.0
    along_spacing = 2.0 * area_half_cm / float(shots - 1)
    across_spacing = 2.0 * area_half_cm / float(lines - 1)
    heading_r = math.radians(float(heading_deg))
    ux, uy = math.sin(heading_r), -math.cos(heading_r)    # along-track (flight dir)
    vx, vy = -math.cos(heading_r), -math.sin(heading_r)   # across-track
    waypoints = []
    for li in range(lines):
        across = (li - (lines - 1) * 0.5) * across_spacing
        shot_order = range(shots) if li % 2 == 0 else range(shots - 1, -1, -1)
        for si in shot_order:
            along = (si - (shots - 1) * 0.5) * along_spacing
            x = ux * along + vx * across
            y = uy * along + vy * across
            gps = ue_to_wgs84(x, y, float(alt_m) * 100.0, origin=org)
            waypoints.append({
                "lat": gps["lat"],
                "lon": gps["lon"],
                "alt_rel_m": float(alt_m),
                "speed_mps": float(speed_mps),
                "gimbal": {"pitch": float(gimbal_pitch), "yaw": float(heading_deg), "roll": 0.0},
                "take_photo": True,
            })
    return {
        "mission_id": mission_id,
        "pattern": pattern,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "llm_drone/ue5_mission/mission_to_poses.py --make-grid",
        "origin_wgs84": org,
        "defaults": {"alt_rel_m": float(alt_m), "gimbal_pitch": float(gimbal_pitch),
                     "yaw": float(heading_deg), "speed_mps": float(speed_mps),
                     "photo_interval_s": float(photo_interval_s)},
        "waypoints": waypoints,
    }


# --------------------------------------------------------------------------------- CLI
def _read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path, payload):
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="mission_to_poses.py",
        description="Convert a drone mission JSON into UE5 virtual-camera poses "
                    "(or generate a sample grid mission).")
    parser.add_argument("--mission", "-m", help="input mission JSON")
    parser.add_argument("--out", "-o", help="output JSON path (poses, or mission with --make-grid)")
    parser.add_argument("--limit", type=int, default=0,
                        help="keep only N evenly spaced photo points (small validation runs)")
    parser.add_argument("--origin", nargs=3, type=float, metavar=("LAT", "LON", "ALT"),
                        help="override local WGS84 origin (default 39.9042 116.4074 43)")
    parser.add_argument("--make-grid", action="store_true", help="generate a grid mission JSON")
    parser.add_argument("--mission-id", default="mission_grid")
    parser.add_argument("--lines", type=int, default=4)
    parser.add_argument("--shots", type=int, default=3)
    parser.add_argument("--area-half-m", type=float, default=40.0)
    parser.add_argument("--alt-m", type=float, default=40.0)
    parser.add_argument("--pitch", type=float, default=-45.0)
    parser.add_argument("--yaw", type=float, default=90.0)
    parser.add_argument("--summary", action="store_true", help="print a summary only")
    args = parser.parse_args(argv)

    origin = None
    if args.origin:
        origin = {"lat": args.origin[0], "lon": args.origin[1], "alt": args.origin[2]}

    if args.make_grid:
        mission = make_grid_mission(mission_id=args.mission_id, lines=args.lines,
                                    shots=args.shots, area_half_m=args.area_half_m,
                                    alt_m=args.alt_m, gimbal_pitch=args.pitch,
                                    heading_deg=args.yaw, origin=origin)
        if args.out:
            _write_json(args.out, mission)
            print("wrote mission %s (%d waypoints) -> %s"
                  % (mission["mission_id"], len(mission["waypoints"]), args.out))
        else:
            print(json.dumps(mission, indent=2, ensure_ascii=False))
        return 0

    if not args.mission:
        parser.error("--mission is required (or use --make-grid)")
    mission = _read_json(args.mission)
    mission["_source_path"] = os.path.abspath(args.mission)
    payload = mission_to_poses(mission, origin=origin, limit=args.limit)

    if args.out:
        _write_json(args.out, payload)
    if args.summary or not args.out:
        stats = payload["stats"]
        print("mission_id      : %s" % payload["mission_id"])
        print("photo points    : %d (waypoints %d, skipped %d)"
              % (stats["photo_points"], stats["waypoints"], stats["skipped"]))
        print("origin          : %s" % payload["origin_wgs84"])
        for pose in payload["poses"][:5]:
            print("  #%03d ue=(%.1f, %.1f, %.1f) yaw=%.1f pitch=%.1f gps=(%.7f, %.7f, %.1f)"
                  % (pose["index"], pose["loc"][0], pose["loc"][1], pose["loc"][2],
                     pose["yaw"], pose["pitch"], pose["gps"]["lat"], pose["gps"]["lon"],
                     pose["gps"]["alt"]))
        if len(payload["poses"]) > 5:
            print("  ... (%d more)" % (len(payload["poses"]) - 5))
        for warning in payload["warnings"]:
            print("warning: %s" % warning)
    if args.out:
        print("wrote %d poses -> %s" % (len(payload["poses"]), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
