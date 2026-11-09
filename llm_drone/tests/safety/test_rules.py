"""SafetyValidator 规则逐条测试（A1-A10 + E_STATE/E_BUSY/E_NOT_AIRBORNE + 默认值 + 顺序）。

纯函数测试：不启动 HTTP，直接断言 SafetyDecision.error_code（PROTOCOL.md §8.2 逐字）。
"""

from __future__ import annotations

import math
import unittest

from safety import errors, geo
from safety.config import load_config
from safety.schemas import TOOL_NAMES, normalize_mission, spec_tool_names
from safety.validator import (
    estimate_mission_energy_pct,
    nominal_state,
    preflight_checks,
    validate_command,
)

CONFIG = load_config()


def check(tool, args=None, confirm=None, telemetry=None, active_mission_id=None):
    return validate_command(
        tool,
        args or {},
        confirm=confirm,
        telemetry=telemetry or nominal_state(),
        config=CONFIG,
        active_mission_id=active_mission_id,
    )


def hovering(**overrides):
    return nominal_state(state="hovering", alt_rel_m=40.0, alt_abs_m=83.0, **overrides)


def mission_of(waypoints, mission_id=None):
    mission = {
        "schema": "llm_drone.mission/v1",
        "type": "grid",
        "origin_wgs84": {"lat": 39.9042, "lon": 116.4074, "alt": 43.0},
        "home": {"lat": 39.9042, "lon": 116.4074, "alt_abs_m": 43.0},
        "flight": {"altitude_m": 40.0, "speed_mps": 5.0, "gimbal_pitch_deg": -45.0, "heading_deg": 0.0},
        "waypoints": waypoints,
    }
    if mission_id:
        mission["mission_id"] = mission_id
    return mission


def waypoint(lat, lon, alt_rel_m=40.0, speed_mps=5.0, action="photo"):
    return {
        "lat": float(lat),
        "lon": float(lon),
        "alt_rel_m": float(alt_rel_m),
        "heading_deg": 0.0,
        "gimbal_pitch_deg": -45.0,
        "speed_mps": float(speed_mps),
        "action": action,
    }


def far_waypoint(distance_m=800.0):
    point = geo.offset_latlon(39.9042, 116.4074, 90.0, distance_m)
    return waypoint(point["lat"], point["lon"])


def no_fly_waypoint():
    # 位于 PROTOCOL.md §8.1 默认禁飞多边形内
    return waypoint(39.9048, 116.4080)


class DefaultsTest(unittest.TestCase):
    """§8 / §8.1 默认值逐项断言（对抗测试使用默认值）。"""

    def test_thresholds(self):
        self.assertEqual(CONFIG.max_alt_m, 120.0)
        self.assertEqual(CONFIG.max_speed_mps, 15.0)
        self.assertEqual(CONFIG.min_takeoff_battery_pct, 30.0)
        self.assertEqual(CONFIG.rth_reserve_pct, 20.0)
        self.assertEqual(CONFIG.force_rth_pct, 20.0)
        self.assertEqual(CONFIG.gps_min_fix, 3)
        self.assertEqual(CONFIG.gps_min_satellites, 10)
        self.assertTrue(CONFIG.require_rc)
        self.assertFalse(CONFIG.allow_real_mode)

    def test_geofence(self):
        fence = CONFIG.geofence
        self.assertEqual(fence["type"], "circle")
        self.assertAlmostEqual(fence["center"]["lat"], 39.9042)
        self.assertAlmostEqual(fence["center"]["lon"], 116.4074)
        self.assertEqual(fence["radius_m"], 300.0)

    def test_no_fly_zone_polygon(self):
        self.assertEqual(len(CONFIG.no_fly_zones), 1)
        zone = CONFIG.no_fly_zones[0]
        self.assertEqual(zone["name"], "default_no_fly")
        self.assertEqual(zone["alt_range_m"], [0, 120])
        expected = [
            {"lat": 39.9046, "lon": 116.4078},
            {"lat": 39.9050, "lon": 116.4078},
            {"lat": 39.9050, "lon": 116.4082},
            {"lat": 39.9046, "lon": 116.4082},
        ]
        self.assertEqual(zone["polygon"], expected)

    def test_error_code_spelling(self):
        expected = {
            "E_SCHEMA", "E_PARAM_RANGE", "E_UNKNOWN_TOOL", "E_CONFIRM_REQUIRED", "E_MODE",
            "E_STATE", "E_BUSY", "E_ALT_LIMIT", "E_SPEED_LIMIT", "E_GEOFENCE", "E_NOFLY",
            "E_BATTERY_TAKEOFF", "E_BATTERY_RTH", "E_GPS", "E_RC_LINK",
            "E_MISSION_NOT_FOUND", "E_REAL_NOT_AVAILABLE", "E_NOT_SUPPORTED",
            "E_NOT_AIRBORNE", "E_INTERNAL",
        }
        for code in expected:
            self.assertEqual(getattr(errors, code), code)
        self.assertEqual(set(errors.ERROR_MESSAGES), expected)

    def test_whitelist_is_subset_of_spec_tools(self):
        spec_names = set(spec_tool_names())
        self.assertTrue(spec_names, "spec/tools.json 读取失败")
        self.assertTrue(set(TOOL_NAMES) <= spec_names)
        self.assertIn("takeoff", TOOL_NAMES)
        self.assertNotIn("plan_capture_mission", TOOL_NAMES)
        self.assertNotIn("orbit", TOOL_NAMES)


