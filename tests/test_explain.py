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


class AgeTests(unittest.TestCase):
    def test_age_from_birth_year(self):
        today = date(2026, 10, 2)
        self.assertEqual(ex.age_from_birth_year(1986, today), 40)
        self.assertIsNone(ex.age_from_birth_year(None, today))
        self.assertIsNone(ex.age_from_birth_year("", today))
        self.assertIsNone(ex.age_from_birth_year("abc", today))
        self.assertIsNone(ex.age_from_birth_year(2026, today))      # newborn, not believable
        self.assertIsNone(ex.age_from_birth_year(1900, today))

    def test_age_factor_shape(self):
        self.assertEqual(ex.age_factor(None), 1.0)
        self.assertEqual(ex.age_factor(0), 1.0)
        self.assertEqual(ex.age_factor(16), ex.YOUTH_FACTOR)
        self.assertEqual([ex.age_factor(a) for a in (18, 25, 35)], [1.0, 1.0, 1.0])
        self.assertAlmostEqual(ex.age_factor(45), 0.92)
        self.assertAlmostEqual(ex.age_factor(60), 0.80)
        factors = [ex.age_factor(a) for a in range(35, 96)]
        self.assertEqual(factors, sorted(factors, reverse=True))
        self.assertEqual(ex.age_factor(95), ex.FTP_AGE_FLOOR)

    def test_heart_rate_estimates(self):
        self.assertEqual(ex.max_hr_from_age(40), 180)
        self.assertEqual(ex.lthr_from_age(40), 160)
        self.assertGreater(ex.lthr_from_age(25), ex.lthr_from_age(60))

    def test_older_riders_start_lower_and_blank_age_changes_nothing(self):
        def start(age):
            return ex.starting_ftp_range(70, "I ride, but without a plan", ex.DEFAULT_ACTIVITY, "man", age)
        self.assertEqual(start(None), start(30))
        self.assertLess(start(55)["start"], start(45)["start"])
        self.assertLess(start(45)["start"], start(30)["start"])
        for a in (16, 30, 50, 70, 90):
            r = start(a)
            self.assertTrue(r["low"] <= r["start"] <= r["high"])
            self.assertTrue(all(r[k] % 5 == 0 for k in ("low", "high", "start")))

    def test_age_and_sex_combine(self):
        young_man = ex.starting_ftp_range(70, "New to cycling", ex.DEFAULT_ACTIVITY, "man", 30)["start"]
        older_woman = ex.starting_ftp_range(70, "New to cycling", ex.DEFAULT_ACTIVITY, "woman", 55)["start"]
        self.assertLess(older_woman, young_man)
        self.assertGreaterEqual(ex.starting_ftp_range(40, "New to cycling", "Mostly inactive", "woman", 80)["low_wkg"], 0.9)


