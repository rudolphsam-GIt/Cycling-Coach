"""Correctness fixes: taper load, one TSS rule, FTP history, a new FTP flowing into upcoming
workouts, Strava errors and Claude errors. Run with venv/bin/python -m unittest tests.test_correctness -v"""
import json
import unittest
from datetime import date, timedelta
from unittest import mock

import anthropic
import requests

import claude_client
import ftp_change
import workout_watts
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
        tss, if_value, source = ride_tss(3600, 250, 150, 180, 250, 165)
        self.assertAlmostEqual(tss, 100)
        self.assertAlmostEqual(if_value, 1.0)
        self.assertEqual(source, "power")
        tss, if_value, source = ride_tss(3600, None, 165, 180, 250, 165)
        self.assertAlmostEqual(tss, 100)          # heart rate when there's no power
        self.assertIsNone(if_value)
        self.assertEqual(source, "hr")
        tss, _, source = ride_tss(3600, None, None, None, 250, 0)
        self.assertGreater(tss, 0)                # estimate when there's neither
        self.assertEqual(source, "estimate")

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


class WorkoutWattsTests(unittest.TestCase):
    def test_watts_become_percent_and_back(self):
        stored = workout_watts.to_pct("2x20 at 230 to 255W, then 10 min at about 250 W", 345)
        self.assertEqual(stored, "2x20 at {66.7%FTP} to {73.9%FTP}W, then 10 min at about {72.5%FTP} W")
        self.assertEqual(workout_watts.to_watts(stored, 345), "2x20 at 230 to 255W, then 10 min at about 250 W")
        self.assertEqual(workout_watts.to_watts(stored, 300), "2x20 at 200 to 220W, then 10 min at about 220 W")

    def test_percentages_wkg_and_tokens_are_left_alone(self):
        for text in ("hold 90% FTP", "3.5 W/kg climb", "{66.7%FTP} to {75%FTP}W", "", None):
            self.assertEqual(workout_watts.to_pct(text, 345), text)

    def test_no_ftp_leaves_the_text_as_written(self):
        self.assertEqual(workout_watts.to_pct("hold 250 W", 0), "hold 250 W")

    def test_changed_lines_show_before_and_after(self):
        stored = workout_watts.to_pct("Warm up. 60 min at 250 to 270W. Cool down.", 330)
        self.assertEqual(workout_watts.changed_lines(stored, 330, 345), [("60 min at 250 to 270W.", "60 min at 260 to 280W.")])


class NewFtpTests(Base):
    def test_upcoming_workouts_follow_the_new_ftp_and_past_ones_do_not(self):
        future = _workout(TODAY + timedelta(days=3), "4x8 at 250 W")
        past = _workout(TODAY - timedelta(days=3), "4x8 at 250 W")
        with mock.patch.object(ftp_change, "start_garmin_resend") as resend:
            out = ftp_change.apply_new_ftp(275)
        by_id = {w["id"]: w for w in q.get_workouts("2000-01-01", "2100-01-01")}
        self.assertEqual(by_id[future]["description"], "4x8 at 275 W")
        self.assertEqual(by_id[past]["description"], "4x8 at 250 W")
        self.assertEqual(out, {"workouts": 1})
        resend.assert_not_called()                # nothing is sent until the rider says so
        self.assertEqual(q.get_setting("ftp_watts"), "275")
        self.assertEqual(q.get_ftp_history()[-1]["ftp_watts"], 275)

    def test_a_change_waits_for_review_and_holds_trainingpeaks(self):
        from auth import trainingpeaks as tp
        _workout(TODAY + timedelta(days=3), "60 min at 250 W")
        ftp_change.apply_new_ftp(275)
        self.assertEqual({k: ftp_change.pending()[k] for k in ("old", "new")}, {"old": 250, "new": 275})
        view = ftp_change.preview()
        self.assertEqual((view["count"], view["examples"][0][1:]), (1, ("60 min at 250 W", "60 min at 275 W")))
        with mock.patch.object(tp, "is_enabled", return_value=True), \
                mock.patch.object(tp, "needs_signin", return_value=False):
            self.assertFalse(tp.sync_due())
            ftp_change.clear_pending()
            self.assertTrue(tp.sync_due())

    def test_two_changes_before_an_answer_are_one_review(self):
        _workout(TODAY + timedelta(days=3), "60 min at 250 W")
        ftp_change.apply_new_ftp(275)
        ftp_change.apply_new_ftp(300)
        self.assertEqual((ftp_change.pending()["old"], ftp_change.pending()["new"]), (250, 300))
        ftp_change.apply_new_ftp(250)                # back where it was sent: nothing to review
        self.assertIsNone(ftp_change.pending())

    def test_same_ftp_changes_nothing(self):
        _workout(TODAY + timedelta(days=3), "4x8 at 250 W")
        self.assertEqual(ftp_change.apply_new_ftp(250), {"workouts": 0})
        self.assertIsNone(ftp_change.pending())

    def test_saving_a_workout_as_shown_keeps_its_exact_numbers(self):
        steps = json.dumps([{"kind": "interval", "minutes": 10, "low_pct": 90, "high_pct": 95}])
        wid = _workout(TODAY + timedelta(days=3), "hold 263 W", structured_json=steps)
        ftp_change.apply_new_ftp(275)
        w = q.get_workout(wid)
        self.assertEqual(w["description"], "hold 290 W")
        q.update_workout(wid, w)                     # opened and saved with no change
        raw = q.get_upcoming_workouts(TODAY.isoformat(), raw=True)[0]
        self.assertEqual(raw["description"], "hold {105.2%FTP} W")
        self.assertEqual(raw["structured_json"], steps)

    def test_garmin_copies_are_sent_again_only_when_asked(self):
        steps = json.dumps([{"kind": "interval", "minutes": 10, "low_pct": 90, "high_pct": 95}])
        wid = _workout(TODAY + timedelta(days=2), "Threshold")
        q.set_workout_garmin(wid, "g1", "s1", steps, "2026-01-01")
        _workout(TODAY + timedelta(days=4), "Not sent")
        with mock.patch.object(ftp_change, "start_garmin_resend", return_value=True) as resend:
            ftp_change.apply_new_ftp(275)
            resend.assert_not_called()
            self.assertIsNotNone(ftp_change.pending())       # Garmin's watts are fixed at send
            self.assertEqual([d["key"] for d in ftp_change.destinations()], ["garmin"])
            ftp_change.push(["garmin"])
        resend.assert_called_once_with([wid])
        self.assertIsNone(ftp_change.pending())

        import garmin_workouts
        with mock.patch.object(garmin_workouts, "send") as send:
            msg = ftp_change.resend_to_garmin([wid])
        send.assert_called_once()
        self.assertEqual(send.call_args.args[1], json.loads(steps))
        self.assertIn("Updated 1 workout", msg)

    def test_old_databases_are_converted_once(self):
        from db import schema
        wid = _workout(TODAY + timedelta(days=3), "hold 250 W")
        conn = get_conn()
        conn.execute("UPDATE workouts SET description='hold 250 W' WHERE id=?", (wid,))
        conn.execute("DELETE FROM athlete_settings WHERE key='workout_watts_pct'")
        conn.commit()
        conn.close()
        schema.run_migrations()
        schema.run_migrations()
        raw = q.get_upcoming_workouts(TODAY.isoformat(), raw=True)[0]
        self.assertEqual(raw["description"], "hold {100%FTP} W")


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
