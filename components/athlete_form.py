"""
The coach's Add athlete form. Sam fills it in about someone he coaches, so it asks for "their"
numbers. It shares the save logic with onboarding (onboarding.save_answers) and then adds what a
coach knows that a new rider usually doesn't: heart rates, the weekdays they ride, and ride files.
"""
from __future__ import annotations

from datetime import date

import streamlit as st

import planning
from components import onboarding
from components.units import weight_input
from db import profiles, schema
from db.queries import get_setting, set_setting
from metrics.explain import (ACTIVITY_DETAILS, ACTIVITY_LEVEL, DEFAULT_ACTIVITY, DEFAULT_GENDER,
                             GENDER_LABELS, RIDER_TYPES, starting_ftp_range)
from metrics.units import DISTANCE_UNITS, UNITS
from metrics.training_load import rides_cover_seed

OPEN_KEY = "adding_athlete"

FTP_CHOICES = {
    "I know their FTP": "known",
    "Estimate it and put an FTP test in their first block": "test",
    "Estimate it and skip the test": "estimate",
}

DEFAULT_DAYS = ["Tue", "Thu", "Sat", "Sun"]

# The answers onboarding.save_answers takes, so the form passes exactly those through.
_SHARED = ("name", "goal_text", "rider_type", "activity", "gender", "age", "weekly_hours",
           "days_per_week", "weight", "unit", "dist_unit", "ftp_choice", "ftp_input", "lthr_input",
           "race_name", "race_date")


def open_form() -> None:
    st.session_state[OPEN_KEY] = True


def close_form() -> None:
    st.session_state.pop(OPEN_KEY, None)


def is_open() -> bool:
    return bool(st.session_state.get(OPEN_KEY))


def save_athlete(answers: dict, fit_files=None) -> dict:
    """Create the athlete's profile and fill it in. Settings and FTP go in first, so ride files
    imported afterwards are scored on their FTP and heart rates. When the files reach back six
    weeks or more, the starting fitness seed is dropped so it doesn't count on top of the rides.
    Returns the new profile plus {imported, message, seed_reset}."""
    days = planning.parse_days(answers.get("available_days"))
    shared = {k: answers.get(k) for k in _SHARED}
    shared["days_per_week"] = len(days) or answers.get("days_per_week") or len(DEFAULT_DAYS)
    shared["race_name"] = shared["race_name"] or ""
    p = profiles.create_profile(answers["name"])
    with schema.use(p["path"]):
        onboarding.save_answers(**shared)
        set_setting("max_hr_manual", int(answers["max_hr"]) if answers.get("max_hr") else "")
        set_setting("resting_hr_manual", int(answers["resting_hr"]) if answers.get("resting_hr") else "")
        set_setting("available_days", ",".join(days))
        set_setting("onboarding_complete", "1")
        imported, message, seed_reset = 0, "", False
        if fit_files:
            from auth.fit_import import import_fit_files
            imported, message = import_fit_files(fit_files)
            if imported and rides_cover_seed():
                set_setting("ctl_start", 0)
                set_setting("atl_start", 0)
                seed_reset = True
    return {**p, "imported": imported, "message": message, "seed_reset": seed_reset}


def _rides_note(result: dict) -> str:
    if not result["imported"]:
        return result["message"]
    note = result["message"]
    if result["seed_reset"]:
        note += " Their rides go back six weeks or more, so fitness is worked out from the rides alone."
    else:
        note += " Their fitness starts from an estimate until more rides are in."
    return note


