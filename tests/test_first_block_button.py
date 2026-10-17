"""
The welcome banner on Today shows once, so its Build my first block button is gone on the rerun its
click causes. The click must still open the coach on the Plan page with the request written.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from streamlit.testing.v1 import AppTest

from db import schema, queries as q

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


class WelcomeFirstBlockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db")),
                  mock.patch("config.is_setup_complete", return_value=True),
                  mock.patch("config.ANTHROPIC_API_KEY", ""),            # no coach call from a test
                  mock.patch("auth.garmin.is_connected", return_value=False)):
            p.start()
            self.addCleanup(p.stop)
        schema.run_migrations()
        q.set_setting("onboarding_complete", "1")
        q.set_setting("goal_text", "Ride my first 100 mile day")
        q.set_setting("days_per_week", 4)

    def test_the_welcome_button_opens_the_coach_with_the_request(self):
        at = AppTest.from_file(APP, default_timeout=60)
        at.session_state["onboarding_just_finished"] = ["endurance"]
        at.run()
        self.assertFalse(at.exception)
        at.button(key="welcome_first_block").click().run()
        self.assertFalse(at.exception)
        self.assertIn("100 mile", at.session_state["pending_message"])
        self.assertEqual(at.session_state["plan_tab"], "Coach")          # the Plan page's Coach tab


if __name__ == "__main__":
    unittest.main()
