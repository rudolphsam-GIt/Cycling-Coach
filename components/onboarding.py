from __future__ import annotations

import streamlit as st
from datetime import date

from db.queries import set_setting, log_ftp_history, add_race

GOALS = {
    "Get faster (speed & power)": "speed",
    "Build endurance": "endurance",
    "Lose weight": "weight_loss",
    "Train for a specific race": "race",
    "Get back into shape / general fitness": "general_fitness",
}

EXPERIENCE = {
    "New to structured training": {"w_per_kg": 2.2, "ctl_start": 25, "lthr_default": 158},
    "Some structured training experience": {"w_per_kg": 2.8, "ctl_start": 45, "lthr_default": 165},
    "Experienced racer": {"w_per_kg": 3.4, "ctl_start": 65, "lthr_default": 172},
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
        with st.form("onboarding_form"):
            name = st.text_input("What's your name?", placeholder="e.g. Sam")

            goal_text = st.text_area(
                "What are your goals?",
                placeholder="Write it however you like, a sentence or two is plenty.",
                height=100,
                help="Anything you want from riding, big or small. Your coach plans around what you write.",
            )
            st.caption("Ideas to get you thinking: " + ", ".join(GOAL_EXAMPLES) + ".")

            experience_label = st.radio(
                "How would you describe your training experience?",
                list(EXPERIENCE.keys()),
                help="Sets your starting numbers and how much the app and your coach explain. "
                     "Choose the first one if you have never followed a structured plan.",
            )

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

            weight = st.number_input(
                "Weight (kg)", min_value=30.0, max_value=200.0, value=70.0, step=0.5,
            )

            know_ftp = st.checkbox("I know my FTP (functional threshold power)")
            ftp_input = None
            if know_ftp:
                ftp_input = st.number_input("FTP (watts)", min_value=50, max_value=600, value=200, step=5)

            know_lthr = st.checkbox("I know my LTHR (lactate threshold heart rate)")
            lthr_input = None
            if know_lthr:
                lthr_input = st.number_input("LTHR (bpm)", min_value=100, max_value=210, value=160, step=1)

            st.caption("Don't know FTP or LTHR yet? No problem, we'll estimate a starting point and refine it as you train.")

            has_race = st.checkbox("I have a specific race I'm training for")
            race_name = race_date = None
            if has_race:
                race_name = st.text_input("Race name", placeholder="e.g. OBRA Road Race #3")
                race_date = st.date_input("Race date", value=date.today())

            submitted = st.form_submit_button("Get Started", type="primary", width="stretch")

        if submitted and not goal_text.strip():
            st.error("Tell us a little about your goals before continuing. A sentence is plenty.")

        if submitted and goal_text.strip():
            exp = EXPERIENCE[experience_label]
            goal_key_list = infer_goal_keys(goal_text)
            goal_keys_str = ",".join(goal_key_list)

            final_ftp = ftp_input if ftp_input else round(weight * exp["w_per_kg"])
            final_lthr = lthr_input if lthr_input else exp["lthr_default"]

            set_setting("athlete_name", name or "")
            set_setting("primary_goal", goal_keys_str)
            set_setting("goal_text", goal_text.strip())
            set_setting("days_per_week", days_per_week)
            set_setting("experience_level", experience_label)
            set_setting("weekly_hours_target", weekly_hours)
            set_setting("weight_kg", weight)
            set_setting("ftp_watts", final_ftp)
            set_setting("lthr", final_lthr)
            set_setting("ctl_start", exp["ctl_start"])
            set_setting("ftp_estimated", "0" if ftp_input else "1")
            set_setting("lthr_estimated", "0" if lthr_input else "1")
            log_ftp_history(final_ftp, notes="Initial estimate from onboarding" if not ftp_input else "")

            if has_race and race_name and race_date:
                add_race({
                    "name": race_name, "date": race_date.isoformat(),
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
    first_block_button("welcome_first_block")