def render_athlete_form() -> None:
    st.markdown(
        '<div class="hero">'
        '<div class="hero-eyebrow">Coaching</div>'
        '<div class="hero-title">Add an athlete</div>'
        '<div class="hero-sub">What you know about them. Their plan, rides and coach chat stay in '
        'their own profile.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    _, col_form, _ = st.columns([1, 2, 1])
    with col_form:
        # Plain widgets rather than a form, so the weight box converts when the unit changes and the
        # FTP options show their own fields. The unit switches here don't save, since the profile
        # you are on now isn't the one being made.
        u1, u2 = st.columns(2)
        saved_unit = get_setting("weight_unit", "") or "lb"
        unit = u1.segmented_control("Weight units", list(UNITS), key="af_unit",
                                    default=saved_unit if saved_unit in UNITS else "lb") or "lb"
        saved_dist = get_setting("distance_unit", "") or "mi"
        dist_unit = u2.segmented_control("Distance units", list(DISTANCE_UNITS), key="af_distance",
                                         default=saved_dist if saved_dist in DISTANCE_UNITS else "mi") or "mi"

        name = st.text_input("Their name", placeholder="e.g. Alex", key="af_name")
        goal_text = st.text_area(
            "Their goals", key="af_goals", height=100,
            placeholder="In their words or yours, a sentence or two is plenty.",
            help="The coach plans around what you write here.")
        st.caption("For example " + ", ".join(onboarding.GOAL_EXAMPLES).lower() + ".")

        rider_type = st.radio(
            "Which best describes them?", list(RIDER_TYPES), key="af_rider_type",
            captions=[v["detail"] for v in RIDER_TYPES.values()],
            help="Sets their starting fitness and a typical power range if you don't know their FTP.")
        activity = st.radio(
            "How active are they right now?", list(ACTIVITY_LEVEL), key="af_activity",
            index=list(ACTIVITY_LEVEL).index(DEFAULT_ACTIVITY),
            captions=[ACTIVITY_DETAILS[k] for k in ACTIVITY_LEVEL])

        g_col, a_col = st.columns(2)
        gender_label = g_col.selectbox("Gender", list(GENDER_LABELS), index=None, placeholder="Optional",
                                       key="af_gender",
                                       help="Used only to pick typical power ranges.")
        gender = GENDER_LABELS.get(gender_label, DEFAULT_GENDER)
        age = a_col.number_input("Age", min_value=12, max_value=95, value=None, step=1,
                                 placeholder="Optional", key="af_age")

        weight = weight_input("Weight", 70.0, key="af_weight", unit=unit, min_kg=30.0, max_kg=200.0)
        weekly_hours = st.slider("Hours a week they can train", min_value=1, max_value=20, value=6,
                                 key="af_hours")
        available_days = st.multiselect(
            "Days they can ride", list(planning.WEEKDAYS), default=DEFAULT_DAYS, key="af_days",
            placeholder="Any day",
            help="Generated blocks and the coach put rides only on these days, with the long ride on a "
                 "weekend day when one is picked. Leave empty for any four days.")

        st.markdown("**Their FTP**")
        ftp_label = st.radio("FTP", list(FTP_CHOICES), key="af_ftp_choice", label_visibility="collapsed")
        ftp_choice = FTP_CHOICES[ftp_label]
        start = starting_ftp_range(weight, rider_type, activity, gender, age)
        ftp_in = None
        if ftp_choice == "known":
            ftp_in = st.number_input("FTP in watts", min_value=50, max_value=600, value=200, step=5,
                                     key="af_ftp")
        else:
            st.caption(f"Riders like them usually start between {start['low']:.0f} and {start['high']:.0f} "
                       f"watts. They will start at {start['start']:.0f} W, refined from their rides"
                       + (" and the test." if ftp_choice == "test" else "."))

        st.markdown("**Heart rate**")
        h1, h2, h3 = st.columns(3)
        lthr_in = h1.number_input("Threshold HR", min_value=0, max_value=220, value=None, step=1,
                                  placeholder="Estimate", key="af_lthr",
                                  help="The heart rate they can hold for about an hour. Estimated if blank.")
        max_hr = h2.number_input("Max HR", min_value=0, max_value=230, value=None, step=1,
                                 placeholder="From rides", key="af_max_hr",
                                 help="Leave blank to use the highest heart rate their rides reach.")
        resting_hr = h3.number_input("Resting HR", min_value=0, max_value=120, value=None, step=1,
                                     placeholder="Optional", key="af_rest_hr")

        st.markdown("**Goal race (optional)**")
        r1, r2 = st.columns([3, 2])
        race_name = r1.text_input("Race name", placeholder="e.g. OBRA Road Race #3", key="af_race_name")
        race_date = r2.date_input("Race date", value=None, min_value=date.today(), key="af_race_date")

        st.markdown("**Their rides (optional)**")
        fit_files = st.file_uploader(
            "Ride files", type=["fit"], accept_multiple_files=True, key="af_fit",
            label_visibility="collapsed",
            help="Ask them to export rides from Garmin Connect or Strava as .fit files. Six weeks or "
                 "more gives the app their real fitness. You can add more later in Settings.")

        go, cancel = st.columns(2)
        submitted = go.button("Add athlete", type="primary", width="stretch", key="af_go")
        cancel.button("Cancel", width="stretch", key="af_cancel", on_click=close_form)

        if submitted:
            if not name.strip():
                st.error("Give them a name.")
                return
            if not goal_text.strip():
                st.error("Write a sentence about their goals so the coach has something to plan around.")
                return
            with st.spinner("Setting up their profile"):
                result = save_athlete({
                    "name": name.strip(), "goal_text": goal_text, "rider_type": rider_type,
                    "activity": activity, "gender": gender, "age": age, "weekly_hours": weekly_hours,
                    "available_days": available_days, "weight": weight, "unit": unit, "dist_unit": dist_unit,
                    "ftp_choice": ftp_choice, "ftp_input": ftp_in, "lthr_input": lthr_in,
                    "max_hr": max_hr, "resting_hr": resting_hr,
                    "race_name": race_name, "race_date": race_date,
                }, fit_files)
            from components import profile_switcher
            profile_switcher.switch_to(result["slug"])      # also closes this form
            st.session_state["onboarding_just_finished"] = ["coached"]
            st.session_state["athlete_rides_note"] = _rides_note(result) if fit_files else ""
            st.rerun()
