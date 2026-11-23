"""The food library, its safety filter, and the How you eat answers that feed it.
Run with venv/bin/python -m pytest tests/test_foods.py"""
from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from unittest import mock

import streamlit as st
from streamlit.testing.v1 import AppTest

import intake_import as ii
from db import profiles, schema
from db import queries as q
from metrics import diet
from metrics import foods
from tests.test_intake_import import FULL, _row

PAGES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pages")
LIB = foods.load_library()
ALLERGENS = set(diet.AVOID.values())
NUTS = {"peanuts", "tree_nuts"}


def _marked(item) -> set:
    return set(item["contains"]) | set(item["may_contain"])


def _suggested_ids(result) -> set:
    return {p["id"] for c in result["combos"] for p in c["items"]}


def _food(**over) -> dict:
    base = {"id": "test", "name": "Test food", "serving": {"label": "1", "g": 100, "unit": "g", "from": "app"},
            "per_100g": {"kcal": 300, "carbs_g": 60, "protein_g": 10, "fat_g": 1, "fibre_g": 1,
                         "sodium_mg": 0, "caffeine_mg": 0},
            "phases": ["before", "during", "after", "everyday"], "diets": ["vegan", "vegetarian", "pescatarian"],
            "contains": [], "may_contain": [], "allergens_checked": True, "allergen_source": "", "source": {}}
    base.update(over)
    return base


class LibraryDataTests(unittest.TestCase):
    def test_about_120_items_each_with_an_fdc_id_or_a_label(self):
        self.assertGreaterEqual(len(LIB), 100)
        ids = [f["id"] for f in LIB]
        self.assertEqual(len(ids), len(set(ids)))
        for f in LIB:
            with self.subTest(food=f["id"]):
                if f["source"]["database"] == "Maker's label":
                    for key in ("brand", "product", "url", "read", "ingredients", "allergen_statement"):
                        self.assertTrue(f["source"][key], key)
                    self.assertTrue(f["source"]["url"].startswith("https://"))
                else:
                    self.assertIsInstance(f["source"]["fdc_id"], int)
                    self.assertEqual(f["source"]["database"], "USDA FoodData Central")
                    self.assertTrue(f["source"]["description"])
                self.assertGreater(f["serving"]["g"], 0)
                self.assertIn(f["serving"]["unit"], ("g", "ml", "piece"))
                self.assertIsNotNone(f["per_100g"]["carbs_g"])
                self.assertIsNotNone(f["per_100g"]["protein_g"])
                self.assertLessEqual(_marked(f), ALLERGENS)
                self.assertLessEqual(set(f["phases"]), set(foods.PHASES) | {"ingredient"})
                self.assertLessEqual(set(f["diets"]), {"vegan", "vegetarian", "pescatarian"})
                self.assertIsInstance(f["allergens_checked"], bool)
                self.assertTrue(f["allergen_source"])

    def test_diet_tags_agree_with_the_allergens(self):
        for f in LIB:
            with self.subTest(food=f["id"]):
                if "vegan" in f["diets"]:
                    self.assertFalse(set(f["contains"]) & {"eggs", "dairy", "fish_shellfish"})
                    self.assertIn("vegetarian", f["diets"])
                if "vegetarian" in f["diets"]:
                    self.assertNotIn("fish_shellfish", f["contains"])
                    self.assertIn("pescatarian", f["diets"])
        self.assertNotIn("vegan", foods.by_id(LIB)["honey"]["diets"])

    def test_raw_ingredients_are_there_for_recipes(self):
        ids = set(foods.by_id(LIB))
        for need in ("oats", "white_rice_raw", "pasta_dry", "flour_all_purpose", "sugar", "maple_syrup",
                     "olive_oil", "cinnamon", "raspberries_frozen", "kidney_beans", "salt",
                     "tomatoes_canned", "white_beans", "gnocchi", "maltodextrin"):
            self.assertIn(need, ids)


