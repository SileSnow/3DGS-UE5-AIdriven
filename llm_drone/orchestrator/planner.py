# -*- coding: utf-8 -*-
"""确定性航拍规划器：自然语言参数 → spec §6 Mission JSON（grid / orbit / point）。

设计（PROTOCOL.md §6/§11/§12）：
  - 纯标准库、无副作用、不飞行；输出可被 Drone Agent（goto_waypoints.mission）与 UE5 渲染器直接消费。
  - grid 按「相机地面覆盖幅宽 × (1-重叠率)」算航线/拍照点间距，boustrophedon（往返条带）；
    幅宽用斜距投影 2*(H/sinθ)*tan(FOV/2)（θ=云台下视角），忽略斜视拉伸 → 保守（重叠更大、照片更多）。
  - orbit 圆周等分航点、heading 指向目标（等价「云台朝目标」）；point 定点重复拍摄 shots 张。
  - 原点/起飞点优先取 Agent telemetry.home，否则用 spec 默认 ORIGIN_WGS84。
  - 规划只给警告（限高/限速/围栏/禁飞区提示）；最终安全裁决在 Drone Agent 侧。
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
ORIGIN_WGS84 = {"lat": 39.9042, "lon": 116.4074, "alt": 43.0}
CAMERA = {
    "model": "DJI Mini 4 Pro (simulated)",
    "width": 1600, "height": 1200,
    "fx": 1148.343, "fy": 1148.343, "cx": 800.0, "cy": 600.0,
    "fov_horizontal_deg": 69.726, "fov_vertical_deg": 55.18,
    "sensor_mm": {"width": 9.6, "height": 7.2, "diagonal": 12},
}
SCENE = {"world": "UE_LHS_Zup_cm", "ue_axis": "UE +X = East, UE +Y = South, UE +Z = Up (cm)"}
M_PER_DEG_LAT = 111320.0
DEFAULT_SPEED_MPS = 5.0
DEFAULT_GIMBAL_PITCH = -45.0
DEFAULT_OVERLAP = 0.7
DEFAULT_RADIUS_M = 30.0
MAX_PHOTOS = 60
MIN_SPACING_M = 1.0
SAFETY_DEFAULT = {
    "max_alt_m": 120.0,
    "max_speed_mps": 15.0,
    "fence_center": {"lat": 39.9042, "lon": 116.4074},
    "fence_radius_m": 300.0,
    "no_fly_polygon": [
        {"lat": 39.9046, "lon": 116.4078}, {"lat": 39.9050, "lon": 116.4078},
        {"lat": 39.9050, "lon": 116.4082}, {"lat": 39.9046, "lon": 116.4082},
    ],
}


def now_iso():
    return datetime.now(CST).isoformat(timespec="seconds")


def m_per_deg_lon(lat):
    return M_PER_DEG_LAT * math.cos(math.radians(float(lat)))


def offset_latlon(lat, lon, dist_m, bearing_deg):
    br = math.radians(float(bearing_deg))
    north = float(dist_m) * math.cos(br)
    east = float(dist_m) * math.sin(br)
    return {"lat": round(lat + north / M_PER_DEG_LAT, 9),
            "lon": round(lon + east / m_per_deg_lon(lat), 9)}


def distance_between(a, b):
    dn = (b["lat"] - a["lat"]) * M_PER_DEG_LAT
    de = (b["lon"] - a["lon"]) * m_per_deg_lon((a["lat"] + b["lat"]) / 2.0)
    return math.hypot(dn, de)


def bearing_between(a, b):
    dn = (b["lat"] - a["lat"]) * M_PER_DEG_LAT
    de = (b["lon"] - a["lon"]) * m_per_deg_lon((a["lat"] + b["lat"]) / 2.0)
    return (math.degrees(math.atan2(de, dn)) + 360.0) % 360.0


def point_in_polygon(lat, lon, polygon):
    if not polygon or len(polygon) < 3:
        return False
    x, y = float(lon), float(lat)
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = float(polygon[i]["lon"]), float(polygon[i]["lat"])
        x2, y2 = float(polygon[(i + 1) % n]["lon"]), float(polygon[(i + 1) % n]["lat"])
        if (y1 > y) != (y2 > y):
            xin = (x2 - x1) * (y - y1) / (y2 - y1 + 1e-15) + x1
            if x < xin:
                inside = not inside
    return inside


def bbox_of(points):
    if not points:
        return {}
    lats = [p["lat"] for p in points]
    lons = [p["lon"] for p in points]
    return {"lat_min": round(min(lats), 9), "lat_max": round(max(lats), 9),
            "lon_min": round(min(lons), 9), "lon_max": round(max(lons), 9)}


def _path_length(waypoints):
    return sum(distance_between(a, b) for a, b in zip(waypoints, waypoints[1:]))


def ground_footprint(altitude_m, gimbal_pitch_deg):
    """地面覆盖幅宽（米）：along=沿航向，across=垂直航向；斜距投影、忽略斜视拉伸。"""
    alt = max(0.5, float(altitude_m))
    theta = max(5.0, min(89.9, abs(float(gimbal_pitch_deg))))
    slant = alt / math.sin(math.radians(theta))
    along = 2.0 * slant * math.tan(math.radians(CAMERA["fov_vertical_deg"] / 2.0))
    across = 2.0 * slant * math.tan(math.radians(CAMERA["fov_horizontal_deg"] / 2.0))
    return {"along_m": round(along, 3), "across_m": round(across, 3),
            "slant_m": round(slant, 3), "theta_deg": round(theta, 2)}


def home_from_telemetry(telemetry):
    tel = telemetry or {}
    home = tel.get("home") if isinstance(tel, dict) else None
    if isinstance(home, dict) and "lat" in home and "lon" in home:
        alt = home.get("alt_abs_m", home.get("alt", ORIGIN_WGS84["alt"]))
        return {"lat": float(home["lat"]), "lon": float(home["lon"]), "alt_abs_m": float(alt)}
    if isinstance(tel, dict) and "lat" in tel and "lon" in tel and tel.get("ok") is not False:
        alt = tel.get("alt_abs_m", ORIGIN_WGS84["alt"])
        return {"lat": float(tel["lat"]), "lon": float(tel["lon"]), "alt_abs_m": float(alt)}
    return {"lat": ORIGIN_WGS84["lat"], "lon": ORIGIN_WGS84["lon"], "alt_abs_m": ORIGIN_WGS84["alt"]}


def make_plan_id(pattern, params):
    canonical = json.dumps({"pattern": pattern, "params": params}, sort_keys=True,
                           ensure_ascii=False, separators=(",", ":"))
    return "plan-" + hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:10]


def _waypoint(index, lat, lon, alt_rel_m, gimbal_pitch_deg, heading_deg, speed_mps, action, home):
    alt_rel = round(float(alt_rel_m), 1)
    return {
        "index": int(index),
        "lat": round(float(lat), 9),
        "lon": round(float(lon), 9),
        "alt_rel_m": alt_rel,
        "alt_abs_m": round(float(home["alt_abs_m"]) + alt_rel, 1),
        "heading_deg": round(float(heading_deg) % 360.0, 1),
        "gimbal_pitch_deg": round(float(gimbal_pitch_deg), 1),
        "speed_mps": round(float(speed_mps), 1),
        "action": action,
    }


def _estimate(waypoints, speed_mps):
    path = _path_length(waypoints)
    n_photos = sum(1 for wp in waypoints if wp.get("action") == "photo")
    speed = max(0.5, float(speed_mps))
    duration = path / speed + n_photos * 1.5 + 20.0
    return {"n_waypoints": len(waypoints), "n_photos": n_photos,
            "est_distance_m": round(path, 1), "est_duration_s": round(duration, 1),
            "battery_pct_est": round(min(95.0, 3.0 + duration * 0.058), 1)}


def build_mission(pattern, waypoints, home, plan_id, altitude_m, speed_mps, gimbal_pitch_deg,
                  overlap=DEFAULT_OVERLAP, heading_deg=0.0, stats=None):
    pattern = str(pattern)
    if pattern not in ("grid", "orbit", "point"):
        raise ValueError(f"不支持的 pattern: {pattern!r}（仅 grid/orbit/point）")
    photo_points = [wp["index"] for wp in waypoints if wp.get("action") == "photo"]
    est = stats or _estimate(waypoints, speed_mps)
    return {
        "schema": "llm_drone.mission/v1",
        "plan_id": plan_id,
        "type": pattern,
        "created_at": now_iso(),
        "origin_wgs84": {"lat": round(home["lat"], 9), "lon": round(home["lon"], 9),
                         "alt": round(home["alt_abs_m"], 1)},
        "home": {"lat": round(home["lat"], 9), "lon": round(home["lon"], 9),
                 "alt_abs_m": round(home["alt_abs_m"], 1)},
        "scene": {"ground_alt_m": round(home["alt_abs_m"], 1), **SCENE},
        "camera": json.loads(json.dumps(CAMERA)),
        "flight": {
            "pattern": pattern, "altitude_m": round(float(altitude_m), 1),
            "speed_mps": round(float(speed_mps), 1),
            "gimbal_pitch_deg": round(float(gimbal_pitch_deg), 1),
            "overlap": round(float(overlap), 3),
            "heading_deg": round(float(heading_deg) % 360.0, 1),
            "turn_mode": "stop_and_turn",
        },
        "waypoints": waypoints,
        "photo_points": photo_points,
        "stats": {"n_waypoints": est["n_waypoints"], "n_photos": est["n_photos"],
                  "est_distance_m": est["est_distance_m"], "est_duration_s": est["est_duration_s"]},
    }


def _grid_waypoints(center_lat, center_lon, radius_m, altitude_m, overlap, gimbal_pitch_deg,
                    speed_mps, home):
    fp = ground_footprint(altitude_m, gimbal_pitch_deg)
    spacing_along = max(MIN_SPACING_M, fp["along_m"] * (1.0 - float(overlap)))
    spacing_across = max(MIN_SPACING_M, fp["across_m"] * (1.0 - float(overlap)))
    half = float(radius_m)
    scale = 1.0
    while True:
        n_lines = max(2, int(math.ceil(2.0 * half / (spacing_across * scale))) + 1)
        n_per = max(2, int(math.ceil(2.0 * half / (spacing_along * scale))) + 1)
        if n_lines * n_per <= MAX_PHOTOS:
            break
        scale *= 1.1
    waypoints = []
    idx = 0
    for i in range(n_lines):
        east = (-half + (2.0 * half) * i / (n_lines - 1)) if n_lines > 1 else 0.0
        norths = [(-half + (2.0 * half) * j / (n_per - 1)) if n_per > 1 else 0.0
                  for j in range(n_per)]
        if i % 2 == 1:
            norths = list(reversed(norths))
        heading = 0.0 if i % 2 == 0 else 180.0
        for north in norths:
            p = offset_latlon(center_lat, center_lon, north, 0.0)
            p = offset_latlon(p["lat"], p["lon"], east, 90.0)
            waypoints.append(_waypoint(idx, p["lat"], p["lon"], altitude_m, gimbal_pitch_deg,
                                       heading, speed_mps, "photo", home))
            idx += 1
    meta = {"footprint": fp, "grid": {"lines": n_lines, "shots_per_line": n_per},
            "spacing_m": {"along": round(spacing_along * scale, 2),
                          "across": round(spacing_across * scale, 2)},
            "capped_to_max_photos": scale > 1.0}
    return waypoints, meta


def _orbit_waypoints(center_lat, center_lon, radius_m, altitude_m, shots, gimbal_pitch_deg,
                     speed_mps, home):
    shots = max(4, min(72, int(shots)))
    waypoints = []
    for i in range(shots):
        bearing = 360.0 * i / shots
        p = offset_latlon(center_lat, center_lon, radius_m, bearing)
        heading = (bearing + 180.0) % 360.0
        waypoints.append(_waypoint(i, p["lat"], p["lon"], altitude_m, gimbal_pitch_deg,
                                   heading, speed_mps, "photo", home))
    return waypoints, {"orbit": {"shots": shots, "radius_m": float(radius_m)}}


def _point_waypoints(center_lat, center_lon, altitude_m, shots, gimbal_pitch_deg, speed_mps, home):
    shots = max(1, int(shots))
    return [_waypoint(i, center_lat, center_lon, altitude_m, gimbal_pitch_deg, 0.0,
                      speed_mps, "photo", home) for i in range(shots)], {"point": {"shots": shots}}


def plan_warnings(waypoints, altitude_m, speed_mps, safety=None):
    s = dict(SAFETY_DEFAULT)
    if safety:
        s.update(safety)
    warnings = []
    if altitude_m > s["max_alt_m"]:
        warnings.append(f"规划航高 {altitude_m:.0f}m 超过安全限高 {s['max_alt_m']:.0f}m，执行会被安全层拒绝（E_ALT_LIMIT）")
    if speed_mps > s["max_speed_mps"]:
        warnings.append(f"规划速度 {speed_mps:.1f}m/s 超过安全限速 {s['max_speed_mps']:.0f}m/s（E_SPEED_LIMIT）")
    center = s["fence_center"]
    for wp in waypoints:
        dist = distance_between({"lat": wp["lat"], "lon": wp["lon"]}, center)
        if dist > s["fence_radius_m"]:
            warnings.append(f"航点距围栏中心 {dist:.0f}m 超出半径 {s['fence_radius_m']:.0f}m（E_GEOFENCE）")
            break
    for wp in waypoints:
        if point_in_polygon(wp["lat"], wp["lon"], s["no_fly_polygon"]):
            warnings.append(f"航点 ({wp['lat']:.5f},{wp['lon']:.5f}) 位于默认禁飞区内（E_NOFLY）")
            break
    return warnings


def plan_capture_mission(args, home=None, safety=None):
    """spec tools.json plan_capture_mission 的确定性实现（只读不飞行）。"""
    if not isinstance(args, dict):
        raise ValueError("args 必须是对象")
    pattern = str(args.get("pattern") or "").strip().lower()
    if pattern not in ("grid", "orbit", "point"):
        raise ValueError(f"pattern 必须是 grid/orbit/point，实际 {pattern!r}")
    try:
        center_lat = float(args["center_lat"]); center_lon = float(args["center_lon"])
        altitude_m = float(args["altitude_m"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"center_lat/center_lon/altitude_m 必须提供且为数值：{exc}") from exc
    if altitude_m <= 0:
        raise ValueError("altitude_m 必须 > 0")
    radius_m = float(args.get("radius_m", DEFAULT_RADIUS_M))
    if radius_m <= 0:
        raise ValueError("radius_m 必须 > 0")
    overlap = max(0.0, min(0.95, float(args.get("overlap", DEFAULT_OVERLAP))))
    gimbal_pitch = max(-90.0, min(0.0, float(args.get("gimbal_pitch_deg", DEFAULT_GIMBAL_PITCH))))
    heading_deg = float(args.get("heading_deg", 0.0))
    speed_mps = float(args.get("speed_mps", DEFAULT_SPEED_MPS))
    shots_default = {"grid": 0, "orbit": 12, "point": 5}[pattern]
    shots = int(args.get("shots", shots_default) or shots_default or 5)
    home = dict(home or {"lat": ORIGIN_WGS84["lat"], "lon": ORIGIN_WGS84["lon"],
                         "alt_abs_m": ORIGIN_WGS84["alt"]})
    if pattern == "grid":
        waypoints, meta = _grid_waypoints(center_lat, center_lon, radius_m, altitude_m,
                                          overlap, gimbal_pitch, speed_mps, home)
    elif pattern == "orbit":
        waypoints, meta = _orbit_waypoints(center_lat, center_lon, radius_m, altitude_m,
                                           shots, gimbal_pitch, speed_mps, home)
    else:
        waypoints, meta = _point_waypoints(center_lat, center_lon, altitude_m, shots,
                                           gimbal_pitch, speed_mps, home)
    params = {"pattern": pattern, "center_lat": round(center_lat, 9),
              "center_lon": round(center_lon, 9), "radius_m": radius_m,
              "altitude_m": altitude_m, "overlap": round(overlap, 3),
              "gimbal_pitch_deg": gimbal_pitch, "heading_deg": heading_deg,
              "shots": shots, "speed_mps": speed_mps}
    plan_id = make_plan_id(pattern, params)
    est = _estimate(waypoints, speed_mps)
    mission = build_mission(pattern, waypoints, home, plan_id, altitude_m, speed_mps,
                            gimbal_pitch, overlap, heading_deg, stats=est)
    warnings = plan_warnings(waypoints, altitude_m, speed_mps, safety)
    return {
        "plan_id": plan_id, "mission": mission, "pattern": pattern,
        "photo_interval_s": float(args.get("photo_interval_s", 1.0) or 1.0),
        "summary": _summary_text(pattern, center_lat, center_lon, radius_m, altitude_m,
                                 overlap, gimbal_pitch, mission["stats"], meta),
        "estimates": {"n_waypoints": est["n_waypoints"], "n_photos": est["n_photos"],
                      "est_distance_m": est["est_distance_m"],
                      "est_duration_s": est["est_duration_s"],
                      "battery_pct_est": est["battery_pct_est"]},
        "bounds": bbox_of(waypoints), "warnings": warnings, "params": params,
        "facts": meta,
    }


def plan_orbit(args, home=None, safety=None):
    """spec tools.json orbit 工具：target_lat/target_lon + radius/altitude/shots → orbit mission。"""
    if not isinstance(args, dict):
        raise ValueError("args 必须是对象")
    try:
        target_lat = float(args["target_lat"]); target_lon = float(args["target_lon"])
        altitude_m = float(args["altitude_m"]); radius_m = float(args["radius_m"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"target_lat/target_lon/radius_m/altitude_m 必须提供：{exc}") from exc
    shots = max(4, min(36, int(args.get("shots", 12) or 12)))
    gimbal_pitch = max(-90.0, min(0.0, float(args.get("gimbal_pitch_deg", -30.0))))
    home = dict(home or {"lat": ORIGIN_WGS84["lat"], "lon": ORIGIN_WGS84["lon"],
                         "alt_abs_m": ORIGIN_WGS84["alt"]})
    waypoints, meta = _orbit_waypoints(target_lat, target_lon, radius_m, altitude_m, shots,
                                       gimbal_pitch, DEFAULT_SPEED_MPS, home)
    params = {"pattern": "orbit", "center_lat": round(target_lat, 9),
              "center_lon": round(target_lon, 9), "radius_m": radius_m,
              "altitude_m": altitude_m, "shots": shots,
              "gimbal_pitch_deg": gimbal_pitch, "speed_mps": DEFAULT_SPEED_MPS}
    plan_id = make_plan_id("orbit", params)
    est = _estimate(waypoints, DEFAULT_SPEED_MPS)
    mission = build_mission("orbit", waypoints, home, plan_id, altitude_m, DEFAULT_SPEED_MPS,
                            gimbal_pitch, DEFAULT_OVERLAP, 0.0, stats=est)
    return {"plan_id": plan_id, "mission": mission, "pattern": "orbit",
            "photo_interval_s": 1.0,
            "summary": (f"环绕拍摄：目标 ({target_lat:.5f},{target_lon:.5f})，半径 {radius_m:.0f}m，"
                        f"航高 {altitude_m:.0f}m，{shots} 张，云台 {gimbal_pitch:.0f}°。"),
            "estimates": est, "bounds": bbox_of(waypoints),
            "warnings": plan_warnings(waypoints, altitude_m, DEFAULT_SPEED_MPS, safety),
            "params": params, "facts": meta}


def mission_from_waypoints(waypoints, home=None, plan_id=None, mission_type="grid",
                           speed_mps=DEFAULT_SPEED_MPS, gimbal_pitch_deg=DEFAULT_GIMBAL_PITCH,
                           take_photos=True, heading_deg=0.0):
    """把 LLM 显式给的航点数组包成 spec §6 Mission（goto_waypoints.waypoints 路径）。"""
    if not isinstance(waypoints, list) or not waypoints:
        raise ValueError("waypoints 必须是非空数组")
    home = dict(home or {"lat": ORIGIN_WGS84["lat"], "lon": ORIGIN_WGS84["lon"],
                         "alt_abs_m": ORIGIN_WGS84["alt"]})
    wps = []
    for i, raw in enumerate(waypoints):
        if not isinstance(raw, dict):
            raise ValueError(f"waypoints[{i}] 必须是对象")
        try:
            lat = float(raw["lat"]); lon = float(raw["lon"]); alt = float(raw["alt_rel_m"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"waypoints[{i}] 缺少 lat/lon/alt_rel_m：{exc}") from exc
        action = "none"
        if raw.get("action") in ("photo", "video_start", "video_stop", "none"):
            action = raw["action"]
        elif take_photos:
            action = "photo"
        wps.append(_waypoint(i, lat, lon, alt,
                             float(raw.get("gimbal_pitch_deg", gimbal_pitch_deg)),
                             float(raw.get("heading_deg", heading_deg)),
                             float(raw.get("speed_mps", speed_mps)), action, home))
    plan_id = plan_id or make_plan_id(mission_type, {"custom_waypoints": len(wps)})
    est = _estimate(wps, speed_mps)
    alt0 = float(wps[0]["alt_rel_m"]) if wps else 0.0
    mission = build_mission(mission_type, wps, home, plan_id, alt0, speed_mps,
                            gimbal_pitch_deg, 0.0, heading_deg, stats=est)
    return {"plan_id": plan_id, "mission": mission, "pattern": mission_type,
            "photo_interval_s": 1.0,
            "summary": f"自定义航点任务：{len(wps)} 个航点，{est['n_photos']} 张照片。",
            "estimates": est, "bounds": bbox_of(wps), "warnings": [],
            "params": {"pattern": mission_type, "n_waypoints": len(wps)}, "facts": {}}


def _summary_text(pattern, center_lat, center_lon, radius_m, altitude_m, overlap,
                  gimbal_pitch, stats, meta):
    if pattern == "grid":
        grid = (meta or {}).get("grid") or {}
        return (f"grid 网格航拍：中心 ({center_lat:.5f},{center_lon:.5f})，区域 {2*radius_m:.0f}m×{2*radius_m:.0f}m，"
                f"航高 {altitude_m:.0f}m，重叠率 {overlap*100:.0f}%，云台 {gimbal_pitch:.0f}°，"
                f"{grid.get('lines', '?')} 条航线 × {grid.get('shots_per_line', '?')} 点 = "
                f"{stats['n_waypoints']} 个航点/照片，航线约 {stats['est_distance_m']/1000:.2f}km，"
                f"预计 {stats['est_duration_s']/60:.1f} 分钟。")
    if pattern == "orbit":
        orbit = (meta or {}).get("orbit") or {}
        return (f"orbit 环绕拍摄：目标 ({center_lat:.5f},{center_lon:.5f})，半径 {radius_m:.0f}m，"
                f"航高 {altitude_m:.0f}m，{orbit.get('shots', stats['n_waypoints'])} 个航点/照片，"
                f"云台 {gimbal_pitch:.0f}° 朝目标，预计 {stats['est_duration_s']/60:.1f} 分钟。")
    return (f"point 定点拍摄：位置 ({center_lat:.5f},{center_lon:.5f})，航高 {altitude_m:.0f}m，"
            f"{stats['n_photos']} 张照片，云台 {gimbal_pitch:.0f}°，预计 {stats['est_duration_s']/60:.1f} 分钟。")


if __name__ == "__main__":
    home = {"lat": 39.9042, "lon": 116.4074, "alt_abs_m": 43.0}
    print("footprint(-45,40):", ground_footprint(40, -45))
    for pat in ("grid", "orbit", "point"):
        args = {"pattern": pat, "center_lat": 39.9042, "center_lon": 116.4074,
                "altitude_m": 40, "radius_m": 28, "overlap": 0.7, "gimbal_pitch_deg": -45,
                "shots": 12 if pat == "orbit" else 5}
        p = plan_capture_mission(args, home)
        m = p["mission"]
        print(f"[{pat}] {p['plan_id']} n_wp={len(m['waypoints'])} n_photos={m['stats']['n_photos']} "
              f"dist={m['stats']['est_distance_m']}m")
        print("   ", p["summary"])
        print("    wp0:", m["waypoints"][0])
