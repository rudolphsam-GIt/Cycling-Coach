"""
Shared UI for the AI coach: stream a reply with a live status line, and show
workouts the coach proposed with a confirm button.
"""
from __future__ import annotations

import json
import re

import pandas as pd
import streamlit as st

import claude_client
import coach_tools
import plan_changes
import strength_text
from db.queries import add_workout, add_strength_session, save_phase_notes, add_my_workout, get_setting

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


# A line that ends in a question mark, allowing for closing markdown or quotes after it.
_QUESTION_LINE = re.compile(r"\?[\s*_)\"'”]*$")
_LIST_LINE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
ASK_HEADING = "**Waiting on your answer**"


def _asks(paragraph: str) -> bool:
    return any(_QUESTION_LINE.search(line) for line in paragraph.splitlines())


def _is_list(paragraph: str) -> bool:
    lines = [line for line in paragraph.splitlines() if line.strip()]
    return bool(lines) and all(_LIST_LINE.match(line) for line in lines)


def split_questions(reply: str) -> tuple[str, str]:
    """
    Split the questions the coach ends a reply with from the rest of it, so they can be shown
    where the athlete (or their coach) sees that an answer is needed. Returns (body, questions),
    with questions empty when the reply doesn't end by asking something.

    The closing paragraphs that hold a line ending in a question mark count, along with a list
    of options straight after the question ("Which of these would you change?" then a list).
    """
    paras = [p for p in re.split(r"\n\s*\n", (reply or "").strip()) if p.strip()]
    end = len(paras)
    while end > 0 and _is_list(paras[end - 1]) and not _asks(paras[end - 1]):
        end -= 1                        # options listed after the question
    start = end
    while start > 0 and _asks(paras[start - 1]):
        start -= 1
    if start == end:
        return (reply or "").strip(), ""
    return "\n\n".join(paras[:start]), "\n\n".join(paras[start:])


# The chat coach marks its reply as answer, then [QUESTIONS], then [DETAILS]
# (coach_context.CHAT_LAYOUT). A marker line may come wrapped in bold or with a colon.
_MARKER = re.compile(r"^[ \t]*[*_]*\[(QUESTIONS|DETAILS)\][*_]*:?[ \t]*$", re.IGNORECASE | re.MULTILINE)
DETAILS_LABEL = "More detail"


def split_reply(reply: str) -> tuple[str, str, str]:
    """
    Split a chat reply into (answer, questions, details). Replies without the markers,
    such as older saved messages, fall back to split_questions with no details.
    """
    text = (reply or "").strip()
    parts = _MARKER.split(text)
    if len(parts) == 1:
        body, questions = split_questions(text)
        return body, questions, ""
    sections = {"QUESTIONS": [], "DETAILS": []}
    for name, chunk in zip(parts[1::2], parts[2::2]):
        if chunk.strip():
            sections[name.upper()].append(chunk.strip())
    return parts[0].strip(), "\n\n".join(sections["QUESTIONS"]), "\n\n".join(sections["DETAILS"])


def streaming_view(reply: str) -> str:
    """The reply as it streams in, with the markers turned into plain headings."""
    return _MARKER.sub(lambda m: "**Questions for you**" if m.group(1).upper() == "QUESTIONS"
                       else f"**{DETAILS_LABEL}**", reply)


def show_reply(reply: str, *, ask: bool = False) -> None:
    """
    Draw a coach reply: the answer, then the coach's questions, then any details folded
    away. With `ask` (the latest chat reply) the questions go in a highlighted box.
    """
    answer, questions, details = split_reply(reply)
    if answer:
        st.markdown(answer)
    if questions:
        if ask:
            st.info(f"{ASK_HEADING}\n\n{questions}", icon=":material/help:")
        else:
            st.markdown(questions)
    if details:
        with st.expander(DETAILS_LABEL, icon=":material/notes:"):
            st.markdown(details)


