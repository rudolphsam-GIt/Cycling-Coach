"""
The pounds or kilograms switch. Weights are stored in kilograms (metrics.units);
this draws the switch, remembers the rider's choice, and gives number inputs
that show and return the chosen unit.
"""
from __future__ import annotations

import streamlit as st

from db.queries import get_setting, set_setting
from metrics.units import DISTANCE_UNITS, UNITS, from_kg, to_kg


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


# ── Distance ──────────────────────────────────────────────────────────────────

def distance_unit(default: str = "km") -> str:
    """The saved distance unit (mi or km). Installs from before the switch keep km."""
    saved = get_setting("distance_unit", "")
    return saved if saved in DISTANCE_UNITS else default


def _remember_distance(key: str) -> None:
    choice = st.session_state.get(key)
    if choice in DISTANCE_UNITS:
        set_setting("distance_unit", choice)


def distance_switch(key: str = "distance_unit_switch", default: str = "km", label: str = "Distance units",
                    collapsed: bool = False) -> str:
    """A mi / km switch that remembers the choice. Miles also means feet and mph.
    Returns the unit in use."""
    current = distance_unit(default)
    choice = st.segmented_control(label, list(DISTANCE_UNITS), default=current, key=key,
                                  on_change=_remember_distance, args=(key,),
                                  label_visibility="collapsed" if collapsed else "visible")
    return choice if choice in DISTANCE_UNITS else current


def distance_input(label: str, km_value: float, *, key: str, unit: str, min_km: float, max_km: float,
                   step_km: float = 5.0, step_mi: float = 5.0, **kwargs) -> float:
    """A distance input in the rider's unit. Takes and returns kilometers."""
    from metrics.units import dist_from_km, km_from_dist
    step = step_mi if unit == "mi" else step_km
    lo, hi = round(dist_from_km(min_km, unit), 1), round(dist_from_km(max_km, unit), 1)
    value = min(max(round(dist_from_km(km_value, unit), 1), lo), hi)
    shown = st.number_input(f"{label} ({unit})", min_value=lo, max_value=hi, value=value, step=step,
                            key=f"{key}_{unit}", **kwargs)
    return km_from_dist(shown, unit)


def climb_input(label: str, meters: float, *, key: str, unit: str, min_m: float, max_m: float,
                step_m: float = 50.0, step_ft: float = 100.0, **kwargs) -> float:
    """A climbing input in meters or feet. Takes and returns meters."""
    from metrics.units import climb_from_m, climb_unit, m_from_climb
    step = step_ft if unit == "mi" else step_m
    lo, hi = round(climb_from_m(min_m, unit)), round(climb_from_m(max_m, unit))
    value = min(max(round(climb_from_m(meters, unit)), lo), hi)
    shown = st.number_input(f"{label} ({climb_unit(unit)})", min_value=lo, max_value=hi, value=value,
                            step=int(step), key=f"{key}_{unit}", **kwargs)
    return m_from_climb(shown, unit)
