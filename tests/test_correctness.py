"""Correctness fixes: taper load, one TSS rule, FTP history, a new FTP flowing into upcoming
workouts, Strava errors and Claude errors. Run with venv/bin/python -m unittest tests.test_correctness -v"""
import json
from datetime import date, timedelta
from unittest import mock

import anthropic
import requests

import claude_client
import ftp_change
from auth import garmin as garmin_auth, strava
from db import queries as q
from db.schema import get_conn
from metrics.taper import daily_taper_tss, taper_schedule, taper_workout
from metrics.tss import ride_tss
from tests.test_manual_tss import Base, ride

TODAY = date.today()


def _history(day: str, ftp: int) -> None:
    conn = get_conn()
    conn.execute("INSERT INTO ftp_history (date, ftp_watts, notes, created_at) VALUES (?,?,?,?)",
                 (day, ftp, "", day))
    conn.commit()
    conn.close()


def _workout(day: date, description: str, **kw) -> int:
    return q.add_workout({"date": day.isoformat(), "name": "Threshold", "workout_type": "Threshold",
                          "description": description, "structured_json": None, "tss_planned": 80,
                          "notes": "", **kw})


class TaperTests(Base):
    def test_daily_load_is_ctl_times_the_phase_factor(self):
        self.assertEqual(daily_taper_tss(30, 70), 70)
        self.assertEqual(daily_taper_tss(10, 70), 70 * 0.6)
        self.assertEqual(daily_taper_tss(5, 70), 70 * 0.4)
        self.assertEqual(daily_taper_tss(1, 70), 30)
        self.assertEqual(daily_taper_tss(0, 70), 0)

    def test_schedule_runs_from_tomorrow_to_race_day(self):
        race = TODAY + timedelta(days=10)
        sched = taper_schedule(TODAY, race, 60)
        self.assertEqual(len(sched), 10)
        self.assertEqual(min(sched), (TODAY + timedelta(days=1)).isoformat())
        self.assertEqual(sched[race.isoformat()], 0)
        self.assertAlmostEqual(sched[(TODAY + timedelta(days=1)).isoformat()], 60 * 0.6)

    def test_rest_days_get_no_workout(self):
        race = TODAY + timedelta(days=5)
        self.assertIsNone(taper_workout(race.isoformat(), race, 0))
        self.assertEqual(taper_workout((race - timedelta(days=1)).isoformat(), race, 30)[1], "Race Eve Opener")


class TssRuleTests(Base):
    def test_one_rule_for_every_source(self):
        tss, if_value = ride_tss(3600, 250, 150, 180, 250, 165)
        self.assertAlmostEqual(tss, 100)
        self.assertAlmostEqual(if_value, 1.0)
        tss, if_value = ride_tss(3600, None, 165, 180, 250, 165)
        self.assertAlmostEqual(tss, 100)          # heart rate when there's no power
        self.assertIsNone(if_value)
        tss, _ = ride_tss(3600, None, None, None, 250, 0)
        self.assertGreater(tss, 0)                # estimate when there's neither

    def test_a_garmin_ride_keeps_its_tss_through_a_recalculation(self):
        act = {"activityType": {"typeKey": "road_biking"}, "activityId": 1,
               "startTimeLocal": f"{TODAY - timedelta(days=1)} 08:00:00", "activityName": "Ride",
               "duration": 3650, "movingDuration": 3600, "elapsedDuration": 4500,
               "normPower": 225, "avgPower": 200, "averageHR": 150, "maxHR": 175}
        aid = q.upsert_activity(garmin_auth.activity_row(act, 250, 165))
        before = q.get_activity(aid)["tss"]
        q.recalculate_all_tss()
        self.assertEqual(q.get_activity(aid)["tss"], before)
        self.assertAlmostEqual(before, 82.1, places=1)   # 3650 s of timer time at IF 0.9

    def test_a_garmin_ride_without_power_or_lthr_still_gets_an_estimate(self):
        act = {"activityType": {"typeKey": "cycling"}, "activityId": 2,
               "startTimeLocal": f"{TODAY} 08:00:00", "movingDuration": 3600, "duration": 3600}
        self.assertGreater(garmin_auth.activity_row(act, 250, 0)["tss"], 0)


