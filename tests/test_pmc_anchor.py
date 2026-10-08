import os
import tempfile
import unittest
from datetime import date, timedelta

from db import schema


class PmcAnchorTest(unittest.TestCase):
    """CTL for a given day must not depend on the window a page asks for."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = schema.DB_PATH
        schema.DB_PATH = os.path.join(self.tmp.name, "t.db")
        schema.run_migrations()
        from db import queries
        queries.set_setting("ctl_start", 50)
        queries.set_setting("atl_start", 40)
        conn = schema.get_conn()
        for i in range(0, 200, 2):
            d = (date.today() - timedelta(days=i)).isoformat()
            conn.execute(
                "INSERT INTO activities (source, external_id, date, name, sport_type, tss) "
                "VALUES ('test', ?, ?, 'r', 'Ride', 60)", (f"x{i}", d))
        conn.commit()
        conn.close()

    def tearDown(self):
        schema.DB_PATH = self.old
        self.tmp.cleanup()

    def test_same_ctl_for_today_whatever_the_window(self):
        from metrics.training_load import compute_pmc, get_current_metrics
        today = date.today()
        short = compute_pmc(today - timedelta(days=7), today).iloc[-1]
        long = compute_pmc(today - timedelta(days=365), today).iloc[-1]
        self.assertEqual(short["ctl"], long["ctl"])
        self.assertEqual(short["atl"], long["atl"])
        self.assertEqual(get_current_metrics()["ctl"], short["ctl"])

    def test_days_before_history_hold_the_seed(self):
        from metrics.training_load import compute_pmc
        today = date.today()
        df = compute_pmc(today - timedelta(days=400), today)
        self.assertEqual(df.iloc[0]["ctl"], 50)
        self.assertEqual(df.iloc[0]["atl"], 40)


if __name__ == "__main__":
    unittest.main()
