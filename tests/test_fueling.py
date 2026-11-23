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
DASHBOARD = os.path.join(os.path.dirname(PAGE), "01_Dashboard.py")


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


# ── Before, during and after one ride (fueling.ride_plan) ──────────────────────────────────────

ASKED = {"nutrition_referral": "0"}            # the health question answered no


def _texts(ideas) -> str:
    return " ".join(i["text"] for i in ideas).lower()


class RidePlanTests(unittest.TestCase):
    def test_no_weight_no_plan(self):
        self.assertFalse(fueling.ride_plan(120, None, 0.7)["ok"])

    def test_intensity_from_if_or_workout_type(self):
        self.assertEqual(fueling.intensity_if(0.82), 0.82)
        self.assertEqual(fueling.intensity_if("Threshold"), 0.95)
        self.assertEqual(fueling.intensity_if("recovery"), 0.55)
        self.assertIsNone(fueling.intensity_if("Other"))
        self.assertEqual(fueling.ride_plan(60, 70, "VO2 Max")["effort"], "hard")

    def test_before_a_long_ride_is_1_to_4_g_per_kg_with_ideas(self):
        before = fueling.ride_plan(180, 70, "Endurance", settings={"usual_ride_time": "midday"})["before"]
        self.assertEqual((before["g"], before["low"], before["high"]), (140, 70, 280))
        self.assertEqual(before["timing"], "2 to 3 hours before")
        self.assertFalse(before["early"])
        self.assertTrue(before["why"])
        self.assertEqual([i["kind"] for i in before["ideas"]], ["recipe", "food"])
        self.assertIn("a serving sized to", before["ideas"][0]["text"])

    def test_short_easy_ride_needs_nothing_before_but_short_hard_one_gets_a_snack(self):
        self.assertEqual(fueling.ride_plan(45, 70, 0.70)["before"]["g"], 0)
        hard = fueling.ride_plan(45, 70, 0.95)["before"]
        self.assertEqual(hard["g"], 70)                           # about 1 g/kg
        self.assertEqual(hard["timing"], "30 to 60 minutes before")
        self.assertTrue(hard["ideas"])

    def test_early_ride_from_start_time_gets_a_snack_and_a_big_dinner(self):
        plan = fueling.ride_plan(150, 70, 0.75, start_time="06:30")
        before = plan["before"]
        self.assertTrue(before["early"])
        self.assertEqual(before["g"], 70)
        self.assertEqual(before["timing"], "30 to 60 minutes before")
        self.assertIn("dinner", before["why"])
        self.assertIsNotNone(before["night_before"])
        self.assertTrue(all(i["kind"] == "food" for i in before["ideas"]))

    def test_early_ride_from_usual_ride_time_and_start_time_wins(self):
        early = {"usual_ride_time": "early"}
        self.assertTrue(fueling.ride_plan(150, 70, 0.75, settings=early)["before"]["early"])
        self.assertFalse(fueling.ride_plan(150, 70, 0.75, start_time="12:00", settings=early)["before"]["early"])
        self.assertFalse(fueling.ride_plan(150, 70, 0.75, settings={"usual_ride_time": "evening"})["before"]["early"])

    def test_early_snack_ideas_are_gut_friendly(self):
        from metrics import foods
        before = fueling.ride_plan(150, 70, 0.75, start_time="06:00")["before"]
        gentle = foods.suggest("before", 70, 0, {"gut_sensitive": True}, n=10)["combos"]
        texts = {c["text"] for c in gentle}
        self.assertEqual(len(before["ideas"]), 2)
        self.assertTrue(all(i["text"] in texts for i in before["ideas"]))

    def test_fasted_option_only_on_easy_short_rides_with_the_health_question_answered_no(self):
        self.assertIsNotNone(fueling.ride_plan(60, 70, "Recovery", settings=ASKED)["fasted"])
        self.assertIsNone(fueling.ride_plan(60, 70, 0.95, settings=ASKED)["fasted"])       # hard day
        self.assertIsNone(fueling.ride_plan(60, 70, 0.75, settings=ASKED)["fasted"])       # steady
        self.assertIsNone(fueling.ride_plan(120, 70, 0.60, settings=ASKED)["fasted"])      # long ride
        self.assertIsNone(fueling.ride_plan(60, 70, 0.60, settings=ASKED, race=True)["fasted"])
        self.assertIsNone(fueling.ride_plan(60, 70, 0.60, settings={"nutrition_referral": "1"})["fasted"])
        self.assertIsNone(fueling.ride_plan(60, 70, 0.60, settings={"nutrition_referral": True})["fasted"])
        self.assertIsNone(fueling.ride_plan(60, 70, 0.60, settings={})["fasted"])           # unanswered

    def test_caffeine_only_on_key_sessions_and_never_for_avoiders(self):
        hard = fueling.ride_plan(90, 70, 0.95)
        self.assertIsNotNone(hard["caffeine"])
        self.assertLessEqual(hard["caffeine"]["mg"], 3 * 70)
        self.assertIsNone(fueling.ride_plan(90, 70, 0.70)["caffeine"])
        avoid = {"avoid_foods": "caffeine"}
        plan = fueling.ride_plan(240, 70, 0.95, settings=avoid, race=True)
        self.assertIsNone(plan["caffeine"])
        rest = {k: v for k, v in plan.items() if k != "caffeine"}
        self.assertNotIn("caf", str(rest).lower())

    def test_evening_caffeine_warns_about_sleep(self):
        plan = fueling.ride_plan(90, 70, 0.95, start_time="18:30")
        self.assertIn("sleep", plan["caffeine"]["message"])

    def test_no_caffeinated_food_in_any_idea(self):
        from metrics import foods
        lib = foods.by_id()
        plan = fueling.ride_plan(240, 70, 0.95, race=True, day_carbs_g=600)
        for combo in plan["during"]["ideas"]["combos"]:
            self.assertFalse(any(foods.has_caffeine(lib[p["id"]]) for p in combo["items"]))
        self.assertNotIn("caf", _texts(plan["before"]["ideas"] + plan["after"]["ideas"]))

    def test_during_reuses_during_and_adds_hydration(self):
        plan = fueling.ride_plan(180, 70, 0.70, indoor=True, race_on_calendar=True)
        d = plan["during"]
        self.assertEqual(d["carbs"], fueling.during(180, 0.70))
        self.assertNotIn("caffeine", d)
        self.assertEqual(d["feeds"], fueling.feeds(3, 60))
        lines = " ".join(d["hydration"]["lines"])
        self.assertIn("0.6 to 0.8 L an hour", lines)
        self.assertIn("sodium", lines)
        self.assertIn("never finish heavier", lines)
        self.assertIn("Indoors", lines)
        self.assertIn("limited", d["hydration"]["gut_training"]["text"])

    def test_recovery_spin_needs_no_carbs_during_and_drinks_to_thirst(self):
        d = fueling.ride_plan(50, 70, "Recovery")["during"]
        self.assertEqual(d["carbs"]["g_per_h"], 0)
        self.assertIn("drink to thirst", d["hydration"]["lines"][0])
        self.assertIsNone(d["hydration"]["gut_training"])

    def test_after_a_long_ride_is_protein_plus_carbs(self):
        after = fueling.ride_plan(180, 70, 0.70, day_carbs_g=560)["after"]
        self.assertEqual(after["protein_g"], 21)                  # 0.3 g/kg
        self.assertEqual(after["carbs_g"], 84)                    # the recovery share of the day
        self.assertIsNone(after["refuel"])
        self.assertIn("repair", after["why"])
        self.assertEqual(len(after["ideas"]), 2)
        self.assertEqual(after["ideas"][0]["kind"], "recipe")
        self.assertIn("1.25 to 1.5 L", after["rehydrate"])

    def test_refuel_when_the_next_hard_session_is_under_8_hours_away(self):
        after = fueling.ride_plan(120, 70, 0.95, next_hard_in_h=5)["after"]
        self.assertEqual((after["refuel"]["g_per_h"], after["refuel"]["high_per_h"]), (70, 84))
        self.assertEqual(after["refuel"]["hours"], 4)
        self.assertIsNone(fueling.ride_plan(120, 70, 0.95, next_hard_in_h=10)["after"]["refuel"])

    def test_short_easy_ride_after_is_the_next_meal(self):
        after = fueling.ride_plan(45, 70, 0.6)["after"]
        self.assertEqual(after["protein_g"], 0)
        self.assertEqual(after["ideas"], [])
        self.assertIsNone(after["rehydrate"])

    def test_every_idea_respects_the_rider_settings(self):
        from metrics import foods
        from metrics import recipes as rec
        lib = foods.by_id()
        vegan_nut_free = {"diet": "vegan", "avoid_foods": "peanuts,tree_nuts", "usual_ride_time": "early"}
        allowed_recipes = {r["id"] for r in rec.allowed_recipes(vegan_nut_free)}
        for minutes, intensity in ((180, 0.7), (45, 0.95), (120, 0.9)):
            plan = fueling.ride_plan(minutes, 70, intensity, settings=vegan_nut_free, day_carbs_g=500,
                                     next_hard_in_h=4)
            ideas = plan["before"]["ideas"] + plan["after"]["ideas"]
            for idea in ideas:
                if idea["kind"] == "recipe":
                    self.assertIn(idea["id"], allowed_recipes)
            if plan["before"]["night_before"]:
                self.assertIn(plan["before"]["night_before"]["id"], allowed_recipes)
            for combo in plan["during"]["ideas"].get("combos", []):
                self.assertTrue(all(foods.allowed(lib[p["id"]], vegan_nut_free) for p in combo["items"]))


