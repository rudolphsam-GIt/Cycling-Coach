"""
Progress, History and Rides tabs. History reads every ride and peak and works out its tables, which is
slow, so it is kept until the rides or peaks change. The Rides CSV is built when it is downloaded.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

import streamlit as st
from streamlit.testing.v1 import AppTest

from db import schema, queries as q

PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pages", "05_Dashboard_Charts.py")


def _ride(n: int) -> dict:
    day = (date.today() - timedelta(days=n)).isoformat()
    return {"source": "garmin", "external_id": f"garmin_{n}", "date": day, "name": f"Ride {n}",
            "sport_type": "ride", "duration_seconds": 3600, "elapsed_seconds": 3700, "distance_meters": 30000,
            "elevation_gain_meters": 0, "avg_power_watts": 200, "avg_hr": 140, "max_hr": 170,
            "normalized_power": 210, "tss": 60, "if_value": 0.7, "raw_json": "{}"}


class ProgressTabsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # The Settings links need the whole app's navigation, which a single page test doesn't have.
        for p in (mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db")),
                  mock.patch.object(st, "page_link")):
            p.start()
            self.addCleanup(p.stop)
        schema.run_migrations()
        q.upsert_activity(_ride(3))
        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)

    def open_tab(self, tab: str) -> AppTest:
        at = AppTest.from_file(PAGE, default_timeout=60)
        at.session_state["dash_tab"] = tab
        at.run()
        self.assertFalse(at.exception)
        return at

    def test_history_is_worked_out_again_only_when_the_rides_change(self):
        from metrics import analysis
        real, calls = analysis.period_history, []
        with mock.patch.object(analysis, "period_history", lambda *a, **k: calls.append(1) or real(*a, **k)):
            at = self.open_tab("History")
            at.run()                                                   # a rerun, such as a control change
            self.assertEqual(len(calls), 1)
            q.upsert_activity(_ride(1))                                # a sync brings a new ride
            at.run()
            self.assertEqual(len(calls), 2)

    def test_the_rides_csv_is_built_on_download(self):
        from components import ride_detail
        real, calls = ride_detail.rides_frame, []
        with mock.patch.object(ride_detail, "rides_frame", lambda *a, **k: calls.append(1) or real(*a, **k)):
            self.open_tab("Rides")
        self.assertEqual(len(calls), 1)                                # the table only, not the CSV


if __name__ == "__main__":
    unittest.main()
