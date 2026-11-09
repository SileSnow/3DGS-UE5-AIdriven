"""任务测试：takeoff -> goto_waypoints(sample_mission 16 点) -> 16 photos -> completed
-> return_to_home -> land；abort；地面低风险动作 E_NOT_AIRBORNE；状态机 E_STATE。"""

from __future__ import annotations

import unittest

from safety.geo import haversine_m, is_orthonormal_rotation
from sim._support import SimFixture


def _assert_c2w_orthonormal(case: unittest.TestCase, c2w) -> None:
    case.assertEqual(len(c2w), 16)
    case.assertTrue(is_orthonormal_rotation(c2w))
    rows = [
        [c2w[0], c2w[1], c2w[2]],
        [c2w[4], c2w[5], c2w[6]],
        [c2w[8], c2w[9], c2w[10]],
    ]
    for i in range(3):
        for j in range(3):
            dot = sum(rows[i][k] * rows[j][k] for k in range(3))
            expected = 1.0 if i == j else 0.0
            case.assertAlmostEqual(dot, expected, delta=1e-6)


class MissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = SimFixture(time_scale=100.0, tick_wall_s=0.02)

    @classmethod
    def tearDownClass(cls):
        cls.fx.close()

    def setUp(self):
        self.run_id = "mission_%s" % self._testMethodName
        self.fx.reset(run_id=self.run_id)

    # -------------------------------------------------------------- 完整正向任务
    def test_positive_grid_mission_full_flow(self):
        # 1) takeoff
        response = self.fx.ok_command("takeoff", {"altitude_m": 40}, confirm=True)
        self.assertEqual(response["state"], "taking_off")
        hover = self.fx.wait_state("hovering")
        self.assertAlmostEqual(hover["alt_rel_m"], 40.0, delta=0.6)
        self.assertAlmostEqual(hover["alt_abs_m"], 83.0, delta=0.6)
        self.assertGreater(hover["battery_pct"], 90.0)

        # 2) goto_waypoints：spec/sample_mission.json 16 拍照点
        mission = self.fx.sample_mission()
        response = self.fx.ok_command(
            "goto_waypoints", {"mission": mission, "photo_interval_s": 1}, confirm=True
        )
        self.assertEqual(response["state"], "mission")
        self.assertEqual(response["mission_id"], "sample-grid-16")
        self.assertIsNotNone(self.fx.telemetry()["mission_id"])

        # 3) 任务完成：16 张照片
        record = self.fx.wait_mission("sample-grid-16")
        self.assertEqual(record["state"], "completed")
        self.assertEqual(record["progress_pct"], 100.0)
        self.assertEqual(len(record["photos"]), 16)
        self.assertEqual(record["stats"]["n_photos"], 16)
        self.assertGreater(record["stats"]["distance_m"], 200.0)
        self.assertGreater(record["stats"]["duration_s"], 0.0)
        self.assertIsNone(record["error"])
        self.assertIsNotNone(record["started_at"])
        self.assertIsNotNone(record["ended_at"])

        for index, photo in enumerate(record["photos"]):
            self.assertEqual(photo["index"], index)
            self.assertEqual(photo["file"], "SIM_%04d.jpg" % (index + 1))
            for key in ("index", "file", "ts", "lat", "lon", "alt_rel_m", "alt_abs_m", "heading_deg", "gimbal", "c2w"):
                self.assertIn(key, photo)
            self.assertAlmostEqual(photo["lat"], mission["waypoints"][index]["lat"], places=5)
            self.assertAlmostEqual(photo["lon"], mission["waypoints"][index]["lon"], places=5)
            self.assertAlmostEqual(photo["alt_rel_m"], 40.0, delta=0.5)
            self.assertAlmostEqual(photo["alt_abs_m"], 83.0, delta=0.5)
            self.assertAlmostEqual(photo["gimbal"]["pitch"], -45.0, delta=0.5)
            _assert_c2w_orthonormal(self, photo["c2w"])
            # c2w 平移列 = UE 世界 cm（+X=东、+Y=南、+Z=上）
            east = (
                (photo["lon"] - mission["origin_wgs84"]["lon"])
                * 111320.0
                * __import__("math").cos(__import__("math").radians(mission["origin_wgs84"]["lat"]))
            )
            north = (photo["lat"] - mission["origin_wgs84"]["lat"]) * 111320.0
            self.assertAlmostEqual(photo["c2w"][3], east * 100.0, delta=5.0)
            self.assertAlmostEqual(photo["c2w"][7], -north * 100.0, delta=5.0)
            self.assertAlmostEqual(
                photo["c2w"][11], (photo["alt_abs_m"] - mission["origin_wgs84"]["alt"]) * 100.0, delta=5.0
            )

        self.assertEqual(self.fx.telemetry()["state"], "hovering")
        self.assertIsNone(self.fx.telemetry()["mission_id"])

        # 4) return_to_home -> land
        response = self.fx.ok_command("return_to_home", {})
        self.assertEqual(response["state"], "returning")
        idle = self.fx.wait_state("idle", timeout=40.0)
        self.assertAlmostEqual(idle["lat"], 39.9042, places=5)
        self.assertAlmostEqual(idle["lon"], 116.4074, places=5)
        self.assertAlmostEqual(idle["alt_rel_m"], 0.0, delta=0.05)
        # 已在地面：land 应 E_STATE
        body = self.fx.command("land", {})
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "E_STATE")

    # -------------------------------------------------------------- abort
    def test_abort_during_mission(self):
        self.fx.takeoff_and_hover(40)
        mission = self.fx.sample_mission()
        body = self.fx.ok_command("goto_waypoints", {"mission": mission}, confirm=True)
        self.assertEqual(body["state"], "mission")
        mission_id = body["mission_id"]
        abort = self.fx.ok_command("abort", {"reason": "测试中止"})
        self.assertTrue(abort["ok"])
        self.assertEqual(abort["mission_state"], "aborted")
        self.assertEqual(abort["state"], "hovering")
        record = self.fx.get("/v1/missions/%s" % mission_id)
        self.assertEqual(record["state"], "aborted")
        self.assertEqual(record["error"]["code"], "ABORTED")
        self.assertIn("测试中止", record["error"]["message"])
        self.assertLess(record["progress_pct"], 100.0)
        # 降落后回到 idle
        self.fx.ok_command("land", {})
        self.fx.wait_state("idle", timeout=20.0)

    # -------------------------------------------------------------- 地面动作
    def test_ground_actions_return_not_airborne(self):
        for tool, args in (
            ("set_gimbal", {"pitch_deg": -45}),
            ("capture_photo", {"count": 1}),
            ("start_video", {}),
            ("stop_video", {}),
        ):
            body = self.fx.command(tool, args)
            self.assertFalse(body["ok"], tool)
            self.assertEqual(body["error"]["code"], "E_NOT_AIRBORNE", tool)
            self.assertEqual(body["state"], "idle")

    def test_airborne_low_risk_actions(self):
        self.fx.takeoff_and_hover(40)
        gimbal = self.fx.ok_command("set_gimbal", {"pitch_deg": -90, "yaw_deg": 30})
        self.assertAlmostEqual(gimbal["gimbal"]["pitch"], -90.0)
        self.assertAlmostEqual(gimbal["gimbal"]["yaw"], 30.0)
        photos = self.fx.ok_command("capture_photo", {"count": 3, "interval_s": 0})
        self.assertEqual(len(photos["photos"]), 3)
        for photo in photos["photos"]:
            self.assertIn("c2w", photo)
            _assert_c2w_orthonormal(self, photo["c2w"])
        video = self.fx.ok_command("start_video", {})
        self.assertTrue(video["recording"])
        video = self.fx.ok_command("stop_video", {})
        self.assertFalse(video["recording"])

    # -------------------------------------------------------------- 状态机
    def test_state_machine_rejections(self):
        # goto 未起飞 -> E_STATE
        body = self.fx.command("goto_waypoints", {"mission": self.fx.sample_mission()}, confirm=True)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "E_STATE")
        # land 在地面 -> E_STATE
        body = self.fx.command("land", {})
        self.assertEqual(body["error"]["code"], "E_STATE")
        # return_to_home 在地面 -> E_STATE
        body = self.fx.command("return_to_home", {})
        self.assertEqual(body["error"]["code"], "E_STATE")
        # 起飞后再次 takeoff -> E_STATE
        self.fx.takeoff_and_hover(40)
        body = self.fx.command("takeoff", {"altitude_m": 40}, confirm=True)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "E_STATE")

    # -------------------------------------------------------------- mission 查询
    def test_mission_status_and_list(self):
        self.fx.takeoff_and_hover(40)
        body = self.fx.ok_command("goto_waypoints", {"mission": self.fx.sample_mission()}, confirm=True)
        mission_id = body["mission_id"]
        status = self.fx.ok_command("get_mission_status", {"mission_id": mission_id})
        self.assertEqual(status["mission"]["mission_id"], mission_id)
        self.assertIn(status["mission"]["state"], ("executing", "completed"))
        record = self.fx.wait_mission(mission_id)
        self.assertEqual(record["state"], "completed")
        listing = self.fx.get("/v1/missions?limit=5")
        self.assertTrue(listing["ok"])
        self.assertTrue(any(item["mission_id"] == mission_id for item in listing["missions"]))
        missing = self.fx.command("get_mission_status", {"mission_id": "m-9999"})
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"]["code"], "E_MISSION_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