class AdversarialRulesTest(unittest.TestCase):
    """§11.2 A1-A10 的 Agent 侧确定性断言。"""

    # A1 超限高
    def test_A1_alt_limit(self):
        for altitude in (200.0, 150.0, 120.0001):
            decision = check("takeoff", {"altitude_m": altitude}, confirm=True)
            self.assertFalse(decision.allow)
            self.assertEqual(decision.error_code, "E_ALT_LIMIT", altitude)
            self.assertTrue(decision.reasons)
        # 边界值 120m 合法
        self.assertTrue(check("takeoff", {"altitude_m": 120.0}, confirm=True).allow)

    # A2 飞出围栏
    def test_A2_geofence(self):
        decision = check(
            "goto_waypoints",
            {"mission": mission_of([far_waypoint(800.0)])},
            confirm=True,
            telemetry=hovering(),
        )
        self.assertFalse(decision.allow)
        self.assertEqual(decision.error_code, "E_GEOFENCE")
        self.assertIn("waypoint[0]", " ".join(decision.reasons))

    # A3 禁飞区
    def test_A3_no_fly_zone(self):
        decision = check(
            "goto_waypoints",
            {"mission": mission_of([no_fly_waypoint()])},
            confirm=True,
            telemetry=hovering(),
        )
        self.assertFalse(decision.allow)
        self.assertEqual(decision.error_code, "E_NOFLY")
        self.assertIn("default_no_fly", " ".join(decision.reasons))

    # A4 低电量起飞
    def test_A4_battery_takeoff(self):
        decision = check(
            "takeoff", {"altitude_m": 40}, confirm=True, telemetry=nominal_state(battery_pct=22.0)
        )
        self.assertEqual(decision.error_code, "E_BATTERY_TAKEOFF")
        self.assertIn("22.0", " ".join(decision.reasons))
        # 30% 恰好允许
        self.assertTrue(
            check("takeoff", {"altitude_m": 40}, confirm=True, telemetry=nominal_state(battery_pct=30.0)).allow
        )

    # A5 无确认执行
    def test_A5_confirm_required(self):
        takeoff = check("takeoff", {"altitude_m": 40}, confirm=None)
        self.assertEqual(takeoff.error_code, "E_CONFIRM_REQUIRED")
        takeoff_false = check("takeoff", {"altitude_m": 40}, confirm=False)
        self.assertEqual(takeoff_false.error_code, "E_CONFIRM_REQUIRED")
        goto = check(
            "goto_waypoints",
            {"mission": mission_of([waypoint(39.9042, 116.4074)])},
            confirm=False,
            telemetry=hovering(),
        )
        self.assertEqual(goto.error_code, "E_CONFIRM_REQUIRED")

    # A7 GPS 差
    def test_A7_gps(self):
        decision = check(
            "takeoff",
            {"altitude_m": 40},
            confirm=True,
            telemetry=nominal_state(gps={"fix": 1, "satellites": 6}),
        )
        self.assertEqual(decision.error_code, "E_GPS")
        # 只差卫星数
        decision = check(
            "takeoff",
            {"altitude_m": 40},
            confirm=True,
            telemetry=nominal_state(gps={"fix": 3, "satellites": 9}),
        )
        self.assertEqual(decision.error_code, "E_GPS")

    # A8 遥控断开
    def test_A8_rc_link(self):
        decision = check(
            "takeoff",
            {"altitude_m": 40},
            confirm=True,
            telemetry=nominal_state(rc={"connected": False, "signal": "lost"}),
        )
        self.assertEqual(decision.error_code, "E_RC_LINK")

    # A9 非法参数 / 未知工具
    def test_A9_param_range(self):
        decision = check("takeoff", {"altitude_m": -5}, confirm=True)
        self.assertEqual(decision.error_code, "E_PARAM_RANGE")
        decision = check(
            "goto_waypoints",
            {"mission": mission_of([waypoint(39.9042, 116.4074, speed_mps=20.0)])},
            confirm=True,
            telemetry=hovering(),
        )
        self.assertEqual(decision.error_code, "E_SPEED_LIMIT")
        decision = check("set_gimbal", {"pitch_deg": 10}, telemetry=hovering())
        self.assertEqual(decision.error_code, "E_PARAM_RANGE")
        decision = check("capture_photo", {"count": 21}, telemetry=hovering())
        self.assertEqual(decision.error_code, "E_PARAM_RANGE")
        decision = check("abort", {"reason": "  "})
        self.assertEqual(decision.error_code, "E_PARAM_RANGE")

    def test_A9_unknown_tool(self):
        for tool in ("fly_to_moon", "plan_capture_mission", "orbit", None, "takeoff; rm -rf /"):
            decision = check(tool, {})
            self.assertFalse(decision.allow, tool)
            self.assertEqual(decision.error_code, "E_UNKNOWN_TOOL", tool)

    def test_A9_schema(self):
        self.assertEqual(check("takeoff", {}, confirm=True).error_code, "E_SCHEMA")
        self.assertEqual(check("takeoff", {"altitude_m": "40"}, confirm=True).error_code, "E_SCHEMA")
        self.assertEqual(
            check("takeoff", {"altitude_m": 40, "extra": 1}, confirm=True).error_code, "E_SCHEMA"
        )
        self.assertEqual(check("goto_waypoints", {"waypoints": []}, confirm=True).error_code, "E_SCHEMA")
        nested = waypoint(39.9042, 116.4074)
        nested["gimbal"] = {"pitch": -45}
        self.assertEqual(
            check("goto_waypoints", {"mission": mission_of([nested])}, confirm=True, telemetry=hovering()).error_code,
            "E_SCHEMA",
        )

    # A10 real 模式
    def test_A10_real_not_available(self):
        decision = check("set_mode", {"mode": "real"}, confirm=True)
        self.assertEqual(decision.error_code, "E_REAL_NOT_AVAILABLE")
        # 即使缺 confirm 也是 E_REAL_NOT_AVAILABLE（mode 阶段先于 confirm）
        self.assertEqual(check("set_mode", {"mode": "real"}, confirm=False).error_code, "E_REAL_NOT_AVAILABLE")
        # 切到 sim 是允许的
        self.assertTrue(check("set_mode", {"mode": "sim"}, confirm=True).allow)


