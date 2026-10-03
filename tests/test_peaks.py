"""Peak power storage and the Garmin field reader, on a throwaway database.
Run with venv/bin/python -m unittest tests.test_peaks -v"""
import os
import tempfile
import unittest
from unittest import mock

from db import schema, queries as q


def ride(source, ext, **kw):
    return {"source": source, "external_id": ext, "date": "2026-09-02", "name": "Ride",
            "sport_type": "road_biking", "duration_seconds": 3600, "elapsed_seconds": 3700,
            "distance_meters": 30000, "elevation_gain_meters": 300, "avg_power_watts": 200,
            "avg_hr": 140, "max_hr": 170, "normalized_power": 210, "tss": 60, "if_value": 0.7,
            "raw_json": None, **kw}


class PeakStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()

    def test_upsert_returns_id_for_insert_update_and_cross_source_merge(self):
        first = q.upsert_activity(ride("strava", "strava_1"))
        self.assertIsInstance(first, int)
        self.assertEqual(q.upsert_activity(ride("strava", "strava_1", tss=70)), first)
        merged = q.upsert_activity(ride("garmin", "garmin_9", elapsed_seconds=3650))
        self.assertEqual(merged, first)            # same ride from Garmin lands on the Strava row
        self.assertEqual(len(q.get_activities_between("2026-09-01", "2026-09-30")), 1)
        self.assertEqual(q.match_activity_id(ride("garmin", "garmin_9")), first)
        self.assertIsNone(q.match_activity_id(ride("garmin", "garmin_x", date="2026-09-03")))

    def test_save_keeps_the_best_and_joins_ride_info(self):
        aid = q.upsert_activity(ride("garmin", "garmin_1", name="Hill repeats"))
        q.save_peaks(aid, {300: 380, 5: 1000})
        q.save_peaks(aid, {300: 370, 60: 500})
        rows = {r["duration_s"]: r for r in q.get_peaks_between("2026-09-01", "2026-09-30")}
        self.assertEqual({d: r["watts"] for d, r in rows.items()}, {5: 1000, 60: 500, 300: 380})
        self.assertEqual(rows[300]["name"], "Hill repeats")
        self.assertEqual(q.get_peaks_between("2026-10-01", "2026-10-31"), [])
        q.save_peaks(None, {5: 1})                 # no ride, nothing stored, no error


class GarminPeakTests(unittest.TestCase):
    def test_reads_best_power_fields(self):
        from auth.garmin import peak_powers
        act = {"maxAvgPower_1": 1210, "maxAvgPower_300": 371.5, "maxAvgPower_x": 5,
               "maxAvgPower_60": None, "maxAvgPower_20": 0, "avgPower": 200}
        self.assertEqual(peak_powers(act), {1: 1210.0, 300: 371.5})

    def test_no_power_or_excluded(self):
        from auth.garmin import peak_powers
        self.assertEqual(peak_powers({"avgHR": 140}), {})
        self.assertEqual(peak_powers({"maxAvgPower_5": 900, "excludeFromPowerCurveReports": True}), {})


if __name__ == "__main__":
    unittest.main()
