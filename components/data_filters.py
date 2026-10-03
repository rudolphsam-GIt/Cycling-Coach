"""
The date range, search and filters shared by the Dashboard and Data pages, plus
the summary tiles. The chosen filters are kept in st.session_state under
"df_*" keys, so a search made on one page is still there on the other.

Streamlit forgets a widget's value when you open a page that doesn't draw it, so
each widget has its own key ("dfw_*") seeded from the stored value and copied
back after every run.
"""
from __future__ import annotations

from copy import copy
from datetime import date, timedelta

import streamlit as st

from metrics import analysis as an

PRESETS = {"7 days": 7, "4 weeks": 28, "3 months": 91, "6 months": 182, "1 year": 365,
           "All": None, "Custom": "custom"}
KINDS = ["Road", "Indoor", "Gravel", "Mountain"]
RANGES = {"tss": (0, 400), "intensity": (0.0, 1.5), "minutes": (0, 480), "km": (0, 250)}
DEFAULTS = {"preset": "3 months", "custom": None, "text": "", "kinds": [], "tss": RANGES["tss"],
            "intensity": RANGES["intensity"], "minutes": RANGES["minutes"], "km": RANGES["km"],
            "has_power": False, "has_hr": False}


def _k(name: str) -> str:
    """The widget key for a filter. Clear bumps the generation so every widget
    starts fresh, since a closed popover's widgets would otherwise send their old
    value back from the browser."""
    return f"dfw_{name}_{st.session_state.get('df_gen', 0)}"


def _seed() -> None:
    for name, default in DEFAULTS.items():
        st.session_state.setdefault(f"df_{name}", copy(default))
        if _k(name) not in st.session_state:
            st.session_state[_k(name)] = copy(st.session_state[f"df_{name}"])


def _store() -> None:
    for name in DEFAULTS:
        if name == "preset":
            continue   # handled in render, an empty selection keeps the last preset
        if _k(name) in st.session_state:
            st.session_state[f"df_{name}"] = st.session_state[_k(name)]


def _clear() -> None:
    for name, default in DEFAULTS.items():
        if name not in ("preset", "custom"):
            st.session_state[f"df_{name}"] = copy(default)
    st.session_state["df_gen"] = st.session_state.get("df_gen", 0) + 1


def _range(name: str):
    """None when the slider covers its full range (no filter), else the pair."""
    value = tuple(st.session_state[f"df_{name}"])
    return None if value == tuple(RANGES[name]) else value


def _dates(today: date) -> tuple[date, date]:
    preset = st.session_state["df_preset"]
    days = PRESETS.get(preset, 91)
    if days == "custom":
        picked = st.session_state.get("df_custom")
        if isinstance(picked, (list, tuple)) and len(picked) == 2 and all(picked):
            return picked[0], picked[1]
        return today - timedelta(days=90), today
    if days is None:
        from db.queries import first_activity_date
        first = first_activity_date()
        start = date.fromisoformat(first) if first else today - timedelta(days=365)
        return start, today
    return today - timedelta(days=days - 1), today


