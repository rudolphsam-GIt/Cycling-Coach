"""
The coach's Add athlete form. Sam fills it in about someone he coaches, so it asks for "their"
numbers. It shares the save logic with onboarding (onboarding.save_answers) and then adds what a
coach knows that a new rider usually doesn't: heart rates, the weekdays they ride, and ride files.
It can also fill itself in from the intake Google Form's responses (intake_import), for Sam to
check before saving.
"""
from __future__ import annotations

from datetime import date

import streamlit as st

import intake_import
import planning
from auth.fit_import import RIDE_FILE_HELP, RIDE_FILE_TYPES
from components import onboarding
from components.units import weight_input
from db import profiles, schema
from db.queries import get_setting, set_setting
from metrics.explain import (ACTIVITY_DETAILS, ACTIVITY_LEVEL, DEFAULT_ACTIVITY, DEFAULT_GENDER,
                             GENDER_LABELS, RIDER_TYPES, starting_ftp_range)
from metrics.units import DISTANCE_UNITS, UNITS
from metrics.training_load import HISTORY_ASK, apply_current_ctl, history_days, history_note

OPEN_KEY = "adding_athlete"
# The intake response the form was filled from, its answers shaped for the widgets, and a count
# that changes every widget key on each fill, so the fields start fresh from the new answers.
INTAKE_KEY, PREFILL_KEY, ROUND_KEY = "af_intake", "af_prefill", "af_round"

