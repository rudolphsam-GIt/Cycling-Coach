"""Setting TSS by hand: on a ride you have done (kept through syncs) and on the weeks of a
program draft. Run with venv/bin/python -m unittest tests.test_manual_tss -v"""
import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

import coach_tools
import program_pdf
import programs
from db import schema, queries as q
from tests.test_programs import sample, MONDAY

TODAY = date.today()


def ride(external_id="r1", tss=80.0, **kw):
    return {"source": "garmin", "external_id": external_id, "date": (TODAY - timedelta(days=2)).isoformat(),
            "name": "Morning ride", "sport_type": "Ride", "duration_seconds": 3600, "elapsed_seconds": 3700,
            "distance_meters": 30000, "elevation_gain_meters": 200, "avg_power_watts": 180, "avg_hr": 140,
            "max_hr": 170, "normalized_power": 190, "tss": tss, "if_value": 0.7, "raw_json": "{}",
            "zone_time_json": None, **kw}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()
        q.set_setting("ftp_watts", "250")
        q.set_setting("lthr", "165")


class RideTssTests(Base):
    def test_a_hand_set_tss_is_saved_and_locked(self):
        aid = q.upsert_activity(ride())
        q.set_activity_tss(aid, 123.4)
        a = q.get_activity(aid)
        self.assertEqual((a["tss"], a["tss_locked"]), (123.4, 1))

    def test_a_later_sync_does_not_overwrite_it(self):
        aid = q.upsert_activity(ride(tss=80))
        q.set_activity_tss(aid, 150)
        q.upsert_activity(ride(tss=95))                     # the same ride arrives again with new numbers
        self.assertEqual(q.get_activity(aid)["tss"], 150)

    def test_a_duplicate_from_another_source_does_not_overwrite_it(self):
        aid = q.upsert_activity(ride(tss=80))
        q.set_activity_tss(aid, 150)
        q.upsert_activity(ride(external_id="strava-1", source="strava", tss=99, avg_power_watts=181))
        self.assertEqual(q.get_activity(aid)["tss"], 150)

    def test_recalculating_everything_skips_locked_rides(self):
        a = q.upsert_activity(ride("a", tss=1))
        b = q.upsert_activity(ride("b", tss=1, date=(TODAY - timedelta(days=3)).isoformat(), name="Other"))
        q.set_activity_tss(a, 150)
        q.recalculate_all_tss()
        self.assertEqual(q.get_activity(a)["tss"], 150)
        self.assertGreater(q.get_activity(b)["tss"], 20)    # the unlocked ride was recalculated

    def test_going_back_to_calculated_changes_only_that_ride(self):
        a = q.upsert_activity(ride("a", tss=1))
        b = q.upsert_activity(ride("b", tss=7, date=(TODAY - timedelta(days=3)).isoformat(), name="Other"))
        q.set_activity_tss(a, 150)
        q.clear_activity_tss(a)
        got = q.get_activity(a)
        self.assertEqual(got["tss_locked"], 0)
        self.assertNotEqual(got["tss"], 150)
        self.assertEqual(q.get_activity(b)["tss"], 7)       # untouched

    def test_the_new_tss_reaches_the_training_load_numbers(self):
        aid = q.upsert_activity(ride())
        day = ride()["date"]
        q.set_activity_tss(aid, 300)
        self.assertEqual(q.get_daily_tss(day, day)[day], 300)


