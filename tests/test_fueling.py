"""
Carbs during a race. The rider picks the number, and the app suggests a starting point from
knowledge/nutrition.md: nothing under 45 minutes, optional to 75, 30 to 60 g an hour to 2 hours,
60 to 90 g an hour beyond. Feeds come every 20 minutes, each a third of the hourly amount.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from streamlit.testing.v1 import AppTest

from db import schema
from metrics import fueling

PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pages", "03_Race_Prep.py")


class SuggestTests(unittest.TestCase):
    def test_the_starting_point_follows_the_race_length(self):
        self.assertEqual(fueling.suggest(0.5)["g_per_h"], 0)          # 30 min, water only
        self.assertEqual(fueling.suggest(1.0)["g_per_h"], 0)          # a 60 min crit, optional
        self.assertEqual(fueling.suggest(1.5)["g_per_h"], 60)
        self.assertIn("30 to 60", fueling.suggest(1.5)["range"])
        self.assertIn("60 to 90", fueling.suggest(3.0)["range"])
        self.assertEqual(fueling.suggest(3.0)["g_per_h"], 60)         # 90 only after practice

    def test_feeds_every_20_minutes_add_up_to_the_hourly_rate(self):
        self.assertEqual(fueling.feeds(2.0, 60), [(20, 20.0), (40, 20.0), (60, 20.0), (80, 20.0), (100, 20.0)])
        self.assertEqual(fueling.feeds(1.0, 0), [])

    def test_notes_for_high_intakes(self):
        self.assertEqual(fueling.notes(60), [])
        self.assertTrue(any("fructose" in n for n in fueling.notes(75)))
        self.assertTrue(any("experimental" in n for n in fueling.notes(100)))


class PacingTabTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        schema.run_migrations()

    def test_the_rider_sets_the_carbs_and_the_plan_follows(self):
        at = AppTest.from_file(PAGE, default_timeout=60).run()
        next(n for n in at.number_input if n.label == "Target time (hours)").set_value(3).run()
        next(n for n in at.number_input if n.label == "Target time (minutes)").set_value(0).run()
        carbs = next(n for n in at.number_input if n.label == "Carbs per hour (g)")
        self.assertEqual(carbs.value, 60)                             # the suggestion for 3 hours
        carbs.set_value(90).run()
        next(b for b in at.button if b.label == "Calculate Pacing Plan").click().run()
        self.assertFalse(at.exception)
        plan = at.dataframe[-1].value
        self.assertIn("30 g carbs + water", list(plan["Action"]))      # 90 g an hour, a third per feed
        self.assertTrue(any("fructose" in c.value for c in at.caption))


if __name__ == "__main__":
    unittest.main()