class BrandedFoodTests(unittest.TestCase):
    """Branded foods come from the maker's label, and the label's allergen text is a firm rule."""
    BRANDED = [f for f in LIB if f["source"]["database"] == "Maker's label"]

    def test_there_are_gels_a_drink_mix_and_protein_powders(self):
        ids = {f["id"] for f in self.BRANDED}
        self.assertLessEqual({"maurten_gel_100", "maurten_gel_100_caf", "skratch_hydration", "maltodextrin",
                              "whey_protein", "pea_protein", "soy_chocolate_milk", "gnocchi"}, ids)

    def test_label_values_scale_to_100_g(self):
        for f in self.BRANDED:
            src = f["source"]
            grams = 100 if src["label_per"] == "100 g" else float(src["label_per"].split()[0])
            for key, value in src["label_values"].items():
                with self.subTest(food=f["id"], nutrient=key):
                    if key == "salt_g":
                        self.assertAlmostEqual(f["per_100g"]["sodium_mg"], value * 400 * 100 / grams, places=1)
                    elif value is None:
                        self.assertIsNone(f["per_100g"][key])
                    else:
                        self.assertAlmostEqual(f["per_100g"][key] * grams / 100, value, places=1)
        self.assertAlmostEqual(foods.per_serving(foods.by_id(LIB)["maurten_gel_100"])["carbs_g"], 25, places=2)
        self.assertAlmostEqual(foods.per_serving(foods.by_id(LIB)["whey_protein"])["protein_g"], 24, places=2)
        self.assertEqual(foods.by_id(LIB)["gnocchi"]["per_100g"]["sodium_mg"], 512)       # 1.28 g salt

    def test_contains_and_may_contain_match_the_label_text(self):
        for f in self.BRANDED:
            text = (f["source"]["ingredients"] + " " + f["source"]["allergen_statement"]).lower()
            words = set(re.findall(r"[a-z]+", text))
            with self.subTest(food=f["id"]):
                self.assertTrue(f["allergens_checked"])
                if "may contain" in text or "facility" in text:
                    self.assertTrue(f["may_contain"])
                if "milk" in words and "not manufactured" not in text:
                    self.assertIn("dairy", f["contains"])
                if "soy" in words and "not manufactured" not in text and "may contain" not in text:
                    self.assertIn("soy", f["contains"])
                if "wheat" in words and "not manufactured" not in text:
                    self.assertIn("gluten", f["contains"])

    def test_a_nut_avoider_never_sees_a_gel_or_powder_that_may_contain_nuts(self):
        rider = {"avoid_foods": ["tree_nuts"]}
        by = foods.by_id(LIB)
        self.assertFalse(foods.allowed(by["maltodextrin"], rider))
        self.assertFalse(foods.allowed(by["pea_protein"], rider))
        self.assertTrue(foods.allowed(by["maurten_gel_100"], rider))
        may_nuts = _food(id="gel_may_nuts", contains=[], may_contain=["peanuts", "tree_nuts"])
        self.assertFalse(foods.allowed(may_nuts, {"avoid_foods": ["peanuts"]}))
        lib = LIB + [may_nuts]
        for phase, carbs, protein in (("during", 60, 0), ("during", 90, 0), ("after", 60, 25)):
            for fid in _suggested_ids(foods.suggest(phase, carbs, protein, {"avoid_foods": ["peanuts", "tree_nuts"]},
                                                    library=lib)):
                self.assertNotIn(fid, {"gel_may_nuts", "maltodextrin", "pea_protein"})

    def test_a_caffeine_avoider_never_sees_the_caffeinated_gel(self):
        rider = {"avoid_foods": ["caffeine"]}
        caf = foods.by_id(LIB)["maurten_gel_100_caf"]
        self.assertEqual(caf["per_100g"]["caffeine_mg"], 250)                   # 100 mg per 40 g sachet
        self.assertFalse(foods.allowed(caf, rider))
        without_tag = dict(caf, contains=[])                                    # the caffeine value alone still blocks it
        self.assertFalse(foods.allowed(without_tag, rider))
        self.assertTrue(foods.allowed(foods.by_id(LIB)["maurten_gel_100"], rider))
        for carbs in (25, 50, 60, 75, 100):
            self.assertNotIn("maurten_gel_100_caf", _suggested_ids(foods.suggest("during", carbs, 0, rider)))

    def test_dairy_and_soy_avoiders(self):
        by = foods.by_id(LIB)
        self.assertFalse(foods.allowed(by["whey_protein"], {"avoid_foods": ["dairy"]}))
        self.assertFalse(foods.allowed(by["whey_protein"], {"diet": "vegan"}))
        self.assertTrue(foods.allowed(by["pea_protein"], {"diet": "vegan"}))
        for fid in ("whey_protein", "soy_chocolate_milk", "gnocchi", "pea_protein", "maltodextrin"):
            self.assertFalse(foods.allowed(by[fid], {"avoid_foods": ["soy"]}), fid)
        self.assertFalse(foods.allowed(by["gnocchi"], {"avoid_foods": ["gluten"]}))


