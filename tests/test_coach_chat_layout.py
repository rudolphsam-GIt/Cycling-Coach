"""
The coach chat shows the latest question with its reply right under it. Earlier messages fold away,
and a drafted plan shows as a short summary with Review, so the chat stays short.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

from streamlit.testing.v1 import AppTest

from components import calendar_dnd, coach_ui
from db import schema, queries as q

PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pages", "02_Training_Planner.py")


def ride(day: date, tss: float = 60) -> dict:
    return {"kind": "ride", "date": day.isoformat(), "name": "Endurance", "workout_type": "endurance",
            "description": "Easy 90 min", "steps": None, "tss_planned": tss}


class ChatLayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db")),
                  mock.patch("config.ANTHROPIC_API_KEY", "sk-test"),
                  mock.patch.object(calendar_dnd, "_component", None)):
            p.start()
            self.addCleanup(p.stop)
        schema.run_migrations()

    @staticmethod
    def folded(at: AppTest) -> list:
        # AppTest reads an expander that has an icon as a status box.
        return [e for e in [*at.expander, *at.status] if e.label.startswith("Earlier in this chat")]

    def open_coach(self, **state) -> AppTest:
        at = AppTest.from_file(PAGE, default_timeout=60)
        at.session_state["plan_tab"] = "Coach"
        for k, v in state.items():
            at.session_state[k] = v
        at.run()
        self.assertFalse(at.exception)
        return at

    def test_only_the_latest_exchange_shows_in_full(self):
        for n in range(3):
            q.save_message("user", f"Question {n}")
            q.save_message("assistant", f"Answer {n}")
        at = self.open_coach()
        earlier = self.folded(at)
        self.assertEqual(len(earlier), 1)
        self.assertEqual(earlier[0].label, "Earlier in this chat (4 messages)")
        self.assertEqual(len(earlier[0].chat_message), 4)
        self.assertEqual(len(at.chat_message), 6)
        shown = [m.markdown[0].value for m in at.chat_message[4:]]
        self.assertEqual(shown, ["Question 2", "Answer 2"])

    def test_a_short_chat_has_nothing_folded(self):
        q.save_message("user", "Question")
        q.save_message("assistant", "Answer")
        at = self.open_coach()
        self.assertFalse(self.folded(at))

    def test_details_in_the_folded_history_do_not_break_the_page(self):
        q.save_message("user", "Old question")
        q.save_message("assistant", "Old answer\n\n[DETAILS]\nWhy it works.")
        q.save_message("user", "New question")
        q.save_message("assistant", "New answer\n\n[DETAILS]\nMore.")
        self.open_coach()

    def test_a_proposal_shows_as_a_summary_with_review(self):
        start = date.today() + timedelta(days=2)
        q.save_message("user", "Plan two rides")
        q.save_message("assistant", "Here are two rides. Review them below the chat.")
        at = self.open_coach(proposed_workouts=[ride(start), ride(start + timedelta(days=1), 50)])
        labels = [b.label for b in at.button]
        self.assertIn("Review", labels)
        self.assertNotIn("Send comments to the coach", labels)       # the full card stays in Review
        self.assertTrue(any("2 rides · 110 TSS" in m.value for m in at.markdown))

        next(b for b in at.button if b.label == "Add to Training Planner").click().run()
        self.assertFalse(at.exception)
        added = q.get_workouts(start.isoformat(), (start + timedelta(days=1)).isoformat())
        self.assertEqual(len(added), 2)
        self.assertTrue(any(s.value.startswith("Done. Added 2 rides") for s in at.success))


class ProposalLineTests(unittest.TestCase):
    def test_proposal_line(self):
        self.assertEqual(coach_ui.proposal_line([ride(date.today(), 40)]), "1 ride · 40 TSS")
        self.assertEqual(coach_ui.proposal_line([{"kind": "strength", "date": "2026-10-20"}] * 2),
                         "2 strength sessions")


if __name__ == "__main__":
    unittest.main()
