import json
import re
import unittest

import intake_form as f
from metrics.explain import ACTIVITY_LEVEL, GENDER_LABELS, RIDER_TYPES


def _q(key):
    return next(q for q in f.QUESTIONS if q.key == key)


class IntakeFormTests(unittest.TestCase):
    def test_keys_and_titles_are_unique(self):
        # The importer finds each answer by its column title in the response sheet.
        keys = [q.key for q in f.QUESTIONS]
        titles = [q.title for q in f.QUESTIONS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(titles), len(set(titles)))

    def test_choices_match_the_app_word_for_word(self):
        self.assertEqual(_q("rider_type").choices, tuple(RIDER_TYPES))
        self.assertEqual(_q("activity").choices, tuple(ACTIVITY_LEVEL))
        self.assertEqual(_q("gender").choices, tuple(GENDER_LABELS))
        self.assertEqual(_q("units").choices, tuple(f.UNIT_CHOICES))
        self.assertEqual(_q("available_days").choices, tuple(f.DAY_NAMES))

    def test_ftp_test_answers_map_to_add_athlete_choices(self):
        from components.athlete_form import FTP_CHOICES
        self.assertEqual(_q("ftp_test").choices, tuple(f.FTP_TEST_CHOICES))
        self.assertLessEqual(set(f.FTP_TEST_CHOICES.values()) - {None}, set(FTP_CHOICES.values()))

    def test_plan_has_start_and_end_dates(self):
        self.assertEqual(_q("plan_start").kind, "date")
        self.assertEqual(_q("plan_end").kind, "date")

    def test_what_add_athlete_needs_is_required(self):
        for key in ("name", "goal_text", "rider_type", "activity", "units", "weekly_hours",
                    "available_days", "doctor_limit", "warning_signs", "hr_meds", "consent"):
            self.assertTrue(_q(key).required, key)

    def test_question_kinds_are_ones_the_script_builds(self):
        kinds = {"text", "email", "number", "paragraph", "choice", "checkbox", "list", "date"}
        for q in f.QUESTIONS:
            self.assertIn(q.kind, kinds, q.key)
            self.assertEqual(bool(q.choices), q.kind in {"choice", "checkbox", "list"}, q.key)
            self.assertEqual(q.bounds is not None, q.kind == "number", q.key)

    def test_script_carries_every_question(self):
        script = f.apps_script()
        form = json.loads(re.search(r"const FORM = (\{.*?\n\});", script, re.S).group(1))
        titles = [q["title"] for s in form["sections"] for q in s["questions"]]
        self.assertEqual(titles, [q.title for q in f.QUESTIONS])
        self.assertIn("function createIntakeForm()", script)

    def test_rider_facing_text_has_no_em_dashes(self):
        text = [f.FORM_DESCRIPTION, f.CONFIRMATION] + [s.title + s.description for s in f.SECTIONS]
        text += [q.title + q.help + "".join(q.choices) for q in f.QUESTIONS]
        for t in text:
            self.assertNotIn("—", t)


if __name__ == "__main__":
    unittest.main()
