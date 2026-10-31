"""The draft program as a web page for the athlete to comment on.
Run with venv/bin/python -m pytest tests/test_program_page.py"""
import re
import unittest
from datetime import date

import program_page
import programs
from tests.test_programs import sample


def page(**changes):
    p = programs.validate({**sample(), **changes})
    return p, program_page.build_html({**p, "version": 3}, "Thomas", today=date(2026, 10, 30))


class ProgramPageTests(unittest.TestCase):
    def test_title_and_ask(self):
        _, html = page()
        self.assertIn("<title>Thomas training plan</title>", html)
        self.assertIn("Draft plan for Thomas · version 3", html)
        self.assertIn("Tell me what to change", html)

    def test_every_week_and_typical_day_can_be_pointed_at(self):
        p, html = page()
        for w in range(1, p["total_weeks"] + 1):
            self.assertIn(f'id="week-{w}"', html)
        self.assertIn('id="phase-base-tue"', html)
        self.assertIn("Base, Tue", html)
        self.assertIn('id="phase-base-strength"', html)
        self.assertIn('id="checkpoint-week-5"', html)

    def test_ids_are_unique(self):
        _, html = page()
        ids = re.findall(r'id="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)))

    def test_coach_text_is_escaped(self):
        _, html = page(goal='Go <b>fast</b> & "far"')
        self.assertIn("Go &lt;b&gt;fast&lt;/b&gt; &amp; &quot;far&quot;", html)
        self.assertNotIn("<b>fast</b>", html)

    def test_bars_share_one_scale(self):
        p, html = page()
        heights = [float(h) for h in re.findall(r'class="bar[^"]*" style="height:([\d.]+)%', html)]
        self.assertEqual(len(heights), p["total_weeks"])
        self.assertEqual(max(heights), 100.0)
        self.assertEqual(heights[0], 0.0)           # the Reset weeks are off

    def test_lighter_and_hand_set_weeks_are_marked(self):
        _, html = page(tss_overrides={"6": 450})
        self.assertIn("Lighter week", html)
        self.assertIn("Set by hand", html)

    def test_load_line_says_which_way_it_goes(self):
        p = programs.validate(sample())["phases"][1]
        self.assertIn("250 rising to 330", program_page.phase_load(p))
        self.assertIn("330 easing to 250", program_page.phase_load(
            {**p, "weekly_tss_start": 330, "weekly_tss_end": 250}))

    def test_no_owner_name_when_blank(self):
        p = programs.validate(sample())
        html = program_page.build_html(p)
        self.assertIn(f"<title>{p['title']}</title>", html)
        self.assertIn("Draft plan<", html)


if __name__ == "__main__":
    unittest.main()
