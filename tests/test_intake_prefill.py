import os
import tempfile
import unittest
from unittest import mock

from streamlit.testing.v1 import AppTest

import intake_import as ii
from db import profiles, schema
from db import queries as q
from tests.test_intake_import import FULL, _row


def _app():
    import streamlit as st
    from components import athlete_form
    if "seed_intake" in st.session_state and athlete_form.PREFILL_KEY not in st.session_state:
        athlete_form.prefill(st.session_state["seed_intake"])
    athlete_form.render_athlete_form()


def _by_label(items, label):
    return next(w for w in items if w.label == label)


class PrefillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        q._settings_cache.clear()
        schema.run_migrations()
        q.set_setting("athlete_name", "Sam")

    def _run(self, **answers):
        intake = ii.parse_row(_row(**{**FULL, "plan_start": "", "plan_end": "", **answers}))
        at = AppTest.from_function(_app, default_timeout=60)
        at.session_state["adding_athlete"] = True
        at.session_state["seed_intake"] = intake
        return at.run(), intake

    def test_fields_are_filled_from_the_response(self):
        at, _ = self._run()
        self.assertFalse(at.exception)
        self.assertEqual(_by_label(at.text_input, "Their name").value, "Alex Rider")
        self.assertEqual(_by_label(at.text_area, "Their goals").value, "Finish the Gorge gran fondo")
        self.assertEqual(_by_label(at.radio, "Which best describes them?").value, "I ride, but without a plan")
        self.assertEqual(_by_label(at.radio, "How active are they right now?").value, "Moderately active")
        self.assertEqual(_by_label(at.selectbox, "Gender").value, "Woman")
        self.assertEqual(_by_label(at.number_input, "Age").value, 41)
        self.assertEqual(_by_label(at.number_input, "Weight (lb)").value, 165.0)
        self.assertEqual(_by_label(at.slider, "Hours a week they can train").value, 7)
        self.assertEqual(_by_label(at.multiselect, "Days they can ride").value, ["Tue", "Thu", "Sat", "Sun"])
        self.assertEqual(_by_label(at.radio, "FTP").value, "I know their FTP")
        self.assertEqual(_by_label(at.number_input, "FTP in watts").value, 210)
        self.assertEqual(_by_label(at.number_input, "Threshold HR").value, 165)
        self.assertEqual(_by_label(at.text_input, "Race name").value, "Gorge Fondo")
        self.assertIn("Filled in from Alex Rider's intake form", at.success[0].value)
        self.assertEqual(len(at.warning), 0)            # no health flags, no clash of names

    def test_health_flags_and_an_existing_name_are_shown(self):
        profiles.create_profile("Alex Rider")
        at, _ = self._run(warning_signs="Yes", injuries="Sore left knee")
        text = " ".join(w.value for w in at.warning)
        self.assertIn("Health answers to read first", text)
        self.assertIn("Sore left knee", text)
        self.assertIn("already a profile called Alex Rider", text)

    def test_unsure_ftp_defaults_to_a_test_when_they_gave_no_number(self):
        at, _ = self._run(ftp_input="", ftp_test="Not sure, you decide")
        self.assertEqual(_by_label(at.radio, "FTP").value, "Estimate it and put an FTP test in their first block")

    def test_their_ftp_and_a_test_starts_them_on_their_ftp(self):
        at, _ = self._run(ftp_input="230", ftp_test="Yes, include a test")
        self.assertEqual(_by_label(at.radio, "FTP").value, "I know their FTP, and put a test in their first block")
        self.assertEqual(_by_label(at.number_input, "FTP in watts").value, 230)
        with mock.patch("ftp_change.apply_new_ftp") as apply:
            _by_label(at.button, "Add athlete").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(apply.call_args.args[0], 230)
        slug = next(p["slug"] for p in profiles.list_profiles() if p["name"] == "Alex Rider")
        with schema.use(profiles.path_for(slug)):
            self.assertEqual(q.get_setting("ftp_choice"), "known_test")
            self.assertEqual(q.get_setting("ftp_estimated"), "0")

    def test_a_test_without_an_ftp_is_still_an_estimate(self):
        at, _ = self._run(ftp_input="", ftp_test="Yes, include a test")
        self.assertEqual(_by_label(at.radio, "FTP").value, "Estimate it and put an FTP test in their first block")
        self.assertFalse([n for n in at.number_input if n.label == "FTP in watts"])

    def test_adding_them_saves_the_intake_with_the_profile(self):
        at, intake = self._run()
        with mock.patch("ftp_change.apply_new_ftp"):
            _by_label(at.button, "Add athlete").click().run()
        self.assertFalse(at.exception)
        slug = next(p["slug"] for p in profiles.list_profiles() if p["name"] == "Alex Rider")
        with schema.use(profiles.path_for(slug)):
            saved = ii.from_setting(q.get_setting(ii.SETTING))
        self.assertEqual(saved["answers"]["equipment"], intake.extras["equipment"])
        self.assertEqual(saved["flags"], [])


if __name__ == "__main__":
    unittest.main()
