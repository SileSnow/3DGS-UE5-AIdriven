"""几何 / 坐标工具（纯函数，无副作用）。

坐标约定严格对齐 shared/CONVENTIONS.md 与 PROTOCOL.md 第 2 节：
- 原点 ORIGIN_WGS84 = {lat: 39.9042, lon: 116.4074, alt: 43.0}
- north_m = (lat - lat0) * 111320.0
- east_m  = (lon - lon0) * 111320.0 * cos(radians(lat0))
- UE 世界坐标：cm，左手系，UE +X = East，UE +Y = South，UE +Z = Up
  x_ue_cm = east_m*100; y_ue_cm = -north_m*100; z_ue_cm = (alt_abs_m - alt0)*100
- heading_deg：罗盘角（0=北，90=东，顺时针）；UE yaw = heading_deg - 90
- gimbal_pitch_deg：-90=正下，0=水平
"""

from __future__ import annotations

import math
from typing import Iterable, List, Optional, Sequence, Tuple, Union

M_PER_DEG_LAT = 111320.0

ORIGIN_WGS84 = {"lat": 39.9042, "lon": 116.4074, "alt": 43.0}


# ---------------------------------------------------------------- 局部 <-> WGS84
def local_to_wgs84(
    east_m: float,
    north_m: float,
    up_m: float = 0.0,
    origin: Optional[dict] = None,
) -> dict:
    """局部 ENU（米，原点=origin）-> WGS84 经纬度 + 绝对高度（米）。"""
    o = origin or ORIGIN_WGS84
    lat = float(o["lat"]) + float(north_m) / M_PER_DEG_LAT
    lon = float(o["lon"]) + float(east_m) / (
        M_PER_DEG_LAT * math.cos(math.radians(float(o["lat"])))
    )
    alt_abs = float(o["alt"]) + float(up_m)
    return {"lat": lat, "lon": lon, "alt": alt_abs}


def wgs84_to_local(
    lat: float,
    lon: float,
    alt_abs: Optional[float] = None,
    origin: Optional[dict] = None,
) -> dict:
    """WGS84 -> 局部 ENU（米）。alt_abs 省略时 up_m=0。"""
    o = origin or ORIGIN_WGS84
    north = (float(lat) - float(o["lat"])) * M_PER_DEG_LAT
    east = (float(lon) - float(o["lon"])) * M_PER_DEG_LAT * math.cos(
        math.radians(float(o["lat"]))
    )
    up = 0.0 if alt_abs is None else (float(alt_abs) - float(o["alt"]))
    return {"east_m": east, "north_m": north, "up_m": up}


def local_to_ue_cm(east_m: float, north_m: float, up_m: float) -> List[float]:
    """局部 ENU 米 -> UE 世界 cm（+X=东、+Y=南、+Z=上）。"""
    return [float(east_m) * 100.0, -float(north_m) * 100.0, float(up_m) * 100.0]


def ue_cm_to_local(x_cm: float, y_cm: float, z_cm: float) -> dict:
    """UE 世界 cm -> 局部 ENU 米。"""
    return {
        "east_m": float(x_cm) / 100.0,
        "north_m": -float(y_cm) / 100.0,
        "up_m": float(z_cm) / 100.0,
    }


# ---------------------------------------------------------------- 角度 / 航向
def normalize_deg(deg: float, lo: float = -180.0, hi: float = 180.0) -> float:
    """把角度归一化到 [lo, hi)。"""
    span = float(hi) - float(lo)
    return (float(deg) - lo) % span + lo


def heading_to_ue_yaw(heading_deg: float) -> float:
    """罗盘航向 -> UE rotator yaw（UE yaw 0 = +X = 东）。"""
    return normalize_deg(float(heading_deg) - 90.0, -180.0, 180.0)


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """从点 1 指向点 2 的罗盘方位角 [0, 360)。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(float(lon2) - float(lon1))
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def compass_to_ue_rotator_yaw(compass_yaw_deg: float) -> float:
    """罗盘角 -> UE rotator yaw（capture 工程约定：UE yaw 0 = +X = 东）。"""
    return heading_to_ue_yaw(compass_yaw_deg)


def offset_latlon(
    lat: float,
    lon: float,
    bearing_deg_value: float,
    distance_m: float,
    origin: Optional[dict] = None,
) -> dict:
    """从 (lat,lon) 沿罗盘方位角前进 distance_m 后的经纬度（局部平面近似）。"""
    _ = origin  # 占位：球面公式不依赖局部原点
    radius = 6371000.0
    angular = float(distance_m) / radius
    theta = math.radians(float(bearing_deg_value))
    lat1 = math.radians(float(lat))
    lon1 = math.radians(float(lon))
    sin_lat2 = math.sin(lat1) * math.cos(angular) + math.cos(lat1) * math.sin(angular) * math.cos(theta)
    sin_lat2 = max(-1.0, min(1.0, sin_lat2))
    lat2 = math.asin(sin_lat2)
    lon2 = lon1 + math.atan2(
        math.sin(theta) * math.sin(angular) * math.cos(lat1),
        math.cos(angular) - math.sin(lat1) * sin_lat2,
    )
    return {"lat": math.degrees(lat2), "lon": math.degrees(lon2)}


# ---------------------------------------------------------------- 距离
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点水平大圆距离（米）。"""
    radius = 6371000.0
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp = p2 - p1
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * radius * math.asin(min(1.0, math.sqrt(a)))


