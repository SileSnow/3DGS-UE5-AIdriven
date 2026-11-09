"""占位测试：验证 discover 下包名 shim 生效。"""

import unittest

import safety
from safety import geo
from sim.config import SimConfig
from sim.simulator import DroneSimulator


class ShimImportTest(unittest.TestCase):
    def test_real_packages_importable(self):
        self.assertTrue(hasattr(geo, "haversine_m"))
        self.assertEqual(SimConfig().time_scale, 20.0)
        self.assertIsNotNone(DroneSimulator)
        self.assertTrue(hasattr(safety, "SafetyValidator"))


if __name__ == "__main__":
    unittest.main()
