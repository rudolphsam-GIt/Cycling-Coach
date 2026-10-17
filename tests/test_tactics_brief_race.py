"""
A tactics brief is written for one race. After another race is picked, the page must not show it under
the new race's name or offer to save it into the new race's notes.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

from streamlit.testing.v1 import AppTest

from db import schema, queries as q

PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pages", "06_Competitors.py")
SOON = (date.today() + timedelta(days=10)).isoformat()
LATER = (date.today() + timedelta(days=40)).isoformat()


def _race(name: str, day: str) -> dict:
    return {"name": name, "date": day, "distance_km": 80, "elevation_gain_meters": 800, "category": "A",
            "target_time_seconds": None, "notes": ""}


class TacticsBriefRaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db")),
                  mock.patch("research.tactics.generate_tactics_brief", return_value="Attack on the climb.")):
            p.start()
            self.addCleanup(p.stop)
        schema.run_migrations()
        q.add_race(_race("Hill Climb", SOON))
        q.add_race(_race("Flat Crit", LATER))

    def test_the_brief_stays_with_the_race_it_was_written_for(self):
        at = AppTest.from_file(PAGE, default_timeout=60)
        at.session_state["competitor_profiles"] = [{"name": "Pat Rider", "error": "Not found"}]
        at.run()
        pick = next(s for s in at.selectbox if s.label == "Or pick from your race calendar")
        pick.set_value(f"Hill Climb ({SOON})").run()
        next(b for b in at.button if b.label == "Generate Tactics Brief").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("Attack on the climb." in m.value for m in at.markdown))

        pick = next(s for s in at.selectbox if s.label == "Or pick from your race calendar")
        pick.set_value(f"Flat Crit ({LATER})").run()
        self.assertFalse(at.exception)
        self.assertFalse(any("Attack on the climb." in m.value for m in at.markdown))
        self.assertFalse([b for b in at.button if b.label == "Save to Race Calendar Notes"])

        # Back on the race it was written for, the brief is there to save.
        pick = next(s for s in at.selectbox if s.label == "Or pick from your race calendar")
        pick.set_value(f"Hill Climb ({SOON})").run()
        self.assertTrue(any("Attack on the climb." in m.value for m in at.markdown))
        next(b for b in at.button if b.label == "Save to Race Calendar Notes").click().run()
        notes = {r["name"]: r["notes"] for r in q.get_races()}
        self.assertEqual(notes, {"Hill Climb": "Attack on the climb.", "Flat Crit": ""})


if __name__ == "__main__":
    unittest.main()
