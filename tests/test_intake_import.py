import csv
import io
import unittest
from datetime import date

import intake_import as ii
from components.athlete_form import _SHARED

TODAY = date(2026, 10, 29)          # a Thursday, so the next Monday is Nov 2


def _row(**answers) -> dict:
    """A sheet row the way Google writes it, with question titles as the columns."""
    row = {"Timestamp": answers.pop("Timestamp", "10/28/2026 9:15:02")}
    row.update({q.title: "" for q in ii.QUESTIONS})
    row.update({ii.BY_KEY[k].title: v for k, v in answers.items()})
    return row


def _csv(*rows) -> bytes:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    return ("﻿" + out.getvalue()).encode("utf-8")       # Sheets downloads carry a BOM


FULL = dict(
    name="Alex Rider", email="alex@example.com", age="41", gender="Woman",
    units="Pounds and miles", weight="165", rider_type="I ride, but without a plan",
    activity="Moderately active", goal_text="Finish the Gorge gran fondo",
    race_name="Gorge Fondo", race_date="2027-05-15", plan_start="11/2/2026", plan_end="5/15/2027",
    weekly_hours="7", available_days="Tuesday, Thursday, Saturday, Sunday",
    ftp_input="210", ftp_test="No, use the FTP I gave above", lthr_input="165", max_hr="186",
    resting_hr="52", current_ctl="45",
    equipment="Power meter, Bike computer (Garmin, Wahoo, Hammerhead)",
    doctor_limit="No", warning_signs="No", hr_meds="No",
)


class ParseRowTests(unittest.TestCase):
    def test_full_response_becomes_add_athlete_answers(self):
        i = ii.parse_row(_row(**FULL), today=TODAY)
        a = i.answers
        self.assertEqual(a["name"], "Alex Rider")
        self.assertEqual((a["unit"], a["dist_unit"]), ("lb", "mi"))
        self.assertAlmostEqual(a["weight"], 74.8, places=1)            # stored in kg
        self.assertEqual(a["gender"], "woman")
        self.assertEqual(a["rider_type"], "I ride, but without a plan")
        self.assertEqual(a["available_days"], ["Tue", "Thu", "Sat", "Sun"])
        self.assertEqual((a["ftp_choice"], a["ftp_input"]), ("known", 210))
        self.assertEqual((a["lthr_input"], a["max_hr"], a["resting_hr"], a["current_ctl"]), (165, 186, 52, 45))
        self.assertEqual(a["plan_start"], date(2026, 11, 2))
        self.assertEqual(a["plan_weeks"], 28)
        self.assertEqual(a["race_date"], date(2027, 5, 15))
        self.assertEqual(i.flags, [])
        self.assertEqual(i.notes, [])

    def test_answers_cover_everything_save_athlete_reads(self):
        a = ii.parse_row(_row(**FULL), today=TODAY).answers
        shared = set(_SHARED) - {"days_per_week"}          # save_athlete counts it from available_days
        for key in shared | {"available_days", "max_hr", "resting_hr", "current_ctl",
                             "plan_start", "plan_weeks"}:
            self.assertIn(key, a)

    def test_extras_keep_every_answer_as_given(self):
        x = ii.parse_row(_row(**FULL), today=TODAY).extras
        self.assertEqual(x["equipment"], "Power meter, Bike computer (Garmin, Wahoo, Hammerhead)")
        self.assertEqual(x["email"], "alex@example.com")
        self.assertNotIn("success", x)                                 # blank answers left out

    def test_blank_optionals_and_metric_units(self):
        i = ii.parse_row(_row(name="Jo", units="Kilograms and kilometers", weight="62.5",
                              ftp_test="Not sure, you decide"), today=TODAY)
        a = i.answers
        self.assertEqual((a["unit"], a["dist_unit"], a["weight"]), ("kg", "km", 62.5))
        self.assertEqual(a["gender"], "unspecified")
        self.assertIsNone(a["ftp_choice"])
        for key in ("age", "ftp_input", "lthr_input", "plan_start", "plan_weeks", "race_date"):
            self.assertIsNone(a[key], key)
        self.assertEqual(a["available_days"], [])

    def test_known_ftp_without_a_number_is_left_for_sam(self):
        i = ii.parse_row(_row(name="Jo", ftp_test="No, use the FTP I gave above"), today=TODAY)
        self.assertIsNone(i.answers["ftp_choice"])
        self.assertEqual(len(i.notes), 1)

    def test_past_dates_are_dropped_with_a_note(self):
        i = ii.parse_row(_row(name="Jo", race_date="2026-09-01", plan_start="2026-10-01"), today=TODAY)
        self.assertIsNone(i.answers["race_date"])
        self.assertIsNone(i.answers["plan_start"])
        self.assertEqual(len(i.notes), 2)

    def test_plan_end_alone_counts_from_next_monday(self):
        a = ii.parse_row(_row(name="Jo", plan_end="2026-12-28"), today=TODAY).answers
        self.assertEqual(a["plan_weeks"], 8)

    def test_plan_length_is_kept_within_app_limits(self):
        i = ii.parse_row(_row(name="Jo", plan_start="2026-11-02", plan_end="2029-01-01"), today=TODAY)
        self.assertEqual(i.answers["plan_weeks"], 60)
        self.assertIn("60", i.notes[0])
        short = ii.parse_row(_row(name="Jo", plan_start="2026-11-02", plan_end="2026-11-05"), today=TODAY)
        self.assertEqual(short.answers["plan_weeks"], 2)

    def test_unlikely_weight_is_left_blank(self):
        i = ii.parse_row(_row(name="Jo", units="Pounds and miles", weight="40"), today=TODAY)
        self.assertIsNone(i.answers["weight"])
        self.assertEqual(len(i.notes), 1)


