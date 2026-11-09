# -*- coding: utf-8 -*-
"""tools_runtime 单测：spec/tools.json schema 校验、confirm 门禁、plan_id 展开、Agent 错误码归一化。"""
import copy
import unittest

from orchestrator import tools_runtime


class FakeAgent:
    def __init__(self):
        self.calls = []
        self.responses = {}
        self.missions_list = []
        self.records = {}
        self.state = "idle"
        self.sim_configs = []

    def telemetry(self):
        return {"ok": True, "state": self.state, "lat": 39.9042, "lon": 116.4074,
                "alt_rel_m": 0.0, "alt_abs_m": 43.0, "battery_pct": 100.0,
                "gimbal": {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
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
        return {"ok": True, "tool": tool, "state": "hovering", "mission_id": "m-0001",
                "telemetry_snapshot": self.telemetry()}

    def missions(self, limit=10):
        return {"ok": True, "missions": list(self.missions_list)}

    def mission(self, mission_id):
        return self.records.get(mission_id, {"ok": False,
                                             "error": {"code": "E_MISSION_NOT_FOUND",
                                                       "message": "no such mission"}})

    def wait_state(self, states, timeout_s=120.0):
        telemetry = self.telemetry()
        telemetry["state"] = states[0]
        return telemetry

    def wait_mission(self, mission_id, timeout_s=240.0):
        return self.records.get(mission_id, {"ok": True, "mission_id": mission_id,
                                             "state": "completed", "photos": [],
                                             "stats": {"n_photos": 0}})

    def sim_config(self, config):
        self.sim_configs.append(dict(config))
        return {"ok": True, "config": dict(config)}


PLAN_ARGS = {"pattern": "grid", "center_lat": 39.9042, "center_lon": 116.4074,
             "altitude_m": 40, "radius_m": 28, "overlap": 0.7, "gimbal_pitch_deg": -45}


class ToolRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.agent = FakeAgent()
        self.runtime = tools_runtime.ToolRuntime(self.agent, run_id="test-run",
                                                 wait_missions=True)

    # ---- schema/白名单 ------------------------------------------------------
    def test_unknown_tool_never_sent_to_agent(self):
        outcome = self.runtime.execute("fly_to_moon", {})
        self.assertFalse(outcome["ok"])
        self.assertEqual(outcome["error_code"], "E_UNKNOWN_TOOL")
        self.assertEqual(self.agent.calls, [])

    def test_schema_rejects_wrong_type_and_extra_keys(self):
        bad_type = self.runtime.execute("takeoff", {"altitude_m": "40", "confirm": True})
        self.assertEqual(bad_type["error_code"], "E_SCHEMA")
        extra = self.runtime.execute("takeoff", {"altitude_m": 40, "confirm": True,
                                                 "boost": True})
        self.assertEqual(extra["error_code"], "E_SCHEMA")
        self.assertEqual(self.agent.calls, [])

    def test_goto_requires_plan_or_waypoints(self):
        outcome = self.runtime.execute("goto_waypoints", {"confirm": True})
        self.assertEqual(outcome["error_code"], "E_SCHEMA")
        self.assertEqual(self.agent.calls, [])

    def test_goto_plan_and_waypoints_are_exclusive(self):
        outcome = self.runtime.execute("goto_waypoints", {
            "confirm": True, "plan_id": "plan-x",
            "waypoints": [{"lat": 39.9, "lon": 116.4, "alt_rel_m": 40}]})
        self.assertEqual(outcome["error_code"], "E_SCHEMA")

    # ---- confirm 门禁 -------------------------------------------------------
    def test_confirm_gate_blocks_flight_tools(self):
        for name, args in (("takeoff", {"altitude_m": 40}),
                           ("takeoff", {"altitude_m": 40, "confirm": False}),
                           ("goto_waypoints", {"waypoints": [{"lat": 39.9, "lon": 116.4,
                                                              "alt_rel_m": 40}],
                                               "confirm": False}),
                           ("set_mode", {"mode": "real", "confirm": False})):
            outcome = self.runtime.execute(name, args)
            self.assertEqual(outcome["error_code"], "E_CONFIRM_REQUIRED", name)
            self.assertFalse(outcome["meta"].get("forwarded", False))
        self.assertEqual(self.agent.calls, [])

    def test_confirm_gate_allows_confirmed_takeoff(self):
        outcome = self.runtime.execute("takeoff", {"altitude_m": 40, "confirm": True})
        self.assertTrue(outcome["ok"])
        self.assertEqual(len(self.agent.calls), 1)
        call = self.agent.calls[0]
        self.assertEqual(call["tool"], "takeoff")
        self.assertEqual(call["args"], {"altitude_m": 40})
        self.assertTrue(call["confirm"])
        self.assertEqual(outcome["meta"]["state"], "hovering")

    # ---- 本地规划 + plan_id 展开 -------------------------------------------
    def test_plan_then_goto_expands_mission(self):
        planned = self.runtime.execute("plan_capture_mission", dict(PLAN_ARGS))
        self.assertTrue(planned["ok"])
        plan_id = planned["meta"]["plan_id"]
        self.assertGreaterEqual(planned["meta"]["n_photos"], 12)
        self.assertIn(plan_id, self.runtime.plans)
        self.agent.records["m-0001"] = {
            "ok": True, "mission_id": "m-0001", "state": "completed",
            "photos": [{"file": "SIM_0001.jpg"}, {"file": "SIM_0002.jpg"}],
            "stats": {"n_photos": 2, "duration_s": 12.5}}
        executed = self.runtime.execute("goto_waypoints",
                                        {"plan_id": plan_id, "confirm": True})
        self.assertTrue(executed["ok"])
        goto_call = [call for call in self.agent.calls if call["tool"] == "goto_waypoints"][-1]
        self.assertTrue(goto_call["confirm"])
        self.assertNotIn("plan_id", goto_call["args"])
        mission = goto_call["args"]["mission"]
        self.assertEqual(mission["schema"], "llm_drone.mission/v1")
        self.assertEqual(mission["plan_id"], plan_id)
        self.assertGreaterEqual(len(mission["waypoints"]), 12)
        self.assertEqual(mission["waypoints"][0]["action"], "photo")
        self.assertEqual(mission["waypoints"][0]["alt_abs_m"], 83.0)
        self.assertIn("photo_interval_s", goto_call["args"])
        self.assertEqual(executed["result"]["n_photos"], 2)
        self.assertEqual(executed["result"]["state"], "completed")

    def test_goto_unknown_plan(self):
        outcome = self.runtime.execute("goto_waypoints", {"plan_id": "plan-nope",
                                                          "confirm": True})
        self.assertEqual(outcome["error_code"], "E_PLAN_NOT_FOUND")
        self.assertEqual(self.agent.calls, [])

    def test_goto_explicit_waypoints_wraps_mission(self):
        self.agent.records["m-0001"] = {"ok": True, "mission_id": "m-0001",
                                        "state": "completed", "photos": [],
                                        "stats": {"n_photos": 1}}
        outcome = self.runtime.execute("goto_waypoints", {
            "confirm": True,
            "waypoints": [{"lat": 39.9043, "lon": 116.4075, "alt_rel_m": 40}],
            "photo_interval_s": 3})
        self.assertTrue(outcome["ok"])
        call = [c for c in self.agent.calls if c["tool"] == "goto_waypoints"][-1]
        mission = call["args"]["mission"]
        self.assertEqual(call["args"]["photo_interval_s"], 3)
        self.assertEqual(len(mission["waypoints"]), 1)
        self.assertEqual(mission["waypoints"][0]["action"], "photo")
        self.assertEqual(mission["waypoints"][0]["alt_rel_m"], 40)

    # ---- 错误码归一化 -------------------------------------------------------
    def test_agent_error_rule_mapped_to_spec_code(self):
        self.agent.responses["takeoff"] = {
            "ok": False, "state": "idle",
            "error": {"code": "SAFETY_REJECTED", "rule": "MAX_ALTITUDE",
                      "message": "altitude 200 > 120", "violations": []}}
        outcome = self.runtime.execute("takeoff", {"altitude_m": 200, "confirm": True})
        self.assertFalse(outcome["ok"])
        self.assertEqual(outcome["error_code"], "E_ALT_LIMIT")

    def test_spec_error_code_passthrough(self):
        self.agent.responses["takeoff"] = {
            "ok": False, "state": "idle",
            "error": {"code": "E_BATTERY_TAKEOFF", "message": "22% < 30%", "details": {}}}
        outcome = self.runtime.execute("takeoff", {"altitude_m": 30, "confirm": True})
        self.assertEqual(outcome["error_code"], "E_BATTERY_TAKEOFF")

    def test_real_mode_rejected(self):
        self.agent.responses["set_mode"] = {
            "ok": False, "error": {"code": "E_REAL_NOT_AVAILABLE",
                                   "message": "Phase1 无真机后端", "details": {}}}
        outcome = self.runtime.execute("set_mode", {"mode": "real", "confirm": True})
        self.assertEqual(outcome["error_code"], "E_REAL_NOT_AVAILABLE")
        self.assertTrue(self.agent.calls[-1]["confirm"])

    # ---- 直通/控制 ----------------------------------------------------------
    def test_get_telemetry_passthrough(self):
        outcome = self.runtime.execute("get_telemetry", {})
        self.assertTrue(outcome["ok"])
        self.assertEqual(outcome["result"]["telemetry"]["battery_pct"], 100.0)
        self.assertEqual(self.agent.calls, [])

    def test_control_sim_config(self):
        outcome = self.runtime.control({"type": "sim_config",
                                        "config": {"battery_pct": 19}})
        self.assertTrue(outcome["ok"])
        self.assertEqual(self.agent.sim_configs, [{"battery_pct": 19}])

    def test_return_to_home_waits_idle(self):
        outcome = self.runtime.execute("return_to_home", {})
        self.assertTrue(outcome["ok"])
        self.assertEqual(outcome["result"]["state"], "idle")
        self.assertEqual(self.agent.calls[-1]["tool"], "return_to_home")

    def test_validate_tool_args_helper(self):
        self.assertEqual(tools_runtime.validate_tool_args("takeoff", {"altitude_m": 40}), [])
        self.assertTrue(tools_runtime.validate_tool_args("nope", {}))


if __name__ == "__main__":
    unittest.main()
