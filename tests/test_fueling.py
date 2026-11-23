"""
Carbs during a race. The rider picks the number, and the app suggests a starting point from
knowledge/nutrition.md: nothing under 45 minutes, optional to 75, 30 to 60 g an hour to 2 hours,
60 to 90 g an hour beyond. Feeds come every 20 minutes, each a third of the hourly amount.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from streamlit.testing.v1 import AppTest

from db import schema
from metrics import fueling

PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pages", "03_Race_Prep.py")


class SuggestTests(unittest.TestCase):
    def test_the_starting_point_follows_the_race_length(self):
        self.assertEqual(fueling.suggest(0.5)["g_per_h"], 0)          # 30 min, water only
        self.assertEqual(fueling.suggest(1.0)["g_per_h"], 0)          # a 60 min crit, optional
        self.assertEqual(fueling.suggest(1.5)["g_per_h"], 60)
        self.assertIn("30 to 60", fueling.suggest(1.5)["range"])
        self.assertIn("60 to 90", fueling.suggest(3.0)["range"])
        self.assertEqual(fueling.suggest(3.0)["g_per_h"], 60)         # 90 only after practice

    def test_feeds_every_20_minutes_add_up_to_the_hourly_rate(self):
        self.assertEqual(fueling.feeds(2.0, 60), [(20, 20.0), (40, 20.0), (60, 20.0), (80, 20.0), (100, 20.0)])
        self.assertEqual(fueling.feeds(1.0, 0), [])

    def test_notes_for_high_intakes(self):
        self.assertEqual(fueling.notes(60), [])
        self.assertTrue(any("fructose" in n for n in fueling.notes(75)))
        self.assertTrue(any("experimental" in n for n in fueling.notes(100)))


class DuringRideTests(unittest.TestCase):
    """Carbs an hour on training rides, from length and intensity, inside the nutrition.md bands."""

    def test_short_rides_need_no_carbs(self):
        self.assertEqual(fueling.during(40, 0.95)["g_per_h"], 0)
        easy = fueling.during(60, 0.70)
        self.assertEqual((easy["g_per_h"], easy["optional_g"], easy["total_g"]), (0, 0, 0))
        hard = fueling.during(60, 0.90)                                 # a hard hour gets a little, optional
        self.assertEqual((hard["g_per_h"], hard["optional_g"]), (0, 30))
        self.assertIn("optional", hard["why"])

    def test_the_rate_follows_length_and_intensity(self):
        self.assertEqual(fueling.during(120, 0.60)["g_per_h"], 30)      # easy, bottom of 30 to 60
        self.assertEqual(fueling.during(120, 0.75)["g_per_h"], 45)
        self.assertEqual(fueling.during(120, None)["g_per_h"], 45)      # no IF, the middle
        self.assertEqual(fueling.during(120, 0.90)["g_per_h"], 60)
        self.assertEqual(fueling.during(240, 0.70)["g_per_h"], 60)      # 60 to 90 beyond 2.5 h
        self.assertEqual(fueling.during(240, 0.88)["g_per_h"], 75)
        self.assertEqual(fueling.during(180, 0.70)["total_g"], 180)

    def test_every_start_sits_inside_its_band_and_never_above_90(self):
        for minutes in range(0, 480, 15):
            for avg_if in (None, 0.5, 0.65, 0.75, 0.85, 1.0):
                d = fueling.during(minutes, avg_if)
                with self.subTest(minutes=minutes, avg_if=avg_if):
                    self.assertLessEqual(d["g_per_h"], fueling.TRAINED_GUT_MAX)
                    if d["g_per_h"]:
                        self.assertTrue(d["low"] <= d["g_per_h"] <= d["high"])
                    self.assertIn("Evidence: Strong", d["evidence"])
                    self.assertIn("136 studies", d["evidence"])
                    self.assertTrue(d["why"])

    def test_above_60_g_an_hour_says_to_mix_glucose_and_fructose(self):
        self.assertTrue(any("fructose" in n for n in fueling.during(240, 0.9)["notes"]))
        self.assertEqual(fueling.during(120, 0.6)["notes"], [])


class CaffeineTests(unittest.TestCase):
    """3 mg/kg to start, 6 mg/kg as a firm ceiling, and only for races and hard sessions."""

    def test_limits_scale_with_weight(self):
        self.assertEqual(fueling.caffeine_limits(70), {"start_mg": 210, "max_mg": 420,
                                                       "evidence": fueling.CAFFEINE_EVIDENCE})
        self.assertIsNone(fueling.caffeine_limits(None))
        self.assertIsNone(fueling.caffeine_limits(0))
        self.assertIn("21 meta-analyses", fueling.CAFFEINE_EVIDENCE)

    def test_only_key_sessions_get_caffeine(self):
        self.assertFalse(fueling.is_key_session(0.75))
        self.assertFalse(fueling.is_key_session(None))
        self.assertTrue(fueling.is_key_session(0.9))
        self.assertTrue(fueling.is_key_session(0.6, race=True))

    def test_the_plan_offers_one_caffeinated_item_at_most_and_never_in_the_hourly_mix(self):
        from metrics import foods
        plan = fueling.during_plan(240, 0.9, {}, 70)
        self.assertEqual(plan["per"], "hour")
        self.assertTrue(plan["ideas"]["ok"])
        lib = foods.by_id()
        for c in plan["ideas"]["combos"]:
            for part in c["items"]:
                self.assertFalse(foods.has_caffeine(lib[part["id"]]), part["text"])
        caf = plan["caffeine"]
        self.assertTrue(caf["ok"], caf["message"])
        self.assertEqual(caf["servings"], 1)
        self.assertLessEqual(caf["mg"], 3 * 70)
        self.assertIn("6 mg/kg", caf["message"])
        self.assertIn("bedtime", caf["message"])

    def test_no_caffeine_for_easy_rides_avoiders_or_unknown_weight(self):
        self.assertFalse(fueling.during_plan(240, 0.7, {}, 70)["caffeine"]["ok"])
        avoider = fueling.during_plan(240, 0.9, {"avoid_foods": ["caffeine"]}, 70)["caffeine"]
        self.assertFalse(avoider["ok"])
        self.assertIn("avoid", avoider["message"])
        unknown = fueling.during_plan(240, 0.9, {}, None)["caffeine"]
        self.assertFalse(unknown["ok"])
        self.assertIn("weight", unknown["message"])

    def test_a_serving_above_the_starting_dose_is_not_offered(self):
        from metrics import foods
        strong = {"id": "strong_gel", "name": "Strong gel", "serving": {"label": "1", "g": 40, "unit": "piece"},
                  "per_100g": {"carbs_g": 60, "protein_g": 0, "caffeine_mg": 500},       # 200 mg a gel
                  "phases": ["during"], "diets": ["vegan", "vegetarian", "pescatarian"],
                  "contains": ["caffeine"], "may_contain": [], "allergens_checked": True}
        self.assertFalse(foods.caffeine_option({}, 50, True, library=[strong])["ok"])   # 150 mg limit
        ok = foods.caffeine_option({}, 80, True, library=[strong])                      # 240 mg limit
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["mg"], 200)
        self.assertLessEqual(ok["mg_per_kg"], fueling.CAFFEINE_MAX_MG_PER_KG)

    def test_short_hard_rides_get_an_optional_total_not_an_hourly_rate(self):
        plan = fueling.during_plan(60, 0.95, {}, 70)
        self.assertEqual(plan["per"], "ride")
        for c in plan["ideas"]["combos"]:
            self.assertLessEqual(abs(c["carbs_g"] - 30), 3)
        quiet = fueling.during_plan(30, 0.6, {}, 70)
        self.assertEqual(quiet["ideas"]["combos"], [])


class MaltodextrinTests(unittest.TestCase):
    def test_maltodextrin_counts_toward_the_hourly_carbs_as_a_bottle_mix(self):
        from metrics import foods
        malto = foods.by_id()["maltodextrin"]
        self.assertIn("bottle", malto["name"])
        self.assertIn("during", malto["phases"])
        found = False
        for g in (30, 45, 60, 75, 90):
            for c in foods.suggest("during", g, 0, {})["combos"]:
                found |= any(p["id"] == "maltodextrin" for p in c["items"])
        self.assertTrue(found)


class PacingTabTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        schema.run_migrations()

    def test_the_rider_sets_the_carbs_and_the_plan_follows(self):
        at = AppTest.from_file(PAGE, default_timeout=60).run()
        next(n for n in at.number_input if n.label == "Target time (hours)").set_value(3).run()
        next(n for n in at.number_input if n.label == "Target time (minutes)").set_value(0).run()
        carbs = next(n for n in at.number_input if n.label == "Carbs per hour (g)")
        self.assertEqual(carbs.value, 60)                             # the suggestion for 3 hours
        carbs.set_value(90).run()
        next(b for b in at.button if b.label == "Calculate Pacing Plan").click().run()
        self.assertFalse(at.exception)
        plan = at.dataframe[-1].value
        self.assertIn("30 g carbs + water", list(plan["Action"]))      # 90 g an hour, a third per feed
        self.assertTrue(any("fructose" in c.value for c in at.caption))


if __name__ == "__main__":
    unittest.main()
