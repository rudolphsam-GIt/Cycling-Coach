"""Meal recipes (knowledge/recipes.json, metrics/recipes.py) and the Recipes page.
tests/test_recipes.py covers workout recipes, which are a different thing.
Run with venv/bin/python -m pytest tests/test_food_recipes.py"""
from __future__ import annotations

import copy
import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

from streamlit.testing.v1 import AppTest

from db import schema
from db import queries as q
from metrics import foods
from metrics import recipes as rec
from metrics import units

PAGES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pages")
LIB = foods.by_id()
RECIPES = rec.load_recipes()
NUTS = {"peanuts", "tree_nuts"}
NUT_FREE = {"avoid_foods": "peanuts,tree_nuts"}


def _marked(food_id: str) -> set:
    f = LIB[food_id]
    return set(f.get("contains") or []) | set(f.get("may_contain") or [])


def _food(fid: str, **over) -> dict:
    """A checked test food for a small made up library."""
    base = {"id": fid, "name": fid.title(), "serving": {"label": "100 g", "g": 100, "unit": "g"},
            "per_100g": {"kcal": 100, "carbs_g": 20, "protein_g": 5, "fat_g": 1, "fibre_g": 1,
                         "sodium_mg": 0, "caffeine_mg": 0},
            "phases": ["ingredient"], "diets": ["vegan", "vegetarian", "pescatarian"],
            "contains": [], "may_contain": [], "allergens_checked": True}
    base.update(over)
    return base


class RecipeDataTests(unittest.TestCase):
    def test_every_ingredient_id_exists_in_foods(self):
        for r in RECIPES:
            for ing in r["ingredients"]:
                self.assertIn(ing["food"], LIB, f"{r['id']} uses {ing['food']}")
            for swap in r.get("swaps", []):
                self.assertIn(swap["replace"], {i["food"] for i in r["ingredients"]},
                              f"{r['id']} swap replaces an ingredient it doesn't have")
                for ing in swap.get("with", []):
                    self.assertIn(ing["food"], LIB, f"{r['id']} swap uses {ing['food']}")

    def test_recipe_shape(self):
        self.assertGreaterEqual(len(RECIPES), 30)
        self.assertEqual(len({r["id"] for r in RECIPES}), len(RECIPES))
        for r in RECIPES:
            self.assertTrue(r["slots"] and set(r["slots"]) <= set(rec.SLOTS), r["id"])
            self.assertGreater(r["servings"], 0)
            self.assertTrue(r["steps"] and r["why"], r["id"])
            self.assertIn("fridge_days", r["storage"])
            self.assertIn("freezes", r["storage"])
            for ing in r["ingredients"] + [i for s in r.get("swaps", []) for i in s.get("with", [])]:
                self.assertEqual(len({"g", "ml", "count"} & set(ing)), 1, f"{r['id']} {ing}")
                if "count" in ing:
                    self.assertEqual(LIB[ing["food"]]["serving"]["unit"], "piece", f"{r['id']} {ing}")

    def test_macros_and_allergens_are_not_typed_by_hand(self):
        for r in RECIPES:
            for key in ("per_serving", "kcal", "carbs_g", "protein_g", "allergens", "contains", "tags", "diets"):
                self.assertNotIn(key, r, f"{r['id']} has {key} typed in")

    def test_every_slot_has_vegan_and_gluten_free_options(self):
        for settings in ({"diet": "vegan"}, {"avoid_foods": "gluten"}):
            pool = rec.allowed_recipes(settings)
            for slot in rec.SLOTS:
                self.assertTrue([r for r in pool if slot in r["slots"]], f"{settings} has no {slot}")

    def test_no_recipe_is_a_caffeine_source(self):
        """Caffeine isn't suggested casually, so no recipe uses coffee or a caffeinated gel."""
        self.assertEqual([r["id"] for r in RECIPES if rec.has_caffeine(r)], [])
        self.assertEqual(len(rec.allowed_recipes({})), len(RECIPES))


