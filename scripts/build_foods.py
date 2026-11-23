"""Builds knowledge/foods.json from saved USDA FoodData Central responses and the metadata below.

Usage: python -I scripts/build_foods.py <responses folder> knowledge/foods.json

The folder holds the API's answers as fetched: b*.json from
  GET https://api.nal.usda.gov/fdc/v1/foods?format=full&fdcIds=<up to 20 ids>
and s*.json from
  GET https://api.nal.usda.gov/fdc/v1/foods/search?dataType=SR Legacy&query=...
Nutrient values are copied exactly as FDC gives them. Never type a value or an FDC ID by hand:
look it up, save the response, and add a line to ITEMS.

Branded foods come from the maker's label instead. scripts/food_labels.json holds what the label
prints (values per serving or per 100 g, the ingredients and the allergen statement, copied verbatim)
with the page it was read from. An ITEMS line names its label by key, in place of an FDC ID, and the
build turns the label's numbers into per 100 g values. Set checked to True for a label only when both
the ingredients and the allergen statement were read, and copy any may contain text into may_contain."""
import json
import sys
from pathlib import Path

HERE = Path(sys.argv[1])
OUT = Path(sys.argv[2])
LABELS = Path(__file__).resolve().parent / "food_labels.json"
SODIUM_PER_G_SALT = 400       # mg sodium in 1 g salt, since salt = sodium x 2.5 (EU Regulation 1169/2011, Annex I)

NUTRIENTS = {"208": "kcal", "205": "carbs_g", "203": "protein_g", "204": "fat_g", "291": "fibre_g",
             "307": "sodium_mg", "262": "caffeine_mg"}

SINGLE = "Single ingredient food, so contains comes from the food itself. Cross contact varies by brand, so check the label."
DAIRY = "Plain dairy food made from milk. Cross contact varies by brand, so check the label."
LABEL = "Read from the maker's label: ingredients and allergen statement below."
MIXED = "Ingredients vary by brand and FDC has no ingredient list, so allergens are not checked. Hidden from riders with an avoid list until a labelled product is added."

