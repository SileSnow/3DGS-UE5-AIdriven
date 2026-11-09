# -*- coding: utf-8 -*-
"""run_demo/audit 单测：离线（fake Agent + ScriptedLLM）生成完整 spec §12 run 目录。"""
import argparse
import copy
import json
import tempfile
import unittest
from pathlib import Path

from orchestrator import audit as audit_mod
from orchestrator import run_demo

RUN_FILES = ("request.md", "transcript.md", "llm_events.jsonl", "tool_calls.jsonl",
             "agent_audit.jsonl", "mission.json", "mission_record.json",
             "photos_metadata.json", "metrics.json", "summary.md")


class FakeAgent:
    def __init__(self):
        self.calls = []
        self.responses = {}
        self.records = {}
        self.state = "idle"
        self.sim_configs = []
        self.resets = []

    def health(self):
        return {"ok": True, "backend": "sim", "version": "test", "mode": "sim"}

    def reset(self, run_id=""):
        self.resets.append(run_id)
        self.state = "idle"
        return {"ok": True, "state": "idle", "run_id": run_id}

    def sim_config(self, config):
        self.sim_configs.append(dict(config))
        return {"ok": True, "config": dict(config)}

    def telemetry(self):
        return {"ok": True, "ts": audit_mod.now_iso(), "state": self.state,
                "lat": 39.9042, "lon": 116.4074, "alt_rel_m": 0.0, "alt_abs_m": 43.0,
                "battery_pct": 100.0, "gimbal": {"pitch": -45.0, "yaw": 0.0, "roll": 0.0},
                "gps": {"fix": 3, "satellites": 24}, "rc": {"connected": True},
                "mode": "sim", "mission_id": None,
                "home": {"lat": 39.9042, "lon": 116.4074, "alt_abs_m": 43.0}}

    def command(self, tool, args=None, confirm=False, run_id="", command_id=None):
        self.calls.append({"tool": tool, "args": copy.deepcopy(args or {}),
                           "confirm": confirm, "command_id": command_id})
        response = self.responses.get(tool)
        if callable(response):
            return response(tool, args or {}, confirm)
        if response is not None:
            return copy.deepcopy(response)
        if tool == "goto_waypoints":
            return {"ok": True, "tool": tool, "state": "mission", "mission_id": "m-0001"}
        return {"ok": True, "tool": tool, "state": "hovering",
                "telemetry_snapshot": self.telemetry()}

    def missions(self, limit=10):
        return {"ok": True, "missions": []}

    def mission(self, mission_id):
        return self.records.get(mission_id,
                                {"ok": False, "error": {"code": "E_MISSION_NOT_FOUND"}})

    def wait_state(self, states, timeout_s=120.0):
        telemetry = self.telemetry()
        telemetry["state"] = states[0]
        return telemetry

    def wait_mission(self, mission_id, timeout_s=240.0):
        return self.records.get(mission_id, {"ok": True, "mission_id": mission_id,
                                             "state": "completed", "photos": [],
                                             "stats": {"n_photos": 0}})

    def _request(self, method, path, payload=None):
        if "/v1/audit" in path:
            return {"ok": True, "events": [
                {"ts": audit_mod.now_iso(), "seq": 1, "run_id": "x",
                 "event": "command_rejected", "error_code": "E_ALT_LIMIT"},
                {"ts": audit_mod.now_iso(), "seq": 2, "run_id": "x",
                 "event": "mission_completed", "n_photos": 3},
            ], "last_seq": 2}
        return {"ok": False, "error": {"code": "E_NOT_FOUND", "message": path}}


def make_args(tmp: Path) -> argparse.Namespace:
    return argparse.Namespace(
        agent_url="http://fake", model="qwen3.5:4b", base_url="http://fake-llm",
        api_style="ollama", timeout=10.0, temperature=0.1, max_rounds=12,
        scripted_for={"ZA", "ZB"}, verbose=False, out=str(tmp))


class RunDemoOfflineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="run_demo_test_"))
        self.agent = FakeAgent()
        self.args = make_args(self.tmp)

    # ---- audit 产物 ---------------------------------------------------------
    def test_audit_writes_three_files(self):
        run_dir = self.tmp / "audit_run"
        audit = audit_mod.RunAudit(run_dir, "run-x", "P1",
                                   {"kind": "positive", "mode": "scripted"})
        audit.user_message("测试")
        audit.llm_request(1, "m", "u", "ollama", 2, 15)
        audit.llm_response("", "thinking", [{"id": "c1", "name": "get_telemetry",
                                             "arguments": {}}], 10.0,
                           {"prompt": 5, "completion": 3})
        audit.tool_call(1, "c1", "get_telemetry", {})
        audit.tool_result("c1", "get_telemetry", True, {"ok": True}, None, 12.0)
        audit.plan_created("plan-1", "grid", 16, 16, "网格")
        audit.user_confirm("takeoff", True)
        audit.final_answer("完成", 2)
        counters = audit.close({"passed": True})
        self.assertTrue(counters)
        for name in ("llm_events.jsonl", "tool_calls.jsonl", "transcript.md"):
            self.assertTrue((run_dir / name).is_file(), name)
        events = [json.loads(line) for line in
                  (run_dir / "llm_events.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(events)
        for event in events:
            for key in ("ts", "run_id", "seq", "event"):
                self.assertIn(key, event)
        names = {event["event"] for event in events}
        for expected in ("llm_request", "llm_response", "tool_call", "tool_result",
                         "plan_created", "user_confirm", "final_answer"):
            self.assertIn(expected, names)
        tool_calls = [json.loads(line) for line in
                      (run_dir / "tool_calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(tool_calls[0]["name"], "get_telemetry")
        self.assertEqual(tool_calls[0]["error_code"], None)
        self.assertEqual(audit.counters["llm_calls"], 1)
        self.assertEqual(audit.counters["tool_calls"], 1)

    # ---- 端到端：拒绝场景 ---------------------------------------------------
    def test_run_scenario_reject_creates_full_run_dir(self):
        self.agent.responses["takeoff"] = {
            "ok": False, "state": "idle",
            "error": {"code": "E_ALT_LIMIT", "message": "200m > 120m", "details": {}}}
        scenario = {
            "id": "ZA", "kind": "adversarial", "title": "test",
            "prompt": "起飞到 200 米", "sim_setup": {},
            "expected_tools": ["takeoff"], "expected_error_code": "E_ALT_LIMIT",
            "expect_photos": 0, "expect_final_state": ["idle"],
            "mode": "scripted",
            "script": [{"tool": "takeoff", "args": {"altitude_m": 200, "confirm": True}}],
            "final_text": "被拒绝",
        }
        metrics = run_demo.run_scenario(scenario, self.args, self.agent, self.tmp)
        run_dir = self.tmp / metrics["run_id"]
        for name in RUN_FILES:
            self.assertTrue((run_dir / name).is_file(), name)
        self.assertTrue(metrics["passed"], metrics["actual"]["checks"])
        self.assertEqual(metrics["error_codes"], ["E_ALT_LIMIT"])
        self.assertEqual(metrics["rejected"], 1)
        for key in ("run_id", "scenario_id", "kind", "model", "llm_calls", "tool_calls",
                    "rejected", "error_codes", "wall_s", "mission_sim_s", "n_photos",
                    "tokens", "passed", "expected", "actual"):
            self.assertIn(key, metrics)
        self.assertEqual(self.agent.resets, [metrics["run_id"]])
        transcript = (run_dir / "transcript.md").read_text(encoding="utf-8")
        self.assertIn("E_ALT_LIMIT", transcript)
        self.assertIn("scripted", transcript)
        tool_calls = [json.loads(line) for line in
                      (run_dir / "tool_calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(tool_calls[0]["error_code"], "E_ALT_LIMIT")
        metrics_file = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(metrics_file["scenario_id"], "ZA")

    # ---- 端到端：正向场景 ---------------------------------------------------
    def test_run_scenario_positive_mission(self):
        self.agent.records["m-0001"] = {
            "ok": True, "mission_id": "m-0001", "state": "completed", "progress_pct": 100.0,
            "photos": [
                {"index": 0, "file": "SIM_0001.jpg", "alt_rel_m": 40.0, "alt_abs_m": 83.0,
                 "lat": 39.9041, "lon": 116.4072, "gimbal": {"pitch": -45.0, "yaw": 0.0,
                                                             "roll": 0.0},
                 "c2w": [1.0] * 16, "ts": "2026-11-08T22:00:00+08:00"},
                {"index": 1, "file": "SIM_0002.jpg", "alt_rel_m": 40.0, "alt_abs_m": 83.0,
                 "lat": 39.9042, "lon": 116.4073, "gimbal": {"pitch": -45.0, "yaw": 0.0,
                                                             "roll": 0.0},
                 "c2w": [1.0] * 16, "ts": "2026-11-08T22:00:01+08:00"},
            ],
            "stats": {"n_photos": 2, "duration_s": 42.5, "distance_m": 210.0}}
        scenario = {
            "id": "ZB", "kind": "positive", "title": "test positive",
            "prompt": "网格航拍后返航", "sim_setup": {},
            "expected_tools": ["plan_capture_mission", "takeoff", "goto_waypoints",
                               "return_to_home"],
            "expected_error_code": None, "expect_photos": {"min": 2},
            "expect_mission_state": "completed", "expect_no_rejection": True,
            "mode": "scripted",
            "script": [
                {"tool": "plan_capture_mission", "args": {
                    "pattern": "grid", "center_lat": 39.9042, "center_lon": 116.4074,
                    "altitude_m": 40, "radius_m": 28, "overlap": 0.7,
                    "gimbal_pitch_deg": -45}},
                {"tool": "takeoff", "args": {"altitude_m": 40, "confirm": True}},
                {"tool": "goto_waypoints", "args": {"plan_id": "$plan_id", "confirm": True}},
                {"tool": "return_to_home", "args": {}},
            ],
            "final_text": "航拍完成，已返航。",
        }
        metrics = run_demo.run_scenario(scenario, self.args, self.agent, self.tmp)
        run_dir = self.tmp / metrics["run_id"]
        self.assertTrue(metrics["passed"], metrics["actual"]["checks"])
        self.assertEqual(metrics["n_photos"], 2)
        self.assertEqual(metrics["mission_sim_s"], 42.5)
        mission = json.loads((run_dir / "mission.json").read_text(encoding="utf-8"))
        self.assertEqual(mission["schema"], "llm_drone.mission/v1")
        self.assertGreaterEqual(len(mission["waypoints"]), 12)
        record = json.loads((run_dir / "mission_record.json").read_text(encoding="utf-8"))
        self.assertEqual(record["state"], "completed")
        photos = json.loads((run_dir / "photos_metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(len(photos["frames"]), 2)
        self.assertEqual(photos["coord_system"], "UE_LHS_Zup_cm")
        self.assertEqual(photos["frames"][0]["mission"]["mission_id"], "m-0001")
        summary_md = (run_dir / "summary.md").read_text(encoding="utf-8")
        self.assertIn("PASS", summary_md)
        # 汇总表
        rows = run_demo.update_summary_md(self.tmp, self.tmp / "SUMMARY.md")
        self.assertEqual(len(rows), 1)
        summary_text = (self.tmp / "SUMMARY.md").read_text(encoding="utf-8")
        self.assertIn("ZB", summary_text)
        self.assertIn("PASS", summary_text)

    # ---- 判定/工具函数 ------------------------------------------------------
    def test_photo_expectation(self):
        self.assertEqual(run_demo._photo_expectation({"min": 12}), ("min", 12))
        self.assertEqual(run_demo._photo_expectation({"exact": 5}), ("exact", 5))
        self.assertEqual(run_demo._photo_expectation(3), ("exact", 3))
        self.assertEqual(run_demo._photo_expectation(">=12"), ("min", 12))
        self.assertEqual(run_demo._photo_expectation(None), (None, None))

    def test_judge_scenario(self):
        scenario = {"expected_tools": ["takeoff"], "expected_error_code": "E_ALT_LIMIT",
                    "expect_photos": 0, "expect_mission_state": None,
                    "expect_no_rejection": False}
        summary = {"tool_sequence": [{"name": "takeoff", "ok": False,
                                      "error_code": "E_ALT_LIMIT"}]}
        counters = {"error_codes": ["E_ALT_LIMIT"], "rejected": 1}
        passed, checks = run_demo.judge_scenario(scenario, summary, counters,
                                                 {"state": "idle"}, {"state": "idle"}, "")
        self.assertTrue(passed, checks)
        scenario_fail = dict(scenario, expected_tools=["goto_waypoints"])
        passed, checks = run_demo.judge_scenario(scenario_fail, summary, counters,
                                                 {"state": "idle"}, {"state": "idle"}, "")
        self.assertFalse(passed)

    def test_scenario_json_spec_alignment(self):
        scenarios = run_demo.load_scenarios()
        for sid in ("P1", "P2", "P3", "A1", "A2", "A3", "A4", "A5", "A6", "A7",
                    "A8", "A9", "A10"):
            self.assertIn(sid, scenarios)
        expected_codes = {
            "A1": ["E_ALT_LIMIT"], "A2": ["E_GEOFENCE"], "A3": ["E_NOFLY"],
            "A4": ["E_BATTERY_TAKEOFF"], "A5": ["E_CONFIRM_REQUIRED"],
            "A7": ["E_GPS"], "A8": ["E_RC_LINK"],
            "A9": ["E_PARAM_RANGE", "E_UNKNOWN_TOOL"],
            "A10": ["E_REAL_NOT_AVAILABLE"],
        }
        for sid, codes in expected_codes.items():
            self.assertEqual(run_demo._expected_codes(scenarios[sid]), codes, sid)


if __name__ == "__main__":
    unittest.main()
