"""The Fuel today tile on the Today page (fueling plan Changes 4 and 5).

Daily targets from metrics.nutrition_day, a sample day from metrics.recipes, and a before, during and
after plan for today's ride from metrics.fueling.ride_plan. Everything is a starting point the rider can
change. The referral message is a firm safety rule and shows first when it applies.
"""
from __future__ import annotations

from datetime import date as Date, timedelta

import streamlit as st

from db import queries as q
from metrics import diet as diet_mod
from metrics import fueling, nutrition_day
from metrics import recipes as rec

SETTINGS_PAGE = "pages/07_Settings.py"
RECIPES_PAGE = "pages/08_Recipes.py"
SKI_TYPES = {"nordic ski", "backcountry ski"}
INDOOR_WORDS = ("virtual", "indoor", "trainer")
TOMORROW_MIN = 120            # the plan's "over 2 h"
TOMORROW_TSS = 100            # or TSS over 100
RIDE_SLOTS = ("breakfast", "pre_ride", "pocket", "recovery", "dinner", "snack")
REST_SLOTS = ("breakfast", "lunch", "dinner", "snack")

# Written from knowledge/nutrition.md, each with its grade. Kept short on purpose.
BASICS = [
    ("Why carbs before, during and after",
     "Carbs are the main fuel for hard riding. A meal before tops up your stores, carbs during keep them "
     "from running out on long rides, and carbs after start the refill for tomorrow.",
     "Strong for carbs during rides (136 studies, mostly trained men). Moderate for the meal before and "
     "the refill after (glycogen studies of a few hundred people)."),
    ("What bonking is",
     "Bonking is when the carbs stored in your muscles and liver run low. Power drops, you feel empty and "
     "sometimes shaky or foggy. Steady carbs on rides over about 75 minutes keep it away.",
     "Strong. The benefit of carbs is larger the longer the ride (136 studies)."),
    ("Protein after is for repair",
     "Protein helps your muscles repair and adapt. It doesn't refill your carb stores any faster, so don't "
     "swap carbs for protein after a ride. About 0.3 g/kg in each of 4 or more meals is a good start.",
     "Strong for the daily range (1,863 people, resistance training). Limited for the dose per meal (one "
     "study of six young men)."),
    ("The gut can be trained",
     "Eating a lot on the bike takes practice. Building carbs an hour up slowly on long rides helps your gut "
     "handle more, which matters most before a race.",
     "Limited. One small trial in cyclists and lab work, no pooled data."),
    ("Too much water is a risk too",
     "Big fluid losses on long, hot rides hurt, but drinking more than you sweat can drop your blood sodium, "
     "which is dangerous. Learn your sweat rate by weighing before and after, and never finish heavier than "
     "you started. Headache, nausea or confusion after drinking a lot needs urgent care.",
     "Strong for drinking to your own sweat rate and against overdrinking. Limited and disputed for the "
     "2 percent weight loss line."),
]


def _settings() -> dict:
    s = diet_mod.load()
    s["favorite_recipes"] = q.get_setting("favorite_recipes", "")
    return s


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def todays_ride(day: Date) -> dict | None:
    """Today's ride as {"name", "minutes", "intensity", "indoor", "race", "done", "next_hard_in_h"}.

    A completed ride wins over a planned one. Ski days and workouts with no length give None, or a
    ride with minutes None so the tile can say why there is no plan."""
    d = day.isoformat()
    rides = [a for a in q.get_activities_between(d, d) if q.is_ride(a) and _num(a.get("duration_seconds"))]
    if rides:
        a = max(rides, key=lambda a: a["duration_seconds"])
        secs = float(a["duration_seconds"])
        intensity = _num(a.get("if_value")) or nutrition_day.if_from_tss(_num(a.get("tss")) or 0, secs)
        sport = (a.get("sport_type") or "").lower()
        return {"name": a.get("name") or "Ride", "minutes": secs / 60, "intensity": intensity,
                "indoor": any(w in sport for w in INDOOR_WORDS), "race": False, "done": True,
                "next_hard_in_h": None}
    planned = [w for w in q.get_workouts(d, d)
               if not w.get("completed") and (w.get("workout_type") or "").lower() not in SKI_TYPES]
    if not planned:
        return None
    sized = []
    for w in planned:
        minutes = nutrition_day._planned_minutes(w)
        tss = _num(w.get("tss_planned"))
        ride_if = nutrition_day.if_from_tss(tss, minutes * 60) if (minutes and tss) else None
        sized.append((w, minutes, ride_if or fueling.intensity_if(w.get("workout_type"))))
    w, minutes, intensity = max(sized, key=lambda t: t[1] or 0)
    # A second hard session later the same day is under 8 hours away.
    second_hard = any(x is not w and (i or 0) >= fueling.HARD_IF for x, _, i in sized)
    races_today = [r for r in q.get_races() if r.get("date") == d]
    return {"name": w.get("name") or "Ride", "minutes": minutes, "intensity": intensity,
            "indoor": any(word in (w.get("name") or "").lower() for word in INDOOR_WORDS),
            "race": (w.get("workout_type") or "").lower() == "race" or bool(races_today), "done": False,
            "next_hard_in_h": 0 if second_hard else None}