class StartingFtpTests(unittest.TestCase):
    def rng(self, rider=None, activity=None, sex=None, kg=70):
        return ex.starting_ftp_range(kg, rider, activity, sex)

    def test_range_is_ordered_and_rounded_to_five(self):
        for rider in ex.RIDER_TYPES:
            for activity in ex.ACTIVITY_LEVEL:
                for sex in ex.GENDER_FACTOR:
                    r = self.rng(rider, activity, sex)
                    self.assertLess(r["low"], r["high"])
                    self.assertTrue(r["low"] <= r["start"] <= r["high"])
                    for k in ("low", "high", "start"):
                        self.assertEqual(r[k] % 5, 0)

    def test_more_experience_and_more_activity_raise_the_start(self):
        starts = [self.rng(t)["start"] for t in ex.RIDER_TYPES]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(len(set(starts)), len(starts))
        act = [self.rng(activity=a)["start"] for a in ex.ACTIVITY_LEVEL]
        self.assertEqual(act, sorted(act))
        self.assertLess(act[0], act[-1])

    def test_women_start_lower_and_unspecified_sits_between(self):
        for rider in ex.RIDER_TYPES:
            man, woman, mid = (self.rng(rider, sex=s)["start"] for s in ("man", "woman", "unspecified"))
            self.assertLess(woman, mid)
            self.assertLess(mid, man)
            self.assertAlmostEqual(woman / man, ex.GENDER_FACTOR["woman"], delta=0.06)

    def test_the_factor_matches_the_published_tables(self):
        from metrics.analysis import PROFILE_TABLES
        men, women = PROFILE_TABLES["Men"], PROFILE_TABLES["Women"]
        ratios = [women[d][i] / men[d][i] for d in men for i in range(9)]
        self.assertGreaterEqual(min(ratios), 0.78)
        self.assertLessEqual(max(ratios), 0.92)
        self.assertGreater(ex.GENDER_FACTOR["woman"], min(ratios))
        self.assertLess(ex.GENDER_FACTOR["woman"], max(ratios))

    def test_scales_with_weight_and_has_a_sane_floor(self):
        light, heavy = self.rng(kg=55), self.rng(kg=90)
        self.assertLess(light["start"], heavy["start"])
        floor = self.rng("New to cycling", "Mostly inactive", "woman")
        self.assertGreaterEqual(floor["low_wkg"], 0.9)
        self.assertEqual(self.rng(None, None, None)["start_wkg"],
                         self.rng(ex.DEFAULT_RIDER_TYPE, ex.DEFAULT_ACTIVITY, "unspecified")["start_wkg"])

    def test_rider_types_map_to_the_apps_experience_levels(self):
        self.assertEqual([ex.experience_for(t) for t in ex.RIDER_TYPES],
                         ["New to structured training", "New to structured training",
                          "Some structured training experience", "Experienced racer"])
        self.assertEqual(ex.experience_for(None), "New to structured training")
        self.assertTrue(all(v["detail"] for v in ex.RIDER_TYPES.values()))

    def test_gender_choices_cover_everyone(self):
        self.assertEqual(set(ex.GENDER_LABELS.values()), set(ex.GENDER_FACTOR))
        self.assertEqual(list(ex.GENDER_LABELS), ["Woman", "Man", "Non-binary", "Prefer not to say"])
        self.assertEqual(ex.GENDER_PROFILE_TABLE, {"man": "Men", "woman": "Women"})
        # Non-binary riders and those who would rather not say get the middle of the two
        self.assertEqual(ex.GENDER_FACTOR["nonbinary"], ex.GENDER_FACTOR["unspecified"])
        self.assertAlmostEqual(ex.GENDER_FACTOR["nonbinary"],
                               (ex.GENDER_FACTOR["man"] + ex.GENDER_FACTOR["woman"]) / 2, places=3)
        self.assertEqual(ex.DEFAULT_GENDER, "unspecified")

    def test_every_activity_level_is_defined_in_plain_numbers(self):
        self.assertEqual(list(ex.ACTIVITY_DETAILS), list(ex.ACTIVITY_LEVEL))
        for level, text in ex.ACTIVITY_DETAILS.items():
            self.assertRegex(text, r"hour", level)                 # how much time
            self.assertRegex(text, r"session|exercise", level)      # how often
            self.assertNotIn(EM_DASH, text)
        self.assertIn(ex.DEFAULT_ACTIVITY, ex.ACTIVITY_LEVEL)
        adjustments = list(ex.ACTIVITY_LEVEL.values())
        self.assertEqual(adjustments, sorted(adjustments))          # more active, higher start

    def test_a_brand_new_rider_is_never_given_a_frightening_number(self):
        r = self.rng("New to cycling", ex.DEFAULT_ACTIVITY, "man")
        self.assertLessEqual(r["high_wkg"], 2.0)          # modest and believable, not a racer's number

    def test_reassurance_is_kind_and_has_the_numbers(self):
        text = ex.ftp_reassurance(85, 125, 105)
        for needle in ("between 85 and 125 watts", "105 W", "completely normal", "starting point"):
            self.assertIn(needle, text)
        self.assertNotIn("105 W", ex.ftp_reassurance(85, 125))
        self.assertNotIn(EM_DASH, text)

    def test_gentle_test_has_no_pass_or_fail(self):
        gentle = ex.ftp_test_workout(date(2026, 10, 8), True, gentle=True)
        plain = ex.ftp_test_workout(date(2026, 10, 8), True)
        self.assertIn("no pass or fail", gentle["purpose"])
        self.assertIn("not a race", gentle["feel"])
        self.assertNotIn("10 out of 10", gentle["feel"])
        self.assertIn("10 out of 10", plain["feel"])
        self.assertEqual(gentle["description"], plain["description"])      # same test, kinder words


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
                       "190 W", "only an estimate", "FTP test into the first week", "four weeks", "what it is for", "how it should feel"):
            self.assertIn(needle, m)

    def test_message_without_optional_parts(self):
        m = ex.first_block_message(goals=[], experience="New to structured training", hours=None,
                                   ftp=None, ftp_estimated=False)
        self.assertIn("general fitness", m)
        self.assertNotIn("hours a week", m)
        self.assertNotIn("FTP is set", m)
        self.assertNotIn("FTP test", m)
        self.assertNotIn("race", m.split("Please build")[0])


if __name__ == "__main__":
    unittest.main()
