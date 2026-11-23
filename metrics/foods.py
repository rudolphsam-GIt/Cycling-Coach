"""
The food library (knowledge/foods.json) and what it can suggest for a rider.

allowed() is a firm safety rule. A food whose contains or may_contain lists anything the rider avoids is
never shown, and a food without checked allergen data is never shown to anyone with an avoid list.
Everything else here (amounts, combinations) is a suggestion the rider can change.

Nutrient values are per 100 g from USDA FoodData Central, with the FDC ID on each food.
"""
from __future__ import annotations

import itertools
import json
import os
from functools import lru_cache

from metrics import diet as diet_mod

LIBRARY_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "knowledge", "foods.json")

PHASES = ("before", "during", "after", "everyday")
TOLERANCE = 0.10              # a combination must land within 10 percent of each target
LOW_FIBRE_G = 2.0             # per serving, for gut friendly picks before and during rides
LOW_FAT_G = 5.0
MAX_PIECES = 4               # at most 4 bananas, gels or slices of one food
MAX_SERVINGS = 2.5           # and at most 2.5 servings (cups, tbsp) of anything weighed
MIN_SHARE = 0.15             # each food in a mix gives at least 15 percent of a target, so no 10 g garnish

# Shown once to vegetarian and vegan riders. From knowledge/nutrition.md, vegetarian and vegan riders.
PLANT_NOTE = {
    "text": ("Protein is easy to reach from eggs, dairy, soy and legumes. Vegans may need a little more "
             "total protein, or soy or pea protein, to get the same amount of leucine, the amino acid that "
             "switches on muscle repair. Ask your doctor about B12, iron and omega 3, which plant diets "
             "can run low on."),
    "evidence": ("Evidence: Moderate for performance and protein (8 studies comparing diets, and 9 trials "
                 "with 266 people for soy versus animal protein, mostly resistance training). Moderate for "
                 "B12 and iron (18 and 30 studies, observational). Expert consensus for omega 3."),
    "source": "nutrition.md, vegetarian and vegan riders (Melina et al., 2016; Messina et al., 2018).",
}


@lru_cache(maxsize=4)
def _read(path: str, mtime: float) -> tuple:
    with open(path, encoding="utf-8") as f:
        return tuple(json.load(f).get("foods", []))


def load_library(path: str | None = None) -> list[dict]:
    path = path or LIBRARY_PATH
    try:
        return list(_read(path, os.path.getmtime(path)))
    except (OSError, ValueError):
        return []


def by_id(library: list[dict] | None = None) -> dict:
    return {f["id"]: f for f in (library if library is not None else load_library())}


def per_serving(item: dict, servings: float = 1.0) -> dict:
    """Nutrients for this many servings. A value FDC lacks counts as 0 here."""
    grams = item["serving"]["g"] * servings
    return {k: (v or 0) * grams / 100 for k, v in item.get("per_100g", {}).items()}


def is_low_fibre(item: dict) -> bool:
    fibre = item.get("per_100g", {}).get("fibre_g")
    return fibre is not None and fibre * item["serving"]["g"] / 100 <= LOW_FIBRE_G


def gut_friendly(item: dict) -> bool:
    """Low in fibre and fat per serving, so it sits easily before and during rides."""
    return is_low_fibre(item) and per_serving(item)["fat_g"] <= LOW_FAT_G


def _rider(settings) -> dict:
    s = settings or {}
    return {"diet": s.get("diet") or "none",
            "avoid": set(diet_mod.parse_avoid(s.get("avoid_foods"))),
            "gut": bool(s.get("gut_sensitive")) and s.get("gut_sensitive") not in ("0", 0)}


def blocked_by(item: dict, settings) -> str | None:
    """Why a food is hidden from this rider, or None when it's allowed."""
    r = _rider(settings)
    if r["diet"] != "none" and r["diet"] not in item.get("diets", []):
        return f"not {r['diet']}"
    contains = set(item.get("contains") or [])
    marked = contains | set(item.get("may_contain") or [])
    # A second check on the data, so a mistagged food still can't reach the wrong diet.
    if r["diet"] == "vegan" and contains & {"eggs", "dairy"}:
        return "contains eggs or dairy"
    if r["diet"] in ("vegan", "vegetarian") and "fish_shellfish" in contains:
        return "contains fish"
    if not r["avoid"]:
        return None
    if not item.get("allergens_checked"):
        return "allergens not checked"
    hit = r["avoid"] & marked
    if hit:
        return "contains or may contain " + ", ".join(sorted(hit))
    if "caffeine" in r["avoid"] and (item.get("per_100g", {}).get("caffeine_mg") or 0) > 0:
        return "contains caffeine"
    return None