def tomorrow_line(load: dict, settings) -> dict | None:
    """When tomorrow is long or hard, more carbs tonight and a named dinner. None otherwise."""
    minutes, tss = load.get("minutes") or 0, load.get("tss") or 0
    if minutes <= TOMORROW_MIN and tss <= TOMORROW_TSS:
        return None
    what = (f"Tomorrow is {minutes / 60:.1f} hours" if minutes > TOMORROW_MIN
            else f"Tomorrow is a hard day ({tss:.0f} TSS)")
    dinner = fueling.recipe_ideas("dinner", None, None, settings, 1, prefer_carbs=True)
    text = f"{what}, so make tonight's dinner a big carb meal."
    if dinner:
        text += f" For example {dinner[0]['name'][:1].lower() + dinner[0]['name'][1:]}."
    return {"text": text, "recipe": dinner[0] if dinner else None}


def _go_settings(label: str, key: str) -> None:
    if st.button(label, key=key, icon=":material/settings:", type="tertiary"):
        st.switch_page(SETTINGS_PAGE)


def _targets(t: dict) -> None:
    c, p, k = t["carbs"], t["protein"], t["kcal"]
    m1, m2, m3 = st.columns(3)
    m1.metric("Carbs", f"{c['g']} g", help=f"{c['g_per_kg']:g} g/kg, a range of {c['low']} to {c['high']} g "
              f"({c['g_per_kg_range'][0]} to {c['g_per_kg_range'][1]} g/kg). {c['source']}")
    m1.caption(f"{c['g_per_kg']:g} g/kg")
    m2.metric("Protein", f"{p['g']} g", help=f"A range of {p['low']} to {p['high']} g. {p['source']}")
    m2.caption(f"about {p['per_meal_g']} g in each of {p['meals']} meals")
    if k.get("kcal"):
        # The unit sits in the caption so the number fits a narrow column.
        m3.metric("Calories", f"{k['kcal']:,}",
                  help=f"{k['why']} Range {k['low']:,} to {k['high']:,} kcal. {k['note']} {k['source']}")
        m3.caption("kcal, an estimate" if k.get("estimated")
                   else f"kcal, base {k['base']:,} plus training {k['training']:,}")
    else:
        m3.metric("Calories", "No base yet", help=f"{k['note']} {k['source']}")
        with m3:
            _go_settings("Set a base", "fuel_set_base")
    st.caption(" ".join(x for x in (c["why"], c["note"]) if x))


def _ideas(ideas: list[dict]) -> None:
    for i in ideas:
        st.markdown(f"- {i['text']}")