class AllowedTests(unittest.TestCase):
    def test_no_vegan_suggestion_contains_eggs_or_dairy(self):
        vegan = {"diet": "vegan"}
        for f in LIB:
            if foods.allowed(f, vegan):
                self.assertFalse(set(f["contains"]) & {"eggs", "dairy"}, f["id"])
        for phase, carbs, protein in (("before", 100, 0), ("after", 60, 25), ("everyday", 0, 25), ("during", 60, 0)):
            result = foods.suggest(phase, carbs, protein, vegan)
            self.assertTrue(result["ok"], result["message"])
            by = foods.by_id(LIB)
            for fid in _suggested_ids(result):
                self.assertFalse(set(by[fid]["contains"]) & {"eggs", "dairy"}, fid)

    def test_a_mistagged_vegan_food_with_milk_is_still_blocked(self):
        self.assertFalse(foods.allowed(_food(contains=["dairy"]), {"diet": "vegan"}))
        self.assertFalse(foods.allowed(_food(contains=["fish_shellfish"]), {"diet": "vegetarian"}))

    def test_nothing_that_contains_or_may_contain_nuts_reaches_a_nut_avoider(self):
        rider = {"avoid_foods": ["peanuts", "tree_nuts"]}
        shown = [f for f in LIB if foods.allowed(f, rider)]
        self.assertTrue(shown)
        for f in shown:
            self.assertFalse(_marked(f) & NUTS, f["id"])
        self.assertFalse(foods.allowed(foods.by_id(LIB)["medjool_dates"], rider))      # may contain only
        for phase in ("before", "during", "after"):
            by = foods.by_id(LIB)
            for fid in _suggested_ids(foods.suggest(phase, 60, 20 if phase == "after" else 0, rider)):
                self.assertFalse(_marked(by[fid]) & NUTS, fid)

    def test_missing_allergen_data_hides_a_food_from_any_avoid_list(self):
        unchecked = _food(allergens_checked=False)
        self.assertTrue(foods.allowed(unchecked, {}))
        self.assertTrue(foods.allowed(unchecked, {"avoid_foods": []}))
        for key in ALLERGENS:
            self.assertFalse(foods.allowed(unchecked, {"avoid_foods": [key]}), key)
        no_field = _food()
        del no_field["allergens_checked"]
        self.assertFalse(foods.allowed(no_field, {"avoid_foods": "sesame"}))

    def test_gluten_free_riders_never_see_bagels_or_seitan(self):
        rider = {"avoid_foods": "gluten"}
        by = foods.by_id(LIB)
        for fid in ("bagel", "vital_wheat_gluten", "white_bread", "couscous_cooked", "pasta_cooked", "oats"):
            self.assertFalse(foods.allowed(by[fid], rider), fid)
        for phase in ("before", "during", "after", "everyday"):
            ids = _suggested_ids(foods.suggest(phase, 80 if phase != "everyday" else 0, 25, rider))
            self.assertFalse(ids & {"bagel", "vital_wheat_gluten"})

    def test_caffeine_avoiders_never_see_coffee(self):
        self.assertFalse(foods.allowed(foods.by_id(LIB)["coffee"], {"avoid_foods": ["caffeine"]}))
        self.assertFalse(foods.allowed(_food(per_100g={"caffeine_mg": 40}), {"avoid_foods": ["caffeine"]}))

    def test_diets(self):
        by = foods.by_id(LIB)
        self.assertFalse(foods.allowed(by["salmon"], {"diet": "vegetarian"}))
        self.assertTrue(foods.allowed(by["salmon"], {"diet": "pescatarian"}))
        self.assertFalse(foods.allowed(by["chicken_breast"], {"diet": "pescatarian"}))
        self.assertTrue(foods.allowed(by["chicken_breast"], {"diet": "none"}))
        self.assertTrue(foods.allowed(by["egg"], {"diet": "vegetarian"}))


