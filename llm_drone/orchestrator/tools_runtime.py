# -*- coding: utf-8 -*-
"""工具分发运行时（Orchestrator 侧）。

职责（PROTOCOL.md §1/§3/§4/§6/§8 + tools.json）：
  - 严格按 spec/tools.json 参数 schema 校验（未知工具 → E_UNKNOWN_TOOL；参数 → E_SCHEMA）；
  - **confirm 门禁**：requires_confirm 的飞行/高风险工具若无 confirm=true → 直接返回结构化
    E_CONFIRM_REQUIRED，绝不发给 Agent（A5 场景依赖此行为）；
  - executor=orchestrator（plan_capture_mission / orbit）由本模块确定性规划，plan_id→mission 存内存；
  - executor=agent 的工具转发 Drone Agent；goto_waypoints 把 plan_id 展开成完整 §6 mission，
    Agent 级 args = {"mission": <§6>, "photo_interval_s": n}（spec §4），confirm 走请求顶层；
  - takeoff/goto/return_to_home/land 之后轮询 Agent 状态/任务记录（scripted 对抗场景可关等待）；
  - 统一返回 {"ok","tool","error_code","error","result"(回给 LLM 的紧凑 JSON),"meta"}。
"""
from __future__ import annotations

import copy
import json
import time
from typing import Any

try:
    from . import planner, prompts
except ImportError:  # pragma: no cover
    import planner  # type: ignore
    import prompts  # type: ignore

E_SCHEMA = "E_SCHEMA"
E_CONFIRM_REQUIRED = "E_CONFIRM_REQUIRED"
E_UNKNOWN_TOOL = "E_UNKNOWN_TOOL"
E_PLAN_NOT_FOUND = "E_PLAN_NOT_FOUND"
E_INTERNAL = "E_INTERNAL"

DEFAULT_MISSION_TIMEOUT_S = 240.0
DEFAULT_STATE_TIMEOUT_S = 120.0
TELEMETRY_KEYS = ("ts", "sim_time_s", "state", "lat", "lon", "alt_rel_m", "alt_abs_m",
                  "speed_mps", "vertical_speed_mps", "battery_pct", "gimbal", "gps", "rc",
                  "mode", "mission_id")

#: 兼容旧版 Agent：把内部 rule/违规名映射回 spec §8.2 错误码（新 Agent 直接返回 E_* 时原样透传）。
RULE_TO_ERROR_CODE = {
    "MAX_ALTITUDE": "E_ALT_LIMIT", "ALT_LIMIT": "E_ALT_LIMIT", "MAX_ALT": "E_ALT_LIMIT",
    "MAX_SPEED": "E_SPEED_LIMIT", "SPEED_LIMIT": "E_SPEED_LIMIT",
    "GEOFENCE": "E_GEOFENCE", "OUTSIDE_FENCE": "E_GEOFENCE", "FENCE": "E_GEOFENCE",
    "NO_FLY_ZONE": "E_NOFLY", "NOFLY": "E_NOFLY", "NO_FLY": "E_NOFLY",
    "LOW_BATTERY": "E_BATTERY_TAKEOFF", "BATTERY_TAKEOFF": "E_BATTERY_TAKEOFF",
    "LOW_BATTERY_RTH": "E_BATTERY_RTH", "BATTERY_RTH": "E_BATTERY_RTH",
    "GPS_QUALITY": "E_GPS", "GPS": "E_GPS",
    "RC_DISCONNECTED": "E_RC_LINK", "RC_LINK": "E_RC_LINK",
    "CONFIRMATION_REQUIRED": "E_CONFIRM_REQUIRED", "CONFIRM_REQUIRED": "E_CONFIRM_REQUIRED",
    "PARAM_RANGE": "E_PARAM_RANGE", "INVALID_ARGS": "E_SCHEMA", "SCHEMA": "E_SCHEMA",
    "COMMAND_NOT_ALLOWED": "E_UNKNOWN_TOOL", "UNKNOWN_TOOL": "E_UNKNOWN_TOOL",
    "MODE_FORBIDDEN": "E_REAL_NOT_AVAILABLE", "PHASE1_REAL_FORBIDDEN": "E_REAL_NOT_AVAILABLE",
    "ALREADY_AIRBORNE": "E_STATE", "NOT_AIRBORNE": "E_STATE", "STATE": "E_STATE",
    "BUSY": "E_BUSY",
}


