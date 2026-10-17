"""
The add workout and add race forms need a name. Pressing Add with the name blank must keep what was
typed in the other fields and say what is missing, not clear the form and drop it all.

clear_on_submit is done by the browser, which AppTest doesn't run, so the tests also check the flag.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

from streamlit.testing.v1 import AppTest

from components import calendar_dnd
from db import schema, queries as q

PAGES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pages")
DAY = (date.today() + timedelta(days=1)).isoformat()


def _field(items, label):
    return next(w for w in items if w.label.startswith(label))


def _form(at, form_id):
    """The form block's proto, found by walking the element tree."""
    todo = [at._tree]
    while todo:
        node = todo.pop()
        p = getattr(node, "proto", None)
        if type(p).__name__ == "Block" and p.HasField("form") and p.form.form_id == form_id:
            return p.form
        todo.extend(getattr(node, "children", {}).values())
    raise AssertionError(f"no form {form_id}")


class BlankNameFormTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # The calendar keeps its registered component in a module global, but each AppTest has its own
        # registry. Reset it after, so a later AppTest of the Plan page registers it again.
        for p in (mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db")),
                  mock.patch.object(calendar_dnd, "_component", None)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()

    def test_add_workout_keeps_the_typed_fields_when_the_name_is_blank(self):
        at = AppTest.from_file(os.path.join(PAGES, "02_Training_Planner.py"), default_timeout=60)
        at.session_state["cal_sel"] = DAY
        at.session_state["add_workout_date"] = DAY
        at.run()
        self.assertFalse(_form(at, "workout_form").clear_on_submit)
        _field(at.number_input, "Planned TSS").set_value(85)
        _field(at.text_area, "Description or notes").set_value("4x8 min hard")
        at.button(key="FormSubmitter:workout_form-Add to planner").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(q.get_workouts(DAY, DAY), [])
        self.assertTrue(any("name" in w.value for w in at.warning))
        self.assertEqual(_field(at.number_input, "Planned TSS").value, 85)
        self.assertEqual(_field(at.text_area, "Description or notes").value, "4x8 min hard")

        _field(at.text_input, "Workout name").set_value("Threshold")
        at.button(key="FormSubmitter:workout_form-Add to planner").click().run()
        added = q.get_workouts(DAY, DAY)
        self.assertEqual([(w["name"], w["tss_planned"]) for w in added], [("Threshold", 85)])

    def test_add_race_keeps_the_typed_fields_when_the_name_is_blank(self):
        at = AppTest.from_file(os.path.join(PAGES, "03_Race_Prep.py"), default_timeout=60)
        at.run()
        self.assertFalse(_form(at, "add_race_form").clear_on_submit)
        _field(at.text_area, "Notes").set_value("Hilly circuit")
        at.button(key="FormSubmitter:add_race_form-Add Race").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(q.get_races(), [])
        self.assertTrue(any("name" in w.value for w in at.warning))
        self.assertEqual(_field(at.text_area, "Notes").value, "Hilly circuit")

        _field(at.text_input, "Race name").set_value("Crit #1")
        at.button(key="FormSubmitter:add_race_form-Add Race").click().run()
        self.assertEqual([(r["name"], r["notes"]) for r in q.get_races()], [("Crit #1", "Hilly circuit")])
        self.assertEqual(_field(at.text_area, "Notes").value, "")         # cleared after a real add
        self.assertEqual(_field(at.text_input, "Race name").value, "")


if __name__ == "__main__":
    unittest.main()
