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


# ── Before, during and after one ride (fueling plan Change 5) ────────────────────────────────────
# Every amount comes from the nutrition.md rules for the coach. Where a rule gives a range, the
# starting point inside it is this app's choice, said so in the text, and the rider can change it.
PRE_RIDE_MIN = 60             # rides over 60 minutes get a pre ride meal
PRE_SNACK_G_PER_KG = 1        # a small snack 30 to 60 min before, about 1 g/kg (the 1 h end of the rule)
PRE_MEAL_RANGE = (1, 4)       # 1 to 4 g/kg, 1 to 4 h before: about 1 g/kg at 1 h up to 4 g/kg at 4 h
PRE_MEAL_G_PER_KG = 2        # the app's starting point inside the range, eaten 2 to 3 h before
EARLY_START_HOUR = 8          # a start before 08:00 leaves no time to eat 3 h before
EVENING_START_HOUR = 16       # caffeine after this risks sleep
FASTED_MAX_MIN = 90           # train low: easy rides under 90 minutes only
RECOVERY_PROTEIN_G_PER_KG = 0.3
REFUEL_G_PER_KG_H = (1.0, 1.2)   # with under 8 h to the next hard session, for 4 hours
REFUEL_HOURS = 4
REFUEL_GAP_H = 8
DRINK_ML_PER_KG_MIN = (0.15, 0.20)   # Holland et al., 2017, about 0.6 to 0.8 L an hour for 70 kg
SODIUM_FROM_MIN = 120         # rides over 2 hours, or in heat
GUT_TRAINING_MIN = 120

# Workout types as an intensity, when a ride has no IF. These IFs are the app's mapping of the type
# names, not research. Unknown types give None, which the rules treat as a steady ride.
TYPE_IF = {"recovery": 0.55, "spin": 0.55, "endurance": 0.68, "long ride": 0.70, "tempo": 0.80,
           "sweet spot": 0.88, "threshold": 0.95, "vo2": 1.05, "vo2 max": 1.05,
           "sprint/anaerobic": 1.0, "race": 0.95}

PRE_EVIDENCE = ("nutrition.md, pre ride meals. Evidence: Moderate. Pool: 63 trials, about 641 people, "
                "measuring muscle glycogen, with performance gains from small trials (Thomas et al., 2016; "
                "Burke et al., 2011). The timing and amount inside the range are set by this app.")
FASTED_EVIDENCE = ("nutrition.md, train low. Evidence: Moderate for no clear performance gain. Pool: 9 "
                   "training studies in well trained men and women (Gejl & Nybo, 2021).")
HYDRATION_EVIDENCE = ("nutrition.md, hydration. Evidence: Strong for drinking to your own sweat rate and for "
                      "not overdrinking; Limited and disputed for the 2 percent threshold. Pool: 15 studies, "
                      "about 122 people, plus 2,135 weighed athletes in events (observational).")
GUT_EVIDENCE = ("nutrition.md, the gut is trainable. Evidence: Limited. One small trial in cyclists "
                "(Cox et al., 2010), no meta-analysis.")
AFTER_EVIDENCE = ("nutrition.md, recovery and protein. Evidence: Moderate for carb refuelling (29 trials, "
                  "about 246 people, mostly trained men). Limited for the protein dose per meal (one study "
                  "of six young men after leg resistance exercise) and for the rehydration volume.")


def intensity_if(intensity) -> float | None:
    """A ride's intensity as IF. Takes an IF number or a workout type such as "Threshold"."""
    if intensity is None:
        return None
    if isinstance(intensity, (int, float)):
        return float(intensity) if intensity > 0 else None
    try:
        return float(intensity)
    except (TypeError, ValueError):
        return TYPE_IF.get(str(intensity).strip().lower())