def normalize_agent_error(error: dict | None) -> tuple:
    """把 Agent 的 error 归一化为 spec §8.2 错误码；返回 (code, message, details, raw_rule)。"""
    error = error or {}
    raw_code = str(error.get("code") or "")
    rule = error.get("rule")
    candidates = [raw_code, rule]
    for violation in error.get("violations") or []:
        if isinstance(violation, dict):
            candidates.extend([violation.get("code"), violation.get("rule")])
    code = None
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.startswith("E_") and candidate != "E_SAFETY_REJECTED":
            code = candidate
            break
    if code is None and isinstance(rule, str):
        code = RULE_TO_ERROR_CODE.get(rule.upper())
    if code is None:
        code = raw_code if raw_code.startswith("E_") else "E_INTERNAL"
    message = error.get("message")
    if not message:
        reasons = error.get("violations") or []
        if isinstance(reasons, list) and reasons and isinstance(reasons[0], dict):
            message = reasons[0].get("message")
    details = {"agent_error": error}
    if rule:
        details["rule"] = rule
    return code, str(message or "Agent 返回失败"), details, rule


# ---- spec/tools.json JSON Schema 校验 --------------------------------------
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


def _type_ok(value: Any, tname: str) -> bool:
    if tname == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if tname == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if tname == "boolean":
        return isinstance(value, bool)
    if tname == "string":
        return isinstance(value, str)
    if tname == "object":
        return isinstance(value, dict)
    if tname == "array":
        return isinstance(value, list)
    if tname == "null":
        return value is None
    return True


def _validate_node(schema: dict, value: Any, path: str, errors: list) -> None:
    tname = schema.get("type")
    if tname and not _type_ok(value, tname):
        errors.append(f"{path}: 类型应为 {tname}，实际 {_type_name(value)}")
        return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: 取值必须是 {schema['enum']} 之一，实际 {value!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: 应 >= {schema['minimum']}，实际 {value}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: 应 <= {schema['maximum']}，实际 {value}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: 至少 {schema['minItems']} 项")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: 最多 {schema['maxItems']} 项")
        items = schema.get("items")
        if isinstance(items, dict):
            for i, item in enumerate(value):
                _validate_node(items, item, f"{path}[{i}]", errors)
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: 缺少必填参数 {key}")
        props = schema.get("properties") or {}
        for key, prop_schema in props.items():
            if key in value:
                _validate_node(prop_schema, value[key], f"{path}.{key}", errors)
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errors.append(f"{path}: 不支持参数 {key}")


def validate_tool_args(name: str, args: Any, meta: dict | None = None) -> list:
    """按 spec/tools.json 参数 schema 校验，返回错误列表（空=通过）。confirm 由门禁单独处理。"""
    meta = meta if meta is not None else prompts.tool_meta()
    if name not in meta:
        return [f"未知工具 {name!r}（不在 spec/tools.json 白名单）"]
    if not isinstance(args, dict):
        return [f"参数必须是 JSON 对象，实际 {_type_name(args)}"]
    schema = copy.deepcopy(meta[name]["parameters"])
    check_args = args
    if meta[name]["requires_confirm"]:
        props = schema.get("properties") or {}
        props.pop("confirm", None)
        schema["properties"] = props
        schema["required"] = [r for r in (schema.get("required") or []) if r != "confirm"]
        check_args = {k: v for k, v in args.items() if k != "confirm"}
    errors: list = []
    _validate_node(schema, check_args, name, errors)
    # 跨字段业务规则（JSON Schema 表达不便）
    if name == "goto_waypoints":
        has_plan = isinstance(check_args.get("plan_id"), str) and check_args["plan_id"].strip() != ""
        has_wp = isinstance(check_args.get("waypoints"), list) and len(check_args["waypoints"]) > 0
        if has_plan and has_wp:
            errors.append("goto_waypoints: plan_id 与 waypoints 只能二选一")
        if not has_plan and not has_wp:
            errors.append("goto_waypoints: 必须提供 plan_id 或 waypoints 之一")
    return errors


