"""
A workout the coach suggests in a ride review is shown where the review is, in the ride analysis
Coach tab, so a review of an older ride doesn't leave it somewhere Today never draws. Today's card
for the latest ride can be on screen in the same run, so the two copies need their own widget keys.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

from streamlit.testing.v1 import AppTest

from db import schema, queries as q

SOON = (date.today() + timedelta(days=2)).isoformat()
SPIN = {"kind": "ride", "date": SOON, "name": "Easy spin", "workout_type": "Recovery",
        "description": "30 min easy", "tss_planned": 25}


def _app():
    import streamlit as st
    import coach_reports
    from components import coach_ui, ride_analysis
    from db import queries as q
    act = q.get_activity(st.session_state["ride_id"])
    key, title, prompt = coach_reports.ride_review(act)
    if st.session_state.get("with_today"):           # Today's card for the same ride, drawn first
        coach_ui.report_block("ride_review", key, title, prompt, button_label="Review this ride")

    @st.fragment                                      # the ride analysis popup is a fragment
    def popup():
        ride_analysis._coach(act)
    popup()


class RideReviewProposalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()
        self.ride = q.upsert_activity({
            "source": "garmin", "external_id": "garmin_9", "date": (date.today() - timedelta(days=20)).isoformat(),
            "name": "Old hard ride", "sport_type": "ride", "duration_seconds": 3600, "elapsed_seconds": 3700,
            "distance_meters": 30000, "elevation_gain_meters": 0, "avg_power_watts": 250, "avg_hr": 150,
            "max_hr": 180, "normalized_power": 260, "tss": 80, "if_value": 0.8, "raw_json": "{}"})
        import coach_reports
        key, title, _ = coach_reports.ride_review(q.get_activity(self.ride))
        q.save_report("ride_review", key, title, "Good ride. Take an easy day.")
        self.state_key = f"proposals_ride_review_{key}"

    def run_app(self, **state) -> AppTest:
        at = AppTest.from_function(_app, default_timeout=30)
        at.session_state["ride_id"] = self.ride
        at.session_state[self.state_key] = [dict(SPIN)]
        for k, v in state.items():
            at.session_state[k] = v
        return at.run()

    def test_the_suggestion_waits_in_the_ride_analysis_and_can_be_added(self):
        at = self.run_app()
        self.assertFalse(at.exception)
        add = [b for b in at.button if b.label == "Add to Training Planner"]
        self.assertEqual(len(add), 1)
        add[0].click().run()
        self.assertFalse(at.exception)
        self.assertEqual([w["name"] for w in q.get_workouts(SOON, SOON)], ["Easy spin"])
        self.assertIn("Done. Added 1 ride.", [s.value for s in at.success])     # said in the popup

    def test_today_and_the_ride_analysis_can_show_it_together(self):
        at = self.run_app(with_today=True)
        self.assertFalse(at.exception)
        self.assertEqual(len([b for b in at.button if b.label == "Add to Training Planner"]), 2)


if __name__ == "__main__":
    unittest.main()
