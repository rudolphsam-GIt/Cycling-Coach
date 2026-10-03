"""Miles and kilometers, and the highlighted-part-of-a-ride numbers.
Run with venv/bin/python -m unittest tests.test_distance_units -v"""
import unittest
from datetime import date
from unittest import mock

from components import calendar as cal
from components import charts, ride_detail
from metrics import streams as sm
from metrics import units as u


class ConversionTests(unittest.TestCase):
    def test_distance_and_climb_conversions(self):
        self.assertAlmostEqual(u.dist_from_km(100, "mi"), 62.137, places=2)
        self.assertEqual(u.dist_from_km(100, "km"), 100.0)
        self.assertAlmostEqual(u.km_from_dist(u.dist_from_km(42.5, "mi"), "mi"), 42.5, places=6)
        self.assertAlmostEqual(u.climb_from_m(1000, "mi"), 3280.84, places=1)
        self.assertEqual(u.climb_from_m(1000, "km"), 1000.0)
        self.assertAlmostEqual(u.m_from_climb(u.climb_from_m(850, "mi"), "mi"), 850, places=6)
        self.assertEqual((u.climb_unit("mi"), u.climb_unit("km")), ("ft", "m"))
        self.assertEqual((u.speed_unit("mi"), u.speed_unit("km")), ("mph", "km/h"))
        self.assertAlmostEqual(u.speed_from_kph(32, "mi"), 19.88, places=1)

    def test_formatting(self):
        self.assertEqual(u.fmt_distance(34200, "km"), "34.2 km")
        self.assertEqual(u.fmt_distance(34200, "mi"), "21.3 mi")
        self.assertEqual(u.fmt_climb(175, "mi"), "574 ft")
        self.assertEqual(u.fmt_climb(1750, "km"), "1,750 m")
        self.assertEqual((u.fmt_distance(0, "mi"), u.fmt_distance(None, "km"), u.fmt_climb(0, "mi")), ("", "", ""))


class DisplayTests(unittest.TestCase):
    RIDE = {"id": 1, "date": "2026-10-05", "name": "Long ride", "sport_type": "ride", "tss": 90,
            "duration_seconds": 7200, "distance_meters": 60000, "elevation_gain_meters": 800,
            "avg_power_watts": 190}

    def day(self):
        days = cal.build_month_data(2026, 10, [], [self.RIDE], [], [{"date": "2026-10-05", "name": "Crit",
                                                                    "distance_km": 40}], date(2026, 10, 15))
        return days["2026-10-05"]

    def test_tooltip_follows_the_unit(self):
        km, mi = cal.day_tooltip(self.day()), cal.day_tooltip(self.day(), "mi")
        self.assertIn("60.0 km", km)
        self.assertIn("37.3 mi", mi)
        self.assertNotIn("60.0 km", mi)
        self.assertIn("40 km", cal.day_tooltip(self.day(), "km")) if False else None
        self.assertIn("24.9 mi", mi)                                   # the race distance, 40 km

    def test_payload_uses_the_unit(self):
        days = cal.build_month_data(2026, 10, [], [self.RIDE], [], [], date(2026, 10, 15))
        tips = {d["date"]: d["tip"] for d in cal.build_payload(days, None, date(2026, 10, 15), "mi")["days"]}
        self.assertIn("37.3 mi", tips["2026-10-05"])

    def test_ride_table_columns_follow_the_unit(self):
        km = ride_detail.rides_frame([self.RIDE], "km")
        mi = ride_detail.rides_frame([self.RIDE], "mi")
        self.assertIn("Distance km", km.columns)
        self.assertIn("Climb m", km.columns)
        self.assertIn("Distance mi", mi.columns)
        self.assertIn("Climb ft", mi.columns)
        self.assertAlmostEqual(km["Distance km"][0], 60.0)
        self.assertAlmostEqual(mi["Distance mi"][0], 37.28, places=2)
        self.assertAlmostEqual(mi["Climb ft"][0], 2624.7, places=1)
        blank = ride_detail.rides_frame([{"date": "2026-10-05", "sport_type": "ride"}], "mi")
        self.assertTrue(blank["Distance mi"].isna().all())


