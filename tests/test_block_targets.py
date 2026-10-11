"""The block generator reaches the fitness it promises, ramps gently and tapers sensibly.
Run with venv/bin/python -m unittest tests.test_block_targets -v"""
import itertools
import unittest
from datetime import date, timedelta
from unittest import mock

import coach_tools
import planning
from metrics.training_load import CTL_ALPHA

START = date(2026, 10, 12)          # a Monday
WEDNESDAY = START + timedelta(days=2)

# 20 plans across fitness, targets, lengths and riding days.
CASES = list(itertools.product(
    [(40, 55), (60, 70), (75, 90), (75, 85), (90, 100)],
    [8, 16],
    [None, "Tue,Wed,Thu,Sat,Sun"],
))


def daily_ctl(workouts, ctl, start, race):
    """CTL at the end of each day from start to the day before the race."""
    load = {}
    for w in workouts:
        load[w["date"]] = load.get(w["date"], 0) + w["tss_planned"]
    out, day = {}, start
    while day < race:
        ctl += (load.get(day.isoformat(), 0) - ctl) * CTL_ALPHA
        out[day] = ctl
        day += timedelta(days=1)
    return out


class TargetTests(unittest.TestCase):
    def test_twenty_plans_reach_the_target_or_say_they_cannot(self):
        for (cur, tgt), weeks, days in CASES:
            with self.subTest(cur=cur, tgt=tgt, weeks=weeks, days=days):
                race = START + timedelta(weeks=weeks)
                block = planning.plan_block(cur, tgt, race, "Threshold", START, available_days=days)
                o, plan = block["outlook"], block["workouts"]
                series = daily_ctl(plan, cur, START, race)
                taper = min(date.fromisoformat(w["date"]) for w in plan if w["phase"] == planning.TAPER_LABEL)
                peak = max(v for d, v in series.items() if d < taper)
                self.assertAlmostEqual(peak, o["peak_ctl"], delta=0.1)
                if o["reachable"]:
                    self.assertLessEqual(abs(peak - tgt), planning.REACH_MARGIN)
                else:
                    self.assertLess(peak, tgt - planning.REACH_MARGIN)
                    self.assertEqual(o["ramp_per_week"], planning.MAX_RAMP)
                # The climb never runs faster than the cap (a little slack for uneven days).
                for wk in range(weeks):
                    a, b = START + timedelta(weeks=wk) - timedelta(days=1), START + timedelta(weeks=wk, days=6)
                    gain = series.get(b, 0) - series.get(a, cur)
                    self.assertLessEqual(gain, planning.MAX_RAMP + 1.0, f"week {wk + 1}")

    def test_the_old_shortfall_is_gone(self):
        o = planning.plan_block(75, 90, START + timedelta(weeks=16), "Threshold", START)["outlook"]
        self.assertTrue(o["reachable"])
        self.assertGreaterEqual(o["peak_ctl"], 88)
        self.assertGreater(o["race_day_ctl"], 75)   # fresher than at the start, and fitter

    def test_an_unreachable_target_is_flagged(self):
        o = planning.plan_block(40, 80, START + timedelta(weeks=6), "Threshold", START)["outlook"]
        self.assertFalse(o["reachable"])
        self.assertLess(o["peak_ctl"], 70)

    def test_a_lower_target_is_approached_gently(self):
        plan = planning.plan_block(75, 50, START + timedelta(weeks=10), "Endurance", START)["workouts"]
        series = daily_ctl(plan, 75, START, START + timedelta(weeks=8))
        self.assertGreaterEqual(series[START + timedelta(days=6)], 75 - planning.MAX_RAMP - 1)


class TaperTests(unittest.TestCase):
    def test_the_taper_has_no_races_and_the_last_two_days_are_easy(self):
        for (cur, tgt), weeks, days in CASES:
            with self.subTest(cur=cur, tgt=tgt, weeks=weeks, days=days):
                race = START + timedelta(weeks=weeks) + timedelta(days=3)    # a Thursday race too
                plan = planning.generate_block(cur, tgt, race, "Threshold", START, available_days=days)
                taper = [w for w in plan if w["phase"] == planning.TAPER_LABEL]
                self.assertTrue(taper)
                self.assertFalse([w for w in taper if w["workout_type"] == "Race"])
                for w in plan:
                    to_race = (race - date.fromisoformat(w["date"])).days
                    self.assertGreater(to_race, 0)
                    if to_race <= 2:
                        self.assertLessEqual(w["tss_planned"], 60)
                        self.assertNotIn(w["workout_type"], planning.HARD_TYPES)
                    if to_race <= 7 and w["workout_type"] in planning.HARD_TYPES:
                        self.assertLessEqual(w["tss_planned"], planning.FINAL_WEEK_HARD_MAX)

    def test_the_day_before_the_race_is_openers(self):
        race = START + timedelta(weeks=8, days=6)                # a Sunday race
        plan = planning.generate_block(75, 85, race, "Threshold", START)
        eve = [w for w in plan if w["date"] == (race - timedelta(days=1)).isoformat()]
        self.assertEqual([w["name"] for w in eve], ["(Taper) Openers"])
        self.assertEqual(eve[0]["purpose"], planning.OPENERS_PURPOSE)


class WeekdayTests(unittest.TestCase):
    def test_a_wednesday_start_keeps_the_long_ride_on_saturday(self):
        plan = planning.generate_block(75, 90, WEDNESDAY + timedelta(weeks=12), "Threshold", WEDNESDAY)
        long_days = {date.fromisoformat(w["date"]).weekday() for w in plan if w["workout_type"] == "Long Ride"}
        self.assertEqual(long_days, {5})


class CoachToolTests(unittest.TestCase):
    def test_the_tool_returns_the_outlook(self):
        args = {"target_ctl": 90, "race_date": (date.today() + timedelta(weeks=16)).isoformat(),
                "phase_focus": "Threshold"}
        with mock.patch.object(coach_tools, "get_current_metrics", return_value={"ctl": 75}), \
                mock.patch.object(coach_tools, "get_setting", return_value=""):
            out = coach_tools._generate_block(args)
        self.assertTrue(out["workouts"])
        self.assertTrue(out["outlook"]["reachable"])
        self.assertEqual(out["outlook"]["max_ramp_per_week"], planning.MAX_RAMP)


if __name__ == "__main__":
    unittest.main()


class SweetSpotTemplateTests(unittest.TestCase):
    def test_base_blocks_have_a_weekly_sweet_spot_with_recipe_steps(self):
        plan = planning.generate_block(60, 70, START + timedelta(weeks=10), "Endurance", START)
        ss = [w for w in plan if w["workout_type"] == "Sweet Spot"]
        self.assertTrue(ss)
        self.assertEqual({date.fromisoformat(w["date"]).weekday() for w in ss}, {2})     # Wednesdays
        self.assertTrue(all("88 to 93% FTP" in w["description"] for w in ss if w["tss_planned"] >= 40))
