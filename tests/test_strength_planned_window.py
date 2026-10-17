"""
"Planned by your coach" on the Strength page is for sessions to log now. It shows the unlogged ones from
the last two weeks and the coming week, not every session left in the block, and says how many are later.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

from streamlit.testing.v1 import AppTest

from db import schema, queries as q

PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pages", "04_Strength_Training.py")


def _planned(offset: int, name: str) -> None:
    q.add_strength_session({"date": (date.today() + timedelta(days=offset)).isoformat(), "plan_week": None,
                            "exercises_json": "[]", "duration_minutes": 30,
                            "notes": f"{name} | Planned by AI Coach"})


class PlannedWindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()
        _planned(-20, "Too old")
        _planned(-3, "Missed")
        _planned(0, "Today")
        _planned(7, "Next week")
        _planned(8, "Later one")
        _planned(30, "Later two")

    def test_only_sessions_due_now_get_a_form(self):
        at = AppTest.from_file(PAGE, default_timeout=60).run()
        self.assertFalse(at.exception)
        names = [e.label.split(" · ")[1] for e in at.expander if " · " in e.label]
        self.assertEqual(names, ["Missed", "Today", "Next week"])
        self.assertTrue(any("2 more planned" in c.value for c in at.caption))


if __name__ == "__main__":
    unittest.main()
