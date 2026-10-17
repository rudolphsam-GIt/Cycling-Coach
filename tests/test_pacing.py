"""The Races page pacing calculator: average power from the standard road cycling power equation."""
from __future__ import annotations

import unittest

from metrics import pacing


class RequiredPowerTests(unittest.TestCase):
    def test_a_known_road_race(self):
        # 80 km with 800 m of climbing in 2 h 30 min, a 70 kg rider on an 8 kg bike.
        p = pacing.required_power(80, 800, 9000, 70, 8)
        self.assertAlmostEqual(p["climb"], 78 * 9.81 * 800 / 9000, places=6)      # 68.0 W
        self.assertAlmostEqual(p["rolling"], 0.004 * 78 * 9.81 * 80000 / 9000, places=6)
        self.assertAlmostEqual(p["air"], 0.5 * 1.18 * 0.32 * (80000 / 9000) ** 3, places=6)
        self.assertAlmostEqual(p["total"], 233.4, places=1)
        self.assertAlmostEqual(p["total"], (p["climb"] + p["rolling"] + p["air"]) / 0.976, places=6)
        self.assertAlmostEqual(p["speed_kph"], 32.0, places=6)

    def test_climbing_adds_lifting_work_only(self):
        flat = pacing.required_power(80, 0, 9000, 70, 8)
        hilly = pacing.required_power(80, 1600, 9000, 70, 8)
        self.assertEqual(flat["climb"], 0)
        # Each metre climbed in the same time costs the same, so 1600 m is twice 800 m.
        self.assertAlmostEqual(hilly["climb"], 2 * pacing.required_power(80, 800, 9000, 70, 8)["climb"])
        self.assertAlmostEqual(hilly["total"] - flat["total"], hilly["climb"] / 0.976, places=6)

    def test_the_bike_counts_toward_climbing_and_rolling(self):
        light = pacing.required_power(80, 800, 9000, 70, 0)
        with_bike = pacing.required_power(80, 800, 9000, 70, 8)
        self.assertAlmostEqual(with_bike["climb"] / light["climb"], 78 / 70)
        self.assertEqual(with_bike["air"], light["air"])

    def test_no_time_or_distance_gives_nothing(self):
        self.assertIsNone(pacing.required_power(80, 800, 0, 70, 8))
        self.assertIsNone(pacing.required_power(0, 800, 9000, 70, 8))


if __name__ == "__main__":
    unittest.main()
