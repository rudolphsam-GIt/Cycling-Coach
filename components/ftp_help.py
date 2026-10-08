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


SNOOZE_DAYS = 14
SNOOZE_KEY = "ftp_help_snoozed_until"


def _snooze() -> None:
    set_setting(SNOOZE_KEY, (date.today() + timedelta(days=SNOOZE_DAYS)).isoformat())
    st.session_state.pop("ftp_test_day", None)
    st.toast(f"Okay, we'll leave your FTP alone for {SNOOZE_DAYS} days.")


def _is_snoozed() -> bool:
    until = get_setting(SNOOZE_KEY, "")
    return bool(until) and date.today().isoformat() <= until


def _save_manual(key: str) -> None:
    ftp = st.session_state.get(f"{key}_manual")
    if not ftp:
        return
    set_setting("ftp_watts", int(ftp))
    set_setting("ftp_estimated", "0")
    set_setting(SNOOZE_KEY, "")
    log_ftp_history(int(ftp), "Entered manually")
    st.session_state.pop("ftp_test_day", None)
    st.toast(f"FTP set to {int(ftp)} W")


def render(key: str = "ftp_help", *, snoozable: bool = True, show_lower: bool = False) -> None:
    """The FTP help card. Draws nothing when the FTP is a tested value and nothing better is on
    offer, or when the rider chose Not now (on pages with `snoozable`).

    A suggestion from recent rides is only offered when it would raise FTP, unless
    `show_lower` is set (Settings). A lower number from the last six weeks usually just means no
    all out effort lately, not that the FTP is wrong, so it is not worth a nag on Today."""
    today = date.today()
    ftp = float(get_setting("ftp_watts", 0) or 0)
    estimated = get_setting("ftp_estimated", "") == "1"
    since = (today - timedelta(days=42)).isoformat()
    suggestion = explain.suggest_ftp(get_peaks_between(since, today.isoformat()), today)
    higher = bool(suggestion) and suggestion["ftp"] >= ftp + SUGGEST_DIFF_W
    lower = bool(suggestion) and suggestion["ftp"] <= ftp - SUGGEST_DIFF_W
    differs = higher or (lower and show_lower)
    planned_day = st.session_state.get("ftp_test_day")
    if snoozable and _is_snoozed() and not planned_day:
        return
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
        elif higher:
            st.markdown("**Your recent rides point to a higher FTP.**")
        elif lower:
            st.markdown("**Your last six weeks don't show your FTP.**")
        if differs:
            st.markdown(f"Your best 20 minutes in the last 6 weeks was {suggestion['watts']} W on "
                        f"{suggestion['date']} ({suggestion['name']}). 95% of that is "
                        f"**{suggestion['ftp']} W**, compared with {ftp:.0f} W now.")
            if lower:
                st.caption("That is normal if you haven't done an all out effort lately. Keep your current "
                           "FTP unless you think it is too high.")
        with st.container(horizontal=True):
            if differs:
                st.button(f"Use {suggestion['ftp']} W", key=f"{key}_use", type="primary",
                          icon=":material/check:", on_click=_use_ftp, args=(suggestion["ftp"],))
            st.button("Plan an FTP test", key=f"{key}_test", icon=":material/event:",
                      on_click=_plan_test, args=(has_power,),
                      help="Adds a guided 20 minute test on your next free day")
            with st.popover("Enter it myself", icon=":material/edit:"):
                st.number_input("FTP in watts", min_value=50, max_value=600, value=int(ftp) or 200, step=5,
                                key=f"{key}_manual")
                st.button("Save FTP", key=f"{key}_save", type="primary", icon=":material/save:",
                          on_click=_save_manual, args=(key,))
            if snoozable:
                st.button("Not now", key=f"{key}_snooze", icon=":material/schedule:", on_click=_snooze,
                          help=f"Hide this for {SNOOZE_DAYS} days")
        if planned_day:
            st.success(f"A 20 minute FTP test is on your plan for {date.fromisoformat(planned_day):%A %b %-d}.")
            if st.button("View on calendar", key=f"{key}_view", icon=":material/calendar_month:"):
                coach_ui.jump_to_calendar(planned_day)