class SuggestTests(unittest.TestCase):
    def test_combinations_land_within_10_percent(self):
        cases = [("during", 60, 0, {}), ("during", 90, 0, {"diet": "vegan"}),
                 ("before", 140, 0, {"diet": "vegetarian"}), ("after", 75, 25, {}),
                 ("after", 60, 25, {"avoid_foods": "dairy"}), ("everyday", 0, 30, {"diet": "pescatarian"})]
        for phase, carbs, protein, rider in cases:
            with self.subTest(phase=phase, carbs=carbs, protein=protein, rider=rider):
                result = foods.suggest(phase, carbs, protein, rider)
                self.assertTrue(result["ok"], result["message"])
                self.assertTrue(1 <= len(result["combos"]) <= 3)
                for c in result["combos"]:
                    if carbs:
                        self.assertLessEqual(abs(c["carbs_g"] - carbs), carbs * 0.10, c["text"])
                    if protein:
                        self.assertLessEqual(abs(c["protein_g"] - protein), protein * 0.10, c["text"])
                    self.assertIn("=", c["text"])

    def test_amounts_are_kitchen_sized(self):
        for c in foods.suggest("during", 75, 0, {})["combos"]:
            for p in c["items"]:
                if p["count"] == int(p["count"]) and p["text"].split()[1] == "×":
                    continue                                           # whole pieces
                self.assertEqual(p["grams"] % 5, 0, p["text"])

    def test_the_sum_matches_the_parts(self):
        c = foods.suggest("after", 60, 25, {})["combos"][0]
        self.assertAlmostEqual(c["carbs_g"], sum(p["carbs_g"] for p in c["items"]), places=0)

    def test_gut_sensitive_riders_get_low_fibre_low_fat_foods_on_the_bike(self):
        rider = {"gut_sensitive": True}
        by = foods.by_id(LIB)
        for phase in ("before", "during"):
            for fid in _suggested_ids(foods.suggest(phase, 60, 0, rider)):
                self.assertTrue(foods.gut_friendly(by[fid]), fid)

    def test_an_empty_library_gives_a_clear_message(self):
        result = foods.suggest("during", 60, 0, {}, library=[])
        self.assertFalse(result["ok"])
        self.assertIn("empty", result["message"])

    def test_a_fully_filtered_list_gives_a_clear_message(self):
        result = foods.suggest("during", 60, 0, {"avoid_foods": ["soy"]},
                               library=[_food(contains=["soy"]), _food(id="b", allergens_checked=False)])
        self.assertFalse(result["ok"])
        self.assertEqual(result["combos"], [])
        self.assertIn("avoid list", result["message"])
        unreachable = foods.suggest("during", 5000, 0, {}, library=[_food()])
        self.assertFalse(unreachable["ok"])
        self.assertIn("10 percent", unreachable["message"])

    def test_no_target_is_a_message_too(self):
        self.assertFalse(foods.suggest("during", 0, 0, {})["ok"])

    def test_plant_note_for_vegetarian_and_vegan_riders(self):
        self.assertIsNotNone(foods.plant_note({"diet": "vegan"}))
        self.assertIsNone(foods.plant_note({"diet": "none"}))
        self.assertIn("Evidence", foods.PLANT_NOTE["evidence"])


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


class DietSettingsTests(_TempDb):
    def test_answers_round_trip(self):
        diet.save({"diet": "vegan", "avoid_foods": ["sesame", "gluten"], "gut_sensitive": True,
                   "nutrition_referral": False, "height_cm": 178, "energy_sex": "prefer_not",
                   "usual_ride_time": "early", "cooking_time": "batch", "diet_notes": " No mushrooms "})
        got = diet.load()
        self.assertEqual(got["diet"], "vegan")
        self.assertEqual(got["avoid_foods"], ["gluten", "sesame"])
        self.assertIs(got["gut_sensitive"], True)
        self.assertIs(got["nutrition_referral"], False)
        self.assertEqual(got["height_cm"], 178.0)
        self.assertEqual((got["energy_sex"], got["usual_ride_time"], got["cooking_time"]),
                         ("prefer_not", "early", "batch"))
        self.assertEqual(got["diet_notes"], "No mushrooms")
        self.assertEqual(q.get_setting("gender", ""), "")              # energy_sex is kept apart

    def test_unanswered_health_question_is_not_a_no(self):
        diet.save({"nutrition_referral": None})
        self.assertIsNone(diet.load()["nutrition_referral"])
        self.assertEqual(diet.load()["diet"], "none")

    def test_change_1_reads_the_saved_height_and_sex(self):
        from metrics import nutrition_day as nd
        q.set_setting("weight_kg", 70)
        q.set_setting("birth_year", 1985)
        diet.save({"height_cm": 178, "energy_sex": "male"})
        self.assertTrue(nd.day_targets("2026-11-20")["kcal"]["estimated"])

    def test_height_in_feet_and_inches(self):
        self.assertEqual(diet.cm_from_ft_in(5, 10), 177.8)
        self.assertEqual(diet.ft_in_from_cm(177.8), (5, 10))
        self.assertEqual(diet.cm_from_height(70, "lb"), 177.8)
        self.assertEqual(diet.cm_from_height(178, "kg"), 178.0)
        self.assertIsNone(diet.cm_from_ft_in(None, None))

    def test_each_profile_keeps_its_own_answers(self):
        diet.save({"diet": "none", "avoid_foods": []})
        p = profiles.create_profile("Alex")
        with schema.use(p["path"]):
            diet.save({"diet": "vegan", "avoid_foods": ["peanuts"]})
        self.assertEqual(diet.load()["diet"], "none")
        with schema.use(p["path"]):
            self.assertEqual(diet.load()["avoid_foods"], ["peanuts"])