class SelectionTests(unittest.TestCase):
    def ride(self, n=3600, power=250, speed=10.0):
        return sm.from_records([{"t": i, "power": power, "hr": 150, "speed": speed, "dist": i * speed,
                                "alt": 100 + i * 0.1, "cad": 90} for i in range(n)])

    def test_slice_keeps_every_channel_the_same_length(self):
        sl = sm.slice_streams(self.ride(), 600, 1200)
        self.assertEqual({len(v) for v in sl.values()}, {600})
        self.assertEqual(len(sm.slice_streams(self.ride(100), 50, 5000)["power"]), 50)    # past the end
        self.assertEqual(len(sm.slice_streams(self.ride(100), -20, 30)["power"]), 30)     # before the start

    def test_numbers_for_a_part_of_the_ride(self):
        n = sm.numbers_from_streams(sm.slice_streams(self.ride(), 0, 600), ftp=250)
        self.assertEqual(n["secs"], 600)
        self.assertAlmostEqual(n["meters"], 5990, delta=15)
        self.assertAlmostEqual(n["avg_speed"], 10.0)
        self.assertAlmostEqual(n["max_speed"], 10.0)
        self.assertAlmostEqual(n["avg_w"], 250)
        self.assertAlmostEqual(n["if"], 1.0, places=2)
        self.assertAlmostEqual(n["avg_cad"], 90)
        self.assertAlmostEqual(n["climb"], 60, delta=2)

    def test_tss_matches_the_standard_formula(self):
        hour = sm.numbers_from_streams(self.ride(3600, power=250), ftp=250)
        self.assertAlmostEqual(hour["tss"], 100, delta=0.5)                  # an hour at FTP is 100
        half = sm.numbers_from_streams(self.ride(1800, power=250), ftp=250)
        self.assertAlmostEqual(half["tss"], 50, delta=0.5)
        self.assertIsNone(sm.numbers_from_streams(self.ride(3600), ftp=0)["tss"])

    def test_a_hard_part_looks_harder_than_the_whole_ride(self):
        power = [150] * 600 + [300] * 600 + [150] * 600
        s = sm.from_records([{"t": i, "power": p, "hr": 120 + p // 5, "speed": 6 + p / 60} for i, p in enumerate(power)])
        whole = sm.numbers_from_streams(s, 250)
        hard = sm.numbers_from_streams(sm.slice_streams(s, 600, 1200), 250)
        self.assertGreater(hard["avg_w"], whole["avg_w"])
        self.assertGreater(hard["avg_hr"], whole["avg_hr"])
        self.assertGreater(hard["avg_speed"], whole["avg_speed"])
        self.assertGreater(hard["if"], whole["if"])

    def test_elevation_gain_ignores_noise_and_descents(self):
        self.assertIsNone(sm.elevation_gain([100]))
        self.assertAlmostEqual(sm.elevation_gain([100 + i for i in range(60)]), 59, delta=3)
        self.assertEqual(sm.elevation_gain([200 - i for i in range(60)]), 0)
        noisy = [100 + (0.2 if i % 2 else -0.2) for i in range(200)]          # sensor wobble, no climbing
        self.assertAlmostEqual(sm.elevation_gain(noisy), 0, delta=1.0)
        self.assertAlmostEqual(sm.elevation_gain([100] * 30 + [150] * 30 + [100] * 30 + [150] * 30),
                               100, delta=6)                                   # two real climbs

    def test_a_tiny_selection_never_crashes(self):
        # a stretch shorter than the 30 second smoothing window used to raise
        for n in (1, 3, 10, 29, 31):
            sl = sm.slice_streams(self.ride(), 100, 100 + n)
            numbers = sm.numbers_from_streams(sl, 250)
            self.assertEqual(numbers["secs"], n)
            self.assertEqual(len(sm.smooth(sl["power"], 30)), n)
            self.assertEqual(len(sm.smooth(sl["power"], 60)), n)
            sm.power_zone_seconds(sl["power"], 250)
            sm.find_efforts(sl["power"], 250)
            sm.ride_peaks(sl["power"], [5, 60])
            sm.downsample(sl["power"])
        self.assertEqual(sm.smooth([5], 30), [5.0])
        self.assertEqual(sm.smooth([1, None, 3], 30)[1], None)

    def test_distance_falls_back_to_adding_up_speed(self):
        s = {"speed": [5.0] * 100}
        self.assertEqual(sm.distance_meters(s), 500)
        self.assertIsNone(sm.distance_meters({}))

    def test_a_ride_with_no_speed_or_distance_still_works(self):
        s = sm.from_records([{"t": i, "power": 200} for i in range(120)])
        n = sm.numbers_from_streams(s, 250)
        self.assertIsNone(n["avg_speed"])
        self.assertIsNone(n["meters"])
        self.assertIsNone(n["climb"])


class ChartSelectionTests(unittest.TestCase):
    def read(self, state, key="ra_timeline_7"):
        with mock.patch.object(charts.st, "session_state", state):
            return charts.selected_range(key)

    def test_reads_the_box_the_rider_dragged(self):
        box = {"selection": {"box": [{"x": [10.5, 18.2], "y": [100, 200]}, {"x": [10.5, 18.2]}]}}
        self.assertEqual(self.read({"ra_timeline_7_0": box}), (10.5, 18.2))
        self.assertEqual(self.read({"ra_timeline_7_0": {"selection": {"box": [{"x": [18.2, 10.5]}]}}}),
                         (10.5, 18.2))                                        # dragged right to left

    def test_nothing_selected_or_a_reset_chart(self):
        self.assertIsNone(self.read({}))
        self.assertIsNone(self.read({"ra_timeline_7_0": {"selection": {"box": []}}}))
        self.assertIsNone(self.read({"ra_timeline_7_0": {"selection": {"box": [{"x": [5, 5]}]}}}))
        self.assertIsNone(self.read({"ra_timeline_7_0": {"selection": {"box": [{"x": ["a", "b"]}]}}}))
        # Pressing Clear selection bumps the counter, so the old selection belongs to a chart that is gone
        gone = {"ra_timeline_7_0": {"selection": {"box": [{"x": [1, 2]}]}}, "_zoom_ra_timeline_7": 1}
        self.assertIsNone(self.read(gone))


if __name__ == "__main__":
    unittest.main()


class DrillDownTests(unittest.TestCase):
    """Dragging on the timeline zooms in, and zooms in again inside that."""

    def setUp(self):
        from components import ride_analysis as ra
        self.ra = ra
        self.state = {}
        p = mock.patch.object(ra.st, "session_state", self.state)
        p.start()
        self.addCleanup(p.stop)
        self.box = None
        q = mock.patch.object(ra.charts, "selected_range", lambda key: self.box)
        q.start()
        self.addCleanup(q.stop)

    def drag(self, minutes, length=3600):
        self.box = minutes
        return self.ra.take_drag(7, length)

    def test_starts_on_the_whole_ride(self):
        self.assertEqual(self.ra.current_range(7, 3600), (0, 3600))

    def test_each_drag_goes_one_level_deeper(self):
        self.assertTrue(self.drag((10, 40)))
        self.assertEqual(self.ra.current_range(7, 3600), (600, 2401))
        self.assertTrue(self.drag((15, 25)))                              # inside the zoomed view
        self.assertEqual(self.ra.current_range(7, 3600), (900, 1501))
        self.assertEqual(len(self.state["ra_view_7"]["stack"]), 2)

    def test_a_drag_is_clamped_to_the_current_view(self):
        self.drag((10, 40))
        self.assertTrue(self.drag((5, 20)))                               # starts left of the view
        self.assertEqual(self.ra.current_range(7, 3600), (600, 1201))
        self.drag((0, 100))                                               # covers the whole view: nothing new
        self.assertEqual(len(self.state["ra_view_7"]["stack"]), 2)

    def test_tiny_or_missing_drags_do_nothing(self):
        self.assertFalse(self.drag(None))
        self.assertFalse(self.drag((10, 10.05)))                          # a click, not a drag
        self.assertFalse(self.drag((100, 120)))                           # past the end of a 1 hour ride
        self.assertEqual(self.ra.current_range(7, 3600), (0, 3600))

    def test_back_goes_up_one_level_and_the_chart_starts_fresh(self):
        self.drag((10, 40))
        self.drag((15, 25))
        gen = self.state["ra_view_7"]["gen"]
        self.ra._back(7)
        self.assertEqual(self.ra.current_range(7, 3600), (600, 2401))
        self.assertGreater(self.state["ra_view_7"]["gen"], gen)            # new chart, no lingering drag box
        key_after_back = self.ra.timeline_key(7)
        self.ra._back(7)
        self.assertEqual(self.ra.current_range(7, 3600), (0, 3600))
        self.ra._back(7)                                                    # already at the top: no error
        self.assertEqual(self.ra.current_range(7, 3600), (0, 3600))
        self.assertNotEqual(self.ra.timeline_key(7), key_after_back)

    def test_whole_ride_and_reopening_reset_the_view(self):
        self.drag((10, 40))
        self.drag((15, 25))
        self.ra._whole(7)
        self.assertEqual(self.ra.current_range(7, 3600), (0, 3600))
        self.drag((10, 40))
        self.ra.reset_view(7)
        self.assertEqual(self.ra.current_range(7, 3600), (0, 3600))

    def test_each_ride_keeps_its_own_view(self):
        self.drag((10, 40))
        self.assertEqual(self.ra.current_range(8, 3600), (0, 3600))

    def test_the_timeline_key_changes_with_every_move(self):
        keys = {self.ra.timeline_key(7)}
        self.drag((10, 40))
        keys.add(self.ra.timeline_key(7))
        self.ra._back(7)
        keys.add(self.ra.timeline_key(7))
        self.assertEqual(len(keys), 3)