class RideIdeaTests(unittest.TestCase):
    def test_a_scaled_recipe_lands_within_20_percent_of_each_target(self):
        from metrics import recipes as rec
        idea = fueling.scaled_recipe_idea("recovery", 84, 21, {})
        self.assertIsNotNone(idea)
        self.assertTrue(fueling.SCALE_RANGE[0] <= idea["factor"] <= fueling.SCALE_RANGE[1])
        recipe = rec.recipe_by_id(idea["id"])
        p = rec.scale(recipe, carbs_g=84, protein_g=21)["per_serving"]
        self.assertLessEqual(abs(p["carbs_g"] - 84) / 84, fueling.SCALE_MISS)
        self.assertLessEqual(abs(p["protein_g"] - 21) / 21, fueling.SCALE_MISS)

    def test_no_recipe_when_none_can_be_sized_to_fit(self):
        self.assertIsNone(fueling.scaled_recipe_idea("recovery", 1000, 5, {}))
        self.assertIsNone(fueling.scaled_recipe_idea("recovery", None, None, {}))

    def test_food_backup_is_the_simplest_combination(self):
        ideas = fueling._food_ideas("before", 140, 0, {}, 5)
        sizes = [i["text"].count(" plus ") for i in ideas]
        self.assertEqual(sizes, sorted(sizes))

    def test_without_a_fitting_recipe_two_food_ideas(self):
        ideas = fueling._ideas("after", "recovery", 84, 21, {"diet": "vegan"})
        self.assertEqual(len(ideas), 2)