class MacroTests(unittest.TestCase):
    def test_computed_macros_match_the_sum_of_ingredients(self):
        for r in RECIPES:
            want = {k: 0.0 for k in rec.NUTRIENTS}
            for ing in r["ingredients"]:
                f = LIB[ing["food"]]
                if "count" in ing:
                    g = ing["count"] * f["serving"]["g"]
                elif "ml" in ing:
                    g = ing["ml"] * units.grams_per_ml(f)
                else:
                    g = ing["g"]
                for k in want:
                    want[k] += (f["per_100g"].get(k) or 0) * g / 100
            got = rec.per_serving(r)
            for k in rec.NUTRIENTS:
                self.assertAlmostEqual(got[k], want[k] / r["servings"], delta=0.06, msg=f"{r['id']} {k}")

    def test_hand_worked_example(self):
        r = {"id": "x", "servings": 2, "ingredients": [{"food": "oats", "g": 80}, {"food": "banana", "count": 2}]}
        oats, banana = LIB["oats"]["per_100g"], LIB["banana"]["per_100g"]
        carbs = (oats["carbs_g"] * 0.8 + banana["carbs_g"] * 2 * LIB["banana"]["serving"]["g"] / 100) / 2
        self.assertAlmostEqual(rec.per_serving(r)["carbs_g"], carbs, delta=0.06)

    def test_milk_in_ml_uses_its_label_density(self):
        # 1 cup of milk is 244 g in FDC, so 240 ml weighs 244 g.
        self.assertAlmostEqual(rec.grams({"food": "milk_2pct", "ml": 240}, LIB["milk_2pct"]), 244, places=3)

    def test_recipe_inherits_every_ingredient_allergen(self):
        r = rec.recipe_by_id("pasta_bake")
        a = rec.allergens(r)
        for ing in r["ingredients"]:
            self.assertTrue(set(LIB[ing["food"]]["contains"]) <= set(a["contains"]))
            self.assertTrue(set(LIB[ing["food"]]["may_contain"]) <= set(a["contains"]) | set(a["may_contain"]))
        self.assertIn("gluten", a["contains"])
        self.assertIn("dairy", a["contains"])


