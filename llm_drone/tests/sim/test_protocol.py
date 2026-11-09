"""协议测试：health / telemetry / 幂等 / 未知工具 / reset / sim config / missions / audit。"""

from __future__ import annotations

import unittest

from sim._support import SimFixture


class ProtocolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = SimFixture(time_scale=100.0, tick_wall_s=0.02)

    @classmethod
    def tearDownClass(cls):
        cls.fx.close()

    def setUp(self):
        self.fx.reset(run_id="protocol_%s" % self._testMethodName)

    # -------------------------------------------------------------- health
    def test_health(self):
        body = self.fx.get("/v1/health")
        self.assertTrue(body["ok"])
        self.assertEqual(body["backend"], "sim")
        self.assertEqual(body["mode"], "sim")
        self.assertIn("version", body)
        self.assertGreaterEqual(float(body["time_scale"]), 0.0)
        self.assertIn("ts", body)

    # -------------------------------------------------------------- telemetry
    def test_telemetry_snapshot_fields(self):
        telemetry = self.fx.telemetry()
        for key in (
            "ts", "sim_time_s", "state", "lat", "lon", "alt_rel_m", "alt_abs_m",
            "speed_mps", "vertical_speed_mps", "battery_pct", "gimbal", "gps", "rc",
            "mode", "mission_id", "home",
        ):
            self.assertIn(key, telemetry)
        self.assertEqual(telemetry["state"], "idle")
        self.assertEqual(telemetry["mode"], "sim")
        self.assertAlmostEqual(telemetry["battery_pct"], 100.0, delta=0.5)
        self.assertAlmostEqual(telemetry["lat"], 39.9042, places=6)
        self.assertAlmostEqual(telemetry["lon"], 116.4074, places=6)
        self.assertAlmostEqual(telemetry["alt_rel_m"], 0.0, delta=0.01)
        self.assertAlmostEqual(telemetry["alt_abs_m"], 43.0, delta=0.01)
        self.assertIn("pitch", telemetry["gimbal"])
        self.assertIn("fix", telemetry["gps"])
        self.assertIn("connected", telemetry["rc"])
        self.assertAlmostEqual(telemetry["home"]["lat"], 39.9042, places=6)
        self.assertIsNone(telemetry["mission_id"])

    # -------------------------------------------------------------- 幂等
    def test_idempotent_replay_returns_first_result(self):
        first = self.fx.ok_command("get_telemetry", command_id="c-dup-001")
        second = self.fx.ok_command("takeoff", {"altitude_m": 40}, confirm=True, command_id="c-dup-001")
        self.assertEqual(second["tool"], "get_telemetry")  # 返回首次结果（未执行 takeoff）
        self.assertEqual(second["command_id"], "c-dup-001")
        self.assertEqual(first["tool"], "get_telemetry")
        self.assertEqual(self.fx.telemetry()["state"], "idle")  # takeoff 未真正执行
        events = self.fx.audit_events("protocol_test_idempotent_replay_returns_first_result")
        self.assertTrue(any(e.get("event") == "command_replayed" for e in events))

    def test_command_id_required(self):
        body = self.fx.post("/v1/command", {"tool": "get_telemetry", "args": {}})
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "E_SCHEMA")

    # -------------------------------------------------------------- 未知工具
    def test_unknown_tool_rejected(self):
        body = self.fx.command("fly_to_moon", {})
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "E_UNKNOWN_TOOL")
        self.assertEqual(body["state"], "idle")

    # -------------------------------------------------------------- reset
    def test_reset_restores_defaults_and_switches_audit(self):
        self.fx.sim_config(battery_pct=22.0, gps_fix=1, gps_satellites=5, rc_connected=False)
        telemetry = self.fx.telemetry()
        self.assertAlmostEqual(telemetry["battery_pct"], 22.0, delta=0.5)
        reset = self.fx.reset(run_id="reset_case_001")
        self.assertEqual(reset["state"], "idle")
        telemetry = self.fx.telemetry()
        self.assertAlmostEqual(telemetry["battery_pct"], 100.0, delta=0.5)
        self.assertEqual(telemetry["state"], "idle")
        self.assertEqual(telemetry["gps"]["fix"], 3)
        self.assertEqual(telemetry["gps"]["satellites"], 24)
        self.assertTrue(telemetry["rc"]["connected"])
        audit_file = self.fx.audit_path("reset_case_001")
        self.assertTrue(audit_file.is_file())
        events = self.fx.audit_events("reset_case_001")
        self.assertTrue(events)
        self.assertEqual(events[0]["event"], "sim_reset")

    # -------------------------------------------------------------- sim config
    def test_sim_config_injection(self):
        body = self.fx.sim_config(battery_pct=55.0, gps_fix=2, gps_satellites=7, rc_connected=False)
        self.assertEqual(body["config"]["battery_pct"], 55.0)
        self.assertEqual(body["config"]["gps_fix"], 2)
        self.assertEqual(body["config"]["gps_satellites"], 7)
        self.assertFalse(body["config"]["rc_connected"])
        telemetry = self.fx.telemetry()
        self.assertAlmostEqual(telemetry["battery_pct"], 55.0, delta=0.5)
        self.assertEqual(telemetry["gps"]["fix"], 2)
        self.assertFalse(telemetry["rc"]["connected"])
        self.assertEqual(telemetry["rc"]["signal"], "lost")

    def test_sim_config_invalid(self):
        body = self.fx.post("/v1/sim/config", {"unknown_key": 1})
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "E_SCHEMA")
        body = self.fx.post("/v1/sim/config", {"battery_pct": 120})
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "E_PARAM_RANGE")

    # -------------------------------------------------------------- missions
    def test_missions_empty_and_not_found(self):
        missions = self.fx.get("/v1/missions?limit=10")
        self.assertTrue(missions["ok"])
        self.assertEqual(missions["missions"], [])
        missing = self.fx.get("/v1/missions/nope-0001")
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"]["code"], "E_MISSION_NOT_FOUND")

    # -------------------------------------------------------------- audit
    def test_audit_endpoint(self):
        run_id = "protocol_test_audit_endpoint"
        self.fx.ok_command("get_telemetry")
        body = self.fx.get("/v1/audit?since_seq=0")
        self.assertTrue(body["ok"])
        self.assertTrue(body["events"])
        self.assertGreaterEqual(body["last_seq"], len(body["events"]))
        first_seq = body["events"][0]["seq"]
        tail = self.fx.get("/v1/audit?since_seq=%d" % first_seq)
        self.assertTrue(all(event["seq"] > first_seq for event in tail["events"]))
        # 后台 tick 会持续写审计（关键遥测），因此 last_seq 只保证单调不减；
        # 且 last_seq 必须等于其返回事件序列最后一个 seq（同一次读取的快照语义）
        self.assertGreaterEqual(tail["last_seq"], body["last_seq"])
        if tail["events"]:
            self.assertEqual(tail["last_seq"], tail["events"][-1]["seq"])
        else:
            self.assertEqual(tail["last_seq"], first_seq)


if __name__ == "__main__":
    unittest.main()
