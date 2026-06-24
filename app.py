from __future__ import annotations
import streamlit as st
from db.schema import run_migrations
from config import is_setup_complete
from components import inject_styles
from components.onboarding import is_onboarding_complete, render_onboarding

st.set_page_config(
    page_title="Cycling Coach",
    page_icon="🚴",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_styles()
run_migrations()


def render_setup_needed():
    st.markdown("""
    <div style="max-width:600px; margin: 60px auto; text-align:center;">
        <div style="font-size:3rem;">🚴</div>
        <h1 style="color:#0066CC; margin-bottom:8px;">Cycling Coach</h1>
        <p style="color:#6B7280; font-size:1.1rem; margin-bottom:32px;">
            Training load · Race prep · Strength · AI coaching
        </p>
    </div>
    """, unsafe_allow_html=True)

    st.warning("**Setup needed** — your API keys aren't configured yet.")
    with st.expander("Quick Setup (one time only)", expanded=True):
        st.markdown("""
**Step 1 — Copy the config file** — in Terminal:
```
cp ~/cycling-coach/.env.example ~/cycling-coach/.env
```

**Step 2 — Fill in your API keys** — open `~/cycling-coach/.env` in TextEdit:

| Key | Where to get it |
|-----|-----------------|
| `STRAVA_CLIENT_ID` + `STRAVA_CLIENT_SECRET` | [strava.com/settings/api](https://www.strava.com/settings/api) — set callback domain to `localhost` |
| `GARMIN_EMAIL` + `GARMIN_PASSWORD` | Your Garmin Connect login |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |

**Step 3 — Restart the app:**
```
bash ~/cycling-coach/start.sh
```
        """)


if not is_setup_complete():
    pg = st.navigation([st.Page(render_setup_needed, title="Setup", icon="🚴")])
elif not is_onboarding_complete():
    pg = st.navigation([st.Page(render_onboarding, title="Welcome", icon="🚴")])
else:
    pg = st.navigation([
        st.Page("pages/01_Dashboard.py",        title="Dashboard",    icon="📊"),
        st.Page("pages/02_Training_Planner.py", title="Training",     icon="🗓️"),
        st.Page("pages/03_Race_Prep.py",        title="Race Prep",    icon="🏁"),
        st.Page("pages/04_Strength_Training.py",title="Strength",     icon="💪"),
        st.Page("pages/05_AI_Coach.py",         title="AI Coach",     icon="🤖"),
        st.Page("pages/06_Competitors.py",      title="Competitors",  icon="🔍"),
        st.Page("pages/07_Settings.py",         title="Settings",     icon="⚙️"),
    ])
pg.run()
