"""Multi month programs: validation, turning phases into dated rides, saving and applying,
the coach tool, and the PDF.
Run with venv/bin/python -m unittest tests.test_programs -v"""
import copy
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

TODAY = date.today()
MONDAY = TODAY + timedelta(days=(7 - TODAY.weekday()) % 7 or 7)   # the next Monday after today


def day(name, wtype, title, share, desc="Steady ride", purpose="Builds your base.", feel="3 out of 10"):
    return {"day": name, "workout_type": wtype, "name": title, "description": desc, "share": share,
            "purpose": purpose, "feel": feel}


def sample(start=MONDAY):
    """A believable off season: a break, an easy rebuild, base with strength and a first sharper block."""
    return {
        "title": "Off season 2026 to 2027",
        "goal": "Come back fresh in January with a bigger aerobic base and a stronger body.",
        "overview": "Two easy weeks to reset, a gentle rebuild, then steady base work with gym sessions.",
        "start_date": start.isoformat(),
        "assumptions": ["8 to 10 hours a week", "Rides on Tue, Thu, Sat and Sun", "FTP 330 W"],
        "phases": [
            {"name": "Reset", "weeks": 2, "focus": "Rest and recover.", "why": "The season was long.",
             "weekly_hours": 3, "weekly_tss_start": 0, "weekly_tss_end": 0, "recovery_every": 0},
            {"name": "Rebuild", "weeks": 3, "focus": "Get the routine back.",
             "why": "Easy riding re-teaches the habit without cost.",
             "weekly_hours": 6, "weekly_tss_start": 250, "weekly_tss_end": 330, "recovery_every": 0,
             "week_template": [day("Tue", "Endurance", "Easy spin", 1.0), day("Thu", "Endurance", "Steady", 1.0),
                               day("Sat", "Long Ride", "Long and easy", 1.8, purpose="Builds endurance."),
                               day("Sun", "Recovery", "Recovery spin", 0.5, feel="2 out of 10")],
             "key_workouts": ["The Saturday long ride, keep it conversational"],
             "success_markers": ["You look forward to riding"]},
            {"name": "Base", "weeks": 8, "focus": "Build the aerobic engine.",
             "why": "Everything in the spring sits on this.",
             "weekly_hours": 9, "weekly_tss_start": 400, "weekly_tss_end": 560, "recovery_every": 4,
             "week_template": [day("Tue", "Tempo", "Tempo blocks", 1.1), day("Thu", "Endurance", "Steady", 1.0),
                               day("Sat", "Long Ride", "Long ride", 2.0), day("Sun", "Endurance", "Easy", 0.7)],
             "strength": {"days": ["Mon", "Wed"], "name": "Lower body strength", "duration_minutes": 45,
                          "purpose": "Stronger legs make the same watts cheaper.",
                          "exercises": [{"name": "Squat", "sets": 3, "reps": "6", "intensity": "RPE 7"}]}},
        ],
        "checkpoints": [{"week": 5, "what": "FTP test", "why": "Reset zones before base."},
                        {"week": 13, "what": "FTP test again", "why": "See what the base gave you."}],
        "notes": ["If you are sick, drop that week to easy spins and carry on."],
    }


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()
        g = mock.patch("garmin_workouts.remove_from_garmin", lambda row: None)
        g.start()
        self.addCleanup(g.stop)