# id, fdc (an FDC ID, or a key in food_labels.json), name, serving (label, grams, unit), phases, diet, contains, may_contain, checked
# diet: V vegan, L vegetarian (eggs, dairy, honey), F pescatarian (fish), M meat
# phases: B before, D during, A after, E everyday protein or meal, I recipe ingredient
ITEMS = [
    # grains and starches
    ("oats", 173904, "Rolled oats", ("1/2 cup dry", 40, "g"), "BI", "V", [], ["gluten"], True,
     SINGLE + " Oats are often grown and milled next to wheat, so only oats labelled gluten free suit a gluten free diet."),
    ("white_rice_cooked", 168878, "White rice, cooked", ("1 cup", 158, "g"), "BAEI", "V", [], [], True, SINGLE),
    ("white_rice_raw", 169756, "White rice, uncooked", ("1/4 cup", 46, "g"), "I", "V", [], [], True, SINGLE),
    ("brown_rice_cooked", 168875, "Brown rice, cooked", ("1 cup", 195, "g"), "EI", "V", [], [], True, SINGLE),
    ("quinoa_cooked", 168917, "Quinoa, cooked", ("1 cup", 185, "g"), "EI", "V", [], ["gluten"], True,
     SINGLE + " Quinoa is often packed alongside wheat."),
    ("couscous_cooked", 169700, "Couscous, cooked", ("1 cup", 157, "g"), "BEI", "V", ["gluten"], [], True,
     "Couscous is made from wheat. " + SINGLE),
    ("pasta_cooked", 168928, "Pasta, cooked", ("1 cup", 140, "g"), "BAEI", "V", ["gluten"], ["eggs"], True,
     "Dried pasta is wheat and water. Some brands share lines with egg pasta. " + SINGLE),
    ("pasta_dry", 169736, "Pasta, dry", ("2 oz", 56, "g"), "I", "V", ["gluten"], ["eggs"], True,
     "Dried pasta is wheat and water. Some brands share lines with egg pasta. " + SINGLE),
    ("rice_noodles_dry", 169742, "Rice noodles, dry", ("2 oz", 56, "g"), "I", "V", [], [], True, SINGLE),
    ("potato_baked", 170093, "Potato, baked with skin", ("1 medium", 173, "g"), "BAEI", "V", [], [], True, SINGLE),
    ("sweet_potato_baked", 168483, "Sweet potato, baked", ("1 medium", 114, "g"), "BAEI", "V", [], [], True, SINGLE),
    ("flour_all_purpose", 169761, "Flour, all purpose", ("1/4 cup", 31, "g"), "I", "V", ["gluten"], [], True,
     "Wheat flour. " + SINGLE),
    ("vital_wheat_gluten", 168147, "Vital wheat gluten (for seitan)", ("1/4 cup", 30, "g"), "EI", "V", ["gluten"], [], True,
     "Seitan is made from wheat gluten. " + SINGLE),
    # breads and baked
    ("white_bread", 174924, "White bread", ("1 slice", 29, "piece"), "BDI", "L", ["gluten"], ["dairy", "eggs", "soy", "sesame"], False, MIXED),
    ("wholewheat_bread", 172688, "Whole wheat bread", ("1 slice", 28, "piece"), "EI", "L", ["gluten"], ["dairy", "eggs", "soy", "sesame"], False, MIXED),
    ("bagel", 174899, "Bagel, plain", ("1 medium bagel", 105, "piece"), "B", "L", ["gluten"], ["sesame", "eggs", "dairy"], False,
     MIXED + " FDC's entry includes onion, poppy and sesame bagels."),
    ("pita", 174915, "Pita bread, white", ("1 large pita", 60, "piece"), "BEI", "L", ["gluten"], ["sesame", "dairy"], False, MIXED),
    ("flour_tortilla", 175037, "Flour tortilla", ("1 tortilla (7 to 8 in)", 49, "piece"), "EI", "V", ["gluten"], ["soy", "dairy"], False, MIXED),
    ("corn_tortilla", 175036, "Corn tortilla", ("1 tortilla", 24, "piece"), "EI", "V", [], ["gluten"], False, MIXED),
    ("granola", 171646, "Granola", ("1/2 cup", 61, "g"), "AE", "L", ["gluten", "tree_nuts"], ["peanuts", "sesame", "soy", "dairy"], False,
     MIXED + " FDC's entry is a homemade recipe with nuts."),
    ("fig_bar", 172721, "Fig bar", ("1 bar", 16, "piece"), "D", "L", ["gluten"], ["dairy", "eggs", "soy", "tree_nuts"], False, MIXED),
    ("rice_cake", 170250, "Rice cake, plain", ("1 cake", 9, "piece"), "DB", "V", [], ["sesame", "gluten"], False,
     MIXED + " Plain rice cakes are often made on lines with sesame or wheat versions."),
    ("pretzels", 167555, "Pretzels, hard", ("1 oz", 28, "g"), "D", "V", ["gluten"], ["sesame", "soy", "dairy"], False, MIXED),
    ("gummies", 167989, "Gummy sweets (starch jelly)", ("10 gummies", 36, "g"), "D", "V", [], [], False,
     MIXED + " Many gummies contain gelatin, so check the label if you eat vegetarian."),
    # sweet and spreads
    ("honey", 169640, "Honey", ("1 tbsp", 21, "g"), "BDI", "L", [], [], True, SINGLE),
    ("maple_syrup", 169661, "Maple syrup", ("1 tbsp", 20, "g"), "BDI", "V", [], [], True, SINGLE),
    ("sugar", 169655, "Sugar, white", ("1 tbsp", 12.5, "g"), "I", "V", [], [], True, SINGLE + " Some vegans avoid cane sugar filtered with bone char."),
    ("brown_sugar", 168833, "Brown sugar", ("1 tbsp", 13.8, "g"), "I", "V", [], [], True, SINGLE),
    ("jam", 169641, "Jam", ("1 tbsp", 20, "g"), "BDI", "V", [], [], False, MIXED),
    ("peanut_butter", 172470, "Peanut butter, smooth", ("2 tbsp", 32, "g"), "BEI", "V", ["peanuts"], ["tree_nuts"], True,
     "Peanuts, sometimes salt. Many brands share lines with tree nut butters, so check the label."),
    ("cocoa", 169593, "Cocoa powder, unsweetened", ("1 tbsp", 5.4, "g"), "I", "V", [], ["dairy", "tree_nuts", "peanuts"], True,
     SINGLE + " Cocoa is often made alongside milk chocolate and nuts."),
    # fruit
    ("banana", 173944, "Banana", ("1 medium banana", 118, "piece"), "BDAI", "V", [], [], True, SINGLE),
    ("apple", 171688, "Apple", ("1 medium apple", 182, "piece"), "BEI", "V", [], [], True, SINGLE),
    ("orange", 169097, "Orange", ("1 orange", 131, "piece"), "BEI", "V", [], [], True, SINGLE),
    ("blueberries", 171711, "Blueberries", ("1 cup", 148, "g"), "AEI", "V", [], [], True, SINGLE),
    ("strawberries", 167762, "Strawberries", ("1 cup halves", 152, "g"), "AEI", "V", [], [], True, SINGLE),
    ("raspberries", 167755, "Raspberries", ("1 cup", 123, "g"), "AEI", "V", [], [], True, SINGLE),
    ("raspberries_frozen", 168209, "Raspberries, frozen", ("1 cup", 140, "g"), "AI", "V", [], [], True, SINGLE),
    ("mango", 169910, "Mango", ("1 cup pieces", 165, "g"), "AEI", "V", [], [], True, SINGLE),
    ("raisins", 168165, "Raisins", ("small box (1.5 oz)", 43, "g"), "BDI", "V", [], [], True, SINGLE),
    ("medjool_dates", 168191, "Medjool dates", ("1 date, pitted", 24, "piece"), "BDI", "V", [], ["tree_nuts"], True,
     SINGLE + " Dates are often packed alongside nuts."),
    ("avocado", 171705, "Avocado", ("1/2 avocado", 100, "g"), "EI", "V", [], [], True, SINGLE),
    ("applesauce", 171695, "Applesauce, unsweetened", ("1/2 cup", 122, "g"), "BDI", "V", [], [], True,
     "Apples and water. " + SINGLE),
    ("orange_juice", 169098, "Orange juice", ("1 cup", 248, "ml"), "BAI", "V", [], [], True, SINGLE),
    ("lemon_juice", 167747, "Lemon juice", ("1 tbsp", 15, "ml"), "I", "V", [], [], True, SINGLE),
    # dairy and eggs
    ("egg", 171287, "Egg", ("1 large egg", 50, "piece"), "AEI", "L", ["eggs"], [], True, SINGLE),
    ("egg_boiled", 173424, "Egg, hard boiled", ("1 large egg", 50, "piece"), "AE", "L", ["eggs"], [], True, SINGLE),
    ("milk_whole", 171265, "Milk, whole", ("1 cup", 244, "ml"), "BAEI", "L", ["dairy"], [], True, DAIRY),
    ("milk_2pct", 171267, "Milk, 2%", ("1 cup", 244, "ml"), "BAEI", "L", ["dairy"], [], True, DAIRY),
    ("chocolate_milk", 173450, "Chocolate milk, reduced fat", ("1 cup", 250, "ml"), "A", "L", ["dairy"], [], False, MIXED),
    ("greek_yogurt", 170903, "Greek yogurt, plain, lowfat", ("3/4 cup", 170, "g"), "AEI", "L", ["dairy"], [], True, DAIRY),
    ("greek_yogurt_whole", 171304, "Greek yogurt, plain, whole milk", ("3/4 cup", 170, "g"), "AEI", "L", ["dairy"], [], True, DAIRY),
    ("cottage_cheese", 173417, "Cottage cheese, 1%", ("1/2 cup", 113, "g"), "AEI", "L", ["dairy"], [], True, DAIRY),
    ("cheddar", 173414, "Cheddar cheese", ("1 oz", 28, "g"), "EI", "L", ["dairy"], [], True, DAIRY),
    ("mozzarella", 170845, "Mozzarella", ("1 oz", 28, "g"), "EI", "L", ["dairy"], [], True, DAIRY),
    ("cream_cheese", 173418, "Cream cheese", ("1 tbsp", 14.5, "g"), "BI", "L", ["dairy"], [], True, DAIRY),
    ("butter", 173410, "Butter, salted", ("1 tbsp", 14, "g"), "I", "L", ["dairy"], [], True, DAIRY),
    # plant protein
    ("tofu_firm", 172475, "Tofu, firm", ("1/2 cup", 126, "g"), "AEI", "V", ["soy"], [], True,
     "Soybeans, water and a calcium coagulant. " + SINGLE),
    ("tempeh", 174272, "Tempeh", ("100 g", 100, "g"), "AEI", "V", ["soy"], ["gluten"], True,
     "Fermented soybeans. Some tempeh adds barley or other grains, so check the label."),
    ("edamame", 168411, "Edamame", ("1 cup shelled", 155, "g"), "AEI", "V", ["soy"], [], True, SINGLE),
    ("soy_milk", 175215, "Soy milk, unsweetened", ("1 cup", 243, "ml"), "BAEI", "V", ["soy"], [], False, MIXED),
    ("soy_yogurt", 175227, "Soy yogurt, plain (Silk)", ("1 container (6 oz)", 170, "g"), "AEI", "V", ["soy"], [], False,
     "Branded food (Silk) in FDC's SR Legacy set. The label has not been read yet, so allergens are not checked."),
    ("lentils", 172421, "Lentils, cooked", ("1 cup", 198, "g"), "AEI", "V", [], ["gluten"], True,
     SINGLE + " Lentils can carry stray grains of wheat or barley."),
    ("chickpeas", 173757, "Chickpeas, cooked", ("1 cup", 164, "g"), "AEI", "V", [], [], True, SINGLE),
    ("black_beans", 173735, "Black beans, cooked", ("1 cup", 172, "g"), "AEI", "V", [], [], True, SINGLE),
    ("pinto_beans", 175200, "Pinto beans, cooked", ("1 cup", 171, "g"), "EI", "V", [], [], True, SINGLE),
    ("kidney_beans", 173741, "Kidney beans, canned", ("1/2 cup", 128, "g"), "EI", "V", [], [], True,
     "Beans, water and salt. " + SINGLE),
    ("white_beans", 175204, "White beans, canned", ("1/2 cup", 131, "g"), "EI", "V", [], [], True,
     "Beans, water and salt. " + SINGLE),
    ("hummus", 174289, "Hummus", ("2 tbsp", 30, "g"), "EI", "V", ["sesame"], [], False, MIXED + " Hummus is usually made with tahini."),
    # nuts and seeds
    ("peanuts", 172430, "Peanuts", ("1 oz", 28, "g"), "EI", "V", ["peanuts"], ["tree_nuts"], True, SINGLE),
    ("almonds", 170567, "Almonds", ("1 oz", 28, "g"), "EI", "V", ["tree_nuts"], ["peanuts"], True, SINGLE),
    ("walnuts", 170187, "Walnuts", ("1 oz", 28, "g"), "EI", "V", ["tree_nuts"], ["peanuts"], True, SINGLE),
    ("cashews", 170162, "Cashews", ("1 oz", 28, "g"), "EI", "V", ["tree_nuts"], ["peanuts"], True, SINGLE),
    ("sunflower_seeds", 170562, "Sunflower seeds", ("1 oz", 28, "g"), "EI", "V", [], ["peanuts", "tree_nuts", "sesame"], True,
     SINGLE + " Seeds are often packed with nuts."),
    ("pumpkin_seeds", 170556, "Pumpkin seeds", ("1 oz", 28, "g"), "EI", "V", [], ["peanuts", "tree_nuts", "sesame"], True,
     SINGLE + " Seeds are often packed with nuts."),
    ("chia_seeds", 170554, "Chia seeds", ("1 tbsp", 12, "g"), "I", "V", [], ["peanuts", "tree_nuts", "sesame"], True,
     SINGLE + " Seeds are often packed with nuts."),
    ("flaxseed", 169414, "Flaxseed", ("1 tbsp", 10, "g"), "I", "V", [], ["peanuts", "tree_nuts", "sesame"], True,
     SINGLE + " Seeds are often packed with nuts."),
    ("sesame_seeds", 170150, "Sesame seeds", ("1 tbsp", 9, "g"), "I", "V", ["sesame"], [], True, SINGLE),
    ("tahini", 168604, "Tahini", ("1 tbsp", 15, "g"), "I", "V", ["sesame"], [], True, "Ground sesame. " + SINGLE),
    # meat and fish
    ("chicken_breast", 171477, "Chicken breast, roasted", ("100 g", 100, "g"), "AEI", "M", [], [], True, SINGLE),
    ("ground_beef", 174036, "Ground beef, 80% lean, raw", ("4 oz raw", 113, "g"), "I", "M", [], [], True, SINGLE),
    ("salmon", 175168, "Salmon, cooked", ("100 g", 100, "g"), "AEI", "F", ["fish_shellfish"], [], True, SINGLE),
    ("tuna_canned", 171986, "Tuna, canned in water", ("1 can drained (about 140 g)", 140, "g"), "AEI", "F", ["fish_shellfish"], ["soy"], False,
     MIXED + " Some brands add vegetable broth made with soy."),
    # vegetables
    ("spinach", 168462, "Spinach", ("1 cup", 30, "g"), "I", "V", [], [], True, SINGLE),
    ("kale", 168421, "Kale", ("1 cup chopped", 21, "g"), "I", "V", [], [], True, SINGLE),
    ("broccoli", 170379, "Broccoli", ("1 cup chopped", 91, "g"), "I", "V", [], [], True, SINGLE),
    ("carrots", 170393, "Carrots", ("1 medium", 61, "g"), "I", "V", [], [], True, SINGLE),
    ("tomatoes", 170457, "Tomatoes", ("1 medium", 123, "g"), "I", "V", [], [], True, SINGLE),
    ("tomatoes_canned", 170051, "Tomatoes, canned in juice", ("1 can (190 g)", 190, "g"), "I", "V", [], [], True,
     "Tomatoes and tomato juice. " + SINGLE),
    ("onion", 170000, "Onion", ("1 medium", 110, "g"), "I", "V", [], [], True, SINGLE),
    ("garlic", 169230, "Garlic", ("1 clove", 3, "g"), "I", "V", [], [], True, SINGLE),
    ("red_pepper", 170108, "Red bell pepper", ("1 medium", 119, "g"), "I", "V", [], [], True, SINGLE),
    ("peas_frozen", 170016, "Peas, frozen", ("1/2 cup", 67, "g"), "I", "V", [], [], True, SINGLE),
    ("cucumber", 168409, "Cucumber", ("1/2 cup slices", 52, "g"), "I", "V", [], [], True, SINGLE),
    ("romaine", 169247, "Romaine lettuce", ("1 cup shredded", 47, "g"), "I", "V", [], [], True, SINGLE),
    # oils, seasonings and baking
    ("olive_oil", 171413, "Olive oil", ("1 tbsp", 13.5, "g"), "I", "V", [], [], True, SINGLE),
    ("canola_oil", 172336, "Canola oil", ("1 tbsp", 14, "g"), "I", "V", [], [], True, SINGLE),
    ("coconut_milk", 170173, "Coconut milk, canned", ("1/4 cup", 60, "ml"), "I", "V", [], ["tree_nuts"], False,
     MIXED + " Coconut is no longer listed as a tree nut by the FDA, but some people with nut allergies react to it."),
    ("salt", 173468, "Salt", ("1/4 tsp", 1.5, "g"), "I", "V", [], [], True, SINGLE),
    ("cinnamon", 171320, "Cinnamon, ground", ("1 tsp", 2.6, "g"), "I", "V", [], [], True, SINGLE),
    ("cumin", 170923, "Cumin seed", ("1 tsp", 2.1, "g"), "I", "V", [], [], True, SINGLE),
    ("paprika", 171329, "Paprika", ("1 tsp", 2.3, "g"), "I", "V", [], [], True, SINGLE),
    ("ginger_ground", 170926, "Ginger, ground", ("1 tsp", 1.8, "g"), "I", "V", [], [], True, SINGLE),
    ("curry_powder", 170924, "Curry powder", ("1 tsp", 2, "g"), "I", "V", [], [], False, MIXED + " Spice blends can contain mustard or wheat."),
    ("chili_powder", 171319, "Chili powder", ("1 tsp", 2.7, "g"), "I", "V", [], [], False, MIXED + " Spice blends can contain wheat."),
    ("soy_sauce", 174277, "Soy sauce", ("1 tbsp", 16, "ml"), "I", "V", ["soy", "gluten"], [], True,
     "Shoyu is brewed from soy and wheat. Tamari is the usual wheat free swap."),
    ("vanilla", 173471, "Vanilla extract", ("1 tsp", 4.2, "ml"), "I", "V", [], [], True, "Vanilla and alcohol. " + SINGLE),
    ("baking_powder", 172804, "Baking powder", ("1 tsp", 4.6, "g"), "I", "V", [], ["gluten"], False, MIXED + " Some use wheat starch."),
    ("baking_soda", 175040, "Baking soda", ("1 tsp", 4.6, "g"), "I", "V", [], [], True, SINGLE),
    # drinks
    ("coffee", 171890, "Coffee, brewed", ("1 cup", 237, "ml"), "B", "V", ["caffeine"], [], True, SINGLE),
    # branded, from the maker's label (scripts/food_labels.json)
    ("maurten_gel_100", "maurten_gel_100", "Maurten Gel 100", ("1 sachet", 40, "piece"), "BD", "V", [], [], True,
     LABEL + " No may contain text. The maker says the gel is not certified gluten free."),
    ("maurten_gel_100_caf", "maurten_gel_100_caf_100", "Maurten Gel 100 Caf 100", ("1 sachet", 40, "piece"),
     "BD", "V", ["caffeine"], [], True,
     LABEL + " No may contain text. The maker says the gel is not certified gluten free."),
    ("skratch_hydration", "skratch_sport_hydration_lemon_lime", "Skratch Sport Hydration mix, Lemon + Lime",
     ("1 scoop", 22, "g"), "D", "V", [], [], True,
     LABEL + " The label says dairy free, gluten free and nut free, with no may contain text."),
    ("maltodextrin", "now_carbo_gain_maltodextrin", "Maltodextrin, mixed in your bottles (NOW Carbo Gain)",
     ("1/4 cup", 31.5, "g"), "DI", "V",
     [], ["gluten", "soy", "dairy", "eggs", "fish_shellfish", "tree_nuts", "sesame"], True,
     LABEL + " Pure maltodextrin, made in a facility that also handles wheat, soy, milk, egg, fish, shellfish, "
     "tree nuts and sesame. Peanuts are not named."),
    ("pea_protein", "now_pea_protein_unflavored", "Pea protein powder, unflavored (NOW)", ("1 scoop", 33, "g"), "AEI", "V",
     [], ["gluten", "soy", "dairy", "eggs", "fish_shellfish", "tree_nuts", "sesame"], True,
     LABEL + " Pea protein isolate, made in a facility that also handles wheat, soy, milk, egg, fish, shellfish, "
     "tree nuts and sesame. Peanuts are not named."),
    ("whey_protein", "on_gold_standard_whey_drc", "Whey protein powder, chocolate (Optimum Nutrition)", ("1 scoop", 31, "g"),
     "AEI", "L", ["dairy", "soy"], [], True,
     LABEL + " Contains milk and soy (lecithin). No may contain text."),
    ("soy_chocolate_milk", "silk_chocolate_soymilk", "Soy chocolate milk (Silk)", ("1 cup", 240, "ml"), "AE", "V",
     ["soy"], [], True, LABEL + " Contains soy. No may contain text."),
    ("gnocchi", "de_cecco_gnocchi_di_patate", "Potato gnocchi, shelf stable (De Cecco)", ("100 g", 100, "g"), "EI", "V",
     ["gluten"], ["soy"], True,
     LABEL + " Contains wheat. May contain soy and mustard (mustard is not on the app's avoid list)."),
]

