"""Fixes from a review of the app on real data: distance along the ride, recovery sync status,
the FTP card, and the plan impact panel. Run with
venv/bin/python -m unittest tests.test_audit_fixes -v"""
import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

from streamlit.testing.v1 import AppTest

from components import plan_impact_ui as pui
from db import schema, queries as q
from metrics import streams as sm

TODAY = date.today()
D = lambda n: (TODAY + timedelta(days=n)).isoformat()


class DistanceAxisTests(unittest.TestCase):
    def ride(self, n=4000, speed=8.0):
        return sm.from_records([{"t": i, "speed": speed, "dist": i * speed, "power": 200} for i in range(n)])

    def test_cumulative_distance_never_goes_backwards(self):
        cum = sm.cumulative_distance({"dist": [0, 10, None, 5, 30, None]})
        self.assertEqual(cum, [0, 10, 10, 10, 30, 30])

    def test_falls_back_to_adding_up_speed_or_gives_up(self):
        self.assertEqual(sm.cumulative_distance({"speed": [5.0, None, 5.0]}), [5.0, 5.0, 10.0])
        self.assertIsNone(sm.cumulative_distance({"power": [200, 200]}))
        self.assertIsNone(sm.cumulative_distance({"dist": [None, None]}))

    def test_nice_steps(self):
        self.assertEqual([sm.nice_step(x) for x in (0.05, 0.3, 0.9, 3.3, 7, 9999)], [0.1, 0.5, 1, 5, 10, 500])

    def test_ticks_are_round_distances_in_order_with_the_second_reached(self):
        cum = sm.cumulative_distance(self.ride())
        ticks = sm.distance_ticks(cum, 0, 4000, 1609.344)
        values = [v for v, _ in ticks]
        self.assertEqual(values, sorted(values))
        self.assertTrue(all(v % 2.5 == 0 for v in values))
        for v, i in ticks:
            self.assertGreaterEqual(cum[i], v * 1609.344 - 1e-6)
            self.assertLess(cum[i - 1] if i else -1, v * 1609.344 + 1e-6)
        self.assertGreaterEqual(len(ticks), 4)

    def test_zooming_in_gives_finer_ticks_inside_the_window(self):
        cum = sm.cumulative_distance(self.ride())
        whole = sm.distance_ticks(cum, 0, 4000, 1609.344)
        zoomed = sm.distance_ticks(cum, 1000, 1600, 1609.344)
        self.assertGreater(len(zoomed), 2)
        self.assertTrue(all(1000 <= i < 1600 for _, i in zoomed))
        self.assertLess(zoomed[1][0] - zoomed[0][0], whole[1][0] - whole[0][0])

    def test_kilometers_and_edge_cases(self):
        cum = sm.cumulative_distance(self.ride())
        self.assertTrue(all(v == int(v) or v % 0.5 == 0 for v, _ in sm.distance_ticks(cum, 0, 4000, 1000.0)))
        self.assertEqual(sm.distance_ticks(None, 0, 10, 1000.0), [])
        self.assertEqual(sm.distance_ticks([0.0] * 100, 0, 100, 1000.0), [])        # not moving
        self.assertEqual(sm.distance_ticks(cum, 5, 6, 1000.0), [])                   # too short a window

    def test_hover_text_has_time_and_distance(self):
        from components import ride_analysis as ra
        cum = sm.cumulative_distance(self.ride())
        self.assertIn("mi", ra.hover_label(600, cum, "mi"))
        self.assertIn("3.0 km", ra.hover_label(375, cum, "km"))
        self.assertEqual(ra.hover_label(30, None, "mi"), "0:30")


class PlanImpactTests(unittest.TestCase):
    def state(self, workouts):
        return {"today": TODAY, "workouts": workouts, "focus": TODAY + timedelta(days=28)}

    def test_only_planned_rides_from_today_count_as_a_plan(self):
        self.assertFalse(pui._has_plan(self.state([])))
        self.assertFalse(pui._has_plan(self.state([{"date": D(-1), "tss_planned": 90}])))      # yesterday
        self.assertFalse(pui._has_plan(self.state([{"date": D(3), "tss_planned": 0}])))
        self.assertTrue(pui._has_plan(self.state([{"date": D(3), "tss_planned": 60}])))
        self.assertTrue(pui._has_plan(self.state([{"date": D(0), "tss_planned": 60}])))

    def test_the_end_note_follows_planned_rides_not_rides_already_ridden(self):
        st = self.state([{"date": D(5), "tss_planned": 60}])
        note = pui.plan_end_note({D(0): 224.0}, st)                  # today's ridden TSS must not count
        self.assertIn("planned rides end", note)
        self.assertIsNone(pui.plan_end_note({}, self.state([{"date": D(25), "tss_planned": 60}])))
        self.assertIsNone(pui.plan_end_note({}, self.state([])))


class DbCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()


