"""
mission_io.py -- Mission JSON -> UE5 virtual-camera render plan / dataset metadata.

Pure standard library (no third-party packages, no unreal import).  Runs on the host with the
system Python AND is imported inside UnrealEditor by render_mission.py (UE bundled Python 3.11),
so the offline converter and the in-editor renderer share exactly the same truth math.

Accepted inputs
  1. llm_drone.mission/v1  -- the FROZEN spec format of llm_drone/spec/PROTOCOL.md 6,
     sample: llm_drone/spec/sample_mission.json.
  2. orchestrator demo missions -- the envelope written by llm_drone/orchestrator
     (llm_drone/demo/mission_<scenario>.json): {mission_id, pattern, origin_wgs84,
     defaults{alt_rel_m, gimbal_pitch, yaw, speed_mps}, waypoints[{lat, lon, alt_rel_m,
     gimbal{pitch,yaw,roll}, take_photo}]}; wrapper objects such as {"args": {...}},
     {"mission": {...}} and drone-sim mission records with photos[{gps, gimbal_deg}] are
     unwrapped automatically.  Demo-format waypoint gimbal yaw is DJI convention
     (0 = North, 90 = East, clockwise).

Truth math (identical to capture/scripts/synth_common.py):
  * 2  WGS84 <-> UE world (cm): UE +X = East, UE +Y = South (North = -Y), UE +Z = Up;
       north_m = (lat-lat0)*111320, east_m = (lon-lon0)*111320*cos(lat0)
  * 7.2 c2w: yaw_ue = heading_deg - 90, pitch_ue = gimbal_pitch_deg, roll = 0;
       4x4 row-major, columns = [forward, right, up] camera axes, translation = camera cm in UE
  * 7.3 metadata.json (dataset format of shared/CONVENTIONS.md)

CLI (offline self-check / dry run; no GPU, no Unreal):
    python llm_drone/ue5_mission/mission_io.py --mission llm_drone/spec/sample_mission.json \
        --out llm_drone/ue5_mission/results [--limit N] [--metadata <path>]

Written by the ue5-mission agent (task-6), 2026-11-08.
"""

import argparse
import datetime
import json
import math
import os
import sys

MISSION_SCHEMA = "llm_drone.mission/v1"
SUPPORTED_TYPES = ("grid", "orbit", "point")
SUPPORTED_ACTIONS = ("photo", "video_start", "video_stop", "none")
M_PER_DEG_LAT = 111320.0
UE_AXIS = "UE +X = East, UE +Y = South, UE +Z = Up (cm)"
DATASET_NAME = "synthetic_dji_mini4pro_mission_v1"

# Defaults mirrored from capture/scripts/synth_common.py (DJI Mini 4 Pro, 1600x1200).
DEFAULT_ORIGIN_WGS84 = {"lat": 39.9042, "lon": 116.4074, "alt": 43.0}
DEFAULT_CAMERA = {
    "model": "DJI Mini 4 Pro (simulated)",
    "width": 1600,
    "height": 1200,
    "fx": 1148.343,
    "fy": 1148.343,
    "cx": 800.0,
    "cy": 600.0,
    "fov_horizontal_deg": 69.726,
    "fov_vertical_deg": 55.18,
    "sensor_mm": {"width": 9.6, "height": 7.2, "diagonal": 12.0},
}
SENSOR_DIAG_MM = 12.0
FOV_DIAG_DEG = 82.1
FOCAL_MM = (SENSOR_DIAG_MM * 0.5) / math.tan(math.radians(FOV_DIAG_DEG * 0.5))
EQUIV_FOCAL_MM = 24.0

# Simplified stop_and_turn semantics (PROTOCOL.md 6): hover/settle before each photo.
SETTLE_S = 0.5

# Keys that may hold the waypoint list of an orchestrator demo mission / mission record.
WAYPOINT_LIST_KEYS = ("waypoints", "photo_points", "photoPoints", "photo_waypoints", "points",
                      "photos", "shots", "capture_points")
# Wrapper objects seen in tool-call logs / mission records.
WRAPPER_KEYS = ("args", "mission", "plan", "input")

_THIS = os.path.abspath(__file__)
HERE = os.path.dirname(_THIS)
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))          # <repo>/dji_ue5_3dgs
DEFAULT_RESULTS_DIR = os.path.join(HERE, "results")


class MissionError(ValueError):
    """Raised when a Mission JSON cannot be interpreted (schema / geometry problem)."""


# ----------------------------------------------------------------------------- utilities
def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path, payload):
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path


