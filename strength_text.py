"""
How one strength exercise reads on screen, in the PDF and to the coach.

An exercise is a dict from exercises_json: name, sets, reps and intensity always, and when
the coach gave them, load (what to put on the bar, in the athlete's unit or as a way to find
it), notes and progression. A logged session also carries weight_kg, what was lifted.
Older sessions have no load, so every part is optional except the name.
"""
from __future__ import annotations

from metrics.units import fmt_weight


def _clean(value) -> str:
    return str(value).strip() if value not in (None, "") else ""


def sets_reps(ex: dict) -> str:
    """For example 3 × 10 to 12, or just the reps when sets are missing."""
    sets, reps = _clean(ex.get("sets")), _clean(ex.get("reps"))
    if sets and reps:
        return f"{sets} × {reps}"
    return reps or (f"{sets} sets" if sets else "")


def used(ex: dict, unit: str) -> str:
    """What was lifted, for a logged session, for example "used 135 lb"."""
    try:
        kg = float(ex.get("weight_kg") or 0)
    except (TypeError, ValueError):
        return ""
    return f"used {fmt_weight(kg, unit)}" if kg > 0 else ""


def line(ex: dict, unit: str = "kg", *, effort: bool = True) -> str:
    """The prescription on one line: name, sets and reps, load, effort.
    For example "Back squat · 3 × 10 to 12 · 60 kg · RPE 7". `effort` off leaves out the
    intensity, for tight spaces like the calendar tooltip."""
    parts = [_clean(ex.get("name")) or "Exercise", sets_reps(ex), _clean(ex.get("load")), used(ex, unit)]
    if effort:
        parts.append(_clean(ex.get("intensity")))
    return " · ".join(p for p in parts if p)


def short(ex: dict) -> str:
    """Name, sets and reps and load only, for example "Back squat 3 × 10 to 12, 60 kg"."""
    head = " ".join(p for p in (_clean(ex.get("name")) or "Exercise", sets_reps(ex)) if p)
    load = _clean(ex.get("load"))
    return f"{head}, {load}" if load else head


def note(ex: dict) -> str:
    """The coach's notes and how to progress, as one plain sentence or two, or ""."""
    bits = [b[0].upper() + b[1:] for b in (_clean(ex.get("notes")), _clean(ex.get("progression"))) if b]
    return " ".join(b if b.endswith((".", "!", "?")) else b + "." for b in bits)


def bodyweight_only(ex: dict) -> bool:
    """True when nothing is added to bodyweight, so there is no weight to log. "bodyweight plus
    45 lb" has a weight."""
    text = f"{_clean(ex.get('intensity'))} {_clean(ex.get('load'))}".lower()
    return "bodyweight" in text and not any(ch.isdigit() for ch in _clean(ex.get("load")))


def same_session(a: dict, b: dict) -> bool:
    """True when two proposed sessions have the same name and the same exercises, so a card
    can show the prescription once for all of them."""
    return a.get("name") == b.get("name") and a.get("exercises") == b.get("exercises")
