"""TrainingPeaks sign in window and automatic calendar sync."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

from auth import tp_login, trainingpeaks as tp
from db import queries as q
from tests.test_export import Base, D, STEPS, TODAY, tp_session


def _steps_saved(rides):
    for w in rides:
        q.save_workout_steps(w["id"], json.dumps(STEPS))


class PlanChangeTests(Base):
    def test_every_kind_of_plan_edit_marks_the_plan_changed(self):
        def changed():
            return q.get_setting("plan_changed_at", "")

        w = self.ride(D(1))
        first = changed()
        self.assertTrue(first)
        for edit in (lambda: q.update_workout(w["id"], {**w, "name": "New"}),
                     lambda: q.move_workout(w["id"], D(2)),
                     lambda: q.delete_workout(w["id"])):
            q.set_setting("plan_changed_at", "")
            edit()
            self.assertTrue(changed())


class SyncDueTests(Base):
    def setUp(self):
        super().setUp()
        q.set_setting(tp.COOKIE_SETTING, "abc")
        q.set_setting(tp.ENABLED_SETTING, "1")

    def test_off_or_signed_out_never_syncs(self):
        q.set_setting(tp.ENABLED_SETTING, "")
        self.assertFalse(tp.sync_due())
        q.set_setting(tp.ENABLED_SETTING, "1")
        q.set_setting(tp.NEEDS_SIGNIN_SETTING, "1")
        self.assertFalse(tp.sync_due())

    def test_due_first_time_after_a_change_and_daily(self):
        self.assertTrue(tp.sync_due())
        now = datetime.utcnow()
        q.set_setting(tp.LAST_SYNC_SETTING, now.isoformat())
        q.set_setting("plan_changed_at", (now - timedelta(minutes=5)).isoformat())
        self.assertFalse(tp.sync_due(now))
        q.set_setting("plan_changed_at", (now + timedelta(seconds=1)).isoformat())
        self.assertTrue(tp.sync_due(now))
        q.set_setting("plan_changed_at", "")
        self.assertTrue(tp.sync_due(now + timedelta(hours=25)))

    def test_premium_runs_to_the_last_planned_ride_and_free_to_tomorrow(self):
        self.ride(D(3))
        self.ride(D(180), name="Far")
        q.set_setting(tp.PREMIUM_SETTING, "1")
        self.assertEqual(tp.sync_range(TODAY), (D(0), D(180)))
        q.set_setting(tp.PREMIUM_SETTING, "0")
        self.assertEqual(tp.sync_range(TODAY), (D(0), D(1)))

    def test_nothing_planned_means_just_today(self):
        q.set_setting(tp.PREMIUM_SETTING, "1")
        self.assertEqual(tp.sync_range(TODAY), (D(0), D(0)))


class SyncUpcomingTests(Base):
    def setUp(self):
        super().setUp()
        q.set_setting(tp.COOKIE_SETTING, "abc")
        q.set_setting(tp.ENABLED_SETTING, "1")
        q.set_setting(tp.PREMIUM_SETTING, "1")

    def test_builds_missing_steps_then_sends_skips_and_removes(self):
        a, b = self.ride(D(1), name="A"), self.ride(D(3), name="B")
        built = []

        def build(rides):
            built.extend(w["id"] for w in rides)
            _steps_saved(rides)

        out = tp.sync_upcoming(TODAY, client=tp.Client("abc", session=tp_session()), build_steps=build)
        self.assertEqual(sorted(built), sorted([a["id"], b["id"]]))
        self.assertEqual(out["sent"], 2)
        kind, _, text = tp.last_result()
        self.assertEqual(kind, "ok")
        self.assertIn("Sent 2 rides", text)
        self.assertTrue(q.get_setting(tp.LAST_SYNC_SETTING, ""))

        q.delete_workout(b["id"])
        out = tp.sync_upcoming(TODAY, client=tp.Client("abc", session=tp_session()), build_steps=build)
        self.assertEqual((out["sent"], out["unchanged"], out["removed"]), (0, 1, 1))

    def test_rides_whose_steps_cannot_be_built_are_counted_not_sent(self):
        self.ride(D(1), name="A")
        out = tp.sync_upcoming(TODAY, client=tp.Client("abc", session=tp_session()),
                               build_steps=lambda rides: None)
        self.assertEqual((out["sent"], out["skipped"]), (0, 1))
        self.assertEqual(tp.last_result()[0], "warn")

    def test_free_account_only_sends_today_and_tomorrow(self):
        q.set_setting(tp.PREMIUM_SETTING, "0")
        _steps_saved([self.ride(D(1), name="Soon"), self.ride(D(5), name="Later")])
        out = tp.sync_upcoming(TODAY, client=tp.Client("abc", session=tp_session()))
        self.assertEqual(out["sent"], 1)

    def test_a_refused_cookie_tries_a_silent_refresh_once(self):
        with mock.patch.object(tp, "Client", side_effect=[tp.TPAuthError("x"), "client"]) as client, \
                mock.patch.object(tp_login, "refresh", return_value="fresh") as refresh:
            self.assertEqual(tp._signed_in_client(), "client")
        refresh.assert_called_once()
        self.assertEqual(client.call_args_list[1].args, ("fresh",))
        self.assertEqual(q.get_setting(tp.COOKIE_SETTING), "fresh")
        self.assertFalse(tp.needs_signin())

    def test_when_refresh_fails_syncing_pauses_until_a_real_sign_in(self):
        with mock.patch.object(tp, "Client", side_effect=tp.TPAuthError("x")), \
                mock.patch.object(tp_login, "refresh", return_value=None):
            with self.assertRaises(tp.TPAuthError):
                tp._signed_in_client()
        self.assertTrue(tp.needs_signin())
        self.assertFalse(tp.sync_due())

    def test_connect_saves_the_account_and_clears_a_paused_sync(self):
        q.set_setting(tp.NEEDS_SIGNIN_SETTING, "1")
        info = tp.connect("Production_tpAuth=new; x=1", session=tp_session())
        self.assertEqual(info["name"], "Sam")
        self.assertEqual(q.get_setting(tp.COOKIE_SETTING), "new")
        self.assertTrue(tp.is_premium())
        self.assertFalse(tp.needs_signin())
        self.assertTrue(tp.sync_due())


class NoDuplicatesTests(Base):
    def setUp(self):
        super().setUp()
        q.set_setting(tp.COOKIE_SETTING, "abc")
        q.set_setting(tp.ENABLED_SETTING, "1")
        q.set_setting(tp.PREMIUM_SETTING, "1")

    def deletes(self, s):
        return sorted(c["url"].rsplit("/", 1)[-1] for c in s.calls if c["method"] == "DELETE")

    def posts(self, s):
        return [c for c in s.calls if c["method"] == "POST"]

    def test_a_ride_six_months_out_is_sent(self):
        _steps_saved([self.ride(D(180), name="Far")])
        out = tp.sync_upcoming(TODAY, client=tp.Client("abc", session=tp_session()))
        self.assertEqual(out["sent"], 1)

    def test_a_zip_import_is_replaced_and_ridden_or_other_workouts_are_left(self):
        w = self.ride(D(2), name="Tempo blocks")
        _steps_saved([w])
        listing = [
            {"workoutId": 11, "title": f"{D(2)} Tempo blocks"},               # from the .zwo download
            {"workoutId": 12, "title": "tempo blocks"},                        # dragged in by name
            {"workoutId": 13, "title": "Tempo blocks", "totalTime": 1.2},      # ridden, keep
            {"workoutId": 14, "title": "Coach's recovery spin"},               # someone else's, keep
        ]
        s = tp_session(listing=listing)
        out = tp.sync_upcoming(TODAY, client=tp.Client("abc", session=s))
        self.assertEqual(out["sent"], 1)
        self.assertEqual(self.deletes(s), ["11", "12"])
        self.assertEqual(len(self.posts(s)), 1)

    def test_our_own_copy_is_never_mistaken_for_an_import(self):
        w = self.ride(D(2), name="A")
        _steps_saved([w])
        tp.sync_upcoming(TODAY, client=tp.Client("abc", session=tp_session()))    # sent as 555
        q.update_workout(w["id"], {**q.get_workout(w["id"]), "tss_planned": 90})
        _steps_saved([w])
        s = tp_session(listing=[{"workoutId": 555, "title": "A"}], created={"workoutId": 556})
        tp.sync_upcoming(TODAY, client=tp.Client("abc", session=s))
        self.assertEqual(self.deletes(s), ["555"])                                  # replaced once
        self.assertEqual(len(self.posts(s)), 1)

    def test_a_send_with_no_id_back_is_cleaned_up_next_time(self):
        w = self.ride(D(2), name="A")
        _steps_saved([w])
        q.save_synced(tp.SERVICE, [{"workout_id": w["id"], "remote_id": None, "date": D(2),
                                    "fingerprint": "old"}])
        s = tp_session(listing=[{"workoutId": 40, "title": "A"}], created={"workoutId": 41})
        tp.sync_upcoming(TODAY, client=tp.Client("abc", session=s))
        self.assertEqual(self.deletes(s), ["40"])
        self.assertEqual(q.get_synced(tp.SERVICE)[w["id"]]["remote_id"], "41")

    def test_marking_a_ride_done_keeps_it_on_trainingpeaks(self):
        w = self.ride(D(0), name="Today")
        _steps_saved([w])
        tp.sync_upcoming(TODAY, client=tp.Client("abc", session=tp_session()))
        q.update_workout(w["id"], {**q.get_workout(w["id"]), "completed": 1})
        s = tp_session()
        out = tp.sync_upcoming(TODAY, client=tp.Client("abc", session=s))
        self.assertEqual((out["removed"], self.deletes(s)), (0, []))

    def test_deleting_the_furthest_ride_removes_it(self):
        near, far = self.ride(D(3), name="Near"), self.ride(D(150), name="Far")
        _steps_saved([near, far])
        tp.sync_upcoming(TODAY, client=tp.Client("abc", session=tp_session(created={"workoutId": 9})))
        q.delete_workout(far["id"])
        s = tp_session()
        out = tp.sync_upcoming(TODAY, client=tp.Client("abc", session=s))
        self.assertEqual(out["removed"], 1)
        self.assertNotIn(far["id"], q.get_synced(tp.SERVICE))

    def test_only_one_sync_runs_at_a_time(self):
        with mock.patch.object(tp, "sync_upcoming", return_value={"sent": 0}) as run:
            tp._sync_lock.acquire()
            try:
                self.assertIsNone(tp.run_locked())
            finally:
                tp._sync_lock.release()
            self.assertEqual(tp.run_locked(), {"sent": 0})
        run.assert_called_once()


class LoginWindowTests(unittest.TestCase):
    """The Chrome window, with Playwright replaced by a fake."""

    def fake_playwright(self, cookies_over_time, url="https://app.trainingpeaks.com/home"):
        rounds = iter(cookies_over_time)
        page = mock.Mock(url=url)
        context = mock.Mock(pages=[page])
        last = {"v": []}

        def cookies():
            last["v"] = next(rounds, last["v"])
            return last["v"]

        context.cookies.side_effect = cookies
        context.new_page.return_value = page
        p = mock.Mock()
        p.chromium.launch_persistent_context.return_value = context
        cm = mock.MagicMock()
        cm.__enter__.return_value = p
        return (lambda: cm), p, context

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(tp_login, "PROFILE_DIR", os.path.join(self.tmp.name, "tp_browser"))
        patch.start()
        self.addCleanup(patch.stop)
        sleep = mock.patch.object(tp_login.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_sign_in_waits_for_the_cookie_in_a_visible_chrome(self):
        factory, p, context = self.fake_playwright(
            [[], [{"name": "other", "value": "1"}], [{"name": tp_login.COOKIE, "value": "abc"}]])
        self.assertEqual(tp_login.sign_in(timeout=60, sync_playwright=factory), "abc")
        kwargs = p.chromium.launch_persistent_context.call_args.kwargs
        self.assertEqual((kwargs["channel"], kwargs["headless"]), ("chrome", False))
        context.close.assert_called_once()

    def test_closing_the_window_says_so(self):
        factory, _, context = self.fake_playwright([[]])
        context.pages = []
        with self.assertRaises(tp_login.LoginError):
            tp_login.sign_in(timeout=60, sync_playwright=factory)

    def test_refresh_is_headless_and_gives_up_on_the_login_page(self):
        os.makedirs(tp_login.PROFILE_DIR)
        factory, p, _ = self.fake_playwright([[{"name": tp_login.COOKIE, "value": "new"}]])
        self.assertEqual(tp_login.refresh(sync_playwright=factory), "new")
        self.assertTrue(p.chromium.launch_persistent_context.call_args.kwargs["headless"])
        factory, _, _ = self.fake_playwright([[]], url="https://home.trainingpeaks.com/login")
        self.assertIsNone(tp_login.refresh(sync_playwright=factory))

    def test_no_saved_profile_means_no_refresh(self):
        self.assertIsNone(tp_login.refresh(sync_playwright=lambda: self.fail("should not open Chrome")))


if __name__ == "__main__":
    unittest.main()
