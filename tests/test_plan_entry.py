import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

TODAY = date(2026, 10, 15)


class PlanEntryTest(unittest.TestCase):
    """When the Build plan card shows, and what the empty Export box says."""

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

    def _ride(self, days_ahead, completed=0):
        from db.queries import add_workout
        wid = add_workout({"date": (TODAY + timedelta(days=days_ahead)).isoformat(), "name": "Endurance 60 min",
                           "workout_type": "Endurance", "description": "", "structured_json": None,
                           "tss_planned": 50, "notes": ""})
        if completed:
            conn = self.schema.get_conn()
            conn.execute("UPDATE workouts SET completed=1 WHERE id=?", (wid,))
            conn.commit()
            conn.close()

    def test_no_rides_needs_a_plan(self):
        from components.onboarding import needs_plan, next_planned_ride
        self.assertIsNone(next_planned_ride(TODAY))
        self.assertTrue(needs_plan(TODAY))

    def test_a_ride_in_the_next_two_weeks_means_no_card(self):
        from components.onboarding import needs_plan, next_planned_ride
        self._ride(14)
        nxt = next_planned_ride(TODAY)
        self.assertFalse(needs_plan(TODAY, nxt))

    def test_rides_further_out_still_show_the_card(self):
        from components.onboarding import needs_plan, next_planned_ride
        self._ride(15)
        nxt = next_planned_ride(TODAY)
        self.assertEqual(nxt["date"], (TODAY + timedelta(days=15)).isoformat())
        self.assertTrue(needs_plan(TODAY, nxt))

    def test_done_and_past_rides_dont_count(self):
        from components.onboarding import next_planned_ride
        self._ride(-3)
        self._ride(2, completed=1)
        self.assertIsNone(next_planned_ride(TODAY))

    def test_a_waiting_program_draft_hides_the_card(self):
        from components.onboarding import needs_plan
        with mock.patch("programs.load", return_value={"id": 1}):
            self.assertFalse(needs_plan(TODAY))


if __name__ == "__main__":
    unittest.main()