class ValidationTests(unittest.TestCase):
    def test_a_good_program_gets_dates_and_totals(self):
        p = programs.validate(sample())
        self.assertEqual(p["total_weeks"], 13)
        self.assertEqual(p["end_date"], (MONDAY + timedelta(weeks=13) - timedelta(days=1)).isoformat())

    def test_rejects_a_start_in_the_past(self):
        with self.assertRaises(programs.ProgramError):
            programs.validate(sample(TODAY - timedelta(days=1)))

    def test_rejects_bad_shapes(self):
        cases = {
            "no phases": lambda s: s.update(phases=[]),
            "duplicate phase name": lambda s: s["phases"][2].update(name="Reset"),
            "bad type": lambda s: s["phases"][1]["week_template"][0].update(workout_type="Spin"),
            "two rides one day": lambda s: s["phases"][1]["week_template"].append(day("Tue", "Endurance", "x", 1)),
            "load but no template": lambda s: s["phases"][0].update(weekly_tss_start=100),
            "bad recovery_every": lambda s: s["phases"][2].update(recovery_every=5),
            "fractional recovery_every": lambda s: s["phases"][2].update(recovery_every=3.0),
            "too long": lambda s: s["phases"][2].update(weeks=26) or s["phases"].extend(
                [dict(s["phases"][2], name=f"Extra{i}", weeks=20) for i in range(3)]),
            "checkpoint outside": lambda s: s["checkpoints"][0].update(week=99),
            "missing purpose": lambda s: s["phases"][1]["week_template"][0].pop("purpose"),
            "bad strength day": lambda s: s["phases"][2]["strength"].update(days=["Funday"]),
            "empty title": lambda s: s.update(title=" "),
        }
        for name, mutate in cases.items():
            raw = copy.deepcopy(sample())
            mutate(raw)
            with self.subTest(name), self.assertRaises(programs.ProgramError):
                programs.validate(raw)


class ExpandTests(unittest.TestCase):
    def setUp(self):
        self.p = programs.validate(sample())

    def test_weeks_follow_the_phases(self):
        wk = programs.week_plan(self.p)
        self.assertEqual([w["phase"] for w in wk], ["Reset"] * 2 + ["Rebuild"] * 3 + ["Base"] * 8)
        self.assertEqual(wk[0]["start"], MONDAY.isoformat())
        self.assertEqual(wk[1]["start"], (MONDAY + timedelta(days=7)).isoformat())

    def test_load_ramps_to_the_stated_end_and_lighter_weeks_drop(self):
        wk = programs.week_plan(self.p)
        base = [w for w in wk if w["phase"] == "Base"]
        normal = [w for w in base if not w["recovery"]]
        self.assertEqual(normal[0]["tss"], 400)
        self.assertEqual(normal[-1]["tss"], 560)          # the stated end is really reached
        self.assertEqual(base[2]["tss"], round(400 + 160 * 2 / 5))
        self.assertTrue(base[3]["recovery"] and base[7]["recovery"])
        self.assertEqual(base[3]["tss"], round((400 + 160 * 2 / 5) * programs.RECOVERY_FACTOR))
        self.assertEqual(base[7]["tss"], round(560 * programs.RECOVERY_FACTOR))
        self.assertEqual(max(w["tss"] for w in base), 560)
        self.assertTrue(all(w["tss"] == 0 for w in wk[:2]))

    def test_a_short_phase_with_one_normal_week_does_not_divide_by_zero(self):
        raw = sample()
        raw["checkpoints"] = []
        raw["phases"][2].update(weeks=2, recovery_every=2)       # week 2 is lighter, week 1 is the only normal week
        wk = [w for w in programs.week_plan(programs.validate(raw)) if w["phase"] == "Base"]
        self.assertEqual([w["tss"] for w in wk], [400, 240])

    def test_rides_land_on_the_right_days_and_sum_to_the_week(self):
        out = programs.expand(self.p)
        rides = out["rides"]
        self.assertTrue(rides)
        for r in rides:
            self.assertIn(r["workout_type"], q.WORKOUT_TYPES)
            self.assertTrue(r["purpose"] and r["feel"] and r["phase_note"]["why"])
        wk3 = [r for r in rides if r["week_number"] == 3]          # first Rebuild week
        self.assertEqual([date.fromisoformat(r["date"]).strftime("%a") for r in wk3], ["Tue", "Thu", "Sat", "Sun"])
        self.assertAlmostEqual(sum(r["tss_planned"] for r in wk3), 250, delta=3)
        long = next(r for r in wk3 if r["workout_type"] == "Long Ride")
        self.assertGreater(long["tss_planned"], max(r["tss_planned"] for r in wk3 if r["workout_type"] == "Endurance"))

    def test_a_break_phase_makes_no_rides_and_strength_follows_its_days(self):
        out = programs.expand(self.p)
        self.assertFalse([r for r in out["rides"] if r["week_number"] <= 2])
        self.assertEqual(len(out["strength"]), 16)
        self.assertEqual({date.fromisoformat(s["date"]).strftime("%a") for s in out["strength"]}, {"Mon", "Wed"})

    def test_lighter_weeks_say_so(self):
        rides = programs.expand(self.p)["rides"]
        light = [r for r in rides if r["name"].startswith("(Recovery)")]
        self.assertTrue(light)
        self.assertIn("lighter week on purpose", light[0]["purpose"])

    def test_past_days_are_left_out(self):
        later = MONDAY + timedelta(days=10)
        out = programs.expand(self.p, today=later)
        self.assertTrue(all(r["date"] >= later.isoformat() for r in out["rides"] + out["strength"]))

    def test_a_midweek_start_still_gets_every_template_day_once_per_week(self):
        wed = MONDAY + timedelta(days=2)
        p = programs.validate(sample(wed))
        rebuild = [r for r in programs.expand(p)["rides"] if r["week_number"] == 3]
        self.assertEqual(len(rebuild), 4)
        first = date.fromisoformat(programs.week_plan(p)[2]["start"])
        self.assertTrue(all(first <= date.fromisoformat(r["date"]) <= first + timedelta(days=6) for r in rebuild))

    def test_where_are_we_and_summary(self):
        self.assertIsNone(programs.where_are_we(self.p, MONDAY - timedelta(days=1)))
        self.assertEqual(programs.where_are_we(self.p, MONDAY + timedelta(days=15))["phase"], "Rebuild")
        line = programs.summary_line(self.p, MONDAY + timedelta(days=15))
        self.assertIn("week 3", line)
        self.assertIn("Rebuild", line)
        self.assertIn("Starts", programs.summary_line(self.p, TODAY))

    def test_projected_fitness_rises_with_the_plan(self):
        days = programs.projected_fitness(self.p, 60, 55)
        ctl = programs.weekly_ctl(self.p, days)
        self.assertEqual(set(ctl), set(range(1, 14)))
        self.assertLess(ctl[2], 60)               # the break lets fitness fall
        self.assertGreater(ctl[13], ctl[5])       # base work rebuilds it


