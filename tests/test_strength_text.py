import json
import os
import tempfile
import unittest
from datetime import date, timedelta

import strength_text as stx

SQUAT = {"name": "Back squat", "sets": 3, "reps": "10 to 12", "intensity": "RPE 7", "load": "135 lb",
         "notes": "Push up fast", "progression": "add 5 lb a week while it stays at RPE 7"}


class LineTests(unittest.TestCase):
    def test_full_prescription(self):
        self.assertEqual(stx.line(SQUAT), "Back squat · 3 × 10 to 12 · 135 lb · RPE 7")
        self.assertEqual(stx.short(SQUAT), "Back squat 3 × 10 to 12, 135 lb")
        self.assertEqual(stx.note(SQUAT), "Push up fast. Add 5 lb a week while it stays at RPE 7.")

    def test_older_sessions_without_load_still_read_well(self):
        old = {"name": "Side plank", "sets": 2, "reps": "30 sec each side", "intensity": "Controlled"}
        self.assertEqual(stx.line(old), "Side plank · 2 × 30 sec each side · Controlled")
        self.assertEqual(stx.short({"name": "Ex1"}), "Ex1")
        self.assertEqual(stx.note(old), "")

    def test_logged_weight_in_the_athletes_unit(self):
        done = {"name": "Back squat", "sets": 3, "reps": "8", "intensity": "RPE 8", "weight_kg": 61.23}
        self.assertIn("used 135 lb", stx.line(done, "lb"))
        self.assertIn("used 61.23 kg", stx.line(done, "kg"))
        self.assertNotIn("used", stx.line({**done, "weight_kg": 0}, "lb"))

    def test_bodyweight_only(self):
        self.assertTrue(stx.bodyweight_only({"name": "Box jumps", "intensity": "Easy", "load": "bodyweight"}))
        self.assertTrue(stx.bodyweight_only({"name": "Plank", "intensity": "Bodyweight"}))
        self.assertFalse(stx.bodyweight_only({"name": "Calf raise", "intensity": "RPE 7", "load": "bodyweight plus 45 lb"}))
        self.assertFalse(stx.bodyweight_only(SQUAT))
        # "Bodyweight/weighted" can carry a weight, so it gets a box to log one.
        self.assertFalse(stx.bodyweight_only({"name": "Calf raise", "intensity": "Bodyweight/weighted"}))
        self.assertFalse(stx.bodyweight_only({"name": "Back Squat", "intensity": "75-85% 1RM"}))

    def test_same_session(self):
        a = {"name": "Lower", "exercises": [SQUAT]}
        self.assertTrue(stx.same_session(a, dict(a)))
        self.assertFalse(stx.same_session(a, {"name": "Lower", "exercises": []}))


class CoachToolTests(unittest.TestCase):
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

    def test_proposed_exercises_need_a_load(self):
        import coach_tools
        soon = (date.today() + timedelta(days=3)).isoformat()
        session = {"date": soon, "name": "Lower", "duration_minutes": 45, "purpose": "Leg strength.",
                   "exercises": [{k: v for k, v in SQUAT.items() if k != "load"}]}
        with self.assertRaises(coach_tools.ToolInputError):
            coach_tools._propose_strength({"sessions": [session]}, [])
        out = []
        coach_tools._propose_strength({"sessions": [{**session, "exercises": [SQUAT]}]}, out)
        self.assertEqual(out[0]["exercises"][0]["progression"], SQUAT["progression"])

    def test_coach_sees_logged_weights(self):
        import coach_tools
        from db.queries import add_strength_session, set_setting
        set_setting("weight_unit", "lb")
        day = (date.today() - timedelta(days=2)).isoformat()
        add_strength_session({"date": day, "plan_week": None, "duration_minutes": 45, "completed": 1,
                              "notes": "Lower | felt good",
                              "exercises_json": json.dumps([{**SQUAT, "weight_kg": 61.23}])})
        rows = coach_tools._strength_rows(day, day)
        self.assertIn("used 135 lb", rows[0]["exercises"][0])
        self.assertIn("135 lb", rows[0]["exercises"][0])

    def test_program_keeps_load_and_progression_but_does_not_require_them(self):
        import programs
        out = programs._exercises([SQUAT, {"name": "Plank", "sets": 2, "reps": "45 sec", "intensity": "Easy"}], "phase 1")
        self.assertEqual(out[0]["load"], "135 lb")
        self.assertEqual(out[0]["progression"], SQUAT["progression"])
        self.assertNotIn("load", out[1])


class CalendarTests(unittest.TestCase):
    def test_tooltip_shows_sets_and_load(self):
        from components import calendar as cal
        row = {"date": "2026-10-20", "notes": "Lower | Planned by AI Coach", "completed": 0,
               "exercises_json": json.dumps([SQUAT])}
        days = cal.build_month_data(2026, 10, [], [], [row], [], date(2026, 10, 15))
        tip = cal.day_tooltip(days["2026-10-20"])
        self.assertIn("Back squat 3 × 10 to 12, 135 lb", tip)


if __name__ == "__main__":
    unittest.main()