def _start_hour(start_time) -> float | None:
    """Hour of the day from a time, a datetime or "HH:MM"."""
    if start_time is None or start_time == "":
        return None
    if hasattr(start_time, "hour"):
        return start_time.hour + getattr(start_time, "minute", 0) / 60
    try:
        h, _, m = str(start_time).partition(":")
        return int(h) + (int(m or 0) / 60)
    except ValueError:
        return None


def _when(start_time, usual_ride_time) -> str | None:
    """"early", "midday" or "evening" from the start time, or the rider's usual ride time."""
    hour = _start_hour(start_time)
    if hour is None:
        return usual_ride_time if usual_ride_time in ("early", "midday", "evening") else None
    if hour < EARLY_START_HOUR:
        return "early"
    return "evening" if hour >= EVENING_START_HOUR else "midday"


def _referral(settings) -> bool | None:
    """The health question: True, False, or None when unanswered."""
    from metrics import diet as diet_mod
    raw = (settings or {}).get("nutrition_referral")
    return raw if isinstance(raw, bool) else diet_mod._flag(raw)


def recipe_ideas(slot: str, carbs_g: float | None, protein_g: float | None, settings, n: int,
                  recipes=None, library=None, prefer_carbs: bool = False) -> list[dict]:
    """Recipes for this slot that the rider can have, closest to the target first. Favourites first."""
    from metrics import recipes as rec
    pool = [r for r in rec.allowed_recipes(settings, recipes, library) if slot in (r.get("slots") or [])]
    stars = set(rec.favorites(settings))

    def rank(r):
        p = r["per_serving"]
        if prefer_carbs:
            close = -p["carbs_g"]
        else:
            close = sum(abs(p[k] - t) / t for k, t in (("carbs_g", carbs_g), ("protein_g", protein_g)) if t)
        return (r["id"] not in stars, close, r["id"])

    return [{"kind": "recipe", "id": r["id"], "name": r["name"],
             "text": f"{r['name']} ({r['per_serving']['carbs_g']:.0f} g carbs, "
                     f"{r['per_serving']['protein_g']:.0f} g protein a serving)"}
            for r in sorted(pool, key=rank)[:n]]


def _food_ideas(phase: str, carbs_g, protein_g, settings, n: int, library=None) -> list[dict]:
    from metrics import foods
    res = foods.suggest(phase, carbs_g, protein_g, settings, n=n, library=library)
    return [{"kind": "food", "text": c["text"]} for c in res["combos"]]


def _ideas(phase, slot, carbs_g, protein_g, settings, library=None, recipes=None, recipe_lib=None,
           n: int = 3) -> list[dict]:
    """2 or 3 ideas: one recipe, then food combinations from the library."""
    out = recipe_ideas(slot, carbs_g, protein_g, settings, 1, recipes, recipe_lib) if slot else []
    out += _food_ideas(phase, carbs_g, protein_g, settings, n - len(out), library)
    return out[:n]


def _before(minutes, weight, effort, when, settings, library, recipes, recipe_lib) -> dict:
    hard = effort == "hard"
    out = {"g": 0, "low": 0, "high": 0, "timing": "", "why": "", "ideas": [],
           "early": False, "evidence": PRE_EVIDENCE, "night_before": None}
    if minutes <= PRE_RIDE_MIN and not hard:
        out["why"] = ("For an hour or less at an easy or steady pace, your normal meals cover it. "
                      "There is no need for extra carbs before.")
        return out
    snack = round(PRE_SNACK_G_PER_KG * weight)
    if minutes <= PRE_RIDE_MIN or when == "early":
        out.update(g=snack, low=snack, high=snack, timing="30 to 60 minutes before")
        # Low fibre and low fat foods only. Recipes carry no such check, so none are offered here.
        gentle = dict(settings or {}, gut_sensitive=True)
        out["ideas"] = _food_ideas("before", snack, 0, gentle, 3, library)
        if minutes <= PRE_RIDE_MIN:
            out["why"] = ("A short hard session still goes better with a small carb snack, so you start "
                          "the efforts topped up. Keep it low in fibre so it sits well.")
        else:
            out["early"] = True
            out["why"] = ("An early start leaves no time for a big meal 3 hours before, so have a small, "
                          "low fibre snack and make last night's dinner the big carb meal.")
            dinner = recipe_ideas("dinner", None, None, settings, 1, recipes, recipe_lib, prefer_carbs=True)
            out["night_before"] = dinner[0] if dinner else None
        return out
    out.update(g=round(PRE_MEAL_G_PER_KG * weight), low=round(PRE_MEAL_RANGE[0] * weight),
               high=round(PRE_MEAL_RANGE[1] * weight), timing="2 to 3 hours before")
    out["why"] = ("This tops up the carbs stored in your muscles and liver for the ride. Research gives "
                  "1 to 4 g/kg in the 1 to 4 hours before, about 1 g/kg at 1 hour and up to 4 g/kg at "
                  f"4 hours. This app starts you at {PRE_MEAL_G_PER_KG} g/kg, so eat more if you eat earlier.")
    out["ideas"] = _ideas("before", "breakfast", out["g"], 0, settings, library, recipes, recipe_lib)
    return out