DIETS = {"V": ["vegan", "vegetarian", "pescatarian"], "L": ["vegetarian", "pescatarian"], "F": ["pescatarian"], "M": []}
PHASES = {"B": "before", "D": "during", "A": "after", "E": "everyday", "I": "ingredient"}


PORTIONS = {}


def load_fdc():
    out = {}
    for p in sorted(HERE.glob("b*.json")):
        for f in json.loads(p.read_text()):
            vals = {NUTRIENTS[n["nutrient"]["number"]]: n.get("amount")
                    for n in f["foodNutrients"] if n.get("nutrient", {}).get("number") in NUTRIENTS}
            out[f["fdcId"]] = (f["description"], f.get("dataType"), vals)
            PORTIONS[f["fdcId"]] = [p.get("gramWeight") for p in f.get("foodPortions", [])]
    for p in sorted(HERE.glob("s*.json")):
        for f in json.loads(p.read_text()).get("foods", []):
            if f["fdcId"] in out:
                continue
            vals = {NUTRIENTS[n["nutrientNumber"]]: n.get("value")
                    for n in f["foodNutrients"] if n.get("nutrientNumber") in NUTRIENTS}
            out[f["fdcId"]] = (f["description"], f.get("dataType"), vals)
    return out


def load_labels():
    """Label values as per 100 g, with a source block that records the brand and the page."""
    out = {}
    for key, lab in json.loads(LABELS.read_text())["labels"].items():
        vals = dict(lab["values"])
        if "salt_g" in vals:
            salt = vals.pop("salt_g")
            vals["sodium_mg"] = None if salt is None else round(salt * SODIUM_PER_G_SALT, 1)
        scale = 1.0 if lab["per"] == "100g" else 100 / lab["serving_g"]
        per_100g = {k: (None if vals.get(k) is None else round(vals[k] * scale, 2)) for k in NUTRIENTS.values()}
        source = {"database": "Maker's label", "brand": lab["brand"], "product": lab["product"],
                  "url": lab["url"], "read": lab["read"], "label_serving": lab["label_serving"],
                  "label_per": "100 g" if lab["per"] == "100g" else f"{lab['serving_g']:g} g serving",
                  "label_values": lab["values"], "ingredients": lab["ingredients"],
                  "allergen_statement": lab["allergen_statement"]}
        for extra in ("nutrition_url", "allergen_url", "value_notes"):
            if extra in lab:
                source[extra] = lab[extra]
        out[key] = (per_100g, lab.get("serving_g"), source)
    return out


