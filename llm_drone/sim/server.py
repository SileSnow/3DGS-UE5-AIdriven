"""Phase-1 仿真 Drone Agent HTTP 服务（PROTOCOL.md §3，纯标准库）。

启动：
    cd dji_ue5_3dgs/llm_drone && python -m sim.server --port 8765 --time-scale 20

端点：
    GET  /v1/health              健康检查
    GET  /v1/telemetry           §5 遥测快照（直接返回对象，含 home）
    POST /v1/command             {command_id, tool, args, confirm?, run_id?}（command_id 幂等）
    GET  /v1/missions/{id}       §7.1 mission record
    GET  /v1/missions?limit=N    最近任务列表
    GET  /v1/audit?since_seq=N   §9.1 审计事件
    POST /v1/reset               {run_id?} 重置并将审计切换到 audit_<run_id>.jsonl
    POST /v1/sim/config          故障注入 {battery_pct?,gps_fix?,gps_satellites?,rc_connected?,time_scale?}

业务失败一律 HTTP 200 + {"ok":false,"error":{"code","message","details"?}}；
HTTP 4xx/5xx 仅用于协议/服务器错误。
"""

from __future__ import annotations

import json
import sys
import threading
import time
import traceback
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

_LLM_DRONE = Path(__file__).resolve().parents[1]
if str(_LLM_DRONE) not in sys.path:
    sys.path.insert(0, str(_LLM_DRONE))

from safety.audit import AuditManager, now_iso  # noqa: E402
from safety.config import load_config  # noqa: E402
from safety.errors import (  # noqa: E402
    E_INTERNAL,
    E_MISSION_NOT_FOUND,
    E_NOT_SUPPORTED,
    E_PARAM_RANGE,
    E_SCHEMA,
)
from safety.schemas import is_read_only  # noqa: E402
from safety.validator import validate_command  # noqa: E402

from .config import SIM_VERSION, SimConfig, parse_args  # noqa: E402
from .simulator import DroneSimulator, SimulatorError  # noqa: E402

MAX_BODY_BYTES = 2 * 1024 * 1024
MISSION_PATH_RE = None  # 延迟编译，避免额外 import
SIM_CONFIG_KEYS = ("battery_pct", "gps_fix", "gps_satellites", "rc_connected", "time_scale")


