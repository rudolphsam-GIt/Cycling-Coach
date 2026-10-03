"""Tests for metrics.plan_impact. Run with
venv/bin/python -m unittest tests.test_plan_impact -v"""
import unittest
from datetime import date

from metrics import plan_impact as pi

TODAY = date(2026, 10, 7)   # a Wednesday


class PlanTests(unittest.TestCase):
    def test_today_counts_the_plan_only_without_a_ride(self):
        w = [{"date": "2026-10-07", "tss_planned": 80}]
        self.assertEqual(pi.plan_from_rows(w, {}, TODAY)["2026-10-07"], 80)
        self.assertEqual(pi.plan_from_rows(w, {"2026-10-07": 55}, TODAY)["2026-10-07"], 55)

    def test_past_plans_are_ignored_and_actuals_kept(self):
        w = [{"date": "2026-10-05", "tss_planned": 100}, {"date": "2026-10-09", "tss_planned": 70}]
        plan = pi.plan_from_rows(w, {"2026-10-05": 40}, TODAY)
        self.assertEqual(plan["2026-10-05"], 40)
        self.assertEqual(plan["2026-10-09"], 70)

    def test_bad_values_do_not_crash(self):
        plan = pi.plan_from_rows([{"date": "2026-10-09", "tss_planned": None},
                                  {"date": None, "tss_planned": 5}], {}, TODAY)
        self.assertEqual(plan, {"2026-10-09": 0.0})

    def test_shift_and_with_change_return_copies(self):
        plan = {"2026-10-09": 90.0}
        moved = pi.shift(plan, 90, "2026-10-09", "2026-10-10")
        self.assertEqual(plan, {"2026-10-09": 90.0})
        self.assertEqual(moved, {"2026-10-09": 0.0, "2026-10-10": 90.0})
        self.assertEqual(pi.with_change(plan, remove=("2026-10-09", 90), add=("2026-10-12", 60)),
                         {"2026-10-09": 0.0, "2026-10-12": 60})


class ProjectionTests(unittest.TestCase):
    def test_matches_the_training_load_ewma(self):
        from metrics.training_load import project_future
        plan = {"2026-10-08": 100.0, "2026-10-09": 50.0}
        mine = pi.project(plan, date(2026, 10, 8), date(2026, 10, 10), 60.0, 70.0)
        ref = project_future(60.0, 70.0, plan, days_ahead=3)   # starts the day after today
        # project_future starts tomorrow relative to the real today, so compare shapes only
        self.assertEqual(len(mine), 3)
        self.assertAlmostEqual(mine[0]["ctl"], round(60 + (100 - 60) * (1 - 2.718281828 ** (-1 / 42)), 1), places=1)
        self.assertEqual(mine[0]["tsb"], -10.0)   # yesterday's 60 minus 70
        self.assertEqual(len(ref), 3)

    def test_moving_a_hard_day_closer_to_the_focus_day_lowers_form(self):
        before = {"2026-10-12": 120.0}
        after = pi.shift(before, 120, "2026-10-12", "2026-10-16")
        res = pi.impact(before, after, today=TODAY, ctl=70.0, atl=70.0, focus=date(2026, 10, 17))
        self.assertLess(res["delta"]["tsb"], 0)       # fresher before, more tired after
        self.assertGreater(res["delta"]["atl"], 0)
        self.assertEqual(res["focus"], "2026-10-17")

    def test_identical_plans_have_no_delta(self):
        plan = {"2026-10-12": 80.0}
        res = pi.impact(plan, dict(plan), today=TODAY, ctl=50.0, atl=50.0, focus=date(2026, 10, 20))
        self.assertEqual(res["delta"], {"ctl": 0.0, "atl": 0.0, "tsb": 0.0})

    def test_series_is_at_least_a_week(self):
        res = pi.impact({}, {}, today=TODAY, ctl=0, atl=0, focus=date(2026, 10, 8))
        self.assertEqual(len(res["series_after"]), 8)

    def test_focus_day_prefers_the_next_race(self):
        races = [{"date": "2026-10-01", "name": "Past"}, {"date": "2026-10-25", "name": "Next"},
                 {"date": "2027-06-01", "name": "Far"}]
        self.assertEqual(pi.focus_day(races, TODAY), (date(2026, 10, 25), "Next"))
        d, name = pi.focus_day([{"date": "2027-06-01", "name": "Far"}], TODAY)
        self.assertEqual((d, name), (date(2026, 11, 4), None))


class WarningTests(unittest.TestCase):
    END = date(2026, 10, 25)

    def test_back_to_back_hard_days(self):
        out = pi.warnings({"2026-10-08": 95, "2026-10-09": 100}, [], TODAY, self.END)
        self.assertTrue(any("back to back" in x and "95" in x and "100" in x for x in out))

    def test_hard_then_easy_is_quiet(self):
        out = pi.warnings({"2026-10-08": 95, "2026-10-09": 40}, [], TODAY, self.END)
        self.assertFalse(any("back to back" in x for x in out))

    def test_hard_day_before_a_race(self):
        out = pi.warnings({"2026-10-16": 95}, [{"date": "2026-10-17", "name": "Crit"}], TODAY, self.END)
        self.assertTrue(any("right before Crit" in x for x in out))

    def test_weekly_jump(self):
        plan = {"2026-10-12": 150.0, "2026-10-14": 150.0,       # week of 12 Oct, 300
                "2026-10-19": 200.0, "2026-10-21": 200.0}       # week of 19 Oct, 400 (+33%)
        out = pi.warnings(plan, [], TODAY, self.END)
        self.assertTrue(any("Week of Mon 19 Oct" in x and "33%" in x for x in out))

    def test_no_rest_day(self):
        plan = {f"2026-10-{d}": 40.0 for d in range(12, 19)}
        out = pi.warnings(plan, [], TODAY, self.END)
        self.assertTrue(any("No rest day in the week of Mon 12 Oct" in x for x in out))

    def test_empty_plan_has_no_warnings(self):
        self.assertEqual(pi.warnings({}, [], TODAY, self.END), [])


if __name__ == "__main__":
    unittest.main()
