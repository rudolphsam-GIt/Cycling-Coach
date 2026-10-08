"""Weight units, and where the FTP test lands in a first block.
Run with venv/bin/python -m unittest tests.test_units -v"""
import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

from db import schema, queries as q
from metrics import units


class UnitTests(unittest.TestCase):
    def test_round_trip_keeps_what_was_typed(self):
        for lb in (110, 154, 180.5, 225):
            kg = units.to_kg(lb, "lb")
            self.assertAlmostEqual(round(units.from_kg(kg, "lb"), 1), lb, delta=0.1)
        self.assertEqual(units.to_kg(70, "kg"), 70.0)
        self.assertEqual(units.from_kg(70, "kg"), 70.0)

    def test_known_conversions(self):
        self.assertAlmostEqual(units.to_kg(154, "lb"), 69.85, places=2)
        self.assertAlmostEqual(units.from_kg(100, "lb"), 220.46, places=2)

    def test_formatting(self):
        self.assertEqual(units.fmt_weight(70, "lb"), "154 lb")
        self.assertEqual(units.fmt_weight(70.5, "kg"), "70.5 kg")

    def test_help_text_uses_the_riders_unit(self):
        from metrics import explain
        self.assertIn("at 154 lb", explain.your_wkg(250, 69.85, "lb"))
        self.assertIn("at 70 kg", explain.your_wkg(250, 70, "kg"))
        self.assertIn("3.58 W/kg", explain.your_wkg(250, 69.85, "lb"))


class FtpTestPlacementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()

    def week(self, start, offsets):
        return [(start + timedelta(days=o)).isoformat() for o in offsets]

    def test_goes_on_the_first_rest_day_after_day_one(self):
        from components import ftp_help
        start = date.today() + timedelta(days=7)
        dates = self.week(start, [0, 1, 3, 5, 6])              # rest days: day 2 and day 4
        wid = ftp_help.plan_test_in_block(dates)
        w = q.get_workout(wid)
        self.assertEqual(w["date"], (start + timedelta(days=2)).isoformat())
        self.assertIn("FTP test", w["name"])
        self.assertTrue(w["purpose"] and w["feel"])

    def test_nothing_added_when_the_whole_week_is_full(self):
        from components import ftp_help
        start = date.today() + timedelta(days=7)
        self.assertIsNone(ftp_help.plan_test_in_block(self.week(start, range(7))))
        self.assertIsNone(ftp_help.plan_test_in_block([]))
        self.assertEqual(q.get_workouts("0001-01-01", "9999-12-31"), [])


class OnboardingTests(unittest.TestCase):
    def test_welcome_and_first_block_mention_the_test(self):
        from metrics import explain
        text = explain.first_block_message(goals=["x"], experience="New", hours=5, days=4, ftp=150,
                                           ftp_estimated=True)
        self.assertIn("because I do not know my real one", text)
        self.assertIn("guided 20 minute FTP test into the first week", text)
        known = explain.first_block_message(goals=["x"], experience="New", hours=5, days=4, ftp=250,
                                            ftp_estimated=False)
        self.assertNotIn("FTP test", known)

    def test_choosing_an_estimate_leaves_out_the_test(self):
        from metrics import explain
        skip = explain.first_block_message(goals=["x"], experience="New", hours=5, days=4, ftp=105,
                                           ftp_estimated=True, skip_test=True)
        self.assertIn("rather not do an FTP test", skip)
        self.assertNotIn("guided 20 minute FTP test", skip)
        self.assertIn("because I do not know my real one", skip)

    def test_the_three_ftp_choices(self):
        from components.onboarding import FTP_CHOICES
        self.assertEqual(list(FTP_CHOICES.values()), ["known", "test", "estimate"])
        self.assertTrue(list(FTP_CHOICES)[0].startswith("I know"))
        self.assertIn("happy to do a test", list(FTP_CHOICES)[1])
        self.assertIn("estimate it for me", list(FTP_CHOICES)[2])

    def test_checklist_reassures_about_the_ftp(self):
        from metrics import explain
        why = next(s["why"] for s in explain.checklist({}) if s["key"] == "ftp")
        self.assertIn("No problem", why)
        self.assertIn("FTP test", why)


if __name__ == "__main__":
    unittest.main()
