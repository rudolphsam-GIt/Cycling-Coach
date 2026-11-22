"""
Daily fuel targets: carbs, protein and calories for one day, from the day's training.

Every number is a starting point the rider can change, taken from knowledge/nutrition.md with its
evidence grade. Pure functions that read the database and write nothing.

Energy from power: kJ of work is about the same as kcal burned. Muscles turn roughly 20 to 25 percent
of food energy into work at the pedals, and 1 kcal is 4.184 kJ, so the two cancel. No other factor is
applied.
"""
from __future__ import annotations

import json
import math
from datetime import date as Date

from db import queries as q

KJ_NOTE = ("Energy from power uses kJ ≈ kcal. About 20 to 25 percent of food energy becomes work at "
           "the pedals, and 1 kcal is 4.184 kJ, so the two cancel out.")

# Carb bands from nutrition.md (Thomas et al., 2016). The source gives "about 1 h a day" and
# "1 to 3 h a day" with gaps between, so these edges are ours and are stated in the help text.
LIGHT_MAX_MIN = 45        # under 45 minutes counts as a light day
EASY_IF = 0.65            # a day this easy counts as light whatever its length
ONE_HOUR_MAX_MIN = 90     # 45 to 89 minutes is the about 1 h band
MODERATE_MAX_MIN = 210    # 90 minutes to 3 h 29 min is the 1 to 3 h band, 3 h 30 and over the 4 to 5 h band

CARB_BANDS = {
    "light": (3, 5, "Light day or rest. 3 to 5 g/kg keeps your stores ready."),
    "1h": (5, 7, "About an hour of training. 5 to 7 g/kg refills what the session used."),
    "1to3h": (6, 10, "One to three hours of training. 6 to 10 g/kg covers the work and the refill."),
    "4to5h": (8, 12, "A very big day. 8 to 12 g/kg, much of it on the bike, keeps you from running empty."),
}
CARB_SOURCE = ("nutrition.md, daily carbohydrate. Evidence: Moderate. Expert consensus (Thomas et al., "
               "2016). Pooled data show muscle glycogen tracks intake, but no large trials test the bands "
               "against performance. Band edges between the published ones are set by this app.")

PROTEIN_G_PER_KG = 1.6
PROTEIN_RANGE = (1.2, 2.0)
PROTEIN_PER_MEAL_G_PER_KG = 0.3
PROTEIN_MEALS = 4
PROTEIN_SOURCE = ("nutrition.md, protein. Evidence: Strong for the daily range (resistance training "
                  "pools, 1,863 people), Moderate for endurance benefit (about 1,150 people), Limited for "
                  "the per meal dose (one study of six young men after leg resistance exercise).")

# Non exercise activity factor. FAO/WHO/UNU (2004) puts sedentary or light lifestyles at 1.40 to 1.69
# times BMR, for people without regular exercise. Training is added on top from power, so the low end
# is the starting point and the range runs to the top of that band for riders with active jobs.
ACTIVITY_FACTOR = 1.4
ACTIVITY_RANGE = (1.4, 1.69)
KCAL_SOURCE = ("nutrition.md, daily energy. Base from Mifflin St Jeor (the most accurate common equation "
               "in a systematic review, Frankenfield et al., 2005, though errors for one person can still "
               "be large) times 1.4 to 1.69 for daily life without exercise (FAO/WHO/UNU, 2004). Training "
               "is added from the day's kJ. Evidence: Moderate for the equation, expert consensus for the "
               "factor. Your own base_kcal setting replaces the estimate.")

RIDE_WORDS = ("ride", "cycl", "bik")


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def _is_ride(sport: str | None) -> bool:
    s = (sport or "").lower()
    return any(w in s for w in RIDE_WORDS)


def if_from_tss(tss: float, seconds: float) -> float | None:
    """IF from TSS and time, since TSS = hours × IF² × 100 (Coggan)."""
    hours = seconds / 3600
    if not tss or hours <= 0:
        return None
    return math.sqrt(tss / (100 * hours))


def kj_from_tss(tss: float, seconds: float, ftp: float) -> float | None:
    """Estimated kJ from TSS. Uses NP in place of average power, so it runs a little high."""
    intensity = if_from_tss(tss, seconds)
    if intensity is None or not ftp:
        return None
    return intensity * ftp * seconds / 1000


