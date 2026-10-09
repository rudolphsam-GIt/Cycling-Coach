from __future__ import annotations

import streamlit as st
from datetime import date

from components.units import distance_switch, unit_switch, weight_input
import ftp_change
from db.queries import set_setting, add_race
from metrics.explain import (ACTIVITY_DETAILS, ACTIVITY_LEVEL, DEFAULT_ACTIVITY, RIDER_TYPES,
                             GENDER_LABELS, GENDER_PROFILE_TABLE, DEFAULT_GENDER, experience_for, ftp_reassurance,
                             lthr_from_age, starting_ftp_range)

GOALS = {
    "Get faster (speed & power)": "speed",
    "Build endurance": "endurance",
    "Lose weight": "weight_loss",
    "Train for a specific race": "race",
    "Get back into shape / general fitness": "general_fitness",
}

EXPERIENCE = {
    "New to structured training": {"ctl_start": 25, "lthr_default": 158},
    "Some structured training experience": {"ctl_start": 45, "lthr_default": 165},
    "Experienced racer": {"ctl_start": 65, "lthr_default": 172},
}

GOAL_BLURB = {
    "speed": "We'll lean on threshold and VO2max work, and track your FTP closely.",
    "endurance": "We'll prioritize long Z2 rides and steadily build your weekly volume.",
    "weight_loss": "We'll focus on consistent, sustainable training volume, not extremes.",
    "race": "We'll build toward your race with your coach on the Plan page.",
    "general_fitness": "We'll keep things low-pressure and ramp your fitness gradually.",
}


def is_onboarding_complete() -> bool:
    from db.queries import get_setting
    return bool(get_setting("onboarding_complete", ""))


def parse_goal_keys(raw: str) -> list[str]:
    return [g for g in (raw or "").split(",") if g]


def goal_keys_to_labels(keys: list[str]) -> list[str]:
    rev = {v: k for k, v in GOALS.items()}
    return [rev[k] for k in keys if k in rev]


FTP_CHOICES = {
    "I know it": "known",
    "I don't know it, but I'm happy to do a test": "test",
    "I don't know it and would rather not test, so please estimate it for me": "estimate",
}

GOAL_EXAMPLES = [
    "Ride my first 100 mile day",
    "Get faster for road races next spring",
    "Lose 10 pounds and feel stronger",
    "Keep up with my Saturday group ride",
    "Finish a gran fondo with friends",
]

_KEYWORDS = {
    "race": ("race", "racing", "crit", "criterium", "cat 3", "cat 4", "cat 5", "time trial", "omnium"),
    "speed": ("faster", "speed", "power", "ftp", "stronger", "climb", "keep up", "sprint"),
    "endurance": ("endurance", "century", "100 mile", "gran fondo", "granfondo", "long ride", "distance",
                  "finish", "centuries", "stamina"),
    "weight_loss": ("weight", "lose", "pounds", "lbs", "kilos", "slim", "fat"),
}


def infer_goal_keys(text: str) -> list[str]:
    """Rough goal categories from a rider's own words, so the coach's built in
    guidance still applies. The words themselves are always sent to the coach too."""
    t = (text or "").lower()
    keys = [k for k, words in _KEYWORDS.items() if any(w in t for w in words)]
    return keys or ["general_fitness"]


