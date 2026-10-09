"""Scoring like TrainingPeaks, intervals.icu or the published standard, and checking the app's
scores against intervals.icu. Run with venv/bin/python -m unittest tests.test_score_like -v"""
import json
from datetime import date, timedelta
from unittest import mock

import compare
from auth import garmin as garmin_auth
from auth import intervals
from db import schema, queries as q
from metrics.tss import STANDARDS, hr_tss_seconds, mismatch, tss_duration
from tests.test_manual_tss import Base, ride

TODAY = date.today()
DAY = (TODAY - timedelta(days=3)).isoformat()


def hr_ride(external_id="hr1", **kw):
    """A ride with no power: 60 min of timer time, 50 min moving."""
    return ride(external_id, tss=None, date=DAY, normalized_power=None, avg_power_watts=None, avg_hr=150,
                duration_seconds=3000, timer_seconds=3600, elapsed_seconds=3900, **kw)


class ProfileTests(Base):
    def test_trainingpeaks_is_the_default(self):
        p = q.hr_profile()
        self.assertEqual((p["method"], p["time"]), ("trainingpeaks", "timer"))
        self.assertEqual(compare.standard(), "trainingpeaks")

    def test_each_standard_picks_its_heart_rate_method_and_time(self):
        expect = {"trainingpeaks": ("trainingpeaks", "timer"), "intervals": ("trimp", "moving"),
                  "standard": ("trimp", "timer")}
        for key, want in expect.items():
            q.set_setting("score_like", key)
            p = q.hr_profile()
            self.assertEqual((p["method"], p["time"]), want, key)

    def test_old_heart_rate_setting_still_works_without_score_like(self):
        q.set_setting("hr_tss_method", "trimp")
        self.assertEqual((q.hr_profile()["method"], q.hr_profile()["time"]), ("trimp", "timer"))

    def test_time_rules(self):
        self.assertEqual(tss_duration(3000, 3900, 3600), 3600)
        self.assertEqual(tss_duration(3000, 3900, 3600, "moving"), 3000)
        self.assertEqual(tss_duration(None, 3900, 3600, "moving"), 3600)     # moving falls back to timer
        self.assertEqual(tss_duration(None, 3900, None, "moving"), 3900)     # then elapsed
        self.assertEqual(tss_duration(3000, 3900, None), 3000)               # timer falls back to moving


class ScoringTests(Base):
    def setUp(self):
        super().setUp()
        q.set_setting("max_hr_manual", "195")
        q.set_setting("resting_hr_manual", "50")

    def _rescore(self, standard):
        q.set_setting("score_like", standard)
        q.recalculate_all_tss()

    def test_intervals_scores_on_moving_time_and_trainingpeaks_on_timer(self):
        aid = q.upsert_activity(hr_ride())
        self._rescore("trainingpeaks")
        tp = q.get_activity(aid)["tss"]
        self._rescore("standard")
        std = q.get_activity(aid)["tss"]
        self._rescore("intervals")
        iv = q.get_activity(aid)["tss"]
        # The standard and intervals.icu use the same heart rate formula; only the time differs.
        self.assertAlmostEqual(iv / std, 3000 / 3600, places=2)
        self.assertNotAlmostEqual(tp, std, places=0)

    def test_switching_back_gives_the_same_numbers(self):
        aid = q.upsert_activity(hr_ride())
        self._rescore("trainingpeaks")
        before = q.get_activity(aid)["tss"]
        self._rescore("intervals")
        self._rescore("trainingpeaks")
        self.assertEqual(q.get_activity(aid)["tss"], before)

    def test_power_is_scored_the_same_way_except_for_time(self):
        aid = q.upsert_activity(ride("p", tss=None, date=DAY, duration_seconds=3000, timer_seconds=3600))
        self._rescore("trainingpeaks")
        tp = q.get_activity(aid)["tss"]
        self._rescore("intervals")
        self.assertAlmostEqual(q.get_activity(aid)["tss"], tp * 3000 / 3600, places=0)

    def test_a_garmin_sync_scores_like_the_chosen_standard(self):
        q.set_setting("score_like", "intervals")
        act = {"activityType": {"typeKey": "road_biking"}, "activityId": 7, "startTimeLocal": f"{DAY} 08:00:00",
               "duration": 3600, "movingDuration": 3000, "elapsedDuration": 3900, "normPower": 250}
        row = garmin_auth.activity_row(act, 250, 165, q.hr_profile())
        self.assertAlmostEqual(row["tss"], 3000 / 3600 * 100, places=0)
        row = garmin_auth.activity_row(act, 250, 165, {"time": "timer"})
        self.assertAlmostEqual(row["tss"], 100, places=0)

    def test_hrss_second_by_second_is_spread_over_moving_time(self):
        p = {"rest": 50, "max": 195, "k": 1.92, "method": "trimp"}
        hr = [165] * 3600
        self.assertAlmostEqual(hr_tss_seconds(hr, 165, p), 100)
        self.assertAlmostEqual(hr_tss_seconds(hr, 165, p, duration_s=3000), 100 * 3000 / 3600)