class WeekTssTests(Base):
    def test_overrides_change_that_week_only(self):
        p = programs.validate({**sample(), "tss_overrides": {"4": 200, 5: 0}})
        wk = {w["week"]: w for w in programs.week_plan(p)}
        base = {w["week"]: w for w in programs.week_plan(p, with_overrides=False)}
        self.assertEqual((wk[4]["tss"], wk[4]["edited"]), (200, True))
        self.assertEqual(wk[5]["tss"], 0)
        self.assertEqual(wk[6]["tss"], base[6]["tss"])
        self.assertFalse(wk[6]["edited"])

    def test_the_calendar_follows_an_override(self):
        p = programs.validate({**sample(), "tss_overrides": {"4": 200, "5": 0}})
        rides = programs.expand(p)["rides"]
        self.assertAlmostEqual(sum(r["tss_planned"] for r in rides if r["week_number"] == 4), 200, delta=3)
        self.assertFalse([r for r in rides if r["week_number"] == 5])      # 0 means a week off

    def test_bad_overrides_are_refused(self):
        for bad in ({"99": 100}, {"0": 100}, {"x": 100}, {"3": -5}, {"3": 5000}, [1], {"3": "lots"}):
            with self.subTest(bad), self.assertRaises(programs.ProgramError):
                programs.validate({**sample(), "tss_overrides": bad})

    def test_set_and_clear_on_the_saved_draft(self):
        d = programs.save_draft(sample())
        out = programs.set_week_tss(d["id"], {6: 350, 7: 360})
        self.assertEqual(out["tss_overrides"], {"6": 350, "7": 360})
        self.assertEqual(out["version"], d["version"])                    # an edit by hand is not a revision
        out = programs.set_week_tss(d["id"], {6: None})
        self.assertEqual(out["tss_overrides"], {"7": 360})
        self.assertEqual(programs.load("draft")["tss_overrides"], {"7": 360})

    def test_a_week_outside_the_program_is_refused_and_nothing_changes(self):
        d = programs.save_draft(sample())
        with self.assertRaises(programs.ProgramError):
            programs.set_week_tss(d["id"], {40: 100})
        self.assertEqual(programs.load("draft")["tss_overrides"], {})

    def test_the_coach_keeps_overrides_when_it_sends_them_back(self):
        coach_tools.run_tool("propose_program", {**sample(), "tss_overrides": {"4": 200}}, [])
        self.assertEqual(programs.load("draft")["tss_overrides"], {"4": 200})
        tool = next(t for t in coach_tools.TOOLS if t["name"] == "propose_program")
        self.assertIn("tss_overrides", tool["input_schema"]["properties"])

    def test_the_overrides_are_added_to_the_calendar_and_marked_in_the_pdf(self):
        d = programs.save_draft({**sample(), "tss_overrides": {"4": 200}})
        out = programs.apply(d["id"])
        week4 = [w for w in q.get_workouts(MONDAY.isoformat(), d["end_date"]) if w["week_number"] == 4]
        self.assertAlmostEqual(sum(w["tss_planned"] for w in week4), 200, delta=3)
        self.assertGreater(out["rides"], 0)
        self.assertTrue(program_pdf.build_pdf(programs.load("active")).startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()


class EditRideTests(Base):
    """The Edit ride form's saving rules (components.ride_analysis._save_ride_edits)."""

    def setUp(self):
        super().setUp()
        from components import ride_analysis
        self.ra = ride_analysis
        self.aid = q.upsert_activity(ride(tss=80))
        self.q = q

    def new(self, **kw):
        a = q.get_activity(self.aid)
        base = {"name": a["name"], "duration_seconds": a["duration_seconds"], "distance_meters": a["distance_meters"],
                "elevation_gain_meters": a["elevation_gain_meters"], "avg_power_watts": a["avg_power_watts"],
                "normalized_power": a["normalized_power"], "avg_hr": a["avg_hr"], "max_hr": a["max_hr"]}
        return {**base, **kw}

    def save(self, tss=None, **kw):
        a = q.get_activity(self.aid)
        return self.ra._save_ride_edits(a, self.new(**kw), a["tss"] if tss is None else tss)

    def test_nothing_changed_writes_nothing(self):
        self.assertFalse(self.save())
        a = q.get_activity(self.aid)
        self.assertEqual((a["edited"], a["tss_locked"]), (0, 0))

    def test_a_rename_does_not_freeze_the_synced_numbers(self):
        self.assertTrue(self.save(name="Zwift with the club", distance_meters=31000))
        a = q.get_activity(self.aid)
        self.assertEqual((a["name"], a["edited"], a["tss_locked"], a["tss"]), ("Zwift with the club", 0, 0, 80))
        q.upsert_activity(ride(tss=95, normalized_power=200))          # Garmin reprocesses the power later
        a = q.get_activity(self.aid)
        self.assertEqual((a["tss"], a["normalized_power"], a["name"], a["distance_meters"]),
                         (95, 200, "Zwift with the club", 31000))

    def test_a_typed_tss_is_locked(self):
        self.assertTrue(self.save(tss=140))
        a = q.get_activity(self.aid)
        self.assertEqual((a["tss"], a["tss_locked"]), (140, 1))

    def test_changing_power_and_time_recalculates_tss_when_not_typed_over(self):
        self.assertTrue(self.save(normalized_power=240, duration_seconds=7200))
        a = q.get_activity(self.aid)
        self.assertEqual((a["normalized_power"], a["duration_seconds"], a["elapsed_seconds"]), (240, 7200, 7200))
        self.assertAlmostEqual(a["tss"], 7200 / 3600 * (240 / 250) ** 2 * 100, delta=1)   # FTP 250
        self.assertEqual(a["tss_locked"], 0)

    def test_a_typed_tss_wins_over_the_recalculation(self):
        self.save(tss=55, normalized_power=240, duration_seconds=7200)
        a = q.get_activity(self.aid)
        self.assertEqual((a["tss"], a["tss_locked"]), (55, 1))

    def test_edits_survive_a_resync_from_the_same_source(self):
        self.save(name="Fixed", normalized_power=220, avg_power_watts=200, avg_hr=150, max_hr=175)
        q.upsert_activity(ride(tss=95, normalized_power=190, avg_power_watts=180, avg_hr=140, max_hr=170))
        a = q.get_activity(self.aid)
        self.assertEqual((a["normalized_power"], a["avg_power_watts"], a["avg_hr"], a["max_hr"]), (220, 200, 150, 175))
        self.assertNotEqual(a["tss"], 95)

    def test_edits_survive_a_duplicate_from_another_source(self):
        self.save(normalized_power=220)
        q.upsert_activity(ride(external_id="strava-9", source="strava", normalized_power=190,
                               avg_power_watts=181, tss=99))
        a = q.get_activity(self.aid)
        self.assertEqual(a["normalized_power"], 220)
        self.assertNotEqual(a["tss"], 99)

    def test_an_unedited_ride_still_takes_the_synced_values(self):
        q.upsert_activity(ride(tss=95, normalized_power=200))
        a = q.get_activity(self.aid)
        self.assertEqual((a["tss"], a["normalized_power"]), (95, 200))

    def test_a_big_edit_still_matches_the_same_ride_from_another_source(self):
        self.save(distance_meters=60000, duration_seconds=9000, normalized_power=230)
        dup = q.upsert_activity(ride(external_id="strava-2", source="strava", avg_power_watts=181))
        self.assertEqual(dup, self.aid)
        conn = schema.get_conn()
        n = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
        conn.close()
        self.assertEqual(n, 1)
        self.assertEqual(json.loads(q.get_activity(self.aid)["original_json"])["distance_meters"], 30000)

    def test_the_original_is_kept_from_the_first_edit_only(self):
        self.save(distance_meters=60000)
        self.save(distance_meters=70000)
        self.assertEqual(json.loads(q.get_activity(self.aid)["original_json"])["distance_meters"], 30000)

    def test_the_form_never_fails_on_values_above_the_usual_caps(self):
        q.update_activity_details(self.aid, {"duration_seconds": 60 * 3600})
        q.set_activity_tss(self.aid, 1700)
        from streamlit.testing.v1 import AppTest
        app = os.path.join(self.tmp.name, "popup.py")
        with open(app, "w") as f:
            f.write("import streamlit as st\nfrom components import ride_analysis\nfrom db import queries as q\n"
                    f"ride_analysis._edit_ride(q.get_activity({self.aid}))\n")
        at = AppTest.from_file(app, default_timeout=30).run()      # same process, so it reads the test database
        self.assertEqual([e.value for e in at.exception], [])
        self.assertEqual([n.value for n in at.number_input if n.label in ("Hours", "TSS")], [60, 1700])

    def test_only_the_listed_fields_can_be_written(self):
        q.update_activity_details(self.aid, {"name": "x", "source": "hacked", "date": "1999-01-01"})
        a = q.get_activity(self.aid)
        self.assertEqual((a["name"], a["source"], a["date"] == "1999-01-01"), ("x", "garmin", False))
