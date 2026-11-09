"""Agent 级工具白名单 / JSON Schema / Mission(§6) 归一化（纯函数）。

与 LLM 侧 llm_drone/spec/tools.json 的区别：
  - tools.json 是给 LLM 的 function schema（goto_waypoints 收 plan_id/waypoints）；
  - Agent 级（本模块）按 PROTOCOL.md §4 只接受 goto_waypoints {mission: <§6 Mission JSON>}。
plan_capture_mission / orbit 属于 Orchestrator 侧工具，不在 Agent 白名单内
（发到 Agent 会得到 E_UNKNOWN_TOOL）。

所有函数无副作用、不读网络，便于对抗测试直接断言。
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MISSION_SCHEMA = "llm_drone.mission/v1"
MISSION_TYPES = ("grid", "orbit", "point")
WAYPOINT_ACTIONS = ("photo", "video_start", "video_stop", "none")
MAX_MISSION_WAYPOINTS = 500

SAFETY_DIR = Path(__file__).resolve().parent
SPEC_TOOLS_JSON = SAFETY_DIR.parent / "spec" / "tools.json"

#: Agent 可执行工具（PROTOCOL.md §4 命令表）及其风险/确认/空中要求
TOOL_INFO: Dict[str, Dict[str, Any]] = {
    "get_telemetry": {"risk": "read", "read_only": True, "requires_confirm": False},
    "preflight_check": {"risk": "read", "read_only": True, "requires_confirm": False},
    "takeoff": {"risk": "flight", "read_only": False, "requires_confirm": True},
    "goto_waypoints": {"risk": "flight", "read_only": False, "requires_confirm": True},
    "set_gimbal": {"risk": "low", "read_only": False, "requires_confirm": False, "airborne": True},
    "capture_photo": {"risk": "low", "read_only": False, "requires_confirm": False, "airborne": True},
    "start_video": {"risk": "low", "read_only": False, "requires_confirm": False, "airborne": True},
    "stop_video": {"risk": "low", "read_only": False, "requires_confirm": False, "airborne": True},
    "return_to_home": {"risk": "flight", "read_only": False, "requires_confirm": False},
    "land": {"risk": "flight", "read_only": False, "requires_confirm": False},
    "abort": {"risk": "high", "read_only": False, "requires_confirm": False},
    "get_mission_status": {"risk": "read", "read_only": True, "requires_confirm": False},
    "set_mode": {"risk": "high", "read_only": False, "requires_confirm": "real"},
}

TOOL_NAMES: Tuple[str, ...] = tuple(TOOL_INFO.keys())

_OBJECT = "object"
_NUMBER = "number"
_BOOLEAN = "boolean"
_STRING = "string"


def _empty_args_schema() -> dict:
    return {"type": _OBJECT, "properties": {}, "additionalProperties": False}


#: PROTOCOL.md §4 参数表 -> Agent 级 JSON Schema（additionalProperties=false 拒绝多余字段）
AGENT_SCHEMAS: Dict[str, dict] = {
    "get_telemetry": _empty_args_schema(),
    "preflight_check": _empty_args_schema(),
    "takeoff": {
        "type": _OBJECT,
        "properties": {
            "altitude_m": {"type": _NUMBER},
            "confirm": {"type": _BOOLEAN},
        },
        "required": ["altitude_m"],
        "additionalProperties": False,
    },
    "goto_waypoints": {
        "type": _OBJECT,
        "properties": {
            "mission": {"type": _OBJECT},
            "photo_interval_s": {"type": _NUMBER},
            "take_photos": {"type": _BOOLEAN},  # 可选扩展：false 时不拍照（LLM 工具层兼容）
            "confirm": {"type": _BOOLEAN},
        },
        "required": ["mission"],
        "additionalProperties": False,
    },
    "set_gimbal": {
        "type": _OBJECT,
        "properties": {
            "pitch_deg": {"type": _NUMBER},
            "yaw_deg": {"type": _NUMBER},
        },
        "required": ["pitch_deg"],
        "additionalProperties": False,
    },
    "capture_photo": {
        "type": _OBJECT,
        "properties": {
            "count": {"type": _NUMBER},
            "interval_s": {"type": _NUMBER},
        },
        "additionalProperties": False,
    },
    "start_video": _empty_args_schema(),
    "stop_video": _empty_args_schema(),
    "return_to_home": _empty_args_schema(),
    "land": _empty_args_schema(),
    "abort": {
        "type": _OBJECT,
        "properties": {"reason": {"type": _STRING}},
        "required": ["reason"],
        "additionalProperties": False,
    },
    "get_mission_status": {
        "type": _OBJECT,
        "properties": {"mission_id": {"type": _STRING}},
        "additionalProperties": False,
    },
    "set_mode": {
        "type": _OBJECT,
        "properties": {
            "mode": {"type": _STRING, "enum": ["dry_run", "sim", "real"]},
            "confirm": {"type": _BOOLEAN},
        },
        "required": ["mode"],
        "additionalProperties": False,
    },
}


# ----------------------------------------------------------------- 小工具
def is_whitelisted(tool: Any) -> bool:
    """tool 是否在 Agent 指令白名单内（含类型检查）。"""
    return isinstance(tool, str) and tool in TOOL_INFO


def tool_names() -> Tuple[str, ...]:
    return TOOL_NAMES


def risk_of(tool: str) -> str:
    return TOOL_INFO.get(tool, {}).get("risk", "unknown")


def is_read_only(tool: str) -> bool:
    return bool(TOOL_INFO.get(tool, {}).get("read_only", False))


def requires_confirm(tool: str, args: Optional[dict] = None, confirm_tools: Optional[list] = None) -> bool:
    """该工具此次调用是否必须 confirm=true（PROTOCOL.md §4/§8 规则 12）。"""
    if not is_whitelisted(tool):
        return False
    if tool == "set_mode":
        target = (args or {}).get("mode")
        return target == "real"
    required = set(confirm_tools if confirm_tools is not None else ["takeoff", "goto_waypoints", "orbit"])
    return tool in required


def spec_tool_names() -> List[str]:
    """读取 llm_drone/spec/tools.json 的工具名（供一致性测试/文档；失败返回 []）。"""
    try:
        with open(SPEC_TOOLS_JSON, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return [item["name"] for item in data.get("tools", [])]
    except (OSError, ValueError, KeyError):
        return []


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return type(value).__name__


def _validate_node(schema: dict, value: Any, path: str, errors: List[str]) -> None:
    expected = schema.get("type")
    if expected == _OBJECT:
        if not isinstance(value, dict):
            errors.append("%s: 期望 object，实际 %s" % (path, _type_name(value)))
            return
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append("%s.%s: 缺少必填字段" % (path, name))
        if schema.get("additionalProperties") is False:
            for name in value:
                if name not in properties:
                    errors.append("%s.%s: 不允许的额外字段" % (path, name))
        for name, subschema in properties.items():
            if name in value:
                _validate_node(subschema, value[name], "%s.%s" % (path, name), errors)
        return
    if expected == _NUMBER:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append("%s: 期望 number，实际 %s" % (path, _type_name(value)))
        elif not math.isfinite(float(value)):
            errors.append("%s: 期望有限 number，实际 %r" % (path, value))
        return
    if expected == _BOOLEAN:
        if not isinstance(value, bool):
            errors.append("%s: 期望 boolean，实际 %s" % (path, _type_name(value)))
        return
    if expected == _STRING:
        if not isinstance(value, str):
            errors.append("%s: 期望 string，实际 %s" % (path, _type_name(value)))
        elif "enum" in schema and value not in schema["enum"]:
            errors.append("%s: 取值必须属于 %s，实际 %r" % (path, schema["enum"], value))
        return
    if expected == "array":
        if not isinstance(value, list):
            errors.append("%s: 期望 array，实际 %s" % (path, _type_name(value)))
            return
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                _validate_node(items, item, "%s[%d]" % (path, index), errors)
        return
    # 未声明 type：不校验


# ----------------------------------------------------------------- Mission §6
def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def validate_mission(mission: Any) -> List[str]:
    """校验 PROTOCOL.md §6 Mission JSON 结构，返回错误列表（空=合法）。"""
    errors: List[str] = []
    if not isinstance(mission, dict):
        return ["args.mission: 期望 object，实际 %s" % _type_name(mission)]
    schema_name = mission.get("schema")
    if schema_name is not None and schema_name != MISSION_SCHEMA:
        errors.append("args.mission.schema: 期望 %r，实际 %r" % (MISSION_SCHEMA, schema_name))
    mission_type = mission.get("type")
    if mission_type is not None and mission_type not in MISSION_TYPES:
        errors.append("args.mission.type: 取值必须属于 %s，实际 %r" % (list(MISSION_TYPES), mission_type))

    waypoints = mission.get("waypoints")
    if not isinstance(waypoints, list) or not waypoints:
        errors.append("args.mission.waypoints: 必须是非空数组")
        return errors
    if len(waypoints) > MAX_MISSION_WAYPOINTS:
        errors.append("args.mission.waypoints: 数量 %d 超过上限 %d" % (len(waypoints), MAX_MISSION_WAYPOINTS))

    for index, waypoint in enumerate(waypoints):
        prefix = "args.mission.waypoints[%d]" % index
        if not isinstance(waypoint, dict):
            errors.append("%s: 期望 object，实际 %s" % (prefix, _type_name(waypoint)))
            continue
        for field in ("lat", "lon", "alt_rel_m"):
            if field not in waypoint:
                errors.append("%s.%s: 缺少必填字段" % (prefix, field))
            elif not _is_number(waypoint[field]):
                errors.append("%s.%s: 期望有限 number" % (prefix, field))
        for field in ("alt_abs_m", "heading_deg", "gimbal_pitch_deg", "speed_mps", "index"):
            if field in waypoint and not _is_number(waypoint[field]):
                errors.append("%s.%s: 期望有限 number" % (prefix, field))
        if "action" in waypoint and waypoint["action"] not in WAYPOINT_ACTIONS:
            errors.append(
                "%s.action: 取值必须属于 %s，实际 %r" % (prefix, list(WAYPOINT_ACTIONS), waypoint["action"])
            )
        if "gimbal" in waypoint:
            errors.append("%s.gimbal: §6 航点不支持嵌套 gimbal 字段（用 gimbal_pitch_deg）" % prefix)

    for key in ("origin_wgs84", "home"):
        if key in mission:
            obj = mission[key]
            if not isinstance(obj, dict):
                errors.append("args.mission.%s: 期望 object" % key)
            else:
                if not _is_number(obj.get("lat")):
                    errors.append("args.mission.%s.lat: 期望有限 number" % key)
                if not _is_number(obj.get("lon")):
                    errors.append("args.mission.%s.lon: 期望有限 number" % key)
                alt_key = "alt" if key == "origin_wgs84" else "alt_abs_m"
                if alt_key in obj and not _is_number(obj.get(alt_key)):
                    errors.append("args.mission.%s.%s: 期望有限 number" % (key, alt_key))

    if "flight" in mission and not isinstance(mission["flight"], dict):
        errors.append("args.mission.flight: 期望 object")
    if "camera" in mission and not isinstance(mission["camera"], dict):
        errors.append("args.mission.camera: 期望 object")
    if "photo_points" in mission and not isinstance(mission["photo_points"], list):
        errors.append("args.mission.photo_points: 期望 array")
    return errors


def normalize_mission(mission: dict, origin: Optional[dict] = None) -> dict:
    """把 §6 Mission 归一化为 Agent 执行用结构（不修改入参）。

    补齐默认：alt_abs_m / heading_deg / gimbal_pitch_deg / speed_mps / action；
    缺省 mission_id 时返回 None（由 Agent 分配 m-0001 递增）。
    """
    from .geo import ORIGIN_WGS84  # 延迟导入避免循环

    if not isinstance(mission, dict):
        raise TypeError("mission 必须是 dict")
    base = copy.deepcopy(mission)
    origin_wgs84 = dict(base.get("origin_wgs84") or origin or ORIGIN_WGS84)
    home = base.get("home") or {
        "lat": origin_wgs84["lat"],
        "lon": origin_wgs84["lon"],
        "alt_abs_m": origin_wgs84.get("alt", 43.0),
    }
    home = {
        "lat": float(home.get("lat", origin_wgs84["lat"])),
        "lon": float(home.get("lon", origin_wgs84["lon"])),
        "alt_abs_m": float(home.get("alt_abs_m", origin_wgs84.get("alt", 43.0))),
    }
    flight = dict(base.get("flight") or {})
    photo_points = set()
    for point in base.get("photo_points") or []:
        if isinstance(point, int):
            photo_points.add(point)
    default_heading = float(flight.get("heading_deg", 0.0))
    default_pitch = float(flight.get("gimbal_pitch_deg", 0.0))
    default_speed = float(flight.get("speed_mps", 5.0))
    default_alt = float(flight.get("altitude_m", 0.0))

    waypoints: List[dict] = []
    for index, raw in enumerate(base.get("waypoints") or []):
        alt_rel = float(raw.get("alt_rel_m", default_alt))
        alt_abs = float(raw.get("alt_abs_m", home["alt_abs_m"] + alt_rel))
        action = raw.get("action")
        if action is None:
            if photo_points:
                action = "photo" if int(raw.get("index", index)) in photo_points else "none"
            else:
                action = "photo"
        waypoints.append(
            {
                "index": int(raw.get("index", index)),
                "lat": float(raw["lat"]),
                "lon": float(raw["lon"]),
                "alt_rel_m": alt_rel,
                "alt_abs_m": alt_abs,
                "heading_deg": float(raw.get("heading_deg", default_heading)) % 360.0,
                "gimbal_pitch_deg": float(raw.get("gimbal_pitch_deg", default_pitch)),
                "speed_mps": float(raw.get("speed_mps", default_speed)),
                "action": str(action),
            }
        )
    base["origin_wgs84"] = origin_wgs84
    base["home"] = home
    base["flight"] = flight
    base["waypoints"] = waypoints
    base["photo_points"] = (
        sorted(photo_points) if photo_points else [wp["index"] for wp in waypoints if wp["action"] == "photo"]
    )
    base["mission_id"] = base.get("mission_id")
    base["plan_id"] = base.get("plan_id")
    base["type"] = base.get("type", "grid")
    return base


# ----------------------------------------------------------------- 参数校验入口
def validate_args(tool: str, args: Any) -> List[str]:
    """校验工具参数：返回错误列表（空=通过）。"""
    if not is_whitelisted(tool):
        return ["tool %r 不在指令白名单" % (tool,)]
    if not isinstance(args, dict):
        return ["args: 期望 object，实际 %s" % _type_name(args)]
    errors: List[str] = []
    _validate_node(AGENT_SCHEMAS[tool], args, "args", errors)
    if tool == "goto_waypoints" and "mission" in args and not errors:
        errors.extend(validate_mission(args["mission"]))
    return errors

#: 兼容旧接口：tool -> risk 级（"read" / "low" / "flight" / "high"）
TOOL_RISK = {name: info.get("risk", "unknown") for name, info in TOOL_INFO.items()}

