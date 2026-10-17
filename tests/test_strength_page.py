"""The Strength page's Log Completed Session form offers a weight box for every lift that takes one."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from streamlit.testing.v1 import AppTest

from db import schema, queries as q

PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pages", "04_Strength_Training.py")


class LogFormTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()
        q.set_setting("weight_unit", "kg")

    def weight_boxes(self, session_name: str) -> list[str]:
        at = AppTest.from_file(PAGE, default_timeout=60).run()
        next(b for b in at.button if b.label == f"Log: {session_name}").click().run()
        return [n.label for n in at.number_input if "weight used" in n.label]

    def test_percent_of_1rm_lifts_get_a_weight_box(self):
        boxes = self.weight_boxes("Session A — Lower Power")
        self.assertIn("Back Squat, weight used (kg)", boxes)      # 75-85% 1RM
        self.assertIn("Romanian Deadlift, weight used (kg)", boxes)

    def test_bodyweight_moves_do_not_and_optionally_weighted_ones_do(self):
        at = AppTest.from_file(PAGE, default_timeout=60).run()
        at.selectbox[0].set_value("Build Phase (Explosive Power)").run()
        next(b for b in at.button if b.label == "Log: Session B — Maintenance + Core").click().run()
        boxes = [n.label for n in at.number_input if "weight used" in n.label]
        self.assertNotIn("Nordic Hamstring Curl, weight used (kg)", boxes)     # Bodyweight
        self.assertIn("Calf Raises (single leg), weight used (kg)", boxes)     # Bodyweight/weighted
        self.assertIn("Goblet Squat, weight used (kg)", boxes)


if __name__ == "__main__":
    unittest.main()
