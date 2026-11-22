"""Daily fuel targets from the day's training.
Run with venv/bin/python -m unittest tests.test_nutrition_day -v"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from db import queries as q
from db import schema
from metrics import nutrition_day as nd
from metrics.units import from_kg, to_kg

DAY = "2026-11-20"


def _steps(minutes: int) -> str:
    return json.dumps([{"kind": "interval", "minutes": minutes, "low_pct": 65, "high_pct": 75,
                        "repeat_count": None, "repeat_steps": None}])


class DbTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        schema.run_migrations()
        q._settings_cache.clear()
        self.addCleanup(q._settings_cache.clear)
        q.set_setting("ftp_watts", 250)

    def ride(self, secs=3600, watts=None, tss=None, if_value=None, sport="Ride", ext="a"):
        conn = schema.get_conn()
        conn.execute("INSERT INTO activities (source, external_id, date, sport_type, duration_seconds, "
                     "avg_power_watts, tss, if_value) VALUES (?,?,?,?,?,?,?,?)",
                     ("test", ext, DAY, sport, secs, watts, tss, if_value))
        conn.commit()
        conn.close()

    def plan(self, minutes=None, tss=60, completed=0):
        conn = schema.get_conn()
        conn.execute("INSERT INTO workouts (date, name, workout_type, structured_json, tss_planned, "
                     "completed) VALUES (?,?,?,?,?,?)",
                     (DAY, "Planned", "Endurance", _steps(minutes) if minutes else None, tss, completed))
        conn.commit()
        conn.close()


class CarbBandTests(unittest.TestCase):
    def test_band_edges(self):
        cases = {0: "light", 44: "light", 45: "1h", 89: "1h", 90: "1to3h", 209: "1to3h",
                 210: "4to5h", 300: "4to5h"}
        for minutes, band in cases.items():
            with self.subTest(minutes=minutes):
                self.assertEqual(nd.carb_band(minutes, 0.75)["band"], band)

    def test_a_very_easy_day_is_light_whatever_its_length(self):
        self.assertEqual(nd.carb_band(150, 0.6)["band"], "light")
        self.assertEqual(nd.carb_band(150, None)["band"], "1to3h")

    def test_ranges_and_start_come_from_nutrition_md(self):
        b = nd.carb_band(120, 0.75)
        self.assertEqual((b["low"], b["high"], b["start"]), (6, 10, 8))


class LoadTests(DbTest):
    def test_completed_ride_kj_from_average_power(self):
        self.ride(secs=7200, watts=200, tss=110, if_value=0.74)
        load = nd.day_load(DAY)
        self.assertEqual(load["source"], "completed")
        self.assertEqual(load["kj"], 1440)
        self.assertFalse(load["kj_estimated"])
        self.assertEqual(load["avg_if"], 0.74)

    def test_ride_without_power_is_estimated_from_tss(self):
        self.ride(secs=3600, watts=None, tss=64)          # IF 0.8, so 0.8 × 250 W × 3600 s
        load = nd.day_load(DAY)
        self.assertTrue(load["kj_estimated"])
        self.assertEqual(load["kj"], 720)

    def test_a_run_without_power_counts_time_but_not_energy(self):
        self.ride(secs=2700, watts=None, tss=40, sport="Run")
        load = nd.day_load(DAY)
        self.assertEqual(load["minutes"], 45)
        self.assertEqual(load["kj"], 0)
        self.assertEqual(load["unknown_kj"], 1)

    def test_completed_beats_planned(self):
        self.plan(minutes=180, tss=150)
        self.ride(secs=3600, watts=180, tss=50)
        load = nd.day_load(DAY)
        self.assertEqual(load["source"], "completed")
        self.assertEqual(load["minutes"], 60)

    def test_planned_workout_when_nothing_is_done_yet(self):
        self.plan(minutes=120, tss=100)                   # IF = sqrt(100 / 200) ≈ 0.707
        load = nd.day_load(DAY)
        self.assertEqual(load["source"], "planned")
        self.assertEqual(load["minutes"], 120)
        self.assertTrue(load["kj_estimated"])
        self.assertAlmostEqual(load["kj"], 0.7071 * 250 * 7200 / 1000, delta=1)

    def test_planned_workout_without_steps_is_flagged(self):
        self.plan(minutes=None, tss=80)
        load = nd.day_load(DAY)
        self.assertEqual(load["minutes"], 0)
        self.assertEqual(load["unknown_minutes"], 1)

    def test_empty_day(self):
        self.assertEqual(nd.day_load(DAY)["source"], "none")


class TargetTests(DbTest):
    def test_missing_weight_gives_a_clear_note(self):
        t = nd.day_targets(DAY)
        self.assertFalse(t["ok"])
        self.assertIn("weight", t["note"])

    def test_targets_for_a_two_hour_ride(self):
        q.set_setting("weight_kg", 70)
        self.ride(secs=7200, watts=200, tss=110, if_value=0.74)
        t = nd.day_targets(DAY)
        self.assertEqual(t["carbs"]["g"], 560)            # 8 g/kg
        self.assertEqual((t["carbs"]["low"], t["carbs"]["high"]), (420, 700))
        self.assertEqual(t["protein"]["g"], 112)          # 1.6 g/kg
        self.assertEqual(t["protein"]["per_meal_g"], 21)
        for part in ("carbs", "protein", "kcal"):
            self.assertIn("Evidence", t[part]["source"])

    def test_no_base_and_no_height_or_sex_gives_no_calorie_number(self):
        q.set_setting("weight_kg", 70)
        q.set_setting("birth_year", 1985)
        t = nd.day_targets(DAY)
        self.assertIsNone(t["kcal"]["kcal"])
        self.assertIn("Set a base", t["kcal"]["note"])

    def test_the_riders_own_base_wins(self):
        q.set_setting("weight_kg", 70)
        q.set_setting("base_kcal", 2100)
        q.set_setting("height_cm", 178)
        q.set_setting("birth_year", 1985)
        q.set_setting("energy_sex", "male")
        self.ride(secs=3600, watts=200)
        kcal = nd.day_targets(DAY)["kcal"]
        self.assertEqual(kcal["kcal"], 2100 + 720)
        self.assertFalse(kcal["estimated"])

    def test_estimate_uses_mifflin_st_jeor_times_1_4(self):
        q.set_setting("weight_kg", 70)
        q.set_setting("height_cm", 178)
        q.set_setting("birth_year", 1985)                 # 41 on the test day
        q.set_setting("energy_sex", "male")
        kcal = nd.day_targets(DAY)["kcal"]
        bmr = 10 * 70 + 6.25 * 178 - 5 * 41 + 5
        self.assertTrue(kcal["estimated"])
        self.assertEqual(kcal["kcal"], round(bmr * 1.4, -1))
        self.assertEqual(kcal["high"], round(bmr * 1.69, -1))

    def test_prefer_not_to_say_spans_both_formulas(self):
        est = nd.estimated_base(70, 178, 41, "prefer_not")
        female = nd.mifflin_st_jeor(70, 178, 41, "female")
        male = nd.mifflin_st_jeor(70, 178, 41, "male")
        self.assertEqual(est["low"], round(female * 1.4, -1))
        self.assertEqual(est["high"], round(male * 1.69, -1))
        self.assertIsNone(nd.estimated_base(70, 178, 41, "unspecified"))

    def test_calories_never_fall_below_base_plus_training(self):
        target = nd.calorie_target(70, 2500, base_kcal=2000)
        self.assertEqual(target["low"], 4500)

    def test_weight_entered_in_pounds_gives_the_same_targets(self):
        kg = to_kg(154, "lb")
        self.assertEqual(round(from_kg(kg, "lb")), 154)        # stored to two decimals, shown whole
        q.set_setting("weight_kg", kg)
        from_lb = nd.day_targets(DAY)
        q.set_setting("weight_kg", round(kg, 1))
        from_kg_entry = nd.day_targets(DAY)
        self.assertEqual(from_lb["protein"]["g"], from_kg_entry["protein"]["g"])
        self.assertEqual(from_lb["carbs"]["g"], from_kg_entry["carbs"]["g"])


if __name__ == "__main__":
    unittest.main()
