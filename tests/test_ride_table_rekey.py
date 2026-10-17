"""
The ride table remembers the selected row by its position. When a sync adds a ride at the top, that
position belongs to another ride, so the table's key follows the rides shown and a changed list starts
with nothing picked.

AppTest doesn't carry a dataframe selection from one run to the next, so the tests check the key.
"""
from __future__ import annotations

import unittest

from streamlit.testing.v1 import AppTest


def _ride(i: int, day: str, name: str) -> dict:
    return {"id": i, "date": day, "name": name, "sport_type": "ride", "duration_seconds": 3600,
            "distance_meters": 30000, "elevation_gain_meters": 300, "avg_power_watts": 200,
            "normalized_power": 210, "avg_hr": 140, "tss": 60, "if_value": 0.7}


def _app():
    import streamlit as st
    from components import ride_detail
    ride_detail.ride_table(st.session_state["ride_list"], key="rides")


TWO = [_ride(2, "2026-10-15", "Tuesday tempo"), _ride(1, "2026-10-13", "Sunday long")]


class RideTableRekeyTests(unittest.TestCase):
    def table_key(self, rides: list) -> str:
        at = AppTest.from_function(_app, default_timeout=30)
        at.session_state["ride_list"] = rides
        at.run()
        self.assertFalse(at.exception)
        return at.dataframe[0].proto.id.split("-", 2)[2]             # the widget's own key

    def test_a_synced_ride_gives_the_table_a_new_key(self):
        synced = [_ride(3, "2026-10-16", "Today's crit")] + TWO
        self.assertNotEqual(self.table_key(TWO), self.table_key(synced))

    def test_the_same_rides_keep_the_same_key(self):
        self.assertEqual(self.table_key(TWO), self.table_key([dict(r) for r in TWO]))
        self.assertTrue(self.table_key(TWO).startswith("rides"))


if __name__ == "__main__":
    unittest.main()