def _fasted(minutes, effort, race, settings) -> dict | None:
    """The optional easy fasted ride, only where the train low rules allow it."""
    if race or effort != "easy" or minutes >= FASTED_MAX_MIN:
        return None
    if _referral(settings) is not False:      # unanswered or yes: never, a firm safety rule
        return None
    return {"text": ("Optional: an easy ride like this one can be done before breakfast if you like riding "
                     "that way. Keep it to 1 to 3 easy rides a week, never for intervals, races or long "
                     "rides, and stop if you notice low energy, illness or unplanned weight loss. Pooled "
                     "trials show no clear race benefit, so eating first is just as good."),
            "evidence": FASTED_EVIDENCE}


def _caffeine(weight, ride_if, race, when, settings, library) -> dict | None:
    """The existing caffeine option, or None. Never shown to riders who avoid caffeine."""
    from metrics import foods
    from metrics import diet as diet_mod
    if "caffeine" in diet_mod.parse_avoid((settings or {}).get("avoid_foods")):
        return None
    opt = foods.caffeine_option(settings, weight, key_session=is_key_session(ride_if, race), library=library)
    if not opt.get("ok"):
        return None
    if when == "evening":
        opt = dict(opt, message=opt["message"] + " This is an evening ride, so it may cost you sleep.")
    return opt


def _hydration(minutes, weight, indoor, race_on_calendar) -> dict:
    lines = []
    if minutes <= 60:
        lines.append("Up to about an hour, drink to thirst. Extra fluid doesn't help here.")
    else:
        low = weight * DRINK_ML_PER_KG_MIN[0] * 60 / 1000
        high = weight * DRINK_ML_PER_KG_MIN[1] * 60 / 1000
        lines.append(f"Drink regularly, about {low:.1f} to {high:.1f} L an hour to start, then adjust to your "
                     "own sweat rate. Weigh yourself before and after a ride to learn it.")
        lines.append("Avoid a big deficit on long or hot rides, and never finish heavier than you started. "
                     "Drinking more than you sweat can be dangerous too.")
    if minutes > SODIUM_FROM_MIN:
        lines.append("Over 2 hours or in heat, add sodium: a drink with about 0.5 to 0.7 g per litre.")
    else:
        lines.append("In heat, add sodium: a drink with about 0.5 to 0.7 g per litre.")
    if indoor:
        lines.append("Indoors, less air moves over you and sweat rates run higher. Use a fan and drink a "
                     "little more.")
    gut = None
    if race_on_calendar and minutes >= GUT_TRAINING_MIN:
        gut = {"text": ("You have a race coming. Use long rides like this to practise your race fuel plan, "
                        "building by about 10 to 15 g an hour every week or two if it sits well. The evidence "
                        "for gut training is limited, so treat it as sensible practice."),
               "evidence": GUT_EVIDENCE}
    return {"lines": lines, "evidence": HYDRATION_EVIDENCE, "gut_training": gut}