def _to_float(value, field, errors, fallback=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append("%s must be a number, got %r" % (field, value))
        return fallback


def _lookup(mapping, keys, default=None):
    """First present, non-None value among keys of a mapping."""
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def _as_float(value, default=None):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
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


def _norm_origin(raw, errors):
    origin = dict(DEFAULT_ORIGIN_WGS84)
    if raw is None:
        errors.append("origin_wgs84 is required")
        return origin
    if not isinstance(raw, dict):
        errors.append("origin_wgs84 must be an object")
        return origin
    for key in ("lat", "lon", "alt"):
        if key not in raw:
            errors.append("origin_wgs84.%s is required" % key)
            continue
        origin[key] = _to_float(raw[key], "origin_wgs84.%s" % key, errors, origin[key])
    if not (-90.0 <= origin["lat"] <= 90.0):
        errors.append("origin_wgs84.lat out of range: %r" % (origin["lat"],))
    if not (-180.0 <= origin["lon"] <= 180.0):
        errors.append("origin_wgs84.lon out of range: %r" % (origin["lon"],))
    if not (-500.0 <= origin["alt"] <= 10000.0):
        errors.append("origin_wgs84.alt out of range: %r" % (origin["alt"],))
    return origin


def _norm_camera(raw, errors):
    camera = json.loads(json.dumps(DEFAULT_CAMERA))       # deep copy of the defaults
    if raw is None:
        return camera
    if not isinstance(raw, dict):
        errors.append("camera must be an object")
        return camera
    if isinstance(raw.get("model"), str) and raw["model"]:
        camera["model"] = raw["model"]
    for key in ("width", "height"):
        if key in raw:
            value = _to_float(raw[key], "camera.%s" % key, errors, camera[key])
            if value is not None:
                camera[key] = int(round(value))
    for key in ("fx", "fy", "cx", "cy"):
        if key in raw:
            camera[key] = _to_float(raw[key], "camera.%s" % key, errors, camera[key])
    for key in ("fov_horizontal_deg", "fov_vertical_deg"):
        if key in raw:
            camera[key] = _to_float(raw[key], "camera.%s" % key, errors, camera[key])
    if isinstance(raw.get("sensor_mm"), dict):
        sensor = {"width": 9.6, "height": 7.2, "diagonal": 12.0}
        for key in sensor:
            if key in raw["sensor_mm"]:
                sensor[key] = _to_float(raw["sensor_mm"][key], "camera.sensor_mm.%s" % key,
                                        errors, sensor[key])
        camera["sensor_mm"] = sensor
    if camera["width"] <= 0 or camera["height"] <= 0:
        errors.append("camera.width/height must be positive, got %r x %r" % (
            camera["width"], camera["height"]))
    if camera["fx"] <= 0 or camera["fy"] <= 0:
        errors.append("camera.fx/fy must be positive")
    return camera


# ------------------------------------------------------------------- truth math (spec 2/7.2)
def wgs84_to_ue(lat, lon, alt_abs_m, origin=None):
    """WGS84 -> UE world cm (PROTOCOL.md 2). UE +X = East, +Y = South, +Z = Up."""
    origin = origin or DEFAULT_ORIGIN_WGS84
    lat0 = float(origin["lat"])
    lon0 = float(origin["lon"])
    alt0 = float(origin["alt"])
    north_m = (float(lat) - lat0) * M_PER_DEG_LAT
    east_m = (float(lon) - lon0) * M_PER_DEG_LAT * math.cos(math.radians(lat0))
    return (east_m * 100.0, -north_m * 100.0, (float(alt_abs_m) - alt0) * 100.0)


def ue_to_wgs84(loc_cm, origin=None):
    """UE world cm -> WGS84 (inverse of wgs84_to_ue; rounding identical to synth_common)."""
    origin = origin or DEFAULT_ORIGIN_WGS84
    lat0 = float(origin["lat"])
    lon0 = float(origin["lon"])
    alt0 = float(origin["alt"])
    east_m = float(loc_cm[0]) / 100.0
    north_m = -float(loc_cm[1]) / 100.0
    up_m = float(loc_cm[2]) / 100.0
    lat = lat0 + north_m / M_PER_DEG_LAT
    lon = lon0 + east_m / (M_PER_DEG_LAT * math.cos(math.radians(lat0)))
    return {"lat": round(lat, 9), "lon": round(lon, 9), "alt": round(alt0 + up_m, 4)}


def rotator_axes(yaw_deg, pitch_deg, roll_deg=0.0):
    """UE camera axes (forward, right, up) for a rotator with gimbal roll = 0.

    Identical formulas to capture/scripts/synth_common.py::rotator_axes (PROTOCOL.md 7.2):
        forward = ( cos(p)cos(y),  cos(p)sin(y),  sin(p))
        right   = (-sin(y),        cos(y),        0     )
        up      = (-sin(p)cos(y), -sin(p)sin(y),  cos(p))
    The three vectors are orthonormal (verified by validate_output.py, ||R R^T - I|| < 1e-6).
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
    """4x4 row-major c2w: columns = [forward, right, up], last column = translation cm."""
    forward, right, up = rotator_axes(yaw_deg, pitch_deg, roll_deg)
    tx, ty, tz = float(loc_cm[0]), float(loc_cm[1]), float(loc_cm[2])
    return [
        float(forward[0]), float(right[0]), float(up[0]), tx,
        float(forward[1]), float(right[1]), float(up[1]), ty,
        float(forward[2]), float(right[2]), float(up[2]), tz,
        0.0, 0.0, 0.0, 1.0,
    ]


# ------------------------------------------------------- format 1: llm_drone.mission/v1
def _norm_flight(raw, mission_type, errors):
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        errors.append("flight must be an object")
        raw = {}
    flight = {
        "pattern": raw.get("pattern", mission_type),
        "altitude_m": _to_float(raw.get("altitude_m", 0.0), "flight.altitude_m", errors, 0.0),
        "speed_mps": _to_float(raw.get("speed_mps", 5.0), "flight.speed_mps", errors, 5.0),
        "gimbal_pitch_deg": _to_float(raw.get("gimbal_pitch_deg", -45.0),
                                      "flight.gimbal_pitch_deg", errors, -45.0),
        "heading_deg": _to_float(raw.get("heading_deg", 0.0), "flight.heading_deg", errors, 0.0),
        "overlap": raw.get("overlap"),
        "turn_mode": raw.get("turn_mode", "stop_and_turn"),
    }
    return flight


def _validate_v1(raw, source):
    warnings = []
    errors = []
    if raw.get("schema") != MISSION_SCHEMA:
        errors.append("schema must be %r, got %r" % (MISSION_SCHEMA, raw.get("schema")))
    mission_id = raw.get("mission_id")
    if not isinstance(mission_id, str) or not mission_id.strip():
        # PROTOCOL.md 6: the Agent assigns mission ids (m-0001 ...), so a plan-time mission
        # JSON is allowed to omit mission_id.  Fall back to plan_id for dataset traceability.
        fallback = raw.get("plan_id")
        if isinstance(fallback, str) and fallback.strip():
            mission_id = fallback.strip()
            warnings.append("mission_id missing (PROTOCOL 6: Agent assigns it); using plan_id "
                            "%r as the dataset mission_id" % mission_id)
        else:
            mission_id = "unnamed-mission"
            warnings.append("mission_id missing and no plan_id; using %r" % mission_id)
    mission_type = raw.get("type", "grid")
    if mission_type not in SUPPORTED_TYPES:
        errors.append("type must be one of %s, got %r" % (list(SUPPORTED_TYPES), mission_type))

    origin = _norm_origin(raw.get("origin_wgs84"), errors)
    camera = _norm_camera(raw.get("camera"), errors)
    flight = _norm_flight(raw.get("flight"), mission_type, errors)

    raw_waypoints = raw.get("waypoints")
    if not isinstance(raw_waypoints, list) or not raw_waypoints:
        errors.append("waypoints must be a non-empty list")
        raw_waypoints = []
    waypoints = []
    for position, raw_wp in enumerate(raw_waypoints):
        if not isinstance(raw_wp, dict):
            errors.append("waypoints[%d] must be an object" % position)
            continue
        label = "waypoints[%d]" % position
        index_value = _to_float(raw_wp.get("index", position), label + ".index", errors, position)
        index = int(round(index_value)) if index_value is not None else position
        lat = _to_float(raw_wp.get("lat"), label + ".lat", errors)
        lon = _to_float(raw_wp.get("lon"), label + ".lon", errors)
        alt_abs_raw = raw_wp.get("alt_abs_m")
        alt_rel_raw = raw_wp.get("alt_rel_m")
        alt_abs = None
        alt_rel = None
        if alt_abs_raw is None and alt_rel_raw is None:
            errors.append("%s needs alt_abs_m or alt_rel_m" % label)
        if alt_abs_raw is not None:
            alt_abs = _to_float(alt_abs_raw, label + ".alt_abs_m", errors)
        if alt_rel_raw is not None:
            alt_rel = _to_float(alt_rel_raw, label + ".alt_rel_m", errors)
        if alt_abs is not None and alt_rel is not None:
            delta = alt_abs - (origin["alt"] + alt_rel)
            if abs(delta) > 0.05:
                warnings.append("%s alt_abs_m=%.3f differs from origin.alt+alt_rel_m=%.3f by %.3f m"
                                % (label, alt_abs, origin["alt"] + alt_rel, delta))
        elif alt_abs is not None:
            alt_rel = alt_abs - origin["alt"]
        elif alt_rel is not None:
            alt_abs = origin["alt"] + alt_rel

        heading = _to_float(raw_wp.get("heading_deg", flight["heading_deg"]),
                            label + ".heading_deg", errors, flight["heading_deg"])
        gimbal_pitch = _to_float(raw_wp.get("gimbal_pitch_deg", flight["gimbal_pitch_deg"]),
                                 label + ".gimbal_pitch_deg", errors, flight["gimbal_pitch_deg"])
        speed = _to_float(raw_wp.get("speed_mps", flight["speed_mps"]), label + ".speed_mps",
                          errors, flight["speed_mps"])
        action = raw_wp.get("action", "none")
        if action not in SUPPORTED_ACTIONS:
            errors.append("%s action must be one of %s, got %r"
                          % (label, list(SUPPORTED_ACTIONS), action))

        if lat is not None and not (-90.0 <= lat <= 90.0):
            errors.append("%s lat out of range: %r" % (label, lat))
        if lon is not None and not (-180.0 <= lon <= 180.0):
            errors.append("%s lon out of range: %r" % (label, lon))
        if gimbal_pitch is not None and not (-90.0 <= gimbal_pitch <= 0.0):
            errors.append("%s gimbal_pitch_deg must be within [-90, 0], got %r"
                          % (label, gimbal_pitch))
        if speed is not None and speed <= 0.0:
            errors.append("%s speed_mps must be > 0, got %r" % (label, speed))
        if alt_rel is not None:
            if alt_rel < 0.0:
                errors.append("%s alt_rel_m must be >= 0, got %r" % (label, alt_rel))
            elif alt_rel > 120.0:
                warnings.append("%s alt_rel_m=%.1f m exceeds the 120 m safety limit"
                                % (label, alt_rel))
            if alt_rel > 500.0:
                errors.append("%s alt_rel_m=%.1f m is not a plausible mission altitude"
                              % (label, alt_rel))
        if speed is not None and speed > 15.0:
            warnings.append("%s speed_mps=%.1f exceeds the 15 m/s safety limit" % (label, speed))

        if None in (lat, lon, alt_abs, alt_rel, heading, gimbal_pitch, speed):
            continue
        waypoints.append({
            "index": index,
            "lat": lat,
            "lon": lon,
            "alt_abs_m": alt_abs,
            "alt_rel_m": alt_rel,
            "heading_deg": heading,
            "gimbal_pitch_deg": gimbal_pitch,
            "speed_mps": speed,
            "action": action,
            "yaw_source": "mission_heading_deg",
        })

    photo_waypoints = [wp for wp in waypoints if wp["action"] == "photo"]
    if not photo_waypoints:
        errors.append("mission has no waypoint with action='photo' -- nothing to render")

    declared = raw.get("photo_points")
    if declared is not None:
        if isinstance(declared, list):
            declared_indices = []
            for value in declared:
                number = _to_float(value, "photo_points[]", errors, -1)
                if number is not None:
                    declared_indices.append(int(round(number)))
            actual_indices = sorted(wp["index"] for wp in photo_waypoints)
            if sorted(declared_indices) != actual_indices:
                warnings.append("photo_points %s != action=photo waypoint indices %s"
                                % (sorted(declared_indices), actual_indices))
        else:
            errors.append("photo_points must be a list")

    if errors:
        raise MissionError("invalid mission (%s):\n  - %s" % (source, "\n  - ".join(errors)))

    scene = raw.get("scene")
    if not isinstance(scene, dict):
        scene = {"ground_alt_m": origin["alt"], "world": "UE_LHS_Zup_cm", "ue_axis": UE_AXIS}
    return {
        "schema": MISSION_SCHEMA,
        "format": MISSION_SCHEMA,
        "mission_id": mission_id,
        "plan_id": raw.get("plan_id"),
        "type": mission_type,
        "pattern": (raw.get("flight") or {}).get("pattern", mission_type),
        "created_at": raw.get("created_at"),
        "origin_wgs84": origin,
        "home": raw.get("home"),
        "scene": scene,
        "camera": camera,
        "flight": flight,
        "waypoints": waypoints,
        "photo_waypoints": photo_waypoints,
        "stats": raw.get("stats"),
        "warnings": warnings,
        "source": source,
    }


# ------------------------------------- format 2: orchestrator demo missions (llm_drone/demo)
def _waypoint_candidates(container):
    """Return (list, key) for the first list-of-dicts waypoint candidate, else (None, None)."""
    if not isinstance(container, dict):
        return None, None
    for key in WAYPOINT_LIST_KEYS:
        value = container.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value, key
    lat_value = _lookup(container, ("lat", "latitude"))
    if isinstance(lat_value, (int, float)):
        return [container], "<root>"
    return None, None


def _demo_envelope(raw, depth=0):
    """Locate the dict that holds the waypoint list (unwrap args/mission/plan wrappers)."""
    found, key = _waypoint_candidates(raw)
    if found is not None:
        return raw, found, key
    if depth >= 2:
        return None, None, None
    for wrapper in WRAPPER_KEYS:
        candidate = raw.get(wrapper)
        if isinstance(candidate, dict):
            inner, found_list, found_key = _demo_envelope(candidate, depth + 1)
            if inner is not None:
                return inner, found_list, found_key
    return None, None, None


def _wp_latlon(raw_wp):
    gps = raw_wp.get("gps") if isinstance(raw_wp.get("gps"), dict) else {}
    lat = _as_float(_lookup(raw_wp, ("lat", "latitude")))
    lon = _as_float(_lookup(raw_wp, ("lon", "lng", "longitude")))
    if lat is None:
        lat = _as_float(gps.get("lat"))
    if lon is None:
        lon = _as_float(gps.get("lon"))
    return lat, lon


def _infer_origin_from_photo_records(waypoint_list):
    """Derive origin_wgs84 from a drone-sim mission record (photo gps + pose_enu offsets).

    Mission records (llm_drone/demo/missions/<scenario>_m-001.json) store per-photo gps and
    pose_enu relative to the take-off point but no origin_wgs84.  The mapping is exact:
        north_m = (lat - lat0) * M_PER_DEG_LAT
        east_m  = (lon - lon0) * M_PER_DEG_LAT * cos(lat0)
        up_m    = alt_abs_m - alt0
    so the origin can be recovered from any one photo.
    """
    for raw_wp in waypoint_list:
        if not isinstance(raw_wp, dict):
            continue
        gps = raw_wp.get("gps") if isinstance(raw_wp.get("gps"), dict) else {}
        enu = raw_wp.get("pose_enu") if isinstance(raw_wp.get("pose_enu"), dict) else {}
        lat = _as_float(gps.get("lat"))
        lon = _as_float(gps.get("lon"))
        north = _as_float(enu.get("north_m"))
        east = _as_float(enu.get("east_m"))
        up = _as_float(enu.get("up_m"))
        alt_abs = _as_float(gps.get("alt_abs_m"))
        if alt_abs is None:
            alt_abs = _as_float(raw_wp.get("alt_abs_m"))
        if None in (lat, lon, north, east):
            continue
        lat0 = lat - north / M_PER_DEG_LAT
        lon0 = lon - east / (M_PER_DEG_LAT * math.cos(math.radians(lat0)))
        alt0 = DEFAULT_ORIGIN_WGS84["alt"]
        if alt_abs is not None and up is not None:
            alt0 = alt_abs - up
        return {"lat": lat0, "lon": lon0, "alt": alt0}
    return None


def _flight_direction_heading(waypoint_list, position):
    """Compass heading (deg, 0=N) of the flight direction at waypoint_list[position]."""
    def heading_between(first, second):
        alat, alon = _wp_latlon(first)
        blat, blon = _wp_latlon(second)
        if None in (alat, alon, blat, blon):
            return None
        north = (blat - alat) * M_PER_DEG_LAT
        east = (blon - alon) * M_PER_DEG_LAT * math.cos(math.radians(alat))
        if abs(north) < 1e-9 and abs(east) < 1e-9:
            return None
        return math.degrees(math.atan2(east, north))

    if position + 1 < len(waypoint_list):
        value = heading_between(waypoint_list[position], waypoint_list[position + 1])
        if value is not None:
            return value
    if position > 0:
        return heading_between(waypoint_list[position - 1], waypoint_list[position])
    return None


def _validate_demo(raw, source):
    warnings = []
    errors = []
    if not isinstance(raw, dict):
        raise MissionError("mission root must be a JSON object")
    envelope, raw_list, list_key = _demo_envelope(raw)
    if envelope is None:
        raise MissionError(
            "unrecognised mission JSON (%s): expected a %r mission or an orchestrator demo "
            "envelope with one of %s (optionally wrapped in %s)"
            % (source, MISSION_SCHEMA, list(WAYPOINT_LIST_KEYS), list(WRAPPER_KEYS)))

    origin_raw = envelope.get("origin_wgs84") or raw.get("origin_wgs84")
    if origin_raw is None:
        origin_raw = _infer_origin_from_photo_records(raw_list)
        if origin_raw is not None:
            warnings.append("origin_wgs84 missing; inferred from mission-record gps/pose_enu: "
                            "lat=%.7f lon=%.7f alt=%.2f"
                            % (origin_raw["lat"], origin_raw["lon"], origin_raw["alt"]))
    origin = _norm_origin(origin_raw, errors)
    mission_id = (envelope.get("mission_id") or raw.get("mission_id")
                  or envelope.get("plan_id") or "orchestrator-demo")
    pattern = str(envelope.get("pattern") or raw.get("pattern") or "grid")
    defaults = envelope.get("defaults")
    if not isinstance(defaults, dict):
        defaults = {}
    camera = _norm_camera(envelope.get("camera") or raw.get("camera"), errors)

    default_alt_rel = _as_float(_lookup(defaults, ("alt_rel_m", "relative_alt_m", "height_m",
                                                  "altitude_m", "alt_m")), 50.0)
    default_pitch = _as_float(_lookup(defaults, ("gimbal_pitch", "gimbal_pitch_deg", "pitch")),
                              -45.0)
    default_yaw = _as_float(_lookup(defaults, ("yaw", "yaw_deg", "heading_deg",
                                               "gimbal_yaw", "gimbal_yaw_deg")))
    default_speed = _as_float(_lookup(defaults, ("speed_mps", "speed")), 5.0)
    flight = {
        "pattern": pattern,
        "altitude_m": default_alt_rel,
        "speed_mps": default_speed,
        "gimbal_pitch_deg": default_pitch,
        "heading_deg": default_yaw if default_yaw is not None else 0.0,
        "overlap": envelope.get("overlap"),
        "turn_mode": envelope.get("turn_mode", "stop_and_turn"),
    }

    waypoints = []
    for position, raw_wp in enumerate(raw_list):
        if not isinstance(raw_wp, dict):
            errors.append("%s[%d] must be an object" % (list_key, position))
            continue
        label = "%s[%d]" % (list_key, position)
        gps_block = raw_wp.get("gps") if isinstance(raw_wp.get("gps"), dict) else {}
        gimbal = _lookup(raw_wp, ("gimbal", "gimbal_deg", "gimbal_attitude"))
        if not isinstance(gimbal, dict):
            gimbal = {}

        lat, lon = _wp_latlon(raw_wp)
        if lat is None or lon is None:
            errors.append("%s needs lat/lon" % label)
            continue
        alt_abs = _as_float(_lookup(raw_wp, ("alt_abs_m", "absolute_alt_m", "abs_alt_m")))
        alt_rel = _as_float(_lookup(raw_wp, ("alt_rel_m", "relative_alt_m", "altitude_rel_m",
                                             "height_m")))
        if alt_abs is None:
            alt_abs = _as_float(gps_block.get("alt_abs_m"))
        if alt_rel is None:
            alt_rel = _as_float(gps_block.get("alt_rel_m"))
        if alt_abs is None and alt_rel is None:
            alt_rel = default_alt_rel
        if alt_abs is None:
            alt_abs = origin["alt"] + alt_rel
        if alt_rel is None:
            alt_rel = alt_abs - origin["alt"]

        dji_yaw = _as_float(_lookup(gimbal, ("yaw", "yaw_deg")))
        if dji_yaw is None:
            dji_yaw = _as_float(_lookup(raw_wp, ("gimbal_yaw_deg", "gimbal_yaw", "yaw_deg",
                                                 "heading_deg", "heading", "camera_yaw_deg")))
        yaw_source = "explicit"
        if dji_yaw is None:
            dji_yaw = default_yaw
            yaw_source = "defaults"
        if dji_yaw is None:
            dji_yaw = _flight_direction_heading(raw_list, position)
            yaw_source = "flight_direction" if dji_yaw is not None else "unknown"
        if dji_yaw is None:
            dji_yaw = 0.0
            warnings.append("%s: no gimbal yaw and no flight direction -> 0 deg" % label)
        pitch = _as_float(_lookup(gimbal, ("pitch", "pitch_deg")))
        if pitch is None:
            pitch = _as_float(_lookup(raw_wp, ("gimbal_pitch_deg", "gimbal_pitch")))
        if pitch is None:
            pitch = default_pitch
            warnings.append("%s: no gimbal pitch -> default %.1f deg" % (label, pitch))
        roll = _as_float(_lookup(gimbal, ("roll", "roll_deg")))
        if roll is None:
            roll = _as_float(_lookup(raw_wp, ("gimbal_roll_deg", "roll_deg"))) or 0.0
        speed = _as_float(_lookup(raw_wp, ("speed_mps", "speed")))
        if speed is None:
            speed = default_speed
        take_photo = _as_bool(_lookup(raw_wp, ("take_photo", "take_photos", "photo",
                                               "capture", "capture_photo")), True)
        action = "photo" if take_photo else "none"

        dji_yaw = float(dji_yaw) % 360.0
        if not (-90.0 <= pitch <= 0.0):
            errors.append("%s gimbal pitch must be within [-90, 0], got %r" % (label, pitch))
        if roll != 0.0:
            warnings.append("%s gimbal roll=%r ignored (the capture rig renders roll=0)"
                            % (label, roll))
        if speed <= 0.0:
            errors.append("%s speed_mps must be > 0, got %r" % (label, speed))
        if alt_rel < 0.0:
            errors.append("%s alt_rel_m must be >= 0, got %r" % (label, alt_rel))
        if alt_rel > 120.0:
            warnings.append("%s alt_rel_m=%.1f m exceeds the 120 m safety limit"
                            % (label, alt_rel))
        if alt_rel > 500.0:
            errors.append("%s alt_rel_m=%.1f m is not a plausible mission altitude"
                          % (label, alt_rel))
        if speed > 15.0:
            warnings.append("%s speed_mps=%.1f exceeds the 15 m/s safety limit" % (label, speed))
        waypoints.append({
            "index": position,
            "lat": float(lat),
            "lon": float(lon),
            "alt_abs_m": float(alt_abs),
            "alt_rel_m": float(alt_rel),
            "heading_deg": dji_yaw,
            "gimbal_pitch_deg": float(pitch),
            "speed_mps": float(speed),
            "action": action,
            "yaw_source": yaw_source,
        })

    photo_waypoints = [wp for wp in waypoints if wp["action"] == "photo"]
    if not photo_waypoints:
        errors.append("demo mission has no photo waypoint -- nothing to render")
    if errors:
        raise MissionError("invalid mission (%s):\n  - %s" % (source, "\n  - ".join(errors)))

    scene = envelope.get("scene")
    if not isinstance(scene, dict):
        scene = {"ground_alt_m": origin["alt"], "world": "UE_LHS_Zup_cm", "ue_axis": UE_AXIS}
    return {
        "schema": "(orchestrator-demo)",
        "format": "orchestrator-demo",
        "mission_id": str(mission_id),
        "plan_id": envelope.get("plan_id") or raw.get("plan_id"),
        "type": pattern,
        "pattern": pattern,
        "created_at": envelope.get("created_at") or raw.get("created_at"),
        "origin_wgs84": origin,
        "home": envelope.get("home"),
        "scene": scene,
        "camera": camera,
        "flight": flight,
        "waypoints": waypoints,
        "photo_waypoints": photo_waypoints,
        "stats": {"n_waypoints": len(waypoints), "n_photos": len(photo_waypoints)},
        "warnings": warnings,
        "source": source,
    }


def validate_mission(raw, source="<memory>"):
    """Validate + normalise a mission (v1 spec or orchestrator demo envelope)."""
    if not isinstance(raw, dict):
        raise MissionError("mission root must be a JSON object")
    if raw.get("schema") == MISSION_SCHEMA:
        return _validate_v1(raw, source)
    return _validate_demo(raw, source)


def load_mission(path):
    """Read + validate a mission JSON file. Raises MissionError on any problem."""
    absolute = os.path.abspath(path)
    if not os.path.isfile(absolute):
        raise MissionError("mission file not found: %s" % absolute)
    with open(absolute, "r", encoding="utf-8") as handle:
        try:
            raw = json.load(handle)
        except json.JSONDecodeError as exc:
            raise MissionError("invalid JSON in %s: %s" % (absolute, exc))
    mission = validate_mission(raw, source=absolute)
    try:
        mission["source_relpath"] = os.path.relpath(absolute, REPO_ROOT).replace(os.sep, "/")
    except ValueError:
        mission["source_relpath"] = absolute
    return mission


# --------------------------------------------------------------- mission -> render plan
def build_render_plan(mission, limit=0):
    """One render pose per photo waypoint (PROTOCOL.md 6/7.2/7.3).

    Pose keys: index (1-based frame/file number), waypoint_index, action_index, loc_cm,
    yaw (UE yaw = heading_deg - 90), pitch (gimbal pitch), roll (always 0), heading_deg,
    gimbal_pitch_deg, alt_rel_m, timestamp (simulated mission seconds), gps (simulated
    WGS84), c2w (16 floats row-major), prefix (''), yaw_source.
    """
    photo_waypoints = mission.get("photo_waypoints") or [
        wp for wp in mission["waypoints"] if wp["action"] == "photo"]
    if not photo_waypoints:
        raise MissionError("mission has no photo waypoints to render")
    if limit and limit > 0:
        photo_waypoints = photo_waypoints[:int(limit)]

    origin = mission["origin_wgs84"]
    default_speed = float(mission["flight"].get("speed_mps") or 5.0)
    poses = []
    timestamp = 0.0
    previous_ue = None
    for photo_index, waypoint in enumerate(photo_waypoints):
        loc_cm = wgs84_to_ue(waypoint["lat"], waypoint["lon"], waypoint["alt_abs_m"], origin)
        if previous_ue is not None:
            distance_m = math.sqrt((loc_cm[0] - previous_ue[0]) ** 2 +
                                   (loc_cm[1] - previous_ue[1]) ** 2 +
                                   (loc_cm[2] - previous_ue[2]) ** 2) / 100.0
            speed = float(waypoint["speed_mps"] or default_speed)
            timestamp += distance_m / max(speed, 1e-6) + SETTLE_S
        yaw_ue = float(waypoint["heading_deg"]) - 90.0
        pitch_ue = float(waypoint["gimbal_pitch_deg"])
        poses.append({
            "index": photo_index + 1,
            "waypoint_index": int(waypoint["index"]),
            "action_index": photo_index,
            "loc_cm": [float(loc_cm[0]), float(loc_cm[1]), float(loc_cm[2])],
            "yaw": yaw_ue,
            "pitch": pitch_ue,
            "roll": 0.0,
            "heading_deg": float(waypoint["heading_deg"]),
            "gimbal_pitch_deg": float(waypoint["gimbal_pitch_deg"]),
            "alt_rel_m": float(waypoint["alt_rel_m"]),
            "timestamp": round(timestamp, 3),
            "gps": ue_to_wgs84(loc_cm, origin),
            "c2w": c2w_from_pose(loc_cm, yaw_ue, pitch_ue, 0.0),
            "prefix": "",
            "yaw_source": waypoint.get("yaw_source", "mission_heading_deg"),
        })
        previous_ue = loc_cm
    return poses


def frame_entry(pose, mission):
    """PROTOCOL.md 7.3 frame entry for one rendered pose."""
    return {
        "file": "images/%04d.png" % int(pose["index"]),
        "c2w": [float(value) for value in pose["c2w"]],
        "gps": dict(pose["gps"]),
        "gimbal_deg": {
            "yaw": round(float(pose["yaw"]), 4),
            "pitch": round(float(pose["pitch"]), 4),
            "roll": round(float(pose["roll"]), 4),
        },
        "timestamp": float(pose["timestamp"]),
        "waypoint_index": int(pose["waypoint_index"]),
        "dji_gimbal_yaw_deg": round((float(pose["yaw"]) + 90.0) % 360.0, 4),
        "yaw_source": pose.get("yaw_source", "mission_heading_deg"),
        "mission": {
            "mission_id": mission["mission_id"],
            "waypoint_index": int(pose["waypoint_index"]),
            "heading_deg": round(float(pose["heading_deg"]), 4),
            "gimbal_pitch_deg": round(float(pose["gimbal_pitch_deg"]), 4),
            "alt_rel_m": round(float(pose["alt_rel_m"]), 4),
        },
    }


def _camera_outputs(camera):
    width = int(camera["width"])
    height = int(camera["height"])
    fx = float(camera["fx"])
    fy = float(camera["fy"])
    fov_h = camera.get("fov_horizontal_deg")
    fov_v = camera.get("fov_vertical_deg")
    if fov_h is None:
        fov_h = math.degrees(2.0 * math.atan(width / (2.0 * fx)))
    if fov_v is None:
        fov_v = math.degrees(2.0 * math.atan(height / (2.0 * fy)))
    sensor = camera.get("sensor_mm") or {"width": 9.6, "height": 7.2, "diagonal": 12.0}
    diagonal = float(sensor.get("diagonal")
                     or math.hypot(float(sensor["width"]), float(sensor["height"])))
    focal_mm = (diagonal * 0.5) / math.tan(math.radians(FOV_DIAG_DEG * 0.5))
    return {
        "fov_horizontal_deg": round(float(fov_h), 4),
        "fov_vertical_deg": round(float(fov_v), 4),
        "sensor_mm": sensor,
        "focal_mm": round(focal_mm, 4),
    }


NOTES = (
    "UE5.8 SceneCapture2D render of a drone mission (llm_drone.mission/v1 or an "
    "llm_drone/orchestrator demo mission). c2w is 4x4 row-major, columns = camera axes "
    "[forward, right, up] in UE world (cm); camera axes follow UE (+X forward, +Y right, "
    "+Z up, left-handed world); translation is the camera centre in UE cm. GPS is simulated "
    "from the UE coordinates with UE +X = East, UE +Y = South (North = -Y), UE +Z = Up "
    "(see PROTOCOL.md 2). gimbal_deg.yaw is the UE camera yaw (heading_deg - 90 where "
    "heading_deg is the DJI compass heading); dji_gimbal_yaw_deg is the same yaw in DJI "
    "convention (0 = North, clockwise). gimbal_deg.pitch is the DJI-style gimbal pitch "
    "(-90 = straight down). timestamps are simulated mission seconds (cruise at the waypoint "
    "speed plus a 0.5 s hover/settle per photo point). fx=fy=1148.343 px comes from the DJI "
    "Mini 4 Pro 82.1 deg diagonal FOV on a 1/1.3 inch 4:3 sensor (9.6x7.2 mm), identical to "
    "the capture dataset."
)


def build_metadata(mission, poses, generator_extra=None):
    """metadata.json per PROTOCOL.md 7.3 / shared/CONVENTIONS.md (dataset contract)."""
    camera = mission["camera"]
    outputs = _camera_outputs(camera)
    frames = [frame_entry(pose, mission) for pose in poses]
    generator = {
        "tool": "llm_drone/ue5_mission/render_mission.py",
        "truth_math": "llm_drone/ue5_mission/mission_io.py (same formulas as capture/scripts/synth_common.py)",
        "capture_rig": "capture/scripts/synth_common.py::create_capture_rig/render_pose (reused read-only)",
        "scene": "capture/scripts/synth_common.py::build_scene procedural campus, seed 20261108",
        "ue_version": "unknown",
        "rendered_at": now_iso(),
        "frame_count": len(frames),
    }
    if generator_extra:
        generator.update(generator_extra)
    mission_block = {
        "mission_id": mission["mission_id"],
        "plan_id": mission.get("plan_id"),
        "type": mission["type"],
        "pattern": mission.get("pattern"),
        "source_format": mission.get("format"),
        "created_at": mission.get("created_at"),
        "source_file": mission.get("source_relpath") or mission.get("source"),
        "n_waypoints": len(mission["waypoints"]),
        "n_photos": len(frames),
        "photo_waypoint_indices": [int(pose["waypoint_index"]) for pose in poses],
        "flight": dict(mission["flight"]),
        "scene": mission.get("scene"),
    }
    metadata = {
        "dataset": DATASET_NAME,
        "camera_model": camera.get("model", DEFAULT_CAMERA["model"]),
        "width": int(camera["width"]),
        "height": int(camera["height"]),
        "fx": round(float(camera["fx"]), 4),
        "fy": round(float(camera["fy"]), 4),
        "cx": round(float(camera["cx"]), 4),
        "cy": round(float(camera["cy"]), 4),
        "coord_system": "UE_LHS_Zup_cm",
        "origin_wgs84": dict(mission["origin_wgs84"]),
        "sensor_mm": outputs["sensor_mm"],
        "focal_mm": outputs["focal_mm"],
        "equivalent_focal_mm": EQUIV_FOCAL_MM,
        "fov_deg": {
            "diagonal": FOV_DIAG_DEG,
            "horizontal": outputs["fov_horizontal_deg"],
            "vertical": outputs["fov_vertical_deg"],
        },
        "units": "cm / degrees",
        "generator": generator,
        "mission": mission_block,
        "validation": {"warnings": list(mission.get("warnings", []))},
        "frames": frames,
        "notes": NOTES,
    }
    return metadata


def plan_summary(mission, poses):
    """Compact human/agent-readable summary of the render plan (poses_mission.json)."""
    locations = [pose["loc_cm"] for pose in poses]
    bounds = {
        "min_cm": [round(min(loc[axis] for loc in locations), 3) for axis in range(3)],
        "max_cm": [round(max(loc[axis] for loc in locations), 3) for axis in range(3)],
    }
    return {
        "generated_at": now_iso(),
        "mission_id": mission["mission_id"],
        "mission_type": mission["type"],
        "source_format": mission.get("format"),
        "source_file": mission.get("source_relpath") or mission.get("source"),
        "origin_wgs84": dict(mission["origin_wgs84"]),
        "camera": {
            "width": mission["camera"]["width"],
            "height": mission["camera"]["height"],
            "fx": mission["camera"]["fx"],
            "fy": mission["camera"]["fy"],
            "cx": mission["camera"]["cx"],
            "cy": mission["camera"]["cy"],
        },
        "n_waypoints": len(mission["waypoints"]),
        "n_photo_waypoints": len(mission["photo_waypoints"]),
        "n_render_frames": len(poses),
        "timestamps": {
            "first_s": poses[0]["timestamp"] if poses else None,
            "last_s": poses[-1]["timestamp"] if poses else None,
        },
        "bounds_ue_cm": bounds,
        "poses": [
            {
                "frame": pose["index"],
                "file": "images/%04d.png" % int(pose["index"]),
                "waypoint_index": pose["waypoint_index"],
                "loc_cm": [round(value, 6) for value in pose["loc_cm"]],
                "yaw_ue": round(pose["yaw"], 4),
                "pitch_ue": round(pose["pitch"], 4),
                "heading_deg": round(pose["heading_deg"], 4),
                "gimbal_pitch_deg": round(pose["gimbal_pitch_deg"], 4),
                "timestamp": pose["timestamp"],
                "gps": pose["gps"],
                "c2w": pose["c2w"],
                "yaw_source": pose.get("yaw_source"),
            }
            for pose in poses
        ],
        "warnings": list(mission.get("warnings", [])),
    }


# ------------------------------------------------------------------------------------ CLI
def default_results_dir():
    return DEFAULT_RESULTS_DIR


def _resolve_input(path, base):
    if os.path.isabs(path):
        return os.path.normpath(path)
    candidate = os.path.normpath(os.path.join(base, path))
    if os.path.exists(candidate):
        return candidate
    return os.path.normpath(os.path.join(os.getcwd(), path))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="mission_io.py",
        description="Mission JSON -> UE5 render plan / dataset metadata (offline dry run).")
    parser.add_argument("--mission", required=True,
                        help="mission JSON (llm_drone.mission/v1 or orchestrator demo envelope)")
    parser.add_argument("--out", default=DEFAULT_RESULTS_DIR,
                        help="directory for mission_plan.json (default: llm_drone/ue5_mission/results)")
    parser.add_argument("--limit", type=int, default=0,
                        help="only the first N photo points (0 = all)")
    parser.add_argument("--metadata", default=None,
                        help="optional: also write a dry-run metadata.json to this path")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    mission_path = _resolve_input(args.mission, REPO_ROOT)
    out_dir = _resolve_input(args.out, REPO_ROOT)
    mission = load_mission(mission_path)
    poses = build_render_plan(mission, limit=args.limit)
    summary = plan_summary(mission, poses)
    write_json(os.path.join(out_dir, "mission_plan.json"), summary)

    if args.metadata:
        metadata_path = _resolve_input(args.metadata, REPO_ROOT)
        write_json(metadata_path, build_metadata(mission, poses))
        if not args.quiet:
            print("wrote dry-run metadata: %s" % metadata_path)

    if not args.quiet:
        print("mission    : %s (%s, format=%s)" % (
            mission["mission_id"], mission["type"], mission.get("format")))
        print("source     : %s" % mission_path)
        print("origin     : %s" % mission["origin_wgs84"])
        print("waypoints  : %d (%d photo points)" % (
            len(mission["waypoints"]), len(mission["photo_waypoints"])))
        print("render plan: %d frames, timestamps %.1f..%.1f s" % (
            len(poses), poses[0]["timestamp"], poses[-1]["timestamp"]))
        print("bounds     : %s .. %s (UE cm)" % (summary["bounds_ue_cm"]["min_cm"],
                                                 summary["bounds_ue_cm"]["max_cm"]))
        for pose in poses:
            print("  %04d wp=%-3d loc=(%9.2f,%9.2f,%9.2f) yaw=%7.2f pitch=%6.1f t=%7.2f "
                  "gps=(%.9f,%.9f,%.2f)" % (
                      pose["index"], pose["waypoint_index"], pose["loc_cm"][0],
                      pose["loc_cm"][1], pose["loc_cm"][2], pose["yaw"], pose["pitch"],
                      pose["timestamp"], pose["gps"]["lat"], pose["gps"]["lon"],
                      pose["gps"]["alt"]))
        for warning in mission.get("warnings", []):
            print("WARNING:", warning)
        print("wrote plan:", os.path.join(out_dir, "mission_plan.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