def has_caffeine(item: dict) -> bool:
    return "caffeine" in (item.get("contains") or []) or (item.get("per_100g", {}).get("caffeine_mg") or 0) > 0


def allowed(item: dict, settings) -> bool:
    """True when the food fits the rider's diet and avoid list. A firm safety rule."""
    return blocked_by(item, settings) is None


def _options(item: dict) -> list[float]:
    if item["serving"]["unit"] == "piece":
        return [float(k) for k in range(1, MAX_PIECES + 1)]
    return [k / 2 for k in range(1, int(MAX_SERVINGS * 2) + 1)]


def _grams(item: dict, count: float) -> float:
    """Gram or ml amounts round to 5, pieces stay as weighed."""
    g = item["serving"]["g"] * count
    return g if item["serving"]["unit"] == "piece" or g < 10 else round(g / 5) * 5


def _part(item: dict, count: float) -> dict:
    grams = _grams(item, count)
    totals = {k: (v or 0) * grams / 100 for k, v in item.get("per_100g", {}).items()}
    unit = item["serving"]["unit"]
    if unit == "piece":
        text = f"{count:g} × {item['name'].lower()}"
    else:
        text = f"{grams:g} {'ml' if unit == 'ml' else 'g'} {item['name'].lower()}"
    return {"id": item["id"], "name": item["name"], "count": count, "grams": grams, "text": text,
            "carbs_g": totals.get("carbs_g", 0), "protein_g": totals.get("protein_g", 0),
            "kcal": totals.get("kcal", 0)}


def _error(value: float, target: float) -> float:
    return abs(value - target) / target if target else 0.0


def _pulls_weight(part: dict, carbs: float, protein: float) -> bool:
    return ((carbs and part["carbs_g"] >= MIN_SHARE * carbs)
            or (protein and part["protein_g"] >= MIN_SHARE * protein))


def suggest(phase: str, carbs_g: float | None, protein_g: float | None, settings, n: int = 3,
            library: list[dict] | None = None, caffeine: bool = False) -> dict:
    """A few food combinations that reach the targets, each within 10 percent.

    Caffeinated foods are left out unless caffeine is True, so caffeine is never repeated hour after
    hour. caffeine_option() offers it on its own, within the rider's limit.

    Returns {"ok", "combos", "message"}. Each combo has items (with amounts), carbs_g, protein_g,
    kcal and a text like "2 × banana plus 1 × fig bar = 75 g carbs". When nothing fits, ok is False and
    message says why in plain words."""
    library = load_library() if library is None else library
    carbs, protein = max(carbs_g or 0, 0), max(protein_g or 0, 0)
    if not library:
        return {"ok": False, "combos": [], "message": "The food library is empty, so there are no ideas to show yet."}
    if not (carbs or protein):
        return {"ok": False, "combos": [], "message": "There is no carb or protein target to build ideas for."}
    if phase not in PHASES:
        raise ValueError(f"phase must be one of {PHASES}")

    r = _rider(settings)
    pool = [f for f in library if phase in f.get("phases", []) and allowed(f, settings)
            and (caffeine or not has_caffeine(f))]
    if not pool:
        message = "No foods in the library fit your diet and avoid list for this part of the day."
        if r["avoid"]:
            message += (" With an avoid list, foods without checked allergen data stay hidden to keep you "
                        "safe, so the choice is small for now.")
        return {"ok": False, "combos": [], "message": message}
    if r["gut"] and phase in ("before", "during"):
        gentle = [f for f in pool if gut_friendly(f)]
        pool = gentle or pool

    tried = []
    for size in (1, 2):
        for combo in itertools.combinations(range(len(pool)), size):
            for counts in itertools.product(*(_options(pool[i]) for i in combo)):
                parts = [_part(pool[i], c) for i, c in zip(combo, counts)]
                c_total = sum(p["carbs_g"] for p in parts)
                p_total = sum(p["protein_g"] for p in parts)
                err_c, err_p = _error(c_total, carbs), _error(p_total, protein)
                if err_c > TOLERANCE or err_p > TOLERANCE:
                    continue
                if size > 1 and not all(_pulls_weight(p, carbs, protein) for p in parts):
                    continue
                tried.append((err_c + err_p, sum(counts), parts, c_total, p_total))
    # Close enough counts as equal (5 percent steps), then fewer servings, then by name so it's stable.
    tried.sort(key=lambda t: (round(t[0] / 0.05), t[1], [p["id"] for p in t[2]]))

    picked, used = [], set()
    for strict in (True, False):
        for score, _, parts, c_total, p_total in tried:
            ids = frozenset(p["id"] for p in parts)
            if len(picked) >= n:
                break
            if any(ids == frozenset(p["id"] for p in c["items"]) for c in picked):
                continue
            if strict and ids & used:
                continue
            used |= ids
            picked.append(_combo(parts, c_total, p_total, carbs, protein))
    if not picked:
        want = " and ".join(x for x in (f"{carbs:.0f} g carbs" if carbs else "",
                                         f"{protein:.0f} g protein" if protein else "") if x)
        return {"ok": False, "combos": [],
                "message": f"No mix of one or two foods that fit your settings reaches {want} within 10 percent."}
    return {"ok": True, "combos": picked, "message": ""}


