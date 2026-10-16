"""Ski days: planned as hrTSS targets, scored on the ski threshold, sent to TrainingPeaks as XC
ski, and kept out of the bike only exports."""
import os
import tempfile
import unittest
from datetime import date, timedelta

import sports


class SkiKindTests(unittest.TestCase):
    def test_sport_names_from_every_source(self):
        cases = {
            "cross_country_skiing": "nordic", "skate_skiing": "nordic", "NordicSki": "nordic",
            "cross_country_skiing_skate_skiing": "nordic",
            "backcountry_skiing": "backcountry", "BackcountrySki": "backcountry",
            "alpine_skiing_backcountry": "backcountry", "skimo": "backcountry",
            "resort_skiing_snowboarding_ws": "downhill", "AlpineSki": "downhill", "snowboarding": "downhill",
        }
        for name, kind in cases.items():
            with self.subTest(name=name):
                self.assertEqual(sports.ski_kind(name), kind)
        for other in ("cycling", "running", "Ride", "", None, "strength_training"):
            self.assertIsNone(sports.ski_kind(other))

    def test_threshold_for(self):
        self.assertEqual(sports.threshold_for("cross_country_skiing", 156, 165), 165)
        self.assertEqual(sports.threshold_for("cross_country_skiing", 156, 0), 156)    # not set yet
        self.assertEqual(sports.threshold_for("road_biking", 156, 165), 156)
        self.assertEqual(sports.threshold_for("running", 156, 165), 156)

    def test_ski_workouts(self):
        self.assertTrue(sports.is_ski_workout({"workout_type": "Backcountry Ski"}))
        self.assertFalse(sports.is_ski_workout({"workout_type": "Long Ride"}))
        from db.queries import WORKOUT_TYPES
        self.assertTrue(set(sports.SKI_TYPES) <= set(WORKOUT_TYPES))


SKI = {"id": 7, "date": "2026-12-19", "name": "Big ski day", "workout_type": "Backcountry Ski",
       "description": "4 to 6 h touring, climbs at HR 140 to 160. Bike option 3.5 h endurance.",
       "tss_planned": 230, "purpose": "Long aerobic day.", "feel": "Steady."}


class TrainingPeaksTests(unittest.TestCase):
    def test_ski_day_goes_as_xc_ski_without_bike_steps(self):
        from auth import trainingpeaks as tp
        p = tp.payload("42", SKI, [])
        self.assertEqual(p["workoutTypeValueId"], sports.TP_XC_SKI)
        self.assertEqual(p["tssPlanned"], 230)
        self.assertNotIn("structure", p)
        self.assertIn("Bike option", p["description"])
        self.assertTrue(tp.fingerprint(SKI, []))

    def test_ski_days_never_go_to_the_step_builder(self):
        import garmin_workouts
        out = garmin_workouts.ensure_steps([SKI])
        self.assertIsInstance(out[7], str)
        self.assertIn("ski day", out[7])


class DbTests(unittest.TestCase):
    def setUp(self):
        from db import schema
        self.schema = schema
        self.tmp = tempfile.TemporaryDirectory()
        self.old = schema.DB_PATH
        schema.DB_PATH = os.path.join(self.tmp.name, "t.db")
        schema.run_migrations()

    def tearDown(self):
        self.schema.DB_PATH = self.old
        self.tmp.cleanup()

    def test_ski_activity_is_scored_on_the_ski_threshold(self):
        from db.queries import get_activity, recalculate_all_tss, set_setting, upsert_activity
        set_setting("lthr", 150)
        day = (date.today() - timedelta(days=1)).isoformat()
        common = {"date": day, "duration_seconds": 3 * 3600, "elapsed_seconds": 3 * 3600, "avg_hr": 145,
                  "max_hr": 170, "distance_meters": 30000, "elevation_gain_meters": 900,
                  "avg_power_watts": None, "normalized_power": None, "tss": None, "if_value": None,
                  "raw_json": None}
        ski = upsert_activity({**common, "source": "fit_import", "external_id": "ski1", "name": "Tour",
                               "sport_type": "backcountry_skiing"})
        run = upsert_activity({**common, "source": "fit_import", "external_id": "run1", "name": "Run",
                               "sport_type": "running", "date": (date.today() - timedelta(days=2)).isoformat()})
        recalculate_all_tss()
        on_bike_threshold = get_activity(ski)["tss"]
        self.assertAlmostEqual(on_bike_threshold, get_activity(run)["tss"], delta=0.5)
        set_setting(sports.SKI_LTHR_SETTING, 165)
        recalculate_all_tss()
        self.assertLess(get_activity(ski)["tss"], on_bike_threshold)      # higher threshold, lower hrTSS
        self.assertAlmostEqual(get_activity(run)["tss"], on_bike_threshold, delta=0.5)

    def test_coach_plans_ski_days_without_steps(self):
        import coach_tools
        soon = (date.today() + timedelta(days=3)).isoformat()
        day = {"date": soon, "name": "Nordic 2 h", "workout_type": "Nordic Ski", "tss_planned": 110,
               "description": "2 h at ski HR 130 to 145. Bike option 2 h endurance.",
               "purpose": "Aerobic base on snow.", "feel": "Steady, can talk."}
        out = []
        coach_tools._propose({"workouts": [day]}, out)
        self.assertEqual(out[0]["workout_type"], "Nordic Ski")
        steps = [{"kind": "steady", "minutes": 60, "low_pct": 60, "high_pct": 70}]
        with self.assertRaises(coach_tools.ToolInputError):
            coach_tools._propose({"workouts": [{**day, "steps": steps}]}, [])


if __name__ == "__main__":
    unittest.main()
