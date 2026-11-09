"""geo 坐标工具测试：与 capture 工程（synth_common.py）逐位对齐。"""

from __future__ import annotations

import math
import unittest

from tests.helpers import ORIGIN  # noqa: F401  （确保 sys.path 初始化）

from safety import geo


class GeoBaseTest(unittest.TestCase):
    def test_origin_roundtrip(self):
        wgs = geo.local_to_wgs84(0.0, 0.0, 0.0)
        self.assertAlmostEqual(wgs["lat"], 39.9042, places=9)
        self.assertAlmostEqual(wgs["lon"], 116.4074, places=9)
        self.assertAlmostEqual(wgs["alt"], 43.0, places=4)
        loc = geo.wgs84_to_local(39.9042, 116.4074, 43.0)
        self.assertAlmostEqual(loc["east_m"], 0.0, places=6)
        self.assertAlmostEqual(loc["north_m"], 0.0, places=6)
        self.assertAlmostEqual(loc["up_m"], 0.0, places=6)

    def test_capture_metadata_gps_parity(self):
        # data/synthetic/capture/metadata.json 第一帧：UE(-4500,-4500,4000)cm -> GPS
        p = geo.local_to_wgs84(-45.0, 45.0, 40.0)
        self.assertAlmostEqual(p["lat"], 39.90460424, places=7)
        self.assertAlmostEqual(p["lon"], 116.406873041, places=7)
        self.assertAlmostEqual(p["alt"], 83.0, places=4)

    def test_ue_cm_mapping(self):
        self.assertEqual(geo.local_to_ue_cm(10.0, 20.0, 30.0), [1000.0, -2000.0, 3000.0])
        loc = geo.ue_cm_to_local(1000.0, -2000.0, 3000.0)
        self.assertAlmostEqual(loc["east_m"], 10.0)
        self.assertAlmostEqual(loc["north_m"], 20.0)
        self.assertAlmostEqual(loc["up_m"], 30.0)

    def test_haversine_and_bearing(self):
        p = geo.offset_latlon(39.9042, 116.4074, 0.0, 100.0)
        self.assertAlmostEqual(geo.haversine_m(39.9042, 116.4074, p["lat"], p["lon"]), 100.0, places=3)
        self.assertAlmostEqual(geo.bearing_deg(39.9042, 116.4074, p["lat"], p["lon"]), 0.0, places=3)
        east = geo.offset_latlon(39.9042, 116.4074, 90.0, 100.0)
        self.assertAlmostEqual(geo.bearing_deg(39.9042, 116.4074, east["lat"], east["lon"]), 90.0, places=2)

    def test_point_in_polygon(self):
        poly = [
            {"lat": 39.9042, "lon": 116.4074},
            {"lat": 39.9042, "lon": 116.4084},
            {"lat": 39.9052, "lon": 116.4084},
            {"lat": 39.9052, "lon": 116.4074},
        ]
        self.assertTrue(geo.point_in_polygon(39.9047, 116.4079, poly))
        self.assertFalse(geo.point_in_polygon(39.9040, 116.4079, poly))
        self.assertFalse(geo.point_in_polygon(39.9047, 116.4090, poly))
        # 顶点上（边界视为在内）
        self.assertTrue(geo.point_in_polygon(39.9042, 116.4074, poly))

    def test_circle_contains(self):
        self.assertTrue(geo.circle_contains(39.9042, 116.4074, 39.9042, 116.4074, 1.0))
        self.assertFalse(geo.circle_contains(39.9058, 116.4074, 39.9042, 116.4074, 100.0))

    def test_compass_to_ue_rotator_yaw(self):
        self.assertAlmostEqual(geo.compass_to_ue_rotator_yaw(90.0), 0.0)   # 罗盘东 -> UE yaw 0 (+X)
        self.assertAlmostEqual(geo.compass_to_ue_rotator_yaw(0.0), -90.0)  # 罗盘北 -> UE yaw -90
        self.assertAlmostEqual(geo.compass_to_ue_rotator_yaw(180.0), 90.0)

    def test_c2w_matches_capture_metadata(self):
        # capture 第一帧：gimbal yaw=0(UE rotator) pitch=-45 -> forward=(0.7071,0,-0.7071)
        # 该帧罗盘角 = 90（东）时，c2w 应与 capture 工程一致
        c2w = geo.camera_c2w_ue_cm([-4500.0, -4500.0, 4000.0], 90.0, -45.0, 0.0)
        expected = [
            0.7071067811865476, -0.0, 0.7071067811865476, -4500.0,
            0.0, 1.0, 0.0, -4500.0,
            -0.7071067811865476, 0.0, 0.7071067811865476, 4000.0,
            0.0, 0.0, 0.0, 1.0,
        ]
        for a, b in zip(c2w, expected):
            self.assertAlmostEqual(a, b, places=9)

    def test_rotator_axes_orthonormal(self):
        fwd, right, up = geo.rotator_axes_ue(37.0, -52.0)
        def dot(a, b):
            return sum(x * y for x, y in zip(a, b))
        self.assertAlmostEqual(dot(fwd, fwd), 1.0, places=9)
        self.assertAlmostEqual(dot(right, right), 1.0, places=9)
        self.assertAlmostEqual(dot(up, up), 1.0, places=9)
        self.assertAlmostEqual(dot(fwd, right), 0.0, places=9)
        self.assertAlmostEqual(dot(fwd, up), 0.0, places=9)

    def test_normalize_deg(self):
        self.assertAlmostEqual(geo.normalize_deg(370.0), 10.0)
        self.assertAlmostEqual(geo.normalize_deg(-190.0), 170.0)
        self.assertAlmostEqual(geo.normalize_deg(180.0), -180.0)


if __name__ == "__main__":
    unittest.main()
