"""
Streamlit pieces that show what a change to the plan does to fitness, fatigue and
form: the undo bar after a drag, the impact panel under the calendar, and the
before and after line used inside the workout dialog.

The numbers come from metrics.plan_impact. Nothing here reads the database.
"""
from __future__ import annotations

from datetime import date

import streamlit as st

from components import charts, theme
from components.explain import help_icon
from components.calendar import LAST_MOVE_KEY, undo_last_move
from metrics import plan_impact as pi
from metrics.explain import TIPS


def _day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%a %b} {d.day}"


def focus_label(state: dict) -> str:
    """Words for the day the plan is judged on."""
    focus = state["focus"]
    if state["race_name"]:
        return f"{state['race_name']} ({_day(focus.isoformat())})"
    return f"{_day(focus.isoformat())}, four weeks out"


def _planned_rides(state: dict) -> list[dict]:
    """Rides planned from today on. Rides already ridden don't count as a plan."""
    today = state["today"].isoformat()
    return [w for w in state["workouts"] if w["date"] >= today and (w.get("tss_planned") or 0) > 0]


def _has_plan(state: dict) -> bool:
    """Whether any ride is planned from today on. Without this, a rider with only gym
    sessions planned would be told they are about to rest for a month, because today's
    ride was counted as the plan."""
    return bool(_planned_rides(state))


def plan_end_note(plan: dict, state: dict) -> str | None:
    """A sentence when the planned rides stop well before the focus day, since the
    projection then assumes rest from the last planned ride."""
    last = max((w["date"] for w in _planned_rides(state)), default=None)
    if last and (state["focus"] - date.fromisoformat(last)).days > 7:
        return (f"Your planned rides end {_day(last)}, so the numbers for "
                f"{_day(state['focus'].isoformat())} assume rest after that. Add more workouts to see a "
                "fuller picture.")
    return None


def _dismiss_move() -> None:
    st.session_state.pop(LAST_MOVE_KEY, None)


def render_undo_bar() -> None:
    """The line under the calendar after a move, with Undo."""
    last = st.session_state.get(LAST_MOVE_KEY)
    if not last:
        return
    with st.container(border=True):
        text, undo, close = st.columns([8, 1.6, 0.8], vertical_alignment="center")
        text.markdown(f"Moved **{last['label']}** from {_day(last['from'])} to {_day(last['to'])}.")
        if last.get("garmin"):
            text.caption("The copy on Garmin was removed. Send it again for the new day.")
        undo.button("Undo", key="undo_move", icon=":material/undo:", on_click=undo_last_move,
                    width="stretch")
        close.button("", key="dismiss_move", icon=":material/close:", on_click=_dismiss_move,
                     help="Dismiss", width="stretch")


def _impact_chart(result: dict, compare: bool, race_day: str | None):
    import plotly.graph_objects as go

    fig = go.Figure()
    after = result["series_after"]
    x = [r["date"] for r in after]
    for name, key, color in (("Fitness", "ctl", theme.FITNESS), ("Fatigue", "atl", theme.FATIGUE),
                             ("Form", "tsb", theme.GOOD)):
        if compare:
            fig.add_scatter(x=x, y=[r[key] for r in result["series_before"]], mode="lines",
                            name=f"{name} before", line=dict(color=color, width=1.5, dash="dot"),
                            opacity=0.6, hovertemplate="%{y:.1f}<extra>" + name + " before</extra>")
        fig.add_scatter(x=x, y=[r[key] for r in after], mode="lines", name=name,
                        line=dict(color=color, width=2.5),
                        hovertemplate="%{y:.1f}<extra>" + name + "</extra>")
    if race_day:
        fig.add_shape(type="line", x0=race_day, x1=race_day, y0=0, y1=1, yref="paper",
                      line=dict(color=theme.RACE, width=2, dash="dash"))
    charts.apply_theme(fig, height=260, legend="top")
    fig.update_layout(hovermode="x unified")
    return fig


def _cards(result: dict, show_delta: bool) -> None:
    c1, c2, c3 = st.columns(3)
    for col, label, key, color in ((c1, "Fitness (CTL)", "ctl", "normal"),
                                   (c2, "Fatigue (ATL)", "atl", "off"),
                                   (c3, "Form (TSB)", "tsb", "normal")):
        delta = result["delta"][key]
        col.metric(label, f"{result['after'][key]:.1f}",
                   delta=f"{delta:+.1f}" if show_delta and delta else None, delta_color=color,
                   help=TIPS[key])


def render_impact_panel(state: dict) -> None:
    """Projected fitness, fatigue and form on the focus day, the chart, and any
    warnings. After a ride was moved it also shows the change that move made."""
    today, plan = state["today"], state["plan"]
    last = st.session_state.get(LAST_MOVE_KEY)
    with st.container(border=True):
        title, helper = st.columns([3, 1.6], vertical_alignment="center")
        title.subheader("Plan impact")
        with helper:
            help_icon("plan_impact", "plan_impact", label="What is this?")
        if not _has_plan(state):
            st.caption("No rides are planned from today on. Add workouts or ask your coach to build a block, "
                       "and the projected fitness, fatigue and form appear here.")
            return

        before = plan
        compare = bool(last and last["kind"] == "ride" and last["tss"])
        if compare:
            before = pi.shift(plan, last["tss"], last["to"], last["from"])
        result = pi.impact(before, plan, today=today, ctl=state["ctl"], atl=state["atl"],
                           focus=state["focus"])
        st.caption(f"Projected for {focus_label(state)}, if you ride the plan as written."
                   + (" Changes are from the move above." if compare else ""))
        _cards(result, compare)
        if note := plan_end_note(plan, state):
            st.caption(note)
        if last and last["kind"] == "strength":
            st.caption("Strength isn't counted in training load, so that move doesn't change these numbers.")
        race_day = state["focus"].isoformat() if state["race_name"] else None
        charts.show(_impact_chart(result, compare, race_day), key="impact_chart")

        notes = pi.warnings(plan, state["races"], today, state["horizon_end"])
        if notes:
            st.warning("\n".join(f"- {n}" for n in notes[:5]), icon=":material/warning:")
        else:
            st.caption("No flags. No back to back hard days, no big weekly jumps, and no hard day before a race.")


def render_dialog_impact(before: dict, after: dict, state: dict) -> None:
    """Before and after on the focus day for an edit that hasn't been saved yet."""
    result = pi.impact(before, after, today=state["today"], ctl=state["ctl"], atl=state["atl"],
                       focus=state["focus"])
    changed = any(result["delta"].values())
    st.caption(f"Effect on {focus_label(state)}" if changed
               else f"No change to {focus_label(state)} yet. Edit the date or TSS to see the effect.")
    _cards(result, changed)
    notes = [n for n in pi.warnings(after, state["races"], state["today"], state["horizon_end"])
             if n not in pi.warnings(before, state["races"], state["today"], state["horizon_end"])]
    if notes:
        st.warning("\n".join(f"- {n}" for n in notes[:3]), icon=":material/warning:")
