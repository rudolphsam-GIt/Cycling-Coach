"""The training research library and the coach tool that reads it.
Run with venv/bin/python -m unittest tests.test_knowledge -v"""
import re
import unittest
from unittest import mock

import coach_context
import coach_tools
import knowledge

EXPECTED_TOPICS = {"intensity_distribution", "intervals", "periodization_taper", "weekly_structure",
                   "time_available", "age", "women", "recovery_load", "strength", "testing",
                   "nutrition", "environment"}


class LibraryTests(unittest.TestCase):
    def test_every_planned_topic_is_present(self):
        self.assertEqual(set(knowledge.list_topics()), EXPECTED_TOPICS)

    def test_files_have_front_matter_and_sections(self):
        for key in knowledge.list_topics():
            topic = knowledge._library()[key]
            with self.subTest(topic=key):
                for field in knowledge.REQUIRED_FIELDS:
                    self.assertTrue(topic["meta"].get(field), f"{key} is missing {field}")
                self.assertEqual(topic["path"].stem, key)
                for section in knowledge.REQUIRED_SECTIONS:
                    self.assertIn(section, topic["body"])

    def test_findings_are_graded_and_referenced(self):
        for key in knowledge.list_topics():
            body = knowledge._library()[key]["body"]
            with self.subTest(topic=key):
                self.assertRegex(body, r"\*\*Evidence: (Strong|Moderate|Limited)")
                references = body.split("## References", 1)[1]
                self.assertGreaterEqual(len(re.findall(r"^\d+\.", references, re.M)), 5)

    def test_principles_ride_along_in_the_system_prompt(self):
        core = knowledge.principles()
        self.assertTrue(core)
        self.assertLess(len(core.split()), 1000)
        with mock.patch.object(coach_context, "build_context", return_value=""):
            text = coach_context.system_blocks()[0]["text"]
        self.assertIn(core, text)
        self.assertIn("get_training_research", text)


class ToolTests(unittest.TestCase):
    def run_tool(self, args):
        return coach_tools.run_tool("get_training_research", args, [])

    def test_tool_enum_matches_library(self):
        tool = next(t for t in coach_tools.TOOLS if t["name"] == "get_training_research")
        enum = tool["input_schema"]["properties"]["topics"]["items"]["enum"]
        self.assertEqual(set(enum), EXPECTED_TOPICS)
        self.assertIn("get_training_research", coach_tools.STATUS_LABELS)

    def test_every_topic_loads(self):
        for key in knowledge.list_topics():
            with self.subTest(topic=key):
                self.assertIn("## Rules for the coach", self.run_tool({"topics": [key]}))

    def test_several_topics_come_back_together(self):
        text = self.run_tool({"topics": ["age", "time_available", "age"]})
        self.assertEqual(text.count("## Rules for the coach"), 2)

    def test_unknown_topic_is_refused(self):
        with self.assertRaises(coach_tools.ToolInputError):
            self.run_tool({"topics": ["doping"]})

    def test_too_many_or_no_topics_are_refused(self):
        for topics in ([], ["age", "women", "strength", "testing"], "age", [3]):
            with self.subTest(topics=topics), self.assertRaises(coach_tools.ToolInputError):
                self.run_tool({"topics": topics})


if __name__ == "__main__":
    unittest.main()