class RecoveryStatusTests(DbCase):
    def test_no_data_a_fresh_day_and_a_stale_one(self):
        import auth.garmin as g
        self.assertEqual(g.recovery_status(TODAY), {"last_date": None, "days_old": None, "stale": True})
        q.upsert_recovery(D(-1), {"sleep_hours": 7.5})
        self.assertFalse(g.recovery_status(TODAY)["stale"])                 # yesterday is current
        q.upsert_recovery(D(-5), {"sleep_hours": 7.0})
        self.assertEqual(g.recovery_status(TODAY)["last_date"], D(-1))      # the newest row wins
        self.assertTrue(g.recovery_status(TODAY + timedelta(days=3))["stale"])

    def test_latest_recovery(self):
        self.assertIsNone(q.get_latest_recovery())
        q.upsert_recovery(D(-4), {"sleep_hours": 6.5})
        q.upsert_recovery(D(-2), {"sleep_hours": 8.0})
        self.assertEqual(q.get_latest_recovery()["date"], D(-2))


def _ftp_app():
    import streamlit as st
    from components import ftp_help
    st.session_state.setdefault("_n", 0)
    ftp_help.render("t", snoozable=st.session_state.get("snoozable", True),
                    show_lower=st.session_state.get("show_lower", False))


class FtpCardTests(DbCase):
    def setUp(self):
        super().setUp()
        q.set_setting("ftp_watts", 330)
        q.set_setting("ftp_estimated", "0")
        ride = q.upsert_activity({
            "source": "garmin", "external_id": "garmin_1", "date": D(-10), "name": "Hard ride",
            "sport_type": "ride", "duration_seconds": 3600, "elapsed_seconds": 3700, "distance_meters": 30000,
            "elevation_gain_meters": 0, "avg_power_watts": 250, "avg_hr": 150, "max_hr": 180,
            "normalized_power": 260, "tss": 80, "if_value": 0.8, "raw_json": "{}"})
        self.ride = ride

    def peak(self, watts):
        q.save_peaks(self.ride, {1200: watts})

    def run_app(self, **state):
        at = AppTest.from_function(_ftp_app, default_timeout=30)
        for k, v in state.items():
            at.session_state[k] = v
        return at.run()

    def labels(self, at):
        return [b.label for b in at.button]

    def test_a_lower_suggestion_does_not_nag_on_today_but_shows_in_settings(self):
        self.peak(305)                                              # 95% is 290, below the 330 set
        self.assertEqual(self.labels(self.run_app()), [])           # nothing on Today
        shown = self.labels(self.run_app(show_lower=True, snoozable=False))
        self.assertIn("Use 290 W", shown)
        self.assertIn("Plan an FTP test", shown)
        self.assertNotIn("Not now", shown)                          # Settings has no snooze

    def test_a_higher_suggestion_is_offered_with_every_option(self):
        self.peak(360)                                              # 95% is 342, above 330
        labels = self.labels(self.run_app())
        for want in ("Use 342 W", "Plan an FTP test", "Not now"):
            self.assertIn(want, labels)

    def test_not_now_hides_the_card_for_two_weeks(self):
        self.peak(360)
        at = self.run_app()
        next(b for b in at.button if b.label == "Not now").click().run()
        self.assertEqual(self.labels(at), [])
        self.assertEqual(q.get_setting("ftp_help_snoozed_until"), D(14))
        self.assertEqual(self.labels(self.run_app()), [])                       # still hidden on a fresh visit
        q.set_setting("ftp_help_snoozed_until", D(-1))                          # the snooze has run out
        self.assertIn("Use 342 W", self.labels(self.run_app()))

    def test_an_estimated_ftp_is_still_shown_and_can_be_snoozed(self):
        q.set_setting("ftp_estimated", "1")
        self.assertIn("Not now", self.labels(self.run_app()))
        q.set_setting("ftp_help_snoozed_until", D(5))
        self.assertEqual(self.labels(self.run_app()), [])

    def test_use_suggestion_sets_ftp_and_clears_the_snooze(self):
        self.peak(360)
        q.set_setting("ftp_help_snoozed_until", "")
        at = self.run_app()
        next(b for b in at.button if b.label == "Use 342 W").click().run()
        self.assertEqual(q.get_setting("ftp_watts"), "342")
        self.assertEqual(q.get_setting("ftp_estimated"), "0")

    def test_entering_it_yourself_saves_and_marks_it_known(self):
        q.set_setting("ftp_estimated", "1")
        at = self.run_app()
        at.number_input(key="t_manual").set_value(285).run()
        next(b for b in at.button if b.label == "Save FTP").click().run()
        self.assertEqual(q.get_setting("ftp_watts"), "285")
        self.assertEqual(q.get_setting("ftp_estimated"), "0")
        self.assertEqual(q.get_ftp_history(limit=1)[-1]["ftp_watts"], 285)


if __name__ == "__main__":
    unittest.main()