def iv_activity(day, load, moving=3600, kind="Ride", np_w=None, hr=None, hr_load=None, power_load=None):
    return {"id": f"i{load}", "start_date_local": f"{day}T08:00:00", "type": kind, "name": "Ride",
            "icu_training_load": load, "moving_time": moving, "elapsed_time": moving + 300,
            "icu_weighted_avg_watts": np_w, "average_heartrate": hr, "hr_load": hr_load, "power_load": power_load}


def session_with(**routes):
    """A requests session whose GETs answer from `routes` by the end of the path."""
    s = mock.Mock()

    def get(url, params=None, timeout=None):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = next(v for k, v in routes.items() if url.endswith(k))
        return resp
    s.get.side_effect = get
    return s


class IntervalsCompareTests(Base):
    def setUp(self):
        super().setUp()
        q.set_setting("score_like", "intervals")

    def test_its_numbers_are_kept_and_a_big_difference_is_flagged(self):
        aid = q.upsert_activity(ride("r", date=DAY, duration_seconds=3600, tss=80, tss_source="power"))
        s = session_with(activities=[iv_activity(DAY, 120, np_w=230, power_load=120)])
        self.assertEqual(intervals.compare_with_intervals(days_back=10, session=s), 1)
        a = q.get_activity(aid)
        self.assertEqual(a["tss"], 80)                                    # the app's score is untouched
        self.assertEqual(json.loads(a["ref_json"])["intervals"]["scored_by"], "power")
        m = mismatch(a)
        self.assertEqual((m["app"], m["ref"], m["service"]), (80, 120, "intervals"))
        self.assertTrue(any("intervals.icu" in r for r in m["reasons"]))
        self.assertFalse(any("TrainingPeaks" in r for r in m["reasons"]))

    def test_close_numbers_are_not_flagged(self):
        aid = q.upsert_activity(ride("r", date=DAY, duration_seconds=3600, tss=80, tss_source="power"))
        intervals.compare_with_intervals(days_back=10, session=session_with(activities=[iv_activity(DAY, 84)]))
        self.assertIsNone(mismatch(q.get_activity(aid)))

    def test_other_sports_match_other_sessions(self):
        aid = q.upsert_activity(ride("w", date=DAY, sport_type="strength_training", duration_seconds=3600,
                                     tss=30, tss_source="hr", normalized_power=None))
        s = session_with(activities=[iv_activity(DAY, 31, kind="WeightTraining", hr_load=31)])
        self.assertEqual(intervals.compare_with_intervals(days_back=10, session=s), 1)
        self.assertEqual(json.loads(q.get_activity(aid)["ref_json"])["intervals"]["scored_by"], "hr")

    def test_trainingpeaks_numbers_stay_when_intervals_are_added(self):
        aid = q.upsert_activity(ride("r", date=DAY, duration_seconds=3600, tss=80, tss_source="power"))
        q.set_ref_numbers(aid, "trainingpeaks", {"tss": 79, "scored_by": "power"})
        intervals.compare_with_intervals(days_back=10, session=session_with(activities=[iv_activity(DAY, 120)]))
        ref = json.loads(q.get_activity(aid)["ref_json"])
        self.assertEqual((ref["trainingpeaks"]["tss"], ref["intervals"]["tss"]), (79, 120))
        a = q.get_activity(aid)
        self.assertIsNotNone(mismatch(a))                          # against intervals.icu, the chosen one
        self.assertIsNone(mismatch(a, "trainingpeaks"))

    def test_thresholds_and_fitness(self):
        s = session_with(**{
            "/athlete/0": {"icu_resting_hr": 48, "sportSettings": [
                {"types": ["Run"], "ftp": None, "lthr": 170, "max_hr": 200},
                {"types": ["Ride", "VirtualRide"], "ftp": 330, "lthr": 159, "max_hr": 197}]},
            "/athlete/0/wellness": [{"id": "2026-10-09", "ctl": 74.8, "atl": 70.1, "restingHR": 47}]})
        self.assertEqual(intervals.thresholds(s), {"ftp": 330, "lthr": 159, "max_hr": 197, "rest_hr": 48})
        self.assertEqual(intervals.daily_fitness("2026-10-09", "2026-10-09", s)["2026-10-09"]["ctl"], 74.8)

    def test_compare_due_only_when_connected(self):
        self.assertFalse(intervals.compare_due())
        q.set_setting(intervals.KEY_SETTING, "k")
        self.assertTrue(intervals.compare_due())
        intervals.compare_with_intervals(days_back=1, session=session_with(activities=[]))
        self.assertFalse(intervals.compare_due())


