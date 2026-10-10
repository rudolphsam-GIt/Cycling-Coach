import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

import planning
from db import schema
from db import queries as q


def _monday() -> date:
    return date.today() - timedelta(days=date.today().weekday())


class WeekdayPlacementTests(unittest.TestCase):
    def test_rides_only_land_on_the_chosen_days(self):
        start = _monday()
        plan = planning.generate_block(40, 60, start + timedelta(days=56), "Threshold", start,
                                       available_days="Mon,Wed,Sat")
        self.assertTrue(plan)
        self.assertEqual({date.fromisoformat(w["date"]).weekday() for w in plan} - {0, 2, 5}, set())
        build = [w for w in plan if w["phase"] != planning.TAPER_LABEL]
        self.assertTrue(all(date.fromisoformat(w["date"]).weekday() == 5
                            for w in build if w["workout_type"] == "Long Ride"))
        self.assertTrue(any(w["workout_type"] == "Long Ride" for w in build))

    def test_a_start_mid_week_still_uses_real_weekdays(self):
        start = _monday() + timedelta(days=3)          # a Thursday
        plan = planning.generate_block(40, 60, start + timedelta(days=35), "Endurance", start,
                                       available_days=["Tue", "Sun"])
        self.assertEqual({date.fromisoformat(w["date"]).weekday() for w in plan}, {1, 6})
        long_days = {date.fromisoformat(w["date"]).weekday() for w in plan if w["workout_type"] == "Long Ride"}
        self.assertEqual(long_days, {6})

    def test_without_a_weekend_the_long_ride_goes_last(self):
        start = _monday()
        plan = planning.generate_block(40, 60, start + timedelta(days=28), "Endurance", start,
                                       available_days="Mon,Tue,Wed")
        long_days = {date.fromisoformat(w["date"]).weekday() for w in plan if w["workout_type"] == "Long Ride"}
        self.assertEqual(long_days, {2})

    def test_weekly_load_is_kept(self):
        start = _monday()
        race = start + timedelta(days=28)
        full = planning.generate_block(40, 60, race, "Threshold", start)
        some = planning.generate_block(40, 60, race, "Threshold", start, available_days="Tue,Thu,Sat")
        wk1 = lambda plan: sum(w["tss_planned"] for w in plan if w["week_number"] == 1)
        self.assertAlmostEqual(wk1(full), wk1(some), delta=6)

    def test_unset_days_keep_the_old_behaviour(self):
        start = _monday() + timedelta(days=2)
        race = start + timedelta(days=42)
        self.assertEqual(planning.generate_block(40, 60, race, "Threshold", start, days_per_week=4),
                         planning.generate_block(40, 60, race, "Threshold", start, days_per_week=4,
                                                 available_days=""))

    def test_parse_days(self):
        self.assertEqual(planning.parse_days("Sat, mon,Wed,nope"), ["Mon", "Wed", "Sat"])
        self.assertEqual(planning.parse_days(""), [])
        self.assertEqual(planning.parse_days(None), [])

    def test_target_ctl_range_is_useful_from_zero(self):
        lo, hi, default = planning.target_ctl_range(0)
        self.assertGreaterEqual(lo, 20)
        self.assertGreaterEqual(hi, 60)
        self.assertTrue(lo <= default <= hi)
        lo, hi, default = planning.target_ctl_range(70)
        self.assertEqual((lo, hi), (70, 110))
        self.assertTrue(lo <= default <= hi)
        lo, hi, _ = planning.target_ctl_range(170)
        self.assertGreater(hi, lo)


class _TempOwner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        q._settings_cache.clear()
        schema.run_migrations()
        q.set_setting("athlete_name", "Sam")


def _answers(**over) -> dict:
    a = {"name": "Alex", "goal_text": "Finish a gran fondo with friends", "rider_type": "I ride, but without a plan",
         "activity": "Lightly active", "gender": "woman", "age": 34, "weekly_hours": 7,
         "available_days": ["Tue", "Thu", "Sat"], "weight": 62.0, "unit": "kg", "dist_unit": "km",
         "ftp_choice": "known", "ftp_input": 210, "lthr_input": None, "max_hr": 188, "resting_hr": 52,
         "race_name": "Gran Fondo", "race_date": date.today() + timedelta(days=90)}
    a.update(over)
    return a


def _add_ride(days_ago: int, tss: float = 60) -> None:
    d = (date.today() - timedelta(days=days_ago)).isoformat()
    conn = schema.get_conn()
    conn.execute("INSERT INTO activities (source, external_id, date, name, sport_type, tss) "
                 "VALUES ('fit_import', ?, ?, 'r', 'cycling', ?)", (f"x{days_ago}", d, tss))
    conn.commit()
    conn.close()