# ---------------------------------------------------------------- UE 相机轴 / c2w
def rotator_axes_ue(
    yaw_deg: float, pitch_deg: float, roll_deg: float = 0.0
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]:
    """UE rotator 轴（forward/right/up），与 PROTOCOL.md 7.2 公式一致。

    注意：本函数接收的是 **UE rotator yaw**（不是罗盘航向）；
    调用方应先用 heading_to_ue_yaw() 转换。roll 恒为 0（本仿真）。
    """
    y = math.radians(float(yaw_deg))
    p = math.radians(float(pitch_deg))
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    forward = (cp * cy, cp * sy, sp)
    right = (-sy, cy, 0.0)
    up = (-sp * cy, -sp * sy, cp)
    return forward, right, up


def camera_c2w_from_ue_yaw(
    pos_ue_cm: Sequence[float],
    yaw_ue_deg: float,
    pitch_deg: float,
    roll_deg: float = 0.0,
) -> List[float]:
    """构造 4x4 行主序 c2w（列 = [forward, right, up]，UE 世界 cm）。

    PROTOCOL.md 7.2：
      c2w = [forward.x, right.x, up.x, x_cm,
             forward.y, right.y, up.y, y_cm,
             forward.z, right.z, up.z, z_cm,
             0, 0, 0, 1]
    """
    fwd, right, up = rotator_axes_ue(yaw_ue_deg, pitch_deg, roll_deg)
    tx, ty, tz = float(pos_ue_cm[0]), float(pos_ue_cm[1]), float(pos_ue_cm[2])
    return [
        fwd[0], right[0], up[0], tx,
        fwd[1], right[1], up[1], ty,
        fwd[2], right[2], up[2], tz,
        0.0, 0.0, 0.0, 1.0,
    ]


def camera_c2w_ue_cm(
    pos_ue_cm: Sequence[float],
    heading_deg: float,
    pitch_deg: float,
    roll_deg: float = 0.0,
) -> List[float]:
    """按罗盘航向（0=北）构造 UE c2w（内部换算 UE yaw = heading - 90）。"""
    return camera_c2w_from_ue_yaw(
        pos_ue_cm, heading_to_ue_yaw(heading_deg), pitch_deg, roll_deg
    )


def camera_c2w_from_pose(
    lat: float,
    lon: float,
    alt_abs_m: float,
    heading_deg: float,
    gimbal_pitch_deg: float,
    origin: Optional[dict] = None,
) -> List[float]:
    """由 WGS84 位姿 + 罗盘航向 + 云台 pitch 计算 UE 世界 c2w（cm）。"""
    o = origin or ORIGIN_WGS84
    loc = wgs84_to_local(lat, lon, alt_abs_m, origin=o)
    pos = local_to_ue_cm(loc["east_m"], loc["north_m"], loc["up_m"])
    return camera_c2w_ue_cm(pos, heading_deg, gimbal_pitch_deg)


# ---------------------------------------------------------------- 多边形 / 圆
PointLike = Union[dict, Sequence[float]]


def _poly_local(polygon: Iterable[PointLike], origin: Optional[dict] = None) -> List[Tuple[float, float]]:
    pts: List[Tuple[float, float]] = []
    for v in polygon:
        if isinstance(v, dict):
            lat, lon = float(v["lat"]), float(v["lon"])
        else:
            lat, lon = float(v[0]), float(v[1])
        loc = wgs84_to_local(lat, lon, None, origin=origin)
        pts.append((loc["east_m"], loc["north_m"]))
    return pts


def point_on_segment(
    px: float, py: float, ax: float, ay: float, bx: float, by: float, eps: float = 1e-9
) -> bool:
    """点 (px,py) 是否在线段 ab 上（局部米，eps 容差）。"""
    cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    if abs(cross) > eps:
        return False
    dot = (px - ax) * (bx - ax) + (py - ay) * (by - ay)
    if dot < -eps:
        return False
    sq = (bx - ax) ** 2 + (by - ay) ** 2
    return dot <= sq + eps


def point_in_polygon(
    lat: float, lon: float, polygon: Sequence[PointLike], origin: Optional[dict] = None
) -> bool:
    """射线法判断点是否在多边形内（边上的点视为在内）。"""
    loc = wgs84_to_local(lat, lon, None, origin=origin)
    x, y = loc["east_m"], loc["north_m"]
    pts = _poly_local(polygon, origin=origin)
    n = len(pts)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if point_on_segment(x, y, xi, yi, xj, yj, eps=0.01):
            return True
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / ((yj - yi) if (yj - yi) != 0 else 1e-12) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def circle_contains(
    lat: float, lon: float, center_lat: float, center_lon: float, radius_m: float
) -> bool:
    """点是否在圆形区域内（含边界）。"""
    return haversine_m(lat, lon, center_lat, center_lon) <= float(radius_m)


def is_orthonormal_rotation(c2w: Sequence[float], tol: float = 1e-6) -> bool:
    """检查 4x4 c2w 的旋转部分是否正交（|R R^T - I| < tol，行列式 +1）。"""
    if len(c2w) != 16:
        return False
    r = [
        [c2w[0], c2w[1], c2w[2]],
        [c2w[4], c2w[5], c2w[6]],
        [c2w[8], c2w[9], c2w[10]],
    ]
    for i in range(3):
        for j in range(3):
            dot = sum(r[i][k] * r[j][k] for k in range(3))
            expected = 1.0 if i == j else 0.0
            if abs(dot - expected) > tol:
                return False
    det = (
        r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
        - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
        + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0])
    )
    return abs(det - 1.0) <= tol