class FtpHistoryTests(Base):
    def test_old_rides_keep_the_ftp_they_were_ridden_at(self):
        old_day = (TODAY - timedelta(days=60)).isoformat()
        _history(old_day, 200)
        aid = q.upsert_activity(ride("old", date=(TODAY - timedelta(days=30)).isoformat(),
                                     normalized_power=200, tss=1))
        q.recalculate_all_tss()
        self.assertAlmostEqual(q.get_activity(aid)["tss"], 100, places=0)   # IF 1.0 on FTP 200
        ftp_change.apply_new_ftp(300)
        q.recalculate_all_tss()
        self.assertAlmostEqual(q.get_activity(aid)["tss"], 100, places=0)   # unchanged

    def test_ftp_on_falls_back_sensibly(self):
        self.assertEqual(q.ftp_on("2020-01-01", []), 250)         # no history: the setting
        hist = [{"date": "2024-01-01", "ftp_watts": 220}, {"date": "2025-01-01", "ftp_watts": 240}]
        self.assertEqual(q.ftp_on("2023-06-01", hist), 220)       # before history: earliest
        self.assertEqual(q.ftp_on("2024-06-01", hist), 220)
        self.assertEqual(q.ftp_on("2025-06-01", hist), 240)


class NewFtpTests(Base):
    def test_watts_in_text_scale_and_percentages_do_not(self):
        self.assertEqual(ftp_change.rescale_watts("4x8 at 250 W, 90% FTP", 1.1), "4x8 at 275 W, 90% FTP")
        self.assertEqual(ftp_change.rescale_watts("hold 240-260W", 1.1), "hold 265-285W")
        self.assertEqual(ftp_change.rescale_watts("3.5 W/kg climb", 1.1), "3.5 W/kg climb")

    def test_upcoming_workouts_follow_the_new_ftp(self):
        future = _workout(TODAY + timedelta(days=3), "4x8 at 250 W")
        past = _workout(TODAY - timedelta(days=3), "4x8 at 250 W")
        done = _workout(TODAY + timedelta(days=1), "4x8 at 250 W")
        conn = get_conn()
        conn.execute("UPDATE workouts SET completed=1 WHERE id=?", (done,))
        conn.commit()
        conn.close()
        with mock.patch.object(ftp_change, "start_garmin_resend") as resend:
            out = ftp_change.apply_new_ftp(275)
        by_id = {w["id"]: w for w in q.get_workouts("2000-01-01", "2100-01-01")}
        self.assertEqual(by_id[future]["description"], "4x8 at 275 W")
        self.assertEqual(by_id[past]["description"], "4x8 at 250 W")
        self.assertEqual(by_id[done]["description"], "4x8 at 250 W")
        self.assertEqual(out["descriptions"], 1)
        resend.assert_not_called()                # nothing was on Garmin
        self.assertEqual(q.get_setting("ftp_watts"), "275")
        self.assertEqual(q.get_ftp_history()[-1]["ftp_watts"], 275)

    def test_workouts_on_garmin_are_sent_again_with_saved_steps(self):
        steps = json.dumps([{"type": "steady", "minutes": 10, "low_pct": 90, "high_pct": 95}])
        wid = _workout(TODAY + timedelta(days=2), "Threshold")
        q.set_workout_garmin(wid, "g1", "s1", steps, "2026-01-01")
        _workout(TODAY + timedelta(days=4), "Not sent")
        with mock.patch.object(ftp_change, "start_garmin_resend") as resend:
            out = ftp_change.apply_new_ftp(275)
        resend.assert_called_once_with([wid])
        self.assertEqual(out["garmin"], 1)

        import garmin_workouts
        with mock.patch.object(garmin_workouts, "send") as send:
            msg = ftp_change.resend_to_garmin([wid])
        send.assert_called_once()
        self.assertEqual(send.call_args.args[1], json.loads(steps))
        self.assertIn("Updated 1 workout", msg)

    def test_same_ftp_changes_nothing(self):
        _workout(TODAY + timedelta(days=3), "4x8 at 250 W")
        out = ftp_change.apply_new_ftp(250)
        self.assertEqual(out, {"descriptions": 0, "garmin": 0})


