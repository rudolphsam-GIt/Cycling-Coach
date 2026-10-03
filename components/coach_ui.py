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
from db.queries import add_workout, add_strength_session, save_phase_notes

# Jumping to the Plan page's calendar. The Plan page copies PLAN_JUMP_KEY into its
# tab bar state before drawing the tabs and maps the value to its own tab label.
PLAN_PAGE = "pages/02_Training_Planner.py"
PLAN_JUMP_KEY = "plan_jump"
PLAN_JUMP_CALENDAR = "calendar"


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


def merge_proposals(existing: list[dict] | None, new: list[dict]) -> list[dict]:
    """
    Combine a new proposal with one the athlete hasn't confirmed yet. Anything
    new for a date and kind replaces the old entry for that date and kind, so a
    revised block doesn't duplicate rows while an additive request ("also add a
    recovery day Friday") keeps everything else already on screen.
    """
    replaced = {(p.get("kind", "ride"), p["date"]) for p in new}
    kept = [p for p in (existing or []) if (p.get("kind", "ride"), p["date"]) not in replaced]
    return sorted(kept + new, key=lambda p: (p["date"], p.get("kind", "ride")))


def jump_to_calendar(day_iso: str, on_plan_page: bool = False) -> None:
    """Open the Plan page's calendar on the month and day of `day_iso`."""
    from datetime import date
    d = date.fromisoformat(day_iso)
    st.session_state["cal_ym"] = (d.year, d.month)
    st.session_state["cal_sel"] = day_iso
    st.session_state[PLAN_JUMP_KEY] = PLAN_JUMP_CALENDAR
    if on_plan_page:
        st.rerun()
    else:
        st.switch_page(PLAN_PAGE)


def _ride_frame(items: list) -> pd.DataFrame:
    """The proposed rides as a table, with why and how it should feel when given."""
    df = pd.DataFrame(items).rename(columns={
        "date": "Date", "name": "Workout", "workout_type": "Type", "description": "Details",
        "tss_planned": "TSS", "week_number": "Week", "purpose": "Why", "feel": "Feel"})
    cols = [c for c in ["Week", "Date", "Workout", "Type", "Why", "Feel", "Details", "TSS"]
            if c in df.columns and df[c].notna().any()]
    return df[cols]


def proposal_card(state_key: str, *, on_plan_page: bool = False) -> None:
    """
    Show workouts and/or strength sessions proposed by the coach, stored in
    st.session_state[state_key], with confirm/discard. Each item is tagged
    kind="ride" or kind="strength" (propose_workouts/propose_strength_sessions
    in coach_tools.py); a multi-week ride block additionally carries phase /
    week_number, which groups the preview instead of showing one flat list.

    After the items are added, a "View on calendar" button opens the Plan page
    on the earliest added date. `on_plan_page` says whether this card is already
    drawn on the Plan page (then it just switches tab) or on another page (then
    it navigates there).
    """
    added_key = f"{state_key}_added"
    added = st.session_state.get(added_key)
    if added:
        # Show this for the run that follows the add and one more, so a click on
        # "View on calendar" in that second run still finds its button.
        if added["shown"]:
            st.session_state.pop(added_key)
        else:
            added["shown"] = True
        parts = []
        if added["rides"]:
            parts.append(f"{added['rides']} ride{'s' if added['rides'] > 1 else ''}")
        if added["strength"]:
            parts.append(f"{added['strength']} strength session{'s' if added['strength'] > 1 else ''}")
        if parts:
            st.success("Added " + " and ".join(parts) + " to your plan.")
            if added.get("first"):
                if st.button("View on calendar", key=f"{state_key}_viewcal",
                             icon=":material/calendar_month:"):
                    jump_to_calendar(added["first"], on_plan_page)

    proposed = st.session_state.get(state_key)
    if not proposed:
        return

    rides = [p for p in proposed if p.get("kind", "ride") == "ride"]
    strength = [p for p in proposed if p.get("kind") == "strength"]

    with st.container(border=True):
        st.markdown("**Proposed plan** · review before adding to your calendar")

        if rides:
            by_phase: dict[str, list] = {}
            for r in rides:
                by_phase.setdefault(r.get("phase") or "Workouts", list()).append(r)
            has_phases = any(r.get("phase") for r in rides)
            for phase_name, items in by_phase.items():
                if has_phases:
                    phase_tss = sum(i.get("tss_planned") or 0 for i in items)
                    # A plain heading rather than an expander, so this card can
                    # sit inside the Weekly Check In expander without nesting.
                    st.markdown(f"**{phase_name}** · {len(items)} rides · {phase_tss:.0f} TSS")
                    note = next((i["phase_note"] for i in items if i.get("phase_note")), None)
                    if note:
                        st.markdown(f"**Focus.** {note['focus']}  \n{note['why']}")
                st.dataframe(_ride_frame(items), hide_index=True, width="stretch",
                             column_config={"Why": st.column_config.TextColumn(width="large"),
                                            "Feel": st.column_config.TextColumn(width="medium"),
                                            "Details": st.column_config.TextColumn(width="medium")})

        if strength:
            st.markdown(f"**Strength · {len(strength)} session{'s' if len(strength) > 1 else ''}**")
            for s in strength:
                ex_names = ", ".join(e["name"] for e in s.get("exercises", [])[:4])
                more = f" +{len(s['exercises']) - 4} more" if len(s.get("exercises", [])) > 4 else ""
                st.caption(f"{s['date']} · **{s['name']}** · {ex_names}{more}")
                if s.get("purpose"):
                    st.caption(f"Why. {s['purpose']}")

        c1, c2 = st.columns(2)
        if c1.button("Add to Training Planner", type="primary", width="stretch",
                     key=f"{state_key}_add"):
            for w in rides:
                add_workout({
                    "date": w["date"], "name": w["name"], "workout_type": w["workout_type"],
                    "description": w["description"], "structured_json": None,
                    "tss_planned": w["tss_planned"], "notes": "Planned by AI Coach",
                    "phase": w.get("phase"), "week_number": w.get("week_number"),
                    "purpose": w.get("purpose"), "feel": w.get("feel"),
                })
            save_phase_notes([{"name": w["phase"], **w["phase_note"]} for w in rides
                              if w.get("phase") and w.get("phase_note")])
            for s in strength:
                add_strength_session({
                    "date": s["date"], "plan_week": s.get("week_number"),
                    "exercises_json": json.dumps(s["exercises"]),
                    "duration_minutes": s.get("duration_minutes"),
                    "notes": f"{s['name']} | Planned by AI Coach",
                    "phase": s.get("phase"), "purpose": s.get("purpose"),
                })
            dates = [p["date"] for p in rides + strength]
            st.session_state.pop(state_key)
            st.session_state[added_key] = {"rides": len(rides), "strength": len(strength),
                                           "first": min(dates) if dates else None,
                                           "shown": False}
            st.rerun()
        if c2.button("Discard", width="stretch", key=f"{state_key}_discard"):
            st.session_state.pop(state_key)
            st.rerun()


def report_block(kind: str, ref_key: str, title: str, prompt: str, *,
                 button_label: str, auto: bool = False, on_plan_page: bool = False) -> None:
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

    proposal_card(state_key, on_plan_page=on_plan_page)
