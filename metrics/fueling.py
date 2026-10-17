"""
Carbohydrate during a race. The rider picks the number. These are only starting points, from the ride
fueling rules in knowledge/nutrition.md (position stands and a 136 study meta-analysis, mostly trained
men in cycling tests). Intakes above 90 g an hour rest on a small pool, and gut training on one trial.
"""
from __future__ import annotations

FEED_EVERY_MIN = 20       # feeds every 15 to 20 minutes, starting in the first 20 to 30
GLUCOSE_ONLY_MAX = 60     # glucose alone is oxidized at up to about 60 g an hour
TRAINED_GUT_MAX = 90      # above this is experimental

SOURCE = ("Starting point from sports nutrition position stands and a review of 136 studies, mostly "
          "trained men in cycling tests. It is your number, so change it to what works for you.")


def suggest(hours: float) -> dict:
    """The suggested carbs per hour for a race of this length, the range research gives, and why."""
    minutes = hours * 60
    if minutes < 45:
        return {"g_per_h": 0, "range": "none",
                "note": "Under 45 minutes, water is enough. No carbs are needed."}
    if minutes <= 75:
        return {"g_per_h": 0, "range": "0 to 30 g in total",
                "note": "For a hard 45 to 75 minutes, carbs are optional. A small amount or a carb mouth "
                        "rinse is enough."}
    if hours <= 2:
        return {"g_per_h": 60, "range": "30 to 60 g an hour",
                "note": "For 75 minutes to 2 hours, research suggests 30 to 60 g an hour. A race sits at the "
                        "top of that."}
    return {"g_per_h": 60, "range": "60 to 90 g an hour",
            "note": "For races over 2 hours, research suggests 60 to 90 g an hour. Build toward 90 only after "
                    "practicing it on long rides."}


def notes(g_per_h: float) -> list[str]:
    """Things to know about the rate the rider picked."""
    out = []
    if g_per_h > TRAINED_GUT_MAX:
        out.append(f"Above {TRAINED_GUT_MAX} g an hour is experimental. Only go there if you have trained "
                   "your gut on long rides and it sits well.")
    if g_per_h > GLUCOSE_ONLY_MAX:
        out.append(f"Above {GLUCOSE_ONLY_MAX} g an hour, use drinks or gels that mix glucose and fructose. "
                   "Glucose alone is absorbed at up to about 60 g an hour.")
    return out


def feeds(hours: float, g_per_h: float) -> list[tuple[int, float]]:
    """(minute, grams) for each feed before the finish, every FEED_EVERY_MIN minutes from the first."""
    if g_per_h <= 0:
        return []
    each = g_per_h * FEED_EVERY_MIN / 60
    return [(m, each) for m in range(FEED_EVERY_MIN, int(hours * 60), FEED_EVERY_MIN)]
