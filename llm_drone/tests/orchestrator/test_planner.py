# -*- coding: utf-8 -*-
import json
import math
import unittest

from orchestrator import planner


class PlannerGeometryTest(unittest.TestCase):
    def setUp(self):
        self.home = {"lat": 39.9042, "lon": 116.4074, "alt_abs_m": 43.0}

    def test_offset_and_distance_roundtrip(self):
        p = planner.offset_latlon(39.9042, 116.4074, 100.0, 0.0)
        self.assertAlmostEqual(planner.distance_between(
            {"lat": 39.9042, "lon": 116.4074}, p), 100.0, places=3)
        east = planner.offset_latlon(39.9042, 116.4074, 100.0, 90.0)
        self.assertAlmostEqual(planner.distance_between(
            {"lat": 39.9042, "lon": 116.4074}, east), 100.0, places=3)

    def test_ground_footprint_shrinks_with_nadir(self):
        fp45 = planner.ground_footprint(40.0, -45.0)
        fp90 = planner.ground_footprint(40.0, -90.0)
        self.assertGreater(fp45["along_m"], fp90["along_m"])
        self.assertAlmostEqual(fp90["along_m"],
                               2 * 40.0 * math.tan(math.radians(planner.CAMERA["fov_vertical_deg"] / 2)),
                               places=2)

    def test_grid_boustrophedon_and_counts(self):
        plan = planner.plan_capture_mission({
            "pattern": "grid", "center_lat": 39.9042, "center_lon": 116.4074,
            "altitude_m": 40.0, "radius_m": 28.0, "overlap": 0.7,
            "gimbal_pitch_deg": -45.0}, self.home)
        mission = plan["mission"]
        waypoints = mission["waypoints"]
        self.assertGreaterEqual(mission["stats"]["n_photos"], 12)
        self.assertEqual(mission["stats"]["n_photos"], len(mission["photo_points"]))
        self.assertEqual(mission["schema"], "llm_drone.mission/v1")
        self.assertEqual(mission["type"], "grid")
        self.assertEqual(mission["home"]["alt_abs_m"], 43.0)
        # boustrophedon：同一航线内纬度单调、相邻航线方向相反
        lines = {}
        for wp in waypoints:
            lines.setdefault(round(wp["lon"], 9), []).append(wp)
        self.assertGreaterEqual(len(lines), 2)
        lat_orders = []
        for lon_value, wps in lines.items():
            lats = [wp["lat"] for wp in wps]
            lat_orders.append(lats == sorted(lats) or lats == sorted(lats, reverse=True))
        self.assertTrue(all(lat_orders))
        # 航点/照片数量与 stats/photo_points 一致
        self.assertEqual(len(waypoints), mission["stats"]["n_waypoints"])
        self.assertTrue(all(wp["action"] == "photo" for wp in waypoints))
        for wp in waypoints:
            self.assertIn("alt_abs_m", wp)
            self.assertAlmostEqual(wp["alt_abs_m"], 43.0 + wp["alt_rel_m"], places=1)
        self.assertGreater(mission["stats"]["est_distance_m"], 0)
        self.assertGreater(mission["stats"]["est_duration_s"], 0)
        self.assertIn("origin_wgs84", mission)
        self.assertIn("camera", mission)
        self.assertIn("flight", mission)

    def test_orbit_shots_and_heading_towards_target(self):
        plan = planner.plan_capture_mission({
            "pattern": "orbit", "center_lat": 39.90435, "center_lon": 116.40755,
            "altitude_m": 50.0, "radius_m": 30.0, "shots": 12,
            "gimbal_pitch_deg": -30.0}, self.home)
        mission = plan["mission"]
        self.assertEqual(mission["type"], "orbit")
        self.assertEqual(len(mission["waypoints"]), 12)
        self.assertEqual(mission["stats"]["n_photos"], 12)
        center = {"lat": 39.90435, "lon": 116.40755}
        for wp in mission["waypoints"]:
            dist = planner.distance_between({"lat": wp["lat"], "lon": wp["lon"]}, center)
            self.assertAlmostEqual(dist, 30.0, delta=1.5)
            expected_heading = planner.bearing_between(
                {"lat": wp["lat"], "lon": wp["lon"]}, center)
            circular_diff = abs(((wp["heading_deg"] - expected_heading + 180) % 360) - 180)
            self.assertLess(circular_diff, 1.0)
            self.assertEqual(wp["gimbal_pitch_deg"], -30.0)

    def test_point_shots(self):
        plan = planner.plan_capture_mission({
            "pattern": "point", "center_lat": 39.9045, "center_lon": 116.4070,
            "altitude_m": 30.0, "shots": 5, "gimbal_pitch_deg": -45.0}, self.home)
        mission = plan["mission"]
        self.assertEqual(mission["type"], "point")
        self.assertEqual(mission["stats"]["n_photos"], 5)
        self.assertEqual(len(mission["waypoints"]), 5)
        self.assertEqual(mission["photo_points"], [0, 1, 2, 3, 4])
        self.assertTrue(all(wp["lat"] == mission["waypoints"][0]["lat"]
                            for wp in mission["waypoints"]))

    def test_plan_id_is_deterministic(self):
        args = {"pattern": "grid", "center_lat": 39.9042, "center_lon": 116.4074,
                "altitude_m": 40.0, "radius_m": 28.0}
        p1 = planner.plan_capture_mission(args, self.home)
        p2 = planner.plan_capture_mission(args, self.home)
        self.assertEqual(p1["plan_id"], p2["plan_id"])
        self.assertTrue(p1["plan_id"].startswith("plan-"))

    def test_warnings_for_oversize(self):
        plan = planner.plan_capture_mission({
            "pattern": "grid", "center_lat": 39.9042, "center_lon": 116.4074,
            "altitude_m": 150.0, "radius_m": 20.0}, self.home)
        self.assertTrue(any("E_ALT_LIMIT" in w for w in plan["warnings"]))

    def test_home_from_telemetry(self):
        home = planner.home_from_telemetry({
            "ok": True, "lat": 39.9, "lon": 116.4, "alt_abs_m": 40.0,
            "home": {"lat": 39.9050, "lon": 116.4080, "alt_abs_m": 43.5}})
        self.assertEqual(home["lat"], 39.9050)
        self.assertEqual(home["alt_abs_m"], 43.5)
        default = planner.home_from_telemetry({})
        self.assertEqual(default["lat"], planner.ORIGIN_WGS84["lat"])

    def test_mission_from_waypoints(self):
        plan = planner.mission_from_waypoints(
            [{"lat": 39.9043, "lon": 116.4075, "alt_rel_m": 40}], home=self.home)
        mission = plan["mission"]
        self.assertEqual(mission["schema"], "llm_drone.mission/v1")
        self.assertEqual(len(mission["waypoints"]), 1)
        self.assertEqual(mission["waypoints"][0]["action"], "photo")
        self.assertEqual(mission["waypoints"][0]["alt_abs_m"], 83.0)

    def test_invalid_plan_args_raise(self):
        with self.assertRaises(ValueError):
            planner.plan_capture_mission({"pattern": "spiral", "center_lat": 39.9,
                                          "center_lon": 116.4, "altitude_m": 40})
        with self.assertRaises(ValueError):
            planner.plan_capture_mission({"pattern": "grid", "center_lat": 39.9,
                                          "center_lon": 116.4, "altitude_m": -5})


if __name__ == "__main__":
    unittest.main()
