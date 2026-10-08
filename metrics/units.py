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