class CompareServiceTests(Base):
    def test_each_standard_compares_against_its_own_service(self):
        self.assertEqual(compare.compare_service("trainingpeaks"), "trainingpeaks")
        self.assertEqual(compare.compare_service("intervals"), "intervals")

    def test_the_standard_compares_against_whatever_is_connected(self):
        self.assertIsNone(compare.compare_service("standard"))
        q.set_setting(intervals.KEY_SETTING, "k")
        self.assertEqual(compare.compare_service("standard"), "intervals")
        with mock.patch("auth.trainingpeaks.is_enabled", return_value=True):
            self.assertEqual(compare.compare_service("standard"), "trainingpeaks")

    def test_every_standard_has_its_parts(self):
        for v in STANDARDS.values():
            self.assertTrue({"label", "hr_method", "time", "compare", "about"} <= set(v))


class MigrationTests(Base):
    def test_tp_json_moves_into_ref_json_and_still_flags(self):
        aid = q.upsert_activity(ride("r", date=DAY, tss=150, tss_source="power"))
        conn = q.get_conn()
        conn.execute("UPDATE activities SET tp_json=? WHERE id=?",
                      (json.dumps({"tss": 100, "scored_by": "hr", "hours": 1.0}), aid))
        conn.commit()
        conn.close()
        schema.run_migrations()
        a = q.get_activity(aid)
        self.assertIsNone(a["tp_json"])
        self.assertEqual(json.loads(a["ref_json"])["trainingpeaks"]["tss"], 100)
        m = mismatch(a)
        self.assertEqual((m["ref"], m["name"]), (100, "TrainingPeaks"))
        schema.run_migrations()                                          # running again changes nothing
        self.assertEqual(q.get_activity(aid)["ref_json"], a["ref_json"])

    def test_clearing_one_service_keeps_the_other(self):
        aid = q.upsert_activity(ride("r", date=DAY))
        q.set_ref_numbers(aid, "trainingpeaks", {"tss": 1})
        q.set_ref_numbers(aid, "intervals", {"tss": 2})
        q.set_ref_numbers(aid, "trainingpeaks", None)
        self.assertEqual(json.loads(q.get_activity(aid)["ref_json"]), {"intervals": {"tss": 2}})
        q.set_ref_numbers(aid, "intervals", None)
        self.assertIsNone(q.get_activity(aid)["ref_json"])