class StateAndBusyTest(unittest.TestCase):
    def test_E_STATE(self):
        self.assertEqual(check("takeoff", {"altitude_m": 40}, confirm=True, telemetry=hovering()).error_code, "E_STATE")
        self.assertEqual(check("land", {}, telemetry=nominal_state()).error_code, "E_STATE")
        self.assertEqual(
            check(
                "goto_waypoints",
                {"mission": mission_of([waypoint(39.9042, 116.4074)])},
                confirm=True,
                telemetry=nominal_state(),
            ).error_code,
            "E_STATE",
        )
        self.assertEqual(
            check("set_mode", {"mode": "sim"}, confirm=True, telemetry=hovering()).error_code, "E_STATE"
        )

    def test_E_NOT_AIRBORNE(self):
        for tool, args in (
            ("set_gimbal", {"pitch_deg": -45}),
            ("capture_photo", {"count": 1}),
            ("start_video", {}),
            ("stop_video", {}),
        ):
            decision = check(tool, args, telemetry=nominal_state())
            self.assertEqual(decision.error_code, "E_NOT_AIRBORNE", tool)

    def test_E_BUSY(self):
        mission_state = nominal_state(state="mission", mission_id="m-0001")
        for tool, args, confirm in (
            ("takeoff", {"altitude_m": 40}, True),
            ("capture_photo", {"count": 1}, None),
            ("land", {}, None),
            ("set_gimbal", {"pitch_deg": -30}, None),
        ):
            decision = check(tool, args, confirm=confirm, telemetry=mission_state, active_mission_id="m-0001")
            self.assertFalse(decision.allow, tool)
            self.assertEqual(decision.error_code, "E_BUSY", tool)
        # 任务中允许的命令
        for tool, args, confirm in (
            ("abort", {"reason": "用户中止"}, None),
            ("get_telemetry", {}, None),
            ("get_mission_status", {"mission_id": "m-0001"}, None),
            ("return_to_home", {}, None),
        ):
            decision = check(tool, args, confirm=confirm, telemetry=mission_state, active_mission_id="m-0001")
            self.assertTrue(decision.allow, "%s: %s" % (tool, decision.error_code))

    def test_validation_order(self):
        # battery（规则5）先于 altitude 范围（规则1）
        decision = check(
            "takeoff", {"altitude_m": 200}, confirm=True, telemetry=nominal_state(battery_pct=22.0)
        )
        self.assertEqual(decision.error_code, "E_BATTERY_TAKEOFF")
        # confirm 先于 battery
        decision = check(
            "takeoff", {"altitude_m": 200}, confirm=False, telemetry=nominal_state(battery_pct=22.0)
        )
        self.assertEqual(decision.error_code, "E_CONFIRM_REQUIRED")
        # state 先于 geofence：地面 goto 远处航点 -> E_STATE（演示 A2/A3 需先 takeoff）
        decision = check(
            "goto_waypoints", {"mission": mission_of([far_waypoint(800.0)])}, confirm=True, telemetry=nominal_state()
        )
        self.assertEqual(decision.error_code, "E_STATE")
        # geofence 先于 no-fly
        decision = check(
            "goto_waypoints",
            {"mission": mission_of([no_fly_waypoint(), far_waypoint(800.0)])},
            confirm=True,
            telemetry=hovering(),
        )
        self.assertEqual(decision.error_code, "E_GEOFENCE")


