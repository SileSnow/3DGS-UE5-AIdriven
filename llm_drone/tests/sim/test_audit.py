"""审计测试：JSONL 字段完整、seq 递增、拒绝含 error_code/reasons、force_rth、mission 事件。"""

from __future__ import annotations

import time
import unittest

from sim._support import SimFixture


class AuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = SimFixture(time_scale=100.0, tick_wall_s=0.02)

    @classmethod
    def tearDownClass(cls):
        cls.fx.close()

    def setUp(self):
        self.run_id = "audit_%s" % self._testMethodName
        self.fx.reset(run_id=self.run_id)

    # -------------------------------------------------------------- 字段/seq
    def test_audit_jsonl_fields_and_sequence(self):
        self.fx.ok_command("get_telemetry")
        rejected = self.fx.command("fly_to_moon", {})
        self.assertFalse(rejected["ok"])
        rejected2 = self.fx.command("land", {})  # 地面 land -> E_STATE
        self.assertFalse(rejected2["ok"])
        events = self.fx.audit_events(self.run_id)
        self.assertGreaterEqual(len(events), 8)
        # 每行合法 JSON、必含 ts/seq/run_id/event、seq 从 1 严格递增
        self.assertEqual([event["seq"] for event in events], list(range(1, len(events) + 1)))
        for event in events:
            self.assertIsInstance(event["event"], str)
            self.assertIsInstance(event["ts"], str)
            self.assertEqual(event["run_id"], self.run_id)
            self.assertIn("seq", event)
        # 命令类事件字段
        received = [e for e in events if e["event"] == "command_received"]
        self.assertGreaterEqual(len(received), 3)
        for event in received:
            for key in ("tool", "command_id", "args", "confirm", "decision"):
                self.assertIn(key, event)
            self.assertEqual(event["decision"], "pending")
        accepted = [e for e in events if e["event"] == "command_accepted"]
        self.assertTrue(accepted)
        for event in accepted:
            self.assertIn("state_before", event)
            self.assertIn("state_after", event)
            self.assertEqual(event["decision"], "allow")
        rejected_events = [e for e in events if e["event"] == "command_rejected"]
        self.assertGreaterEqual(len(rejected_events), 2)
        for event in rejected_events:
            self.assertEqual(event["decision"], "reject")
            self.assertIn("error_code", event)
            self.assertIn("reasons", event)
            self.assertIsInstance(event["reasons"], list)
            self.assertTrue(event["reasons"])
            self.assertIn("tool", event)
            self.assertIn("command_id", event)
        self.assertIn("E_UNKNOWN_TOOL", [e["error_code"] for e in rejected_events])
        # safety_check 事件
        safety_checks = [e for e in events if e["event"] == "safety_check"]
        self.assertTrue(safety_checks)
        self.assertTrue(all(e["decision"] in ("allow", "reject") for e in safety_checks))

    # -------------------------------------------------------------- audit endpoint
    def test_audit_endpoint_matches_file(self):
        self.fx.ok_command("get_telemetry")
        # 服务端 tick 线程可能在本测试读取文件与查询端点之间追加事件（如 telemetry_keyframe），
        # 直接比较会产生偶发 5!=4 的竞态。这里轮询到“文件 == 端点”稳定为止，再断言。
        deadline = time.time() + 3.0
        events = body = None
        while time.time() < deadline:
            events = self.fx.audit_events(self.run_id)
            body = self.fx.get("/v1/audit?since_seq=0")
            if (body.get("ok") and events
                    and body.get("last_seq") == events[-1]["seq"]
                    and [e["seq"] for e in body["events"]] == [e["seq"] for e in events]):
                break
            time.sleep(0.02)
        self.assertIsNotNone(events)
        self.assertIsNotNone(body)
        self.assertTrue(body["ok"])
        self.assertTrue(events)
        self.assertEqual(body["last_seq"], events[-1]["seq"])
        self.assertEqual([e["seq"] for e in body["events"]], [e["seq"] for e in events])
        cut = events[2]["seq"]
        tail = self.fx.get("/v1/audit?since_seq=%d" % cut)
        self.assertTrue(all(event["seq"] > cut for event in tail["events"]))

    # -------------------------------------------------------------- force_rth
    def test_force_rth_audited_and_landed(self):
        self.fx.takeoff_and_hover(40)
        self.fx.sim_config(battery_pct=19)
        force = self.fx.wait_audit_event(
            self.run_id, "force_rth", predicate=lambda event: event.get("decision") == "force_rth"
        )
        self.assertIn("battery", force["reason"])
        self.assertLess(force["battery_pct"], 20.0)
        idle = self.fx.wait_state("idle", timeout=40.0)
        self.assertAlmostEqual(idle["alt_rel_m"], 0.0, delta=0.05)
        events = self.fx.audit_events(self.run_id)
        names = [event["event"] for event in events]
        self.assertIn("rth_started", names)
        self.assertIn("landed", names)
        self.assertIsNone(self.fx.telemetry()["mission_id"])

    # -------------------------------------------------------------- mission 事件
    def test_mission_events_audited(self):
        self.fx.takeoff_and_hover(40)
        body = self.fx.ok_command(
            "goto_waypoints", {"mission": self.fx.sample_mission(), "photo_interval_s": 1}, confirm=True
        )
        mission_id = body["mission_id"]
        self.fx.wait_mission(mission_id)
        events = self.fx.audit_events(self.run_id)
        started = [e for e in events if e["event"] == "mission_started"]
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0]["mission_id"], mission_id)
        self.assertEqual(started[0]["n_waypoints"], 16)
        photos = [e for e in events if e["event"] == "photo_captured"]
        self.assertEqual(len(photos), 16)
        for index, event in enumerate(photos):
            self.assertEqual(event["mission_id"], mission_id)
            self.assertEqual(event["index"], index)
            self.assertTrue(event["file"].startswith("SIM_"))
        completed = [e for e in events if e["event"] == "mission_completed"]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["n_photos"], 16)


if __name__ == "__main__":
    unittest.main()
