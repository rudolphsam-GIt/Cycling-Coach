"""
Recipes riders can cook through the day (knowledge/recipes.json), built on the food library.

Every ingredient is a food library id, so the same safety rule applies. allowed_recipes() is firm. It
tries the recipe's swaps first, then checks every ingredient with foods.allowed(). A recipe with any
ingredient the rider can't have, and no swap that fixes it, is never shown. With an avoid list, an
ingredient whose allergens aren't checked hides the recipe too. Caffeinated recipes are left out unless
asked for, the same as foods.suggest.

Macros, diet tags and allergens are computed from the ingredients, never typed in. Everything else
(portion size, which recipe for which meal, what to cook ahead) is a suggestion the rider can change.
The split of the day's carbs across meals (SLOT_SHARE) is set by this app, not by research.
"""
from __future__ import annotations

import itertools
import json
import math
import os
from datetime import date as Date, timedelta
from functools import lru_cache

from metrics import foods as foods_mod
from metrics import units

RECIPES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "knowledge", "recipes.json")

SLOTS = ("breakfast", "pre_ride", "pocket", "recovery", "lunch", "dinner", "snack")
SLOT_LABELS = {"breakfast": "Breakfast", "pre_ride": "Pre ride", "pocket": "Pocket food",
               "recovery": "Recovery", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snack"}
NUTRIENTS = ("kcal", "carbs_g", "protein_g", "fat_g", "fibre_g", "sodium_mg")
ALLERGENS = ("gluten", "dairy", "eggs", "peanuts", "tree_nuts", "soy", "fish_shellfish", "sesame")

# A starting split of the day's carbs across meals. Set by this app as a rough guide, not from research.
# Pocket food is sized by the ride's own carbs per hour (metrics.fueling.during), so it has no share.
SLOT_SHARE = {"breakfast": 0.20, "pre_ride": 0.10, "lunch": 0.20, "dinner": 0.25, "recovery": 0.15,
              "snack": 0.10}
FIT_RANGE = (0.5, 1.5)       # one serving fits a meal when its carbs are half to one and a half of the share
QUICK_MIN = 30               # "Quick meals only" riders see meals done in 30 minutes first
LONG_DAY_MIN = 180           # 3 hours or more counts as a long day
HARD_IF = 0.85               # matches metrics.fueling: a hard session
BIG_DAY_DINNER = "dinner"


# ── Loading ──────────────────────────────────────────────────────────────────

@lru_cache(maxsize=4)
def _read(path: str, mtime: float) -> tuple:
    with open(path, encoding="utf-8") as f:
        return tuple(json.load(f).get("recipes", []))


def load_recipes(path: str | None = None) -> list[dict]:
    path = path or RECIPES_PATH
    try:
        return [dict(r) for r in _read(path, os.path.getmtime(path))]
    except (OSError, ValueError):
        return []


def recipe_by_id(recipe_id: str, recipes: list[dict] | None = None) -> dict | None:
    return next((r for r in (recipes if recipes is not None else load_recipes()) if r["id"] == recipe_id), None)


# ── Amounts and macros ───────────────────────────────────────────────────────

def grams(ingredient: dict, food: dict) -> float:
    """An ingredient's weight in grams, whether it's given in g, ml or a count."""
    if "count" in ingredient:
        return ingredient["count"] * food["serving"]["g"]
    if "ml" in ingredient:
        density = units.grams_per_ml(food) or 1.0
        return ingredient["ml"] * density
    return float(ingredient["g"])


def amount_text(ingredient: dict, food: dict) -> str:
    """For example "80 g rolled oats (about 1 cup)" or "2 × large egg (100 g)"."""
    amount, note = units.kitchen_parts(food, grams(ingredient, food), ml=ingredient.get("ml"),
                                       count=ingredient.get("count"))
    text = amount if "count" in ingredient else f"{amount} {food['name'].lower()}"
    return f"{text} ({note})" if note else text


def totals(ingredients: list[dict], library: dict | None = None) -> dict:
    """Nutrients for the whole batch. A value the food library lacks counts as 0."""
    lib = library if library is not None else foods_mod.by_id()
    out = {k: 0.0 for k in NUTRIENTS}
    for ing in ingredients:
        food = lib[ing["food"]]
        g = grams(ing, food)
        for k in NUTRIENTS:
            out[k] += (food.get("per_100g", {}).get(k) or 0) * g / 100
    return out


def per_serving(recipe: dict, library: dict | None = None) -> dict:
    t = totals(recipe["ingredients"], library)
    n = recipe.get("servings") or 1
    return {k: round(v / n, 1) for k, v in t.items()}


def allergens(recipe: dict, library: dict | None = None) -> dict:
    """Everything any ingredient contains or may contain, and whether all of them are checked."""
    lib = library if library is not None else foods_mod.by_id()
    contains, may = set(), set()
    checked = True
    for ing in recipe["ingredients"]:
        food = lib[ing["food"]]
        contains |= set(food.get("contains") or [])
        may |= set(food.get("may_contain") or [])
        checked = checked and bool(food.get("allergens_checked"))
    return {"contains": sorted(contains), "may_contain": sorted(may - contains), "checked": checked}


def diet_tags(recipe: dict, library: dict | None = None) -> list[str]:
    """Diets every ingredient fits, plus free from tags when all allergen data is checked."""
    lib = library if library is not None else foods_mod.by_id()
    diets = None
    for ing in recipe["ingredients"]:
        d = set(lib[ing["food"]].get("diets") or [])
        diets = d if diets is None else diets & d
    tags = [d for d in ("vegan", "vegetarian", "pescatarian") if d in (diets or set())]
    a = allergens(recipe, lib)
    if a["checked"]:
        marked = set(a["contains"]) | set(a["may_contain"])
        for allergen, tag in (("gluten", "gluten_free"), ("dairy", "dairy_free")):
            if allergen not in marked:
                tags.append(tag)
        if not marked & {"peanuts", "tree_nuts"}:
            tags.append("nut_free")
    return tags


def has_caffeine(recipe: dict, library: dict | None = None) -> bool:
    """True when an ingredient is a caffeine source (coffee, a caffeinated gel), marked in its contains list.

    Cocoa and chocolate milk carry a little natural caffeine without being a caffeine source, so they
    don't count here. Their mg still shows on the card, and riders who avoid caffeine never see them,
    because foods.blocked_by hides any food with caffeine from them."""
    lib = library if library is not None else foods_mod.by_id()
    return any("caffeine" in (lib[i["food"]].get("contains") or []) for i in recipe["ingredients"])


def caffeine_mg(recipe: dict, library: dict | None = None) -> float:
    lib = library if library is not None else foods_mod.by_id()
    n = recipe.get("servings") or 1
    return sum((lib[i["food"]].get("per_100g", {}).get("caffeine_mg") or 0) * grams(i, lib[i["food"]]) / 100
               for i in recipe["ingredients"]) / n


def total_minutes(recipe: dict) -> int:
    return int(recipe.get("prep_min") or 0) + int(recipe.get("cook_min") or 0)


# ── The safety filter, with swaps ────────────────────────────────────────────

def _blocked(ingredient: dict, settings, lib: dict) -> str | None:
    return foods_mod.blocked_by(lib[ingredient["food"]], settings)


def resolve(recipe: dict, settings, library: dict | None = None, caffeine: bool = False) -> dict:
    """The recipe as this rider would cook it, or why it's hidden.

    Each ingredient the rider can't have is replaced by the first swap for it whose new ingredients are
    all allowed. A swap that keeps a blocked food (walnuts for almonds, for a nut free rider) is never
    used. Returns {"ok", "recipe", "swaps_used", "reason"}. The resolved recipe carries its computed
    macros, allergens and tags."""
    lib = library if library is not None else foods_mod.by_id()
    used, ingredients = [], []
    for ing in recipe["ingredients"]:
        why = _blocked(ing, settings, lib)
        if why is None:
            ingredients.append(ing)
            continue
        fix = None
        for swap in recipe.get("swaps", []):
            if swap.get("replace") != ing["food"]:
                continue
            new = swap.get("with", [])
            if all(_blocked(n, settings, lib) is None for n in new):
                fix = swap
                break
        if fix is None:
            return {"ok": False, "recipe": None, "swaps_used": [],
                    "reason": f"{lib[ing['food']]['name']}: {why}"}
        used.append(fix)
        ingredients.extend(fix.get("with", []))
    out = dict(recipe, ingredients=ingredients)
    # Checked again on the finished list, so a swap can never bring back a blocked food.
    for ing in ingredients:
        why = _blocked(ing, settings, lib)
        if why:
            return {"ok": False, "recipe": None, "swaps_used": [],
                    "reason": f"{lib[ing['food']]['name']}: {why}"}
    if not caffeine and has_caffeine(out, lib):
        return {"ok": False, "recipe": None, "swaps_used": [], "reason": "contains caffeine"}
    return {"ok": True, "recipe": _with_computed(out, lib, used), "swaps_used": used, "reason": None}


def _with_computed(recipe: dict, lib: dict, used: list) -> dict:
    return dict(recipe, per_serving=per_serving(recipe, lib), allergens=allergens(recipe, lib),
                tags=diet_tags(recipe, lib), caffeine_mg=round(caffeine_mg(recipe, lib)), swaps_used=[s["text"] for s in used],
                minutes=total_minutes(recipe))


def allowed_recipes(settings, recipes: list[dict] | None = None, library: dict | None = None,
                    caffeine: bool = False) -> list[dict]:
    """Every recipe this rider can have, with swaps applied. A firm safety rule."""
    lib = library if library is not None else foods_mod.by_id()
    out = []
    for r in (recipes if recipes is not None else load_recipes()):
        res = resolve(r, settings, lib, caffeine=caffeine)
        if res["ok"]:
            out.append(res["recipe"])
    return out


def hidden_recipes(settings, recipes: list[dict] | None = None, library: dict | None = None) -> list[dict]:
    """The recipes left out for this rider and why, for a short note on the page."""
    lib = library if library is not None else foods_mod.by_id()
    out = []
    for r in (recipes if recipes is not None else load_recipes()):
        res = resolve(r, settings, lib)
        if not res["ok"]:
            out.append({"id": r["id"], "name": r["name"], "reason": res["reason"]})
    return out


# ── Scaling ──────────────────────────────────────────────────────────────────

WHOLE_ONLY = {"egg", "egg_boiled"}   # eggs stay whole. Bananas, bagels and bread can be halved.


def _count_options(ing: dict, factor: float) -> list:
    step = 1 if ing["food"] in WHOLE_ONLY else 0.5
    raw = ing["count"] * factor
    options = {max(step, math.floor(raw / step) * step), max(step, math.ceil(raw / step) * step)}
    return sorted(int(o) if float(o).is_integer() else o for o in options)


def _round_amount(value: float) -> float:
    """Sensible kitchen sizes. 10 g (or ml) steps from 20 up, 5 from 5, half grams for spices."""
    if value >= 20:
        return round(value / 10) * 10
    if value >= 5:
        return max(5.0, round(value / 5) * 5)
    return max(0.5, round(value * 2) / 2)


def scale(recipe: dict, carbs_g: float | None = None, protein_g: float | None = None,
          library: dict | None = None) -> dict:
    """The same recipe and number of servings, with each serving sized to the target.

    With both targets the factor sits between the two, so neither misses by much. Eggs round to whole
    ones, bananas, bagels and bread slices to halves, weights to 10 g steps. Returns {"recipe", "factor",
    "per_serving", "note"}, where per_serving is worked out again from the rounded amounts."""
    lib = library if library is not None else foods_mod.by_id()
    base = per_serving(recipe, lib)
    factors = []
    if carbs_g and base["carbs_g"]:
        factors.append(carbs_g / base["carbs_g"])
    if protein_g and base["protein_g"]:
        factors.append(protein_g / base["protein_g"])
    if not factors:
        return {"recipe": recipe, "factor": 1.0, "per_serving": base,
                "note": "There is no carb or protein target to scale to."}
    # Two targets: the harmonic mean keeps the bigger of the two misses as small as it can be.
    factor = factors[0] if len(factors) == 1 else 2 * factors[0] * factors[1] / (factors[0] + factors[1])

    n = recipe.get("servings") or 1
    want = {k: t for k, t in (("carbs_g", carbs_g), ("protein_g", protein_g)) if t}

    def miss(ingredients) -> float:
        got = totals(ingredients, lib)
        return max(abs(got[k] / n - t) / t for k, t in want.items())

    def build(counts: dict, weigh: float) -> list[dict]:
        out = []
        for i, ing in enumerate(recipe["ingredients"]):
            if "count" in ing:
                out.append(dict(ing, count=counts[i]))
            elif "ml" in ing:
                out.append(dict(ing, ml=_round_amount(ing["ml"] * weigh)))
            else:
                out.append(dict(ing, g=_round_amount(ing["g"] * weigh)))
        return out

    # Whole foods round first, trying the size either side. The weighed ingredients then make up what
    # rounding added or lost, so one bagel can't push a small portion far off its target. Of the
    # options, the closest to the target wins, then the one that keeps the recipe's proportions.
    counted = [(i, ing) for i, ing in enumerate(recipe["ingredients"]) if "count" in ing]
    weighed = [ing for ing in recipe["ingredients"] if "count" not in ing]
    base_weighed = totals(weighed, lib)
    best = None
    for choice in itertools.product(*(_count_options(ing, factor) for _, ing in counted)):
        counts = {i: c for (i, _), c in zip(counted, choice)}
        fixed = totals([dict(ing, count=counts[i]) for i, ing in counted], lib)
        fs = [(t * n - fixed[k]) / base_weighed[k] for k, t in want.items() if base_weighed[k] > 0]
        fs = [f for f in fs if f > 0]
        weigh = (fs[0] if len(fs) == 1 else 2 * fs[0] * fs[1] / (fs[0] + fs[1])) if fs else factor
        ingredients = build(counts, weigh)
        score = (miss(ingredients) > 0.05, abs(math.log(weigh / factor)))
        if best is None or score < best[0]:
            best = (score, ingredients)
    ingredients = best[1]

    # Rounding to 10 g steps can still leave a small portion a little off. Nudge one weighed
    # ingredient at a time by one step while that brings it closer.
    for _ in range(6):
        current = miss(ingredients)
        if current <= 0.03:
            break
        tries = []
        for i, ing in enumerate(ingredients):
            key = "ml" if "ml" in ing else "g" if "g" in ing else None
            if not key:
                continue
            step = 10 if ing[key] >= 20 else 5 if ing[key] >= 5 else 0.5
            for move in (step, -step):
                if ing[key] + move <= 0:
                    continue
                trial = ingredients[:i] + [dict(ing, **{key: ing[key] + move})] + ingredients[i + 1:]
                tries.append((miss(trial), i, trial))
        if not tries or min(tries, key=lambda t: t[:2])[0] >= current:
            break
        ingredients = min(tries, key=lambda t: t[:2])[2]
    scaled = dict(recipe, ingredients=ingredients)
    after = per_serving(scaled, lib)
    if "per_serving" in recipe:
        scaled["per_serving"] = after
    parts = []
    if carbs_g:
        parts.append(f"{after['carbs_g']:.0f} g carbs (target {carbs_g:.0f})")
    if protein_g:
        parts.append(f"{after['protein_g']:.0f} g protein (target {protein_g:.0f})")
    return {"recipe": scaled, "factor": round(factor, 2), "per_serving": after,
            "note": "Each serving now has " + " and ".join(parts) + "."}


# ── Picking for a day ────────────────────────────────────────────────────────

def favorites(settings) -> list[str]:
    raw = (settings or {}).get("favorite_recipes") or ""
    items = raw if isinstance(raw, (list, tuple, set)) else raw.split(",")
    return [i.strip() for i in items if str(i).strip()]


def toggle_favorite(recipe_id: str, get_setting=None, set_setting=None) -> bool:
    """Star or unstar a recipe for the current athlete. Returns True when it's now starred."""
    if get_setting is None or set_setting is None:
        from db.queries import get_setting, set_setting
    current = favorites({"favorite_recipes": get_setting("favorite_recipes", "")})
    starred = recipe_id not in current
    current = current + [recipe_id] if starred else [r for r in current if r != recipe_id]
    set_setting("favorite_recipes", ",".join(current))
    return starred


def slot_carbs(slot: str, day_carbs_g: float | None) -> float | None:
    share = SLOT_SHARE.get(slot)
    return round(day_carbs_g * share) if share and day_carbs_g else None


def fits(recipe: dict, slot: str, day_carbs_g: float | None) -> bool:
    """Whether one serving is in the right range for this meal of the day. Pocket food always fits."""
    target = slot_carbs(slot, day_carbs_g)
    if not target:
        return True
    carbs = recipe.get("per_serving", {}).get("carbs_g") or 0
    return FIT_RANGE[0] * target <= carbs <= FIT_RANGE[1] * target


def _slots(recipe: dict) -> list[str]:
    return recipe.get("slots") or []


def for_day(day, settings, n: int = 2, targets: dict | None = None, tomorrow: dict | None = None,
            recipes: list[dict] | None = None, library: dict | None = None) -> dict:
    """Up to n recipes for each slot that suit the day. Favourites come first.

    targets is nutrition_day.day_targets() and tomorrow is nutrition_day.day_load() for the next day,
    both read from the database when not given. Before a long day, dinner leans to the most carbs.
    Riders who cook quick meals only see meals done in 30 minutes first.
    Returns {"date", "slots": {slot: [recipe, ...]}, "notes": [...], "day_carbs_g"}."""
    from metrics import nutrition_day
    day = Date.fromisoformat(str(day)) if day else Date.today()
    if targets is None:
        targets = nutrition_day.day_targets(day)
    if tomorrow is None:
        tomorrow = nutrition_day.day_load(day + timedelta(days=1))
    day_carbs = (targets.get("carbs") or {}).get("g") if targets and targets.get("ok") else None
    long_tomorrow = (tomorrow or {}).get("minutes", 0) >= LONG_DAY_MIN
    quick = (settings or {}).get("cooking_time") == "quick"
    stars = set(favorites(settings))

    pool = allowed_recipes(settings, recipes, library)
    notes = []
    if long_tomorrow:
        notes.append("Tomorrow is a long day, so dinner leans toward the most carbs.")
    if quick:
        notes.append(f"Meals done in {QUICK_MIN} minutes come first, since you cook quick meals.")
    out = {}
    for slot in SLOTS:
        options = [r for r in pool if slot in _slots(r)]
        target = slot_carbs(slot, day_carbs)

        def rank(r, slot=slot, target=target):
            slow = quick and r["minutes"] > QUICK_MIN
            if slot == BIG_DAY_DINNER and long_tomorrow:
                closeness = -r["per_serving"]["carbs_g"]
            elif target:
                closeness = abs(r["per_serving"]["carbs_g"] - target) / target
            else:
                closeness = 0
            return (r["id"] not in stars, slow, not fits(r, slot, day_carbs), closeness, r["id"])

        out[slot] = sorted(options, key=rank)[:n]
    return {"date": str(day), "slots": out, "notes": notes, "day_carbs_g": day_carbs}


# ── Cooking ahead ────────────────────────────────────────────────────────────

def _keeps(recipe: dict) -> bool:
    storage = recipe.get("storage") or {}
    return bool(storage.get("freezes")) or (storage.get("fridge_days") or 0) >= 2


def _hours(minutes: float) -> str:
    h = minutes / 60
    if abs(h - round(h)) < 0.13:
        n = round(h)
        return f"{n} hour" + ("s" if n != 1 else "")
    return f"{h:.1f} hours"


def week_loads(start=None, days: int = 7) -> list[dict]:
    """day_load() for each of the coming days, read from the database."""
    from metrics import nutrition_day
    start = Date.fromisoformat(str(start)) if start else Date.today()
    return [nutrition_day.day_load(start + timedelta(days=i)) for i in range(days)]


def prep_ahead(week: list[dict] | None, settings=None, recipes: list[dict] | None = None,
               library: dict | None = None) -> list[dict]:
    """What to cook the day before each long or hard day of the week.

    week is a list of day loads ({"date", "minutes", "avg_if"}), for example from week_loads(). Picks
    pocket food and a carb heavy dinner that keep in the fridge or freezer, from recipes this rider can
    have. Returns [{"date", "cook_on", "recipes", "text"}], empty when nothing is coming up."""
    if not week:
        return []
    pool = [r for r in allowed_recipes(settings, recipes, library) if _keeps(r)]
    stars = set(favorites(settings))
    pocket = sorted((r for r in pool if "pocket" in _slots(r)),
                    key=lambda r: (r["id"] not in stars, -r["per_serving"]["carbs_g"], r["id"]))
    dinner = sorted((r for r in pool if "dinner" in _slots(r)),
                    key=lambda r: (r["id"] not in stars, -r["per_serving"]["carbs_g"], r["id"]))
    out, used = [], set()
    for d in week:
        minutes = d.get("minutes") or 0
        hard = (d.get("avg_if") or 0) >= HARD_IF and minutes >= 45
        if minutes < LONG_DAY_MIN and not hard:
            continue
        day = Date.fromisoformat(str(d["date"]))
        cook_on = day - timedelta(days=1)
        picks = []
        if minutes >= LONG_DAY_MIN and pocket:
            picks.append(next((r for r in pocket if r["id"] not in used), pocket[0]))
        if dinner:
            picks.append(next((r for r in dinner if r["id"] not in used), dinner[0]))
        if not picks:
            continue
        used |= {r["id"] for r in picks}
        what = (f"{day:%A} is {_hours(minutes)}." if minutes >= LONG_DAY_MIN
                else f"{day:%A} has a hard session.")
        names = " and ".join(_lower_first(r["name"]) for r in picks)
        out.append({"date": str(day), "cook_on": str(cook_on), "recipes": picks,
                    "text": f"{what} Make {names} on {cook_on:%A}."})
    return out


def _lower_first(name: str) -> str:
    return name[:1].lower() + name[1:]