class EnergyAndPreflightTest(unittest.TestCase):
    def test_sample_mission_energy_feasible(self):
        sample = normalize_mission(_load_sample_mission(), CONFIG.origin)
        estimate = estimate_mission_energy_pct(sample, hovering(), CONFIG)
        self.assertTrue(estimate["feasible"])
        self.assertLess(estimate["required_pct"], 40.0)
        self.assertEqual(estimate["n_waypoints"], 16)

    def test_battery_rth_rejected_for_long_mission(self):
        # 16 个航点来回横穿围栏（≈8.4 km），40% 电量任务前估算不足
        north = geo.offset_latlon(39.9042, 116.4074, 0.0, 280.0)
        south = geo.offset_latlon(39.9042, 116.4074, 180.0, 280.0)
        points = []
        for index in range(16):
            target = north if index % 2 == 0 else south
            points.append(waypoint(target["lat"], target["lon"], alt_rel_m=40.0, action="none"))
        decision = check(
            "goto_waypoints",
            {"mission": mission_of(points)},
            confirm=True,
            telemetry=hovering(battery_pct=40.0),
        )
        self.assertFalse(decision.allow)
        self.assertEqual(decision.error_code, "E_BATTERY_RTH")
        details = decision.details
        self.assertGreater(details["required_pct"], 40.0)

    def test_preflight(self):
        body = preflight_checks(nominal_state(), CONFIG)
        self.assertTrue(body["ok"])
        self.assertTrue(body["can_fly"])
        names = [item["name"] for item in body["checks"]]
        for expected in ("mode", "state", "battery", "gps", "rc", "geofence", "no_fly_zone"):
            self.assertIn(expected, names)
        bad = preflight_checks(nominal_state(battery_pct=22.0, gps={"fix": 1, "satellites": 4}), CONFIG)
        self.assertFalse(bad["can_fly"])
        failed = {item["name"] for item in bad["checks"] if not item["pass"]}
        self.assertTrue({"battery", "gps"} <= failed)


class MissionSchemaTest(unittest.TestCase):
    def test_normalize_sample_mission(self):
        sample = _load_sample_mission()
        mission = normalize_mission(sample, CONFIG.origin)
        self.assertEqual(len(mission["waypoints"]), 16)
        first = mission["waypoints"][0]
        self.assertAlmostEqual(first["alt_abs_m"], 83.0)
        self.assertEqual(first["action"], "photo")
        self.assertEqual(first["heading_deg"], 0.0)
        self.assertEqual(mission["mission_id"], "sample-grid-16")
        self.assertEqual(mission["photo_points"], list(range(16)))

    def test_missing_mission_id_is_none(self):
        mission = normalize_mission(mission_of([waypoint(39.9042, 116.4074)]), CONFIG.origin)
        self.assertIsNone(mission["mission_id"])

    def test_invalid_mission_schema(self):
        decision = check(
            "goto_waypoints",
            {"mission": {"schema": "llm_drone.mission/v1", "waypoints": []}},
            confirm=True,
            telemetry=hovering(),
        )
        self.assertEqual(decision.error_code, "E_SCHEMA")


def _load_sample_mission():
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "spec" / "sample_mission.json"
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


if __name__ == "__main__":
    unittest.main()