def stream_reply(system: list[dict], messages: list[dict], effort: str,
                 proposals: list[dict], model: str = claude_client.MODEL,
                 ask: bool = False) -> tuple[str, str | None]:
    """
    Stream the coach's reply into the current container, running tools as needed.
    Workouts the coach proposes are appended to `proposals`. While the coach works, a
    spinner says what it is doing, so a pause for a tool doesn't look like the end of
    the reply. `ask` highlights the questions the reply ends with (the chat uses it).
    Returns (reply_text, error_message_or_None).
    """
    status = st.empty()
    status.status("Thinking", state="running")
    body = st.empty()
    reply, error, looked_up = "", None, []

    events = claude_client.stream_chat(
        system, messages, coach_tools.TOOLS,
        lambda name, args: coach_tools.run_tool(name, args, proposals),
        effort=effort, model=model,
    )
    writing = False
    for kind, value in events:
        if kind == "text":
            reply += value
            body.markdown(streaming_view(reply) + "▌")
            if not writing:
                status.status("Writing the reply", state="running")
                writing = True
        elif kind == "tool":
            label = coach_tools.STATUS_LABELS.get(value, value)
            if label not in looked_up:
                looked_up.append(label)
            status.status(f"{label}, still working on the reply", state="running")
            writing = False
        elif kind == "error":
            error = value

    with body.container():
        show_reply(reply, ask=ask)
    if looked_up:
        status.caption("Looked at: " + ", ".join(
            l.replace("Checking your ", "").replace("Saving a note about you", "saved a note")
            for l in looked_up))
    else:
        status.empty()
    if error:
        st.error(error)
    return reply, error


def _proposal_key(p: dict) -> tuple:
    """New items are identified by date and kind, changes by the item they change."""
    if p.get("kind") == "change":
        return plan_changes.key(p)
    return (p.get("kind", "ride"), p["date"])


def merge_proposals(existing: list[dict] | None, new: list[dict]) -> list[dict]:
    """
    Combine a new proposal with one the athlete hasn't confirmed yet. Anything
    new for a date and kind replaces the old entry for that date and kind (a change
    replaces an earlier change to the same workout), so a revised block doesn't
    duplicate rows while an additive request ("also add a recovery day Friday")
    keeps everything else already on screen.
    """
    replaced = {_proposal_key(p) for p in new}
    kept = [p for p in (existing or []) if _proposal_key(p) not in replaced]
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


# ── Comments on a drafted plan ────────────────────────────────────────────────
# The athlete (or their coach) writes comments next to the drafted rows, and one button sends
# them all to the coach as a single chat message, instead of remembering them and typing them out.

COMMENT = "Your comment"


def comments_message(lines: list[str], general: str = "", *, what: str = "the proposed plan") -> str:
    """The chat message that carries the comments. Empty when there are none."""
    general = (general or "").strip()
    if not lines and not general:
        return ""
    items = list(lines) + ([f"Overall → {general}"] if general else [])
    return (f"I have comments on {what}. Please revise it with these in mind and show me the new version."
            "\n\n" + "\n".join(f"- {item}" for item in items))


def comment_key(state_key: str, data) -> str:
    """A widget key prefix that changes when the draft changes or comments are sent, so old
    comments never sit next to rows they weren't written for."""
    import zlib
    version = st.session_state.get(f"{state_key}_cv", 0)
    digest = zlib.crc32(json.dumps(data, sort_keys=True, default=str).encode())
    return f"{state_key}_c{version}_{digest}"


def comment_table(df: pd.DataFrame, key: str, label, *, after: str, column_config: dict | None = None) -> list[str]:
    """Show `df` with an editable comment column placed after the `after` column. Returns one
    line per comment, "<label of the row> → <comment>", where `label(row)` names the row."""
    df = df.copy()
    df[COMMENT] = ""
    order = list(df.columns[:-1])
    order.insert(order.index(after) + 1 if after in order else len(order), COMMENT)
    edited = st.data_editor(
        df, key=key, hide_index=True, width="stretch", column_order=order,
        disabled=[c for c in df.columns if c != COMMENT],
        column_config={**(column_config or {}),
                       COMMENT: st.column_config.TextColumn(
                           COMMENT, width="medium",
                           help="Click a cell and type what you would change, then press Enter. Comments "
                                "go to the coach together when you press Send.")})
    return [f"{label(row)} → {str(row[COMMENT]).strip()}" for _, row in edited.iterrows()
            if str(row[COMMENT] or "").strip()]


