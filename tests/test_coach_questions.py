import unittest

from components.coach_ui import split_questions


class SplitQuestionsTests(unittest.TestCase):
    def test_closing_question_is_split_off(self):
        body, ask = split_questions("Here is week one.\n\nTuesday is VO2 max.\n\nWhich of these would you change?")
        self.assertEqual(body, "Here is week one.\n\nTuesday is VO2 max.")
        self.assertEqual(ask, "Which of these would you change?")

    def test_no_question_leaves_the_reply_alone(self):
        self.assertEqual(split_questions("Rest tomorrow.\n\nRide easy on Thursday."),
                         ("Rest tomorrow.\n\nRide easy on Thursday.", ""))

    def test_question_in_the_middle_is_not_highlighted(self):
        reply = "Why 3x15? It builds sweet spot time.\n\nThat is the plan for this week."
        self.assertEqual(split_questions(reply), (reply, ""))

    def test_numbered_questions_and_bold_endings_count(self):
        body, ask = split_questions("Draft below.\n\nA few things first:\n1. **Can you ride Friday?**\n"
                                    "2. Do you have a trainer?")
        self.assertEqual(body, "Draft below.")
        self.assertIn("Do you have a trainer?", ask)

    def test_options_listed_after_the_question_stay_with_it(self):
        body, ask = split_questions("Two ways to go.\n\nWhich do you prefer?\n\n- Ski Saturday\n- Ride Saturday")
        self.assertEqual(body, "Two ways to go.")
        self.assertTrue(ask.startswith("Which do you prefer?"))
        self.assertTrue(ask.endswith("- Ride Saturday"))

    def test_a_list_with_no_question_before_it_is_not_highlighted(self):
        reply = "This week:\n\n- Tuesday VO2 max\n- Saturday long ride"
        self.assertEqual(split_questions(reply), (reply, ""))

    def test_reply_that_is_only_a_question(self):
        self.assertEqual(split_questions("Which day works?"), ("", "Which day works?"))

    def test_empty_reply(self):
        self.assertEqual(split_questions(""), ("", ""))


if __name__ == "__main__":
    unittest.main()
