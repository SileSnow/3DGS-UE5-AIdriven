"""Mission record（PROTOCOL.md §7.1）-> metadata.json（§7.3）导出。

供 orchestrator / demo 直接落 photos_metadata.json（仿真记录版，无真实图像）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

DEFAULT_CAMERA = {
    "model": "DJI Mini 4 Pro (simulated)",
    "width": 1600,
    "height": 1200,
    "fx": 1148.343,
    "fy": 1148.343,
    "cx": 800.0,
    "cy": 600.0,
}


def _camera_of(mission_def: Optional[dict]) -> Dict[str, Any]:
    camera = dict(DEFAULT_CAMERA)
    if isinstance(mission_def, dict):
        source = mission_def.get("camera") or {}
        for key in ("model", "width", "height", "fx", "fy", "cx", "cy"):
            if key in source:
                camera[key] = source[key]
    return camera


def _origin_of(mission_def: Optional[dict], record: Optional[dict] = None) -> dict:
    if isinstance(mission_def, dict):
        origin = mission_def.get("origin_wgs84")
        if isinstance(origin, dict) and "lat" in origin and "lon" in origin:
            return {
                "lat": float(origin["lat"]),
                "lon": float(origin["lon"]),
                "alt": float(origin.get("alt", 43.0)),
            }
    return {"lat": 39.9042, "lon": 116.4074, "alt": 43.0}


def mission_record_to_metadata(
    record: dict,
    mission_def: Optional[dict] = None,
    dataset: str = "synthetic_dji_mini4pro_mission_v1",
) -> dict:
    """把 §7.1 mission record 转成 §7.3 metadata.json 结构。"""
    camera = _camera_of(mission_def)
    origin = _origin_of(mission_def, record)
    mission_id = record.get("mission_id")
    frames = []
    for photo in record.get("photos") or []:
        gimbal = photo.get("gimbal") or {}
        frames.append(
            {
                "file": str(photo.get("file", "")),
                "c2w": [float(value) for value in photo.get("c2w") or []],
                "gps": {
                    "lat": photo.get("lat"),
                    "lon": photo.get("lon"),
                    "alt": photo.get("alt_abs_m"),
                },
                "gimbal_deg": {
                    "yaw": float(gimbal.get("yaw", 0.0)),
                    "pitch": float(gimbal.get("pitch", 0.0)),
                    "roll": float(gimbal.get("roll", 0.0)),
                },
                "timestamp": photo.get("sim_time_s", photo.get("index", 0)),
                "mission": {
                    "mission_id": mission_id,
                    "waypoint_index": photo.get("index"),
                },
            }
        )
    return {
        "dataset": dataset,
        "camera_model": camera["model"],
        "width": int(camera["width"]),
        "height": int(camera["height"]),
        "fx": float(camera["fx"]),
        "fy": float(camera["fy"]),
        "cx": float(camera["cx"]),
        "cy": float(camera["cy"]),
        "coord_system": "UE_LHS_Zup_cm",
        "origin_wgs84": origin,
        "frames": frames,
    }
