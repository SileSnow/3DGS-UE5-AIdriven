"""c2w（PROTOCOL.md §7.2）与 §7.3 metadata 导出测试。"""

from __future__ import annotations

import math
import unittest

from safety import geo
from safety.config import load_config
from sim.export import mission_record_to_metadata

CONFIG = load_config()
ORIGIN = CONFIG.origin


class C2WTest(unittest.TestCase):
    def test_spec_formula_heading_north_pitch_down45(self):
        # heading=0（北）-> UE yaw=-90；pitch=-45
        c2w = geo.camera_c2w_from_pose(
            39.9042, 116.4074, 43.0, 0.0, -45.0, origin=ORIGIN
        )
        root2 = math.sqrt(2.0) / 2.0
        # forward=(0,-cos45,-sin45)；right=(1,0,0)；up=(0,-sin45,cos45)
        expected_rotation = [
            [0.0, 1.0, 0.0],
            [-root2, 0.0, -root2],
            [-root2, 0.0, root2],
        ]
        for row in range(3):
            for col in range(3):
                self.assertAlmostEqual(c2w[row * 4 + col], expected_rotation[row][col], places=9)
        self.assertAlmostEqual(c2w[3], 0.0, places=6)
        self.assertAlmostEqual(c2w[7], 0.0, places=6)
        self.assertAlmostEqual(c2w[11], 0.0, places=6)
        self.assertEqual(c2w[12:], [0.0, 0.0, 0.0, 1.0])
        self.assertTrue(geo.is_orthonormal_rotation(c2w))

    def test_heading_east_pitch_level(self):
        # heading=90（东）-> UE yaw=0；pitch=0
        c2w = geo.camera_c2w_from_pose(39.9042, 116.4074, 43.0, 90.0, 0.0, origin=ORIGIN)
        self.assertAlmostEqual(c2w[0], 1.0, places=9)   # forward.x
        self.assertAlmostEqual(c2w[1], 0.0, places=9)   # right.x
        self.assertAlmostEqual(c2w[2], 0.0, places=9)   # up.x
        self.assertAlmostEqual(c2w[5], 1.0, places=9)   # right.y
        self.assertAlmostEqual(c2w[10], 1.0, places=9)  # up.z
        self.assertTrue(geo.is_orthonormal_rotation(c2w))

    def test_translation_is_ue_cm(self):
        east, north, up = 28.0, -28.0, 40.0
        point = geo.local_to_wgs84(east, north, up, origin=ORIGIN)
        c2w = geo.camera_c2w_from_pose(
            point["lat"], point["lon"], point["alt"], 180.0, -30.0, origin=ORIGIN
        )
        self.assertAlmostEqual(c2w[3], east * 100.0, delta=1e-3)
        self.assertAlmostEqual(c2w[7], -north * 100.0, delta=1e-3)
        self.assertAlmostEqual(c2w[11], up * 100.0, delta=1e-3)

    def test_orthonormal_checker(self):
        self.assertTrue(geo.is_orthonormal_rotation(geo.camera_c2w_from_pose(
            39.9042, 116.4074, 43.0, 37.0, -52.0, origin=ORIGIN)))
        bad = [2.0, 0.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 1.0]
        self.assertFalse(geo.is_orthonormal_rotation(bad))


class MetadataExportTest(unittest.TestCase):
    def _record(self):
        c2w = geo.camera_c2w_from_pose(39.903948473, 116.407072114, 83.0, 0.0, -45.0, origin=ORIGIN)
        return {
            "ok": True,
            "mission_id": "sample-grid-16",
            "plan_id": "plan-sample-001",
            "state": "completed",
            "progress_pct": 100.0,
            "photos": [
                {
                    "index": 0,
                    "file": "SIM_0001.jpg",
                    "ts": "2026-11-08T17:30:00+08:00",
                    "lat": 39.903948473,
                    "lon": 116.407072114,
                    "alt_rel_m": 40.0,
                    "alt_abs_m": 83.0,
                    "heading_deg": 0.0,
                    "gimbal": {"pitch": -45.0, "yaw": 0.0, "roll": 0.0},
                    "c2w": c2w,
                }
            ],
            "error": None,
            "stats": {"distance_m": 300.0, "duration_s": 80.0, "n_photos": 1},
        }

    def test_metadata_structure(self):
        mission_def = {
            "camera": {
                "model": "DJI Mini 4 Pro (simulated)",
                "width": 1600,
                "height": 1200,
                "fx": 1148.343,
                "fy": 1148.343,
                "cx": 800.0,
                "cy": 600.0,
            },
            "origin_wgs84": {"lat": 39.9042, "lon": 116.4074, "alt": 43.0},
        }
        metadata = mission_record_to_metadata(self._record(), mission_def)
        self.assertEqual(metadata["dataset"], "synthetic_dji_mini4pro_mission_v1")
        self.assertEqual(metadata["camera_model"], "DJI Mini 4 Pro (simulated)")
        self.assertEqual(metadata["width"], 1600)
        self.assertEqual(metadata["height"], 1200)
        self.assertAlmostEqual(metadata["fx"], 1148.343)
        self.assertEqual(metadata["coord_system"], "UE_LHS_Zup_cm")
        self.assertAlmostEqual(metadata["origin_wgs84"]["lat"], 39.9042)
        self.assertEqual(len(metadata["frames"]), 1)
        frame = metadata["frames"][0]
        self.assertEqual(frame["file"], "SIM_0001.jpg")
        self.assertEqual(len(frame["c2w"]), 16)
        self.assertAlmostEqual(frame["gps"]["alt"], 83.0)
        self.assertAlmostEqual(frame["gimbal_deg"]["pitch"], -45.0)
        self.assertEqual(frame["mission"]["mission_id"], "sample-grid-16")
        self.assertEqual(frame["mission"]["waypoint_index"], 0)

    def test_metadata_without_mission_def_uses_defaults(self):
        metadata = mission_record_to_metadata(self._record())
        self.assertEqual(metadata["width"], 1600)
        self.assertAlmostEqual(metadata["origin_wgs84"]["lat"], 39.9042)


if __name__ == "__main__":
    unittest.main()