def comment_footer(state_key: str, key: str, lines: list[str], *, what: str, on_plan_page: bool) -> None:
    """An overall comment box and the Send comments button."""
    general = st.text_input("Anything else about the whole draft?", key=f"{key}_general",
                            placeholder="Optional, e.g. keep Fridays free")
    message = comments_message(lines, general, what=what)
    n = len(lines) + (1 if general.strip() else 0)
    label = f"Send {n} comment{'s' if n != 1 else ''} to the coach" if n else "Send comments to the coach"
    if st.button(label, key=f"{key}_send", icon=":material/rate_review:", disabled=not message,
                 width="stretch",
                 help="Write comments in the Your comment column first. They go to the coach as one message."):
        st.session_state["pending_message"] = message
        st.session_state[f"{state_key}_cv"] = st.session_state.get(f"{state_key}_cv", 0) + 1
        st.session_state[PLAN_JUMP_KEY] = "coach"
        if on_plan_page:
            st.rerun()
        else:
            st.switch_page(PLAN_PAGE)


def _ride_label(row) -> str:
    """How a proposed ride is named in a comment, e.g. "Tue Oct 20, VO2 max 5x3 min"."""
    from datetime import date
    try:
        d = date.fromisoformat(str(row["Date"]))
        day = f"{d:%a %b} {d.day}"
    except (KeyError, ValueError):
        day = str(row.get("Date", ""))
    return f"{day}, {row.get('Workout', 'ride')}"


def _rerun(in_dialog: bool) -> None:
    """After a click inside a popup, redraw just the popup so it stays open. Streamlit allows that
    only in the popup's own rerun, which is how its clicks normally arrive, so anything else
    reruns the page."""
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    ctx = get_script_run_ctx()
    st.rerun(scope="fragment" if in_dialog and ctx and ctx.fragment_ids_this_run else "app")


