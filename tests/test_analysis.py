"""Tests for metrics.analysis. Run with venv/bin/python -m unittest tests.test_analysis -v"""
import json
import unittest
from datetime import date

from metrics import analysis as an


def R(day, name="Ride", sport="Ride", tss=60, secs=3600, meters=30000, ap=200, np_=210, hr=140,
      if_=0.7, climb=300, **kw):
    return {"date": day, "name": name, "sport_type": sport, "tss": tss, "duration_seconds": secs,
            "distance_meters": meters, "avg_power_watts": ap, "normalized_power": np_,
            "avg_hr": hr, "if_value": if_, "elevation_gain_meters": climb, **kw}


F = lambda **kw: an.Filters(start=date(2026, 9, 1), end=date(2026, 9, 30), **kw)


class FilterTests(unittest.TestCase):
    rows = [R("2026-09-02", "Tuesday ZRL race"), R("2026-09-05", "Long gravel ride", sport="gravel_cycling"),
            R("2026-09-08", "Zwift recovery", sport="virtual_ride", tss=20, if_=0.5),
            R("2026-08-30", "Before range"), R("2026-09-10", "Run", sport="running"),
            R("2026-09-12", "No power", ap=None, np_=None, hr=None, tss=None, if_=None)]

    def names(self, f):
        return [r["name"] for r in an.filter_rides(self.rows, f)]

    def test_date_range_and_rides_only(self):
        self.assertEqual(self.names(F()), ["Tuesday ZRL race", "Long gravel ride", "Zwift recovery", "No power"])

    def test_every_word_must_match_in_any_order(self):
        self.assertEqual(self.names(F(text="race zrl")), ["Tuesday ZRL race"])
        self.assertEqual(self.names(F(text="RIDE")), ["Long gravel ride"])
        self.assertEqual(self.names(F(text="race gravel")), [])

    def test_kinds_and_ranges(self):
        self.assertEqual(self.names(F(kinds=("Indoor",))), ["Zwift recovery"])
        self.assertEqual(self.names(F(tss=(50, 100))), ["Tuesday ZRL race", "Long gravel ride"])
        self.assertEqual(self.names(F(intensity=(0.0, 0.6))), ["Zwift recovery"])
        self.assertEqual(self.names(F(minutes=(59, 61), km=(29, 31), has_power=True, has_hr=True)),
                         ["Tuesday ZRL race", "Long gravel ride", "Zwift recovery"])

    def test_narrowed_and_previous_period(self):
        self.assertFalse(F().narrowed())
        self.assertTrue(F(text=" x ").narrowed())
        prev = F(text="a").previous()
        self.assertEqual((prev.start, prev.end, prev.text), (date(2026, 8, 2), date(2026, 8, 31), "a"))


class SummaryTests(unittest.TestCase):
    def test_totals_and_averages_skip_missing(self):
        s = an.summary([R("2026-09-02", if_=0.8), R("2026-09-03", ap=None, np_=None, if_=None, hr=None)])
        self.assertEqual(s["rides"], 2)
        self.assertAlmostEqual(s["hours"], 2.0)
        self.assertAlmostEqual(s["km"], 60.0)
        self.assertAlmostEqual(s["kj"], 720.0)          # 200 W for an hour, other ride has no power
        self.assertAlmostEqual(s["avg_if"], 0.8)
        self.assertAlmostEqual(s["avg_ef"], 1.5)

    def test_empty(self):
        s = an.summary([])
        self.assertEqual((s["rides"], s["tss"], s["avg_if"], s["avg_ef"]), (0, 0, None, None))

    def test_deltas(self):
        d = an.deltas({"tss": 300.0, "avg_if": None}, {"tss": 250.0, "avg_if": 0.7})
        self.assertEqual(d, {"tss": 50.0, "avg_if": None})


class OverTimeTests(unittest.TestCase):
    def test_weekly_across_a_year_boundary_includes_empty_weeks(self):
        rows = [R("2026-12-29", tss=100), R("2027-01-02", tss=50), R("2027-01-13", tss=70)]
        out = an.weekly(rows, "TSS", date(2026, 12, 28), date(2027, 1, 17))
        self.assertEqual(out, [("2026-12-28", 150.0), ("2027-01-04", 0.0), ("2027-01-11", 70.0)])
        hours = an.weekly(rows, "Hours", date(2026, 12, 28), date(2027, 1, 3))
        self.assertEqual(hours, [("2026-12-28", 2.0)])

    def test_planned_vs_done(self):
        out = an.planned_vs_done([{"date": "2026-09-01", "tss_planned": 90}],
                                 [R("2026-09-02", tss=80)], date(2026, 9, 1), date(2026, 9, 6))
        self.assertEqual(out, [{"week": "2026-08-31", "planned": 90.0, "done": 80.0}])

    def test_efficiency_skips_rides_without_hr_and_rolls(self):
        rows = [R("2026-09-03", np_=210, hr=140), R("2026-09-01", np_=200, hr=100), R("2026-09-02", hr=None)]
        pts = an.efficiency(rows, window=2)
        self.assertEqual([p["date"] for p in pts], ["2026-09-01", "2026-09-03"])
        self.assertAlmostEqual(pts[0]["rolling"], 2.0)
        self.assertAlmostEqual(pts[1]["rolling"], (2.0 + 1.5) / 2)

    def test_zone_hours(self):
        z = json.dumps({"z1_s": 1800, "z2_s": 3600, "z3_s": 0, "z4_s": 0, "z5_s": 360})
        out = an.zone_hours([R("2026-09-01", zone_time_json=z), R("2026-09-02", zone_time_json="bad"),
                             R("2026-09-03")])
        self.assertEqual([round(x, 2) for x in out], [0.5, 1.0, 0.0, 0.0, 0.1])


class PeakTests(unittest.TestCase):
    rows = [{"activity_id": 1, "date": "2026-09-01", "name": "A", "duration_s": 300, "watts": 380},
            {"activity_id": 2, "date": "2026-09-05", "name": "B", "duration_s": 300, "watts": 400},
            {"activity_id": 1, "date": "2026-09-01", "name": "A", "duration_s": 5, "watts": 1100}]

    def test_best_per_duration_with_its_ride(self):
        c = an.peak_curve(self.rows)
        self.assertEqual(list(c), [5, 300])
        self.assertEqual(c[300], {"watts": 400.0, "date": "2026-09-05", "name": "B"})

    def test_limited_to_filtered_rides(self):
        c = an.peak_curve(self.rows, activity_ids={1})
        self.assertEqual(c[300]["watts"], 380.0)

    def test_labels(self):
        self.assertEqual([an.duration_label(s) for s in (5, 60, 1200, 3600)], ["5 s", "1 min", "20 min", "1 h"])
        self.assertEqual(an.ride_kind({"sport_type": "road_biking"}), "Road")


if __name__ == "__main__":
    unittest.main()