def main():
    fdc = load_fdc()
    labels = load_labels()
    items, seen = [], set()
    for (iid, fid, name, serving, phases, diet, contains, may, checked, note) in ITEMS:
        assert iid not in seen, iid
        seen.add(iid)
        label, grams, unit = serving
        if isinstance(fid, str):
            per_100g, label_g, source = labels[fid]
            served_from = "label" if grams == label_g else "app"
        else:
            desc, dtype, vals = fdc[fid]
            per_100g = {k: vals.get(k) for k in NUTRIENTS.values()}
            served_from = "FDC portion" if grams in PORTIONS.get(fid, []) else "app"
            source = {"database": "USDA FoodData Central", "data_type": dtype, "fdc_id": fid, "description": desc}
        items.append({
            "id": iid, "name": name,
            "serving": {"label": label, "g": grams, "unit": unit, "from": served_from},
            "per_100g": per_100g,
            "phases": [PHASES[c] for c in phases],
            "diets": DIETS[diet],
            "contains": contains, "may_contain": may, "allergens_checked": checked,
            "allergen_source": note,
            "source": source,
        })
    doc = {
        "about": ("Foods and recipe ingredients for fueling suggestions. Nutrient values are per 100 g "
                  "exactly as USDA FoodData Central gives them (SR Legacy, looked up 2026-11-22 and "
                  "2026-11-23), with the FDC ID and description for each. Branded foods come from the "
                  "maker's label instead (read 2026-11-23), scaled from the label serving to 100 g, with "
                  "the brand, page, label values, ingredients and allergen statement in source. Serving "
                  "sizes say where they came from: an FDC portion weight, the label serving, or a common "
                  "household measure set by the app. FDC has no allergen data: contains and may_contain "
                  "are filled from the food itself for single ingredient foods, and from the label's "
                  "contains and may contain text for branded foods. allergens_checked is true only for "
                  "those, plain dairy, and labels where both the ingredients and allergen statement were "
                  "read. Mixed foods stay unchecked until a labelled product is added. A null nutrient "
                  "means the source has no value for it."),
        "allergens": ["gluten", "dairy", "eggs", "peanuts", "tree_nuts", "soy", "fish_shellfish", "sesame", "caffeine"],
        "foods": items,
    }
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(len(items), "foods")


main()
