"""
The Plan page's workout dialog. Closing a dialog doesn't rerun the page, so the next workout opened
can be drawn in the very next run. Its inputs must start from that workout, not the one before.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

from streamlit.testing.v1 import AppTest

from db import schema, queries as q

PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pages", "02_Training_Planner.py")
DAY = (date.today() + timedelta(days=1)).isoformat()


class WorkoutDialogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()
        self.long = q.add_workout({"date": DAY, "name": "Long ride", "workout_type": "Long Ride",
                                   "description": "Steady all day", "structured_json": None,
                                   "tss_planned": 150, "notes": ""})
        self.tempo = q.add_workout({"date": DAY, "name": "Tempo", "workout_type": "Tempo",
                                    "description": "60 min tempo", "structured_json": None,
                                    "tss_planned": 60, "notes": ""})

    def open(self, at: AppTest, wid: int) -> AppTest:
        at.session_state["cal_open"] = {"kind": "ride", "id": wid}
        return at.run()

    def fields(self, at: AppTest) -> dict:
        return {"name": next(t.value for t in at.text_input if t.label == "Workout name"),
                "tss": next(n.value for n in at.number_input if n.label == "Planned TSS"),
                "desc": next(t.value for t in at.text_area if t.label == "Description or notes")}

    def test_the_next_workout_opens_with_its_own_values(self):
        at = AppTest.from_file(PAGE, default_timeout=60)
        self.assertEqual(self.fields(self.open(at, self.long)),
                         {"name": "Long ride", "tss": 150, "desc": "Steady all day"})
        # The dialog is closed without a rerun, then the other workout on the day is opened.
        self.assertEqual(self.fields(self.open(at, self.tempo)),
                         {"name": "Tempo", "tss": 60, "desc": "60 min tempo"})


if __name__ == "__main__":
    unittest.main()