def render() -> dict:
    """Draw the filter bar. Returns the filters and the rides they select:
    {"filters", "all" (every ride in the dates), "rides" (after the search and
    filters), "previous" (filtered rides in the period before, or None for All)}."""
    from db.queries import get_activities_between

    _seed()
    today = date.today()
    with st.container(border=True):
        top, clear = st.columns([6, 1], vertical_alignment="bottom")
        with top:
            st.segmented_control("Date range", list(PRESETS), key=_k("preset"),
                                 selection_mode="single")
        # Clicking the selected preset again unselects it; keep the last one instead.
        st.session_state["df_preset"] = (st.session_state.get(_k("preset"))
                                         or st.session_state["df_preset"] or "3 months")
        clear.button("Clear", key="df_clear", help="Clear the search and filters", on_click=_clear, width="stretch",
                     icon=":material/filter_alt_off:")

        if st.session_state["df_preset"] == "Custom":
            if not st.session_state.get(_k("custom")):
                st.session_state[_k("custom")] = (today - timedelta(days=90), today)
            st.date_input("From and to", key=_k("custom"), max_value=today)

        search, more = st.columns([4, 1.4], vertical_alignment="bottom")
        search.text_input("Search rides", key=_k("text"), placeholder="Search rides by name, e.g. zwift race",
                          label_visibility="collapsed")
        with more.popover("More filters", icon=":material/tune:", width="stretch"):
            st.pills("Ride type", KINDS, key=_k("kinds"), selection_mode="multi")
            st.slider("TSS", *RANGES["tss"], key=_k("tss"), step=5)
            st.slider("Intensity factor", *RANGES["intensity"], key=_k("intensity"), step=0.05)
            st.slider("Moving time (minutes)", *RANGES["minutes"], key=_k("minutes"), step=10)
            st.slider("Distance (km)", *RANGES["km"], key=_k("km"), step=5)
            st.toggle("Only rides with power", key=_k("has_power"))
            st.toggle("Only rides with heart rate", key=_k("has_hr"))
    _store()

    start, end = _dates(today)
    if start > end:
        start, end = end, start
    f = an.Filters(start=start, end=end, text=st.session_state["df_text"] or "",
                   kinds=tuple(st.session_state["df_kinds"] or ()), tss=_range("tss"),
                   intensity=_range("intensity"), minutes=_range("minutes"), km=_range("km"),
                   has_power=bool(st.session_state["df_has_power"]),
                   has_hr=bool(st.session_state["df_has_hr"]))
    with_previous = st.session_state["df_preset"] != "All"
    prev = f.previous()
    rows = get_activities_between((prev.start if with_previous else start).isoformat(), end.isoformat())
    everything = an.Filters(start=start, end=end)
    return {
        "filters": f,
        "all": an.filter_rides(rows, everything),
        "rides": an.filter_rides(rows, f),
        "previous": an.filter_rides(rows, prev) if with_previous else None,
    }


def describe(ctx: dict) -> str:
    """One line saying what is selected."""
    f = ctx["filters"]
    span = f"{f.start:%b %-d, %Y} to {f.end:%b %-d, %Y}"
    n, total = len(ctx["rides"]), len(ctx["all"])
    if f.narrowed():
        return f"{n} of {total} rides match your search, {span}."
    return f"{total} rides, {span}."


def summary_tiles(ctx: dict) -> None:
    """Totals for the selected rides, with the change against the period before."""
    now = an.summary(ctx["rides"])
    before = an.summary(ctx["previous"]) if ctx["previous"] is not None else None
    diff = an.deltas(now, before) if before else {}

    def tile(col, label, key, fmt, dfmt):
        d = diff.get(key)
        shown = dfmt(d) if d else None
        if shown and not any(ch in "123456789" for ch in shown):
            shown = None   # rounds to zero, so no arrow
        col.metric(label, fmt(now[key]) if now[key] is not None else "–",
                   delta=shown,
                   help="Change against the period of the same length just before" if before else None)

    r1 = st.columns(4)
    tile(r1[0], "Rides", "rides", lambda v: f"{v}", lambda d: f"{d:+.0f}")
    tile(r1[1], "Time", "hours",
         lambda v: f"{v:,.0f} h" if v >= 100 else f"{int(v)}h {int(v % 1 * 60):02d}m",
         lambda d: f"{d:+.1f} h")
    tile(r1[2], "Distance km", "km", lambda v: f"{v:,.0f}", lambda d: f"{d:+,.0f}")
    tile(r1[3], "Climbing m", "climb_m", lambda v: f"{v:,.0f}", lambda d: f"{d:+,.0f}")
    r2 = st.columns(4)
    tile(r2[0], "TSS", "tss", lambda v: f"{v:,.0f}", lambda d: f"{d:+,.0f}")
    tile(r2[1], "Work kJ", "kj", lambda v: f"{v:,.0f}", lambda d: f"{d:+,.0f}")
    tile(r2[2], "Avg IF", "avg_if", lambda v: f"{v:.2f}", lambda d: f"{d:+.2f}")
    tile(r2[3], "Avg EF", "avg_ef", lambda v: f"{v:.2f}", lambda d: f"{d:+.2f}")
