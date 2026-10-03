"""Tests for the pure parts of components.calendar. Run from the repo root with
venv/bin/python -m unittest tests.test_calendar -v"""
import json
import unittest
from datetime import date

from components import calendar as cal


def W(day, name="Workout", tss=60, completed=0, **kw):
    return {"date": day, "name": name, "workout_type": "Endurance", "tss_planned": tss,
            "completed": completed, "description": "", **kw}


def A(day, name="Ride", tss=60, sport="Ride", **kw):
    return {"date": day, "name": name, "sport_type": sport, "tss": tss,
            "duration_seconds": 3600, "distance_meters": 30000, **kw}


def build(workouts=(), activities=(), strength=(), races=(), today=date(2026, 10, 15),
          year=2026, month=10):
    return cal.build_month_data(year, month, list(workouts), list(activities),
                                list(strength), list(races), today)


class GridTests(unittest.TestCase):
    def test_sunday_first_month(self):
        # 2026-02-01 is a Sunday, so the grid starts on Monday 2026-01-26.
        days = build(year=2026, month=2, today=date(2026, 2, 10))
        keys = sorted(days)
        self.assertEqual(keys[0], "2026-01-26")
        self.assertEqual(date.fromisoformat(keys[0]).weekday(), 0)
        self.assertFalse(days["2026-01-26"].in_month)
        self.assertTrue(days["2026-02-01"].in_month)
        self.assertEqual(len(keys) % 7, 0)
        self.assertEqual(keys[-1], "2026-03-01")
        self.assertEqual(len(keys), 35)

    def test_six_week_month(self):
        # October 2026 starts on a Thursday and has 31 days, which spans 5 weeks;
        # August 2026 starts on a Saturday and has 31 days, which spans 6 weeks.
        days = build(year=2026, month=8, today=date(2026, 8, 10))
        self.assertEqual(len(days), 42)
        self.assertFalse(days["2026-09-06"].in_month)
        self.assertTrue(days["2026-08-31"].in_month)

    def test_every_grid_date_present_and_flagged(self):
        days = build()
        self.assertEqual(len(days), 35)
        self.assertEqual(sum(d.in_month for d in days.values()), 31)

    def test_empty_inputs(self):
        days = build()
        self.assertTrue(all(d.status in ("rest",) for d in days.values()))
        self.assertTrue(all(d.planned_tss == 0 and d.actual_tss == 0 for d in days.values()))


class StatusTests(unittest.TestCase):
    TODAY = date(2026, 10, 15)

    def status(self, day, **kw):
        return build(today=self.TODAY, **kw)[day].status

    def test_done(self):
        self.assertEqual(self.status("2026-10-05", workouts=[W("2026-10-05", tss=60)],
                                     activities=[A("2026-10-05", tss=65)]), "done")

    def test_short(self):
        self.assertEqual(self.status("2026-10-05", workouts=[W("2026-10-05", tss=100)],
                                     activities=[A("2026-10-05", tss=60)]), "short")

    def test_exactly_seventy_percent_is_done(self):
        self.assertEqual(self.status("2026-10-05", workouts=[W("2026-10-05", tss=100)],
                                     activities=[A("2026-10-05", tss=70)]), "done")

    def test_missed(self):
        self.assertEqual(self.status("2026-10-05", workouts=[W("2026-10-05")]), "missed")

    def test_extra(self):
        self.assertEqual(self.status("2026-10-05", activities=[A("2026-10-05")]), "extra")

    def test_rest(self):
        self.assertEqual(self.status("2026-10-05"), "rest")
        self.assertEqual(self.status("2026-10-25"), "rest")

    def test_future_plan_is_planned(self):
        self.assertEqual(self.status("2026-10-25", workouts=[W("2026-10-25")]), "planned")

    def test_today_with_plan_and_no_ride_is_planned(self):
        self.assertEqual(self.status("2026-10-15", workouts=[W("2026-10-15")]), "planned")

    def test_today_with_plan_and_ride_is_done(self):
        self.assertEqual(self.status("2026-10-15", workouts=[W("2026-10-15", tss=60)],
                                     activities=[A("2026-10-15", tss=60)]), "done")

    def test_completed_flag_without_ride_is_done(self):
        self.assertEqual(self.status("2026-10-05", workouts=[W("2026-10-05", completed=1)]), "done")

    def test_completed_flag_beats_short(self):
        self.assertEqual(self.status("2026-10-05", workouts=[W("2026-10-05", tss=100, completed=1)],
                                     activities=[A("2026-10-05", tss=20)]), "done")

    def test_partial_completion_without_ride_is_missed(self):
        ws = [W("2026-10-05", completed=1), W("2026-10-05", name="Second")]
        self.assertEqual(self.status("2026-10-05", workouts=ws), "missed")

    def test_non_ride_activity_is_not_a_ride(self):
        days = build(activities=[A("2026-10-05", sport="Run")], today=self.TODAY)
        self.assertEqual(days["2026-10-05"].status, "rest")
        self.assertEqual(len(days["2026-10-05"].other), 1)
        self.assertEqual(days["2026-10-05"].rides, [])

    def test_multiple_rides_one_day(self):
        days = build(workouts=[W("2026-10-05", tss=100)],
                     activities=[A("2026-10-05", name="AM", tss=40), A("2026-10-05", name="PM", tss=50)],
                     today=self.TODAY)
        d = days["2026-10-05"]
        self.assertEqual(len(d.rides), 2)
        self.assertEqual(d.actual_tss, 90)
        self.assertEqual(d.planned_tss, 100)
        self.assertEqual(d.status, "done")

    def test_unknown_tss_is_not_short(self):
        self.assertEqual(self.status("2026-10-05", workouts=[W("2026-10-05", tss=100)],
                                     activities=[A("2026-10-05", tss=None)]), "done")

    def test_datetime_strings_match_by_date(self):
        days = build(activities=[A("2026-10-05T07:30:00")], today=self.TODAY)
        self.assertEqual(days["2026-10-05"].status, "extra")

    def test_dates_outside_grid_ignored(self):
        days = build(workouts=[W("2025-01-01")], activities=[A("2027-01-01")])
        self.assertTrue(all(not d.planned and not d.rides for d in days.values()))


