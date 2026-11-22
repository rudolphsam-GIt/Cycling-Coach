"""Where the prompt cache points go, so Claude reuses what it can.
Run with venv/bin/python -m unittest tests.test_prompt_cache -v"""
import unittest
from unittest import mock

import claude_client
import coach_context

CACHE = {"type": "ephemeral"}


class SystemBlockTests(unittest.TestCase):
    def blocks(self, extra=""):
        with mock.patch.object(coach_context, "build_context", return_value="SNAPSHOT"):
            return coach_context.system_blocks(extra)

    def test_instructions_and_snapshot_each_get_a_cache_point(self):
        blocks = self.blocks()
        self.assertEqual(len(blocks), 2)
        self.assertEqual([b.get("cache_control") for b in blocks], [CACHE, CACHE])
        self.assertEqual(blocks[1]["text"], "SNAPSHOT")

    def test_extra_rules_come_last_so_they_do_not_break_the_shared_prefix(self):
        plain, report = self.blocks(), self.blocks("REPORT RULES")
        self.assertEqual(report[:2], plain)
        self.assertEqual(report[2], {"type": "text", "text": "REPORT RULES"})
        self.assertNotIn("REPORT RULES", report[0]["text"])


class RequestTests(unittest.TestCase):
    def request(self, **kw):
        return claude_client._request([{"type": "text", "text": "s"}], [], "low", 100, **kw)

    def test_conversations_cache_the_tail(self):
        self.assertEqual(self.request()["cache_control"], CACHE)

    def test_one_shot_calls_skip_the_tail_cache(self):
        self.assertNotIn("cache_control", self.request(cache_tail=False))

    def test_structured_caches_only_the_fixed_system_prompt(self):
        reply = mock.Mock(stop_reason="end_turn", content=[mock.Mock(type="text", text="{}")])
        with mock.patch.object(claude_client, "_client") as client, \
                mock.patch.object(claude_client, "_log"):
            client.return_value.beta.messages.create.return_value = reply
            claude_client.structured("SYSTEM", "prompt", {"type": "object"})
        sent = client.return_value.beta.messages.create.call_args.kwargs
        self.assertNotIn("cache_control", sent)
        self.assertEqual(sent["system"], [{"type": "text", "text": "SYSTEM", "cache_control": CACHE}])


if __name__ == "__main__":
    unittest.main()
