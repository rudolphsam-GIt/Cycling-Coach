"""Tests for the plain language wording in metrics.explain.
Run with venv/bin/python -m unittest tests.test_explain -v"""
import re
import unittest
from datetime import date

from metrics import explain as ex
from metrics.zones import get_power_zones

EM_DASH = "—"


def all_strings():
    for term in ex.TERMS.values():
        yield from term.values()
    yield from ex.TIPS.values()
    yield from ex.SETTINGS_HELP.values()
    yield from ex.FEEL.values()
    yield from ex.PURPOSE.values()
    for note in [*ex.PHASE_NOTES.values(), ex.TAPER_NOTE]:
        yield from note.values()


class WordingTests(unittest.TestCase):
    def test_every_term_has_the_three_parts(self):
        for key, t in ex.TERMS.items():
            self.assertTrue(t["title"] and t["what"] and t["why"], key)

    def test_no_em_dashes_anywhere(self):
        for text in all_strings():
            self.assertNotIn(EM_DASH, text)

    def test_card_has_all_sections_and_your_number_only_with_data(self):
        full = ex.card("tsb", tsb=-18, ctl=47)
        self.assertEqual([p.split(".")[0] for p in full.split("\n\n")[1:]],
                         ["**What it is", "**Why it matters", "**Your number"])
        bare = ex.card("tsb")
        self.assertNotIn("Your number", bare)
        self.assertNotIn(EM_DASH, full)

    def test_every_workout_type_has_feel_and_purpose(self):
        from db.queries import WORKOUT_TYPES
        for t in WORKOUT_TYPES:
            self.assertTrue(ex.feel_for(t), t)
            self.assertIn(t, ex.PURPOSE)
        self.assertEqual(ex.feel_for(None), ex.FEEL["Other"])


class PersonalTests(unittest.TestCase):
    def test_form_bands_match_the_banner(self):
        self.assertEqual(ex.form_state(10, 50), "fresh")
        self.assertEqual(ex.form_state(9.9, 50), "building")
        self.assertEqual(ex.form_state(10, 20), "building")      # too little fitness to call it fresh
        self.assertEqual(ex.form_state(-29.9, 50), "building")
        self.assertEqual(ex.form_state(-30, 50), "fatigued")

    def test_form_text_follows_the_state(self):
        self.assertIn("fresh", ex.your_tsb(12, 50))
        self.assertIn("very tired", ex.your_tsb(-35, 50))
        self.assertIn("normal", ex.your_tsb(-18, 47))
        self.assertIn("-18", ex.your_tsb(-18, 47))

    def test_ftp_line_uses_the_real_zone_ranges(self):
        z = get_power_zones(250)
        text = ex.your_ftp(250, 72, estimated=True)
        self.assertIn(f"{z[1]['min_watts']} to {z[1]['max_watts']} W", text)
        self.assertIn(f"{z[3]['min_watts']} to {z[3]['max_watts']} W", text)
        self.assertIn("3.47 watts per kilo", text)
        self.assertIn("estimate", text)
        self.assertNotIn("estimate", ex.your_ftp(250, 72))

    def test_tss_anchor(self):
        self.assertIn("one hour at your FTP is 100", ex.your_tss(420, 7.5))
        self.assertIn("420 TSS from 7.5 hours", ex.your_tss(420, 7.5))

    def test_missing_or_zero_data_gives_none(self):
        for fn, args in ((ex.your_ftp, {}), (ex.your_tss, {"week_tss": 0}), (ex.your_if, {}),
                         (ex.your_np, {"np": 200}), (ex.your_ctl, {}), (ex.your_atl, {}),
                         (ex.your_tsb, {}), (ex.your_ramp, {}), (ex.your_ef, {}),
                         (ex.your_peaks, {}), (ex.your_profile, {}), (ex.your_wkg, {"ftp": 250})):
            self.assertIsNone(fn(**args), fn.__name__)

    def test_intensity_bands(self):
        self.assertIn("recovery", ex.your_if(0.5))
        self.assertIn("endurance", ex.your_if(0.7))
        self.assertIn("threshold", ex.your_if(1.0))
        self.assertIn("very hard", ex.your_if(1.2))

    def test_ramp_and_fatigue_text(self):
        self.assertIn("healthy build", ex.your_ctl(47, 3))
        self.assertIn("faster than most", ex.your_ctl(47, 9))
        self.assertIn("holding steady", ex.your_ctl(47, 0.5))
        self.assertIn("rest or a lighter week", ex.your_ctl(47, -4))
        self.assertIn("a lot of tiredness", ex.your_atl(80, 50))
        self.assertIn("rested", ex.your_atl(45, 50))
        self.assertTrue(ex.your_ramp(3.1).startswith("Your fitness rose"))

    def test_peaks_line(self):
        out = ex.your_peaks({300: {"watts": 360}, 1200: 300}, 72)
        self.assertIn("5 minutes is 360 W (5.00 W/kg)", out)
        self.assertIn("20 minutes is 300 W", out)