def proposal_card(state_key: str, *, on_plan_page: bool = False, in_dialog: bool = False) -> None:
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

    `in_dialog` is for a card inside a popup (the ride analysis). Its buttons get their own keys,
    since the page behind can show the same card in the same run, and Add and Discard redraw only
    the popup, so it stays open to say what was added.
    """
    wk = f"dlg_{state_key}" if in_dialog else state_key      # widget keys
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
            parts.append(f"added {added['rides']} ride{'s' if added['rides'] > 1 else ''}")
        if added["strength"]:
            parts.append(f"added {added['strength']} strength session{'s' if added['strength'] > 1 else ''}")
        for key, verb in (("moved", "moved"), ("updated", "edited"), ("removed", "removed")):
            if added.get(key):
                parts.append(f"{verb} {added[key]}")
        if parts:
            text = ", ".join(parts)
            st.success(f"Done. {text[0].upper() + text[1:]}.")
        for skipped in added.get("skipped", []):
            st.warning(f"Skipped {skipped['name']}. {skipped['why']}.")
        if parts and added.get("first"):
            if st.button("View on calendar", key=f"{wk}_viewcal", icon=":material/calendar_month:"):
                jump_to_calendar(added["first"], on_plan_page)

    proposed = st.session_state.get(state_key)
    if not proposed:
        return

    rides = [p for p in proposed if p.get("kind", "ride") == "ride"]
    strength = [p for p in proposed if p.get("kind") == "strength"]
    changes = [p for p in proposed if p.get("kind") == "change"]

    ckey = ("dlg_" if in_dialog else "") + comment_key(state_key, proposed)
    comments: list[str] = []
    with st.container(border=True):
        st.markdown("**Proposed changes** · review before they touch your calendar" if changes and not
                    (rides or strength) else "**Proposed plan** · review before adding to your calendar")

        if changes:
            if rides or strength:
                st.markdown(f"**Changes to your plan · {len(changes)}**")
            for c in changes:
                icon = {"remove": ":material/delete:", "move": ":material/event:",
                        "update": ":material/edit:"}[c["action"]]
                st.markdown(f"{icon} {plan_changes.describe(c)}")
                st.caption(f"Why. {c['reason']}")

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
                kept = [i["name"] for i in items if i.get("save")]
                if kept:
                    st.caption(":material/bookmark: Also saved to My workouts: " + ", ".join(kept))
                comments += comment_table(
                    _ride_frame(items), f"{ckey}_{phase_name}", _ride_label, after="Workout",
                    column_config={"Why": st.column_config.TextColumn(width="large"),
                                   "Feel": st.column_config.TextColumn(width="medium"),
                                   "Details": st.column_config.TextColumn(width="medium")})

        if strength:
            st.markdown(f"**Strength · {len(strength)} session{'s' if len(strength) > 1 else ''}**")
            unit = get_setting("weight_unit", "") or "kg"
            # Sessions that repeat (same name and exercises) show their prescription once.
            groups: list[list[dict]] = []
            for s in strength:
                if groups and strength_text.same_session(groups[-1][0], s):
                    groups[-1].append(s)
                else:
                    groups.append([s])
            for group in groups:
                s = group[0]
                when = (s["date"] if len(group) == 1 else
                        f"{len(group)} sessions, {group[0]['date']} to {group[-1]['date']}")
                st.markdown(f"**{s['name']}** · {when}"
                            + (f" · about {s['duration_minutes']} min" if s.get("duration_minutes") else ""))
                for ex in s.get("exercises", []):
                    tip = strength_text.note(ex)
                    st.markdown(f"- {strength_text.line(ex, unit)}" + (f"  \n  _{tip}_" if tip else ""))
                if s.get("purpose"):
                    st.caption(f"Why. {s['purpose']}")
                note = st.text_input(f"Your comment on {s['name']}", key=f"{ckey}_s{groups.index(group)}",
                                     placeholder="Your comment on these sessions (optional)", label_visibility="collapsed")
                if note.strip():
                    comments.append(f"Strength, {s['name']} ({when}) → {note.strip()}")

        if rides or strength:
            st.caption("Want changes? Write them in the Your comment column or boxes, then send them "
                       "to the coach in one go.")
            comment_footer(state_key, ckey, comments, what="the proposed plan", on_plan_page=on_plan_page)

        c1, c2 = st.columns(2)
        adding = bool(rides or strength)
        label = ("Add to Training Planner" if adding and not changes else
                 "Apply changes" if changes and not adding else "Add and apply changes")
        if c1.button(label, type="primary", width="stretch", key=f"{wk}_add"):
            for w in rides:
                if w.get("save"):
                    add_my_workout({"name": w["name"], "workout_type": w["workout_type"],
                                    "description": w["description"], "steps": w["steps"],
                                    "tss": w["tss_planned"], "purpose": w.get("purpose"), "feel": w.get("feel")})
                add_workout({
                    "date": w["date"], "name": w["name"], "workout_type": w["workout_type"],
                    "description": w["description"],
                    "structured_json": json.dumps(w["steps"]) if w.get("steps") else None,
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
            outcome = plan_changes.apply_changes(changes) if changes else {}
            dates = [p["date"] for p in rides + strength] + ([outcome["first"]] if outcome.get("first") else [])
            st.session_state.pop(state_key)
            st.session_state[added_key] = {"rides": len(rides), "strength": len(strength),
                                           "moved": outcome.get("moved", 0), "updated": outcome.get("updated", 0),
                                           "removed": outcome.get("removed", 0),
                                           "skipped": outcome.get("skipped", []),
                                           "first": min(dates) if dates else None,
                                           "shown": False}
            _rerun(in_dialog)
        if c2.button("Discard", width="stretch", key=f"{wk}_discard"):
            st.session_state.pop(state_key)
            _rerun(in_dialog)


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
                coach_reports.MODEL.get(kind, claude_client.MODEL),
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