def _trim_telemetry(tel: dict | None) -> dict:
    if not isinstance(tel, dict):
        return {}
    return {key: tel[key] for key in TELEMETRY_KEYS if key in tel}


class ToolRuntime:
    """工具执行器：本地规划 + Agent 转发 + confirm 门禁 + plan_id 展开。"""

    def __init__(self, agent: Any, run_id: str = "", wait_missions: bool = True,
                 mission_timeout_s: float = DEFAULT_MISSION_TIMEOUT_S,
                 state_timeout_s: float = DEFAULT_STATE_TIMEOUT_S,
                 safety: dict | None = None) -> None:
        self.agent = agent
        self.run_id = run_id
        self.wait_missions = bool(wait_missions)
        self.mission_timeout_s = float(mission_timeout_s)
        self.state_timeout_s = float(state_timeout_s)
        self.safety = safety
        self.meta = prompts.tool_meta()
        self.spec = prompts.load_tools_spec()
        self.plans: dict[str, dict] = {}
        self.last_plan_id: str | None = None
        self.last_mission_id: str | None = None
        self.last_mission: dict | None = None
        self.last_mission_args: dict | None = None
        self.home: dict | None = None
        self._cmd_seq = 0
        self.read_calls: dict[str, int] = {}
        self.repeat_blocked = 0
        self.max_repeat_read = 2   # 同一只读工具累计调用上限（熔断，防止 4B 模型死循环 get_telemetry）

    # ---- 结果封装 -----------------------------------------------------------
    @staticmethod
    def _ok(name: str, result: dict, meta: dict | None = None) -> dict:
        return {"ok": True, "tool": name, "error_code": None, "error": None,
                "result": result, "meta": meta or {}}

    @staticmethod
    def _fail(name: str, code: str, message: str, details: dict | None = None,
              result_extra: dict | None = None, meta: dict | None = None) -> dict:
        error = {"code": code, "message": message, "details": details or {}}
        result = {"ok": False, "tool": name, "error": error}
        if result_extra:
            result.update(result_extra)
        return {"ok": False, "tool": name, "error_code": code, "error": error,
                "result": result, "meta": meta or {}}

    # ---- 起飞点 -------------------------------------------------------------
    def get_home(self, refresh: bool = False) -> dict:
        if self.home is not None and not refresh:
            return dict(self.home)
        telemetry = self.agent.telemetry()
        if isinstance(telemetry, dict) and telemetry.get("ok") is not False:
            self.home = planner.home_from_telemetry(telemetry)
        else:
            self.home = planner.home_from_telemetry(None)
        return dict(self.home)

    # ---- 主入口 -------------------------------------------------------------
    def execute(self, name: str, args: Any) -> dict:
        meta = self.meta.get(name)
        if meta is None:
            return self._fail(name, E_UNKNOWN_TOOL,
                              f"未知工具 {name!r}；可用工具：{', '.join(sorted(self.meta))}")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return self._fail(name, E_SCHEMA, "工具参数必须是 JSON 对象")
        # 1) confirm 门禁（先于任何 Agent 调用）
        if meta["requires_confirm"] and args.get("confirm") is not True:
            return self._fail(
                name, E_CONFIRM_REQUIRED,
                f"{name} 属于飞行/高风险指令，必须带 confirm=true（用户明确确认后）；已拒绝，未发送给 Agent",
                details={"tool": name, "confirm": args.get("confirm")},
                meta={"gate": "confirm", "forwarded": False})
        # 2) 只读工具重复调用熔断（4B 模型常见死循环：反复 get_telemetry）
        if name in ("get_telemetry", "preflight_check"):
            used = int(self.read_calls.get(name, 0))
            if used >= self.max_repeat_read:
                self.repeat_blocked += 1
                return self._ok(name, {
                    "ok": True,
                    "guidance": (f"{name} 已调用 {used} 次，结果已足够，请勿重复调用。"
                                 "下一步应调用 plan_capture_mission 生成计划（若尚未规划），"
                                 "然后 takeoff(confirm=true) → goto_waypoints(plan_id, confirm=true) → "
                                 "return_to_home/land。"),
                    "repeat_blocked": True,
                    "next_actions": ["plan_capture_mission", "takeoff"],
                }, meta={"repeat_blocked": True, "skipped_agent": True})
            self.read_calls[name] = used + 1
        # 3) schema 校验（严格按 tools.json）
        errors = validate_tool_args(name, args, self.meta)
        if errors:
            return self._fail(name, E_SCHEMA, "参数校验失败：" + "；".join(errors),
                              details={"errors": errors}, meta={"gate": "schema", "forwarded": False})
        # 3) 分发
        try:
            if meta["executor"] == "orchestrator":
                return self._execute_local(name, args, meta)
            return self._execute_agent(name, args, meta)
        except ValueError as exc:
            return self._fail(name, "E_PARAM_RANGE", str(exc))
        except Exception as exc:  # noqa: BLE001 - 兜底保证循环不断
            return self._fail(name, E_INTERNAL, f"{type(exc).__name__}: {exc}")

    # ---- 本地规划工具 -------------------------------------------------------
    def _store_plan(self, plan: dict) -> str:
        plan_id = plan["plan_id"]
        self.plans[plan_id] = plan
        self.last_plan_id = plan_id
        return plan_id

    def _execute_local(self, name: str, args: dict, meta: dict) -> dict:
        if name == "plan_capture_mission":
            plan = planner.plan_capture_mission(args, home=self.get_home(), safety=self.safety)
            self._store_plan(plan)
            mission = plan["mission"]
            result = {
                "ok": True,
                "plan_id": plan["plan_id"],
                "pattern": plan["pattern"],
                "summary": plan["summary"],
                "estimates": plan["estimates"],
                "bounds": plan["bounds"],
                "warnings": plan["warnings"],
                "photo_interval_s": plan["photo_interval_s"],
                "note": ("计划已生成（未飞行）。用户原始请求已授权本次执行：下一步请直接调用 "
                         "takeoff(altitude_m=<计划航高>, confirm=true)，然后 goto_waypoints("
                         "plan_id=..., confirm=true) 执行；完成后调用 return_to_home 或 land。不要再停下来询问用户。"),
            }
            return self._ok(name, result, meta={
                "plan_id": plan["plan_id"], "pattern": plan["pattern"],
                "altitude_m": plan["params"].get("altitude_m"),
                "n_waypoints": len(mission["waypoints"]),
                "n_photos": mission["stats"]["n_photos"], "summary": plan["summary"]})
        if name == "orbit":
            # orbit 会展开为 goto_waypoints 直接执行，因此要求已起飞（否则 Agent 会 E_STATE）
            telemetry = self.agent.telemetry()
            state = telemetry.get("state") if isinstance(telemetry, dict) else None
            if state not in ("hovering", "mission"):
                alt = float(args.get("altitude_m") or 0)
                return self._fail(
                    name, "E_STATE",
                    f"orbit 会直接执行航点任务，需要先起飞（当前 state={state!r}）。"
                    f"请先调用 takeoff(altitude_m={alt:g}, confirm=true)，再重试 orbit。",
                    details={"state": state,
                             "next_actions": [f"takeoff(altitude_m={alt:g}, confirm=true)",
                                              "orbit(..., confirm=true)"]})
            plan = planner.plan_orbit(args, home=self.get_home(), safety=self.safety)
            self._store_plan(plan)
            forward = self._goto_mission(plan["mission"], plan["photo_interval_s"],
                                         plan_id=plan["plan_id"], tool="orbit")
            if not forward["ok"]:
                forward["result"].setdefault("error", {})["details"].setdefault(
                    "plan_id", plan["plan_id"])
                return forward
            result = dict(forward["result"])
            result["plan_id"] = plan["plan_id"]
            return self._ok(name, result, meta=forward["meta"])
        return self._fail(name, E_UNKNOWN_TOOL, f"executor=orchestrator 未实现的工具 {name!r}")

    # ---- Agent 工具 ---------------------------------------------------------
    def _execute_agent(self, name: str, args: dict, meta: dict) -> dict:
        if name == "get_telemetry":
            telemetry = self.agent.telemetry()
            if not isinstance(telemetry, dict) or telemetry.get("ok") is False:
                return self._agent_error(name, telemetry)
            return self._ok(name, {"ok": True, "telemetry": _trim_telemetry(telemetry)})
        if name == "preflight_check":
            return self._finish(name, self._raw_command(name, {}))
        if name == "takeoff":
            resp = self._raw_command(name, {"altitude_m": args["altitude_m"]}, confirm=True)
            if not resp.get("ok"):
                return self._agent_error(name, resp)
            telemetry = self.agent.wait_state(["hovering", "mission"],
                                              timeout_s=self.state_timeout_s)
            state = telemetry.get("state")
            result = {"ok": state in ("hovering", "mission"), "state": state,
                      "alt_rel_m": telemetry.get("alt_rel_m"),
                      "battery_pct": telemetry.get("battery_pct"),
                      "telemetry": _trim_telemetry(telemetry)}
            if telemetry.get("timed_out"):
                result["warning"] = "等待进入悬停超时（遥测可能仍在爬升）"
            return self._ok(name, result, meta={"state": state})
        if name == "goto_waypoints":
            return self._goto_waypoints(args)
        if name in ("return_to_home", "land"):
            resp = self._raw_command(name, {}, confirm=False)
            if not resp.get("ok"):
                return self._agent_error(name, resp)
            telemetry = self.agent.wait_state(["idle"], timeout_s=self.state_timeout_s)
            state = telemetry.get("state")
            result = {"ok": state == "idle", "state": state,
                      "alt_rel_m": telemetry.get("alt_rel_m"),
                      "battery_pct": telemetry.get("battery_pct"),
                      "telemetry": _trim_telemetry(telemetry)}
            if state != "idle":
                return self._fail(name, "E_STATE",
                                  f"{name} 后未在 {self.state_timeout_s:.0f}s 内回到 idle（state={state}）",
                                  result_extra=result)
            return self._ok(name, result, meta={"state": state})
        if name == "set_gimbal":
            cmd = {"pitch_deg": args["pitch_deg"]}
            if "yaw_deg" in args:
                cmd["yaw_deg"] = args["yaw_deg"]
            return self._finish(name, self._raw_command(name, cmd))
        if name == "capture_photo":
            cmd = {key: args[key] for key in ("count", "interval_s") if key in args}
            return self._finish(name, self._raw_command(name, cmd))
        if name in ("start_video", "stop_video"):
            return self._finish(name, self._raw_command(name, {}))
        if name == "abort":
            return self._finish(name, self._raw_command(name, {"reason": args.get("reason", "")}))
        if name == "get_mission_status":
            return self._mission_status(args)
        if name == "set_mode":
            return self._finish(name, self._raw_command(name, {"mode": args["mode"]}, confirm=True))
        return self._fail(name, E_UNKNOWN_TOOL, f"Agent 侧未实现的工具 {name!r}")

    # ---- Agent 调用辅助 -----------------------------------------------------
    def _next_command_id(self, name: str) -> str:
        self._cmd_seq += 1
        return f"c-{self._cmd_seq:04d}"

    def _raw_command(self, tool: str, args: dict, confirm: bool = False) -> dict:
        command_id = self._next_command_id(tool)
        resp = self.agent.command(tool, args, confirm=confirm, run_id=self.run_id,
                                  command_id=command_id)
        if not isinstance(resp, dict):
            return {"ok": False, "error": {"code": E_INTERNAL, "message": "Agent 返回非对象"}}
        return resp

    def _finish(self, name: str, resp: dict) -> dict:
        if not isinstance(resp, dict) or resp.get("ok") is False:
            return self._agent_error(name, resp)
        result = {k: v for k, v in resp.items()
                  if k not in ("telemetry", "telemetry_snapshot", "warnings", "idempotent_replay")}
        result["ok"] = True
        telemetry = resp.get("telemetry") or resp.get("telemetry_snapshot")
        if telemetry:
            result["telemetry"] = _trim_telemetry(telemetry)
        if resp.get("warnings"):
            result["warnings"] = resp["warnings"]
        return self._ok(name, result)

    def _agent_error(self, name: str, resp: Any) -> dict:
        resp = resp if isinstance(resp, dict) else {}
        code, message, details, raw_rule = normalize_agent_error(resp.get("error"))
        extra = {"state": resp.get("state")}
        if code == "E_STATE":
            next_actions = []
            state = resp.get("state")
            if state in ("idle", "landed"):
                next_actions = ["takeoff(confirm=true)"]
            elif name == "takeoff":
                next_actions = ["goto_waypoints(plan_id=..., confirm=true)"]
            details = dict(details or {})
            details["next_actions"] = next_actions
        telemetry = resp.get("telemetry") or resp.get("telemetry_snapshot")
        if telemetry:
            extra["telemetry"] = _trim_telemetry(telemetry)
        return self._fail(name, code, message, details=details,
                          result_extra=extra, meta={"source": "agent", "rule": raw_rule})

    def _extract_mission_id(self, resp: dict) -> str | None:
        mission_id = resp.get("mission_id")
        if not mission_id:
            rec = resp.get("mission") or resp.get("record") or {}
            if isinstance(rec, dict):
                mission_id = rec.get("mission_id")
        if not mission_id:
            listing = self.agent.missions(limit=1)
            missions = listing.get("missions") or []
            if missions:
                mission_id = missions[0].get("mission_id")
        return mission_id

    def _mission_result(self, name: str, mission_id: str, plan_id: str | None,
                        resp: dict) -> dict:
        if self.wait_missions:
            record = self.agent.wait_mission(mission_id, timeout_s=self.mission_timeout_s)
        else:
            record = {"ok": True, "state": resp.get("state") or "executing",
                      "mission_id": mission_id}
        state = record.get("state")
        photos = record.get("photos") or []
        stats = record.get("stats") or {}
        n_photos = len(photos) if photos else int(stats.get("n_photos") or 0)
        if not self.wait_missions:
            # 异步模式（对抗场景注入用）：命令已受理，不等待任务完成
            result = {"ok": True, "async": True, "mission_id": mission_id, "state": state,
                      "n_photos": n_photos, "note": "任务已开始执行（异步；后续用 get_mission_status 查询）"}
            if plan_id:
                result["plan_id"] = plan_id
            return self._ok(name, result, meta={"mission_id": mission_id, "state": state,
                                                "async": True, "plan_id": plan_id})
        result = {
            "ok": state == "completed",
            "mission_id": mission_id,
            "state": state,
            "progress_pct": record.get("progress_pct"),
            "n_photos": n_photos,
            "photos": [p.get("file") for p in photos[:8] if isinstance(p, dict)],
            "stats": stats,
            "mission_error": record.get("error"),
        }
        if plan_id:
            result["plan_id"] = plan_id
        if state == "completed":
            return self._ok(name, result, meta={"mission_id": mission_id, "state": state,
                                                "n_photos": n_photos, "plan_id": plan_id})
        if record.get("timed_out"):
            return self._fail(name, "E_MISSION_TIMEOUT",
                              f"等待任务 {mission_id} 完成超时（state={state}）",
                              result_extra=result, meta={"mission_id": mission_id})
        error = record.get("error") or {}
        code = error.get("code") or ("E_MISSION_" + str(state).upper() if state else "E_MISSION_FAILED")
        message = error.get("message") or f"任务 {mission_id} 未完成（state={state}）"
        return self._fail(name, code, message, details=error.get("details") or {},
                          result_extra=result, meta={"mission_id": mission_id, "state": state})

    def _goto_mission(self, mission: dict, photo_interval_s: float,
                      plan_id: str | None = None, tool: str = "goto_waypoints") -> dict:
        agent_args = {"mission": mission, "photo_interval_s": float(photo_interval_s)}
        resp = self._raw_command("goto_waypoints", agent_args, confirm=True)
        if not resp.get("ok"):
            return self._agent_error(tool, resp)
        mission_id = self._extract_mission_id(resp)
        if not mission_id:
            return self._fail(tool, "E_INTERNAL", "Agent 未返回 mission_id",
                              result_extra={"agent_response": resp})
        self.last_mission_id = mission_id
        self.last_mission = copy.deepcopy(mission)
        self.last_mission_args = copy.deepcopy(agent_args)
        return self._mission_result(tool, mission_id, plan_id, resp)

    def _goto_waypoints(self, args: dict) -> dict:
        plan_id = args.get("plan_id")
        if isinstance(plan_id, str) and plan_id.strip():
            plan = self.plans.get(plan_id)
            if plan is None:
                return self._fail(
                    "goto_waypoints", E_PLAN_NOT_FOUND,
                    f"不存在 plan_id={plan_id!r}（可能未规划或已失效）；请先调用 plan_capture_mission",
                    details={"known_plan_ids": sorted(self.plans)})
            mission = copy.deepcopy(plan["mission"])
            photo_interval = float(args.get("photo_interval_s", plan.get("photo_interval_s", 1.0)))
            return self._goto_mission(mission, photo_interval, plan_id=plan_id)
        try:
            plan = planner.mission_from_waypoints(
                args["waypoints"], home=self.get_home(),
                speed_mps=float(args.get("speed_mps", planner.DEFAULT_SPEED_MPS)),
                gimbal_pitch_deg=float(args.get("gimbal_pitch_deg", planner.DEFAULT_GIMBAL_PITCH)),
                take_photos=bool(args.get("take_photos", True)))
        except ValueError as exc:
            return self._fail("goto_waypoints", E_SCHEMA, f"waypoints 无法包装为 mission：{exc}")
        self._store_plan(plan)
        photo_interval = float(args.get("photo_interval_s", 1.0))
        return self._goto_mission(plan["mission"], photo_interval, plan_id=plan["plan_id"])

    def _mission_status(self, args: dict) -> dict:
        mission_id = args.get("mission_id")
        if mission_id:
            record = self.agent.mission(str(mission_id))
        else:
            listing = self.agent.missions(limit=1)
            if listing.get("ok") is False:
                return self._agent_error("get_mission_status", listing)
            missions = listing.get("missions") or []
            if not missions:
                return self._fail("get_mission_status", "E_MISSION_NOT_FOUND",
                                  "当前没有任务记录")
            record = missions[0]
        if not isinstance(record, dict) or record.get("ok") is False:
            return self._agent_error("get_mission_status", record)
        photos = record.get("photos") or []
        result = {
            "ok": True,
            "mission_id": record.get("mission_id"),
            "state": record.get("state"),
            "progress_pct": record.get("progress_pct"),
            "n_photos": len(photos) if photos else int((record.get("stats") or {}).get("n_photos") or 0),
            "photos": [p.get("file") for p in photos[:8] if isinstance(p, dict)],
            "stats": record.get("stats"),
            "error": record.get("error"),
        }
        return self._ok("get_mission_status", result)

    # ---- scripted 控制步 ----------------------------------------------------
    def control(self, control: dict) -> dict:
        """scripted 模式的控制动作：故障注入/等待状态（不经过 LLM 工具调用）。"""
        control = control or {}
        ctype = str(control.get("type") or "")
        if ctype == "sim_config":
            resp = self.agent.sim_config(control.get("config") or {})
            return {"ok": resp.get("ok", False), "control": control, "response": resp}
        if ctype == "wait_state":
            telemetry = self.agent.wait_state(control.get("states") or ["idle"],
                                              timeout_s=float(control.get("timeout_s", 120.0)))
            return {"ok": telemetry.get("state") in (control.get("states") or ["idle"]),
                    "control": control,
                    "response": {"state": telemetry.get("state"),
                                 "timed_out": telemetry.get("timed_out"),
                                 "telemetry": _trim_telemetry(telemetry)}}
        if ctype == "wait_mission":
            record = self.agent.wait_mission(str(control.get("mission_id") or self.last_mission_id),
                                             timeout_s=float(control.get("timeout_s", 240.0)))
            return {"ok": record.get("state") == "completed", "control": control,
                    "response": {"state": record.get("state"),
                                 "n_photos": len(record.get("photos") or []),
                                 "error": record.get("error")}}
        if ctype == "sleep":
            seconds = float(control.get("seconds", 1.0))
            time.sleep(max(0.0, seconds))
            return {"ok": True, "control": control, "response": {"slept_s": seconds}}
        return {"ok": False, "control": control,
                "response": {"error": {"code": E_INTERNAL, "message": f"未知控制步 {ctype!r}"}}}

    # ---- 快照 ---------------------------------------------------------------
    def snapshot(self) -> dict:
        return {"plans": sorted(self.plans), "last_plan_id": self.last_plan_id,
                "last_mission_id": self.last_mission_id, "home": dict(self.home or {}),
                "wait_missions": self.wait_missions}

    def latest_mission_record(self) -> dict | None:
        if not self.last_mission_id:
            return None
        record = self.agent.mission(self.last_mission_id)
        return record if isinstance(record, dict) else None