class OverlayTests(unittest.TestCase):
    def test_strength_planned_vs_done(self):
        ex = json.dumps([{"name": "Back squat", "sets": 3}, {"name": "Plank"}])
        rows = [
            {"date": "2026-10-06", "notes": "Lower body A | Planned by AI Coach", "completed": 0,
             "duration_minutes": 45, "exercises_json": ex},
            {"date": "2026-10-07", "notes": "Upper | felt good", "completed": 1,
             "duration_minutes": 50, "exercises_json": ex},
        ]
        days = build(strength=rows)
        planned = days["2026-10-06"].strength[0]
        done = days["2026-10-07"].strength[0]
        self.assertEqual(planned["name"], "Lower body A")
        self.assertTrue(planned["planned"])
        self.assertEqual(planned["exercises"], ["Back squat", "Plank"])
        self.assertEqual(done["name"], "Upper")
        self.assertFalse(done["planned"])
        self.assertEqual(days["2026-10-06"].status, "rest")  # overlay only

    def test_strength_bad_json_and_none(self):
        rows = [{"date": "2026-10-06", "notes": None, "completed": None,
                 "duration_minutes": None, "exercises_json": "not json"},
                {"date": "2026-10-08", "notes": "Planned by AI Coach", "completed": 0,
                 "exercises_json": None}]
        days = build(strength=rows)
        s = days["2026-10-06"].strength[0]
        self.assertEqual(s["exercises"], [])
        self.assertFalse(s["planned"])
        self.assertEqual(days["2026-10-08"].strength[0]["name"], "Strength session")

    def test_race_day(self):
        race = {"date": "2026-10-18", "name": "Demo Road Race", "category": "Road",
                "distance_km": 120.0}
        days = build(races=[race])
        self.assertEqual(days["2026-10-18"].races, [race])
        self.assertEqual(days["2026-10-18"].status, "rest")

    def test_none_fields_do_not_crash(self):
        w = {"date": "2026-10-05", "name": None, "tss_planned": None, "completed": None,
             "description": None, "workout_type": None}
        a = {"date": "2026-10-05", "name": None, "sport_type": "Ride", "tss": None,
             "duration_seconds": None, "distance_meters": None, "avg_power_watts": None,
             "normalized_power": None, "avg_hr": None, "if_value": None, "zone_time_json": None}
        days = build(workouts=[w], activities=[a], today=date(2026, 10, 15))
        d = days["2026-10-05"]
        self.assertEqual(d.planned_tss, 0)
        self.assertEqual(d.actual_tss, 0)
        self.assertIsInstance(cal.day_tooltip(d), str)
        payload = cal.build_payload(days, None, date(2026, 10, 15))
        self.assertEqual(len(payload["days"]), 35)


