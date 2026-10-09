from __future__ import annotations
from pathlib import Path

import streamlit as st
from db.schema import run_migrations
from config import is_setup_complete
from components import inject_styles
from components.onboarding import is_onboarding_complete, render_onboarding

st.set_page_config(
    page_icon="assets/icon.svg",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_styles()


@st.cache_resource
def _migrate_once():
    # Schema setup only needs to run once per server process, not every rerun.
    run_migrations()
    return True


_migrate_once()


def render_setup_needed():
    app_dir = Path(__file__).parent
    st.markdown(
        '<div class="hero">'
        '<div class="hero-eyebrow">Setup</div>'
        '<div class="hero-title">Cycling Coach</div>'
        '<div class="hero-sub">Training load, race prep, strength and AI coaching.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    col_l, col_main, col_r = st.columns([1, 3, 1])
    with col_main:
        st.warning(
            "**One thing is needed to open the app.** Add your Anthropic API key. "
            "Garmin and Strava are connected afterwards from Settings.",
            icon=":material/key:",
        )
        st.markdown("**Step 1.** Copy the example config file. In Terminal, run")
        st.code(f'cp "{app_dir / ".env.example"}" "{app_dir / ".env"}"', language="bash")
        st.markdown(
            "**Step 2.** Open `.env` in a text editor and set your key, which you can "
            "create at [console.anthropic.com](https://console.anthropic.com)."
        )
        st.code(f'open -e "{app_dir / ".env"}"', language="bash")
        st.code("ANTHROPIC_API_KEY=your_key_here", language="bash")
        st.markdown("**Step 3.** Restart the app.")
        st.code(f'bash "{app_dir / "start.sh"}"', language="bash")
        st.caption(
            "Strava keys in `.env` are optional. If you want Strava, "
            "`STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` come from "
            "strava.com/settings/api, with the callback domain set to `localhost`."
        )


if not is_setup_complete():
    pg = st.navigation([st.Page(render_setup_needed, title="Setup", icon=":material/directions_bike:")])
elif not is_onboarding_complete():
    pg = st.navigation([st.Page(render_onboarding, title="Welcome", icon=":material/directions_bike:")])
else:
    st.logo("assets/logo.svg", size="large", icon_image="assets/icon.svg")
    pg = st.navigation({
        "Train": [
            st.Page("pages/01_Dashboard.py", title="Today", icon=":material/today:",
                    url_path="today", default=True),
            st.Page("pages/02_Training_Planner.py", title="Plan", icon=":material/calendar_month:",
                    url_path="plan"),
            st.Page("pages/05_Dashboard_Charts.py", title="Progress", icon=":material/monitoring:",
                    url_path="progress"),
            st.Page("pages/04_Strength_Training.py", title="Strength",
                    icon=":material/fitness_center:", url_path="strength"),
        ],
        "Race": [
            st.Page("pages/03_Race_Prep.py", title="Races", icon=":material/flag:",
                    url_path="races"),
            st.Page("pages/06_Competitors.py", title="Competitors", icon=":material/groups:",
                    url_path="competitors"),
        ],
        "Account": [
            st.Page("pages/07_Settings.py", title="Settings", icon=":material/settings:",
                    url_path="settings"),
        ],
    })
if is_setup_complete() and is_onboarding_complete() and not st.session_state.get("auto_synced"):
    # Pull new rides and recovery from Garmin once per visit, if it's been a few hours.
    st.session_state["auto_synced"] = True
    import auth.garmin as garmin_auth
    if garmin_auth.needs_auto_sync():
        with st.spinner("Syncing new rides from Garmin…"):
            result = garmin_auth.auto_sync()
        if result:
            st.toast(result[1])

if is_setup_complete() and is_onboarding_complete():
    # Keep the TrainingPeaks calendar in step with the plan, in the background.
    import auth.trainingpeaks as tp
    if tp.is_enabled():
        if tp.sync_due() and not tp.is_syncing():
            tp.start_background_sync()
        res = tp.last_result()
        when = res[1] if res else ""
        if "tp_result_seen" not in st.session_state:
            st.session_state["tp_result_seen"] = when      # don't repeat an old result on arrival
        elif res and st.session_state["tp_result_seen"] != when:
            st.toast(res[2], icon=":material/event_upcoming:" if res[0] == "ok" else ":material/warning:")
            st.session_state["tp_result_seen"] = when
    # Read intervals.icu's scores now and then, to check the app's against.
    import auth.intervals as intervals_auth
    if intervals_auth.compare_due():
        intervals_auth.start_background_compare()

pg.run()
