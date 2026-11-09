# -*- coding: utf-8 -*-
"""LLM 工具定义（OpenAI function-calling schema）+ 轻量 JSON Schema 校验。

对应 llm_drone/docs/CONTRACT.md §1「工具定义」。
仅依赖 Python 标准库；orchestrator / demo / 测试共用本文件。
"""
from __future__ import annotations

import copy
from typing import Any

# ---- 风险级（与 CONTRACT 表一致） -------------------------------------------
RISK_READONLY = "readonly"   # 只读
RISK_LOW = "low"             # 低风险（云台/拍照/录像）
RISK_FLIGHT = "flight"       # 飞行
RISK_HIGH = "high"           # 高风险（中止、模式切换）

_LATLON = {
    "type": "object",
    "description": "WGS84 经纬度坐标",
    "properties": {
        "lat": {"type": "number", "minimum": -90, "maximum": 90, "description": "纬度"},
        "lon": {"type": "number", "minimum": -180, "maximum": 180, "description": "经度"},
    },
    "required": ["lat", "lon"],
}

_WAYPOINT = {
    "type": "object",
    "description": "航点：相对高度 alt_rel_m，可选该点速度与云台俯仰",
    "properties": {
        "lat": {"type": "number", "minimum": -90, "maximum": 90},
        "lon": {"type": "number", "minimum": -180, "maximum": 180},
        "alt_rel_m": {"type": "number", "minimum": 0.5, "maximum": 500, "description": "相对起飞点高度（米）"},
        "speed_mps": {"type": "number", "minimum": 0.2, "maximum": 15},
        "gimbal_pitch": {"type": "number", "minimum": -90, "maximum": 30},
    },
    "required": ["lat", "lon", "alt_rel_m"],
}

TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_telemetry",
            "description": "读取无人机当前遥测（位置/高度/速度/电量/云台/GPS/遥控链路）。只读，不飞行。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preflight_check",
            "description": "起飞前检查（GPS/电量/禁飞区/固件/遥控链路）。只读，不飞行。返回逐项检查结果。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_capture_mission",
            "description": (
                "规划航拍任务（只读，不飞行）：根据航拍模式生成 waypoints 与拍照点，"
                "返回 plan_id、照片数/航线长度/预计耗时估算。之后可用 plan_id 执行，无需抄写航点。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "enum": ["grid", "five_direction", "orbit"],
                        "description": "航拍模式：grid=区域网格航拍（3DGS 重建）；five_direction=定点五向/多角度；orbit=环绕目标",
                    },
                    "area": {
                        "type": "object",
                        "description": "作业区域：中心点 + 半径（米）；grid 用半径表示正方形半边长，orbit/five_direction 用半径表示环绕距离",
                        "properties": {
                            "center": _LATLON,
                            "radius_m": {"type": "number", "minimum": 5, "maximum": 2000},
                        },
                        "required": ["center", "radius_m"],
                    },
                    "altitude_m": {"type": "number", "minimum": 3, "maximum": 500, "description": "相对起飞点航高（米）；安全上限 120m 由安全层校验"},
                    "overlap": {"type": "number", "minimum": 0.3, "maximum": 0.95, "description": "航向重叠率（0~1），3DGS 建议 0.75~0.85"},
                    "side_overlap": {"type": "number", "minimum": 0.3, "maximum": 0.95, "description": "旁向重叠率（0~1），默认 0.7"},
                    "gimbal_pitch": {"type": "number", "minimum": -90, "maximum": 30, "description": "云台俯仰角（度，向下为负）；grid 建议 -90"},
                    "speed_mps": {"type": "number", "minimum": 1, "maximum": 15, "description": "航线速度 m/s，默认 5"},
                    "shots": {"type": "integer", "minimum": 3, "maximum": 72, "description": "orbit/five_direction 拍照张数（五向默认 5）"},
                    "task_name": {"type": "string", "description": "任务名称，便于审计"},
                },
                "required": ["pattern", "area", "altitude_m"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "takeoff",
            "description": "起飞到指定相对高度。飞行指令，必须用户明确确认后带 confirm=true。",
            "parameters": {
                "type": "object",
                "properties": {
                    "altitude_m": {"type": "number", "minimum": 1, "maximum": 500, "description": "相对起飞高度（米）；安全上限 120m 由安全层校验"},
                    "confirm": {"type": "boolean", "description": "用户已明确确认执行时才为 true"},
                },
                "required": ["altitude_m"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "goto_waypoints",
            "description": (
                "执行航点任务（含可选连拍）。飞行指令，必须用户明确确认后带 confirm=true。"
                "推荐传 plan_capture_mission 返回的 plan_id，由编排层确定性展开航点；"
                "仅在用户自定义航点时才手写 waypoints。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string", "description": "plan_capture_mission 返回的计划 ID（与 waypoints 二选一）"},
                    "waypoints": {"type": "array", "items": _WAYPOINT, "maxItems": 200, "description": "航点数组（与 plan_id 二选一）"},
                    "speed_mps": {"type": "number", "minimum": 0.2, "maximum": 15, "description": "巡航速度 m/s"},
                    "take_photos": {"type": "boolean", "description": "是否在每个航点拍照"},
                    "photo_interval_s": {"type": "number", "minimum": 0.5, "maximum": 60, "description": "拍照间隔（秒）"},
                    "confirm": {"type": "boolean", "description": "用户已明确确认执行时才为 true"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "orbit",
            "description": "环绕目标拍摄。飞行指令，必须用户明确确认后带 confirm=true。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": _LATLON,
                    "radius_m": {"type": "number", "minimum": 5, "maximum": 300, "description": "环绕半径（米）"},
                    "altitude_m": {"type": "number", "minimum": 3, "maximum": 500, "description": "相对高度（米）；安全上限 120m 由安全层校验"},
                    "shots": {"type": "integer", "minimum": 4, "maximum": 72, "description": "环绕拍摄张数"},
                    "gimbal_pitch": {"type": "number", "minimum": -90, "maximum": 30, "description": "云台俯仰角（度）"},
                    "confirm": {"type": "boolean", "description": "用户已明确确认执行时才为 true"},
                },
                "required": ["target", "radius_m", "altitude_m"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_gimbal",
            "description": "设置云台角度（低风险，非飞行）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pitch_deg": {"type": "number", "minimum": -90, "maximum": 30, "description": "俯仰角（向下为负）"},
                    "yaw_deg": {"type": "number", "minimum": -180, "maximum": 180, "description": "偏航角（正北为 0，顺时针为正）"},
                },
                "required": ["pitch_deg"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "capture_photo",
            "description": "拍照（低风险，需已起飞）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "minimum": 1, "maximum": 20, "description": "张数，默认 1"},
                    "interval_s": {"type": "number", "minimum": 0.5, "maximum": 60, "description": "间隔秒，默认 2"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_video",
            "description": "开始录像（低风险，需已起飞）。",
            "parameters": {
                "type": "object",
                "properties": {"duration_s": {"type": "number", "minimum": 1, "maximum": 3600, "description": "可选：自动停止时长"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_video",
            "description": "停止录像。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "return_to_home",
            "description": "一键返航（安全动作，无需 confirm）。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "land",
            "description": "原地降落（安全动作，无需 confirm）。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "abort",
            "description": "中止当前任务（悬停/返航），高优先级安全动作。",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string", "description": "中止原因"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_mission_status",
            "description": "查询任务进度/照片/电量（只读）。不传 mission_id 时查询最近一次任务。",
            "parameters": {
                "type": "object",
                "properties": {"mission_id": {"type": "string", "description": "任务 ID，可选"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_mode",
            "description": "切换运行模式 dry_run|sim|real。real 需人工确认（Phase-1 禁止）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["dry_run", "sim", "real"]},
                    "confirm": {"type": "boolean", "description": "real 模式必须人工确认"},
                },
                "required": ["mode"],
            },
        },
    },
]

# ---- 工具元数据 -------------------------------------------------------------
TOOL_META: dict[str, dict[str, Any]] = {
    "get_telemetry": {"risk": RISK_READONLY, "confirm_required": False, "executor": "backend"},
    "preflight_check": {"risk": RISK_READONLY, "confirm_required": False, "executor": "backend"},
    "plan_capture_mission": {"risk": RISK_READONLY, "confirm_required": False, "executor": "local_planner"},
    "takeoff": {"risk": RISK_FLIGHT, "confirm_required": True, "executor": "backend"},
    "goto_waypoints": {"risk": RISK_FLIGHT, "confirm_required": True, "executor": "backend"},
    "orbit": {"risk": RISK_FLIGHT, "confirm_required": True, "executor": "backend"},
    "set_gimbal": {"risk": RISK_LOW, "confirm_required": False, "executor": "backend"},
    "capture_photo": {"risk": RISK_LOW, "confirm_required": False, "executor": "backend"},
    "start_video": {"risk": RISK_LOW, "confirm_required": False, "executor": "backend"},
    "stop_video": {"risk": RISK_LOW, "confirm_required": False, "executor": "backend"},
    "return_to_home": {"risk": RISK_FLIGHT, "confirm_required": False, "executor": "backend"},
    "land": {"risk": RISK_FLIGHT, "confirm_required": False, "executor": "backend"},
    "abort": {"risk": RISK_HIGH, "confirm_required": False, "executor": "backend"},
    "get_mission_status": {"risk": RISK_READONLY, "confirm_required": False, "executor": "backend"},
    "set_mode": {"risk": RISK_HIGH, "confirm_required": True, "executor": "backend"},
}

FLIGHT_TOOLS = {name for name, meta in TOOL_META.items() if meta["risk"] in (RISK_FLIGHT, RISK_HIGH)}
CONFIRM_TOOLS = {name for name, meta in TOOL_META.items() if meta["confirm_required"]}
LOCAL_TOOLS = {name for name, meta in TOOL_META.items() if meta["executor"] == "local_planner"}

ALLOWED_ARG_KEYS = {name: set(spec["function"]["parameters"].get("properties", {})) for name, spec in
                    ((s["function"]["name"], s) for s in TOOL_SPECS)}


def tool_names() -> list[str]:
    return [s["function"]["name"] for s in TOOL_SPECS]


def get_tool_spec(name: str) -> dict | None:
    for spec in TOOL_SPECS:
        if spec["function"]["name"] == name:
            return spec
    return None


def get_tool_schemas() -> list[dict]:
    """返回可直接塞给 OpenAI 兼容接口的 tools 数组（深拷贝，调用方可安全修改）。"""
    return copy.deepcopy(TOOL_SPECS)


def is_flight_tool(name: str) -> bool:
    return name in FLIGHT_TOOLS


def requires_confirm(name: str) -> bool:
    return name in CONFIRM_TOOLS


def tool_catalog_for_prompt() -> str:
    """JSON 降级模式使用的工具目录（纯文本）。"""
    lines: list[str] = []
    for spec in TOOL_SPECS:
        fn = spec["function"]
        props = (fn.get("parameters") or {}).get("properties") or {}
        req = (fn.get("parameters") or {}).get("required") or []
        parts = []
        for key, prop in props.items():
            tag = f"{key}:{prop.get('type', 'any')}"
            if prop.get("enum"):
                tag += "=" + "|".join(str(v) for v in prop["enum"])
            if key in req:
                tag += "(必填)"
            parts.append(tag)
        lines.append(f"- {fn['name']}: {fn['description']} 参数: {', '.join(parts) or '无'}")
    return "\n".join(lines)


# ---- 轻量 JSON Schema 校验 --------------------------------------------------
_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "number": (int, float),
    "integer": int,
    "null": type(None),
}


def _type_ok(value: Any, tname: str) -> bool:
    if tname == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if tname == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if tname == "boolean":
        return isinstance(value, bool)
    expected = _TYPE_MAP.get(tname)
    if expected is None:
        return True
    return isinstance(value, expected)


def _validate(schema: dict, value: Any, path: str, errors: list[str]) -> None:
    tname = schema.get("type")
    if tname and not _type_ok(value, tname):
        errors.append(f"{path} 类型应为 {tname}，实际 {type(value).__name__}")
        return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} 取值必须是 {schema['enum']} 之一，实际 {value!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path} 应 >= {schema['minimum']}，实际 {value}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path} 应 <= {schema['maximum']}，实际 {value}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path} 长度应 >= {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path} 长度应 <= {schema['maxLength']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path} 至少 {schema['minItems']} 项")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path} 最多 {schema['maxItems']} 项")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(value):
                _validate(item_schema, item, f"{path}[{i}]", errors)
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path} 缺少必填参数 {key}")
        props = schema.get("properties") or {}
        for key, prop_schema in props.items():
            if key in value:
                _validate(prop_schema, value[key], f"{path}.{key}", errors)
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errors.append(f"{path} 不支持参数 {key}")