class SafetyTests(unittest.TestCase):
    """allowed_recipes is a firm safety rule."""

    def _lib(self):
        return {"walnuts": _food("walnuts", contains=["tree_nuts"]),
                "almonds": _food("almonds", contains=["tree_nuts"]),
                "oats": _food("oats"),
                "butter": _food("butter", contains=["dairy"], diets=["vegetarian", "pescatarian"]),
                "oil": _food("oil"),
                "yogurt": _food("yogurt", contains=["dairy"], diets=["vegetarian", "pescatarian"]),
                "soy_yogurt": _food("soy_yogurt", contains=["soy"]),
                "seeds": _food("seeds", may_contain=["tree_nuts"]),
                "mystery": _food("mystery", allergens_checked=False)}

    def test_nut_recipe_never_reaches_a_nut_avoider_even_through_a_swap(self):
        lib = self._lib()
        cake = {"id": "cake", "name": "Cake", "slots": ["snack"], "servings": 4,
                "ingredients": [{"food": "oats", "g": 100}, {"food": "walnuts", "g": 50}, {"food": "butter", "g": 30}],
                "swaps": [{"text": "Almonds for walnuts", "replace": "walnuts", "with": [{"food": "almonds", "g": 50}]},
                          {"text": "Seeds for walnuts", "replace": "walnuts", "with": [{"food": "seeds", "g": 50}]},
                          {"text": "Oil for butter", "replace": "butter", "with": [{"food": "oil", "g": 30}]}]}
        for avoid in ("tree_nuts", "peanuts,tree_nuts", "tree_nuts,dairy"):
            self.assertEqual(rec.allowed_recipes({"avoid_foods": avoid}, [cake], lib), [], avoid)
        self.assertFalse(rec.resolve(cake, {"avoid_foods": "tree_nuts"}, lib)["ok"])

    def test_real_recipes_never_give_a_nut_avoider_anything_marked_nuts(self):
        for r in rec.allowed_recipes(NUT_FREE):
            for ing in r["ingredients"]:
                self.assertFalse(_marked(ing["food"]) & NUTS, f"{r['id']} {ing['food']}")
                self.assertTrue(LIB[ing["food"]]["allergens_checked"], f"{r['id']} {ing['food']}")
        hidden = {h["id"] for h in rec.hidden_recipes(NUT_FREE)}
        self.assertIn("trail_mix", hidden)         # its only swap is seeds that may contain nuts

    def test_a_swap_makes_a_recipe_allowed_dairy_free_yogurt(self):
        lib = self._lib()
        bowl = {"id": "bowl", "name": "Bowl", "slots": ["breakfast"], "servings": 1,
                "ingredients": [{"food": "oats", "g": 50}, {"food": "yogurt", "g": 150}],
                "swaps": [{"text": "Use soy yogurt for dairy free", "replace": "yogurt",
                           "with": [{"food": "soy_yogurt", "g": 150}]}]}
        self.assertEqual(len(rec.allowed_recipes({}, [bowl], lib)), 1)
        got = rec.allowed_recipes({"avoid_foods": "dairy"}, [bowl], lib)
        self.assertEqual(len(got), 1)
        self.assertEqual([i["food"] for i in got[0]["ingredients"]], ["oats", "soy_yogurt"])
        self.assertEqual(got[0]["swaps_used"], ["Use soy yogurt for dairy free"])
        self.assertIn("dairy_free", got[0]["tags"])
        # The same swap is useless to someone who avoids both, so the recipe stays hidden.
        self.assertEqual(rec.allowed_recipes({"avoid_foods": "dairy,soy"}, [bowl], lib), [])

    def test_a_swap_makes_a_real_recipe_allowed(self):
        """Dairy free riders get the chocolate milk recipe as soy chocolate milk."""
        got = {r["id"]: r for r in rec.allowed_recipes({"avoid_foods": "dairy"})}
        self.assertIn("chocolate_milk_recovery", got)
        self.assertEqual([i["food"] for i in got["chocolate_milk_recovery"]["ingredients"]], ["soy_chocolate_milk"])
        vegan = {r["id"]: r for r in rec.allowed_recipes({"diet": "vegan"})}
        self.assertEqual([i["food"] for i in vegan["overnight_oats"]["ingredients"]][1:3], ["soy_milk", "soy_yogurt"])

    def test_unchecked_ingredient_hides_recipe_from_anyone_with_an_avoid_list(self):
        lib = self._lib()
        r = {"id": "m", "name": "M", "slots": ["snack"], "servings": 1,
             "ingredients": [{"food": "oats", "g": 50}, {"food": "mystery", "g": 20}]}
        self.assertEqual(len(rec.allowed_recipes({}, [r], lib)), 1)
        self.assertEqual(rec.allowed_recipes({"avoid_foods": "sesame"}, [r], lib), [])
        for real in rec.allowed_recipes({"avoid_foods": "sesame"}):
            for ing in real["ingredients"]:
                self.assertTrue(LIB[ing["food"]]["allergens_checked"], f"{real['id']} {ing['food']}")

    def test_diet_swaps_and_diet_safety(self):
        for diet, banned in (("vegan", {"eggs", "dairy", "fish_shellfish"}), ("vegetarian", {"fish_shellfish"})):
            pool = rec.allowed_recipes({"diet": diet})
            for r in pool:
                for ing in r["ingredients"]:
                    self.assertIn(diet, LIB[ing["food"]]["diets"], f"{r['id']} {ing['food']}")
                    self.assertFalse(set(LIB[ing["food"]]["contains"]) & banned, f"{r['id']} {ing['food']}")
        stir_fry = {r["id"]: r for r in rec.allowed_recipes({"diet": "vegetarian"})}["noodle_stir_fry"]
        self.assertIn("tofu_firm", [i["food"] for i in stir_fry["ingredients"]])

    def test_caffeine_avoiders_get_no_caffeine_at_all(self):
        for r in rec.allowed_recipes({"avoid_foods": "caffeine"}):
            self.assertEqual(r["caffeine_mg"], 0, r["id"])
            for ing in r["ingredients"]:
                self.assertFalse(LIB[ing["food"]]["per_100g"].get("caffeine_mg"), f"{r['id']} {ing['food']}")

    def test_caffeine_source_kept_out_unless_asked(self):
        lib = {"oats": _food("oats"), "coffee": _food("coffee", contains=["caffeine"],
                                                      per_100g={"carbs_g": 0, "caffeine_mg": 40})}
        r = {"id": "c", "name": "Coffee oats", "slots": ["breakfast"], "servings": 1,
             "ingredients": [{"food": "oats", "g": 50}, {"food": "coffee", "g": 200}]}
        self.assertEqual(rec.allowed_recipes({}, [r], lib), [])
        self.assertEqual(len(rec.allowed_recipes({}, [r], lib, caffeine=True)), 1)


class SwapNameTests(unittest.TestCase):
    def test_a_swap_of_the_named_food_renames_the_recipe(self):
        veg = {"diet": "vegetarian"}
        got = {r["id"]: r for r in rec.allowed_recipes(veg)}
        self.assertEqual(got["salmon_rice_greens"]["name"], "Tempeh with rice and greens")
        self.assertNotIn("salmon", got["salmon_rice_greens"]["why"].lower())
        vegan = {r["id"]: r["name"] for r in rec.allowed_recipes({"diet": "vegan"})}
        self.assertEqual(vegan.get("rice_cakes_savoury"), "Savoury rice cakes with tofu")
        self.assertEqual(vegan.get("greek_yogurt_bowl"), "Soy yogurt bowl")
        self.assertEqual(vegan.get("rice_egg_bowl"), "Savoury rice and tofu bowl")

    def test_no_swap_keeps_the_name(self):
        got = {r["id"]: r for r in rec.allowed_recipes({})}
        self.assertEqual(got["salmon_rice_greens"]["name"], "Salmon with rice and greens")
        self.assertEqual(got["eggs_on_toast"]["name"], "Scrambled eggs on toast")

    def test_a_swap_that_leaves_the_named_food_keeps_the_name(self):
        got = {r["id"]: r["name"] for r in rec.allowed_recipes({"avoid_foods": "gluten"})}
        self.assertNotIn("Tempeh", got.get("salmon_rice_greens", ""))


