"""
The multi month program on the Plan page's Coach tab.

start_card      three ways to begin a program conversation
draft_card      the draft the coach saved, with a chart, a PDF download, and Add to my calendar
active_card     the program that is on the calendar, with the same details and PDF

The conversation itself is the ordinary coach chat, run with program_rules as extra instructions
(see coach_context). The coach saves its draft with propose_program, and this module shows it.
"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import program_pdf
import programs
from components import charts, theme
from db import queries as q
from metrics.training_load import get_current_metrics

MODE_KEY = "program_mode"
ADDED_KEY = "program_added"

STARTERS = [
    ("Let's discuss the off season", ":material/ac_unit:",
     "Let's discuss the off season. I'd like to plan a multi month program for the time after this "
     "season, and how to build into next year. Ask me what you need to know, one question at a time."),
    ("Plan toward a goal or race", ":material/flag:",
     "I'd like to plan a multi month build toward a goal or race. Ask me what you need to know, "
     "one question at a time."),
    ("Something else", ":material/edit_note:",
     "I'd like to plan a multi month training program. Help me work out what I need, one question "
     "at a time, starting with what I'm aiming for."),
]


def in_program_mode() -> bool:
    """True while a program is being discussed: after a starter button, or while a draft exists."""
    return bool(st.session_state.get(MODE_KEY)) or q.get_program("draft") is not None


def begin(message: str) -> None:
    """Callback for a starter button: switch on program mode and send the opening message."""
    st.session_state[MODE_KEY] = True
    st.session_state["pending_message"] = message


def _leave() -> None:
    st.session_state.pop(MODE_KEY, None)


def start_card() -> None:
    if st.session_state.get(MODE_KEY):
        with st.container(border=True):
            text, back = st.columns([4, 1], vertical_alignment="center")
            text.markdown("**Program planning is on.** Your coach is asking questions so it can draft a program. "
                          "Everything you type here goes toward that.")
            back.button("Back to normal chat", key="prog_leave", on_click=_leave, width="stretch")
        return
    with st.container(border=True):
        st.markdown("**Plan a longer program**")
        st.caption("Talk it through with your coach, review the plan, download it as a PDF, "
                   "then add it to your calendar when you are happy.")
        cols = st.columns(len(STARTERS))
        for col, (label, icon, message) in zip(cols, STARTERS):
            col.button(label, icon=icon, key=f"prog_start_{label}", width="stretch",
                       on_click=begin, args=(message,))


@st.cache_data(show_spinner=False, max_entries=8)
def _pdf_bytes(content_json: str, ctl: float, atl: float) -> bytes:
    program = json.loads(content_json)
    days = programs.projected_fitness(program, ctl, atl)
    return program_pdf.build_pdf(program, programs.weekly_ctl(program, days))


def _clean(program: dict) -> dict:
    return {k: v for k, v in program.items()
            if k not in ("id", "version", "status", "created_at", "updated_at", "executed_at")}


def _pdf_button(program: dict, key: str, m: dict, *, primary: bool = False) -> None:
    """`m` is get_current_metrics(), passed in so a card works it out once."""
    data = _pdf_bytes(json.dumps(_clean(program), sort_keys=True), round(m["ctl"], 1), round(m["atl"], 1))
    st.download_button("Download PDF", data, file_name=program_pdf.filename(program), mime="application/pdf",
                       key=key, icon=":material/picture_as_pdf:", width="stretch",
                       type="primary" if primary else "secondary")


def _chart(program: dict, ctl_by_week: dict, key: str) -> None:
    weeks = programs.week_plan(program)
    names = [p["name"] for p in program["phases"]]
    palette = ["#4D9FFF", "#34D399", "#FBBF24", "#F87171", "#C084FC", "#38BDF8", "#F472B6", "#A3E635"]
    fig = go.Figure()
    for i, name in enumerate(names):
        rows = [w for w in weeks if w["phase"] == name]
        fig.add_bar(x=[w["week"] for w in rows], y=[w["tss"] for w in rows], name=name,
                    marker=dict(color=palette[i % len(palette)],
                                opacity=[0.45 if w["recovery"] else 1 for w in rows]),
                    customdata=[[w["start"], w["hours"], "lighter week" if w["recovery"] else ""] for w in rows],
                    hovertemplate="Week %{x} (%{customdata[0]})<br>%{y} TSS · %{customdata[1]} h "
                                  "%{customdata[2]}<extra>" + name + "</extra>")
    if ctl_by_week:
        fig.add_scatter(x=list(ctl_by_week), y=list(ctl_by_week.values()), name="Projected fitness (CTL)",
                        mode="lines", yaxis="y2", line=dict(color="#FFFFFF", width=2),
                        hovertemplate="Week %{x}<br>CTL %{y}<extra></extra>")
    charts.apply_theme(fig, height=300, legend="top", dual_y=True)
    fig.update_layout(barmode="stack", bargap=0.2)
    fig.update_xaxes(title_text="Week of the program", dtick=1 if len(weeks) <= 26 else 4)
    fig.update_yaxes(title_text="Weekly TSS", rangemode="tozero")
    top = max(ctl_by_week.values(), default=0)
    fig.update_layout(legend_traceorder="normal",
                      yaxis2=dict(title="CTL", overlaying="y", side="right", showgrid=False,
                                  rangemode="tozero", tickmode="linear", dtick=10 if top <= 80 else 20, tickfont=dict(size=12, color=theme.TEXT2),
                                  title_font=dict(size=12, color=theme.TEXT2)))
    charts.show(fig, key=key, zoom=None)


def _phase_view(p: dict) -> None:
    st.markdown(f"**{p['focus']}**")
    st.markdown(p["why"])
    if p["week_template"]:
        mid = (p["weekly_tss_start"] + p["weekly_tss_end"]) / 2
        total = sum(d["share"] for d in p["week_template"]) or 1.0
        st.dataframe(pd.DataFrame([{
            "Day": d["day"], "Session": d["name"], "Details": d["description"], "Why": d["purpose"],
            "Feel": d["feel"], "TSS": round(mid * d["share"] / total)} for d in p["week_template"]]),
            hide_index=True, width="stretch",
            column_config={"Why": st.column_config.TextColumn(width="large"),
                           "Details": st.column_config.TextColumn(width="medium"),
                           "Feel": st.column_config.TextColumn(width="medium")})
        if p["recovery_every"]:
            st.caption(f"Every {p['recovery_every']}th week is lighter on purpose, at about 60 percent of the load.")
    else:
        st.caption("A break from structured riding. Ride for fun if you feel like it.")
    s = p["strength"]
    if s:
        st.markdown(f"**Strength** · {', '.join(s['days'])} · about {s['duration_minutes']} minutes · {s['name']}")
        st.caption(s["purpose"])
        st.caption(", ".join(f"{e['name']} {e['sets']}x{e['reps']}" for e in s["exercises"]))
    for label, items in (("Key sessions", p["key_workouts"]), ("Signs it is working", p["success_markers"])):
        if items:
            st.markdown(f"**{label}**")
            for item in items:
                st.markdown(f"- {item}")


def details(program: dict, key: str, m: dict) -> dict:
    """The body of a program card: numbers, chart, phases, checkpoints. `m` is
    get_current_metrics(). Returns the projected CTL by week."""
    days = programs.projected_fitness(program, m["ctl"], m["atl"])
    ctl_by_week = programs.weekly_ctl(program, days)
    weeks = programs.week_plan(program)

    st.caption(f"{programs.friendly_range(program)} · {program['total_weeks']} weeks · "
               f"{len(program['phases'])} phases")
    st.markdown(f"**Goal.** {program['goal']}")
    st.markdown(program["overview"])
    if program["assumptions"]:
        st.caption("Assumes " + " · ".join(program["assumptions"]))

    peak = max(weeks, key=lambda w: w["tss"])
    end_ctl = ctl_by_week.get(program["total_weeks"])
    a, b, c, d = st.columns(4)
    a.metric("Length", f"{program['total_weeks']} wks")
    b.metric("Peak week", f"{peak['tss']} TSS", help="The biggest week of training load in the program.")
    c.metric("Fitness now", f"{m['ctl']:.0f}", help="Your current CTL.")
    d.metric("Fitness at end", f"{end_ctl:.0f}" if end_ctl is not None else "n/a",
             delta=f"{end_ctl - m['ctl']:+.0f}" if end_ctl is not None else None,
             help="Projected CTL if you ride the program exactly as written.")
    _chart(program, ctl_by_week, f"{key}_chart")

    n = 0
    for p in program["phases"]:
        first, last = weeks[n], weeks[n + p["weeks"] - 1]
        n += p["weeks"]
        span = f"week {first['week']}" if p["weeks"] == 1 else f"weeks {first['week']} to {last['week']}"
        with st.expander(f"{p['name']} · {span} · {p['focus']}"):
            _phase_view(p)
    if program["checkpoints"]:
        st.markdown("**Checkpoints**")
        by_week = {w["week"]: w for w in weeks}
        for cp in program["checkpoints"]:
            when = programs.day_label(by_week[cp["week"]]["start"])
            st.markdown(f"- Week {cp['week']}, {when}. **{cp['what']}**. {cp['why']}")
    for note in program["notes"]:
        st.caption(note)
    return ctl_by_week


def _load_editor(draft: dict) -> None:
    """A table of the weeks where the TSS can be typed over. Weeks that differ from the plan are
    kept as overrides, and a week set back to the planned number goes back to following the plan."""
    import zlib

    weeks = programs.week_plan(draft)
    planned = {w["week"]: w["tss"] for w in programs.week_plan(draft, with_overrides=False)}
    n_edited = sum(1 for w in weeks if w["edited"])
    label = "Adjust the weekly load" + (f" · {n_edited} week{'s' if n_edited != 1 else ''} set by you" if n_edited else "")
    with st.expander(label, icon=":material/tune:"):
        st.caption("Change a week's TSS if the plan looks too much or too little, such as a busy week or a week "
                   "you want off. Set 0 for a week with no riding. Your changes show in the chart and the PDF "
                   "and carry through when your coach revises the draft.")
        df = pd.DataFrame([{"Week": w["week"], "Dates": programs.span_label(w["start"], w["end"]), "Phase": w["phase"],
                            "Planned": planned[w["week"]], "TSS": w["tss"],
                            "Note": "Lighter week" if w["recovery"] else ""} for w in weeks])
        sig = zlib.crc32(json.dumps(draft.get("tss_overrides") or {}, sort_keys=True).encode())
        edited = st.data_editor(
            df, hide_index=True, width="stretch", key=f"prog_load_{draft['id']}_{draft['version']}_{sig}",
            disabled=["Week", "Dates", "Phase", "Planned", "Note"],
            column_config={"TSS": st.column_config.NumberColumn("TSS", min_value=0, max_value=1500, step=5,
                                                                 required=True, help="Type over this number."),
                           "Planned": st.column_config.NumberColumn("Planned", help="What the plan said.")})
        changes = {}
        for w, new in zip(weeks, edited["TSS"]):
            new = None if pd.isna(new) else int(round(new))
            if new is not None and new != w["tss"]:
                changes[w["week"]] = None if new == planned[w["week"]] else new
        c1, c2 = st.columns(2)
        if c1.button("Save load changes", type="primary", width="stretch", disabled=not changes,
                     key=f"prog_load_save_{draft['id']}", icon=":material/save:"):
            programs.set_week_tss(draft["id"], changes)
            st.rerun()
        if c2.button("Back to the planned load", width="stretch", disabled=not n_edited,
                     key=f"prog_load_reset_{draft['id']}"):
            programs.set_week_tss(draft["id"], {w["week"]: None for w in weeks if w["edited"]})
            st.rerun()


def draft_card(*, on_plan_page: bool = True) -> None:
    """The draft the coach saved, until it is added to the calendar or discarded."""
    from components import coach_ui

    added = st.session_state.get(ADDED_KEY)
    if added:
        parts = [f"{added['rides']} rides"]
        if added["strength"]:
            parts.append(f"{added['strength']} strength sessions")
        if added["removed"]:
            parts.append(f"and replaced {added['removed']} workouts you had planned")
        st.success(f"{added['title']} is on your calendar. Added " + ", ".join(parts) + ".")
        pcol, vcol = st.columns(2)
        if vcol.button("View on calendar", key="prog_viewcal", icon=":material/calendar_month:", width="stretch"):
            st.session_state.pop(ADDED_KEY, None)
            coach_ui.jump_to_calendar(added["first"], on_plan_page)
        if pcol.button("Done", key="prog_added_done", width="stretch"):
            st.session_state.pop(ADDED_KEY, None)
            st.rerun()

    draft = programs.load("draft")
    if not draft:
        return
    with st.container(border=True):
        st.markdown(f"**Draft program** · version {draft['version']} · not on your calendar yet")
        st.subheader(draft["title"], anchor=False)
        m = get_current_metrics()
        details(draft, f"prog_draft_{draft['id']}_{draft['version']}", m)
        _load_editor(draft)

        if draft["start_date"] < date.today().isoformat():
            st.warning("The start date has passed. Days before today are skipped when you add it. "
                       "Ask your coach to move the start if you want the whole program.")
        found = programs.conflicts(draft)
        n_existing = len(found["rides"]) + len(found["strength"])
        replace = False
        if n_existing:
            replace = st.checkbox(
                f"Replace the {n_existing} workout{'s' if n_existing != 1 else ''} already planned on these dates",
                value=True, key=f"prog_replace_{draft['id']}",
                help="Planned rides and strength sessions inside the program's dates are removed so days are not "
                     "double booked. Rides you have already done are never touched.")
        else:
            st.caption("Nothing else is planned on these dates.")

        c1, c2, c3 = st.columns(3)
        with c1:
            _pdf_button(draft, f"prog_pdf_{draft['id']}_{draft['version']}", m)
        if c2.button("Add to my calendar", type="primary", width="stretch", icon=":material/event_available:",
                     key=f"prog_add_{draft['id']}_{draft['version']}"):
            try:
                out = programs.apply(draft["id"], replace_existing=replace)
            except programs.ProgramError as e:
                st.error(str(e))
            else:
                st.session_state[ADDED_KEY] = {**out, "title": draft["title"]}
                st.session_state.pop(MODE_KEY, None)
                st.rerun()
        if c3.button("Discard draft", width="stretch", icon=":material/delete:",
                     key=f"prog_discard_{draft['id']}_{draft['version']}"):
            q.set_program_status(draft["id"], "discarded")
            st.session_state.pop(MODE_KEY, None)
            st.rerun()
        st.caption("Want something different? Tell your coach in the chat and the draft updates.")


def _open_export() -> None:
    """Callback: open Plan, Manage with the export panel on this program's dates."""
    from components import plan_export
    plan_export.choose_program_range()
    st.session_state["plan_jump"] = "manage"


