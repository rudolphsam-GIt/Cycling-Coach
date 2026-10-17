"""
Two small fixes. The taper planner's "3 or fewer days" note shows at 3 days too, and clearing Age in
Settings clears the stored birth year.
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

PAGES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pages")


class SmallFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db")),
                  mock.patch.object(st, "page_link")):          # links need the whole app's navigation
            p.start()
            self.addCleanup(p.stop)
        schema.run_migrations()

    def test_a_race_three_days_out_gets_the_rest_and_openers_note(self):
        q.add_race({"name": "Saturday crit", "date": (date.today() + timedelta(days=3)).isoformat(),
                    "distance_km": 40, "elevation_gain_meters": 100, "category": "B",
                    "target_time_seconds": None, "notes": ""})
        at = AppTest.from_file(os.path.join(PAGES, "03_Race_Prep.py"), default_timeout=60).run()
        self.assertFalse(at.exception)
        self.assertTrue(any("3 or fewer days" in w.value for w in at.warning))

    def test_clearing_age_clears_the_birth_year(self):
        q.set_setting("birth_year", date.today().year - 40)
        at = AppTest.from_file(os.path.join(PAGES, "07_Settings.py"), default_timeout=60).run()
        self.assertFalse(at.exception)
        age = next(n for n in at.number_input if n.label == "Age")
        self.assertEqual(age.value, 40)
        age.set_value(None).run()                     # the box starts empty, so None is what a clear sends
        self.assertIsNone(next(n for n in at.number_input if n.label == "Age").value)
        next(b for b in at.button if b.label == "Save profile").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(q.get_setting("birth_year", ""), "")

        q.set_setting("birth_year", date.today().year - 46)            # the stored year changes later
        at.run()
        self.assertEqual(next(n for n in at.number_input if n.label == "Age").value, 46)

    def test_the_birth_year_rule(self):
        from metrics.explain import birth_year_for
        today = date(2026, 10, 16)
        self.assertEqual(birth_year_for(40, today), 1986)
        self.assertEqual(birth_year_for(None, today), "")


if __name__ == "__main__":
    unittest.main()
