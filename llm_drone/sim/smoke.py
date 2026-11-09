"""端到端 smoke / 验收脚本（PROTOCOL.md §3/§10/§11）。

流程：
  1) health / reset / telemetry
  2) takeoff 40m -> hovering
  3) goto_waypoints(sample_mission.json) -> mission completed，16 张照片，c2w 正交
  4) capture_photo / set_gimbal / return_to_home -> idle
  5) 对抗 A1-A10（A1/A4/A5/A7/A8/A9/A10 直调；A2/A3 先 takeoff；A6 飞行中注低电量强制 RTH）
  6) command_id 幂等、审计 seq 单调、审计含 command_rejected/force_rth
证据输出：<out>/smoke_report.json + <out>/smoke_transcript.txt

用法：
  cd dji_ue5_3dgs/llm_drone && python -m sim.smoke --agent-url http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, List, Optional

_LLM_DRONE = Path(__file__).resolve().parents[1]
if str(_LLM_DRONE) not in sys.path:
    sys.path.insert(0, str(_LLM_DRONE))

from safety.geo import is_orthonormal_rotation  # noqa: E402

SAMPLE_MISSION = _LLM_DRONE / "spec" / "sample_mission.json"


class Agent:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.transcript: List[str] = []

    # ---- HTTP ---------------------------------------------------------
    def _request(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.base + path, data=data, headers={"Content-Type": "application/json; charset=utf-8"}, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                body = {"raw": raw}
            body.setdefault("_http_status", exc.code)
            return body

    def get(self, path: str) -> dict:
        return self._request("GET", path)

    def post(self, path: str, payload: Optional[dict] = None) -> dict:
        return self._request("POST", path, payload or {})

    def command(self, command_id: str, tool: str, args: Optional[dict] = None, confirm: bool = False,
                log: bool = True) -> dict:
        resp = self.post(
            "/v1/command",
            {"command_id": command_id, "tool": tool, "args": args or {}, "confirm": confirm},
        )
        if log:
            err = resp.get("error") or {}
            self.transcript.append(
                "[cmd] %-22s cid=%-18s confirm=%-5s ok=%-5s code=%-20s state=%s"
                % (tool, command_id, confirm, resp.get("ok"), err.get("code") or "-", resp.get("state"))
            )
        return resp

    # ---- 轮询 ---------------------------------------------------------
    def wait_state(self, states, timeout_s: float = 120.0) -> dict:
        wanted = tuple(states)
        deadline = time.time() + float(timeout_s)
        last: dict = {}
        while time.time() < deadline:
            last = self.get("/v1/telemetry")
            if last.get("state") in wanted:
                return last
            time.sleep(0.1)
        raise TimeoutError("等待 state∈%s 超时（最后 state=%r）" % (list(wanted), (last or {}).get("state")))

    def wait_mission(self, mission_id: str, timeout_s: float = 180.0) -> dict:
        deadline = time.time() + float(timeout_s)
        last: dict = {}
        while time.time() < deadline:
            last = self.get("/v1/missions/" + mission_id)
            if last.get("state") in ("completed", "aborted", "failed"):
                return last
            time.sleep(0.1)
        raise TimeoutError("等待 mission %s 结束超时（最后 state=%r）" % (mission_id, (last or {}).get("state")))

    def reset(self, run_id: str) -> dict:
        self.transcript.append("[reset] run_id=%s" % run_id)
        return self.post("/v1/reset", {"run_id": run_id})

    def log(self, line: str) -> None:
        self.transcript.append(line)
        print(line)


def expect(resp: dict, ok: bool, code: Optional[str] = None) -> dict:
    if bool(resp.get("ok")) != bool(ok):
        raise AssertionError("ok 期望 %r，实际响应: %s" % (ok, json.dumps(resp, ensure_ascii=False)[:600]))
    if code is not None:
        actual = (resp.get("error") or {}).get("code")
        if actual != code:
            raise AssertionError("error.code 期望 %r，实际 %r（响应: %s）" % (code, actual, json.dumps(resp, ensure_ascii=False)[:600]))
    return resp


def load_sample_mission() -> dict:
    with open(SAMPLE_MISSION, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PROTOCOL v1.0 端到端 smoke")
    parser.add_argument("--agent-url", default="http://127.0.0.1:8765")
    parser.add_argument("--out", default=str(_LLM_DRONE / "sim" / "output" / "smoke"))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--skip-force-rth", action="store_true", help="跳过 A6（飞行中低电量强制返航）")
    args = parser.parse_args(argv)
    run_id = args.run_id or "smoke_%s" % time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    sample = load_sample_mission()
    agent = Agent(args.agent_url)
    report: dict = {"agent_url": args.agent_url, "run_id": run_id, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "checks": [], "passed": False}

    def check(name: str, func: Callable[[], Any]) -> Any:
        started = time.time()
        try:
            value = func()
            report["checks"].append({"name": name, "pass": True, "wall_s": round(time.time() - started, 2)})
            agent.log("[ok]   %s" % name)
            return value
        except Exception as exc:  # noqa: BLE001
            report["checks"].append({"name": name, "pass": False, "error": repr(exc), "wall_s": round(time.time() - started, 2)})
            agent.log("[FAIL] %s: %r" % (name, exc))
            report["passed"] = False
            raise

    try:
        # ---------------------------------------------------------- 1 健康
        health = check("health", lambda: expect(agent.get("/v1/health"), True))
        agent.log("       backend=%s version=%s time_scale=%s" % (health.get("backend"), health.get("version"), health.get("time_scale")))
        report["health"] = {k: health.get(k) for k in ("ok", "backend", "version", "mode", "time_scale")}

        reset = check("reset", lambda: agent.reset(run_id))
        report["reset"] = reset

        telemetry = check("telemetry", lambda: agent.get("/v1/telemetry"))
        check("telemetry_fields", lambda: _assert_telemetry(telemetry))
        report["telemetry_initial"] = telemetry

        # ---------------------------------------------------------- 2 正向任务
        check("takeoff_40m", lambda: expect(agent.command("smoke-takeoff-1", "takeoff", {"altitude_m": 40}, True), True))
        hover = check("wait_hovering", lambda: agent.wait_state(["hovering"], timeout_s=60))
        check("hovering_alt", lambda: _assert_close(hover.get("alt_rel_m"), 40.0, 0.2, "alt_rel_m"))
        report["hovering_telemetry"] = hover

        mission = sample
        goto = check(
            "goto_sample_mission",
            lambda: expect(
                agent.command(
                    "smoke-goto-1",
                    "goto_waypoints",
                    {"mission": mission, "photo_interval_s": 1},
                    True,
                ),
                True,
            ),
        )
        mission_id = goto.get("mission_id") or mission.get("mission_id")
        record = check("mission_completed", lambda: agent.wait_mission(mission_id, timeout_s=180))
        check("mission_state", lambda: _assert_equal(record.get("state"), "completed", "mission.state"))
        check("photo_count_16", lambda: _assert_equal(len(record.get("photos") or []), 16, "photos"))
        check("photo_fields", lambda: _assert_photos(record))
        report["mission"] = record

        status = check("get_mission_status", lambda: expect(agent.command("smoke-status-1", "get_mission_status", {"mission_id": mission_id}), True))
        check("status_photos", lambda: _assert_equal(len((status.get("mission") or {}).get("photos") or []), 16, "status.mission.photos"))

        # capture_photo：interval_s=0 时立即拍 count 张（count>1 且 interval>0 由主循环补拍，这里测同步路径）
        photo_resp = check("capture_photo", lambda: expect(agent.command("smoke-photo-1", "capture_photo", {"count": 3, "interval_s": 0}), True))
        check("capture_photo_count", lambda: _assert_equal(len(photo_resp.get("photos") or []), 3, "capture.photos"))

        preflight = check("preflight_check_tool", lambda: expect(agent.command("smoke-preflight-1", "preflight_check", {}), True))
        report["preflight"] = preflight
        telemetry_tool = check("get_telemetry_tool", lambda: expect(agent.command("smoke-tel-1", "get_telemetry", {}), True))
        report["get_telemetry_tool"] = {"ok": telemetry_tool.get("ok"), "state": telemetry_tool.get("state")}

        gimbal = check("set_gimbal", lambda: expect(agent.command("smoke-gimbal-1", "set_gimbal", {"pitch_deg": -90.0}), True))
        check("gimbal_pitch", lambda: _assert_close(gimbal.get("gimbal", {}).get("pitch"), -90.0, 0.01, "gimbal.pitch"))

        check("return_to_home", lambda: expect(agent.command("smoke-rth-1", "return_to_home"), True))
        check("wait_idle_after_rth", lambda: agent.wait_state(["idle"], timeout_s=120))
        report["photos_metadata"] = _metadata(record, mission)

        # ---------------------------------------------------------- 3 对抗
        adversarial = {}
        agent.reset(run_id)
        adversarial["A1_alt_limit"] = expect(agent.command("adv-a1", "takeoff", {"altitude_m": 200}, True), False, "E_ALT_LIMIT")
        adversarial["A5_no_confirm"] = expect(agent.command("adv-a5", "goto_waypoints", {"mission": sample}, False), False, "E_CONFIRM_REQUIRED")
        adversarial["A9_param_range"] = expect(agent.command("adv-a9a", "takeoff", {"altitude_m": -5}, True), False, "E_PARAM_RANGE")
        adversarial["A9_unknown_tool"] = expect(agent.command("adv-a9b", "fly_to_moon", {}, True), False, "E_UNKNOWN_TOOL")
        adversarial["A10_real_mode"] = expect(agent.command("adv-a10", "set_mode", {"mode": "real"}, True), False, "E_REAL_NOT_AVAILABLE")

        agent.reset(run_id)
        sim_cfg = expect(agent.post("/v1/sim/config", {"battery_pct": 22}), True)
        report["sim_config_low_battery"] = sim_cfg
        adversarial["A4_low_battery"] = expect(agent.command("adv-a4", "takeoff", {"altitude_m": 40}, True), False, "E_BATTERY_TAKEOFF")

        agent.reset(run_id)
        expect(agent.post("/v1/sim/config", {"gps_fix": 1, "gps_satellites": 6}), True)
        adversarial["A7_gps"] = expect(agent.command("adv-a7", "takeoff", {"altitude_m": 40}, True), False, "E_GPS")

        agent.reset(run_id)
        expect(agent.post("/v1/sim/config", {"rc_connected": False}), True)
        adversarial["A8_rc_link"] = expect(agent.command("adv-a8", "takeoff", {"altitude_m": 40}, True), False, "E_RC_LINK")
        agent.reset(run_id)

        # A2/A3：先起飞再 goto（goto 需 hovering）
        expect(agent.command("adv-takeoff-a2", "takeoff", {"altitude_m": 40}, True), True)
        agent.wait_state(["hovering"], timeout_s=60)
        far_mission = _mission_with_waypoints(
            [{"lat": 39.9114, "lon": 116.4074, "alt_rel_m": 40, "speed_mps": 5, "heading_deg": 0,
              "gimbal_pitch_deg": -45, "action": "photo", "index": 0}],
            mission_id="adv-far",
        )
        adversarial["A2_geofence"] = expect(agent.command("adv-a2", "goto_waypoints", {"mission": far_mission}, True), False, "E_GEOFENCE")

        nfz_mission = _mission_with_waypoints(
            [{"lat": 39.9048, "lon": 116.4080, "alt_rel_m": 40, "speed_mps": 5, "heading_deg": 0,
              "gimbal_pitch_deg": -45, "action": "photo", "index": 0}],
            mission_id="adv-nfz",
        )
        adversarial["A3_no_fly_zone"] = expect(agent.command("adv-a3", "goto_waypoints", {"mission": nfz_mission}, True), False, "E_NOFLY")

        # A6：飞行中注低电量 -> 强制 RTH -> 最终 idle
        if not args.skip_force_rth:
            agent.reset(run_id)
            expect(agent.command("adv-takeoff-a6", "takeoff", {"altitude_m": 40}, True), True)
            agent.wait_state(["hovering"], timeout_s=60)
            mission_a6 = dict(sample)
            mission_a6["mission_id"] = "adv-force-rth"
            goto_a6 = expect(agent.command("adv-a6-goto", "goto_waypoints", {"mission": mission_a6, "photo_interval_s": 1}, True), True)
            a6_mission_id = goto_a6.get("mission_id") or mission_a6["mission_id"]
            for _ in range(100):
                if (agent.get("/v1/telemetry") or {}).get("mission_id") == a6_mission_id:
                    break
                time.sleep(0.05)
            expect(agent.post("/v1/sim/config", {"battery_pct": 19}), True)
            final = agent.wait_state(["idle"], timeout_s=180)
            record_a6 = agent.get("/v1/missions/" + a6_mission_id)
            report["force_rth_final_state"] = final.get("state")
            report["force_rth_mission"] = {
                "mission_id": a6_mission_id,
                "state": record_a6.get("state"),
                "error": record_a6.get("error"),
            }
            adversarial["A6_force_rth"] = {
                "ok": True,
                "final_state": final.get("state"),
                "battery_pct": final.get("battery_pct"),
                "mission_state": record_a6.get("state"),
            }
            check("A6_force_rth_landed", lambda: _assert_true(
                record_a6.get("state") in ("aborted", "completed") and final.get("state") == "idle",
                "A6 强制返航后任务未 aborted 或未回到 idle: mission=%r telemetry=%r" % (record_a6.get("state"), final.get("state")),
            ))
        report["adversarial"] = {key: {"ok": bool(value.get("ok") is False), "error_code": (value.get("error") or {}).get("code")}
                                 for key, value in adversarial.items()}
        expected_codes = ["E_ALT_LIMIT", "E_CONFIRM_REQUIRED", "E_PARAM_RANGE", "E_UNKNOWN_TOOL",
                          "E_REAL_NOT_AVAILABLE", "E_BATTERY_TAKEOFF", "E_GPS", "E_RC_LINK",
                          "E_GEOFENCE", "E_NOFLY"]
        check("adversarial_all_rejected",
              lambda: _assert_equal(
                  sorted(str((value.get("error") or {}).get("code")) for value in adversarial.values()),
                  sorted(expected_codes),
                  "adversarial error codes",
              ))

        # ---------------------------------------------------------- 4 幂等 / 审计
        time.sleep(0.3)
        first = agent.command("idem-1", "get_telemetry", {}, log=False)
        second = agent.command("idem-1", "get_telemetry", {}, log=False)
        check("idempotent_replay", lambda: _assert_equal(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True), "idempotent response"))
        report["idempotent_sample"] = {"first_ok": first.get("ok"), "second_ok": second.get("ok")}

        audit = agent.get("/v1/audit?since_seq=0")
        check("audit_ok", lambda: expect(audit, True))
        events = audit.get("events") or []
        check("audit_seq_monotonic", lambda: _assert_seq(events))
        event_names = [event.get("event") for event in events]
        check("audit_has_rejections", lambda: _assert_true("command_rejected" in event_names, "缺少 command_rejected 审计事件"))
        if not args.skip_force_rth:
            check("audit_has_force_rth", lambda: _assert_true("force_rth" in event_names, "缺少 force_rth 审计事件"))
        report["audit"] = {"last_seq": audit.get("last_seq"), "n_events": len(events),
                           "has_force_rth": "force_rth" in event_names,
                           "has_command_rejected": "command_rejected" in event_names,
                           "audit_path": health.get("audit_path") or (agent.get("/v1/health") or {}).get("audit_path")}

        report["passed"] = True
    except Exception as exc:  # noqa: BLE001
        report.setdefault("passed", False)
        report["fatal_error"] = repr(exc)

    report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    report["transcript_lines"] = len(agent.transcript)
    (out_dir / "smoke_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "smoke_transcript.txt").write_text("\n".join(agent.transcript), encoding="utf-8")
    print("\n== smoke %s == 报告: %s" % ("PASS" if report.get("passed") else "FAIL", out_dir / "smoke_report.json"))
    return 0 if report.get("passed") else 1


# ---------------------------------------------------------------- 断言辅助
def _assert_true(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


def _assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError("%s 期望 %r，实际 %r" % (label, expected, actual))


def _assert_close(actual, expected, tol: float, label: str) -> None:
    if actual is None or abs(float(actual) - float(expected)) > float(tol):
        raise AssertionError("%s 期望 %.2f±%.2f，实际 %r" % (label, float(expected), float(tol), actual))


TELEMETRY_REQUIRED = ("ts", "sim_time_s", "state", "lat", "lon", "alt_rel_m", "alt_abs_m", "speed_mps",
                      "vertical_speed_mps", "battery_pct", "gimbal", "gps", "rc", "mode", "mission_id", "home")


def _assert_telemetry(telemetry: dict) -> None:
    for field in TELEMETRY_REQUIRED:
        if field not in telemetry:
            raise AssertionError("telemetry 缺字段 %r" % field)
    if telemetry["state"] not in ("idle", "taking_off", "hovering", "mission", "returning", "landing", "aborted", "failsafe"):
        raise AssertionError("telemetry.state 非法: %r" % telemetry["state"])


def _assert_photos(record: dict) -> None:
    photos = record.get("photos") or []
    if len(photos) != 16:
        raise AssertionError("photos 数量期望 16，实际 %d" % len(photos))
    for index, photo in enumerate(photos):
        for field in ("index", "file", "ts", "lat", "lon", "alt_rel_m", "alt_abs_m", "heading_deg", "gimbal", "c2w"):
            if field not in photo:
                raise AssertionError("photo[%d] 缺字段 %r" % (index, field))
        if not str(photo["file"]).startswith("SIM_") or not str(photo["file"]).endswith(".jpg"):
            raise AssertionError("photo[%d].file 非法: %r" % (index, photo["file"]))
        if not is_orthonormal_rotation(photo["c2w"]):
            raise AssertionError("photo[%d].c2w 非正交旋转" % index)
        gimbal = photo.get("gimbal") or {}
        for key in ("pitch", "yaw", "roll"):
            if key not in gimbal:
                raise AssertionError("photo[%d].gimbal 缺 %r" % (index, key))


def _assert_seq(events: List[dict]) -> None:
    seqs = [int(event.get("seq", 0)) for event in events]
    if not seqs:
        raise AssertionError("审计事件为空")
    if seqs != sorted(seqs) or len(set(seqs)) != len(seqs):
        raise AssertionError("审计 seq 非严格单调递增: %r" % seqs[:20])
    for event in events:
        for field in ("ts", "seq", "run_id", "event"):
            if field not in event:
                raise AssertionError("审计事件缺字段 %r: %r" % (field, event))


def _mission_with_waypoints(waypoints: List[dict], mission_id: str) -> dict:
    mission = {
        "schema": "llm_drone.mission/v1",
        "mission_id": mission_id,
        "type": "point",
        "origin_wgs84": {"lat": 39.9042, "lon": 116.4074, "alt": 43.0},
        "home": {"lat": 39.9042, "lon": 116.4074, "alt_abs_m": 43.0},
        "camera": {"model": "DJI Mini 4 Pro (simulated)", "width": 1600, "height": 1200,
                   "fx": 1148.343, "fy": 1148.343, "cx": 800.0, "cy": 600.0},
        "flight": {"pattern": "point", "altitude_m": 40.0, "speed_mps": 5.0,
                   "gimbal_pitch_deg": -45.0, "overlap": 0.7, "heading_deg": 0.0,
                   "turn_mode": "stop_and_turn"},
        "waypoints": waypoints,
        "photo_points": [waypoint.get("index", index) for index, waypoint in enumerate(waypoints)],
        "stats": {"n_waypoints": len(waypoints), "n_photos": len(waypoints)},
    }
    return mission


def _metadata(record: dict, mission_def: dict) -> dict:
    """调用 sim.export 生成 §7.3 仿真记录版 metadata（不作为 smoke 断言，仅证据）。"""
    try:
        from sim.export import mission_record_to_metadata

        return mission_record_to_metadata(record, mission_def)
    except Exception as exc:  # noqa: BLE001
        return {"error": repr(exc)}


if __name__ == "__main__":
    sys.exit(main())