def _after(minutes, weight, effort, next_hard_in_h, day_carbs_g, settings, library, recipes, recipe_lib) -> dict:
    protein = round(RECOVERY_PROTEIN_G_PER_KG * weight)
    hard_or_long = effort == "hard" or minutes >= 90
    out = {"protein_g": protein if hard_or_long else 0, "carbs_g": None, "refuel": None, "ideas": [],
           "why": "", "rehydrate": None, "evidence": AFTER_EVIDENCE}
    if next_hard_in_h is not None and next_hard_in_h < REFUEL_GAP_H:
        lo, hi = (round(x * weight) for x in REFUEL_G_PER_KG_H)
        out["refuel"] = {"g_per_h": lo, "high_per_h": hi, "hours": REFUEL_HOURS,
                         "text": f"Your next hard session is under 8 hours away. Take {lo} to {hi} g of carbs "
                                 f"an hour, at least hourly, for {REFUEL_HOURS} hours to refill in time."}
        out["carbs_g"] = lo
    elif day_carbs_g:
        from metrics import recipes as rec
        out["carbs_g"] = rec.slot_carbs("recovery", day_carbs_g)
    if hard_or_long:
        out["why"] = ("Protein soon after helps repair muscle. Carbs start the refill. Protein doesn't speed "
                      "the refill, so don't cut carbs to make room for it.")
    else:
        out["why"] = ("After a short easy ride your next normal meal covers it. Keep to your daily targets.")
    if hard_or_long or out["refuel"]:
        out["ideas"] = _ideas("after", "recovery", out["carbs_g"], out["protein_g"] or None, settings,
                              library, recipes, recipe_lib)
    if minutes > 60:
        out["rehydrate"] = ("Rehydrate with about 1.25 to 1.5 L for each kg you lost on the ride, with some salt "
                            "from food or an electrolyte drink.")
    return out


def ride_plan(minutes, weight_kg, intensity, start_time=None, indoor=False, *, settings=None, race=False,
              race_on_calendar=False, next_hard_in_h=None, day_carbs_g=None, library=None, recipes=None,
              recipe_lib=None) -> dict:
    """What and when to eat before, during and after one ride, with a plain why for each part.

    intensity is the ride's IF, or its workout type ("Threshold"). start_time is a time or "HH:MM";
    without it, settings["usual_ride_time"] decides whether this is an early ride. settings are the How
    you eat answers (metrics.diet), which filter every food and recipe idea. Returns {"ok": False,
    "message"} without a weight, since every amount is per kg."""
    if not weight_kg or weight_kg <= 0:
        return {"ok": False, "message": "Add your weight in Settings to see how much to eat around rides."}
    minutes = max(float(minutes or 0), 0)
    weight = float(weight_kg)
    ride_if = intensity_if(intensity)
    effort = _effort(ride_if)
    settings = settings or {}
    when = _when(start_time, settings.get("usual_ride_time"))
    before = _before(minutes, weight, effort, when, settings, library, recipes, recipe_lib)
    during_part = during_plan(minutes, ride_if, settings, weight, race=race, library=library)
    during_part.pop("caffeine", None)          # caffeine is offered once, in before
    during_part["hydration"] = _hydration(minutes, weight, indoor, race_on_calendar)
    during_part["feeds"] = feeds(minutes / 60, during_part["carbs"]["g_per_h"])
    after = _after(minutes, weight, effort, next_hard_in_h, day_carbs_g, settings, library, recipes, recipe_lib)
    return {"ok": True, "minutes": minutes, "if": ride_if, "effort": effort, "when": when,
            "indoor": bool(indoor), "before": before, "during": during_part, "after": after,
            "fasted": _fasted(minutes, effort, race, settings),
            "caffeine": _caffeine(weight, ride_if, race, when, settings, library)}
