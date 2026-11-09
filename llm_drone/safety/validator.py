"""SafetyValidator —— 确定性安全/策略校验层（权威安全执行后端）。

设计原则：
- 纯函数优先：validate_command / preflight_check 不修改传入状态、不做 I/O；
  审计由调用方（Drone Agent）根据返回的 SafetyDecision 写入。
- 校验顺序严格按 PROTOCOL.md §4（任一失败立即拒绝，拒绝优于截断参数）：
    schema -> whitelist -> mode -> confirm -> state -> battery -> gps -> rc
    -> altitude/speed 范围 -> geofence -> no-fly zone -> 返航能量估算 -> 允许
- 错误码逐字使用 safety.errors 常量（PROTOCOL.md §8.2）。

实现说明（与规格的对应关系，已写入 safety/README.md）：
1) 未知工具无法做参数 schema（schema 依赖工具定义），因此白名单先于 schema 判定，
   返回 E_UNKNOWN_TOOL（对应 §11.2 A9 与 §8 规则 10）。
2) 规则 16（并发命令 E_BUSY）在 state 阶段最前面判定；任务执行中仅允许
   abort/get_telemetry/get_mission_status/return_to_home。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import errors as E
from .config import SafetyConfig, default_config
from .geo import haversine_m, point_in_polygon
from .schemas import (
    TOOL_INFO,
    is_whitelisted,
    normalize_mission,
    requires_confirm,
    validate_args,
)

#: 任务执行中唯一允许的命令（PROTOCOL.md §8 规则 16）
BUSY_ALLOWED_TOOLS = frozenset({"abort", "get_telemetry", "get_mission_status", "return_to_home"})

#: 需要“在空中”才允许的低风险动作
AIRBORNE_ACTIONS = frozenset({"set_gimbal", "capture_photo", "start_video", "stop_video"})

AIRBORNE_STATES = frozenset(
    {"taking_off", "hovering", "mission", "returning", "landing", "aborted", "failsafe"}
)

SKIP_CONFIRM_KEY = "confirm"


@dataclass
class SafetyDecision:
    """校验结论。allow=False 时 error_code / reasons 必须存在并写审计。"""

    allow: bool
    error_code: Optional[str] = None
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    stages: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "allow": self.allow,
            "error_code": self.error_code,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "details": dict(self.details),
        }


def _reject(code: str, reasons: List[str], details: Optional[dict] = None) -> SafetyDecision:
    return SafetyDecision(
        allow=False,
        error_code=code,
        reasons=list(reasons),
        details=dict(details or {}),
    )


def _clean_args(args: Any) -> Dict[str, Any]:
    """复制参数并剥离顶层协议字段（confirm 走请求顶层；兼容 args.confirm）。"""
    if not isinstance(args, dict):
        return {}
    cleaned = dict(args)
    cleaned.pop(SKIP_CONFIRM_KEY, None)
    return cleaned


# --------------------------------------------------------------------- 各阶段
def _stage_schema(tool: str, raw_args: Any, args: Dict[str, Any]) -> Optional[SafetyDecision]:
    if not is_whitelisted(tool):
        return _reject(
            E.E_UNKNOWN_TOOL,
            ["tool %r 不在指令白名单（Agent 级 §4 命令表）" % (tool,)],
            {"allowed_tools": sorted(TOOL_INFO.keys())},
        )
    schema_errors = validate_args(tool, args)
    if schema_errors:
        return _reject(E.E_SCHEMA, schema_errors, {"tool": tool})
    if raw_args is not None and not isinstance(raw_args, dict):
        return _reject(E.E_SCHEMA, ["args: 期望 object，实际 %s" % type(raw_args).__name__])
    return None


def _stage_mode(tool: str, args: Dict[str, Any], telemetry: dict, config: SafetyConfig) -> Optional[SafetyDecision]:
    mode = telemetry.get("mode", "sim")
    if mode not in E.MODES:
        return _reject(E.E_MODE, ["当前 mode=%r 非法" % (mode,)])
    if tool == "set_mode":
        target = args.get("mode")
        if target == "real" and not config.allow_real_mode:
            return _reject(
                E.E_REAL_NOT_AVAILABLE,
                ["Phase1 仅仿真后端，set_mode(real) 不可用（allow_real_mode=false）"],
                {"requested_mode": target},
            )
        return None
    if mode == "real":
        return _reject(E.E_REAL_NOT_AVAILABLE, ["Phase1 无真机后端（mode=real）"])
    return None


def _stage_confirm(
    tool: str, args: Dict[str, Any], confirm: Any, config: SafetyConfig
) -> Optional[SafetyDecision]:
    if confirm is not None and not isinstance(confirm, bool):
        return _reject(E.E_SCHEMA, ["confirm: 期望 boolean，实际 %s" % type(confirm).__name__])
    required = requires_confirm(tool, args, config.require_confirm_tools)
    if required and confirm is not True:
        return _reject(
            E.E_CONFIRM_REQUIRED,
            ["tool %r 必须带 confirm=true（当前 confirm=%r）" % (tool, confirm)],
            {"tool": tool, "confirm": confirm},
        )
    return None


def _stage_state(
    tool: str, args: Dict[str, Any], state: str, active_mission_id: Optional[str]
) -> Optional[SafetyDecision]:
    if active_mission_id and tool not in BUSY_ALLOWED_TOOLS:
        return _reject(
            E.E_BUSY,
            [
                "任务 %s 执行中，仅允许 abort/get_telemetry/get_mission_status/return_to_home"
                % active_mission_id
            ],
            {"mission_id": active_mission_id},
        )

    if tool == "takeoff":
        if state != "idle":
            return _reject(E.E_STATE, ["takeoff 需要 state=idle，当前 state=%r" % (state,)], {"state": state})
        return None
    if tool == "goto_waypoints":
        if state != "hovering":
            return _reject(
                E.E_STATE,
                ["goto_waypoints 需要 state=hovering（先 takeoff），当前 state=%r" % (state,)],
                {"state": state},
            )
        return None
    if tool in AIRBORNE_ACTIONS:
        if state not in AIRBORNE_STATES:
            return _reject(
                E.E_NOT_AIRBORNE,
                ["%s 需要空中状态（当前 state=%r，需先起飞）" % (tool, state)],
                {"state": state},
            )
        return None
    if tool == "return_to_home":
        if state not in AIRBORNE_STATES or state == "landing":
            return _reject(E.E_STATE, ["return_to_home 需要空中且非降落状态，当前 state=%r" % (state,)])
        return None
    if tool == "land":
        if state not in AIRBORNE_STATES or state in ("landing",):
            return _reject(E.E_STATE, ["land 需要空中状态，当前 state=%r" % (state,)])
        return None
    if tool == "abort":
        return None
    if tool == "set_mode":
        if state != "idle":
            return _reject(E.E_STATE, ["set_mode 需要 state=idle，当前 state=%r" % (state,)], {"state": state})
        return None
    # get_telemetry / preflight_check / get_mission_status 任意状态可用
    return None


def _stage_battery(tool: str, telemetry: dict, config: SafetyConfig) -> Optional[SafetyDecision]:
    if tool != "takeoff":
        return None
    battery = _number(telemetry.get("battery_pct"), 0.0)
    if battery < float(config.min_takeoff_battery_pct):
        return _reject(
            E.E_BATTERY_TAKEOFF,
            ["起飞电量不足：%.1f%% < %.1f%%" % (battery, config.min_takeoff_battery_pct)],
            {"battery_pct": battery, "min_pct": float(config.min_takeoff_battery_pct)},
        )
    return None


def _stage_gps(tool: str, telemetry: dict, config: SafetyConfig) -> Optional[SafetyDecision]:
    if tool != "takeoff":
        return None
    gps = telemetry.get("gps") or {}
    fix = int(_number(gps.get("fix"), 0))
    satellites = int(_number(gps.get("satellites"), 0))
    if fix < int(config.gps_min_fix) or satellites < int(config.gps_min_satellites):
        return _reject(
            E.E_GPS,
            [
                "GPS 质量不足：fix=%d（需>=%d）、satellites=%d（需>=%d）"
                % (fix, config.gps_min_fix, satellites, config.gps_min_satellites)
            ],
            {"fix": fix, "satellites": satellites},
        )
    return None


def _stage_rc(tool: str, telemetry: dict, config: SafetyConfig) -> Optional[SafetyDecision]:
    if tool != "takeoff" or not config.require_rc:
        return None
    rc = telemetry.get("rc") or {}
    if not bool(rc.get("connected")):
        return _reject(E.E_RC_LINK, ["遥控链路未连接（rc.connected=false）"], {"rc": dict(rc)})
    return None


def _stage_range(
    tool: str, args: Dict[str, Any], telemetry: dict, config: SafetyConfig
) -> Optional[SafetyDecision]:
    if tool == "takeoff":
        altitude = float(args.get("altitude_m", 0.0))
        if altitude <= 0:
            return _reject(
                E.E_PARAM_RANGE,
                ["takeoff.altitude_m=%.2f 必须 > 0" % altitude],
                {"altitude_m": altitude},
            )
        if altitude > float(config.max_alt_m):
            return _reject(
                E.E_ALT_LIMIT,
                ["takeoff.altitude_m=%.2f > 最大相对高度 %.1f m" % (altitude, config.max_alt_m)],
                {"altitude_m": altitude, "max_alt_m": float(config.max_alt_m)},
            )
        return None

    if tool == "goto_waypoints":
        mission = args.get("mission") or {}
        waypoints = normalize_mission(mission, origin=config.origin)["waypoints"]
        for index, waypoint in enumerate(waypoints):
            altitude = float(waypoint["alt_rel_m"])
            if altitude <= 0:
                return _reject(
                    E.E_PARAM_RANGE,
                    ["mission.waypoints[%d].alt_rel_m=%.2f 必须 > 0" % (index, altitude)],
                    {"waypoint": index, "alt_rel_m": altitude},
                )
            if altitude > float(config.max_alt_m):
                return _reject(
                    E.E_ALT_LIMIT,
                    [
                        "mission.waypoints[%d].alt_rel_m=%.2f > 最大相对高度 %.1f m"
                        % (index, altitude, config.max_alt_m)
                    ],
                    {"waypoint": index, "alt_rel_m": altitude, "max_alt_m": float(config.max_alt_m)},
                )
            speed = float(waypoint["speed_mps"])
            if speed <= 0:
                return _reject(
                    E.E_PARAM_RANGE,
                    ["mission.waypoints[%d].speed_mps=%.2f 必须 > 0" % (index, speed)],
                    {"waypoint": index, "speed_mps": speed},
                )
            if speed > float(config.max_speed_mps):
                return _reject(
                    E.E_SPEED_LIMIT,
                    [
                        "mission.waypoints[%d].speed_mps=%.2f > 最大速度 %.1f m/s"
                        % (index, speed, config.max_speed_mps)
                    ],
                    {"waypoint": index, "speed_mps": speed, "max_speed_mps": float(config.max_speed_mps)},
                )
            pitch = float(waypoint["gimbal_pitch_deg"])
            if not (-90.0 <= pitch <= 0.0):
                return _reject(
                    E.E_PARAM_RANGE,
                    ["mission.waypoints[%d].gimbal_pitch_deg=%.2f 必须在 [-90, 0]" % (index, pitch)],
                    {"waypoint": index, "gimbal_pitch_deg": pitch},
                )
        interval = args.get("photo_interval_s")
        if interval is not None:
            interval = float(interval)
            if not (0.0 <= interval <= 10.0):
                return _reject(
                    E.E_PARAM_RANGE,
                    ["goto_waypoints.photo_interval_s=%.2f 必须在 [0, 10]" % interval],
                    {"photo_interval_s": interval},
                )
        return None

    if tool == "set_gimbal":
        pitch = float(args.get("pitch_deg", 0.0))
        if not (-90.0 <= pitch <= 0.0):
            return _reject(
                E.E_PARAM_RANGE,
                ["set_gimbal.pitch_deg=%.2f 必须在 [-90, 0]（-90=正下，0=水平）" % pitch],
                {"pitch_deg": pitch},
            )
        yaw = args.get("yaw_deg")
        if yaw is not None:
            yaw = float(yaw)
            if not (-180.0 <= yaw <= 180.0):
                return _reject(
                    E.E_PARAM_RANGE,
                    ["set_gimbal.yaw_deg=%.2f 必须在 [-180, 180]" % yaw],
                    {"yaw_deg": yaw},
                )
        return None

    if tool == "capture_photo":
        count = float(args.get("count", 1))
        if count != int(count) or not (1 <= int(count) <= 20):
            return _reject(
                E.E_PARAM_RANGE,
                ["capture_photo.count=%r 必须是 1..20 的整数" % (args.get("count"),)],
                {"count": count},
            )
        interval = float(args.get("interval_s", 1.0))
        if not (0.0 <= interval <= 10.0):
            return _reject(
                E.E_PARAM_RANGE,
                ["capture_photo.interval_s=%.2f 必须在 [0, 10]" % interval],
                {"interval_s": interval},
            )
        return None

    if tool == "abort":
        reason = str(args.get("reason", "")).strip()
        if not reason:
            return _reject(E.E_PARAM_RANGE, ["abort.reason 不能为空"], {"reason": args.get("reason")})
        return None

    if tool == "set_mode":
        target = args.get("mode")
        if target not in E.MODES:
            return _reject(E.E_SCHEMA, ["set_mode.mode=%r 必须是 dry_run|sim|real" % (target,)])
        return None

    if tool == "get_mission_status":
        mission_id = args.get("mission_id")
        if mission_id is not None and (not isinstance(mission_id, str) or not mission_id.strip()):
            return _reject(E.E_PARAM_RANGE, ["get_mission_status.mission_id 必须是非空字符串"])
        return None

    return None


def _fence_center(config: SafetyConfig) -> dict:
    fence = config.geofence or {}
    return fence.get("center") or {"lat": config.origin["lat"], "lon": config.origin["lon"]}


def _points_to_guard(
    tool: str, args: Dict[str, Any], telemetry: dict, config: SafetyConfig
) -> List[dict]:
    """返回需要做围栏/禁飞区检查的点：[{label,lat,lon,alt_rel_m}]。"""
    if tool == "takeoff":
        return [
            {
                "label": "takeoff",
                "lat": _number(telemetry.get("lat"), config.origin["lat"]),
                "lon": _number(telemetry.get("lon"), config.origin["lon"]),
                "alt_rel_m": 0.0,
            }
        ]
    if tool == "goto_waypoints":
        mission = args.get("mission") or {}
        waypoints = normalize_mission(mission, origin=config.origin)["waypoints"]
        return [
            {
                "label": "waypoint[%d]" % index,
                "lat": float(waypoint["lat"]),
                "lon": float(waypoint["lon"]),
                "alt_rel_m": float(waypoint["alt_rel_m"]),
            }
            for index, waypoint in enumerate(waypoints)
        ]
    return []


def _stage_geofence(
    tool: str, args: Dict[str, Any], telemetry: dict, config: SafetyConfig
) -> Optional[SafetyDecision]:
    points = _points_to_guard(tool, args, telemetry, config)
    if not points:
        return None
    center = _fence_center(config)
    radius = float((config.geofence or {}).get("radius_m", 0.0))
    for point in points:
        distance = haversine_m(point["lat"], point["lon"], center["lat"], center["lon"])
        if distance > radius + 1e-6:
            return _reject(
                E.E_GEOFENCE,
                [
                    "%s 距圆形围栏圆心 %.1f m > 半径 %.1f m"
                    % (point["label"], distance, radius)
                ],
                {
                    "label": point["label"],
                    "distance_m": round(distance, 3),
                    "radius_m": radius,
                    "center": center,
                },
            )
    return None


def _stage_no_fly(
    tool: str, args: Dict[str, Any], telemetry: dict, config: SafetyConfig
) -> Optional[SafetyDecision]:
    points = _points_to_guard(tool, args, telemetry, config)
    if not points:
        return None
    for point in points:
        for zone in config.no_fly_zones or []:
            alt_range = zone.get("alt_range_m") or [0.0, config.max_alt_m]
            low, high = float(alt_range[0]), float(alt_range[1])
            if not (low <= point["alt_rel_m"] <= high):
                continue
            polygon = zone.get("polygon") or []
            if polygon and point_in_polygon(point["lat"], point["lon"], polygon, origin=config.origin):
                return _reject(
                    E.E_NOFLY,
                    [
                        "%s 位于禁飞区 %r 内（高度 %.1f m ∈ [%.0f, %.0f]）"
                        % (point["label"], zone.get("name", "no_fly"), point["alt_rel_m"], low, high)
                    ],
                    {
                        "label": point["label"],
                        "zone": zone.get("name"),
                        "alt_rel_m": point["alt_rel_m"],
                        "alt_range_m": [low, high],
                    },
                )
    return None


def estimate_mission_energy_pct(
    mission: dict,
    telemetry: dict,
    config: Optional[SafetyConfig] = None,
    home: Optional[dict] = None,
) -> Dict[str, Any]:
    """任务前能量估算（PROTOCOL.md §8 规则 6，用于 E_BATTERY_RTH）。

    简化模型（与 §10 仿真电量模型一致）：巡航 0.05%/s、爬升/下降 0.15%/s、
    悬停(到点动作前 0.5 s + 每航点) 0.04%/s，最后从末航点返航（10 m/s）+ 下降。
    返回 {mission_pct, return_pct, required_pct, battery_pct, reserve_pct, feasible}。
    """
    cfg = config or default_config()
    energy = cfg.energy
    waypoints = normalize_mission(mission, origin=cfg.origin)["waypoints"]
    current_lat = _number(telemetry.get("lat"), cfg.origin["lat"])
    current_lon = _number(telemetry.get("lon"), cfg.origin["lon"])
    current_alt = _number(telemetry.get("alt_abs_m"), cfg.origin["alt"])
    home_obj = home or (normalize_mission(mission, origin=cfg.origin)["home"])
    home_lat = float(home_obj["lat"])
    home_lon = float(home_obj["lon"])
    home_alt = float(home_obj["alt_abs_m"])

    cruise = float(energy["cruise_pct_per_s"])
    climb = float(energy["climb_pct_per_s"])
    descend = float(energy["descend_pct_per_s"])
    hover = float(energy["hover_pct_per_s"])
    climb_speed = float(energy["climb_speed_mps"])
    descend_speed = float(energy["descend_speed_mps"])
    rth_speed = float(energy["rth_speed_mps"])
    hover_time = float(energy.get("hover_before_action_s", 0.5))

    mission_pct = 0.0
    prev_lat, prev_lon, prev_alt = current_lat, current_lon, current_alt
    for waypoint in waypoints:
        horizontal = haversine_m(prev_lat, prev_lon, waypoint["lat"], waypoint["lon"])
        speed = max(float(waypoint["speed_mps"]), 0.1)
        mission_pct += horizontal / speed * cruise
        delta = float(waypoint["alt_abs_m"]) - prev_alt
        if delta > 0:
            mission_pct += delta / climb_speed * climb
        else:
            mission_pct += -delta / descend_speed * descend
        mission_pct += hover_time * hover
        prev_lat, prev_lon, prev_alt = waypoint["lat"], waypoint["lon"], waypoint["alt_abs_m"]
    last = waypoints[-1]
    horizontal_return = haversine_m(last["lat"], last["lon"], home_lat, home_lon)
    return_pct = horizontal_return / rth_speed * cruise
    return_pct += abs(last["alt_abs_m"] - home_alt) / descend_speed * descend
    return_pct += hover_time * hover
    battery = _number(telemetry.get("battery_pct"), 0.0)
    required = mission_pct + return_pct + float(cfg.rth_reserve_pct)
    return {
        "mission_pct": round(mission_pct, 4),
        "return_pct": round(return_pct, 4),
        "reserve_pct": float(cfg.rth_reserve_pct),
        "required_pct": round(required, 4),
        "battery_pct": round(battery, 4),
        "feasible": battery + 1e-9 >= required,
        "n_waypoints": len(waypoints),
    }


def _stage_rth_energy(
    tool: str, args: Dict[str, Any], telemetry: dict, config: SafetyConfig
) -> Optional[SafetyDecision]:
    if tool != "goto_waypoints":
        return None
    mission = args.get("mission") or {}
    estimate = estimate_mission_energy_pct(mission, telemetry, config)
    if not estimate["feasible"]:
        return _reject(
            E.E_BATTERY_RTH,
            [
                "返航电量估算不足：电池 %.1f%% < 任务+返航+保留 %.1f%%"
                % (estimate["battery_pct"], estimate["required_pct"])
            ],
            estimate,
        )
    return None


def _number(value: Any, fallback: float) -> float:
    try:
        if isinstance(value, bool):
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _collect_warnings(tool: str, telemetry: dict, config: SafetyConfig) -> List[str]:
    warnings: List[str] = []
    battery = _number(telemetry.get("battery_pct"), 100.0)
    if tool in ("takeoff", "goto_waypoints") and battery < float(config.min_takeoff_battery_pct) + 5.0:
        warnings.append("battery_pct=%.1f%% 接近起飞最低电量" % battery)
    if telemetry.get("state") == "returning":
        warnings.append("当前处于返航状态")
    return warnings


# --------------------------------------------------------------------- 主入口
def validate_command(
    tool: Any,
    args: Any,
    confirm: Any = None,
    telemetry: Optional[dict] = None,
    config: Optional[SafetyConfig] = None,
    active_mission_id: Optional[str] = None,
) -> SafetyDecision:
    """按 PROTOCOL.md §4 固定顺序校验一条 Agent 命令（纯函数）。

    参数：
      tool: 工具名（Any 以覆盖 tool=None/非字符串的对抗输入）
      args: 工具参数 dict
      confirm: 请求顶层 confirm（None/True/False）
      telemetry: §5 遥测快照（提供 state/battery/gps/rc/mode/位置）
      config: SafetyConfig（缺省加载 safety/config.json -> 默认值）
      active_mission_id: 当前执行中的 mission_id（用于 E_BUSY）
    """
    cfg = config or default_config()
    telemetry = telemetry or {}
    raw_args = args
    cleaned = _clean_args(args)
    state = telemetry.get("state", "idle")

    stages: List[Dict[str, Any]] = []

    def run_stage(name: str, rejection: Optional[SafetyDecision]) -> Optional[SafetyDecision]:
        stages.append({"stage": name, "ok": rejection is None})
        return rejection

    rejection = run_stage("schema", _stage_schema(tool, raw_args, cleaned))
    if rejection is None:
        rejection = run_stage("whitelist", None)  # 白名单已在 schema 阶段覆盖
    if rejection is None:
        rejection = run_stage("mode", _stage_mode(tool, cleaned, telemetry, cfg))
    if rejection is None:
        rejection = run_stage("confirm", _stage_confirm(tool, cleaned, confirm, cfg))
    if rejection is None:
        rejection = run_stage("state", _stage_state(tool, cleaned, state, active_mission_id))
    if rejection is None:
        rejection = run_stage("battery", _stage_battery(tool, telemetry, cfg))
    if rejection is None:
        rejection = run_stage("gps", _stage_gps(tool, telemetry, cfg))
    if rejection is None:
        rejection = run_stage("rc", _stage_rc(tool, telemetry, cfg))
    if rejection is None:
        rejection = run_stage("range", _stage_range(tool, cleaned, telemetry, cfg))
    if rejection is None:
        rejection = run_stage("geofence", _stage_geofence(tool, cleaned, telemetry, cfg))
    if rejection is None:
        rejection = run_stage("no_fly_zone", _stage_no_fly(tool, cleaned, telemetry, cfg))
    if rejection is None:
        rejection = run_stage("rth_energy", _stage_rth_energy(tool, cleaned, telemetry, cfg))

    if rejection is not None:
        rejection.stages = stages
        return rejection
    decision = SafetyDecision(allow=True, warnings=_collect_warnings(tool, telemetry, cfg))
    decision.stages = stages
    return decision


def preflight_checks(
    telemetry: Optional[dict] = None, config: Optional[SafetyConfig] = None
) -> Dict[str, Any]:
    """起飞前检查（PROTOCOL.md §4 preflight_check 返回结构）。

    返回 {"ok": True, "can_fly": bool, "checks": [{name,pass,detail}]}。
    """
    cfg = config or default_config()
    telemetry = telemetry or {}
    checks: List[Dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "pass": bool(passed), "detail": detail})

    mode = telemetry.get("mode", "sim")
    state = telemetry.get("state", "idle")
    battery = _number(telemetry.get("battery_pct"), 0.0)
    gps = telemetry.get("gps") or {}
    rc = telemetry.get("rc") or {}
    fix = int(_number(gps.get("fix"), 0))
    satellites = int(_number(gps.get("satellites"), 0))
    lat = _number(telemetry.get("lat"), cfg.origin["lat"])
    lon = _number(telemetry.get("lon"), cfg.origin["lon"])

    add("mode", mode in E.MODES and mode != "real", "mode=%s" % mode)
    add("state", state == "idle", "state=%s（需 idle）" % state)
    add(
        "battery",
        battery >= float(cfg.min_takeoff_battery_pct),
        "battery=%.1f%%（需>=%.1f%%）" % (battery, cfg.min_takeoff_battery_pct),
    )
    add(
        "gps",
        fix >= int(cfg.gps_min_fix) and satellites >= int(cfg.gps_min_satellites),
        "fix=%d（需>=%d）、satellites=%d（需>=%d）"
        % (fix, cfg.gps_min_fix, satellites, cfg.gps_min_satellites),
    )
    add("rc", (bool(rc.get("connected")) or not cfg.require_rc), "rc.connected=%r" % rc.get("connected"))
    center = _fence_center(cfg)
    radius = float((cfg.geofence or {}).get("radius_m", 0.0))
    distance = haversine_m(lat, lon, center["lat"], center["lon"])
    add("geofence", distance <= radius, "距围栏圆心 %.1fm / 半径 %.1fm" % (distance, radius))
    in_nfz = False
    nfz_name = None
    for zone in cfg.no_fly_zones or []:
        alt_range = zone.get("alt_range_m") or [0.0, cfg.max_alt_m]
        if 0.0 < float(alt_range[0]):
            continue
        if point_in_polygon(lat, lon, zone.get("polygon") or [], origin=cfg.origin):
            in_nfz, nfz_name = True, zone.get("name")
            break
    add("no_fly_zone", not in_nfz, "位于禁飞区 %r" % nfz_name if in_nfz else "不在禁飞区")
    add("altitude_limit", True, "max_alt_m=%.1f" % cfg.max_alt_m)
    add("real_mode", not cfg.allow_real_mode, "Phase1 real 模式不可用（预期）")

    can_fly = all(item["pass"] for item in checks)
    return {"ok": True, "can_fly": can_fly, "checks": checks}

def nominal_state(**overrides: Any) -> dict:
    """构造一份“正常可飞”的 §5 遥测字典（测试/兼容旧接口用）。"""
    telemetry = {
        "ts": "2026-11-08T17:30:00+08:00",
        "sim_time_s": 0.0,
        "state": "idle",
        "lat": 39.9042,
        "lon": 116.4074,
        "alt_rel_m": 0.0,
        "alt_abs_m": 43.0,
        "speed_mps": 0.0,
        "vertical_speed_mps": 0.0,
        "battery_pct": 100.0,
        "gimbal": {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
        "gps": {"fix": 3, "satellites": 24},
        "rc": {"connected": True, "signal": "good"},
        "mode": "sim",
        "mission_id": None,
        "home": {"lat": 39.9042, "lon": 116.4074, "alt_abs_m": 43.0},
    }
    telemetry.update(overrides)
    return telemetry


class SafetyValidator:
    """面向对象的轻薄包装（等价于 validate_command / preflight_checks 纯函数）。"""

    def __init__(self, config: Optional[SafetyConfig] = None):
        self.config = config or default_config()

    def validate(
        self,
        tool: Any,
        args: Any = None,
        confirm: Any = None,
        telemetry: Optional[dict] = None,
        active_mission_id: Optional[str] = None,
    ) -> SafetyDecision:
        return validate_command(
            tool,
            args,
            confirm=confirm,
            telemetry=telemetry,
            config=self.config,
            active_mission_id=active_mission_id,
        )

    def preflight(self, telemetry: Optional[dict] = None) -> Dict[str, Any]:
        return preflight_checks(telemetry, self.config)

    def estimate_energy(self, mission: dict, telemetry: dict) -> Dict[str, Any]:
        return estimate_mission_energy_pct(mission, telemetry, self.config)