FTP_CHOICES = {
    "I know their FTP": "known",
    "I know their FTP, and put a test in their first block": "known_test",
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
    for key in (OPEN_KEY, INTAKE_KEY, PREFILL_KEY, ROUND_KEY):
        st.session_state.pop(key, None)


def is_open() -> bool:
    return bool(st.session_state.get(OPEN_KEY))


def save_athlete(answers: dict, fit_files=None, intake: intake_import.Intake | None = None) -> dict:
    """Create the athlete's profile and fill it in. Settings and FTP go in first, so ride files
    imported afterwards are scored on their FTP and heart rates. The starting fitness seed stays and
    fades out as the rides build fitness. An intake form response is kept whole for the coach.
    Returns the new profile plus {imported, message, history_days}."""
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
        if intake:
            set_setting(intake_import.SETTING, intake_import.to_setting(intake))
        planning.save_target_plan(answers.get("plan_start"), answers.get("plan_weeks"))
        imported, message = 0, ""
        if fit_files:
            from auth.fit_import import import_ride_files
            imported, message = import_ride_files(fit_files)
        apply_current_ctl(answers.get("current_ctl"))         # after the rides, which it accounts for
        days = history_days() if imported else 0
    return {**p, "imported": imported, "message": message, "history_days": days}


def _rides_note(result: dict) -> str:
    if not result["imported"]:
        return result["message"]
    note = result["message"]
    if (more := history_note(result.get("history_days", 0))):
        note += " " + more
    return note


def _within(v, lo, hi):
    """A prefilled number only when the widget can show it, so a hand edited sheet can't break the form."""
    return v if v is not None and lo <= v <= hi else None


def prefill(intake: intake_import.Intake) -> None:
    """Fill the form from an intake response. Run as a button callback, before the widgets draw."""
    a = intake.answers
    labels = {v: k for k, v in FTP_CHOICES.items()}
    st.session_state[INTAKE_KEY] = intake
    st.session_state[PREFILL_KEY] = {
        **a,
        "gender_label": intake.extras.get("gender") if intake.extras.get("gender") in GENDER_LABELS else None,
        "ftp_label": labels.get(a["ftp_choice"]) or labels["known" if a["ftp_input"] else "test"],
        "age": _within(a["age"], 12, 95),
        "weekly_hours": _within(a["weekly_hours"], 1, 20),
        "ftp_input": _within(a["ftp_input"], 50, 600),
        "current_ctl": _within(a["current_ctl"], 0, 200),
        "lthr_input": _within(a["lthr_input"], 0, 220),
        "max_hr": _within(a["max_hr"], 0, 230),
        "resting_hr": _within(a["resting_hr"], 0, 120),
    }
    st.session_state[ROUND_KEY] = st.session_state.get(ROUND_KEY, 0) + 1


def _render_intake_import() -> None:
    intake = st.session_state.get(INTAKE_KEY)
    with st.expander("Fill in from the intake form", expanded=intake is None,
                     icon=":material/assignment:"):
        st.caption("In the response sheet choose File, Download, Comma separated values, then drop "
                   "the file here. You can check and change everything before adding them.")
        sheet = st.file_uploader("Response sheet", type=["csv"], key="af_intake_csv",
                                 label_visibility="collapsed")
        if sheet:
            try:
                responses = intake_import.read_responses(sheet.getvalue())
            except ValueError as e:
                st.error(str(e))
                responses = []
            if responses:
                pick = st.selectbox("Who", range(len(responses)), key="af_intake_pick",
                                    format_func=lambda i: f"{responses[i].name}, sent {responses[i].submitted}")
                st.button("Fill in their answers", key="af_intake_fill", on_click=prefill,
                          args=(responses[pick],), icon=":material/edit_note:")
    if intake:
        _render_intake_review(intake)


def _render_intake_review(intake: intake_import.Intake) -> None:
    """What Sam should read before adding them: health first, then what the import changed."""
    st.success(f"Filled in from {intake.name}'s intake form. Check the answers below, then add them.")
    if intake.flags:
        st.warning("**Health answers to read first**\n\n" + "\n".join(f"- {f}" for f in intake.flags),
                   icon=":material/health_and_safety:")
    taken = {p["name"].strip().lower() for p in profiles.list_profiles()}
    if intake.name.strip().lower() in taken:
        st.warning(f"There is already a profile called {intake.name}. Adding them again makes a second one.")
    if intake.notes:
        st.info("\n".join(f"- {n}" for n in intake.notes))
    if (share := intake.extras.get("ride_share")):
        st.caption(f'Ride history. They said "{share}".')
    shown = set(intake.answers) | {"units", "plan_end", "ftp_test", "ride_share", "consent"}
    others = [(q.title, intake.extras[q.key]) for q in intake_import.QUESTIONS
              if q.key in intake.extras and q.key not in shown]
    if others:
        with st.expander("Their other answers"):
            st.caption("Saved with their profile for the coach to plan from.")
            for title, answer in others:
                st.markdown(f"**{title}**  \n{answer}")


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
        _render_intake_import()
        pre = st.session_state.get(PREFILL_KEY) or {}
        n = st.session_state.get(ROUND_KEY, 0)

        def k(name: str) -> str:
            return f"af_{name}_{n}" if n else f"af_{name}"

        # Plain widgets rather than a form, so the weight box converts when the unit changes and the
        # FTP options show their own fields. The unit switches here don't save, since the profile
        # you are on now isn't the one being made.
        u1, u2 = st.columns(2)
        saved_unit = pre.get("unit") or get_setting("weight_unit", "") or "lb"
        unit = u1.segmented_control("Weight units", list(UNITS), key=k("unit"),
                                    default=saved_unit if saved_unit in UNITS else "lb") or "lb"
        saved_dist = pre.get("dist_unit") or get_setting("distance_unit", "") or "mi"
        dist_unit = u2.segmented_control("Distance units", list(DISTANCE_UNITS), key=k("distance"),
                                         default=saved_dist if saved_dist in DISTANCE_UNITS else "mi") or "mi"

        name = st.text_input("Their name", value=pre.get("name", ""), placeholder="e.g. Alex", key=k("name"))
        goal_text = st.text_area(
            "Their goals", value=pre.get("goal_text", ""), key=k("goals"), height=100,
            placeholder="In their words or yours, a sentence or two is plenty.",
            help="The coach plans around what you write here.")
        st.caption("For example " + ", ".join(onboarding.GOAL_EXAMPLES).lower() + ".")

        rider_types = list(RIDER_TYPES)
        rider_type = st.radio(
            "Which best describes them?", rider_types, key=k("rider_type"),
            index=rider_types.index(pre["rider_type"]) if pre.get("rider_type") in RIDER_TYPES else 0,
            captions=[v["detail"] for v in RIDER_TYPES.values()],
            help="Sets their starting fitness and a typical power range if you don't know their FTP.")
        levels = list(ACTIVITY_LEVEL)
        activity = st.radio(
            "How active are they right now?", levels, key=k("activity"),
            index=levels.index(pre["activity"] if pre.get("activity") in ACTIVITY_LEVEL else DEFAULT_ACTIVITY),
            captions=[ACTIVITY_DETAILS[a] for a in ACTIVITY_LEVEL])

        g_col, a_col = st.columns(2)
        genders = list(GENDER_LABELS)
        gender_label = g_col.selectbox("Gender", genders, placeholder="Optional", key=k("gender"),
                                       index=genders.index(pre["gender_label"]) if pre.get("gender_label") else None,
                                       help="Used only to pick typical power ranges.")
        gender = GENDER_LABELS.get(gender_label, DEFAULT_GENDER)
        age = a_col.number_input("Age", min_value=12, max_value=95, value=pre.get("age"), step=1,
                                 placeholder="Optional", key=k("age"))

        weight = weight_input("Weight", pre.get("weight") or 70.0, key=k("weight"), unit=unit,
                              min_kg=30.0, max_kg=200.0)
        weekly_hours = st.slider("Hours a week they can train", min_value=1, max_value=20,
                                 value=pre.get("weekly_hours") or 6, key=k("hours"))
        available_days = st.multiselect(
            "Days they can ride", list(planning.WEEKDAYS), default=pre.get("available_days") or DEFAULT_DAYS,
            key=k("days"), placeholder="Any day",
            help="Generated blocks and the coach put rides only on these days, with the long ride on a "
                 "weekend day when one is picked. Leave empty for any four days.")

        st.markdown("**Their FTP**")
        ftp_labels = list(FTP_CHOICES)
        ftp_label = st.radio("FTP", ftp_labels, key=k("ftp_choice"), label_visibility="collapsed",
                             index=ftp_labels.index(pre["ftp_label"]) if pre.get("ftp_label") else 0)
        ftp_choice = FTP_CHOICES[ftp_label]
        start = starting_ftp_range(weight, rider_type, activity, gender, age)
        ftp_in = None
        if ftp_choice in ("known", "known_test"):
            ftp_in = st.number_input("FTP in watts", min_value=50, max_value=600,
                                     value=pre.get("ftp_input") or 200, step=5, key=k("ftp"))
            if ftp_choice == "known_test":
                st.caption("They start on this FTP, and the test checks it.")
        else:
            st.caption(f"Riders like them usually start between {start['low']:.0f} and {start['high']:.0f} "
                       f"watts. They will start at {start['start']:.0f} W, refined from their rides"
                       + (" and the test." if ftp_choice == "test" else "."))

        ctl_in = st.number_input(
            "Current fitness, CTL (optional)", min_value=0, max_value=200, value=pre.get("current_ctl"),
            step=1, placeholder="From their experience", key=k("ctl"),
            help="Called Fitness in TrainingPeaks and intervals.icu. Not the Fitness number in Strava, which uses its own scale. Leave blank to start from their experience.")

        st.markdown("**Heart rate**")
        h1, h2, h3 = st.columns(3)
        lthr_in = h1.number_input("Threshold HR", min_value=0, max_value=220, value=pre.get("lthr_input"),
                                  step=1, placeholder="Estimate", key=k("lthr"),
                                  help="The heart rate they can hold for about an hour. Estimated if blank.")
        max_hr = h2.number_input("Max HR", min_value=0, max_value=230, value=pre.get("max_hr"), step=1,
                                 placeholder="From rides", key=k("max_hr"),
                                 help="Leave blank to use the highest heart rate their rides reach.")
        resting_hr = h3.number_input("Resting HR", min_value=0, max_value=120, value=pre.get("resting_hr"),
                                     step=1, placeholder="Optional", key=k("rest_hr"))

        st.markdown("**Goal race (optional)**")
        r1, r2 = st.columns([3, 2])
        race_name = r1.text_input("Race name", value=pre.get("race_name", ""),
                                  placeholder="e.g. OBRA Road Race #3", key=k("race_name"))
        race_date = r2.date_input("Race date", value=pre.get("race_date"), min_value=date.today(),
                                  key=k("race_date"))

        st.markdown("**Their training plan**")
        p1, p2 = st.columns([3, 2])
        plan_start = p1.date_input("Plan start date", value=pre.get("plan_start") or planning.next_monday(),
                                   min_value=date.today(), key=k("plan_start"),
                                   help="The day their first plan week starts. A Monday keeps the weeks lined up.")
        plan_weeks = p2.number_input("Plan length (weeks)", min_value=planning.PLAN_WEEKS_MIN,
                                     max_value=planning.PLAN_WEEKS_MAX,
                                     value=pre.get("plan_weeks") or planning.PLAN_WEEKS_DEFAULT,
                                     step=1, key=k("plan_weeks"))
        if plan_start and plan_weeks:
            span = planning.plan_span_text(plan_start, int(plan_weeks))
            if race_date:
                to_race = (race_date - plan_start).days / 7
                span += (f". The race is {to_race:.0f} weeks after the start" if to_race >= 1
                         else ". The race is before the plan starts")
            st.caption(span + ".")

        st.markdown("**Their rides (optional)**")
        st.caption(HISTORY_ASK)
        fit_files = st.file_uploader(
            "Ride files", type=RIDE_FILE_TYPES, accept_multiple_files=True, key="af_fit",
            label_visibility="collapsed",
            help=RIDE_FILE_HELP + " From a zip, only rides from the last year come in. "
                 "You can add more later in Settings.")

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
                    "max_hr": max_hr, "resting_hr": resting_hr, "current_ctl": ctl_in,
                    "plan_start": plan_start, "plan_weeks": plan_weeks,
                    "race_name": race_name, "race_date": race_date,
                }, fit_files, st.session_state.get(INTAKE_KEY))
            from components import profile_switcher
            profile_switcher.switch_to(result["slug"])      # also closes this form
            st.session_state["onboarding_just_finished"] = ["coached"]
            st.session_state["athlete_rides_note"] = _rides_note(result) if fit_files else ""
            st.rerun()
