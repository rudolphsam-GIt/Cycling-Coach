"""Building a workout with the coach: design_workout, proposing exact steps, and My workouts.
Run with venv/bin/python -m unittest tests.test_build_workout -v"""
import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

import coach_tools
import workout_recipes as wr
from db import schema, queries as q

SOON = (date.today() + timedelta(days=2)).isoformat()
SS = [{"kind": "warmup", "minutes": 15, "low_pct": 50, "high_pct": 65, "repeat_count": None, "repeat_steps": None},
      {"kind": "repeat", "minutes": None, "low_pct": None, "high_pct": None, "repeat_count": 3,
       "repeat_steps": [{"kind": "interval", "minutes": 20, "low_pct": 88, "high_pct": 93},
                        {"kind": "recovery", "minutes": 5, "low_pct": 50, "high_pct": 60}]},
      {"kind": "cooldown", "minutes": 10, "low_pct": 45, "high_pct": 60, "repeat_count": None, "repeat_steps": None}]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()


class DesignTests(Base):
    def test_design_workout_reports_time_tss_and_wording(self):
        out = json.loads(coach_tools.run_tool("design_workout", {"steps": SS}, []))
        self.assertEqual(out["minutes"], 100)
        self.assertEqual(out["tss"], round(wr.steps_tss(SS)))
        self.assertIn("3 x 20 min at 88 to 93% FTP with 5 min easy", out["description"])

    def test_bad_steps_are_explained(self):
        with self.assertRaises(coach_tools.ToolInputError):
            coach_tools.run_tool("design_workout", {"steps": [{"kind": "interval", "minutes": 20,
                                                               "low_pct": 120, "high_pct": 90}]}, [])
        with self.assertRaises(coach_tools.ToolInputError):
            coach_tools.run_tool("design_workout", {"steps": []}, [])


class ProposeStepsTests(Base):
    def ride(self, **kw):
        return {"date": SOON, "name": "3 x 20 sweet spot", "workout_type": "Sweet Spot",
                "description": wr.describe(SS), "tss_planned": round(wr.steps_tss(SS)),
                "purpose": "Raises the power you can hold.", "feel": "6 to 7 out of 10", "steps": SS, **kw}

    def test_steps_must_match_the_planned_tss(self):
        with self.assertRaises(coach_tools.ToolInputError) as e:
            coach_tools._propose({"workouts": [self.ride(tss_planned=40)]}, [])
        self.assertIn("steps add up to", str(e.exception))

    def test_steps_without_targets_are_still_checked(self):
        free = [{"kind": "interval", "minutes": 120, "low_pct": None, "high_pct": None}]
        real = wr.steps_tss(free)
        self.assertAlmostEqual(real, 2 * 0.55 ** 2 * 100, places=1)       # two hours of easy riding
        with self.assertRaises(coach_tools.ToolInputError) as e:
            coach_tools._propose({"workouts": [self.ride(name="Free ride", workout_type="Endurance",
                                                         steps=free, tss_planned=150)]}, [])
        self.assertIn("steps add up to", str(e.exception))
        coach_tools._propose({"workouts": [self.ride(name="Free ride", workout_type="Endurance",
                                                     steps=free, tss_planned=round(real))]}, [])

    def test_saving_needs_steps(self):
        w = self.ride(save_to_my_workouts=True)
        del w["steps"]
        with self.assertRaises(coach_tools.ToolInputError):
            coach_tools._propose({"workouts": [w]}, [])

    def test_confirmed_card_saves_the_exact_steps_and_the_library_copy(self):
        out = []
        coach_tools._propose({"workouts": [self.ride(save_to_my_workouts=True)]}, out)
        self.assertTrue(out[0]["save"])
        from components import coach_ui
        st = mock.MagicMock()
        st.session_state = {"k": out}
        st.columns.return_value = (mock.MagicMock(), mock.MagicMock())
        st.columns.return_value[0].button.return_value = True
        st.columns.return_value[1].button.return_value = False
        st.container.return_value.__enter__.return_value = None
        with mock.patch.object(coach_ui, "st", st):
            coach_ui.proposal_card("k")
        saved = q.get_workouts(SOON, SOON)[0]
        self.assertEqual(json.loads(saved["structured_json"]), SS)
        mine = q.get_my_workouts()
        self.assertEqual([m["name"] for m in mine], ["3 x 20 sweet spot"])
        self.assertEqual(mine[0]["steps"], SS)
        listed = json.loads(coach_tools.run_tool("get_my_workouts", {}, []))
        self.assertEqual(listed[0]["workout_type"], "Sweet Spot")
        q.delete_my_workout(mine[0]["id"])
        self.assertEqual(coach_tools.run_tool("get_my_workouts", {}, []), "My workouts is empty.")


if __name__ == "__main__":
    unittest.main()