class ScaleTests(unittest.TestCase):
    def test_scaling_hits_the_target_within_10_percent(self):
        for r in rec.allowed_recipes({}):
            base = r["per_serving"]["carbs_g"]
            for target in (base * 0.7, base * 1.5):
                got = rec.scale(r, carbs_g=target)["per_serving"]["carbs_g"]
                self.assertLessEqual(abs(got - target) / target, 0.10, f"{r['id']} {target:.0f} got {got}")

    def test_scaling_rounds_eggs_to_whole_numbers(self):
        r = rec.recipe_by_id("rice_egg_bowl")
        for target in (55, 90, 130):
            result = rec.scale(r, carbs_g=target)
            eggs = [i for i in result["recipe"]["ingredients"] if i["food"] == "egg"][0]["count"]
            self.assertIsInstance(eggs, int)
            self.assertGreaterEqual(eggs, 1)
            self.assertLessEqual(abs(result["per_serving"]["carbs_g"] - target) / target, 0.10)

    def test_kitchen_sizes(self):
        result = rec.scale(rec.recipe_by_id("burrito_bowl"), carbs_g=150)
        for ing in result["recipe"]["ingredients"]:
            amount = ing.get("g", ing.get("ml"))
            if amount is not None and amount >= 20:
                self.assertEqual(amount % 10, 0, ing)

    def test_both_targets(self):
        r = rec.recipe_by_id("burrito_bowl")
        result = rec.scale(r, carbs_g=90, protein_g=40)
        self.assertIn("target 90", result["note"])
        self.assertIn("target 40", result["note"])
        self.assertEqual(result["recipe"]["servings"], r["servings"])

    def test_no_target_leaves_it_alone(self):
        r = rec.recipe_by_id("burrito_bowl")
        self.assertEqual(rec.scale(r)["factor"], 1.0)


class DayAndWeekTests(unittest.TestCase):
    TARGETS = {"ok": True, "carbs": {"g": 450}}

    def test_for_day_fills_every_slot_and_puts_favourites_first(self):
        settings = {"favorite_recipes": "bean_chilli"}
        out = rec.for_day("2026-11-24", settings, targets=self.TARGETS, tomorrow={"minutes": 60})
        for slot in rec.SLOTS:
            self.assertTrue(out["slots"][slot], slot)
            self.assertLessEqual(len(out["slots"][slot]), 2)
        self.assertEqual(out["slots"]["dinner"][0]["id"], "bean_chilli")

    def test_carb_heavy_dinner_before_a_long_day(self):
        out = rec.for_day("2026-11-24", {}, targets=self.TARGETS, tomorrow={"minutes": 240})
        dinners = [r for r in rec.allowed_recipes({}) if "dinner" in r["slots"]]
        most = max(r["per_serving"]["carbs_g"] for r in dinners)
        self.assertEqual(out["slots"]["dinner"][0]["per_serving"]["carbs_g"], most)
        self.assertTrue(out["notes"])

    def test_quick_cooks_see_quick_meals_first(self):
        out = rec.for_day("2026-11-24", {"cooking_time": "quick"}, targets=self.TARGETS, tomorrow={"minutes": 0})
        for slot in ("lunch", "dinner", "breakfast"):
            self.assertLessEqual(out["slots"][slot][0]["minutes"], rec.QUICK_MIN, slot)

    def test_for_day_respects_the_avoid_list(self):
        out = rec.for_day("2026-11-24", NUT_FREE, targets=self.TARGETS, tomorrow={"minutes": 0})
        for slot, picks in out["slots"].items():
            for r in picks:
                for ing in r["ingredients"]:
                    self.assertFalse(_marked(ing["food"]) & NUTS)

    def test_for_day_without_targets(self):
        out = rec.for_day("2026-11-24", {}, targets={"ok": False}, tomorrow={"minutes": 0})
        self.assertIsNone(out["day_carbs_g"])
        self.assertTrue(out["slots"]["dinner"])

    def test_prep_ahead_on_an_empty_week_returns_nothing(self):
        self.assertEqual(rec.prep_ahead([]), [])
        self.assertEqual(rec.prep_ahead(None), [])
        quiet = [{"date": str(date(2026, 11, 23) + timedelta(days=i)), "minutes": 0, "avg_if": None}
                 for i in range(7)]
        self.assertEqual(rec.prep_ahead(quiet), [])

    def test_prep_ahead_for_a_long_saturday(self):
        week = [{"date": "2026-11-27", "minutes": 60, "avg_if": 0.6},
                {"date": "2026-11-28", "minutes": 240, "avg_if": 0.7}]
        out = rec.prep_ahead(week)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["cook_on"], "2026-11-27")
        self.assertTrue(out[0]["text"].startswith("Saturday is 4 hours. Make "), out[0]["text"])
        self.assertTrue(out[0]["text"].endswith(" on Friday."))
        slots = [r["slots"] for r in out[0]["recipes"]]
        self.assertTrue(any("pocket" in s for s in slots))
        self.assertTrue(any("dinner" in s for s in slots))
        for r in out[0]["recipes"]:
            self.assertTrue(r["storage"]["freezes"] or r["storage"]["fridge_days"] >= 2)

    def test_prep_ahead_for_a_hard_session_and_the_avoid_list(self):
        out = rec.prep_ahead([{"date": "2026-11-26", "minutes": 75, "avg_if": 0.9}], NUT_FREE)
        self.assertEqual(len(out), 1)
        self.assertIn("Thursday has a hard session", out[0]["text"])
        for r in out[0]["recipes"]:
            for ing in r["ingredients"]:
                self.assertFalse(_marked(ing["food"]) & NUTS)