def _combo(parts, c_total, p_total, carbs, protein) -> dict:
    sums = []
    if carbs:
        sums.append(f"{c_total:.0f} g carbs")
    if protein:
        sums.append(f"{p_total:.0f} g protein")
    return {"items": parts, "carbs_g": round(c_total, 1), "protein_g": round(p_total, 1),
            "kcal": round(sum(p["kcal"] for p in parts)),
            "text": " plus ".join(p["text"] for p in parts) + " = " + " and ".join(sums)}


def caffeine_option(settings, weight_kg: float | None, key_session: bool,
                    library: list[dict] | None = None) -> dict:
    """At most one caffeinated food for the ride, within 3 mg/kg, and never over 6 mg/kg (a firm limit).

    Returns {"ok", "message", plus item, servings, mg, mg_per_kg, start_mg, max_mg and evidence when ok}.
    Nothing is offered to riders who avoid caffeine, on rides that aren't key sessions or races, or when
    the rider's weight is unknown, since the limit depends on it."""
    from metrics import fueling
    if "caffeine" in _rider(settings)["avoid"]:
        return {"ok": False, "message": "You avoid caffeine, so none is suggested."}
    if not key_session:
        return {"ok": False, "message": "Caffeine is kept for races and hard sessions, so none is suggested "
                                        "for this ride."}
    limits = fueling.caffeine_limits(weight_kg)
    if not limits:
        return {"ok": False, "message": "Add your weight to see a caffeine amount, since the safe amount "
                                        "depends on it."}
    library = load_library() if library is None else library
    picks = []
    for f in library:
        if not (has_caffeine(f) and allowed(f, settings) and {"before", "during"} & set(f.get("phases", []))):
            continue
        mg = (f.get("per_100g", {}).get("caffeine_mg") or 0) * f["serving"]["g"] / 100
        if 0 < mg <= limits["start_mg"]:
            picks.append((-(per_serving(f)["carbs_g"]), f["id"], f, mg))
    if not picks:
        return {"ok": False, "message": "No caffeinated food in the library fits your settings and your "
                                        f"limit of {limits['start_mg']} mg."}
    _, _, item, mg = sorted(picks)[0]             # the one that also brings the most carbs
    assert mg <= limits["max_mg"]                 # the firm ceiling, checked again
    return {"ok": True, "item": item, "servings": 1, "mg": round(mg), "mg_per_kg": round(mg / weight_kg, 1),
            "start_mg": limits["start_mg"], "max_mg": limits["max_mg"], "evidence": limits["evidence"],
            "message": (f"Optional: 1 × {item['name'].lower()} ({round(mg)} mg caffeine) about 60 minutes before "
                        f"the hardest part. Keep the whole ride under {limits['start_mg']} mg (3 mg/kg) to start, "
                        f"and never over {limits['max_mg']} mg (6 mg/kg). Skip it within about 6 hours of "
                        "bedtime, and try it in training before a race.")}


def plant_note(settings) -> dict | None:
    """The vegetarian and vegan note, for riders on those diets."""
    return PLANT_NOTE if (settings or {}).get("diet") in ("vegetarian", "vegan") else None
