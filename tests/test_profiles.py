import os
import tempfile
import threading
import unittest
from unittest import mock

from db import schema, profiles
from db import queries as q


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.owner = os.path.join(self.tmp.name, "cycling.db")
        p = mock.patch.object(schema, "DB_PATH", self.owner)
        p.start()
        self.addCleanup(p.stop)
        q._settings_cache.clear()
        schema.run_migrations()
        q.set_setting("athlete_name", "Sam")

    def test_owner_listed_first_and_new_profile_is_migrated(self):
        p = profiles.create_profile("Alex Rider")
        self.assertEqual(p["slug"], "alex-rider")
        self.assertTrue(os.path.isfile(p["path"]))
        names = [x["name"] for x in profiles.list_profiles()]
        self.assertEqual(names, ["Sam", "Alex Rider"])
        with schema.use(p["path"]):
            # Every table exists, so pages work on a brand new athlete.
            self.assertEqual(q.get_workouts("2026-01-01", "2026-12-31"), [])

    def test_same_name_gets_its_own_file(self):
        a = profiles.create_profile("Alex")
        b = profiles.create_profile("Alex")
        self.assertNotEqual(a["path"], b["path"])

    def test_owner_slug_cannot_be_taken(self):
        self.assertNotEqual(profiles.create_profile("Me")["slug"], profiles.OWNER)

    def test_settings_and_rides_stay_apart(self):
        p = profiles.create_profile("Alex")
        q.set_setting("ftp_watts", 330)
        with schema.use(p["path"]):
            q.set_setting("ftp_watts", 240)
            self.assertEqual(q.get_setting("ftp_watts"), "240")
            self.assertFalse(schema.is_owner())
        self.assertEqual(q.get_setting("ftp_watts"), "330")
        self.assertTrue(schema.is_owner())

    def test_thread_keeps_the_profile_it_started_with(self):
        p = profiles.create_profile("Alex")
        started, release = threading.Event(), threading.Event()

        def work(path):
            with schema.use(path):
                started.set()
                release.wait(5)
                q.set_setting("marker", "alex")

        t = threading.Thread(target=work, args=(p["path"],))
        t.start()
        started.wait(5)
        release.set()           # the main thread is still on the owner meanwhile
        t.join(5)
        self.assertIsNone(q.get_setting("marker"))
        with schema.use(p["path"]):
            self.assertEqual(q.get_setting("marker"), "alex")

    def test_background_starters_pin_the_path(self):
        import ftp_change
        p = profiles.create_profile("Alex")
        seen = []
        done = threading.Event()

        def fake_resend(ids):
            seen.append(schema.current_path())
            done.set()

        with mock.patch.object(ftp_change, "resend_to_garmin", fake_resend):
            with schema.use(p["path"]):
                ftp_change.start_garmin_resend([1])
            done.wait(5)
        self.assertEqual(seen, [p["path"]])

    def test_garmin_only_on_owner(self):
        import auth.garmin as g
        p = profiles.create_profile("Alex")
        with mock.patch("os.path.isfile", return_value=True):
            self.assertTrue(g.is_connected())
            with schema.use(p["path"]):
                self.assertFalse(g.is_connected())

    def test_delete_moves_to_backups_and_owner_is_protected(self):
        p = profiles.create_profile("Alex")
        dest = profiles.delete_profile(p["slug"])
        self.assertFalse(os.path.exists(p["path"]))
        self.assertTrue(os.path.isfile(dest))
        self.assertTrue(dest.startswith(profiles.backups_dir()))
        with self.assertRaises(ValueError):
            profiles.delete_profile(profiles.OWNER)

    def test_path_for_rejects_odd_names(self):
        with self.assertRaises(ValueError):
            profiles.path_for("../cycling")


if __name__ == "__main__":
    unittest.main()