def _ride(ride: dict, plan: dict) -> None:
    st.markdown(f"**Your ride: {ride['name']}**, about {plan['minutes'] / 60:.1f} hours"
                + (". It's done, so the after part matters now." if ride["done"] else "."))
    b, d, a = st.columns(3)
    with b:
        before = plan["before"]
        st.markdown("**Before**")
        if before["g"]:
            st.markdown(f"About **{before['g']} g carbs** {before['timing']}")
        st.caption(before["why"])
        _ideas(before["ideas"])
        if before.get("night_before"):
            st.caption(f"Last night's dinner, for next time: {before['night_before']['name']}.")
        if plan.get("caffeine"):
            st.caption(plan["caffeine"]["message"], help=plan["caffeine"]["evidence"])
        if plan.get("fasted"):
            st.caption(plan["fasted"]["text"], help=plan["fasted"]["evidence"])
    with d:
        dur = plan["during"]
        carbs = dur["carbs"]
        st.markdown("**During**")
        if carbs["g_per_h"]:
            st.markdown(f"About **{carbs['g_per_h']} g carbs an hour** ({carbs['range']}), "
                        f"a feed every {fueling.FEED_EVERY_MIN} minutes")
        elif carbs["optional_g"]:
            st.markdown(f"Optional, up to **{carbs['optional_g']} g carbs**")
        else:
            st.markdown("Water is enough")
        st.caption(carbs["why"], help=carbs["evidence"])
        if dur["ideas"].get("ok"):
            for c in dur["ideas"]["combos"][:3]:
                st.markdown(f"- {c['text']}" + (" an hour" if dur["per"] == "hour" else ""))
        elif carbs["g_per_h"] or carbs["optional_g"]:
            st.caption(dur["ideas"]["message"])
        for n in carbs["notes"]:
            st.caption(n)
        hyd = dur["hydration"]
        st.caption(" ".join(hyd["lines"]), help=hyd["evidence"])
        if hyd.get("gut_training"):
            st.caption(hyd["gut_training"]["text"], help=hyd["gut_training"]["evidence"])
    with a:
        after = plan["after"]
        st.markdown("**After**")
        parts = []
        if after["protein_g"]:
            parts.append(f"**{after['protein_g']} g protein**")
        if after["refuel"]:
            parts.append(f"**{after['refuel']['g_per_h']} g carbs an hour for {after['refuel']['hours']} hours**")
        elif after["carbs_g"] and after["protein_g"]:
            parts.append(f"about **{after['carbs_g']} g carbs**")
        if parts:
            st.markdown(" plus ".join(parts) + " soon after")
        st.caption(after["why"], help=after["evidence"])
        if after["refuel"]:
            st.caption(after["refuel"]["text"])
        _ideas(after["ideas"])
        if after["rehydrate"]:
            st.caption(after["rehydrate"])


def _sample_day(day: Date, settings: dict, targets: dict, has_ride: bool) -> None:
    picks = rec.for_day(day, settings, n=1, targets=targets)
    slots = RIDE_SLOTS if has_ride else REST_SLOTS
    st.markdown("**A sample day**")
    st.caption("An example of how today could look, not a meal plan. Swap in anything you like.")
    # One row per meal, so long recipe names have room and don't get cut off.
    for slot in slots:
        options = picks["slots"].get(slot) or []
        label, pick = st.columns([1, 4], vertical_alignment="center")
        label.caption(rec.SLOT_LABELS[slot])
        with pick:
            if options:
                r = options[0]
                if st.button(r["name"], key=f"fuel_rec_{slot}", type="tertiary",
                             help=f"{r['per_serving']['carbs_g']:.0f} g carbs, "
                                  f"{r['per_serving']['protein_g']:.0f} g protein a serving. Opens the recipe."):
                    st.session_state["rec_open"] = r["id"]
                    st.switch_page(RECIPES_PAGE)
            else:
                st.caption("None that fit your settings yet")


def _basics() -> None:
    with st.expander("Fueling basics"):
        for title, text, grade in BASICS:
            st.markdown(f"**{title}**")
            st.markdown(text)
            st.caption(f"Evidence: {grade}")
        st.caption("From knowledge/nutrition.md. General guidance, not a meal plan or medical advice.")


def render(day: Date | None = None, owner: bool = True) -> None:
    day = day or Date.today()
    settings = _settings()
    with st.container(border=True):
        st.markdown("<div class='today-card-label'>Fuel today</div>", unsafe_allow_html=True)
        if settings.get("nutrition_referral"):
            st.warning(diet_mod.REFERRAL_MESSAGE if owner else diet_mod.REFERRAL_MESSAGE_THEY)
        targets = nutrition_day.day_targets(day)
        if not targets.get("ok"):
            st.markdown(targets["note"])
            _go_settings("Add your weight", "fuel_add_weight")
            _basics()
            return
        _targets(targets)

        ride = todays_ride(day)
        if ride and ride["minutes"]:
            plan = fueling.ride_plan(
                ride["minutes"], targets["weight_kg"], ride["intensity"], indoor=ride["indoor"],
                settings=settings, race=ride["race"], race_on_calendar=bool(q.get_races(upcoming_only=True)),
                next_hard_in_h=ride["next_hard_in_h"], day_carbs_g=targets["carbs"]["g"])
            if plan.get("ok"):
                st.divider()
                _ride(ride, plan)
        elif ride:
            st.caption(f"{ride['name']} has no length yet, so there is no ride fuel plan for it.")

        st.divider()
        _sample_day(day, settings, targets, has_ride=bool(ride and ride["minutes"]))
        tomorrow = tomorrow_line(nutrition_day.day_load(day + timedelta(days=1)), settings)
        if tomorrow:
            st.markdown(tomorrow["text"])
        for tip in rec.prep_ahead(rec.week_loads(day + timedelta(days=1)), settings):
            st.caption(f"Cook ahead: {tip['text']}")
        _basics()