def _planned_minutes(workout: dict) -> float | None:
    raw = workout.get("structured_json")
    if not raw:
        return None
    try:
        steps = json.loads(raw)
        from garmin_workouts import total_minutes
        minutes = total_minutes(steps)
    except (TypeError, ValueError, KeyError):
        return None
    return minutes or None


def day_load(day: str | Date) -> dict:
    """Minutes, TSS, average IF and kJ for a day. Completed activities win over planned workouts.

    Returns source ("completed", "planned" or "none"), kj_estimated (some kJ came from TSS, not
    measured power), and unknown (counts of sessions whose kJ or length couldn't be worked out)."""
    day = str(day)
    out = {"date": day, "minutes": 0.0, "tss": 0.0, "avg_if": None, "kj": 0.0,
           "kj_estimated": False, "unknown_kj": 0, "unknown_minutes": 0, "source": "none"}
    if_weighted, if_seconds = 0.0, 0.0

    activities = q.get_activities_between(day, day)
    if activities:
        out["source"] = "completed"
        ftp = q.ftp_on(day)
        for a in activities:
            secs = _num(a.get("duration_seconds")) or 0
            tss = _num(a.get("tss")) or 0
            out["minutes"] += secs / 60
            out["tss"] += tss
            intensity = _num(a.get("if_value")) or (if_from_tss(tss, secs) if secs else None)
            if intensity and secs:
                if_weighted += intensity * secs
                if_seconds += secs
            watts = _num(a.get("avg_power_watts"))
            if watts and secs:
                out["kj"] += watts * secs / 1000
            elif _is_ride(a.get("sport_type")) and tss and secs and ftp:
                out["kj"] += kj_from_tss(tss, secs, ftp)
                out["kj_estimated"] = True
            elif secs:
                out["unknown_kj"] += 1
    else:
        workouts = [w for w in q.get_workouts(day, day) if not w.get("completed")]
        if workouts:
            out["source"] = "planned"
        ftp = q.ftp_on(day)
        for w in workouts:
            tss = _num(w.get("tss_planned")) or 0
            minutes = _planned_minutes(w)
            out["tss"] += tss
            if not minutes:
                if tss:
                    out["unknown_minutes"] += 1
                continue
            secs = minutes * 60
            out["minutes"] += minutes
            intensity = if_from_tss(tss, secs)
            if intensity:
                if_weighted += intensity * secs
                if_seconds += secs
            kj = kj_from_tss(tss, secs, ftp)
            if kj:
                out["kj"] += kj
                out["kj_estimated"] = True
            else:
                out["unknown_kj"] += 1

    if if_seconds:
        out["avg_if"] = round(if_weighted / if_seconds, 2)
    out["minutes"] = round(out["minutes"])
    out["tss"] = round(out["tss"])
    out["kj"] = round(out["kj"])
    return out


def carb_band(minutes: float, avg_if: float | None = None) -> dict:
    """The nutrition.md carb band for a day's training, with a midpoint to start from (g/kg)."""
    minutes = minutes or 0
    if minutes < LIGHT_MAX_MIN or (avg_if is not None and avg_if < EASY_IF):
        key = "light"
    elif minutes < ONE_HOUR_MAX_MIN:
        key = "1h"
    elif minutes < MODERATE_MAX_MIN:
        key = "1to3h"
    else:
        key = "4to5h"
    low, high, why = CARB_BANDS[key]
    return {"band": key, "low": low, "high": high, "start": (low + high) / 2, "why": why}


def protein_target(weight_kg: float) -> dict:
    """1.6 g/kg a day (range 1.2 to 2.0), in 4 or more meals of about 0.3 g/kg."""
    per_meal = round(weight_kg * PROTEIN_PER_MEAL_G_PER_KG)
    return {"g": round(weight_kg * PROTEIN_G_PER_KG),
            "low": round(weight_kg * PROTEIN_RANGE[0]), "high": round(weight_kg * PROTEIN_RANGE[1]),
            "meals": PROTEIN_MEALS, "per_meal_g": per_meal,
            "why": f"Protein repairs muscle after training. Spread it out, about {per_meal} g in each of "
                   f"{PROTEIN_MEALS} or more meals, including one soon after hard or long rides.",
            "source": PROTEIN_SOURCE}