def active_card() -> None:
    """The program that is on the calendar. Details stay hidden until asked for."""
    prog = programs.load("active")
    if not prog:
        return
    here = programs.where_are_we(prog)
    m = get_current_metrics()
    with st.container(border=True):
        head, pdf, export, archive = st.columns([5, 2, 2, 2], vertical_alignment="center")
        title = f"**Your program** · {prog['title']}"
        head.markdown(title)
        if here:
            phase = next(p for p in prog["phases"] if p["name"] == here["phase"])
            head.caption(f"Week {here['week']} of {prog['total_weeks']} · {here['phase']} · {phase['focus']}")
        else:
            head.caption(programs.friendly_range(prog))
        with pdf:
            _pdf_button(prog, f"prog_active_pdf_{prog['id']}", m)
        export.button("Export", key=f"prog_export_{prog['id']}", width="stretch", icon=":material/ios_share:",
                      on_click=_open_export,
                      help="Send the whole program to TrainingPeaks, Zwift and Garmin, or download the files.")
        if archive.button("Archive", key=f"prog_archive_{prog['id']}", width="stretch",
                          icon=":material/inventory_2:",
                          help="Stops showing it here. Workouts already on your calendar stay."):
            q.set_program_status(prog["id"], "archived")
            st.rerun()
        if st.toggle("Show the program", key=f"prog_active_show_{prog['id']}"):
            details(prog, f"prog_active_{prog['id']}", m)
