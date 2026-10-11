"""Standard workouts get fixed recipes whose steps match the planned TSS.
Run with venv/bin/python -m unittest tests.test_recipes -v"""
import unittest
from datetime import date, timedelta
from unittest import mock

import garmin_workouts as gw
import planning
import workout_recipes as wr

# Sensible planned TSS for each type, from a short taper session up to a big day.
RANGES = {"Recovery": range(15, 121, 5), "Endurance": range(25, 301, 5), "Long Ride": range(60, 351, 10),
          "Tempo": range(40, 201, 5), "Sweet Spot": range(40, 221, 5), "Threshold": range(40, 201, 5), "VO2 Max": range(35, 181, 5),
          "Sprint/Anaerobic": range(30, 151, 5)}


class RecipeTests(unittest.TestCase):
    def test_every_standard_workout_lands_within_ten_percent_of_its_tss(self):
        for wtype, tss_range in RANGES.items():
            for tss in tss_range:
                with self.subTest(wtype=wtype, tss=tss):
                    steps = gw.check_steps(wr.build(wtype, tss))
                    self.assertLessEqual(abs(wr.steps_tss(steps) / tss - 1), wr.TOLERANCE)

    def test_hard_sessions_keep_their_intervals(self):
        for wtype in ("Tempo", "Sweet Spot", "Threshold", "VO2 Max", "Sprint/Anaerobic"):
            steps = wr.build(wtype, 100)
            reps = [s for s in steps if s["kind"] == "repeat"]
            self.assertTrue(reps and reps[0]["repeat_count"] >= wr.RECIPES[wtype]["reps"][0], wtype)

    def test_out_of_reach_and_unknown_types(self):
        with self.assertRaises(wr.RecipeError):
            wr.build("Threshold", 15)
        with self.assertRaises(KeyError):
            wr.build("Race", 100)

    def test_which_workouts_use_a_recipe(self):
        self.assertTrue(wr.uses_recipe({"workout_type": "Threshold", "description": ""}))
        self.assertTrue(wr.uses_recipe({"workout_type": "VO2 Max",
                                        "description": "5 x 4 min\nAuto-generated · Build · week 2"}))
        self.assertFalse(wr.uses_recipe({"workout_type": "Threshold", "description": "3x12 at 92%"}))
        self.assertFalse(wr.uses_recipe({"workout_type": "Race", "description": ""}))

    def test_build_steps_uses_the_recipe_without_claude(self):
        w = {"name": "Threshold", "workout_type": "Threshold", "tss_planned": 90,
             "description": "Auto-generated · Build · week 1"}
        with mock.patch.object(gw, "get_setting", return_value="300"), \
                mock.patch.object(gw.claude_client, "structured", side_effect=AssertionError("no Claude")):
            steps = gw.build_steps(w)
        self.assertAlmostEqual(wr.steps_tss(steps), 90, delta=9)

    def test_written_workouts_still_go_to_claude(self):
        w = {"name": "Over unders", "workout_type": "Threshold", "tss_planned": 90,
             "description": "3 x 12 min over unders 95/105%"}
        fake = {"steps": [{"kind": "interval", "minutes": 60, "low_pct": 90, "high_pct": 100,
                           "repeat_count": None, "repeat_steps": None}]}
        with mock.patch.object(gw, "get_setting", return_value="300"), \
                mock.patch.object(gw.claude_client, "structured", return_value=fake) as call:
            gw.build_steps(w)
        call.assert_called_once()

    def test_generated_blocks_spell_out_the_session(self):
        start = date(2026, 10, 12)
        plan = planning.generate_block(75, 85, start + timedelta(weeks=8), "Threshold", start)
        thr = next(w for w in plan if w["workout_type"] == "Threshold" and w["phase"] != planning.TAPER_LABEL)
        self.assertIn("at 95 to 100% FTP", thr["description"])
        self.assertTrue(wr.uses_recipe(thr))
        for w in plan:
            if wr.uses_recipe(w):
                steps = wr.build(w["workout_type"], w["tss_planned"])
                self.assertLessEqual(abs(wr.steps_tss(steps) / w["tss_planned"] - 1), wr.TOLERANCE)


if __name__ == "__main__":
    unittest.main()


class SweetSpotTests(unittest.TestCase):
    def test_sweet_spot_is_a_full_workout_type(self):
        from db.queries import WORKOUT_TYPES
        from metrics import explain
        self.assertIn("Sweet Spot", WORKOUT_TYPES)
        self.assertIn("88 to 93%", explain.PURPOSE["Sweet Spot"])
        self.assertTrue(explain.feel_for("Sweet Spot").startswith("6 to 7"))
        steps = wr.build("Sweet Spot", 110)
        self.assertIn("at 88 to 93% FTP", wr.describe(steps))


class OpenersTests(unittest.TestCase):
    def test_openers_are_short_with_a_few_efforts(self):
        start = date(2026, 10, 12)
        race = start + timedelta(weeks=8, days=6)
        plan = planning.generate_block(75, 85, race, "Threshold", start)
        eve = next(w for w in plan if w["date"] == (race - timedelta(days=1)).isoformat())
        steps = wr.steps_for(eve)
        self.assertEqual(steps, wr.OPENERS)
        self.assertLessEqual(sum(s["minutes"] for s in wr._leaves(steps)), 40)
        self.assertAlmostEqual(eve["tss_planned"], wr.steps_tss(steps), delta=1)
        self.assertIn("4 x 30 s at 115 to 125% FTP", eve["description"])
        with mock.patch.object(gw, "get_setting", return_value="300"), \
                mock.patch.object(gw.claude_client, "structured", side_effect=AssertionError("no Claude")):
            self.assertEqual(gw.build_steps(eve), wr.OPENERS)