def mifflin_st_jeor(weight_kg: float, height_cm: float, age: float, sex: str) -> float:
    """Resting energy in kcal a day (Mifflin et al., 1990). sex is "female" or "male"."""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return base + (5 if sex == "male" else -161)


def estimated_base(weight_kg: float, height_cm: float | None, age: float | None,
                   sex: str | None) -> dict | None:
    """Base kcal (daily life without training) as a start and a range, or None if anything is missing.

    sex "prefer_not" gives the range spanning both formulas."""
    if not (weight_kg and height_cm and age) or sex not in ("female", "male", "prefer_not"):
        return None
    sexes = ("female", "male") if sex == "prefer_not" else (sex,)
    bmrs = [mifflin_st_jeor(weight_kg, height_cm, age, s) for s in sexes]
    start = sum(bmrs) / len(bmrs) * ACTIVITY_FACTOR
    return {"start": round(start, -1), "low": round(min(bmrs) * ACTIVITY_RANGE[0], -1),
            "high": round(max(bmrs) * ACTIVITY_RANGE[1], -1)}


def calorie_target(weight_kg: float, day_kj: float, base_kcal: float | None = None,
                   estimate: dict | None = None) -> dict | None:
    """Base plus training kcal. The rider's own base_kcal wins. With neither, returns None: no guess."""
    training = round(day_kj or 0)
    if base_kcal:
        base = float(base_kcal)
        return {"kcal": round(base + training), "low": round(base + training),
                "high": round(base + training), "base": round(base), "training": training,
                "estimated": False, "why": "Your base for daily life plus what today's training burns."}
    if estimate:
        return {"kcal": round(estimate["start"] + training), "low": round(estimate["low"] + training),
                "high": round(estimate["high"] + training), "base": estimate["start"],
                "training": training, "estimated": True,
                "why": "An estimate from your height, weight and age, plus today's training. Set your own "
                       "base in Settings if you know it."}
    return None


def _age(today: Date) -> float | None:
    year = _num(q.get_setting("birth_year"))
    return today.year - year if year else None


def day_targets(day: str | Date | None = None) -> dict:
    """Carbs, protein and kcal for a day, each with a range, a note, a reason and a source.

    Returns {"ok": False, "note": ...} when there's no weight to work from."""
    day = Date.fromisoformat(str(day)) if day else Date.today()
    weight = _num(q.get_setting("weight_kg"))
    if not weight:
        return {"ok": False, "date": str(day),
                "note": "Add your weight in Settings to see daily fuel targets."}

    load = day_load(day)
    band = carb_band(load["minutes"], load["avg_if"])
    notes = []
    if load["source"] == "planned":
        notes.append("From today's plan. It updates once the ride syncs.")
    if load["kj_estimated"]:
        notes.append("Training energy is estimated from TSS, so it may run a little high.")
    if load["unknown_kj"]:
        notes.append("Some sessions had no power data, so their energy isn't counted.")
    if load["unknown_minutes"]:
        notes.append("A planned session has no length, so it isn't counted in the carb band.")

    carbs = {"g": round(band["start"] * weight), "low": round(band["low"] * weight),
             "high": round(band["high"] * weight), "g_per_kg": band["start"],
             "g_per_kg_range": (band["low"], band["high"]), "band": band["band"],
             "why": band["why"], "note": " ".join(notes), "source": CARB_SOURCE}

    protein = protein_target(weight)
    protein["note"] = ""

    estimate = estimated_base(weight, _num(q.get_setting("height_cm")), _age(day),
                              q.get_setting("energy_sex"))
    kcal = calorie_target(weight, load["kj"], _num(q.get_setting("base_kcal")), estimate)
    if kcal:
        kcal["source"] = KCAL_SOURCE
        kcal["note"] = KJ_NOTE + (" Training is estimated from TSS." if load["kj_estimated"] else "")
    else:
        kcal = {"kcal": None, "note": "Set a base in Settings (or add height, age and sex for an "
                                      "estimate) to see a calorie target.", "source": KCAL_SOURCE}

    return {"ok": True, "date": str(day), "weight_kg": weight, "load": load,
            "carbs": carbs, "protein": protein, "kcal": kcal}
