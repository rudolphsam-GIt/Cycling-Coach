"""
Getting started checklist for riders new to structured training. It shows on the
Today page, ticks itself off from the rider's data, and can be dismissed.
"""
from __future__ import annotations

from datetime import date

import streamlit as st

from components.onboarding import NEW_RIDER, first_block_button
from db.queries import get_activities, get_setting, get_workouts, set_setting
from metrics import explain

SHOWN_FOR = (NEW_RIDER, "Some structured training experience")
PAGE_SETTINGS = "pages/07_Settings.py"


def current_state() -> dict:
    """What the checklist needs to know, read from the app's data."""
    import auth.garmin as garmin_auth
    import auth.strava as strava_auth

    rides = get_activities(days_back=3650)
    workouts = get_workouts("0001-01-01", "9999-12-31")
    first_plan = min((w["date"] for w in workouts), default=None)
    since = [a for a in rides if first_plan and first_plan <= a["date"] <= date.today().isoformat()]
    return {
        "connected": garmin_auth.is_connected() or strava_auth.is_connected(),
        "ftp_confirmed": get_setting("ftp_estimated", "") == "0",
        "rides": len(rides), "workouts": len(workouts), "rides_since_plan": len(since),
    }


def _dismiss() -> None:
    set_setting("checklist_dismissed", "1")


def _go_settings() -> None:
    st.switch_page(PAGE_SETTINGS)


def render() -> None:
    """Draw the checklist when it applies. Nothing for experienced riders or once dismissed."""
    if get_setting("checklist_dismissed", "") == "1":
        return
    if get_setting("experience_level", "") not in SHOWN_FOR:
        return
    steps = explain.checklist(current_state())
    done = sum(s["done"] for s in steps)
    with st.container(border=True):
        head, close = st.columns([5, 2], vertical_alignment="center")
        head.markdown(f"**Getting started** · {done} of {len(steps)} done")
        close.button("Dismiss", key="checklist_dismiss", on_click=_dismiss, width="stretch",
                     icon=":material/close:")
        st.progress(done / len(steps))
        for step in steps:
            line, action = st.columns([5, 3], vertical_alignment="center")
            mark = ":material/check_circle:" if step["done"] else ":material/radio_button_unchecked:"
            line.markdown(f"{mark} **{step['title']}**  \n{step['why']}")
            if step["done"]:
                continue
            with action:
                if step["key"] in ("connect", "ftp", "rides"):
                    if st.button("Open Settings", key=f"check_{step['key']}", width="stretch"):
                        _go_settings()
                elif step["key"] == "block":
                    first_block_button("check_first_block")
        if done == len(steps):
            st.success("You have done the basics. Keep riding, and use the Dashboard to watch your fitness build.")
