"""
Ski days alongside the bike: which planned workouts are ski days, which recorded activities are
skiing, and which threshold heart rate scores them.

A planned ski day has no power steps. Its TSS is an hrTSS target, scored against the ski
threshold heart rate, because heart rate thresholds don't carry over between sports (see
knowledge/cross_training.md). Ski days go to TrainingPeaks as XC ski workouts and are left
out of the bike only exports (Zwift, Garmin, .fit, intervals.icu).
"""
from __future__ import annotations

NORDIC = "Nordic Ski"
BACKCOUNTRY = "Backcountry Ski"
SKI_TYPES = (NORDIC, BACKCOUNTRY)             # planned workout types

SKI_LTHR_SETTING = "ski_lthr"

# TrainingPeaks' XC ski workout type. Taken from third party TrainingPeaks tools; TrainingPeaks
# has no ski touring type, so backcountry days go as XC ski too.
TP_XC_SKI = 11


def is_ski_workout(workout: dict) -> bool:
    return (workout or {}).get("workout_type") in SKI_TYPES


def ski_kind(sport_type: str | None) -> str | None:
    """"nordic", "backcountry" or "downhill" for a recorded activity's sport type (Garmin type
    keys, Strava names, .fit sport and sub sport), or None when it isn't skiing."""
    s = (sport_type or "").lower().replace(" ", "_").replace("-", "_")
    if "backcountry" in s or "ski_touring" in s or "skimo" in s or "ski_mountaineering" in s:
        return "backcountry"
    if "nordic" in s or "cross_country_ski" in s or "skate_ski" in s or "xc_ski" in s or s == "nordicski":
        return "nordic"
    if "alpine" in s or "downhill" in s or "resort_ski" in s or "snowboard" in s or s == "alpineski":
        return "downhill"
    return None


def threshold_for(sport_type: str | None, lthr: float, ski_lthr: float | None) -> float:
    """The threshold heart rate to score an activity with: the ski threshold for skiing when one
    is set, otherwise the cycling one."""
    if ski_lthr and ski_kind(sport_type):
        return float(ski_lthr)
    return lthr


def ski_lthr() -> float:
    """The athlete's ski threshold heart rate, or 0 when it isn't set."""
    from db.queries import get_setting
    try:
        return float(get_setting(SKI_LTHR_SETTING, 0) or 0)
    except (TypeError, ValueError):
        return 0.0