class KitchenUnitTests(unittest.TestCase):
    def test_cups_and_spoons_with_grams_alongside(self):
        self.assertEqual(units.kitchen_text(LIB["oats"], 80), "80 g (about 1 cup)")
        self.assertEqual(units.kitchen_text(LIB["milk_2pct"], 244, ml=240), "240 ml (about 1 cup, 244 g)")
        self.assertEqual(units.kitchen_text(LIB["egg"], 100, count=2), "2 × large egg (100 g)")
        self.assertEqual(units.kitchen_measure(15), "1 tbsp")
        self.assertEqual(units.kitchen_measure(10), "2 tsp")
        self.assertEqual(units.kitchen_measure(180), "3/4 cup")
        self.assertIsNone(units.kitchen_measure(0))

    def test_food_with_no_measure_shows_grams_only(self):
        self.assertEqual(units.kitchen_text(LIB["chicken_breast"], 250), "250 g")

    def test_every_ingredient_reads_with_grams(self):
        for r in RECIPES:
            for ing in r["ingredients"]:
                self.assertIn(" g", rec.amount_text(ing, LIB[ing["food"]]), f"{r['id']} {ing}")


class _TempDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        q._settings_cache.clear()
        self.addCleanup(q._settings_cache.clear)
        schema.run_migrations()
        q.set_setting("athlete_name", "Sam")


class FavoriteTests(_TempDb):
    def test_star_and_unstar(self):
        self.assertTrue(rec.toggle_favorite("bean_chilli"))
        self.assertTrue(rec.toggle_favorite("lentil_curry"))
        self.assertEqual(rec.favorites({"favorite_recipes": q.get_setting("favorite_recipes")}),
                         ["bean_chilli", "lentil_curry"])
        self.assertFalse(rec.toggle_favorite("bean_chilli"))
        self.assertEqual(q.get_setting("favorite_recipes"), "lentil_curry")


class RecipesPageTests(_TempDb):
    def _run(self):
        return AppTest.from_file(os.path.join(PAGES, "08_Recipes.py"), default_timeout=60).run()

    def test_page_shows_recipes(self):
        q.set_setting("weight_kg", "70")
        at = self._run()
        self.assertFalse(at.exception)
        labels = [e.label for e in at.expander]
        self.assertEqual(len(labels), len(RECIPES))
        self.assertTrue(any(label.startswith("Overnight oats") for label in labels))

    def test_page_hides_nut_recipes_and_says_why(self):
        q.set_setting("avoid_foods", "peanuts,tree_nuts")
        at = self._run()
        self.assertFalse(at.exception)
        labels = " ".join(e.label for e in at.expander)
        self.assertNotIn("Trail mix", labels)
        self.assertTrue(any("hidden" in c.value for c in at.caption))

    def test_star_button_saves_a_favourite(self):
        at = self._run()
        at.button(key="rec_star_bean_chilli").click().run()
        self.assertFalse(at.exception)
        self.assertIn("bean_chilli", q.get_setting("favorite_recipes"))


if __name__ == "__main__":
    unittest.main()