class DatabaseTests(Base):
    def test_save_draft_replaces_and_counts_versions(self):
        a = programs.save_draft(sample())
        raw = sample()
        raw["title"] = "Changed"
        b = programs.save_draft(raw)
        self.assertEqual((a["version"], b["version"]), (1, 2))
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(programs.load("draft")["title"], "Changed")
        self.assertIsNone(programs.load("active"))

    def test_apply_writes_everything_and_activates(self):
        prog = programs.save_draft(sample())
        out = programs.apply(prog["id"])
        expected = programs.expand(programs.validate(sample()))
        self.assertEqual(out["rides"], len(expected["rides"]))
        self.assertEqual(out["strength"], len(expected["strength"]))
        rows = q.get_workouts(MONDAY.isoformat(), prog["end_date"])
        self.assertEqual(len(rows), out["rides"])
        self.assertTrue(all(r["purpose"] and r["feel"] and r["phase"] for r in rows))
        self.assertIn("Base", q.get_phase_notes())
        self.assertIsNone(programs.load("draft"))
        self.assertEqual(programs.load("active")["id"], prog["id"])

    def test_apply_twice_is_refused(self):
        prog = programs.save_draft(sample())
        programs.apply(prog["id"])
        with self.assertRaises(programs.ProgramError):
            programs.apply(prog["id"])

    def test_replace_existing_removes_planned_but_keeps_done(self):
        planned = q.add_workout({"date": (MONDAY + timedelta(days=1)).isoformat(), "name": "Old plan",
                                 "workout_type": "Endurance", "description": "", "structured_json": None,
                                 "tss_planned": 50, "notes": ""})
        done = q.add_workout({"date": (MONDAY + timedelta(days=2)).isoformat(), "name": "Done ride",
                              "workout_type": "Endurance", "description": "", "structured_json": None,
                              "tss_planned": 50, "notes": ""})
        conn = schema.get_conn()
        conn.execute("UPDATE workouts SET completed=1 WHERE id=?", (done,))
        conn.commit()
        conn.close()
        prog = programs.save_draft(sample())
        found = programs.conflicts(prog)
        self.assertEqual([w["id"] for w in found["rides"]], [planned])
        out = programs.apply(prog["id"], replace_existing=True)
        self.assertEqual(out["removed"], 1)
        self.assertIsNone(q.get_workout(planned))
        self.assertIsNotNone(q.get_workout(done))

    def test_a_planned_race_day_is_never_replaced(self):
        race = q.add_workout({"date": (MONDAY + timedelta(days=5)).isoformat(), "name": "Crit",
                              "workout_type": "Race", "description": "", "structured_json": None,
                              "tss_planned": 80, "notes": ""})
        prog = programs.save_draft(sample())
        self.assertEqual(programs.conflicts(prog)["rides"], [])
        programs.apply(prog["id"], replace_existing=True)
        self.assertIsNotNone(q.get_workout(race))

    def test_a_failure_part_way_changes_nothing(self):
        planned = q.add_workout({"date": (MONDAY + timedelta(days=1)).isoformat(), "name": "Old plan",
                                 "workout_type": "Endurance", "description": "", "structured_json": None,
                                 "tss_planned": 50, "notes": ""})
        prog = programs.save_draft(sample())
        with mock.patch.object(q, "_insert_strength", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                programs.apply(prog["id"], replace_existing=True)
        self.assertIsNotNone(q.get_workout(planned))                                   # the old plan is still there
        self.assertEqual([w["id"] for w in q.get_workouts(MONDAY.isoformat(), prog["end_date"])], [planned])
        self.assertEqual(programs.load("draft")["id"], prog["id"])                     # still a draft
        self.assertIsNone(programs.load("active"))
        programs.apply(prog["id"], replace_existing=True)                              # and a retry works cleanly
        self.assertEqual(len(q.get_workouts(MONDAY.isoformat(), prog["end_date"])),
                         len(programs.expand(programs.validate(sample()))["rides"]))

    def test_keeping_existing_leaves_them(self):
        planned = q.add_workout({"date": (MONDAY + timedelta(days=1)).isoformat(), "name": "Old plan",
                                 "workout_type": "Endurance", "description": "", "structured_json": None,
                                 "tss_planned": 50, "notes": ""})
        programs.apply(programs.save_draft(sample())["id"])
        self.assertIsNotNone(q.get_workout(planned))

    def test_a_new_active_program_archives_the_old_one(self):
        first = programs.save_draft(sample())
        programs.apply(first["id"])
        raw = sample()
        raw["title"] = "Spring build"
        second = programs.save_draft(raw)
        programs.apply(second["id"])
        self.assertEqual(programs.load("active")["title"], "Spring build")
        self.assertEqual(q.get_program_by_id(first["id"])["status"], "archived")


class ToolTests(Base):
    def test_the_tool_saves_a_draft_and_reports_it(self):
        out = json.loads(coach_tools.run_tool("propose_program", sample(), []))
        self.assertTrue(out["saved"])
        self.assertEqual(out["weeks"], 13)
        self.assertEqual(out["version"], 1)
        self.assertGreater(out["rides_on_calendar_if_added"], 10)
        self.assertIn("NOT on their calendar", out["next"])
        self.assertEqual(programs.load("draft")["version"], 1)

    def test_a_revision_replaces_the_draft(self):
        coach_tools.run_tool("propose_program", sample(), [])
        raw = sample()
        raw["phases"][2]["weeks"] = 6
        raw["checkpoints"] = raw["checkpoints"][:1]
        out = json.loads(coach_tools.run_tool("propose_program", raw, []))
        self.assertEqual((out["version"], out["weeks"]), (2, 11))

    def test_bad_input_raises_a_message_the_coach_can_use(self):
        raw = sample()
        raw["phases"][1]["week_template"][0]["workout_type"] = "Spin"
        with self.assertRaises(ValueError) as cm:
            coach_tools.run_tool("propose_program", raw, [])
        self.assertIn("workout_type", str(cm.exception))
        self.assertIsNone(programs.load("draft"))

    def test_the_tool_schema_lists_every_day_and_type(self):
        tool = next(t for t in coach_tools.TOOLS if t["name"] == "propose_program")
        phase = tool["input_schema"]["properties"]["phases"]["items"]["properties"]
        self.assertEqual(phase["week_template"]["items"]["properties"]["day"]["enum"], programs.DAYS)
        self.assertEqual(phase["week_template"]["items"]["properties"]["workout_type"]["enum"], q.WORKOUT_TYPES)
        self.assertIn("propose_program", coach_tools.STATUS_LABELS)


class ContextTests(Base):
    def test_the_active_program_reaches_the_coach_and_the_draft_reaches_program_mode(self):
        import coach_context
        self.assertNotIn("Active program", coach_context.build_context())
        prog = programs.save_draft(sample())
        rules = coach_context.program_rules(programs.load("draft"))
        self.assertIn("CURRENT DRAFT (version 1", rules)
        self.assertIn("Off season 2026 to 2027", rules)
        self.assertNotIn("CURRENT DRAFT", coach_context.program_rules(None))
        programs.apply(prog["id"])
        self.assertIn("Active program: Off season 2026 to 2027", coach_context.build_context())

    def test_the_rules_ask_one_question_at_a_time_and_ban_em_dashes(self):
        import coach_context
        rules = coach_context.PROGRAM_RULES
        self.assertIn("ONE question at a time", rules)
        self.assertNotIn("—", rules)


class PdfTests(unittest.TestCase):
    def test_builds_a_real_pdf(self):
        p = programs.validate(sample())
        days = programs.projected_fitness(p, 60, 55)
        data = program_pdf.build_pdf(p, programs.weekly_ctl(p, days))
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 5000)

    def test_builds_without_a_fitness_line(self):
        self.assertTrue(program_pdf.build_pdf(programs.validate(sample())).startswith(b"%PDF"))

    def test_hostile_and_unusual_text_does_not_break_it(self):
        raw = sample()
        raw["title"] = "Fast & <b>Furious</b> ≥ 100% → 日本"
        raw["goal"] = "Use <script>alert(1)</script> & 5 < 6 > 4 “quotes” — dash"
        raw["phases"][1]["week_template"][0]["name"] = "A&B <i>"
        data = program_pdf.build_pdf(programs.validate(raw))
        self.assertTrue(data.startswith(b"%PDF"))

    def test_a_single_phase_program_works(self):
        raw = sample()
        raw["phases"] = [raw["phases"][2]]
        raw["phases"][0]["weeks"] = 4
        raw["checkpoints"] = []
        raw["notes"] = []
        self.assertTrue(program_pdf.build_pdf(programs.validate(raw)).startswith(b"%PDF"))

    def test_text_helpers(self):
        self.assertEqual(program_pdf._plain("a ≥ b → c"), "a >= b to c")
        self.assertEqual(program_pdf._t("a<b&c"), "a&lt;b&amp;c")
        self.assertEqual(program_pdf.filename({"title": "Off season: 2026/27!"}), "Off_season__2026_27.pdf")


if __name__ == "__main__":
    unittest.main()
