"""The why behind each workout: tool validation, Quick Generate, storage and
display. Run with venv/bin/python -m unittest tests.test_why -v"""
import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

import coach_tools
import planning
from components import calendar as cal
from db import schema, queries as q

SOON = (date.today() + timedelta(days=3)).isoformat()


def ride(**kw):
    return {"date": SOON, "name": "Easy spin", "workout_type": "Endurance",
            "description": "45 min easy", "tss_planned": 40,
            "purpose": "Builds your base so harder weeks feel manageable.",
            "feel": "3 out of 10, you can chat in full sentences", **kw}


def propose(workouts, phases=None):
    out = []
    args = {"workouts": workouts}
    if phases is not None:
        args["phases"] = phases
    coach_tools._propose(args, out)
    return out


class ProposeTests(unittest.TestCase):
    def test_accepts_purpose_feel_and_phases(self):
        out = propose([ride(phase="Base", week_number=1)],
                      [{"name": "Base", "focus": "Build your base", "why": "Everything else sits on it."}])
        self.assertEqual(out[0]["purpose"], "Builds your base so harder weeks feel manageable.")
        self.assertEqual(out[0]["phase_note"], {"focus": "Build your base", "why": "Everything else sits on it."})

    def test_single_workout_needs_no_phases(self):
        out = propose([ride()])
        self.assertIsNone(out[0]["phase_note"])

    def test_purpose_and_feel_are_required(self):
        for key in ("purpose", "feel"):
            w = ride()
            del w[key]
            with self.assertRaises(coach_tools.ToolInputError, msg=key):
                propose([w])
            with self.assertRaises(coach_tools.ToolInputError, msg=key):
                propose([ride(**{key: "   "})])

    def test_text_limits(self):
        with self.assertRaises(coach_tools.ToolInputError):
            propose([ride(purpose="x" * (coach_tools.PURPOSE_MAX + 1))])
        with self.assertRaises(coach_tools.ToolInputError):
            propose([ride(feel="x" * (coach_tools.FEEL_MAX + 1))])
        with self.assertRaises(coach_tools.ToolInputError):
            propose([ride(phase="Base")], [{"name": "Base", "focus": "x" * 200, "why": "y"}])

    def test_a_workout_phase_missing_from_phases_is_rejected(self):
        with self.assertRaises(coach_tools.ToolInputError) as cm:
            propose([ride(phase="Build")], [{"name": "Base", "focus": "f", "why": "w"}])
        self.assertIn("missing from phases", str(cm.exception))
        with self.assertRaises(coach_tools.ToolInputError):
            propose([ride(phase="Build")])

    def test_bad_phases_shape(self):
        for phases in ("nope", [1], [{"name": "", "focus": "f", "why": "w"}], [{"name": "A", "focus": "f"}]):
            with self.assertRaises(coach_tools.ToolInputError):
                propose([ride()], phases)

    def test_schema_requires_the_new_fields(self):
        tools = {t["name"]: t for t in coach_tools.TOOLS}
        item = tools["propose_workouts"]["input_schema"]["properties"]["workouts"]["items"]
        self.assertTrue({"purpose", "feel"} <= set(item["required"]))
        self.assertIn("phases", tools["propose_workouts"]["input_schema"]["properties"])
        s_item = tools["propose_strength_sessions"]["input_schema"]["properties"]["sessions"]["items"]
        self.assertIn("purpose", s_item["required"])

    def test_strength_needs_a_purpose(self):
        base = {"date": SOON, "name": "Lower", "duration_minutes": 40,
                "exercises": [{"name": "Squat", "sets": 3, "reps": "6", "intensity": "RPE 7"}]}
        out = []
        coach_tools._propose_strength({"sessions": [{**base, "purpose": "Leg strength for climbing."}]}, out)
        self.assertEqual(out[0]["purpose"], "Leg strength for climbing.")
        with self.assertRaises(coach_tools.ToolInputError):
            coach_tools._propose_strength({"sessions": [base]}, [])


