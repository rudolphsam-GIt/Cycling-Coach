"""Planned against ridden (components.workout_compare) and the calendar pairing read from a real
database file. Run with venv/bin/python -m unittest tests.test_workout_compare -v"""
import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

from components import calendar as cal
from components import workout_compare as wc
from db import schema, queries as q

STEPS = [
    {"kind": "warmup", "minutes": 10, "low_pct": 50, "high_pct": 60},
    {"kind": "repeat", "repeat_count": 3, "minutes": None, "low_pct": None, "high_pct": None,
     "repeat_steps": [{"kind": "interval", "minutes": 10, "low_pct": 90, "high_pct": 100},
                      {"kind": "recovery", "minutes": 5, "low_pct": 50, "high_pct": 60}]},
    {"kind": "cooldown", "minutes": 10, "low_pct": None, "high_pct": None},
]
WORKOUT = {"id": 1, "date": "2026-10-05", "name": "Threshold 3x10", "tss_planned": 80}
RIDE = {"id": 9, "date": "2026-10-05", "name": "Morning ride", "duration_seconds": 4200, "tss": 76.0,
        "if_value": 0.84, "normalized_power": 210, "avg_power_watts": 190}


class PlannedNumbersTests(unittest.TestCase):
    def test_from_steps(self):
        p = wc.planned_numbers(WORKOUT, STEPS, 250)
        self.assertEqual(p["secs"], 65 * 60)
        self.assertEqual(p["tss"], 80)
        expected_if = ((25 * 0.55 ** 4 + 30 * 0.95 ** 4) / 55) ** 0.25
        self.assertAlmostEqual(p["if"], expected_if, places=6)
        self.assertAlmostEqual(p["np"], expected_if * 250, places=6)
        self.assertAlmostEqual(p["avg_w"], (25 * 0.55 + 30 * 0.95) / 55 * 250, places=6)
        mins = [s / 60 for s in p["zones"]]
        self.assertEqual(mins[1], 25)          # Z2, warm up and recoveries at 55%
        self.assertEqual(mins[3], 30)          # Z4, the intervals at 95%
        self.assertEqual(sum(mins), 55)        # the cool down has no target, so no zone

    def test_without_steps_only_tss(self):
        p = wc.planned_numbers(WORKOUT, None, 250)
        self.assertEqual(p, {"secs": None, "tss": 80, "if": None, "np": None, "avg_w": None, "zones": None})

    def test_steps_but_no_ftp_keep_intensity(self):
        p = wc.planned_numbers(WORKOUT, STEPS, 0)
        self.assertIsNotNone(p["if"])
        self.assertIsNone(p["np"])

    def test_zone_edges_follow_metrics_zones(self):
        self.assertEqual(wc._zone_index(54.9), 0)
        self.assertEqual(wc._zone_index(55), 1)
        self.assertEqual(wc._zone_index(105), 4)
        self.assertEqual(wc._zone_index(200), 6)


class RiddenNumbersTests(unittest.TestCase):
    def test_from_ride(self):
        r = wc.ridden_numbers(RIDE)
        self.assertEqual((r["secs"], r["tss"], r["if"], r["np"], r["avg_w"]), (4200, 76.0, 0.84, 210, 190))
        self.assertIsNone(r["zones"])

    def test_if_from_np_when_missing(self):
        r = wc.ridden_numbers({**RIDE, "if_value": None}, ftp=250)
        self.assertAlmostEqual(r["if"], 0.84)

    def test_zones_from_power(self):
        power = [100] * 600 + [240] * 300        # 10 min in Z1, 5 min in Z4 at 250 W FTP
        r = wc.ridden_numbers(RIDE, {"power": power}, 250)
        self.assertEqual(r["zones"][0], 600)
        self.assertEqual(r["zones"][3], 300)

    def test_no_ride(self):
        self.assertTrue(all(v is None for v in wc.ridden_numbers(None).values()))