class SaveTests(unittest.TestCase):
    def setUp(self):
        import os
        import tempfile
        from unittest import mock
        from db import schema
        from db import queries as q
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        q._settings_cache.clear()
        schema.run_migrations()
        q.set_setting("athlete_name", "Sam")

    def test_imported_answers_save_through_add_athlete(self):
        from unittest import mock
        from components import athlete_form
        from db import schema
        from db.queries import get_setting
        answers = ii.parse_row(_row(**{**FULL, "plan_start": ""})).answers
        with mock.patch("ftp_change.apply_new_ftp"):
            result = athlete_form.save_athlete(answers, None)
        with schema.use(result["path"]):
            self.assertEqual(get_setting("athlete_name"), "Alex Rider")
            self.assertEqual(get_setting("available_days"), "Tue,Thu,Sat,Sun")
            self.assertEqual(get_setting("weight_unit"), "lb")
            self.assertEqual(get_setting("goal_text"), "Finish the Gorge gran fondo")


class HealthFlagTests(unittest.TestCase):
    def test_no_flags_when_all_clear(self):
        self.assertEqual(ii.health_flags({"doctor_limit": "No", "warning_signs": "No", "hr_meds": "No"}), [])

    def test_each_concern_is_flagged(self):
        flags = ii.health_flags({"doctor_limit": "Yes", "warning_signs": "Yes", "hr_meds": "Not sure",
                                 "injuries": "Sore left knee", "conditions": "Asthma"})
        self.assertEqual(len(flags), 5)
        self.assertIn("No hard training", flags[1])
        self.assertIn("Sore left knee", flags[3])


class ReadResponsesTests(unittest.TestCase):
    def test_reads_sheet_newest_first_and_skips_rows_without_a_name(self):
        data = _csv(_row(**FULL),
                    _row(name="Jo", Timestamp="10/29/2026 7:00:00"),
                    _row(Timestamp="10/29/2026 8:00:00"))
        names = [i.name for i in ii.read_responses(data)]
        self.assertEqual(names, ["Jo", "Alex Rider"])

    def test_other_files_are_refused(self):
        with self.assertRaises(ValueError):
            ii.read_responses(b"Date,Distance\n2026-10-01,40\n")
        with self.assertRaises(ValueError):
            ii.read_responses(b"")

    def test_day_names_never_contain_each_other(self):
        # Checkbox cells are matched by name, since some choices have commas of their own.
        days = list(ii.DAY_NAMES)
        for d in days:
            self.assertEqual([o for o in days if d in o], [d])


if __name__ == "__main__":
    unittest.main()