class QuickGenerateTests(unittest.TestCase):
    def test_every_generated_workout_explains_itself(self):
        plan = planning.generate_block(40, 60, date.today() + timedelta(days=70), "Threshold")
        self.assertGreater(len(plan), 20)
        for w in plan:
            self.assertTrue(w["purpose"] and w["feel"], w["name"])
            self.assertTrue(w["phase_note"], w["phase"])
        phases = {w["phase"] for w in plan}
        self.assertEqual(phases, {"Build / Threshold", "Taper"})
        recovery = [w for w in plan if w["name"].startswith("(Recovery)")]
        self.assertTrue(recovery and all("lighter week on purpose" in w["purpose"] for w in recovery))

    def test_days_per_week_limits_riding_days_and_keeps_the_weekly_load(self):
        race = date.today() + timedelta(days=28)
        start = date.today() - timedelta(days=date.today().weekday())     # a Monday
        full = planning.generate_block(40, 60, race, "Threshold", start)
        four = planning.generate_block(40, 60, race, "Threshold", start, days_per_week=4)
        by_week = lambda plan: {w["week_number"] for w in plan}
        for wk in by_week(four):
            days = {w["date"] for w in four if w["week_number"] == wk}
            self.assertLessEqual(len(days), 4)
        self.assertLess(len(four), len(full))
        wk1_full = sum(w["tss_planned"] for w in full if w["week_number"] == 1)
        wk1_four = sum(w["tss_planned"] for w in four if w["week_number"] == 1)
        self.assertAlmostEqual(wk1_full, wk1_four, delta=6)               # same load, fewer days
        three = planning.generate_block(40, 60, race, "Threshold", start, days_per_week=3)
        self.assertTrue(all(len({w["date"] for w in three if w["week_number"] == k}) <= 3
                            for k in by_week(three)))
        types = {w["workout_type"] for w in three if w["week_number"] == 1}
        self.assertIn("Long Ride", types)                                  # the biggest session stays
        self.assertEqual(len(planning.generate_block(40, 60, race, "Threshold", start, days_per_week=7)), len(full))

    def test_generated_output_passes_the_coach_validation(self):
        plan = planning.generate_block(40, 60, date.today() + timedelta(days=40), "Endurance")
        notes = {w["phase"]: w["phase_note"] for w in plan}
        out = propose([{k: v for k, v in w.items() if k != "phase_note"} for w in plan],
                      [{"name": n, **note} for n, note in notes.items()])
        self.assertEqual(len(out), len(plan))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()

    def test_workout_round_trip_and_edit(self):
        wid = q.add_workout({"date": SOON, "name": "Easy", "workout_type": "Endurance", "description": "",
                             "structured_json": None, "tss_planned": 40, "notes": "",
                             "purpose": "Base building", "feel": "3 out of 10"})
        w = q.get_workout(wid)
        self.assertEqual((w["purpose"], w["feel"]), ("Base building", "3 out of 10"))
        base = {k: w[k] for k in ("name", "workout_type", "description", "tss_planned", "completed", "notes")}
        q.update_workout(wid, {**base, "name": "Renamed"})                  # no purpose given, keep it
        self.assertEqual(q.get_workout(wid)["purpose"], "Base building")
        q.update_workout(wid, {**base, "purpose": "New reason", "feel": ""})
        w = q.get_workout(wid)
        self.assertEqual((w["purpose"], w["feel"]), ("New reason", ""))

    def test_old_style_workouts_still_work(self):
        wid = q.add_workout({"date": SOON, "name": "Old", "workout_type": "Endurance", "description": "",
                             "structured_json": None, "tss_planned": 40, "notes": ""})
        self.assertIsNone(q.get_workout(wid)["purpose"])

    def test_phase_notes(self):
        self.assertEqual(q.get_phase_notes(), {})
        q.save_phase_notes([{"name": "Base", "focus": "f1", "why": "w1"}, {"name": "", "focus": "x", "why": "y"}])
        q.save_phase_notes([{"name": "Base", "focus": "f2", "why": "w2"}, {"name": "Taper", "focus": "t", "why": "u"}])
        self.assertEqual(q.get_phase_notes(), {"Base": {"focus": "f2", "why": "w2"},
                                               "Taper": {"focus": "t", "why": "u"}})
        q.save_phase_notes([])

    def test_strength_purpose(self):
        sid = q.add_strength_session({"date": SOON, "plan_week": 1, "exercises_json": "[]",
                                      "duration_minutes": 30, "notes": "Legs | Planned by AI Coach",
                                      "purpose": "Leg strength"})
        self.assertEqual(q.get_strength_session(sid)["purpose"], "Leg strength")


class DisplayTests(unittest.TestCase):
    def test_tooltip_shows_purpose_and_feel_escaped(self):
        w = {"id": 1, "date": SOON, "name": "Easy", "workout_type": "Endurance", "tss_planned": 40,
             "completed": 0, "description": "", "purpose": "Builds <b>base</b> & more",
             "feel": "3 out of 10 <script>"}
        days = cal.build_month_data(date.today().year, date.today().month, [w], [], [], [], date.today())
        tip = cal.day_tooltip(next(d for d in days.values() if d.planned))
        self.assertIn("<b>Why.</b> Builds &lt;b&gt;base&lt;/b&gt; &amp; more", tip)
        self.assertIn("<b>Feel.</b> 3 out of 10 &lt;script&gt;", tip)
        self.assertNotIn("<script>", tip)

    def test_garmin_description_carries_feel_and_purpose(self):
        import garmin_workouts
        kind = sorted(garmin_workouts.STEP_KINDS)[0]
        steps = [{"kind": kind, "minutes": 30, "low_pct": 60, "high_pct": 70}]
        payload = garmin_workouts.to_garmin_json(
            {"name": "Easy", "description": "30 min", "feel": "3 out of 10", "purpose": "Base"}, steps)
        text = payload["description"]
        self.assertIn("30 min", text)
        self.assertIn("How it should feel. 3 out of 10", text)
        self.assertIn("Why. Base", text)
        plain = garmin_workouts.to_garmin_json({"name": "Easy", "description": "30 min"}, steps)
        self.assertNotIn("Why.", plain["description"])


if __name__ == "__main__":
    unittest.main()