class AgentApp:
    """命令分发 + 幂等缓存 + 审计（与 HTTP 服务器解耦，便于测试）。"""

    def __init__(
        self,
        config: Optional[SimConfig] = None,
        safety_config: Optional[Any] = None,
        audit: Optional[AuditManager] = None,
        simulator: Optional[DroneSimulator] = None,
    ):
        self.config = config or SimConfig()
        self.safety = safety_config or load_config()
        self.audit = audit or AuditManager(
            self.config.audit_dir, self.config.run_id, echo=self.config.echo_audit
        )
        self.sim = simulator or DroneSimulator(
            config=self.config, safety_config=self.safety, audit=self.audit
        )
        self.lock = threading.RLock()
        self.idempotency: "OrderedDict[str, dict]" = OrderedDict()
        self.started_at = time.time()
        self.telemetry_history: List[dict] = []
        self.counters = {
            "commands": 0,
            "accepted": 0,
            "rejected": 0,
            "idempotent_replays": 0,
            "internal_errors": 0,
        }

    # ================================================================ 指令
    def handle_command(self, payload: Any) -> dict:
        with self.lock:
            if not isinstance(payload, dict):
                return self._business_error(None, None, E_SCHEMA, "请求体必须是 JSON object")
            command_id = payload.get("command_id")
            tool = payload.get("tool")
            if not isinstance(command_id, str) or not command_id.strip():
                return self._business_error(
                    command_id, tool, E_SCHEMA, "command_id 必须是非空字符串"
                )
            command_id = command_id.strip()
            cached = self.idempotency.get(command_id)
            if cached is not None:
                self.counters["idempotent_replays"] += 1
                self.audit.log(
                    "command_replayed",
                    tool=tool,
                    command_id=command_id,
                    decision="replay",
                )
                return json.loads(json.dumps(cached))

            raw_args = payload.get("args")
            if raw_args is None:
                raw_args = {}
            if not isinstance(raw_args, dict):
                return self._reject(
                    command_id,
                    tool,
                    None,
                    E_SCHEMA,
                    ["args: 期望 object，实际 %s" % type(raw_args).__name__],
                )
            args = dict(raw_args)
            embedded_confirm = args.pop("confirm", None)
            confirm = payload.get("confirm", embedded_confirm)
            self.counters["commands"] += 1
            self.audit.log(
                "command_received",
                tool=tool,
                command_id=command_id,
                args=args,
                confirm=confirm,
                decision="pending",
            )
            telemetry = self.sim.snapshot()
            decision = validate_command(
                tool,
                args,
                confirm=confirm,
                telemetry=telemetry,
                config=self.safety,
                active_mission_id=self.sim.active_mission_id,
            )
            self.audit.log(
                "safety_check",
                tool=tool,
                command_id=command_id,
                decision="allow" if decision.allow else "reject",
                reasons=list(decision.reasons),
                error_code=decision.error_code,
            )
            if not decision.allow:
                self.audit.log(
                    "command_rejected",
                    tool=tool,
                    command_id=command_id,
                    error_code=decision.error_code,
                    reasons=list(decision.reasons),
                    decision="reject",
                )
                self.counters["rejected"] += 1
                response = self._business_error(
                    command_id,
                    tool,
                    decision.error_code or E_SCHEMA,
                    (decision.reasons[0] if decision.reasons else "安全校验拒绝"),
                    details={"reasons": list(decision.reasons), **decision.details},
                )
                return self._cache_and_return(command_id, response)

            state_before = self.sim.state
            # dry_run：只校验不执行（读命令仍执行）
            if self.sim.mode == "dry_run" and not is_read_only(tool):
                self.audit.log(
                    "command_accepted",
                    tool=tool,
                    command_id=command_id,
                    state_before=state_before,
                    state_after=state_before,
                    decision="allow",
                    dry_run=True,
                )
                self.counters["accepted"] += 1
                response = self._ok_response(
                    command_id, tool, warnings=["dry_run: 参数已通过安全校验，未实际执行"]
                )
                return self._cache_and_return(command_id, response)

            try:
                extras = self._dispatch(tool, args)
            except SimulatorError as exc:
                self.audit.log(
                    "command_rejected",
                    tool=tool,
                    command_id=command_id,
                    error_code=exc.code,
                    reasons=[exc.message],
                    decision="reject",
                )
                self.counters["rejected"] += 1
                response = self._business_error(command_id, tool, exc.code, exc.message, details=exc.details)
                return self._cache_and_return(command_id, response)
            except Exception as exc:  # noqa: BLE001
                self.counters["internal_errors"] += 1
                self.audit.log(
                    "command_error",
                    tool=tool,
                    command_id=command_id,
                    error=repr(exc),
                    traceback=traceback.format_exc(),
                )
                response = self._business_error(command_id, tool, E_INTERNAL, "内部错误: %r" % (exc,))
                return self._cache_and_return(command_id, response)

            self.counters["accepted"] += 1
            self.audit.log(
                "command_accepted",
                tool=tool,
                command_id=command_id,
                state_before=state_before,
                state_after=self.sim.state,
                decision="allow",
            )
            warnings = list(decision.warnings) + list(extras.pop("warnings", []) or [])
            response = self._ok_response(command_id, tool, warnings=warnings, extras=extras)
            return self._cache_and_return(command_id, response)

    def _dispatch(self, tool: str, args: dict) -> dict:
        if tool == "get_telemetry":
            return {"telemetry_only": True}
        if tool == "preflight_check":
            return dict(self.sim.preflight())
        if tool == "takeoff":
            return self.sim.cmd_takeoff(args)
        if tool == "goto_waypoints":
            return self.sim.cmd_goto_waypoints(args)
        if tool == "set_gimbal":
            return self.sim.cmd_set_gimbal(args)
        if tool == "capture_photo":
            return self.sim.cmd_capture_photo(args)
        if tool == "start_video":
            return self.sim.cmd_start_video(args)
        if tool == "stop_video":
            return self.sim.cmd_stop_video(args)
        if tool == "return_to_home":
            return self.sim.cmd_return_to_home(args)
        if tool == "land":
            return self.sim.cmd_land(args)
        if tool == "abort":
            return self.sim.cmd_abort(args)
        if tool == "get_mission_status":
            return self.sim.cmd_get_mission_status(args)
        if tool == "set_mode":
            return self.sim.cmd_set_mode(args["mode"])
        raise SimulatorError(E_SCHEMA, "工具 %r 未实现" % (tool,))

    # -------------------------------------------------------------- 响应
    def _ok_response(
        self,
        command_id: Optional[str],
        tool: Optional[str],
        warnings: Optional[List[str]] = None,
        extras: Optional[dict] = None,
    ) -> dict:
        response: Dict[str, Any] = {
            "ok": True,
            "command_id": command_id,
            "tool": tool,
            "state": self.sim.state,
            "telemetry": self.sim.snapshot(),
        }
        if extras:
            for key, value in extras.items():
                if key in ("ok", "warnings"):
                    continue
                response[key] = value
        if warnings:
            response["warnings"] = list(warnings)
        else:
            response["warnings"] = []
        return response

    def _business_error(
        self,
        command_id: Optional[str],
        tool: Optional[str],
        code: str,
        message: str,
        details: Optional[dict] = None,
    ) -> dict:
        error: Dict[str, Any] = {"code": str(code), "message": str(message)}
        if details:
            error["details"] = details
        return {
            "ok": False,
            "command_id": command_id,
            "tool": tool,
            "state": self.sim.state,
            "error": error,
            "telemetry": self.sim.snapshot(),
        }

    def _reject(
        self, command_id, tool, confirm, code: str, reasons: List[str]
    ) -> dict:
        self.audit.log(
            "command_rejected",
            tool=tool,
            command_id=command_id,
            error_code=code,
            reasons=list(reasons),
            decision="reject",
        )
        self.counters["rejected"] += 1
        return self._business_error(command_id, tool, code, reasons[0] if reasons else code, {"reasons": reasons})

    def _cache_and_return(self, command_id: str, response: dict) -> dict:
        self.idempotency[command_id] = response
        while len(self.idempotency) > int(self.config.max_idempotency_cache):
            self.idempotency.popitem(last=False)
        return response

    # ================================================================ 端点
    def health(self) -> dict:
        with self.lock:
            return {
                "ok": True,
                "backend": "sim",
                "version": SIM_VERSION,
                "mode": self.sim.mode,
                "time_scale": float(self.config.time_scale),
                "state": self.sim.state,
                "ts": now_iso(),
                "uptime_s": round(time.time() - self.started_at, 2),
                "counters": dict(self.counters),
            }

    def telemetry(self) -> dict:
        with self.lock:
            return self.sim.snapshot()

    def telemetry_history_list(self, limit: int = 200) -> dict:
        with self.lock:
            items = self.telemetry_history[-max(1, int(limit)):]
            return {"ok": True, "telemetry": items}

    def missions(self, limit: int = 10) -> dict:
        with self.lock:
            return {"ok": True, "missions": self.sim.list_missions(limit)}

    def mission(self, mission_id: str) -> dict:
        with self.lock:
            record = self.sim.get_mission(mission_id)
            if record is None:
                return {
                    "ok": False,
                    "error": {
                        "code": E_MISSION_NOT_FOUND,
                        "message": "mission_id 不存在: %s" % mission_id,
                        "details": {"mission_id": mission_id},
                    },
                }
            return record

    def audit_events(self, since_seq: int = 0) -> dict:
        with self.lock:
            events = self.audit.read_events(int(since_seq))
            return {"ok": True, "events": events, "last_seq": self.audit.last_seq()}

    def reset(self, run_id: Optional[str] = None) -> dict:
        with self.lock:
            target_run = run_id if isinstance(run_id, str) and run_id.strip() else "default"
            self.audit.switch_run(target_run)
            self.sim.reset(log=False)
            self.idempotency.clear()
            self.telemetry_history.clear()
            self.audit.log("sim_reset", state="idle", run_id=self.audit.run_id)
            return {"ok": True, "state": "idle", "run_id": self.audit.run_id}

    def sim_config(self, payload: Any) -> dict:
        with self.lock:
            if not isinstance(payload, dict):
                return {"ok": False, "error": {"code": E_SCHEMA, "message": "请求体必须是 JSON object"}}
            unknown = set(payload.keys()) - set(SIM_CONFIG_KEYS)
            if unknown:
                return {
                    "ok": False,
                    "error": {
                        "code": E_SCHEMA,
                        "message": "未知配置字段: %s（允许 %s）" % (sorted(unknown), list(SIM_CONFIG_KEYS)),
                    },
                }
            errors: List[str] = []
            normalized: Dict[str, Any] = {}
            for key, value in payload.items():
                if key == "battery_pct":
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        errors.append("battery_pct: 期望 number")
                    elif not (0.0 <= float(value) <= 100.0):
                        errors.append("battery_pct: 必须在 [0,100]")
                    else:
                        normalized[key] = float(value)
                elif key in ("gps_fix", "gps_satellites"):
                    if isinstance(value, bool) or not isinstance(value, int):
                        errors.append("%s: 期望 integer" % key)
                    elif value < 0 or value > 100:
                        errors.append("%s: 必须在 [0,100]" % key)
                    else:
                        normalized[key] = int(value)
                elif key == "rc_connected":
                    if not isinstance(value, bool):
                        errors.append("rc_connected: 期望 boolean")
                    else:
                        normalized[key] = value
                elif key == "time_scale":
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        errors.append("time_scale: 期望 number")
                    elif not (0.1 <= float(value) <= 1000.0):
                        errors.append("time_scale: 必须在 [0.1,1000]")
                    else:
                        normalized[key] = float(value)
            if errors:
                return {"ok": False, "error": {"code": E_PARAM_RANGE, "message": "; ".join(errors)}}
            applied = self.sim.apply_sim_config(normalized)
            return {"ok": True, "config": applied}

    # ================================================================ 主循环
    def tick(self, dt: float) -> None:
        with self.lock:
            self.sim.advance(dt)
            snapshot = self.sim.snapshot()
            self.telemetry_history.append(snapshot)
            if len(self.telemetry_history) > 5000:
                self.telemetry_history = self.telemetry_history[-2500:]
            keyframe_seconds = 10.0
            previous = self.telemetry_history[-2] if len(self.telemetry_history) > 1 else None
            if previous is None or (int(self.sim.sim_time_s // keyframe_seconds) != int((self.sim.sim_time_s - dt) // keyframe_seconds)):
                self.audit.log(
                    "telemetry_keyframe",
                    state=self.sim.state,
                    battery_pct=round(self.sim.battery_pct, 2),
                    lat=round(self.sim.lat, 7),
                    lon=round(self.sim.lon, 7),
                    alt_rel_m=round(self.sim.alt_rel_m, 3),
                )


# ====================================================================== HTTP
class SimHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler_class, app: AgentApp):
        super().__init__(server_address, handler_class)
        self.app = app
        self.stop_event = threading.Event()
        self.tick_thread: Optional[threading.Thread] = None

    def start_tick(self) -> None:
        if self.tick_thread is not None:
            return
        self.tick_thread = threading.Thread(target=self._tick_loop, name="sim-tick", daemon=True)
        self.tick_thread.start()

    def _tick_loop(self) -> None:
        period = max(0.005, float(self.app.config.tick_wall_s))
        while not self.stop_event.wait(period):
            try:
                scale = float(self.app.config.time_scale)
                self.app.tick(period * scale)
            except Exception as exc:  # noqa: BLE001
                self.app.audit.log("tick_error", error=repr(exc))
                print("[sim] tick error: %r" % (exc,), file=sys.stderr)

    def shutdown_extra(self) -> None:
        self.stop_event.set()
        if self.tick_thread is not None and self.tick_thread.is_alive():
            self.tick_thread.join(timeout=2.0)


class SimRequestHandler(BaseHTTPRequestHandler):
    server_version = "llm-drone-sim/" + SIM_VERSION
    verbose = False

    # -------------------------------------------------------------- 工具
    def log_message(self, fmt, *args):  # noqa: A003
        if getattr(self.server, "verbose", False) or SimRequestHandler.verbose:
            print("[http] " + (fmt % args), file=sys.stderr)

    def _read_json(self) -> Tuple[Optional[Any], Optional[str]]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None, "Content-Length 非法"
        if length > MAX_BODY_BYTES:
            return None, "请求体过大"
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            return {}, None
        try:
            return json.loads(raw.decode("utf-8")), None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return None, "JSON 解析失败: %s" % (exc,)

    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _protocol_error(self, status: int, message: str) -> None:
        self._send(status, {"ok": False, "error": {"code": E_SCHEMA, "message": message}})

    # -------------------------------------------------------------- 路由
    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        app: AgentApp = self.server.app
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        if path == "/v1/health":
            return self._send(200, app.health())
        if path == "/v1/telemetry":
            return self._send(200, app.telemetry())
        if path == "/v1/telemetry/history":
            limit = _int_param(query, "limit", 200)
            return self._send(200, app.telemetry_history_list(limit))
        if path == "/v1/missions":
            limit = _int_param(query, "limit", 10)
            return self._send(200, app.missions(limit))
        if path.startswith("/v1/missions/"):
            mission_id = path[len("/v1/missions/"):]
            return self._send(200, app.mission(mission_id))
        if path == "/v1/audit":
            since_seq = _int_param(query, "since_seq", 0)
            return self._send(200, app.audit_events(since_seq))
        if path == "/v1/safety/rules":
            return self._send(200, {"ok": True, "rules": app.safety.to_dict()})
        return self._send(404, {"ok": False, "error": {"code": E_SCHEMA, "message": "未知端点: %s" % path}})

    def do_POST(self):  # noqa: N802
        app: AgentApp = self.server.app
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        payload, error = self._read_json()
        if error is not None:
            return self._protocol_error(400, error)
        if path == "/v1/command":
            return self._send(200, app.handle_command(payload))
        if path == "/v1/reset":
            run_id = payload.get("run_id") if isinstance(payload, dict) else None
            return self._send(200, app.reset(run_id))
        if path == "/v1/sim/config":
            if app.config.backend != "sim":
                return self._send(
                    200,
                    {"ok": False, "error": {"code": E_NOT_SUPPORTED, "message": "仅仿真后端支持 /v1/sim/config"}},
                )
            return self._send(200, app.sim_config(payload))
        return self._send(404, {"ok": False, "error": {"code": E_SCHEMA, "message": "未知端点: %s" % path}})

    def do_PUT(self):  # noqa: N802
        self._protocol_error(405, "仅支持 GET/POST")

    do_DELETE = do_PUT


def _int_param(query: dict, name: str, default: int) -> int:
    try:
        return int((query.get(name) or [default])[0])
    except (TypeError, ValueError):
        return default


# ====================================================================== 生命周期
class ServerHandle:
    """服务器句柄（start/wait_ready/shutdown），供 main 与测试使用。"""

    def __init__(self, httpd: SimHTTPServer, app: AgentApp):
        self.httpd = httpd
        self.app = app
        self.host, self.port = httpd.server_address[0], httpd.server_address[1]
        self._thread: Optional[threading.Thread] = None
        self._closed = False

    @property
    def url(self) -> str:
        host = "127.0.0.1" if self.host in ("0.0.0.0", "") else self.host
        return "http://%s:%d" % (host, int(self.port))

    def start(self) -> "ServerHandle":
        if self._thread is None:
            self.httpd.start_tick()
            self._thread = threading.Thread(
                target=self.httpd.serve_forever,
                kwargs={"poll_interval": 0.05},
                name="sim-http",
                daemon=True,
            )
            self._thread.start()
        return self

    def serve_forever(self) -> None:
        self.httpd.start_tick()
        self.httpd.serve_forever(poll_interval=0.2)

    def wait_ready(self, timeout: float = 10.0) -> bool:
        import urllib.error
        import urllib.request

        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(self.url + "/v1/health", timeout=0.5) as response:
                    if response.status == 200:
                        return True
            except (urllib.error.URLError, OSError, ValueError):
                time.sleep(0.02)
        return False

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.app.audit.log("server_stop")
        except Exception:  # noqa: BLE001
            pass
        self.httpd.shutdown_extra()
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self.app.audit.close()

    def __enter__(self) -> "ServerHandle":
        return self.start()

    def __exit__(self, *exc: Any) -> bool:
        self.shutdown()
        return False


def create_agent_server(
    host: Optional[str] = None,
    port: Optional[int] = None,
    config: Optional[SimConfig] = None,
    safety_config: Optional[Any] = None,
    audit: Optional[AuditManager] = None,
    app: Optional[AgentApp] = None,
) -> ServerHandle:
    """创建（未启动）仿真 Drone Agent 服务器；port=0 由系统分配。"""
    cfg = config or SimConfig()
    if host is not None:
        cfg.host = host
    if port is not None:
        cfg.port = int(port)
    if app is None:
        app = AgentApp(config=cfg, safety_config=safety_config, audit=audit)
    httpd = SimHTTPServer((cfg.host, cfg.port), SimRequestHandler, app)
    return ServerHandle(httpd, app)


def main(argv: Optional[List[str]] = None) -> int:
    config = parse_args(argv)
    safety_config = load_config()
    audit = AuditManager(config.audit_dir, config.run_id, echo=config.echo_audit)
    app = AgentApp(config=config, safety_config=safety_config, audit=audit)
    handle = create_agent_server(config.host, config.port, config, safety_config, audit, app=app)
    app.audit.log(
        "server_start",
        backend="sim",
        version=SIM_VERSION,
        host=handle.host,
        port=handle.port,
        time_scale=config.time_scale,
        home=config.home,
    )
    print("=" * 78)
    print("[sim] LLM drone Phase-1 simulation agent v%s" % SIM_VERSION)
    print("[sim] url         : %s" % handle.url)
    print("[sim] mode/scale  : mode=%s time_scale=%s" % (app.sim.mode, config.time_scale))
    print("[sim] home        : lat=%s lon=%s alt=%sm" % (config.home_lat, config.home_lon, config.home_alt))
    print("[sim] safety      : max_alt=%sm max_speed=%sm/s fence=%sm nfz=%s"
          % (app.safety.max_alt_m, app.safety.max_speed_mps,
             (app.safety.geofence or {}).get("radius_m"), [z.get("name") for z in app.safety.no_fly_zones]))
    print("[sim] audit       : %s" % app.audit.path)
    print("[sim] 按 Ctrl+C 停止")
    print("=" * 78)
    try:
        handle.serve_forever()
    except KeyboardInterrupt:
        print("\n[sim] 收到 Ctrl+C，正在停止 ...")
    finally:
        handle.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
