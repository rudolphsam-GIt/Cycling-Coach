"""
How a rider eats: the "How you eat" answers, stored as athlete_settings keys.

Shared by onboarding, Settings, the Add athlete form and the intake form import, so every place asks
the same questions with the same choices. The food library (metrics.foods) filters on these. Only
diet, avoid_foods and gut_sensitive filter food. diet_notes goes to the coach only.
"""
from __future__ import annotations

DIETS = {"No restrictions": "none", "Vegetarian": "vegetarian", "Vegan": "vegan",
         "Pescatarian": "pescatarian"}
AVOID = {"Gluten": "gluten", "Dairy": "dairy", "Eggs": "eggs", "Peanuts": "peanuts",
         "Tree nuts": "tree_nuts", "Soy": "soy", "Fish or shellfish": "fish_shellfish",
         "Sesame": "sesame", "Caffeine": "caffeine"}
RIDE_TIMES = {"Early morning": "early", "Midday": "midday", "Evening": "evening"}
COOKING = {"Quick meals only": "quick", "Normal cooking": "normal", "Happy to batch cook": "batch"}
ENERGY_SEX = {"Female": "female", "Male": "male", "Prefer not to say": "prefer_not"}

REFERRAL_QUESTION = ("Do you have diabetes, kidney disease, a history of disordered eating, take blood "
                     "pressure medication, are pregnant, or have a gut disease?")
REFERRAL_QUESTION_THEY = ("Do they have diabetes, kidney disease, a history of disordered eating, take "
                          "blood pressure medication, are they pregnant, or have a gut disease?")
# From the referral rule in knowledge/nutrition.md (Rules for the coach). A firm safety rule.
REFERRAL_MESSAGE = ("Because of your health answer, please check with a doctor or a registered sports "
                    "dietitian before changing how much carbohydrate, protein, salt or supplements you "
                    "take. The targets here are general guidance, not a plan for your condition.")
REFERRAL_MESSAGE_THEY = ("Because of their health answer, they should check with a doctor or a registered "
                         "sports dietitian before changing how much carbohydrate, protein, salt or "
                         "supplements they take. The targets are general guidance, not a plan for their "
                         "condition.")

HEIGHT_CM_MIN, HEIGHT_CM_MAX = 120, 230

KEYS = ("diet", "avoid_foods", "gut_sensitive", "nutrition_referral", "usual_ride_time", "cooking_time",
        "diet_notes", "height_cm", "energy_sex")


def _label_for(options: dict, value) -> str | None:
    return next((k for k, v in options.items() if v == value), None)


def diet_label(value) -> str | None:
    return _label_for(DIETS, value)


def ride_time_label(value) -> str | None:
    return _label_for(RIDE_TIMES, value)


def cooking_label(value) -> str | None:
    return _label_for(COOKING, value)


def energy_sex_label(value) -> str | None:
    return _label_for(ENERGY_SEX, value)


def avoid_labels(values) -> list[str]:
    return [k for k, v in AVOID.items() if v in (values or [])]


def parse_avoid(raw) -> list[str]:
    """The stored comma list (or a list) as known avoid keys, in the app's order."""
    items = raw if isinstance(raw, (list, tuple, set)) else (raw or "").split(",")
    picked = {str(i).strip() for i in items}
    return [v for v in AVOID.values() if v in picked]


def _flag(raw) -> bool | None:
    """Stored "1" or "0". Unanswered is None, so a skipped health question is not read as no."""
    if raw in (None, ""):
        return None
    return str(raw) in ("1", "true", "True", "yes", "Yes")


def _height(raw) -> float | None:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if HEIGHT_CM_MIN <= v <= HEIGHT_CM_MAX else None


def from_settings(get) -> dict:
    """The rider's answers from a get_setting style function, cleaned up."""
    diet = get("diet", "") or "none"
    return {
        "diet": diet if diet in DIETS.values() else "none",
        "avoid_foods": parse_avoid(get("avoid_foods", "")),
        "gut_sensitive": _flag(get("gut_sensitive", "")),
        "nutrition_referral": _flag(get("nutrition_referral", "")),
        "usual_ride_time": get("usual_ride_time", "") or None,
        "cooking_time": get("cooking_time", "") or None,
        "diet_notes": get("diet_notes", "") or "",
        "height_cm": _height(get("height_cm", "")),
        "energy_sex": get("energy_sex", "") or None,
    }


def load() -> dict:
    from db.queries import get_setting
    return from_settings(get_setting)


def _stored(key: str, value) -> str:
    if key == "avoid_foods":
        return ",".join(parse_avoid(value))
    if key in ("gut_sensitive", "nutrition_referral"):
        return "" if value is None else ("1" if value else "0")
    if key == "height_cm":
        h = _height(value)
        return f"{h:.1f}" if h else ""
    if key == "diet":
        return value if value in DIETS.values() else "none"
    if key == "usual_ride_time":
        return value if value in RIDE_TIMES.values() else ""
    if key == "cooking_time":
        return value if value in COOKING.values() else ""
    if key == "energy_sex":
        return value if value in ENERGY_SEX.values() else ""
    return (value or "").strip()


def save(answers: dict, set_setting=None) -> None:
    """Write the answers given (any of KEYS) to the current athlete's database."""
    if set_setting is None:
        from db.queries import set_setting
    for key in KEYS:
        if key in answers:
            set_setting(key, _stored(key, answers[key]))


# ── Height in the rider's units ──────────────────────────────────────────────
CM_PER_IN = 2.54


def cm_from_ft_in(feet, inches) -> float | None:
    if not feet and not inches:
        return None
    return round(((feet or 0) * 12 + (inches or 0)) * CM_PER_IN, 1)


def ft_in_from_cm(cm) -> tuple[int, int] | None:
    if not cm:
        return None
    total = round(float(cm) / CM_PER_IN)
    return total // 12, total % 12


def cm_from_height(value, unit: str) -> float | None:
    """A height typed in the rider's system: inches when they use pounds, else cm."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return round(v * CM_PER_IN, 1) if unit == "lb" else v

