"""
A coach reply can be cut off part way, for example when the rider switches tabs while it streams. The
question is saved but the reply never is. The chat must say so and offer Try again.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from streamlit.testing.v1 import AppTest

from components import calendar_dnd
from db import schema, queries as q

PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pages", "02_Training_Planner.py")


class CoachCutOffTests(unittest.TestCase):
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
        self.assertEqual(len(at.chat_input), 1)                  # the coach chat is drawn
        return at

    def test_an_unanswered_question_offers_try_again(self):
        q.save_message("user", "Plan my week please")           # its reply was cut off
        at = self.open_coach()
        self.assertFalse(at.exception)
        retry = [b for b in at.button if b.label == "Try again"]
        self.assertEqual(len(retry), 1)

        with mock.patch("components.coach_ui.stream_reply", return_value=("Here is your week.", None)):
            retry[0].click().run()
        self.assertFalse(at.exception)
        self.assertEqual([m["role"] for m in q.get_conversation_history()], ["user", "assistant"])
        self.assertFalse([b for b in at.button if b.label == "Try again"])

    def test_an_answered_chat_has_no_try_again(self):
        q.save_message("user", "Plan my week please")
        q.save_message("assistant", "Here is your week.")
        at = self.open_coach()
        self.assertFalse(at.exception)
        self.assertFalse([b for b in at.button if b.label == "Try again"])


if __name__ == "__main__":
    unittest.main()