class TooltipTests(unittest.TestCase):
    def test_script_and_template_strings_are_escaped(self):
        evil = "<script>alert(1)</script> %{x}"
        days = build(
            workouts=[W("2026-10-05", name=evil, description=evil, tss=80)],
            activities=[A("2026-10-05", name=evil, tss=70)],
            strength=[{"date": "2026-10-05", "notes": evil + " | Planned by AI Coach", "completed": 0,
                       "exercises_json": json.dumps([{"name": evil}])}],
            races=[{"date": "2026-10-05", "name": evil, "category": evil, "distance_km": 10}],
            today=date(2026, 10, 15))
        tip = cal.day_tooltip(days["2026-10-05"])
        self.assertNotIn("<script", tip)
        self.assertIn("&lt;script&gt;", tip)
        self.assertIn("%{x}", tip)
        payload = cal.build_payload(days, "2026-10-05", date(2026, 10, 15))
        day = next(d for d in payload["days"] if d["date"] == "2026-10-05")
        self.assertNotIn("<script", day["tip"])
        self.assertIn("%{x}", day["tip"])
        # Chip labels are plain text (the grid sets them with textContent) and are cut short.
        for chip in day["chips"]:
            self.assertLessEqual(len(chip["label"]), 22)

    def test_tooltip_sections(self):
        days = build(
            workouts=[W("2026-10-05", name="Threshold 4x8", tss=90, description="Hard day")],
            activities=[A("2026-10-05", name="Morning ride", tss=70, avg_power_watts=200,
                          normalized_power=215, if_value=0.82)],
            today=date(2026, 10, 15))
        tip = cal.day_tooltip(days["2026-10-05"])
        for needle in ("Mon 5 Oct 2026", "(Done)", "<b>Planned</b>", "Threshold 4x8",
                       "90 TSS", "<b>Done</b>", "Morning ride", "1:00", "30.0 km", "200 W avg",
                       "NP 215", "IF 0.82", "Planned 90 TSS, Actual 70 TSS (78%)"):
            self.assertIn(needle, tip)

    def test_long_description_truncated(self):
        tip = cal.day_tooltip(build(workouts=[W("2026-10-20", description="word " * 100)])["2026-10-20"])
        self.assertIn("…", tip)

    def test_empty_day_tooltip(self):
        self.assertIn("Nothing planned or recorded", cal.day_tooltip(build()["2026-10-05"]))

    def test_strength_tooltip_first_four_exercises(self):
        ex = json.dumps([{"name": f"Ex{i}"} for i in range(6)])
        days = build(strength=[{"date": "2026-10-06", "notes": "Legs | Planned by AI Coach",
                                "completed": 0, "exercises_json": ex}])
        tip = cal.day_tooltip(days["2026-10-06"])
        self.assertIn("Strength planned", tip)
        self.assertIn("Ex3", tip)
        self.assertNotIn("Ex4", tip)


class PayloadTests(unittest.TestCase):
    TODAY = date(2026, 10, 15)

    def day(self, payload, iso):
        return next(d for d in payload["days"] if d["date"] == iso)

    def test_structure(self):
        days = build()
        payload = cal.build_payload(days, "2026-10-05", self.TODAY)
        self.assertEqual([d["date"] for d in payload["days"]], sorted(days))
        self.assertEqual(payload["selected"], "2026-10-05")
        self.assertEqual(payload["weekdays"][0], "Mon")
        json.dumps(payload)   # must be JSON safe

    def test_only_upcoming_unfinished_planned_items_can_be_dragged(self):
        days = build(
            workouts=[W("2026-10-05", name="Past", id=1), W("2026-10-20", name="Soon", id=2),
                      W("2026-10-21", name="Done early", id=3, completed=1)],
            strength=[{"id": 7, "date": "2026-10-22", "notes": "Legs | Planned by AI Coach",
                       "completed": 0, "exercises_json": "[]"},
                      {"id": 8, "date": "2026-10-23", "notes": "Upper", "completed": 1,
                       "exercises_json": "[]"}],
            activities=[A("2026-10-16", id=9)], today=self.TODAY)
        p = cal.build_payload(days, None, self.TODAY)
        locked = lambda iso: {(c["kind"], c["id"]): c["locked"] for c in self.day(p, iso)["chips"]}
        self.assertEqual(locked("2026-10-05"), {("ride", 1): True})
        self.assertEqual(locked("2026-10-20"), {("ride", 2): False})
        self.assertEqual(locked("2026-10-21"), {("ride", 3): True})
        self.assertEqual(locked("2026-10-22"), {("strength", 7): False})
        self.assertEqual(locked("2026-10-23"), {("strength", 8): True})
        self.assertEqual(locked("2026-10-16"), {("done", 9): True})

    def test_today_is_draggable_and_marked(self):
        days = build(workouts=[W("2026-10-15", id=4)], today=self.TODAY)
        d = self.day(cal.build_payload(days, None, self.TODAY), "2026-10-15")
        self.assertTrue(d["today"])
        self.assertFalse(d["past"])
        self.assertFalse(d["chips"][0]["locked"])

    def test_chip_overflow(self):
        days = build(workouts=[W("2026-10-20", id=i) for i in range(5)], today=self.TODAY)
        d = self.day(cal.build_payload(days, None, self.TODAY), "2026-10-20")
        self.assertEqual(len(d["chips"]), cal.MAX_CHIPS)
        self.assertEqual(d["more"], 2)

    def test_race_name_is_passed_for_the_bar(self):
        days = build(races=[{"date": "2026-10-18", "name": "Crit"}], today=self.TODAY)
        self.assertEqual(self.day(cal.build_payload(days, None, self.TODAY), "2026-10-18")["race"], "Crit")

    def test_month_totals(self):
        today = date(2026, 10, 15)
        days = build(workouts=[W("2026-10-05", tss=100), W("2026-10-20", tss=50)],
                     activities=[A("2026-10-05", tss=80), A("2026-09-30", tss=40)], today=today)
        t = cal.month_totals(days, today)
        self.assertEqual(t["plan"], 150)
        self.assertEqual(t["plan_to_date"], 100)
        self.assertEqual(t["actual"], 80)   # Sept 30 is outside the month
        self.assertEqual(t["rides"], 1)


if __name__ == "__main__":
    unittest.main()
