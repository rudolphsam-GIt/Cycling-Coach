"""
The check in, memories and program planning sit in one row above the coach chat, and a draft program
shows as a short card with Open draft, so they don't push the chat down the page.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

from streamlit.testing.v1 import AppTest

import programs
from components import calendar_dnd
from db import schema, queries as q
from tests.test_programs import sample

PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pages", "02_Training_Planner.py")


class CoachBarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db")),
                  mock.patch("config.ANTHROPIC_API_KEY", "sk-test"),
                  mock.patch.object(calendar_dnd, "_component", None)):
            p.start()
            self.addCleanup(p.stop)
        schema.run_migrations()

    def open_coach(self) -> AppTest:
        at = AppTest.from_file(PAGE, default_timeout=60)
        at.session_state["plan_tab"] = "Coach"
        at.run()
        self.assertFalse(at.exception)
        return at

    @staticmethod
    def labels(at: AppTest) -> list[str]:
        return [b.label for b in at.button]

    def test_the_bar_replaces_the_cards_above_the_chat(self):
        q.add_memory("schedule", "Rides before work on weekdays")
        at = self.open_coach()
        self.assertTrue({"Weekly check in", "Weekly check in ready"} & set(self.labels(at)))
        self.assertFalse([e for e in at.expander if e.label in ("What your coach remembers", "Weekly check in",
                                                                "Past check ins")])
        self.assertFalse(any("Plan a longer program" in m.value for m in at.markdown))
        # The starters still work from the popover.
        start = next(b for b in at.button if b.label == "Plan toward a goal or race")
        with mock.patch("components.coach_ui.stream_reply", return_value=("What is the goal?", None)):
            start.click().run()
        self.assertFalse(at.exception)
        self.assertIn("Back to normal chat", self.labels(at))
        self.assertTrue(any("Program planning is on" in c.value for c in at.caption))

    def test_a_draft_program_shows_short_with_open_draft(self):
        monday = date.today() + timedelta(days=7 - date.today().weekday())
        programs.save_draft(sample(monday))
        at = self.open_coach()
        labels = self.labels(at)
        for label in ("Open draft", "Add to my calendar", "Discard draft"):
            self.assertIn(label, labels)
        self.assertNotIn("Send comments to the coach", labels)      # comments live in Open draft
        self.assertNotIn("Plan toward a goal or race", labels)      # no starters while a draft waits
        self.assertFalse(at.metric)                                 # the numbers and chart too


if __name__ == "__main__":
    unittest.main()