def render_onboarding():
    st.markdown(
        '<div class="hero">'
        '<div class="hero-eyebrow">Cycling Coach</div>'
        '<div class="hero-title">Welcome to Cycling Coach</div>'
        '<div class="hero-sub">A few quick questions so your coach knows where to start.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    col_l, col_form, col_r = st.columns([1, 2, 1])
    with col_form:
        # Plain widgets rather than a form, so the weight box converts when the unit changes
        # and the FTP options can show their own fields and the starting range as they answer.
        u1, u2 = st.columns(2)
        with u1:
            unit = unit_switch("onb_unit", default="lb")
        with u2:
            dist_unit = distance_switch("onb_distance", default="mi")
        name = st.text_input("What's your name?", placeholder="e.g. Sam")

        goal_text = st.text_area(
            "What are your goals?",
            placeholder="Write it however you like, a sentence or two is plenty.",
            height=100,
            help="Anything you want from riding, big or small. Your coach plans around what you write.",
        )
        st.caption("Ideas to get you thinking: " + ", ".join(GOAL_EXAMPLES) + ".")

        rider_type = st.radio(
            "Which best describes you?", list(RIDER_TYPES),
            captions=[v["detail"] for v in RIDER_TYPES.values()],
            help="There are no wrong answers. This sets how much the app and your coach explain, "
                 "and gives you a friendly starting point for your power numbers.")
        experience_label = experience_for(rider_type)

        activity = st.radio(
            "How active are you right now, away from the bike or on it?", list(ACTIVITY_LEVEL),
            index=list(ACTIVITY_LEVEL).index(DEFAULT_ACTIVITY),
            captions=[ACTIVITY_DETAILS[k] for k in ACTIVITY_LEVEL],
            help="Think about a typical week over the last month or two. Count planned exercise, "
                 "not just daily movement.")

        g_col, a_col = st.columns(2)
        gender_label = g_col.selectbox(
            "Gender", list(GENDER_LABELS), index=None, placeholder="Optional",
            help="Used only to pick typical power ranges, which differ between women and men. Non-binary and "
                 "Prefer not to say use an average of the two. You can change it any time in Settings.")
        gender = GENDER_LABELS.get(gender_label, DEFAULT_GENDER)   # unanswered is treated as prefer not to say
        age = a_col.number_input(
            "Age", min_value=12, max_value=95, value=None, step=1, placeholder="Optional",
            help="Power and heart rate both change with age, so this makes your starting numbers more "
                 "accurate. You can skip it. We only keep your birth year.")

        weekly_hours = st.slider(
            "How many hours a week do you have to train?",
            min_value=1, max_value=20, value=6,
            help="Be realistic. A plan you can keep up beats an ambitious one you skip.",
        )

        days_per_week = st.slider(
            "How many days a week can you train?",
            min_value=1, max_value=7, value=4,
            help="Count the days you can ride or lift. Rest days are part of the plan, so you "
                 "do not need to pick seven.",
        )

        weight = weight_input("Weight", 70.0, key="onb_weight", unit=unit, min_kg=30.0, max_kg=200.0)

        st.markdown("**Do you know your FTP?**")
        st.caption("FTP is the most power you can hold for about an hour. Every training zone is based on it. "
                   "Most people starting out don't know theirs, and that is completely normal.")
        ftp_label = st.radio("FTP", list(FTP_CHOICES), index=1, label_visibility="collapsed")
        ftp_choice = FTP_CHOICES[ftp_label]
        start = starting_ftp_range(weight, rider_type, activity, gender, age)
        ftp_in = None
        if ftp_choice == "known":
            ftp_in = st.number_input("Your FTP in watts", min_value=50, max_value=600, value=200, step=5)
        else:
            st.info(ftp_reassurance(start["low"], start["high"], start["start"]) + (
                " We'll build a friendly FTP test into the start of your first training block, so we know "
                "where to go from there." if ftp_choice == "test" else
                " We'll use that estimate and refine it from your rides, and you can test any time."),
                icon=":material/info:")

        lthr_in = st.number_input(
            "Threshold heart rate in bpm (optional)", min_value=0, max_value=220, value=None, step=1,
            placeholder="Leave blank if you don't know it",
            help="The heart rate you can hold for about an hour of hard riding. We'll estimate it if you skip this.")

        st.markdown("**Training for a specific race? (optional)**")
        race_name = st.text_input("Race name", placeholder="e.g. OBRA Road Race #3",
                                  label_visibility="collapsed")
        race_date = st.date_input("Race date", value=None, min_value=date.today(),
                                  help="Leave blank if you are not training for a specific race.")

        submitted = st.button("Get Started", type="primary", width="stretch")

        if submitted and not goal_text.strip():
            st.error("Tell us a little about your goals before continuing. A sentence is plenty.")

        if submitted and goal_text.strip():
            exp = EXPERIENCE[experience_label]
            goal_key_list = infer_goal_keys(goal_text)
            goal_keys_str = ",".join(goal_key_list)

            ftp_input, lthr_input = ftp_in or None, lthr_in or None
            final_ftp = ftp_input if ftp_input else start["start"]
            final_lthr = lthr_input if lthr_input else (lthr_from_age(age) if age else exp["lthr_default"])

            set_setting("athlete_name", name or "")
            set_setting("primary_goal", goal_keys_str)
            set_setting("goal_text", goal_text.strip())
            set_setting("days_per_week", days_per_week)
            set_setting("experience_level", experience_label)
            set_setting("weekly_hours_target", weekly_hours)
            set_setting("weight_kg", weight)
            set_setting("weight_unit", unit)
            set_setting("distance_unit", dist_unit)
            set_setting("lthr", final_lthr)
            set_setting("ctl_start", exp["ctl_start"])
            set_setting("ftp_choice", ftp_choice)
            set_setting("ftp_estimated", "0" if ftp_input else "1")
            if age:
                set_setting("birth_year", date.today().year - int(age))
            set_setting("rider_type", rider_type)
            set_setting("gender", gender)
            if gender in GENDER_PROFILE_TABLE:
                set_setting("power_profile_table", GENDER_PROFILE_TABLE[gender])
            set_setting("activity_level", activity)
            set_setting("ftp_range_low", start["low"])
            set_setting("ftp_range_high", start["high"])
            set_setting("lthr_estimated", "0" if lthr_input else "1")
            ftp_change.apply_new_ftp(final_ftp, "Initial estimate from onboarding" if not ftp_input else "")

            if race_name.strip() and race_date:
                add_race({
                    "name": race_name.strip(), "date": race_date.isoformat(),
                    "distance_km": None, "elevation_gain_meters": None,
                    "category": None, "target_time_seconds": None,
                    "notes": "",
                })

            set_setting("onboarding_complete", "1")
            st.session_state["onboarding_just_finished"] = goal_key_list
            st.rerun()


NEW_RIDER = "New to structured training"


def _goals_for_message(get_setting) -> list[str]:
    """The rider's own words if they gave any, else the older category labels."""
    text = (get_setting("goal_text", "") or "").strip()
    if text:
        return [text]
    return goal_keys_to_labels(parse_goal_keys(get_setting("primary_goal", "")))


def build_first_block_message() -> str:
    """The first message to the coach, written from the rider's own settings."""
    from db.queries import get_races, get_setting
    from metrics.explain import first_block_message

    def num(key):
        try:
            return float(get_setting(key, 0) or 0) or None
        except (TypeError, ValueError):
            return None

    races = get_races(upcoming_only=True)
    return first_block_message(
        goals=_goals_for_message(get_setting),
        days=num("days_per_week"),
        experience=get_setting("experience_level", "") or NEW_RIDER,
        hours=num("weekly_hours_target"), ftp=num("ftp_watts"),
        ftp_estimated=get_setting("ftp_estimated", "") == "1",
        skip_test=get_setting("ftp_choice", "") == "estimate",
        race=races[0] if races else None, name=get_setting("athlete_name", "") or None)


def _go_first_block() -> None:
    from components import coach_ui
    st.session_state["pending_message"] = build_first_block_message()
    st.session_state[coach_ui.PLAN_JUMP_KEY] = "coach"
    st.switch_page(coach_ui.PLAN_PAGE)


def first_block_button(key: str) -> None:
    """Opens the coach with a first block request already written."""
    if st.button("Build my first block", key=key, type="primary", icon=":material/auto_awesome:",
                 help="Opens your coach with a request for a four week starting block, "
                      "written from your goals and hours"):
        _go_first_block()


def render_onboarding_welcome_banner():
    """Shown once on the Dashboard right after onboarding completes."""
    goal_key_list = st.session_state.pop("onboarding_just_finished", None)
    if not goal_key_list:
        return
    blurbs = [GOAL_BLURB[k] for k in goal_key_list if k in GOAL_BLURB]
    blurb_str = " ".join(blurbs)
    st.success(f"You're all set! {blurb_str} Head to **Settings** anytime to refine your FTP, LTHR, or goals.")
    from db.queries import get_setting
    if get_setting("experience_level", "") == NEW_RIDER:
        st.info("New to structured training? Look for the small help icons and the question mark "
                "tooltips next to numbers and charts. They explain what each one is, why it matters, "
                "and what your own number means. The checklist below walks you through setting up.",
                icon=":material/school:")
    if get_setting("ftp_estimated", "") == "1":
        low, high = get_setting("ftp_range_low", ""), get_setting("ftp_range_high", "")
        range_text = (ftp_reassurance(float(low), float(high), float(get_setting("ftp_watts", 0) or 0))
                      if low and high else "")
        if get_setting("ftp_choice", "") == "estimate":
            st.info(f"You asked us to estimate your FTP, and that is completely fine. {range_text} We will "
                    "refine it from your rides, and the Today page will suggest a better value once you "
                    "have a few weeks in. You can test any time you like.", icon=":material/speed:")
        else:
            st.info(f"You did not enter an FTP, and that is completely fine. {range_text} Your first training "
                    "block will start with an FTP test, so we know where to go from there.",
                    icon=":material/speed:")
    first_block_button("welcome_first_block")