if __name__ == "__main__":
    class _FakeAgent:
        def telemetry(self):
            return {"ok": True, "state": "idle", "lat": 39.9042, "lon": 116.4074,
                    "alt_rel_m": 0.0, "alt_abs_m": 43.0, "battery_pct": 100.0,
                    "gimbal": {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
                    "gps": {"fix": 3, "satellites": 24}, "rc": {"connected": True},
                    "mode": "sim", "home": {"lat": 39.9042, "lon": 116.4074, "alt_abs_m": 43.0}}

        def command(self, tool, args=None, confirm=False, run_id="", command_id=None):
            return {"ok": True, "tool": tool, "state": "idle"}

        def missions(self, limit=10):
            return {"ok": True, "missions": []}

        def mission(self, mission_id):
            return {"ok": False, "error": {"code": "E_MISSION_NOT_FOUND"}}

        def sim_config(self, config):
            return {"ok": True, "config": config}

        def wait_state(self, states, timeout_s=120.0):
            tel = self.telemetry()
            tel["state"] = states[0]
            return tel

        def wait_mission(self, mission_id, timeout_s=240.0):
            return {"ok": True, "mission_id": mission_id, "state": "completed",
                    "photos": [], "stats": {"n_photos": 0}}

    rt = ToolRuntime(_FakeAgent(), run_id="selftest", wait_missions=True)
    for label, name, args in (
        ("未知工具", "fly_to_moon", {}),
        ("缺 confirm", "takeoff", {"altitude_m": 40}),
        ("非法参数", "takeoff", {"altitude_m": -5, "confirm": True}),
        ("规划", "plan_capture_mission", {"pattern": "grid", "center_lat": 39.9042,
                                          "center_lon": 116.4074, "altitude_m": 40,
                                          "radius_m": 28, "overlap": 0.7,
                                          "gimbal_pitch_deg": -45}),
    ):
        out = rt.execute(name, args)
        print(f"[{label}] ok={out['ok']} code={out['error_code']} "
              f"result={json.dumps(out['result'], ensure_ascii=False)[:220]}")
