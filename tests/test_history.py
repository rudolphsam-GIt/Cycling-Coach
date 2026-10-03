"""Tests for metrics.peaks and the history and power profile parts of
metrics.analysis. Run with venv/bin/python -m unittest tests.test_history -v"""
import io
import unittest
import zipfile
from datetime import date

from metrics import analysis as an
from metrics import peaks


class MeanMaxTests(unittest.TestCase):
    def test_best_window(self):
        samples = [(t, 100) for t in range(60)] + [(60 + t, 400) for t in range(5)] + \
                  [(65 + t, 100) for t in range(60)]
        out = peaks.mean_max(samples, (5, 10, 300))
        self.assertEqual(out[5], 400.0)
        self.assertEqual(out[10], 250.0)
        self.assertNotIn(300, out)            # the ride is shorter than 5 minutes

    def test_short_gaps_filled_pauses_cut_out(self):
        filled = peaks.mean_max([(0, 200), (3, 200), (4, 200)], (5,))
        self.assertEqual(filled, {5: 200.0})  # 0, then 1 to 2 filled, 3, 4
        joined = peaks.mean_max([(0, 300), (1, 300), (600, 100), (601, 100)], (3, 4, 5))
        self.assertEqual(joined, {3: 233.3, 4: 200.0})   # a 10 minute stop is cut out, not averaged in

    def test_missing_and_zero_heart_rate(self):
        hr = [(0, 150), (1, 150), (2, None), (3, 160), (4, 0), (5, 170)]
        self.assertEqual(peaks.mean_max(hr, (1, 2), zero_is_missing=True), {1: 170.0, 2: 165.0})
        # power of zero is real (coasting)
        self.assertEqual(peaks.mean_max([(0, 0), (1, 300)], (2,)), {2: 150.0})

    def test_unsorted_and_duplicate_timestamps(self):
        self.assertEqual(peaks.mean_max([(2, 300), (0, 100), (1, 200), (1, 999)], (3,)), {3: 200.0})

    def test_zip_unwrap(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("123_ACTIVITY.fit", b"FITDATA")
        self.assertEqual(peaks.fit_from_download(buf.getvalue()), b"FITDATA")
        self.assertEqual(peaks.fit_from_download(b"\x0e\x10plain"), b"\x0e\x10plain")


def R(day, aid, secs=3600, tss=60, ap=200, meters=30000):
    return {"id": aid, "date": day, "sport_type": "ride", "duration_seconds": secs, "tss": tss,
            "avg_power_watts": ap, "distance_meters": meters}


class HistoryTests(unittest.TestCase):
    TODAY = date(2026, 10, 2)   # a Friday

    def test_rows_and_totals(self):
        rides = [R("2026-09-29", 1), R("2026-09-22", 2, tss=100), R("2025-10-15", 3),
                 R("2024-01-01", 4), {"id": 5, "date": "2026-09-30", "sport_type": "running", "tss": 50}]
        power = [{"activity_id": 1, "date": "2026-09-29", "duration_s": 5, "watts": 900},
                 {"activity_id": 2, "date": "2026-09-22", "duration_s": 5, "watts": 1000},
                 {"activity_id": 2, "date": "2026-09-22", "duration_s": 7, "watts": 1}]
        hr = [{"activity_id": 1, "date": "2026-09-29", "duration_s": 60, "bpm": 180}]
        rows = an.period_history(rides, power, hr, self.TODAY)
        weeks = [r for r in rows if r["section"] == "week"]
        months = [r for r in rows if r["section"] == "month"]
        self.assertEqual([r["label"] for r in weeks], ["9/28/2026", "9/21/2026", "9/14/2026", "9/7/2026"])
        self.assertTrue(weeks[0]["current"] and not weeks[1]["current"])
        self.assertEqual(len(months), 13)
        self.assertEqual((months[0]["label"], months[-1]["label"]), ("October '26", "October '25"))
        self.assertEqual(weeks[0]["rides"], 1)                 # the run is not counted
        self.assertEqual(weeks[0]["power"], {5: 900.0})
        self.assertEqual(weeks[0]["hr"], {60: 180.0})
        self.assertEqual(months[1]["tss"], 160.0)              # September '26
        self.assertEqual(months[1]["power"], {5: 1000.0})      # 7 s is not a table column
        self.assertEqual(months[-1]["rides"], 1)               # October '25
        everything = rows[-1]
        self.assertEqual((everything["label"], everything["rides"]), ("All time", 4))
        self.assertEqual(everything["kj"], 4 * 720.0)
        self.assertEqual(everything["power"][5], 1000.0)

    def test_empty(self):
        rows = an.period_history([], [], [], self.TODAY)
        self.assertEqual(len(rows), 4 + 13 + 1)
        self.assertTrue(all(r["rides"] == 0 and not r["power"] for r in rows))


class ProfileTests(unittest.TestCase):
    def test_levels(self):
        bounds = an.PROFILE_TABLES["Men"]["ft"]
        self.assertAlmostEqual(an.profile_level(bounds[3], bounds), 3.0)          # bottom of Good
        self.assertAlmostEqual(an.profile_level((bounds[3] + bounds[4]) / 2, bounds), 3.5)
        self.assertEqual(an.profile_level(99, bounds), 8.0)
        self.assertLess(an.profile_level(1.0, bounds), 1.0)

    def test_profile_uses_ft_for_20_and_60_min(self):
        best = {5: 1000, 60: 600, 300: 400, 1200: 320, 3600: 290}
        out = {p["secs"]: p for p in an.power_profile(best, 80)}
        self.assertEqual(set(out), {5, 60, 300, 1200, 3600})
        self.assertAlmostEqual(out[3600]["wkg"], 3.625)
        self.assertEqual(out[3600]["category"], "Good (Cat 3)")          # 3.47 to 4.09
        self.assertEqual(out[1200]["category"], "Good (Cat 3)")          # 320 x 0.95 / 80 = 3.8
        self.assertEqual(out[5]["category"], "Fair (Cat 5)")             # 12.5 W/kg, 11.80 to 13.44
        women = {p["secs"]: p for p in an.power_profile(best, 80, "Women")}
        self.assertEqual(women[3600]["category"], "Very good (Cat 2)")   # 3.55 to 4.05

    def test_needs_weight_and_skips_missing(self):
        self.assertEqual(an.power_profile({5: 1000}, 0), [])
        self.assertEqual([p["secs"] for p in an.power_profile({5: {"watts": 1000}}, 75)], [5])


if __name__ == "__main__":
    unittest.main()