def _extra_rules(name: str, args: dict) -> list[str]:
    """跨字段业务规则（JSON Schema 表达不便的）。"""
    errors: list[str] = []
    if name == "goto_waypoints":
        has_wp = isinstance(args.get("waypoints"), list) and len(args.get("waypoints") or []) > 0
        has_plan = isinstance(args.get("plan_id"), str) and args["plan_id"].strip() != ""
        if has_wp and has_plan:
            errors.append("waypoints 与 plan_id 只能二选一")
        if not has_wp and not has_plan:
            errors.append("必须提供 waypoints 或 plan_id 之一")
        if has_wp and len(args["waypoints"]) > 200:
            errors.append("waypoints 超过 200 个上限")
    if name == "plan_capture_mission":
        area = args.get("area") or {}
        if isinstance(area, dict):
            if not area.get("center"):
                errors.append("area.center 必须提供")
            if "radius_m" not in area:
                errors.append("area.radius_m 必须提供")
        if args.get("pattern") not in (None, "grid", "five_direction", "orbit"):
            errors.append("pattern 只支持 grid / five_direction / orbit")
    if name == "set_mode":
        if args.get("mode") == "real" and args.get("confirm") is not True:
            errors.append("切换到 real 模式必须 confirm=true 且经人工确认")
    return errors


