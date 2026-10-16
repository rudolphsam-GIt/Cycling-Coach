import unittest
from unittest import mock

import pandas as pd

from components import coach_ui


class CommentsMessageTests(unittest.TestCase):
    def test_no_comments_no_message(self):
        self.assertEqual(coach_ui.comments_message([], "  "), "")

    def test_lines_and_overall_become_one_message(self):
        msg = coach_ui.comments_message(["Tue Oct 20, VO2 max 5x3 min → move to Wednesday"],
                                        "keep Fridays free", what="the draft program")
        self.assertTrue(msg.startswith("I have comments on the draft program."))
        self.assertIn("\n\n- Tue Oct 20, VO2 max 5x3 min → move to Wednesday", msg)
        self.assertTrue(msg.endswith("- Overall → keep Fridays free"))

    def test_overall_alone_is_enough(self):
        self.assertIn("- Overall → fewer VO2 days", coach_ui.comments_message([], "fewer VO2 days"))


class LabelAndKeyTests(unittest.TestCase):
    def test_ride_label(self):
        row = pd.Series({"Date": "2026-10-20", "Workout": "VO2 max 5x3 min"})
        self.assertEqual(coach_ui._ride_label(row), "Tue Oct 20, VO2 max 5x3 min")
        self.assertEqual(coach_ui._ride_label(pd.Series({"Date": "soon", "Workout": "Ride"})), "soon, Ride")

    def test_key_changes_with_the_draft_and_after_sending(self):
        state = {}
        with mock.patch.object(coach_ui.st, "session_state", state):
            a = coach_ui.comment_key("p", [{"date": "2026-10-20"}])
            self.assertEqual(a, coach_ui.comment_key("p", [{"date": "2026-10-20"}]))
            self.assertNotEqual(a, coach_ui.comment_key("p", [{"date": "2026-10-21"}]))
            state["p_cv"] = 1
            self.assertNotEqual(a, coach_ui.comment_key("p", [{"date": "2026-10-20"}]))


if __name__ == "__main__":
    unittest.main()
