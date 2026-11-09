"""对抗场景 HTTP 集成测试（A1-A10 / E_BUSY / E_NOT_AIRBORNE，真实 HTTP + 真实 tick 线程）。"""

from __future__ import annotations

import unittest

from safety import geo
from sim._support import SimFixture

ORIGIN = {"lat": 39.9042, "lon": 116.4074, "alt": 43.0}


def mission_with(waypoints, mission_id=None):
    mission = {
        "schema": "llm_drone.mission/v1",
        "type": "grid",
        "origin_wgs84": ORIGIN,
        "home": {"lat": 39.9042, "lon": 116.4074, "alt_abs_m": 43.0},
        "flight": {"altitude_m": 40.0, "speed_mps": 5.0, "gimbal_pitch_deg": -45.0},
        "waypoints": waypoints,
    }
    if mission_id:
        mission["mission_id"] = mission_id
    return mission


def waypoint(lat, lon, alt_rel_m=40.0, speed_mps=5.0):
    return {
        "lat": float(lat),
        "lon": float(lon),
        "alt_rel_m": float(alt_rel_m),
        "heading_deg": 0.0,
        "gimbal_pitch_deg": -45.0,
        "speed_mps": float(speed_mps),
        "action": "photo",
    }


class AdversarialHTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = SimFixture(time_scale=100.0, tick_wall_s=0.02)

    @classmethod
    def tearDownClass(cls):
        cls.fx.close()

    def setUp(self):
        self.run_id = "safety_%s" % self._testMethodName
        self.fx.reset(run_id=self.run_id)

    def assert_rejected(self, body, code):
        self.assertFalse(body.get("ok"), body)
        self.assertEqual(body["error"]["code"], code, body)
        return body

    # A1 超限高
    def test_A1_alt_limit_http(self):
        body = self.fx.command("takeoff", {"altitude_m": 200}, confirm=True)
        self.assert_rejected(body, "E_ALT_LIMIT")
        self.assertEqual(self.fx.telemetry()["state"], "idle")
        body = self.fx.command("takeoff", {"altitude_m": 150}, confirm=True)
        self.assert_rejected(body, "E_ALT_LIMIT")

    # A2 飞出围栏（先 takeoff，避免 E_STATE 抢先 —— 校验顺序严格按 §4）
    def test_A2_geofence_after_takeoff(self):
        self.fx.takeoff_and_hover(40)
        far = geo.offset_latlon(39.9042, 116.4074, 90.0, 800.0)
        body = self.fx.command(
            "goto_waypoints", {"mission": mission_with([waypoint(far["lat"], far["lon"])])}, confirm=True
        )
        self.assert_rejected(body, "E_GEOFENCE")
        self.assertEqual(self.fx.telemetry()["state"], "hovering")
        # 审计有拒绝记录
        events = self.fx.audit_events(self.run_id)
        rejected = [e for e in events if e["event"] == "command_rejected"]
        self.assertTrue(any(e["error_code"] == "E_GEOFENCE" for e in rejected))
        self.fx.ok_command("abort", {"reason": "cleanup"})

    # A3 禁飞区
    def test_A3_no_fly_after_takeoff(self):
        self.fx.takeoff_and_hover(40)
        body = self.fx.command(
            "goto_waypoints", {"mission": mission_with([waypoint(39.9048, 116.4080)])}, confirm=True
        )
        self.assert_rejected(body, "E_NOFLY")
        self.assertEqual(self.fx.telemetry()["state"], "hovering")
        self.fx.ok_command("abort", {"reason": "cleanup"})

    # A4 低电量起飞
    def test_A4_battery_takeoff_http(self):
        self.fx.sim_config(battery_pct=22.0)
        body = self.fx.command("takeoff", {"altitude_m": 40}, confirm=True)
        self.assert_rejected(body, "E_BATTERY_TAKEOFF")
        self.assertEqual(self.fx.telemetry()["state"], "idle")

    # A5 无确认执行
    def test_A5_confirm_required_http(self):
        body = self.fx.command("takeoff", {"altitude_m": 40}, confirm=False)
        self.assert_rejected(body, "E_CONFIRM_REQUIRED")
        body = self.fx.command("takeoff", {"altitude_m": 40})
        self.assert_rejected(body, "E_CONFIRM_REQUIRED")
        body = self.fx.command("goto_waypoints", {"mission": self.fx.sample_mission()}, confirm=False)
        self.assert_rejected(body, "E_CONFIRM_REQUIRED")

    # A6 飞行中低电量 -> 强制 RTH（审计 decision=force_rth，最终 landed/idle）
    def test_A6_force_rth_http(self):
        self.fx.takeoff_and_hover(40)
        self.fx.sim_config(battery_pct=19)
        record = self.fx.wait_audit_event(
            self.run_id, "force_rth", predicate=lambda e: e.get("decision") == "force_rth"
        )
        self.assertLess(record["battery_pct"], 20.0)
        idle = self.fx.wait_state("idle", timeout=40.0)
        self.assertAlmostEqual(idle["alt_rel_m"], 0.0, delta=0.05)
        self.assertIsNone(idle["mission_id"])
        events = self.fx.audit_events(self.run_id)
        self.assertTrue(any(e["event"] == "landed" for e in events))

    # A7 GPS 差
    def test_A7_gps_http(self):
        self.fx.sim_config(gps_fix=1, gps_satellites=6)
        body = self.fx.command("takeoff", {"altitude_m": 40}, confirm=True)
        self.assert_rejected(body, "E_GPS")

    # A8 RC 断开
    def test_A8_rc_link_http(self):
        self.fx.sim_config(rc_connected=False)
        body = self.fx.command("takeoff", {"altitude_m": 40}, confirm=True)
        self.assert_rejected(body, "E_RC_LINK")

    # A9 非法参数 / 未知工具
    def test_A9_param_range_and_unknown_tool_http(self):
        body = self.fx.command("takeoff", {"altitude_m": -5}, confirm=True)
        self.assert_rejected(body, "E_PARAM_RANGE")
        body = self.fx.command("fly_to_moon", {})
        self.assert_rejected(body, "E_UNKNOWN_TOOL")
        body = self.fx.command("takeoff", {"altitude_m": "forty"}, confirm=True)
        self.assert_rejected(body, "E_SCHEMA")

    # A10 real 模式
    def test_A10_real_mode_http(self):
        body = self.fx.command("set_mode", {"mode": "real"}, confirm=True)
        self.assert_rejected(body, "E_REAL_NOT_AVAILABLE")
        self.assertEqual(self.fx.telemetry()["mode"], "sim")

    # E_BUSY：任务执行中的并发命令
    def test_E_BUSY_http(self):
        self.fx.takeoff_and_hover(40)
        body = self.fx.ok_command(
            "goto_waypoints", {"mission": self.fx.sample_mission(), "photo_interval_s": 1}, confirm=True
        )
        mission_id = body["mission_id"]
        self.assertEqual(body["state"], "mission")
        busy = self.fx.command("capture_photo", {"count": 1})
        self.assert_rejected(busy, "E_BUSY")
        busy = self.fx.command("land", {})
        self.assert_rejected(busy, "E_BUSY")
        abort = self.fx.ok_command("abort", {"reason": "E_BUSY 测试清理"})
        self.assertEqual(abort["mission_state"], "aborted")
        self.fx.wait_state("hovering")
        record = self.fx.get("/v1/missions/%s" % mission_id)
        self.assertEqual(record["state"], "aborted")

    # E_NOT_AIRBORNE：地面拍照/云台
    def test_E_NOT_AIRBORNE_http(self):
        body = self.fx.command("capture_photo", {"count": 1})
        self.assert_rejected(body, "E_NOT_AIRBORNE")
        body = self.fx.command("set_gimbal", {"pitch_deg": -45})
        self.assert_rejected(body, "E_NOT_AIRBORNE")

    # E_STATE：地面 goto / 地面 land
    def test_E_STATE_http(self):
        body = self.fx.command("goto_waypoints", {"mission": self.fx.sample_mission()}, confirm=True)
        self.assert_rejected(body, "E_STATE")
        body = self.fx.command("land", {})
        self.assert_rejected(body, "E_STATE")


if __name__ == "__main__":
    unittest.main()
