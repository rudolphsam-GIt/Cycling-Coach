"""Body and lifting weights are stored in kilograms. These convert to and from
pounds for display and for what the rider types in."""
from __future__ import annotations

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