class TodayPageTests(unittest.TestCase):
    """The Fuel today tile on pages/01_Dashboard.py."""

    def setUp(self):
        from db import queries as q
        self.q = q
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db")),
                  # Page links only resolve inside the full app, and Garmin reads tokens from home.
                  mock.patch("streamlit.page_link"),
                  mock.patch("auth.garmin.is_connected", return_value=False)):
            p.start()
            self.addCleanup(p.stop)
        schema.run_migrations()
        q._settings_cache.clear()
        self.addCleanup(q._settings_cache.clear)

    def _run(self):
        return AppTest.from_file(DASHBOARD, default_timeout=90).run()

    def _plan(self, minutes, tss, kind="Endurance", day=None):
        import json
        from datetime import date
        steps = json.dumps([{"kind": "interval", "minutes": minutes, "low_pct": 65, "high_pct": 75,
                             "repeat_count": None, "repeat_steps": None}])
        conn = schema.get_conn()
        conn.execute("INSERT INTO workouts (date, name, workout_type, structured_json, tss_planned, completed) "
                     "VALUES (?,?,?,?,?,0)", (day or date.today().isoformat(), f"{kind} ride", kind, steps, tss))
        conn.commit()
        conn.close()

    def _markdown(self, at) -> str:
        return " ".join(m.value for m in at.markdown)

    def test_empty_database_asks_for_weight(self):
        at = self._run()
        self.assertFalse(at.exception)
        self.assertIn("Add your weight in Settings to see daily fuel targets.", self._markdown(at))
        self.assertTrue(any(b.label == "Add your weight" for b in at.button))
        self.assertTrue(any(e.label == "Fueling basics" for e in at.expander))

    def test_no_ride_shows_targets_and_a_sample_day_only(self):
        self.q.set_setting("weight_kg", "70")
        at = self._run()
        self.assertFalse(at.exception)
        self.assertEqual([m.label for m in at.metric], ["Carbs", "Protein", "Calories"])
        text = self._markdown(at)
        self.assertIn("A sample day", [e.label for e in at.expander])
        self.assertNotIn("**Before**", text)
        self.assertTrue(any(b.label == "Set a base" for b in at.button))

    def test_planned_ride_shows_before_during_and_after(self):
        from datetime import date, timedelta
        self.q.set_setting("weight_kg", "70")
        self.q.set_setting("ftp_watts", "250")
        self.q.set_setting("base_kcal", "2000")
        self._plan(180, 170)
        self._plan(150, 140, day=(date.today() + timedelta(days=1)).isoformat())
        at = self._run()
        self.assertFalse(at.exception)
        text = self._markdown(at)
        self.assertIn("A sample day", [e.label for e in at.expander])
        for part in ("**Before**", "**During**", "**After**", "60 g carbs an hour", "21 g protein"):
            self.assertIn(part, text)
        self.assertIn("Tomorrow is 2.5 hours", text)
        self.assertTrue(any(m.label == "Calories" and m.value.replace(",", "").isdigit() for m in at.metric))
        self.assertTrue(any(c.value.startswith("kcal, base 2,000 plus training") for c in at.caption))

    def test_sample_day_opens_the_recipe(self):
        self.q.set_setting("weight_kg", "70")
        at = self._run()
        with mock.patch("streamlit.switch_page") as go:
            next(b for b in at.button if b.key == "fuel_rec_breakfast").click().run()
        self.assertTrue(at.session_state["rec_open"])

    def test_referral_message_shows_first(self):
        from metrics import diet
        self.q.set_setting("weight_kg", "70")
        self.q.set_setting("nutrition_referral", "1")
        at = self._run()
        self.assertFalse(at.exception)
        self.assertTrue(any(diet.REFERRAL_MESSAGE == w.value for w in at.warning))

    def test_caffeine_avoider_sees_no_caffeine_on_a_hard_day(self):
        self.q.set_setting("weight_kg", "70")
        self.q.set_setting("ftp_watts", "250")
        self._plan(90, 140, kind="Threshold")
        at = self._run()
        self.assertTrue(any("caffeine" in c.value for c in at.caption))
        self.q.set_setting("avoid_foods", "caffeine")
        at = self._run()
        self.assertFalse(at.exception)
        self.assertFalse(any("caffeine" in c.value.lower() for c in at.caption))


if __name__ == "__main__":
    unittest.main()
