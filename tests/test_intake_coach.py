import os
import tempfile
import unittest
from unittest import mock

import intake_import as ii
from db import schema
from db import queries as q
from tests.test_intake_import import FULL, TODAY, _row


def _saved(**answers) -> dict:
    return ii.from_setting(ii.to_setting(ii.parse_row(_row(**{**FULL, **answers}), today=TODAY)))


class CoachBlockTests(unittest.TestCase):
    def test_lists_the_riders_own_answers(self):
        text = ii.coach_block(_saved(success="Riding the climbs without walking",
                                     group_rides="Saturday shop ride"))
        self.assertTrue(text.startswith("INTAKE FORM (the athlete's own answers on 10/28/2026"))
        self.assertIn('What would make the next 3 to 6 months a success? "Riding the climbs without walking"', text)
        self.assertIn('"Saturday shop ride"', text)
        self.assertIn('"Power meter, Bike computer (Garmin, Wahoo, Hammerhead)"', text)
        self.assertNotIn("Health flags", text)

    def test_leaves_out_contact_details_and_numbers_the_app_keeps(self):
        text = ii.coach_block(_saved())
        for left_out in ("alex@example.com", "Your weight", "FTP in watts", "Which days can you ride?",
                         "Please confirm", "How can you share your ride history?"):
            self.assertNotIn(left_out, text)

    def test_health_flags_come_first(self):
        text = ii.coach_block(_saved(warning_signs="Yes", injuries="Sore left knee"))
        lines = text.splitlines()
        self.assertTrue(lines[1].startswith("  Health flags. Apply the safety rules"))
        self.assertIn("No hard training until a doctor has seen them.", lines[2])
        self.assertIn("Sore left knee", lines[3])

    def test_nothing_when_there_is_no_intake(self):
        self.assertEqual(ii.coach_block({}), "")
        self.assertEqual(ii.coach_block(ii.from_setting("not json")), "")


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        q._settings_cache.clear()
        schema.run_migrations()

    def test_coach_snapshot_carries_the_intake(self):
        from coach_context import build_context
        self.assertNotIn("INTAKE FORM", build_context())
        q.set_setting(ii.SETTING, ii.to_setting(ii.parse_row(_row(**{**FULL, "hr_meds": "Yes"}), today=TODAY)))
        text = build_context()
        self.assertIn("INTAKE FORM", text)
        self.assertIn("They take medicine that changes heart rate", text)
        self.assertLess(text.index("INTAKE FORM"), text.index("Physiology:"))


if __name__ == "__main__":
    unittest.main()