EATING = dict(diet="Vegetarian", avoid_foods="Peanuts, Tree nuts", gut_sensitive="Yes",
              nutrition_referral="No", height="70", energy_sex="Female", usual_ride_time="Early morning",
              cooking_time="Quick meals only", diet_notes="No mushrooms")


class IntakeTests(_TempDb):
    def test_eating_answers_import(self):
        i = ii.parse_row(_row(**{**FULL, **EATING}))
        e = i.answers["eating"]
        self.assertEqual(e["diet"], "vegetarian")
        self.assertEqual(e["avoid_foods"], ["peanuts", "tree_nuts"])
        self.assertIs(e["gut_sensitive"], True)
        self.assertIs(e["nutrition_referral"], False)
        self.assertEqual(e["height_cm"], 177.8)                        # 70 in, since they use pounds
        self.assertEqual((e["energy_sex"], e["usual_ride_time"], e["cooking_time"]), ("female", "early", "quick"))
        self.assertEqual(i.flags, [])
        self.assertNotIn("diet_notes", ii.coach_block(json.loads(ii.to_setting(i))))

    def test_yes_to_the_health_check_is_a_flag(self):
        i = ii.parse_row(_row(**{**FULL, **EATING, "nutrition_referral": "Yes"}))
        self.assertTrue(any("dietitian" in f for f in i.flags))

    def test_a_height_that_looks_wrong_is_left_blank(self):
        i = ii.parse_row(_row(**{**FULL, **EATING, "height": "178"}))     # cm typed, but units are pounds
        self.assertIsNone(i.answers["eating"]["height_cm"])
        self.assertTrue(any("Height" in n for n in i.notes))

    def test_the_form_asks_the_questions(self):
        keys = {q_.key for q_ in ii.QUESTIONS}
        self.assertLessEqual({"diet", "avoid_foods", "gut_sensitive", "nutrition_referral", "height",
                              "energy_sex", "usual_ride_time", "cooking_time", "diet_notes"}, keys)
        self.assertEqual(ii.BY_KEY["avoid_foods"].choices, tuple(diet.AVOID))

    def test_answers_save_into_the_new_profile(self):
        from components import athlete_form
        answers = ii.parse_row(_row(**{**FULL, **EATING, "plan_start": ""})).answers
        with mock.patch("ftp_change.apply_new_ftp"):
            result = athlete_form.save_athlete(answers, None)
        with schema.use(result["path"]):
            got = diet.load()
            self.assertEqual((got["diet"], got["avoid_foods"]), ("vegetarian", ["peanuts", "tree_nuts"]))
        self.assertEqual(diet.load()["diet"], "none")                  # the coach's own profile is untouched


def _by_label(items, label):
    return next(w for w in items if w.label == label)


