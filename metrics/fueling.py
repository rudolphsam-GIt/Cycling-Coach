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


# Training rides. The bands are the nutrition.md ride fueling rules (Thomas et al., 2016; Jeukendrup,
# 2014). Where a ride sits inside a band follows its intensity, since easy riding burns less carbohydrate.
# Those starting points are this app's choice and the rider can change them.
HARD_IF = 0.85            # threshold, VO2 and race efforts
EASY_IF = 0.65            # recovery and very easy endurance, as in nutrition_day.EASY_IF
NO_CARBS_MIN = 45
SHORT_MAX_MIN = 75
BAND_1_MAX_MIN = 150      # nutrition.md gives 30 to 60 g an hour for 1 to 2.5 hours

CARB_EVIDENCE = ("nutrition.md, carbohydrate during rides. Evidence: Strong. Pool: 136 studies, mostly "
                 "trained men in cycling time trials and time to exhaustion tests (Ramos-Campo et al., 2024), "
                 "with the bands from the 2016 position stand (Thomas et al., 2016). Where you start inside a "
                 "band is set by this app from the ride's intensity. It is your number, so change it.")


def _effort(avg_if: float | None) -> str:
    if avg_if is None:
        return "unknown"
    if avg_if >= HARD_IF:
        return "hard"
    return "easy" if avg_if < EASY_IF else "steady"


def during(minutes: float, avg_if: float | None = None) -> dict:
    """Carbs per hour for a training ride, from its length and intensity (IF), with the band and why.

    Returns g_per_h (a starting point), low and high (the research band in g an hour), total_g for the
    whole ride, optional_g (a small optional amount for short hard rides), why, notes and evidence."""
    minutes = max(minutes or 0, 0)
    hours = minutes / 60
    effort = _effort(avg_if)
    out = {"minutes": minutes, "effort": effort, "optional_g": 0, "evidence": CARB_EVIDENCE}
    if minutes < NO_CARBS_MIN:
        out.update(g_per_h=0, low=0, high=0, range="none",
                   why="Under 45 minutes, the carbs already stored in your muscles cover the ride. Water is enough.")
    elif minutes <= SHORT_MAX_MIN:
        if effort == "hard":
            out.update(g_per_h=0, low=0, high=0, range="0 to 30 g in total", optional_g=30,
                       why="For a hard ride under 75 minutes, carbs are optional. Up to about 30 g, or just "
                           "rinsing your mouth with a sports drink, can help you hold the effort.")
        else:
            out.update(g_per_h=0, low=0, high=0, range="none",
                       why="For an easy or steady ride under 75 minutes, your stores cover it. Eat well after.")
    elif minutes <= BAND_1_MAX_MIN:
        start = {"easy": 30, "hard": 60}.get(effort, 45)
        out.update(g_per_h=start, low=30, high=60, range="30 to 60 g an hour",
                   why="Rides of 75 minutes to 2.5 hours go better with 30 to 60 g of carbs an hour. "
                       + {"easy": "An easy ride burns less, so start at the low end.",
                          "hard": "A hard ride burns more, so start at the top."}.get(
                           effort, "Start in the middle and adjust to how you feel."))
    else:
        start = 75 if effort == "hard" else 60
        out.update(g_per_h=start, low=60, high=90, range="60 to 90 g an hour",
                   why="Rides over 2.5 hours need steady carbs to avoid fading late, 60 to 90 g an hour. "
                       + ("A hard ride burns more, so start above the bottom. " if effort == "hard" else "")
                       + "Build toward 90 only after practising it on long rides.")
    out["total_g"] = round(out["g_per_h"] * hours) if out["g_per_h"] else out["optional_g"]
    out["notes"] = notes(out["g_per_h"])
    return out


# Caffeine, from the nutrition.md caffeine section and its coaching rule: 3 mg/kg about 60 minutes before
# key sessions or races is a sensible start, never over 6 mg/kg, avoid it within about 6 hours of bedtime,
# and trial it in training first. The 6 mg/kg ceiling is a firm safety limit. About 9 mg/kg adds side effects.
CAFFEINE_START_MG_PER_KG = 3
CAFFEINE_MAX_MG_PER_KG = 6
CAFFEINE_EVIDENCE = ("nutrition.md, caffeine. Evidence: Strong. Pool: an umbrella review of 21 meta-analyses "
                     "and 44 endurance time trial studies, mostly young men, with few women or older riders "
                     "(Guest et al., 2021; Grgic et al., 2020; Southward et al., 2018). Some people ride slower "
                     "on it, so try it in training first.")


def caffeine_limits(weight_kg: float | None) -> dict | None:
    """The caffeine starting dose and the firm ceiling for this rider, in mg for the whole ride."""
    if not weight_kg or weight_kg <= 0:
        return None
    return {"start_mg": round(CAFFEINE_START_MG_PER_KG * weight_kg),
            "max_mg": round(CAFFEINE_MAX_MG_PER_KG * weight_kg),
            "evidence": CAFFEINE_EVIDENCE}


def is_key_session(avg_if: float | None, race: bool = False) -> bool:
    """Caffeine is kept for races and hard sessions, so it isn't suggested on every ride."""
    return bool(race) or (avg_if is not None and avg_if >= HARD_IF)


def during_plan(minutes: float, avg_if: float | None, settings, weight_kg: float | None,
                race: bool = False, library: list[dict] | None = None) -> dict:
    """Everything for the ride: carbs per hour, food ideas for each hour, and an optional caffeine idea."""
    from metrics import foods
    carbs = during(minutes, avg_if)
    target = carbs["g_per_h"] or carbs["optional_g"]
    ideas = (foods.suggest("during", target, 0, settings, library=library) if target
             else {"ok": False, "combos": [], "message": carbs["why"]})
    caffeine = foods.caffeine_option(settings, weight_kg, key_session=is_key_session(avg_if, race),
                                     library=library)
    return {"carbs": carbs, "ideas": ideas, "per": "hour" if carbs["g_per_h"] else "ride", "caffeine": caffeine}