def validate_args(name: str, args: Any) -> list[str]:
    """校验工具参数；返回错误列表，空列表表示通过。"""
    if not isinstance(args, dict):
        return [f"参数必须是 JSON 对象，实际 {type(args).__name__}"]
    spec = get_tool_spec(name)
    if spec is None:
        return [f"未知工具 {name!r}（白名单：{', '.join(tool_names())}）"]
    errors: list[str] = []
    _validate(spec["function"].get("parameters") or {}, args, name, errors)
    errors.extend(_extra_rules(name, args))
    return errors


def validate_tool_call(name: str, args: Any) -> tuple[bool, list[str]]:
    errors = validate_args(name, args)
    return (not errors), errors


if __name__ == "__main__":
    # 自检：打印工具目录 + 几个校验样例
    print(f"共 {len(TOOL_SPECS)} 个工具：")
    for n in tool_names():
        meta = TOOL_META[n]
        print(f"  {n:<22} risk={meta['risk']:<8} confirm={str(meta['confirm_required']):<5} exec={meta['executor']}")
    print()
    print("校验样例：")
    cases = [
        ("takeoff", {"altitude_m": 20, "confirm": True}),
        ("takeoff", {"altitude_m": 150}),
        ("goto_waypoints", {"plan_id": "plan-abc"}),
        ("goto_waypoints", {}),
        ("plan_capture_mission", {"pattern": "grid", "area": {"center": {"lat": 39.9, "lon": 116.4}, "radius_m": 70}, "altitude_m": 50}),
        ("set_mode", {"mode": "real"}),
    ]
    for name, args in cases:
        ok, errs = validate_tool_call(name, args)
        print(f"  {name:<22} ok={ok} errors={errs}")