class SettingsFormTests(_TempDb):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(st, "page_link")
        p.start()
        self.addCleanup(p.stop)

    def test_saving_how_you_eat(self):
        q.set_setting("weight_unit", "kg")
        at = AppTest.from_file(os.path.join(PAGES, "07_Settings.py"), default_timeout=60).run()
        self.assertFalse(at.exception)
        _by_label(at.selectbox, "How do you eat?").set_value("Vegan")
        _by_label(at.multiselect, "Foods you avoid").set_value(["Sesame", "Caffeine"])
        _by_label(at.radio, "Does your stomach get upset on rides?").set_value("No")
        _by_label(at.radio, diet.REFERRAL_QUESTION).set_value("No")
        _by_label(at.number_input, "Height (cm)").set_value(172)
        _by_label(at.selectbox, "Sex for energy estimates").set_value("Prefer not to say")
        _by_label(at.number_input, "Daily base calories (kcal)").set_value(2000)
        next(b for b in at.button if b.label == "Save eating answers").click().run()
        self.assertFalse(at.exception)
        got = diet.load()
        self.assertEqual((got["diet"], got["avoid_foods"]), ("vegan", ["sesame", "caffeine"]))
        self.assertIs(got["gut_sensitive"], False)
        self.assertEqual((got["height_cm"], got["energy_sex"]), (172.0, "prefer_not"))
        self.assertEqual(q.get_setting("base_kcal"), "2000")
        self.assertTrue(any("saved" in s.value for s in at.success))

    def test_height_in_feet_and_inches_for_pound_users(self):
        q.set_setting("weight_unit", "lb")
        diet.save({"height_cm": 177.8})
        at = AppTest.from_file(os.path.join(PAGES, "07_Settings.py"), default_timeout=60).run()
        self.assertFalse(at.exception)
        self.assertEqual(_by_label(at.number_input, "Height (ft)").value, 5)
        self.assertEqual(_by_label(at.number_input, "Height (in)").value, 10)


def _onboarding():
    from components import onboarding
    onboarding.render_onboarding()


def _athlete_form():
    import streamlit as st
    from components import athlete_form
    if "seed_intake" in st.session_state and athlete_form.PREFILL_KEY not in st.session_state:
        athlete_form.prefill(st.session_state["seed_intake"])
    athlete_form.render_athlete_form()


class OnboardingFormTests(_TempDb):
    def test_onboarding_saves_how_you_eat(self):
        at = AppTest.from_function(_onboarding, default_timeout=60).run()
        self.assertFalse(at.exception)
        _by_label(at.text_area, "What are your goals?").set_value("Ride my first century")
        _by_label(at.selectbox, "How do you eat?").set_value("Pescatarian")
        _by_label(at.multiselect, "Foods you avoid").set_value(["Gluten"])
        _by_label(at.radio, diet.REFERRAL_QUESTION).set_value("Yes")
        at.run()
        self.assertTrue(any("dietitian" in i.value for i in at.info))
        with mock.patch("ftp_change.apply_new_ftp"):
            next(b for b in at.button if b.label == "Get Started").click().run()
        self.assertFalse(at.exception)
        got = diet.load()
        self.assertEqual((got["diet"], got["avoid_foods"], got["nutrition_referral"]),
                         ("pescatarian", ["gluten"], True))

    def test_skipping_it_saves_no_restrictions(self):
        at = AppTest.from_function(_onboarding, default_timeout=60).run()
        _by_label(at.text_area, "What are your goals?").set_value("Get fitter")
        with mock.patch("ftp_change.apply_new_ftp"):
            next(b for b in at.button if b.label == "Get Started").click().run()
        self.assertFalse(at.exception)
        got = diet.load()
        self.assertEqual((got["diet"], got["avoid_foods"], got["nutrition_referral"]), ("none", [], None))


class AddAthleteFormTests(_TempDb):
    def test_intake_answers_fill_how_they_eat(self):
        at = AppTest.from_function(_athlete_form, default_timeout=60)
        at.session_state["adding_athlete"] = True
        at.session_state["seed_intake"] = ii.parse_row(_row(**{**FULL, **EATING, "plan_start": "", "plan_end": ""}))
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(_by_label(at.selectbox, "How do they eat?").value, "Vegetarian")
        self.assertEqual(_by_label(at.multiselect, "Foods they avoid").value, ["Peanuts", "Tree nuts"])
        self.assertEqual(_by_label(at.radio, "Does their stomach get upset on rides?").value, "Yes")
        self.assertEqual(_by_label(at.number_input, "Height (ft)").value, 5)
        self.assertEqual(_by_label(at.selectbox, "When do they usually ride?").value, "Early morning")
        self.assertEqual(_by_label(at.text_area, "Anything else about how they eat?").value, "No mushrooms")


if __name__ == "__main__":
    unittest.main()
