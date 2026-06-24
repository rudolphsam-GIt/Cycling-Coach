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
    "weight_loss": "We'll focus on consistent, sustainable training volume — not extremes.",
    "race": "We'll build toward your race using the Periodization Wizard in Training.",
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


def render_onboarding():
    st.markdown("""
    <div style="max-width:600px; margin: 40px auto 24px; text-align:center;">
        <div style="font-size:2.5rem;">🚴</div>
        <h1 style="color:#4D9FFF; margin-bottom:4px;">Welcome to Cycling Coach</h1>
        <p style="color:#94A3B8;">Quick questions so your coach knows where to start.</p>
    </div>
    """, unsafe_allow_html=True)

    col_l, col_form, col_r = st.columns([1, 2, 1])
    with col_form:
        with st.form("onboarding_form"):
            name = st.text_input("What's your name?", placeholder="e.g. Sam")

            goal_labels = st.multiselect(
                "What are your main goals right now? (pick one or more)",
                list(GOALS.keys()),
                default=[list(GOALS.keys())[0]],
            )

            experience_label = st.radio(
                "How would you describe your training experience?",
                list(EXPERIENCE.keys()),
            )

            weekly_hours = st.slider(
                "How many hours per week can you realistically train?",
                min_value=1, max_value=20, value=6,
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

            st.caption("Don't know FTP or LTHR yet? No problem — we'll estimate a starting point and refine it as you train.")

            has_race = st.checkbox("I have a specific race I'm training for")
            race_name = race_date = None
            if has_race:
                race_name = st.text_input("Race name", placeholder="e.g. OBRA Road Race #3")
                race_date = st.date_input("Race date", value=date.today())

            submitted = st.form_submit_button("Get Started", type="primary", use_container_width=True)

        if submitted and not goal_labels:
            st.error("Pick at least one goal before continuing.")

        if submitted and goal_labels:
            exp = EXPERIENCE[experience_label]
            goal_key_list = [GOALS[g] for g in goal_labels]
            goal_keys_str = ",".join(goal_key_list)

            final_ftp = ftp_input if ftp_input else round(weight * exp["w_per_kg"])
            final_lthr = lthr_input if lthr_input else exp["lthr_default"]

            set_setting("athlete_name", name or "")
            set_setting("primary_goal", goal_keys_str)
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


def render_onboarding_welcome_banner():
    """Shown once on the Dashboard right after onboarding completes."""
    goal_key_list = st.session_state.pop("onboarding_just_finished", None)
    if not goal_key_list:
        return
    blurbs = [GOAL_BLURB[k] for k in goal_key_list if k in GOAL_BLURB]
    blurb_str = " ".join(blurbs)
    st.success(f"You're all set! {blurb_str} Head to **Settings** anytime to refine your FTP, LTHR, or goals.")
