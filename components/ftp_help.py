"""
Help for riders who don't know their FTP: say when it is only an estimate,
suggest a value from their best 20 minutes, or add a guided 20 minute test to
the plan. Nothing changes until the rider presses a button.
"""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from components import coach_ui
from db.queries import (add_workout, get_activities, get_peaks_between, get_setting,
                        get_workouts, log_ftp_history, set_setting)
from metrics import explain

SUGGEST_DIFF_W = 3   # don't suggest a change smaller than this


def _next_free_day(today: date) -> date:
    """The first day from tomorrow with nothing planned, within the next two weeks."""
    start = today + timedelta(days=1)
    busy = {w["date"] for w in get_workouts(start.isoformat(), (start + timedelta(days=14)).isoformat())}
    day = start
    while day.isoformat() in busy and day < start + timedelta(days=14):
        day += timedelta(days=1)
    return day


def plan_test_in_block(block_dates: list[str]) -> int | None:
    """Add the FTP test on the first rest day among the block's first week, or
    None if every day that week is taken. Returns the new workout's id."""
    if not block_dates:
        return None
    first = date.fromisoformat(min(block_dates))
    taken = set(block_dates)
    day = first + timedelta(days=1)          # never the very first day, ease in first
    while day < first + timedelta(days=7):
        if day.isoformat() not in taken:
            has_power = any(a.get("avg_power_watts") for a in get_activities(days_back=60))
            return add_workout({**explain.ftp_test_workout(day, has_power, gentle=_is_new_rider()),
                                "structured_json": None, "notes": "", "phase": None})
        day += timedelta(days=1)
    return None


def _use_ftp(ftp: int) -> None:
    set_setting("ftp_watts", ftp)
    set_setting("ftp_estimated", "0")
    log_ftp_history(ftp, "From my best 20 minutes")
    st.session_state.pop("ftp_test_day", None)
    st.toast(f"FTP set to {ftp} W")


def _is_new_rider() -> bool:
    return get_setting("experience_level", "") == "New to structured training"


def _plan_test(has_power: bool) -> None:
    day = _next_free_day(date.today())
    add_workout({**explain.ftp_test_workout(day, has_power, gentle=_is_new_rider()),
                 "structured_json": None, "notes": ""})
    st.session_state["ftp_test_day"] = day.isoformat()


def render(key: str = "ftp_help") -> None:
    """The FTP help card. Draws nothing when the FTP is a tested value and no
    better suggestion exists."""
    today = date.today()
    ftp = float(get_setting("ftp_watts", 0) or 0)
    estimated = get_setting("ftp_estimated", "") == "1"
    since = (today - timedelta(days=42)).isoformat()
    suggestion = explain.suggest_ftp(get_peaks_between(since, today.isoformat()), today)
    differs = bool(suggestion) and abs(suggestion["ftp"] - ftp) >= SUGGEST_DIFF_W
    planned_day = st.session_state.get("ftp_test_day")
    if not (estimated or differs or planned_day):
        return

    has_power = any(a.get("avg_power_watts") for a in get_activities(days_back=60))
    with st.container(border=True):
        if estimated:
            st.markdown("**Your FTP is an estimate, and that is completely fine.** The app picked a starting "
                        "point from what you told it. Every zone and training stress number is based on it, "
                        "so a better value makes everything more accurate.")
            low, high = get_setting("ftp_range_low", ""), get_setting("ftp_range_high", "")
            if low and high:
                st.caption(explain.ftp_reassurance(float(low), float(high)))
        else:
            st.markdown("**Your FTP may be out of date.**")
        if differs:
            st.markdown(f"Your best 20 minutes in the last 6 weeks was {suggestion['watts']} W on "
                        f"{suggestion['date']} ({suggestion['name']}). 95% of that is "
                        f"**{suggestion['ftp']} W**, compared with {ftp:.0f} W now.")
        with st.container(horizontal=True):
            if differs:
                st.button(f"Use {suggestion['ftp']} W", key=f"{key}_use", type="primary",
                          icon=":material/check:", on_click=_use_ftp, args=(suggestion["ftp"],))
            st.button("Plan an FTP test", key=f"{key}_test", icon=":material/event:",
                      on_click=_plan_test, args=(has_power,),
                      help="Adds a guided 20 minute test on your next free day")
        if planned_day:
            st.success(f"A 20 minute FTP test is on your plan for {date.fromisoformat(planned_day):%A %b %-d}.")
            if st.button("View on calendar", key=f"{key}_view", icon=":material/calendar_month:"):
                coach_ui.jump_to_calendar(planned_day)
