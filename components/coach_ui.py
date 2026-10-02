"""
Shared UI for the AI coach: stream a reply with a live status line, and show
workouts the coach proposed with a confirm button.
"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

import claude_client
import coach_tools
from db.queries import add_workout, add_strength_session


def local_time(utc_iso: str) -> str:
    """Show a stored UTC timestamp in the computer's local time."""
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(utc_iso).replace(tzinfo=timezone.utc).astimezone()
    except ValueError:
        return utc_iso
    return dt.strftime("%a %b %-d, %-I:%M %p")


def stream_reply(system: list[dict], messages: list[dict], effort: str,
                 proposals: list[dict]) -> tuple[str, str | None]:
    """
    Stream the coach's reply into the current container, running tools as needed.
    Workouts the coach proposes are appended to `proposals`.
    Returns (reply_text, error_message_or_None).
    """
    status = st.empty()
    status.caption("Thinking…")
    body = st.empty()
    reply, error, looked_up = "", None, []

    events = claude_client.stream_chat(
        system, messages, coach_tools.TOOLS,
        lambda name, args: coach_tools.run_tool(name, args, proposals),
        effort=effort,
    )
    for kind, value in events:
        if kind == "text":
            reply += value
            body.markdown(reply + "▌")
        elif kind == "tool":
            label = coach_tools.STATUS_LABELS.get(value, value)
            if label not in looked_up:
                looked_up.append(label)
            status.caption(f"{label}…")
        elif kind == "error":
            error = value

    body.markdown(reply)
    if looked_up:
        status.caption("Looked at: " + ", ".join(
            l.replace("Checking your ", "").replace("Saving a note about you", "saved a note")
            for l in looked_up))
    else:
        status.empty()
    if error:
        st.error(error)
    return reply, error


def proposal_card(state_key: str) -> None:
    """
    Show workouts and/or strength sessions proposed by the coach, stored in
    st.session_state[state_key], with confirm/discard. Each item is tagged
    kind="ride" or kind="strength" (propose_workouts/propose_strength_sessions
    in coach_tools.py); a multi-week ride block additionally carries phase /
    week_number, which groups the preview instead of showing one flat list.
    """
    added_key = f"{state_key}_added"
    if added := st.session_state.pop(added_key, None):
        rides_n, strength_n = added
        parts = []
        if rides_n:
            parts.append(f"{rides_n} ride{'s' if rides_n > 1 else ''}")
        if strength_n:
            parts.append(f"{strength_n} strength session{'s' if strength_n > 1 else ''}")
        if parts:
            st.success("Added " + " and ".join(parts) + " to your plan.")

    proposed = st.session_state.get(state_key)
    if not proposed:
        return

    rides = [p for p in proposed if p.get("kind", "ride") == "ride"]
    strength = [p for p in proposed if p.get("kind") == "strength"]

    with st.container(border=True):
        st.markdown("**Proposed plan** · review before adding to your calendar")

        if rides:
            has_phases = any(r.get("phase") for r in rides)
            if has_phases:
                by_phase: dict[str, list] = {}
                for r in rides:
                    by_phase.setdefault(r.get("phase") or "Workouts", list()).append(r)
                for phase_name, items in by_phase.items():
                    phase_tss = sum(i.get("tss_planned") or 0 for i in items)
                    df = pd.DataFrame(items).rename(columns={
                        "date": "Date", "name": "Workout", "workout_type": "Type",
                        "description": "Details", "tss_planned": "TSS", "week_number": "Week"})
                    cols = [c for c in ["Week", "Date", "Workout", "Type", "Details", "TSS"]
                            if c in df.columns]
                    with st.expander(f"{phase_name} · {len(items)} rides · {phase_tss:.0f} TSS",
                                     expanded=True):
                        st.dataframe(df[cols], hide_index=True, width="stretch")
            else:
                st.dataframe(
                    pd.DataFrame(rides).rename(columns={
                        "date": "Date", "name": "Workout", "workout_type": "Type",
                        "description": "Details", "tss_planned": "TSS"})[
                        ["Date", "Workout", "Type", "Details", "TSS"]],
                    hide_index=True, width="stretch",
                )

        if strength:
            st.markdown(f"**Strength · {len(strength)} session{'s' if len(strength) > 1 else ''}**")
            for s in strength:
                ex_names = ", ".join(e["name"] for e in s.get("exercises", [])[:4])
                more = f" +{len(s['exercises']) - 4} more" if len(s.get("exercises", [])) > 4 else ""
                st.caption(f"{s['date']} · **{s['name']}** · {ex_names}{more}")

        c1, c2 = st.columns(2)
        if c1.button("Add to Training Planner", type="primary", width="stretch",
                     key=f"{state_key}_add"):
            for w in rides:
                add_workout({
                    "date": w["date"], "name": w["name"], "workout_type": w["workout_type"],
                    "description": w["description"], "structured_json": None,
                    "tss_planned": w["tss_planned"], "notes": "Planned by AI Coach",
                    "phase": w.get("phase"), "week_number": w.get("week_number"),
                })
            for s in strength:
                add_strength_session({
                    "date": s["date"], "plan_week": s.get("week_number"),
                    "exercises_json": json.dumps(s["exercises"]),
                    "duration_minutes": s.get("duration_minutes"),
                    "notes": f"{s['name']} | Planned by AI Coach",
                    "phase": s.get("phase"),
                })
            st.session_state.pop(state_key)
            st.session_state[added_key] = (len(rides), len(strength))
            st.rerun()
        if c2.button("Discard", width="stretch", key=f"{state_key}_discard"):
            st.session_state.pop(state_key)
            st.rerun()


def report_block(kind: str, ref_key: str, title: str, prompt: str, *,
                 button_label: str, auto: bool = False) -> None:
    """
    Show a saved coach report, or write one when asked (or right away if auto).
    Proposed workouts from the report get their own confirm card.
    """
    import coach_context
    import coach_reports
    from db.queries import get_report, save_report

    state_key = f"proposals_{kind}_{ref_key}"
    run_key = f"run_{kind}_{ref_key}"
    existing = get_report(kind, ref_key)
    # Only write automatically once per visit, so a failure doesn't retry on every rerun.
    auto_key = f"auto_{kind}_{ref_key}"
    if auto and st.session_state.get(auto_key):
        auto = False
    elif auto and not existing:
        st.session_state[auto_key] = True

    with st.container(border=True):
        head, action = st.columns([4, 1])
        head.markdown(f"**{title}**")
        if existing and not st.session_state.get(run_key):
            if action.button("Rewrite", key=f"rewrite_{kind}_{ref_key}", width="stretch",
                             help="Write this again with the latest data"):
                st.session_state[run_key] = True
                st.rerun()
            st.markdown(existing["content"])
            st.caption(f"Written {local_time(existing['created_at'])}")
        elif st.session_state.get(run_key) or auto:
            st.session_state.pop(run_key, None)
            proposals: list[dict] = []
            reply, error = stream_reply(
                coach_context.system_blocks(coach_reports.REPORT_RULES),
                [{"role": "user", "content": prompt}],
                coach_reports.EFFORT.get(kind, "medium"), proposals,
            )
            if not error and reply.strip():
                save_report(kind, ref_key, title, reply)
                if proposals:
                    st.session_state[state_key] = proposals
                st.rerun()
        else:
            if st.button(button_label, type="primary", key=f"start_{kind}_{ref_key}"):
                st.session_state[run_key] = True
                st.rerun()

    proposal_card(state_key)
