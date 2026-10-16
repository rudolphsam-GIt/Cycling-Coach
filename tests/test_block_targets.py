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


    def test_a_saturday_race_gets_openers_on_the_rest_day_before(self):
        race = START + timedelta(weeks=7, days=5)                # a Saturday race, Friday rests
        plan = planning.generate_block(60, 70, race, "Endurance", START)
        eve = [w for w in plan if w["date"] == (race - timedelta(days=1)).isoformat()]
        self.assertEqual([w["name"] for w in eve], ["(Taper) Openers"])

    def test_openers_respect_the_days_the_athlete_can_ride(self):
        race = START + timedelta(weeks=7, days=5)                # Saturday, and Friday is not a riding day
        plan = planning.generate_block(60, 70, race, "Endurance", START, available_days="Tue,Thu,Sat")
        self.assertFalse([w for w in plan if w["date"] == (race - timedelta(days=1)).isoformat()])

    def test_openers_keep_race_week_within_the_riding_days(self):
        race = START + timedelta(weeks=7, days=5)
        plan = planning.generate_block(60, 70, race, "Endurance", START, days_per_week=3)
        last = [w for w in plan if w["week_number"] == max(w["week_number"] for w in plan)]
        self.assertLessEqual(len(last), 3)
        self.assertEqual(last[-1]["name"], "(Taper) Openers")

    def test_a_race_this_week_is_all_taper(self):
        for days_out in range(1, 8):
            with self.subTest(days_out=days_out):
                race = START + timedelta(days=days_out)
                plan = planning.generate_block(60, 70, race, "Endurance", START)
                self.assertTrue(all(w["phase"] == planning.TAPER_LABEL for w in plan))
                for w in plan:
                    if w["workout_type"] in planning.HARD_TYPES:
                        self.assertLessEqual(w["tss_planned"], planning.FINAL_WEEK_HARD_MAX)
                if days_out > 1:
                    self.assertEqual(plan[-1]["name"], "(Taper) Openers")

    def test_the_taper_is_the_last_days_before_the_race(self):
        for days_out in (8, 10, 13, 30, 45, 60):
            with self.subTest(days_out=days_out):
                race = START + timedelta(days=days_out)
                plan = planning.generate_block(60, 70, race, "Endurance", START)
                taper_days = 14 if -(-days_out // 7) >= 6 else 7
                for w in plan:
                    to_race = (race - date.fromisoformat(w["date"])).days
                    self.assertEqual(w["phase"] == planning.TAPER_LABEL, to_race <= taper_days, w)
                    self.assertGreaterEqual(date.fromisoformat(w["date"]), START)


class WeekCountTests(unittest.TestCase):
    def test_the_page_count_matches_the_block(self):
        for days_out in (1, 6, 7, 8, 45, 70):
            with self.subTest(days_out=days_out):
                race = START + timedelta(days=days_out)
                plan = planning.generate_block(60, 70, race, "Endurance", START)
                self.assertEqual(planning.weeks_to_race(START, race), max(w["week_number"] for w in plan))


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


def weekly_tss(workouts):
    out = {}
    for w in workouts:
        out[w["week_number"]] = out.get(w["week_number"], 0) + w["tss_planned"]
    return [out[k] for k in sorted(out)]


class NoRaceBlockTests(unittest.TestCase):
    """Quick Generate with no race: no taper, and fitness ends where the athlete asked."""

    def block(self, cur, tgt, weeks, days="Mon,Tue,Wed,Thu,Fri,Sat,Sun", start=START):
        end = start + timedelta(weeks=weeks)
        return planning.plan_block(cur, tgt, end, "Endurance", start, available_days=days, taper=False), end

    def test_no_taper_and_no_openers(self):
        out, end = self.block(82, 82, 8)
        self.assertTrue(out["workouts"])
        self.assertFalse(any(w["phase"] == planning.TAPER_LABEL for w in out["workouts"]))
        self.assertFalse(any("(Taper)" in w["name"] or planning.workout_recipes.OPENERS_NAME in w["name"]
                             for w in out["workouts"]))
        self.assertTrue(all(START.isoformat() <= w["date"] < end.isoformat() for w in out["workouts"]))
        self.assertEqual(max(w["week_number"] for w in out["workouts"]), 8)

    def test_holding_fitness_ends_at_todays_fitness(self):
        for cur, weeks in ((82, 8), (82, 12), (40, 8)):
            out, _ = self.block(cur, cur, weeks)
            self.assertAlmostEqual(out["outlook"]["race_day_ctl"], cur, delta=planning.REACH_MARGIN)

    def test_building_and_easing_land_on_the_target(self):
        for cur, tgt in ((82, 90), (40, 55), (82, 70), (82, 60)):
            out, _ = self.block(cur, tgt, 8)
            self.assertAlmostEqual(out["outlook"]["race_day_ctl"], tgt, delta=planning.REACH_MARGIN, msg=(cur, tgt))

    def test_lighter_weeks_but_not_when_easing_down(self):
        held = weekly_tss(self.block(82, 82, 8)[0]["workouts"])
        self.assertLess(held[3], 0.75 * held[2])                 # week 4 is lighter
        eased = self.block(82, 70, 8)[0]["workouts"]
        self.assertFalse(any("(Recovery)" in w["name"] for w in eased))

    def test_climb_back_after_a_lighter_week_is_spread_out(self):
        for cur, tgt in ((82, 82), (40, 40), (82, 90)):
            weeks = weekly_tss(self.block(cur, tgt, 12)[0]["workouts"])
            for prev, wk in ((2, 4), (6, 8)):                    # the week after a lighter week, against the last normal one
                self.assertLessEqual(weeks[wk], weeks[prev] * planning.BOUNCE_BACK_MAX + 15, msg=(cur, tgt, weeks))

    def test_target_range_holds_fitness_by_default_with_no_race(self):
        lo, hi, default = planning.target_ctl_range(82, race=False)
        self.assertEqual(default, 82)
        self.assertLess(lo, 82)
        self.assertGreater(hi, 82)
        self.assertEqual(planning.target_ctl_range(0, race=False)[2], 20)
