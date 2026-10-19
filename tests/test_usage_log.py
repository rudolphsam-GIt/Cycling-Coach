"""
Every Claude call is logged with its feature, tokens and estimated cost, in the owner's database,
and Settings shows the month's totals per feature.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest import mock

import streamlit as st
from streamlit.testing.v1 import AppTest

import claude_client
from db import schema, usage

PAGES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pages")


def response(model="claude-opus-5-5", *, inp=1000, read=10000, w5=2000, w1=0, out=500, split=True):
    u = SimpleNamespace(input_tokens=inp, cache_read_input_tokens=read, cache_creation_input_tokens=w5 + w1,
                        cache_creation=SimpleNamespace(ephemeral_5m_input_tokens=w5, ephemeral_1h_input_tokens=w1)
                        if split else None, output_tokens=out)
    return SimpleNamespace(model=model, usage=u, stop_reason="end_turn",
                           content=[SimpleNamespace(type="text", text="Ride easy.")])


class UsageLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.owner = os.path.join(self.tmp.name, "owner.db")
        p = mock.patch.object(schema, "DB_PATH", self.owner)
        p.start()
        self.addCleanup(p.stop)
        schema.run_migrations()

    def ask(self, resp, feature="tactics"):
        client = mock.Mock()
        client.beta.messages.create.return_value = resp
        with mock.patch.object(claude_client, "_client", return_value=client):
            return claude_client.ask([{"type": "text", "text": "s"}], [{"role": "user", "content": "hi"}],
                                     feature=feature)

    def rows(self):
        return usage.summary(date.today() - timedelta(days=1), date.today() + timedelta(days=2))

    def test_cost_follows_the_list_prices(self):
        # Opus 5.5 is $4 in, $20 out, $0.20 cache read, writes 1.25x (5 min) and 2x (1 hour) input.
        self.assertAlmostEqual(claude_client.cost("claude-opus-5-5", 1_000_000, 0, 0, 0, 0), 4.00)
        self.assertAlmostEqual(claude_client.cost("claude-opus-5-5", 0, 1_000_000, 0, 0, 0), 0.20)
        self.assertAlmostEqual(claude_client.cost("claude-opus-5-5", 0, 0, 1_000_000, 0, 0), 5.00)
        self.assertAlmostEqual(claude_client.cost("claude-opus-5-5", 0, 0, 0, 1_000_000, 0), 8.00)
        self.assertAlmostEqual(claude_client.cost("claude-sonnet-5-5", 0, 0, 0, 0, 1_000_000), 10.00)
        self.assertIsNone(claude_client.cost("some-other-model", 1, 1, 1, 1, 1))

    def test_a_call_is_logged_with_its_feature_and_cost(self):
        self.assertEqual(self.ask(response()), "Ride easy.")
        [row] = self.rows()
        self.assertEqual((row["feature"], row["calls"], row["input_tokens"], row["cache_read_tokens"],
                          row["cache_write_tokens"], row["output_tokens"]), ("tactics", 1, 1000, 10000, 2000, 500))
        expected = (1000 * 4 + 10000 * 0.2 + 2000 * 5 + 500 * 20) / 1_000_000
        self.assertAlmostEqual(row["cost_usd"], expected)

    def test_a_write_without_the_ttl_split_counts_as_5_minute(self):
        self.ask(response(inp=0, read=0, w5=1000, out=0, split=False))
        self.assertAlmostEqual(self.rows()[0]["cost_usd"], 1000 * 5 / 1_000_000)

    def test_calls_from_another_athlete_land_in_the_owner_database(self):
        other = os.path.join(self.tmp.name, "profiles", "alex.db")
        os.makedirs(os.path.dirname(other))
        with schema.use(other):
            schema.run_migrations()
            self.ask(response(), feature="chat")
        conn = schema.get_conn()
        athlete = conn.execute("SELECT athlete FROM claude_usage").fetchone()[0]
        conn.close()
        self.assertEqual(athlete, "alex")
        with schema.use(other):
            conn = schema.get_conn()
            self.assertIsNone(conn.execute(
                "SELECT name FROM sqlite_master WHERE name='claude_usage'").fetchone())
            conn.close()

    def test_a_logging_problem_never_breaks_a_reply(self):
        with mock.patch.object(schema, "get_conn", side_effect=OSError("disk full")):
            self.assertEqual(self.ask(response()), "Ride easy.")

    def test_month_bounds_cover_the_whole_month(self):
        start, end = usage.month_bounds(2026, 12)
        self.assertLess(start, datetime(2026, 12, 2))
        self.assertGreater(end, datetime(2026, 12, 31))
        self.assertLess(end, datetime(2027, 1, 2))

    def open_settings(self, passcode: str) -> AppTest:
        with mock.patch.object(st, "page_link"), mock.patch("config.USAGE_PASSCODE", passcode):
            at = AppTest.from_file(os.path.join(PAGES, "07_Settings.py"), default_timeout=60).run()
        self.assertFalse(at.exception)
        return at

    @staticmethod
    def usage_shown(at: AppTest) -> bool:
        return any(m.label == "Estimated cost" for m in at.metric)

    def test_usage_stays_hidden_without_a_passcode_set(self):
        self.ask(response(), feature="chat")
        at = self.open_settings("")
        self.assertFalse(self.usage_shown(at))
        self.assertFalse([b for b in at.button if b.label == "Show usage"])
        self.assertTrue(any("USAGE_PASSCODE" in c.value for c in at.caption))

    def test_a_wrong_passcode_keeps_it_hidden(self):
        self.ask(response(), feature="chat")
        with mock.patch("config.USAGE_PASSCODE", "tempo42"):
            at = self.open_settings("tempo42")
            at.text_input(key="usage_code").input("wrong")
            next(b for b in at.button if b.label == "Show usage").click().run()
        self.assertFalse(self.usage_shown(at))
        self.assertTrue(any("doesn't match" in e.value for e in at.error))

    def test_the_passcode_shows_the_month(self):
        self.ask(response(), feature="chat")
        self.ask(response(model="claude-sonnet-5-5"), feature="ride_review")
        with mock.patch("config.USAGE_PASSCODE", "tempo42"), mock.patch.object(st, "page_link"):
            at = self.open_settings("tempo42")
            self.assertFalse(self.usage_shown(at))
            at.text_input(key="usage_code").input("tempo42")
            next(b for b in at.button if b.label == "Show usage").click().run()
            self.assertFalse(at.exception)
            self.assertTrue(self.usage_shown(at))
            self.assertEqual([m.label for m in at.metric][-3:], ["Estimated cost", "Requests", "Read from cache"])
            self.assertEqual(sorted(at.dataframe[-1].value["Feature"]), ["Coach chat", "Ride review"])
            next(b for b in at.button if b.label == "Hide usage").click().run()
            self.assertFalse(self.usage_shown(at))

if __name__ == "__main__":
    unittest.main()