class AthleteFormSaveTests(_TempOwner):
    def _save(self, ride_days_ago=None, files=("ride.fit",), **over):
        from components import athlete_form
        import ftp_change
        calls = []
        real_apply = ftp_change.apply_new_ftp

        def apply(*a, **k):
            calls.append("ftp")
            return real_apply(*a, **k)

        def fake_import(uploaded):
            # Settings and FTP must already be there when rides are scored.
            calls.append(("import", q.get_setting("ftp_watts"), q.get_setting("lthr"),
                          len(q.ftp_history_rows())))
            for n in ride_days_ago or []:
                _add_ride(n)
            return len(ride_days_ago or []), "Imported rides."

        with mock.patch.object(ftp_change, "apply_new_ftp", side_effect=apply), \
                mock.patch("auth.fit_import.import_fit_files", side_effect=fake_import):
            result = athlete_form.save_athlete(_answers(**over), list(files) if files else None)
        return result, calls

    def test_writes_settings_and_race_then_imports(self):
        result, calls = self._save(ride_days_ago=[3, 10])
        self.assertEqual(calls[0], "ftp")
        self.assertEqual(calls[1][0], "import")
        self.assertEqual(calls[1][1], "210")                 # FTP set before the import
        self.assertTrue(calls[1][2])                        # LTHR estimated before the import
        self.assertEqual(calls[1][3], 1)                    # and FTP history has its first entry
        self.assertTrue(schema.is_owner())                  # the session never left the owner
        self.assertIsNone(q.get_setting("available_days"))
        with schema.use(result["path"]):
            self.assertFalse(schema.is_owner())
            s = q.get_all_settings()
            self.assertEqual(s["athlete_name"], "Alex")
            self.assertEqual(s["max_hr_manual"], "188")
            self.assertEqual(s["resting_hr_manual"], "52")
            self.assertEqual(s["available_days"], "Tue,Thu,Sat")
            self.assertEqual(s["days_per_week"], "3")
            self.assertEqual(s["weekly_hours_target"], "7")
            self.assertEqual(s["onboarding_complete"], "1")
            self.assertEqual(s["ftp_estimated"], "0")
            self.assertEqual(s["lthr_estimated"], "1")
            self.assertEqual(s["ctl_start"], "25")          # short history keeps the experience seed
            self.assertEqual([r["name"] for r in q.get_races(upcoming_only=True)], ["Gran Fondo"])
        self.assertEqual(result["imported"], 2)
        self.assertFalse(result["seed_reset"])

    def test_six_weeks_of_rides_replace_the_seed(self):
        result, _ = self._save(ride_days_ago=[2, 20, 45])
        self.assertTrue(result["seed_reset"])
        with schema.use(result["path"]):
            self.assertEqual(float(q.get_setting("ctl_start")), 0)
            self.assertEqual(float(q.get_setting("atl_start")), 0)

    def test_no_files_and_estimated_ftp(self):
        result, calls = self._save(files=None, ftp_choice="estimate", ftp_input=None, max_hr=None,
                                   resting_hr=None, race_name="", race_date=None, available_days=[])
        self.assertEqual(calls, ["ftp"])
        with schema.use(result["path"]):
            s = q.get_all_settings()
            self.assertEqual(s["ftp_estimated"], "1")
            self.assertGreater(float(s["ftp_watts"]), 0)
            self.assertEqual(s["max_hr_manual"], "")
            self.assertEqual(s["available_days"], "")
            self.assertEqual(s["days_per_week"], "4")
            self.assertEqual(q.get_races(), [])


class SeedRuleTests(_TempOwner):
    def test_rides_cover_seed(self):
        from metrics.training_load import rides_cover_seed
        self.assertFalse(rides_cover_seed())
        _add_ride(41)
        self.assertFalse(rides_cover_seed())
        _add_ride(42)
        self.assertTrue(rides_cover_seed())


class CoachContextTests(_TempOwner):
    def test_coached_profile_snapshot(self):
        from coach_context import build_context
        from db import profiles
        p = profiles.create_profile("Alex")
        with schema.use(p["path"]):
            q.set_setting("ctl_start", 45)
            q.set_setting("available_days", "Tue,Sat")
            q.set_setting("max_hr_manual", 190)
            q.set_setting("resting_hr_manual", 50)
            _add_ride(5)
            text = build_context()
        self.assertIn("Sam is the coach and is planning for Alex", text)
        self.assertIn("Name: Alex", text)
        self.assertIn("Days they can ride: Tue, Sat", text)
        self.assertIn("Max HR: 190bpm", text)
        self.assertIn("Resting HR: 50bpm", text)
        self.assertIn("estimated seed of 45", text)
        self.assertIn("not measured", text)

    def test_owner_with_long_history_has_neither_note(self):
        from coach_context import build_context
        q.set_setting("ctl_start", 45)
        _add_ride(60)
        _add_ride(1)
        text = build_context()
        self.assertNotIn("is the coach and is planning", text)
        self.assertNotIn("estimated seed", text)
        self.assertNotIn("Days they can ride", text)

    def test_coached_first_block_message(self):
        from metrics import explain
        m = explain.first_block_message(goals=["Ride a century"], experience="New to structured training",
                                        hours=6, days=3, ftp=180, ftp_estimated=True, name="Alex",
                                        ride_days=["Tue", "Thu", "Sat"], coach="Sam")
        self.assertIn("I'm Sam. I'm planning for Alex", m)
        self.assertIn("in their own words", m)
        self.assertIn("can ride on Tue, Thu and Sat", m)
        self.assertIn("because they do not know their real one", m)
        self.assertNotIn("—", m)


class FormTextTests(unittest.TestCase):
    def test_no_em_dashes_in_new_text(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "components", "athlete_form.py")) as f:
            text = f.read()
        body = text.split('"""', 2)[2]          # the module docstring is for developers
        self.assertNotIn("—", body)
        self.assertNotIn("–", body)


if __name__ == "__main__":
    unittest.main()