class ComparisonTests(unittest.TestCase):
    def test_rows(self):
        rows = wc.comparison_rows(wc.planned_numbers(WORKOUT, STEPS, 250), wc.ridden_numbers(RIDE))
        by = {r["What"]: r for r in rows}
        self.assertEqual(by["Time (h:mm)"], {"What": "Time (h:mm)", "Planned": "1:05", "Ridden": "1:10",
                                             "Difference": "+0:05 (108%)"})
        self.assertEqual(by["TSS"]["Difference"], "-4 (95%)")
        self.assertEqual(by["Normalized power"]["Ridden"], "210 W")

    def test_rows_skip_numbers_nobody_has(self):
        rows = wc.comparison_rows(wc.planned_numbers(WORKOUT, None, 250),
                                  wc.ridden_numbers({**RIDE, "normalized_power": None, "avg_power_watts": None,
                                                     "if_value": None}))
        self.assertEqual([r["What"] for r in rows], ["Time (h:mm)", "TSS"])
        self.assertEqual(rows[0]["Planned"], "")
        self.assertEqual(rows[0]["Difference"], "")

    def test_zone_rows(self):
        planned = wc.planned_numbers(WORKOUT, STEPS, 250)
        ridden = wc.ridden_numbers(RIDE, {"power": [240] * 1800}, 250)
        rows = wc.zone_rows(planned, ridden)
        self.assertEqual([r["zone"] for r in rows], ["Z2", "Z4"])
        self.assertEqual(rows[1]["planned_min"], 30)
        self.assertEqual(rows[1]["ridden_min"], 30)
        self.assertEqual(rows[0]["ridden_min"], 0)

    def test_zone_rows_one_side_missing(self):
        rows = wc.zone_rows(wc.planned_numbers(WORKOUT, STEPS, 250), wc.ridden_numbers(RIDE))
        self.assertTrue(rows)
        self.assertTrue(all(r["ridden_min"] is None for r in rows))
        self.assertEqual(wc.zone_rows(wc.planned_numbers(WORKOUT, None, 250), wc.ridden_numbers(RIDE)), [])

    def test_verdicts(self):
        self.assertEqual(wc.tss_verdict(100, 95), "on")
        self.assertEqual(wc.tss_verdict(100, 80), "under")
        self.assertEqual(wc.tss_verdict(100, 69), "short")
        self.assertEqual(wc.tss_verdict(100, 70), "under")       # the calendar's 70% line
        self.assertEqual(wc.tss_verdict(100, 120), "over")
        self.assertIsNone(wc.tss_verdict(None, 50))
        self.assertIsNone(wc.tss_verdict(100, None))

    def test_summary(self):
        line = wc.summary_line(wc.planned_numbers(WORKOUT, STEPS, 250), wc.ridden_numbers(RIDE), True)
        self.assertEqual(line, "You rode 76 TSS against 80 planned (95%) and 1:10 riding against 1:05 "
                               "planned. Right on plan.")
        self.assertIn("No ride was recorded", wc.summary_line({}, {}, False))
        self.assertIn("no numbers to compare", wc.summary_line({"tss": None}, {"tss": 50}, True))

    def test_plain_language(self):
        texts = list(wc.VERDICT_TEXT.values()) + [
            wc.summary_line(wc.planned_numbers(WORKOUT, STEPS, 250), wc.ridden_numbers(RIDE), True),
            wc.summary_line({}, {}, False)]
        for t in texts:
            self.assertNotIn("—", t)
            self.assertNotRegex(t, r":\D")       # times like 1:05 are fine, prose colons are not


class DatabaseTests(unittest.TestCase):
    """The pairing read back through load_month from a temporary database."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()
        q.set_setting("ftp_watts", "250")

    def ride(self, day, ext, tss, name="Ride"):
        return q.upsert_activity({
            "source": "garmin", "external_id": ext, "date": day, "name": name, "sport_type": "Ride",
            "duration_seconds": 3600, "elapsed_seconds": 3700, "distance_meters": 30000,
            "elevation_gain_meters": 100, "avg_power_watts": 180, "avg_hr": 140, "max_hr": 170,
            "normalized_power": 190, "tss": tss, "if_value": 0.76, "raw_json": "{}", "zone_time_json": None})

    def workout(self, day, name, tss, completed=0):
        wid = q.add_workout({"date": day, "name": name, "workout_type": "Endurance", "description": "Steady",
                             "structured_json": json.dumps(STEPS), "tss_planned": tss, "notes": ""})
        if completed:
            q.update_workout(wid, {**q.get_workout(wid), "completed": 1})
        return wid

    def test_month_pairs_from_the_database(self):
        today = date.today()
        past, gone, soon, free = (today - timedelta(days=d) for d in (1, 2, -2, 3))
        done = self.workout(past.isoformat(), "Endurance", 70)
        missed = self.workout(gone.isoformat(), "Threshold", 90)
        future = self.workout(soon.isoformat(), "Long ride", 150)
        rid = self.ride(past.isoformat(), "r1", 66, "Done ride")
        extra = self.ride(free.isoformat(), "r2", 40, "Coffee spin")

        def day(d):
            return cal.get_day(d.isoformat())
        self.assertEqual([(p["workout"]["id"], p["ride"]["id"], p["state"]) for p in day(past).pairs],
                         [(done, rid, "done")])
        self.assertEqual([(p["workout"]["id"], p["ride"], p["state"]) for p in day(gone).pairs],
                         [(missed, None, "missed")])
        self.assertEqual([(p["workout"]["id"], p["state"]) for p in day(soon).pairs], [(future, "planned")])
        self.assertEqual([r["id"] for r in day(free).unplanned], [extra])

        # The saved steps and the paired ride give the full comparison.
        from garmin_workouts import saved_steps
        w = q.get_workout(done)
        rows = wc.comparison_rows(wc.planned_numbers(w, saved_steps(w), q.ftp_on(w["date"])),
                                  wc.ridden_numbers(day(past).pairs[0]["ride"]))
        self.assertEqual({r["What"] for r in rows},
                         {"Time (h:mm)", "TSS", "Intensity (IF)", "Normalized power", "Average power"})


if __name__ == "__main__":
    unittest.main()
