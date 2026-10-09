"""Taper load for the run in to a race."""
from __future__ import annotations

from datetime import date, timedelta


def daily_taper_tss(days_to_race: int, ctl: float) -> float:
    """Planned TSS for one day of the taper. CTL is already average TSS per day, so a day at
    100% of CTL holds fitness and the later steps shed fatigue."""
    if days_to_race > 21:
        return ctl * 1.0
    if days_to_race > 14:
        return ctl * 0.8
    if days_to_race > 7:
        return ctl * 0.6
    if days_to_race > 2:
        return ctl * 0.4
    if days_to_race == 1:
        return 30.0     # opener
    return 0.0


def taper_schedule(today: date, race_date: date, ctl: float) -> dict[str, float]:
    """{iso date: planned TSS} for every day from tomorrow up to race day."""
    out = {}
    for i in range((race_date - today).days):
        d = today + timedelta(days=i + 1)
        out[d.isoformat()] = max(0.0, daily_taper_tss((race_date - d).days, ctl))
    return out


def taper_workout(day: str, race_date: date, tss: float) -> tuple[str, str] | None:
    """(workout type, name) for a taper day, or None for a rest day."""
    if tss < 5:
        return None
    days_to_race = (race_date - date.fromisoformat(day)).days
    if days_to_race > 14:
        return "Endurance", "Taper Endurance"
    if days_to_race > 7:
        return "Tempo", "Taper Tempo"
    if days_to_race > 2:
        return "Recovery", "Taper Recovery"
    return "Recovery", "Race Eve Opener"
