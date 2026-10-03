"""
The pounds or kilograms switch. Weights are stored in kilograms (metrics.units);
this draws the switch, remembers the rider's choice, and gives number inputs
that show and return the chosen unit.
"""
from __future__ import annotations

import streamlit as st

from db.queries import get_setting, set_setting
from metrics.units import UNITS, from_kg, to_kg


def weight_unit(default: str = "kg") -> str:
    """The saved unit. Installs from before the switch existed keep kilograms."""
    saved = get_setting("weight_unit", "")
    return saved if saved in UNITS else default


def _remember(key: str) -> None:
    choice = st.session_state.get(key)
    if choice in UNITS:
        set_setting("weight_unit", choice)


def unit_switch(key: str = "weight_unit_switch", default: str = "kg") -> str:
    """A lb / kg switch that remembers the choice. Returns the unit in use."""
    current = weight_unit(default)
    choice = st.segmented_control("Weight units", list(UNITS), default=current, key=key,
                                  on_change=_remember, args=(key,))
    return choice if choice in UNITS else current


def weight_input(label: str, kg_value: float, *, key: str, unit: str, min_kg: float, max_kg: float,
                 step_lb: float = 1.0, step_kg: float = 0.5, **kwargs) -> float:
    """A number input in the rider's unit. Takes and returns kilograms. The key
    includes the unit, so switching starts a fresh input showing the converted value."""
    step = step_lb if unit == "lb" else step_kg
    value = round(from_kg(kg_value, unit), 1)
    lo, hi = round(from_kg(min_kg, unit), 1), round(from_kg(max_kg, unit), 1)
    shown = st.number_input(f"{label} ({unit})", min_value=lo, max_value=hi,
                            value=min(max(value, lo), hi), step=step, key=f"{key}_{unit}", **kwargs)
    return to_kg(shown, unit)
