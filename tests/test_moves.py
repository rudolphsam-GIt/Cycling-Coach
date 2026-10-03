"""Moving planned workouts and strength sessions, on a throwaway database.
Run with venv/bin/python -m unittest tests.test_moves -v"""
import os
import tempfile
import unittest
from datetime import date
from unittest import mock

import streamlit as st

from components import calendar as cal
from db import schema, queries as q


class MoveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()

    def _workout(self, day="2026-10-06"):
        return q.add_workout({"date": day, "name": "Threshold", "workout_type": "Threshold",
                              "description": "4x8", "structured_json": None,
                              "tss_planned": 90, "notes": ""})

    def test_move_workout_changes_only_the_date(self):
        wid = self._workout()
        old = q.move_workout(wid, "2026-10-07")
        self.assertEqual(old["date"], "2026-10-06")
        w = q.get_workout(wid)
        self.assertEqual(w["date"], "2026-10-07")
        self.assertEqual((w["name"], w["tss_planned"], w["description"]),
                         ("Threshold", 90, "4x8"))

    def test_move_clears_garmin_ids(self):
        wid = self._workout()
        q.set_workout_garmin(wid, "g1", "s1", "[]", "2026-10-01T00:00:00")
        old = q.move_workout(wid, "2026-10-08")
        self.assertEqual(old["garmin_workout_id"], "g1")   # caller can delete the copy
        w = q.get_workout(wid)
        self.assertIsNone(w["garmin_workout_id"])
        self.assertIsNone(w["garmin_schedule_id"])
        self.assertIsNone(w["garmin_sent_at"])

    def test_move_to_same_day_or_missing_row_is_a_no_op(self):
        wid = self._workout()
        self.assertIsNone(q.move_workout(wid, "2026-10-06"))
        self.assertIsNone(q.move_workout(9999, "2026-10-07"))
        self.assertEqual(q.get_workout(wid)["date"], "2026-10-06")

    def test_move_strength_session(self):
        sid = q.add_strength_session({"date": "2026-10-09", "plan_week": 1,
                                      "exercises_json": "[]", "duration_minutes": 45,
                                      "notes": "Lower | Planned by AI Coach"})
        old = q.move_strength_session(sid, "2026-10-10")
        self.assertEqual(old["date"], "2026-10-09")
        rows = [s for s in q.get_strength_sessions(days_back=4000) if s["id"] == sid]
        self.assertEqual(rows[0]["date"], "2026-10-10")
        self.assertEqual(rows[0]["notes"], "Lower | Planned by AI Coach")
        self.assertIsNone(q.move_strength_session(sid, "2026-10-10"))


class ApplyMoveTests(unittest.TestCase):
    TODAY = date(2026, 10, 7)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        for target in (mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db")),
                       mock.patch.object(st, "session_state", {}),
                       mock.patch.object(st, "toast", lambda *a, **k: None)):
            target.start()
            self.addCleanup(target.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()
        self.removed = []
        patcher = mock.patch("garmin_workouts.remove_from_garmin", self.removed.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _workout(self, day, **kw):
        return q.add_workout({"date": day, "name": "Threshold", "workout_type": "Threshold",
                              "description": "", "structured_json": None, "tss_planned": 90,
                              "notes": "", **kw})

    def test_moves_an_upcoming_workout_and_remembers_it(self):
        wid = self._workout("2026-10-12")
        self.assertIsNone(cal.apply_move("ride", wid, "2026-10-14", self.TODAY))
        self.assertEqual(q.get_workout(wid)["date"], "2026-10-14")
        last = st.session_state[cal.LAST_MOVE_KEY]
        self.assertEqual((last["from"], last["to"], last["tss"]), ("2026-10-12", "2026-10-14", 90.0))

    def test_removes_the_garmin_copy_once(self):
        wid = self._workout("2026-10-12")
        q.set_workout_garmin(wid, "g1", "s1", "[]", "2026-10-01T00:00:00")
        cal.apply_move("ride", wid, "2026-10-14", self.TODAY)
        self.assertEqual([w["garmin_workout_id"] for w in self.removed], ["g1"])
        self.assertTrue(st.session_state[cal.LAST_MOVE_KEY]["garmin"])

    def test_refuses_past_targets_past_sources_and_done_workouts(self):
        future = self._workout("2026-10-12")
        past = self._workout("2026-10-05")
        done = self._workout("2026-10-12")
        q.update_workout(done, {**q.get_workout(done), "completed": 1})
        self.assertIn("passed", cal.apply_move("ride", future, "2026-10-06", self.TODAY))
        self.assertIn("stay where", cal.apply_move("ride", past, "2026-10-14", self.TODAY))
        self.assertIn("stay where", cal.apply_move("ride", done, "2026-10-14", self.TODAY))
        self.assertEqual(q.get_workout(future)["date"], "2026-10-12")
        self.assertEqual(self.removed, [])
        self.assertNotIn(cal.LAST_MOVE_KEY, st.session_state)

    def test_refuses_bad_input(self):
        wid = self._workout("2026-10-12")
        self.assertIn("valid date", cal.apply_move("ride", wid, "nonsense", self.TODAY))
        self.assertIn("can't be moved", cal.apply_move("ride", "abc", "2026-10-14", self.TODAY))
        self.assertIn("can't be moved", cal.apply_move("other", wid, "2026-10-14", self.TODAY))
        self.assertIn("no longer exists", cal.apply_move("ride", 9999, "2026-10-14", self.TODAY))

    def test_same_day_is_a_quiet_no_op(self):
        wid = self._workout("2026-10-12")
        self.assertIsNone(cal.apply_move("ride", wid, "2026-10-12", self.TODAY))
        self.assertNotIn(cal.LAST_MOVE_KEY, st.session_state)

    def test_undo_puts_it_back(self):
        wid = self._workout("2026-10-12")
        cal.apply_move("ride", wid, "2026-10-14", self.TODAY)
        cal.undo_last_move()
        self.assertEqual(q.get_workout(wid)["date"], "2026-10-12")
        self.assertNotIn(cal.LAST_MOVE_KEY, st.session_state)
        cal.undo_last_move()   # nothing left, must not raise

    def test_strength_move_and_done_session_is_locked(self):
        planned = q.add_strength_session({"date": "2026-10-12", "plan_week": 1, "exercises_json": "[]",
                                          "duration_minutes": 40, "notes": "Legs | Planned by AI Coach"})
        done = q.add_strength_session({"date": "2026-10-13", "plan_week": 1, "exercises_json": "[]",
                                       "duration_minutes": 40, "notes": "Upper", "completed": 1})
        self.assertIsNone(cal.apply_move("strength", planned, "2026-10-15", self.TODAY))
        self.assertEqual(q.get_strength_session(planned)["date"], "2026-10-15")
        self.assertEqual(st.session_state[cal.LAST_MOVE_KEY]["label"], "Legs")
        self.assertEqual(self.removed, [])
        self.assertIn("stay where", cal.apply_move("strength", done, "2026-10-15", self.TODAY))
        cal.undo_last_move()
        self.assertEqual(q.get_strength_session(planned)["date"], "2026-10-12")


if __name__ == "__main__":
    unittest.main()
