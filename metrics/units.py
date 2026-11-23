"""Body and lifting weights are stored in kilograms. These convert to and from
pounds for display and for what the rider types in."""
from __future__ import annotations

import math

KG_PER_LB = 0.45359237
UNITS = ("lb", "kg")


def to_kg(value: float, unit: str) -> float:
    """What the rider typed, in kilograms (two decimals, so 154 lb round trips)."""
    return round(float(value) * KG_PER_LB, 2) if unit == "lb" else float(value)


def from_kg(kg: float, unit: str) -> float:
    return float(kg) / KG_PER_LB if unit == "lb" else float(kg)


def fmt_weight(kg: float, unit: str) -> str:
    """For example 154 lb or 70 kg."""
    value = from_kg(kg, unit)
    return f"{value:.0f} lb" if unit == "lb" else f"{value:g} kg"


# ── Distance, climbing and speed ──────────────────────────────────────────────
# Distances are stored in meters (rides) or kilometers (races). A rider who chooses
# miles also sees climbing in feet and speed in mph.

KM_PER_MI = 1.609344
FT_PER_M = 3.280839895
DISTANCE_UNITS = ("mi", "km")


def dist_from_km(km: float, unit: str) -> float:
    return float(km) / KM_PER_MI if unit == "mi" else float(km)


def km_from_dist(value: float, unit: str) -> float:
    return float(value) * KM_PER_MI if unit == "mi" else float(value)


def climb_from_m(meters: float, unit: str) -> float:
    return float(meters) * FT_PER_M if unit == "mi" else float(meters)


def m_from_climb(value: float, unit: str) -> float:
    return float(value) / FT_PER_M if unit == "mi" else float(value)


def climb_unit(unit: str) -> str:
    return "ft" if unit == "mi" else "m"


def speed_unit(unit: str) -> str:
    return "mph" if unit == "mi" else "km/h"


def speed_from_kph(kph: float, unit: str) -> float:
    return float(kph) / KM_PER_MI if unit == "mi" else float(kph)


def fmt_distance(meters: float, unit: str) -> str:
    """For example 21.3 mi or 34.2 km. Empty when there is no distance."""
    if not meters:
        return ""
    return f"{dist_from_km(float(meters) / 1000, unit):.1f} {unit}"


def fmt_climb(meters: float, unit: str) -> str:
    """For example 575 ft or 175 m. Empty when there is no climbing."""
    if not meters:
        return ""
    return f"{climb_from_m(meters, unit):,.0f} {climb_unit(unit)}"


def num(v) -> float | None:
    """A finite float, or None when the value is missing, blank, NaN or not a number."""
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


# ── Kitchen measures ──────────────────────────────────────────────────────────
# Recipes are stored in grams (ml for drinks, or a count for eggs and bananas). These turn an amount into
# cups and spoons, with the grams always shown alongside. US measures: 1 cup is 240 ml, 1 tbsp is 15 ml,
# 1 tsp is 5 ml. How many grams fill a cup comes from the food's own serving label ("1/2 cup dry", 40 g).

ML_PER = {"cup": 240.0, "tbsp": 15.0, "tsp": 5.0}
_FRACTIONS = {0.25: "1/4", 1 / 3: "1/3", 0.5: "1/2", 2 / 3: "2/3", 0.75: "3/4"}


def _label_measure(label: str) -> tuple[float, str] | None:
    """(amount, unit) from a serving label like "1/2 cup dry", "2 tbsp" or "1 cup halves"."""
    words = (label or "").lower().replace("tablespoon", "tbsp").replace("teaspoon", "tsp").split()
    if len(words) < 2 or words[1] not in ML_PER:
        return None
    num = words[0]
    try:
        if "/" in num:
            top, bottom = num.split("/")
            value = float(top) / float(bottom)
        else:
            value = float(num)
    except (ValueError, ZeroDivisionError):
        return None
    return value, words[1]


def grams_per_ml(food: dict) -> float | None:
    """Density from the serving label (milk is 244 g a cup, so about 1.02 g per ml)."""
    measure = _label_measure(food.get("serving", {}).get("label", ""))
    if not measure:
        return None
    value, unit = measure
    return food["serving"]["g"] / (value * ML_PER[unit])


def _nice(value: float, unit: str) -> str | None:
    """Nearest friendly amount of a cup (quarters and thirds) or spoon (halves), or None when that's
    off by more than 15 percent."""
    whole = int(value)
    rest = value - whole
    steps = _FRACTIONS if unit == "cup" else {0.5: "1/2"}
    options = [(0.0, "")] + list(steps.items()) + [(1.0, "")]
    frac, text = min(options, key=lambda o: abs(o[0] - rest))
    if frac == 1.0:
        whole, text = whole + 1, ""
    shown = whole + (frac if frac < 1 else 0)
    if shown <= 0 or abs(shown - value) > 0.15 * value:
        return None
    number = f"{whole} {text}".strip() if whole else text
    plural = "s" if unit == "cup" and shown > 1 else ""
    return f"{number} {unit}{plural}"


def kitchen_measure(ml: float) -> str | None:
    """A volume in the biggest measure that reads well: cups from 1/4 cup, then tbsp, then tsp."""
    if not ml or ml <= 0:
        return None
    for unit in ("cup", "tbsp", "tsp"):
        value = ml / ML_PER[unit]
        if unit == "cup" and value < 0.25:
            continue
        if unit == "tbsp" and value < 1:
            continue
        text = _nice(value, unit)
        if text:
            return text
    return None


def kitchen_parts(food: dict, grams: float, ml: float | None = None,
                  count: float | None = None) -> tuple[str, str]:
    """(amount, note) for an ingredient. The note always has the grams unless the amount is grams."""
    if count:
        label = food["serving"].get("label", "")
        size = label[2:] if label.startswith("1 ") else food["name"].lower()
        return f"{count:g} × {size}", f"{grams:.0f} g"
    if ml:
        cups = kitchen_measure(ml)
        return f"{ml:.0f} ml", (f"about {cups}, " if cups else "") + f"{grams:.0f} g"
    density = grams_per_ml(food)
    cups = kitchen_measure(grams / density) if density else None
    amount = f"{grams:.0f} g" if grams >= 10 else f"{grams:g} g"
    return amount, (f"about {cups}" if cups else "")


def kitchen_text(food: dict, grams: float, ml: float | None = None, count: float | None = None) -> str:
    """How an ingredient amount reads in a recipe, always with the grams. For example "80 g (about
    1 cup)", "200 ml (about 3/4 cup, 203 g)" or "2 × large egg (100 g)"."""
    amount, note = kitchen_parts(food, grams, ml, count)
    return f"{amount} ({note})" if note else amount