class StravaErrorTests(Base):
    def test_a_rejected_sign_in_is_a_readable_error(self):
        q.set_setting("strava_access_token", "x")
        q.set_setting("strava_refresh_token", "y")
        q.set_setting("strava_token_expires_at", str(2**31))
        resp = requests.Response()
        resp.status_code = 401
        with mock.patch.object(strava.requests, "get", return_value=resp):
            with self.assertRaises(strava.StravaError) as ctx:
                strava.sync_activities("id", "secret")
        self.assertIn("connect Strava again", str(ctx.exception))

    def test_not_connected_is_an_error_not_a_message(self):
        with self.assertRaises(strava.StravaError):
            strava.sync_activities("id", "secret")


class ClaudeErrorTests(Base):
    def test_ask_raises_instead_of_returning_the_error_as_text(self):
        err = anthropic.APIConnectionError(request=mock.Mock())
        client = mock.Mock()
        client.beta.messages.create.side_effect = err
        with mock.patch.object(claude_client, "_client", return_value=client):
            with self.assertRaises(claude_client.ClaudeError):
                claude_client.ask([{"type": "text", "text": "s"}], [{"role": "user", "content": "hi"}])

    def test_race_notes_are_added_to_not_replaced(self):
        rid = q.add_race({"name": "Banana Belt", "date": (TODAY + timedelta(days=20)).isoformat(),
                          "distance_km": None, "elevation_gain_meters": None, "category": None,
                          "target_time_seconds": None, "notes": "obra.org/events/123"})
        q.add_race_notes(rid, "x" * 900)
        notes = next(r for r in q.get_races() if r["id"] == rid)["notes"]
        self.assertTrue(notes.startswith("obra.org/events/123"))
        self.assertIn("x" * 900, notes)


class FirstFtpChangeTests(Base):
    def test_the_old_ftp_is_kept_as_history_when_there_was_none(self):
        aid = q.upsert_activity(ride("old", date=(TODAY - timedelta(days=30)).isoformat(),
                                     normalized_power=250, tss=1))
        q.recalculate_all_tss()
        before = q.get_activity(aid)["tss"]
        ftp_change.apply_new_ftp(300)
        q.recalculate_all_tss()                    # a full recalculation still uses the old FTP
        self.assertEqual(q.get_activity(aid)["tss"], before)
        self.assertEqual([h["ftp_watts"] for h in q.get_ftp_history()], [250, 300])

    def test_a_resync_scores_old_rides_on_their_own_ftp(self):
        _history((TODAY - timedelta(days=90)).isoformat(), 200)
        q.set_setting("ftp_watts", "300")
        _history(TODAY.isoformat(), 300)
        act = {"activityType": {"typeKey": "road_biking"}, "activityId": 9,
               "startTimeLocal": f"{TODAY - timedelta(days=10)} 08:00:00", "duration": 3600,
               "normPower": 200, "averageHR": 150}
        api = mock.Mock()
        api.get_activities_by_date.return_value = [act]
        with mock.patch.object(garmin_auth, "_hr_peaks", return_value={}):
            garmin_auth._sync_rides(api, 30)
        a = q.get_activities(days_back=30)[0]
        self.assertAlmostEqual(a["tss"], 100, places=0)   # IF 1.0 on the FTP of that day
        self.assertEqual(a["timer_seconds"], 3600)