class GoalTests(unittest.TestCase):
    def test_goal_words_become_categories(self):
        from components.onboarding import infer_goal_keys
        self.assertEqual(infer_goal_keys("Ride my first 100 mile day"), ["endurance"])
        self.assertEqual(infer_goal_keys("Lose 10 pounds and feel stronger"), ["speed", "weight_loss"])
        self.assertIn("race", infer_goal_keys("Get faster for Cat 4 road races"))
        self.assertEqual(infer_goal_keys("have fun outside"), ["general_fitness"])
        self.assertEqual(infer_goal_keys(""), ["general_fitness"])


class FtpTests(unittest.TestCase):
    TODAY = date(2026, 10, 2)

    def rows(self):
        return [{"duration_s": 1200, "watts": 280, "date": "2026-09-20", "name": "Old"},
                {"duration_s": 1200, "watts": 300, "date": "2026-09-25", "name": "Best"},
                {"duration_s": 1200, "watts": 350, "date": "2026-07-01", "name": "Too old"},
                {"duration_s": 300, "watts": 400, "date": "2026-09-30", "name": "Wrong duration"}]

    def test_suggestion_is_95_percent_of_best_recent_20_minutes(self):
        s = ex.suggest_ftp(self.rows(), self.TODAY)
        self.assertEqual((s["ftp"], s["watts"], s["name"], s["date"]), (285, 300, "Best", "2026-09-25"))

    def test_no_suggestion_without_recent_20_minute_power(self):
        self.assertIsNone(ex.suggest_ftp([], self.TODAY))
        self.assertIsNone(ex.suggest_ftp(self.rows()[2:], self.TODAY))

    def test_test_workout(self):
        w = ex.ftp_test_workout(date(2026, 10, 8), True)
        self.assertEqual((w["date"], w["workout_type"]), ("2026-10-08", "Threshold"))
        self.assertIn("95%", w["description"])
        self.assertTrue(w["purpose"] and w["feel"])
        hr = ex.ftp_test_workout(date(2026, 10, 8), False)
        self.assertIn("heart rate", hr["description"])
        self.assertNotIn(EM_DASH, w["description"] + hr["description"])


class ChecklistTests(unittest.TestCase):
    def done(self, **state):
        return {s["key"]: s["done"] for s in ex.checklist(state)}

    def test_nothing_done(self):
        self.assertFalse(any(self.done().values()))

    def test_each_step_ticks_from_its_own_data(self):
        self.assertTrue(self.done(connected=True)["connect"])
        self.assertTrue(self.done(ftp_confirmed=True)["ftp"])
        self.assertTrue(self.done(rides=1)["rides"])
        self.assertTrue(self.done(workouts=3)["block"])
        self.assertFalse(self.done(rides_since_plan=2)["week"])
        self.assertTrue(self.done(rides_since_plan=3)["week"])

    def test_steps_in_order_with_reasons(self):
        steps = ex.checklist({})
        self.assertEqual([s["key"] for s in steps], ["connect", "ftp", "rides", "block", "week"])
        self.assertTrue(all(s["why"] and s["title"] for s in steps))


class FirstBlockTests(unittest.TestCase):
    def test_message_carries_goals_hours_race_and_estimate(self):
        m = ex.first_block_message(goals=["Build endurance", "Lose weight"], experience="New to structured training",
                                   hours=6, days=4, ftp=190, ftp_estimated=True,
                                   race={"name": "Gran Fondo", "date": "2027-05-01"}, name="Sam")
        for needle in ("I'm Sam", "in my own words", "Build endurance; Lose weight", "about 6 hours a week, spread over 4 days",
                       "Gran Fondo on 2027-05-01",
                       "190 W", "only an estimate", "four weeks", "what it is for", "how it should feel"):
            self.assertIn(needle, m)

    def test_message_without_optional_parts(self):
        m = ex.first_block_message(goals=[], experience="New to structured training", hours=None,
                                   ftp=None, ftp_estimated=False)
        self.assertIn("general fitness", m)
        self.assertNotIn("hours a week", m)
        self.assertNotIn("FTP is set", m)
        self.assertNotIn("race", m.split("Please build")[0])


if __name__ == "__main__":
    unittest.main()
