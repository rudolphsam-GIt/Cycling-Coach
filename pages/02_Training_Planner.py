from __future__ import annotations
import base64
import io
import json
import zipfile
import streamlit as st
from datetime import date, timedelta
from PIL import Image
from components import page_header
from components import calendar as plan_cal
from components import ftp_help, plan_export, plan_impact_ui, ride_analysis

from db.queries import (get_workouts, add_workout, update_workout, delete_workout,
                         get_setting, get_races, WORKOUT_TYPES,
                         get_workout, get_strength_session, delete_strength_session, garmin_status, save_message, get_conversation_history, get_conversation_window,
                         get_memories, forget_memory, save_phase_notes, get_phase_notes)
import auth.garmin as garmin_auth
import exporters
import garmin_workouts
import sync
import planning
from metrics.training_load import get_current_metrics
from metrics import plan_impact
from metrics import explain
from config import ANTHROPIC_API_KEY


page_header("Plan", "Review your calendar, talk to your coach and manage upcoming workouts.")

ftp = float(get_setting("ftp_watts", 200) or 200)
today = date.today()
metrics = get_current_metrics()   # computed once per run and reused everywhere below

# Tab labels. The selected one lives in st.session_state["plan_tab"].
TAB_CAL, TAB_COACH, TAB_MANAGE = "Calendar", "Coach", "Manage"
TAB_BY_JUMP = {"calendar": TAB_CAL, "coach": TAB_COACH, "manage": TAB_MANAGE}

GARMIN_BADGE = {"sent": ":green[On Garmin]", "changed": ":orange[Edited, resend to Garmin]"}

coach_available = bool(ANTHROPIC_API_KEY) and ANTHROPIC_API_KEY != "paste_your_key_here"
coach_import_error = False
if coach_available:
    try:
        import coach_context
        import coach_reports
        from components import coach_ui, program_ui
        import programs
    except ImportError:
        coach_available = False
        coach_import_error = True

# A jump request (from the coach proposal card, or a Manage list Edit button) names a
# tab. It has to land in the tab bar's own state before st.tabs is drawn.
if _jump := st.session_state.pop("plan_jump", None):
    st.session_state["plan_tab"] = TAB_BY_JUMP.get(_jump, _jump)


def remove_workout(w: dict) -> None:
    """Delete a planned workout, and the copy we sent to Garmin if there is one."""
    garmin_workouts.remove_from_garmin(w)
    delete_workout(w["id"])
    sync.remove_everywhere([w["id"]])


def queue_garmin_send(ws: list) -> None:
    st.session_state["garmin_queue"] = [w["id"] for w in ws]
    st.rerun()


def queue_fit_download(ws: list) -> None:
    st.session_state["fit_queue"] = [w["id"] for w in ws]
    st.rerun()


def can_send(w: dict) -> bool:
    return garmin_auth.is_connected() and w["date"] >= today.isoformat()


def garmin_button(w: dict, container, key: str) -> None:
    if not can_send(w):
        return
    status = garmin_status(w)
    label = {"not_sent": "Send to Garmin", "sent": "Resend", "changed": "Resend"}[status]
    if container.button(label, key=key, icon=":material/watch:",
                        help="Upload to Garmin Connect and schedule it on this date"):
        queue_garmin_send([w])


def fit_button(w: dict, container, key: str) -> None:
    if container.button("Download .fit", key=key, icon=":material/download:",
                        help="A .fit file you can import manually into TrainingPeaks or elsewhere"):
        queue_fit_download([w])


def _steps_for(w: dict, cache: dict):
    """
    This workout's structured steps, or an error message. Steps are built once with
    garmin_workouts.ensure_steps and saved on the workout, so the Garmin send, the .fit
    download and the plan export all share them. `cache` keeps failures for this visit so a
    workout that can't be converted isn't retried on every rerun.
    """
    wid = w["id"]
    if wid not in cache:
        with st.spinner(f"Turning {w['name']} into structured steps…"):
            try:
                cache[wid] = garmin_workouts.ensure_steps([w])[wid]
            except garmin_workouts.WorkoutError as e:
                cache[wid] = str(e)
    steps = cache[wid]
    if isinstance(steps, list):
        cache.pop(wid)           # saved now, so the next visit reads the latest from the workout
    return steps


def garmin_send_panel() -> None:
    """Preview the Garmin steps for queued workouts, then send them on confirm."""
    if msg := st.session_state.pop("garmin_send_msg", None):
        (st.success if msg[0] == "ok" else st.warning)(msg[1])

    queue = st.session_state.get("garmin_queue")
    if not queue:
        return
    cache = st.session_state.setdefault("step_cache", {})
    with st.container(border=True):
        st.markdown("**Send to Garmin** · check the steps, then send")
        ready = []
        for wid in queue:
            w = get_workout(wid)
            if not w:
                continue
            steps = _steps_for(w, cache)
            if isinstance(steps, str):
                st.markdown(f"**{w['date']} · {w['name']}**")
                st.error(steps)
                continue
            st.markdown(f"**{w['date']} · {w['name']}** · "
                        f"{garmin_workouts.total_minutes(steps):.0f} min")
            st.dataframe(garmin_workouts.preview_rows(steps), hide_index=True, width="stretch")
            ready.append((w, steps))

        c1, c2 = st.columns(2)
        send_label = f"Send {len(ready)} workout{'s' if len(ready) != 1 else ''} to Garmin"
        if c1.button(send_label, type="primary", width="stretch", disabled=not ready,
                     key="garmin_confirm"):
            sent, failed = 0, []
            with st.spinner("Sending to Garmin…"):
                for w, steps in ready:
                    try:
                        garmin_workouts.send(w, steps)
                        sent += 1
                    except garmin_workouts.WorkoutError as e:
                        failed.append(f"{w['name']}: {e}")
            st.session_state.pop("garmin_queue", None)
            text = f"Sent {sent} workout{'s' if sent != 1 else ''} to Garmin. Sync your Edge or watch to load them."
            if failed:
                st.session_state["garmin_send_msg"] = ("warn", text + " Couldn't send: " + "; ".join(failed))
            else:
                st.session_state["garmin_send_msg"] = ("ok", text)
            st.rerun()
        if c2.button("Cancel", width="stretch", key="garmin_cancel"):
            st.session_state.pop("garmin_queue", None)
            st.rerun()


def fit_download_panel() -> None:
    """Preview + build .fit files for queued workouts — one file, or a zip for more than one."""
    queue = st.session_state.get("fit_queue")
    if not queue:
        return
    cache = st.session_state.setdefault("step_cache", {})
    with st.container(border=True):
        st.markdown("**Download .fit** · for manual import into TrainingPeaks or elsewhere")
        ready = []
        for wid in queue:
            w = get_workout(wid)
            if not w:
                continue
            steps = _steps_for(w, cache)
            if isinstance(steps, str):
                st.markdown(f"**{w['date']} · {w['name']}**")
                st.error(steps)
                continue
            st.markdown(f"**{w['date']} · {w['name']}** · "
                        f"{garmin_workouts.total_minutes(steps):.0f} min")
            ready.append((w, steps))

        fit_error = None
        if len(ready) == 1:
            w, steps = ready[0]
            try:
                data = garmin_workouts.to_fit_bytes(w, steps)
                st.download_button(f"Download {w['name']}.fit", data=data,
                                   file_name=f"{exporters.file_base(w)}.fit",
                                   mime="application/octet-stream", width="stretch", type="primary")
            except Exception as e:
                fit_error = str(e)
        elif ready:
            try:
                buf = io.BytesIO()
                used_names: set[str] = set()
                with zipfile.ZipFile(buf, "w") as zf:
                    for w, steps in ready:
                        base = exporters.file_base(w)
                        arcname, n = f"{base}.fit", 2
                        while arcname in used_names:
                            arcname, n = f"{base}_{n}.fit", n + 1
                        used_names.add(arcname)
                        zf.writestr(arcname, garmin_workouts.to_fit_bytes(w, steps))
                st.download_button(f"Download {len(ready)} workouts (.zip)", data=buf.getvalue(),
                                   file_name="training_plan.zip", mime="application/zip",
                                   width="stretch", type="primary")
            except Exception as e:
                fit_error = str(e)
        if fit_error:
            st.error(f"Couldn't build the .fit file: {fit_error}")
        if st.button("Close", key="fit_close"):
            st.session_state.pop("fit_queue", None)
            st.rerun()


# ── Shared helpers for the three tabs ──────────────────────────────────────────

_panels_drawn = False


def render_send_panels() -> None:
    """Draw the Garmin and .fit panels once per run, whichever tab asks first."""
    global _panels_drawn
    if _panels_drawn:
        return
    _panels_drawn = True
    garmin_send_panel()
    fit_download_panel()


def jump_to_day(day_iso: str, tab: str = "calendar") -> None:
    """Callback: select a day on the calendar and switch to a tab."""
    d = date.fromisoformat(day_iso)
    st.session_state["cal_ym"] = (d.year, d.month)
    st.session_state["cal_sel"] = day_iso
    st.session_state["plan_jump"] = tab


def start_edit(w: dict) -> None:
    """Callback: open this workout's edit dialog on the calendar."""
    st.session_state[plan_cal.OPEN_KEY] = {"kind": "ride", "id": w["id"]}
    jump_to_day(w["date"])


def set_done(w: dict, done: bool) -> None:
    """Callback: mark a planned workout done or undo that."""
    update_workout(w["id"], {**w, "completed": 1 if done else 0})


def fmt_day(day_iso: str) -> str:
    return date.fromisoformat(day_iso).strftime("%a %b %-d")


def workout_summary(w: dict) -> str:
    """One caption line: type, planned TSS, done state and Garmin status."""
    tss = w.get("tss_planned")
    bits = [w.get("workout_type") or "Workout", f"{tss:.0f} TSS" if tss is not None else "no TSS"]
    if w.get("completed"):
        bits.append(":green[Done]")
    if (badge := GARMIN_BADGE.get(garmin_status(w))):
        bits.append(badge)
    return " · ".join(bits)


def why_block(w: dict) -> None:
    """What the workout is for, how it should feel, and the phase it belongs to."""
    if w.get("purpose"):
        st.markdown(f"**Why.** {w['purpose']}")
    if w.get("feel"):
        st.markdown(f"**How it should feel.** {w['feel']}")
    note = get_phase_notes().get(w.get("phase") or "")
    if note:
        st.markdown(f"**Part of {w['phase']}.** {note['focus']} {note['why']}")


def workout_form(default_date: date) -> None:
    """The add form. Editing an existing workout happens in workout_dialog."""
    st.markdown("**Add a workout**")
    with st.form("workout_form", clear_on_submit=True, border=False):
        w_date = st.date_input("Date", value=default_date)
        w_name = st.text_input("Workout name", placeholder="e.g. Threshold intervals")
        w_type = st.selectbox("Type", WORKOUT_TYPES)
        w_tss = st.number_input("Planned TSS", min_value=0, max_value=500, value=60, step=5)
        w_desc = st.text_area("Description or notes", placeholder="3x10 min @ 95% FTP, 5 min rest")
        w_purpose = st.text_input("What is it for? (optional)",
                                  placeholder="Leave blank to use a standard explanation for the type")
        w_feel = st.text_input("How should it feel? (optional)",
                               placeholder="Leave blank to use a standard effort guide for the type")
        submitted = st.form_submit_button("Add to planner", type="primary", icon=":material/save:")

    if st.button("Cancel", key="cancel_add", icon=":material/close:"):
        st.session_state.pop("add_workout_date", None)
        st.rerun()

    if not submitted:
        return
    if not w_name.strip():
        st.warning("Give the workout a name first.")
        return
    add_workout({
        "date": w_date.isoformat(), "name": w_name,
        "workout_type": w_type, "description": w_desc,
        "structured_json": None, "tss_planned": w_tss, "notes": "",
        "purpose": w_purpose.strip() or explain.PURPOSE.get(w_type, explain.PURPOSE["Other"]),
        "feel": w_feel.strip() or explain.feel_for(w_type),
    })
    st.session_state.pop("add_workout_date", None)
    st.toast(f"Added {w_name}")
    st.rerun()


# ── Calendar tab ───────────────────────────────────────────────────────────────

def planned_row(w: dict) -> None:
    """One planned workout in the selected day panel, with its actions."""
    wid = w["id"]
    with st.container(border=True):
        st.markdown(f"**{w['name']}**")
        st.caption(workout_summary(w))
        if w.get("description"):
            st.write(w["description"])
        why_block(w)
        with st.container(horizontal=True):
            if w.get("completed"):
                st.button("Undo", key=f"cal_undo_{wid}", icon=":material/undo:",
                          on_click=set_done, args=(w, False))
            else:
                st.button("Mark done", key=f"cal_done_{wid}", icon=":material/check_circle:",
                          on_click=set_done, args=(w, True))
            st.button("Edit", key=f"cal_edit_{wid}", icon=":material/edit:",
                      on_click=start_edit, args=(w,))
            if st.button("Remove", key=f"cal_del_{wid}", icon=":material/delete:",
                         help=f"Remove {w['name']}"):
                remove_workout(w)
                st.rerun()
            garmin_button(w, st, f"garmin_cal_{wid}")
            fit_button(w, st, f"fit_cal_{wid}")


def day_strength_actions(info: dict) -> None:
    """Open and Remove buttons inside each strength session in the day panel."""
    row = get_strength_session(info["id"]) if info.get("id") else None
    if not row:
        return
    with st.container(horizontal=True):
        st.button("Open", key=f"day_s_open_{row['id']}", icon=":material/open_in_new:",
                  on_click=lambda i=row["id"], d=row["date"]: st.session_state.update(
                      {plan_cal.OPEN_KEY: {"kind": "strength", "id": i}, "cal_sel": d}))
        strength_remove_controls(row, f"day_s_{row['id']}")


def day_panel(sel: str) -> None:
    """Everything about the selected calendar day, with add and edit."""
    d = date.fromisoformat(sel)
    day = plan_cal.get_day(sel, st.session_state.get(plan_cal.MONTH_DAYS_KEY))
    planned = get_workouts(sel, sel)

    with st.container(border=True):
        st.subheader(d.strftime("%A, %B %-d"))
        if not planned:
            st.caption("Nothing planned for this day.")
        for w in planned:
            planned_row(w)

        plan_cal.render_day_readonly(sel, strength_actions=day_strength_actions, day=day)

        planned_tss = float(getattr(day, "planned_tss", 0) or 0)
        actual_tss = float(getattr(day, "actual_tss", 0) or 0)
        if planned_tss or actual_tss:
            m1, m2 = st.columns(2)
            m1.metric("Planned TSS", f"{planned_tss:.0f}")
            delta = None
            if planned_tss and d <= today:
                delta = f"{(actual_tss - planned_tss) / planned_tss * 100:+.0f}%"
            m2.metric("Actual TSS", f"{actual_tss:.0f}", delta=delta)

        if st.session_state.get("add_workout_date") == sel:
            with st.container(border=True):
                workout_form(d)
        elif st.button("Add workout on this day", key="cal_add_day", icon=":material/add:"):
            st.session_state["add_workout_date"] = sel
            st.rerun()


def _workout_plan(state: dict, w: dict, *, date_iso: str, tss: float) -> dict:
    """The plan as it would be if workout `w` had this date and planned TSS."""
    edited = [{**x, "date": date_iso, "tss_planned": tss} if x["id"] == w["id"] else x
              for x in state["workouts"]]
    if all(x["id"] != w["id"] for x in state["workouts"]):
        edited.append({**w, "date": date_iso, "tss_planned": tss})
    return plan_impact.plan_from_rows(edited, state["actual"], state["today"])


@st.dialog("Workout", width="large")
def workout_dialog(kind: str, item_id, state: dict) -> None:
    """Open one planned workout or strength session, edit it, and see what the
    change does to fitness, fatigue and form before saving."""
    if kind == "strength":
        return strength_dialog(item_id)
    w = get_workout(int(item_id)) if item_id is not None else None
    if not w:
        st.info("That workout no longer exists.")
        return
    skipped = not w.get("completed") and w["date"] < today.isoformat()
    editable = not w.get("completed")
    st.markdown(f"**{fmt_day(w['date'])}**")
    st.caption(workout_summary(w))

    if not editable:
        st.write(w.get("description") or "No description.")
        why_block(w)
        st.caption("A workout marked done stays as it is. Undo done if you need to change it.")
        with st.container(horizontal=True):
            if w.get("completed"):
                st.button("Undo done", key="dlg_undo", icon=":material/undo:",
                          on_click=set_done, args=(w, False))
            else:
                st.button("Mark done", key="dlg_done", icon=":material/check_circle:",
                          on_click=set_done, args=(w, True))
            if st.button("Remove", key="dlg_del", icon=":material/delete:"):
                remove_workout(w)
                st.rerun()
        return

    name = st.text_input("Workout name", value=w["name"], key="dlg_name")
    c1, c2 = st.columns(2)
    wtype = c1.selectbox("Type", WORKOUT_TYPES, key="dlg_type",
                         index=WORKOUT_TYPES.index(w["workout_type"])
                         if w.get("workout_type") in WORKOUT_TYPES else 0)
    new_date = c2.date_input("Date", value=date.fromisoformat(w["date"]),
                             min_value=None if skipped else today, key="dlg_date")
    if skipped:
        st.info("This workout was not ridden on its day. Move it to another day to do it later, or to the "
                "day you really did it, then mark it done. You can also edit it first.", icon=":material/event_busy:")
    tss = c1.number_input("Planned TSS", min_value=0, max_value=500, step=5, key="dlg_tss",
                          value=int(w["tss_planned"]) if w.get("tss_planned") is not None else 60)
    desc = st.text_area("Description or notes", value=w.get("description") or "", key="dlg_desc",
                        placeholder="3x10 min @ 95% FTP, 5 min rest")
    purpose = st.text_area("What is it for?", value=w.get("purpose") or "", key="dlg_purpose", height=80)
    feel = st.text_input("How should it feel?", value=w.get("feel") or "", key="dlg_feel")
    note = get_phase_notes().get(w.get("phase") or "")
    if note:
        st.caption(f"Part of {w['phase']}. {note['focus']} {note['why']}")

    before = _workout_plan(state, w, date_iso=w["date"], tss=float(w.get("tss_planned") or 0))
    after = _workout_plan(state, w, date_iso=new_date.isoformat(), tss=float(tss))
    plan_impact_ui.render_dialog_impact(before, after, state)

    if (badge := GARMIN_BADGE.get(garmin_status(w))):
        st.caption(badge)
    with st.container(horizontal=True):
        if st.button("Save changes", key="dlg_save", type="primary", icon=":material/save:"):
            if not name.strip():
                st.warning("Give the workout a name first.")
                return
            update_workout(w["id"], {"name": name, "workout_type": wtype, "description": desc,
                                     "tss_planned": tss, "completed": w.get("completed", 0),
                                     "notes": w.get("notes", ""), "purpose": purpose.strip(),
                                     "feel": feel.strip()})
            if new_date.isoformat() != w["date"]:
                err = plan_cal.apply_move("ride", w["id"], new_date.isoformat(), today)
                if err:
                    st.warning(err)
                    return
            else:
                st.toast(f"Updated {name}")
            st.rerun()
        st.button("Mark done", key="dlg_done", icon=":material/check_circle:",
                  on_click=set_done, args=(w, True))
        if st.button("Remove", key="dlg_del", icon=":material/delete:"):
            remove_workout(w)
            st.rerun()
    with st.container(horizontal=True):
        garmin_button(w, st, "dlg_garmin")
        fit_button(w, st, "dlg_fit")


def remove_strength(sid: int) -> None:
    """Callback: remove a strength session from the plan or the log."""
    removed = delete_strength_session(sid)
    if removed:
        st.toast("Removed " + plan_cal._strength_row(removed)["name"])


def strength_remove_controls(row: dict, key: str) -> None:
    """Remove button for a strength session. A session that was already logged needs
    a tick first, since the record of what was lifted goes with it."""
    logged = bool(row.get("completed"))
    sure = st.checkbox("Yes, delete this logged session and its weights", key=f"{key}_sure") if logged else True
    if st.button("Remove session", key=f"{key}_rm", icon=":material/delete:", disabled=not sure,
                 help="Takes this session off your calendar"):
        remove_strength(row["id"])
        st.rerun()


def strength_dialog(item_id) -> None:
    """A planned strength session: what is in it, and which day it is on."""
    row = get_strength_session(int(item_id)) if item_id is not None else None
    if not row:
        st.info("That session no longer exists.")
        return
    info = plan_cal._strength_row(row)
    st.markdown(f"**{info['name']}**")
    st.caption(fmt_day(row["date"]) + (f" · {row['duration_minutes']} min" if row.get("duration_minutes") else ""))
    for ex in info["exercises"]:
        st.markdown(f"- {ex}")
    if row.get("purpose"):
        st.markdown(f"**Why.** {row['purpose']}")
    st.caption("Strength isn't counted in training load. Log the session itself on the Strength page.")
    if not info["planned"]:
        st.caption("A session you have logged stays where it is.")
        strength_remove_controls(row, "dlg_s")
        return
    skipped = row["date"] < today.isoformat()
    if skipped:
        st.info("This session was not done on its day. Move it to another day to do it later.",
                icon=":material/event_busy:")
    new_date = st.date_input("Date", value=date.fromisoformat(row["date"]),
                             min_value=None if skipped else today, key="dlg_s_date")
    with st.container(horizontal=True):
        if st.button("Move session", key="dlg_s_save", type="primary", icon=":material/event:",
                     disabled=new_date.isoformat() == row["date"]):
            err = plan_cal.apply_move("strength", row["id"], new_date.isoformat(), today)
            if err:
                st.warning(err)
                return
            st.rerun()
        if st.button("Remove session", key="dlg_s_rm", icon=":material/delete:"):
            remove_strength(row["id"])
            st.rerun()


def render_calendar_tab() -> None:
    plan_export.tp_status("cal_tp", invite=False)
    state = plan_impact.load_plan_state(today)
    sel = plan_cal.render_month_calendar("cal")
    plan_impact_ui.render_undo_bar()
    if opened := st.session_state.pop(plan_cal.OPEN_KEY, None):
        if opened.get("kind") == "done":
            ride_analysis.open_analysis(opened.get("id"))     # a ride that was ridden
        else:
            workout_dialog(opened.get("kind"), opened.get("id"), state)
    plan_impact_ui.render_impact_panel(state)
    if sel:
        day_panel(sel)
    else:
        st.caption("Select a day to see its workouts, rides and strength, or to add a workout.")
    render_send_panels()


# ── Coach tab ──────────────────────────────────────────────────────────────────

STARTER_FALLBACK = [
    "Help me build a training block",
    "What should my focus be this week?",
    "Suggest a workout for today",
    "How is my training load looking, am I overdoing it?",
    "How should I structure my training zones?",
]
MAX_IMAGE_BYTES = 3_500_000
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def get_quick_questions(next_race=None) -> list[str]:
    qs = list(STARTER_FALLBACK)
    if next_race:
        days_out = (date.fromisoformat(next_race["date"]) - today).days
        qs.insert(0, f"Build me a plan toward {next_race['name']} in {days_out} days")
    return qs


def image_block(upload) -> dict:
    """Turn an uploaded screenshot into an image block, shrinking it if it's too big."""
    data, media_type = upload.getvalue(), upload.type
    if len(data) > MAX_IMAGE_BYTES or media_type not in IMAGE_TYPES:
        img = Image.open(io.BytesIO(data))
        img.thumbnail((2400, 2400))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=85)
        data, media_type = buf.getvalue(), "image/jpeg"
    return {"type": "image",
            "source": {"type": "base64", "media_type": media_type,
                       "data": base64.b64encode(data).decode()}}


def recent_history() -> list:
    """Recent messages for the API: consecutive same role turns are merged, and the
    list starts with a user turn (a failed send leaves two user messages in a row)."""
    merged: list[dict] = []
    for m in get_conversation_window():
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"] += "\n\n" + m["content"]
        else:
            merged.append({"role": m["role"], "content": m["content"]})
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    return merged


def queue_message(text: str) -> None:
    """Callback for a starter chip."""
    st.session_state["pending_message"] = text


def queue_resend() -> None:
    """Callback for Try again: answer the last saved user message again."""
    st.session_state["chat_resend"] = True


def clear_chat() -> None:
    from db.schema import get_conn
    conn = get_conn()
    conn.execute("DELETE FROM ai_conversations")
    conn.commit()
    conn.close()
    for k in ("chat_error", "chat_resend", "pending_message", "program_mode"):
        st.session_state.pop(k, None)


def render_memories() -> None:
    with st.expander("What your coach remembers"):
        notes = get_memories()
        if not notes:
            st.caption("Nothing yet. Tell the coach about injuries, your schedule or preferences "
                       "and it will remember them.")
        for m in notes:
            mc1, mc2 = st.columns([6, 1], vertical_alignment="center")
            mc1.markdown(f"**{m['category'].replace('_', ' ').title()}** · {m['note']}")
            if mc2.button("Forget", key=f"forget_{m['id']}", icon=":material/close:",
                          help="Forget this"):
                forget_memory(m["id"])
                st.rerun()


def render_checkin() -> None:
    from db.queries import get_report, get_reports
    start = coach_reports.checkin_week()
    key, title, prompt = coach_reports.weekly_checkin(start)
    # Saturday to Monday, until it has been run, the check in sits open at the top.
    due = today.weekday() in (5, 6, 0) and not get_report("weekly", key)
    box = st.container(border=True) if due else st.expander("Weekly check in")
    with box:
        if due:
            st.markdown(f"**Weekly check in for the week of {start:%b %-d} is ready**")
        st.caption("Your coach reviews the week and drafts the next one.")
        coach_ui.report_block("weekly", key, title, prompt,
                              button_label="Run my weekly check in", on_plan_page=True)
    past = [r for r in get_reports("weekly", limit=7) if r["ref_key"] != key]
    if past:
        with st.expander("Past check ins"):
            for r in past:
                st.markdown(f"**{r['title']}**")
                st.markdown(r["content"])
                st.divider()


def build_messages(images: list) -> list | None:
    """API messages for the reply. Attached images ride on the last user turn for this
    call only; the database keeps just the text. None when there is nothing to answer."""
    messages = recent_history()
    if not messages or messages[-1]["role"] != "user":
        return None
    if images:
        messages[-1]["content"] = [*[image_block(i) for i in images],
                                   {"type": "text", "text": messages[-1]["content"]}]
    return messages


def render_coach_tab(next_race) -> None:
    next_txt = ""
    if next_race:
        days_out = (date.fromisoformat(next_race["date"]) - today).days
        next_txt = f" · Next race **{next_race['name']}** in {days_out} days"
    stats, clear = st.columns([4, 1], vertical_alignment="center")
    stats.markdown(f"**CTL** {metrics['ctl']:.1f} · **ATL** {metrics['atl']:.1f} · "
                   f"**TSB** {metrics['tsb']:.1f} · **FTP** {ftp:.0f}W{next_txt}")

    if coach_import_error:
        st.error("A required package isn't installed. Run `pip install -r requirements.txt` to "
                 "chat with your coach here. The calendar and the Manage tab still work without it.")
        return
    if not coach_available:
        st.info("Add `ANTHROPIC_API_KEY` to your `.env` file to chat with your coach here. "
                "The calendar and the Manage tab still work without it.")
        return

    with clear.popover("Clear chat", icon=":material/delete_sweep:"):
        st.caption("This deletes the saved conversation. Memories and check ins stay.")
        if st.button("Yes, clear it", key="clear_chat_confirm", type="primary",
                     on_click=clear_chat):
            st.rerun()

    render_checkin()
    render_memories()

    # The program card sits above the chat but is filled in after the reply streams, so a draft the
    # coach has just saved shows straight away.
    program_slot = st.container()
    chat_box = st.container(height=520, border=True, autoscroll=True)
    st.markdown("**Message your coach**")
    st.caption("Enter sends. The paperclip attaches a screenshot of a workout or chart.")
    prompt = st.chat_input("Type your message...", key="coach_input", accept_file="multiple",
                           file_type=["png", "jpg", "jpeg", "gif", "webp"])

    # 1. Work out what was sent, and save the user's message before streaming so it is
    #    part of the saved history from the first draw.
    job = None
    if prompt:
        job = {"text": (prompt.text or "").strip(), "images": list(prompt.files), "save": True}
    elif (queued := st.session_state.pop("pending_message", None)):
        job = {"text": queued, "images": [], "save": True}
    elif st.session_state.pop("chat_resend", False):
        job = {"text": "", "images": [], "save": False}   # the user message is already saved

    if job:
        st.session_state.pop("chat_error", None)
        if job["save"]:
            saved = job["text"]
            if job["images"]:
                n = len(job["images"])
                saved += f"\n\n_({n} image{'s' if n > 1 else ''} attached)_"
            if saved.strip():
                save_message("user", saved.strip(),
                             {"ctl": metrics["ctl"], "atl": metrics["atl"], "tsb": metrics["tsb"]})
            else:
                job = None

    # 2. Draw the conversation, the streamed reply and the proposal card in one pass,
    #    with no rerun after, so what streams looks the same as what is saved next run.
    with chat_box:
        history = get_conversation_history(limit=20)
        if not history and not job:
            st.markdown("Ask your coach anything about building a plan, workouts, race prep, "
                        "pacing, recovery or strength. Start with one of these or type your own.")
            for i, q in enumerate(get_quick_questions(next_race)):
                st.button(q, key=f"qq_{i}", on_click=queue_message, args=(q,),
                          width="stretch")
        for i, msg in enumerate(history):
            with st.chat_message(msg["role"]):
                if job and job["images"] and i == len(history) - 1 and msg["role"] == "user":
                    for img in job["images"]:
                        st.image(img, width=320)
                st.markdown(msg["content"])

        if job:
            messages = build_messages(job["images"])
            if messages:
                proposals: list[dict] = []
                with st.chat_message("assistant"):
                    extra = (coach_context.program_rules(programs.load("draft"))
                             if program_ui.in_program_mode() else "")
                    reply, error = coach_ui.stream_reply(
                        coach_context.system_blocks(extra), messages, "medium", proposals)
                if error or not reply.strip():
                    st.session_state["chat_error"] = error or "The coach sent back an empty reply."
                    if not error:
                        st.warning(st.session_state["chat_error"])
                else:
                    save_message("assistant", reply)
                    if proposals:
                        st.session_state["proposed_workouts"] = coach_ui.merge_proposals(
                            st.session_state.get("proposed_workouts"), proposals)
        elif (err := st.session_state.get("chat_error")):
            with st.chat_message("assistant"):
                st.error(err)

        if st.session_state.get("chat_error"):
            st.button("Try again", key="chat_retry", icon=":material/refresh:",
                      on_click=queue_resend)

        coach_ui.proposal_card("proposed_workouts", on_plan_page=True)

    with program_slot:
        program_ui.draft_card(on_plan_page=True)
        if not programs.load("draft"):
            program_ui.active_card()
            program_ui.start_card()


# ── Manage tab ─────────────────────────────────────────────────────────────────

def manage_row(w: dict, prefix: str) -> None:
    wid = w["id"]
    with st.container(border=True):
        info, acts = st.columns([3, 8], vertical_alignment="center")
        info.markdown(f"**{fmt_day(w['date'])}** · **{w['name']}**")
        info.caption(workout_summary(w))
        if w.get("purpose"):
            info.caption(w["purpose"])
        with acts.container(horizontal=True, horizontal_alignment="right"):
            garmin_button(w, st, f"garmin_{prefix}_{wid}")
            fit_button(w, st, f"fit_{prefix}_{wid}")
            st.button("Edit", key=f"edit_{prefix}_{wid}", icon=":material/edit:",
                      help="Open on the calendar", on_click=start_edit, args=(w,))
            if not w.get("completed"):
                st.button("Done", key=f"done_{prefix}_{wid}", icon=":material/check_circle:",
                          help="Mark done", on_click=set_done, args=(w, True))
            if st.button("Delete", key=f"del_{prefix}_{wid}", icon=":material/delete:"):
                remove_workout(w)
                st.rerun()


def render_quick_generate() -> None:
    with st.expander("Quick Generate (no conversation)"):
        st.caption("Builds a training block scaled to your current fitness. A fast fallback "
                   "for when you just want something without a chat.")
        current_ctl = metrics["ctl"]
        race_options = {f"{r['name']} ({r['date']})": r for r in get_races(upcoming_only=True)}

        if race_options:
            chosen_race = race_options[st.selectbox("Target race", list(race_options.keys()))]
            race_date = date.fromisoformat(chosen_race["date"])
            weeks_out = max(1, (race_date - today).days // 7)
            st.info(f"{weeks_out} weeks to race · Current CTL **{current_ctl:.0f}**")
        else:
            st.warning("No upcoming races. Add one in Race Prep first.")
            chosen_race = None
            weeks_out = 8
            race_date = today + timedelta(weeks=8)

        lo = int(current_ctl)
        hi = max(min(150, int(current_ctl * 1.6) + 10), lo + 1)
        target_ctl = st.slider(
            "Target peak CTL", min_value=lo, max_value=hi,
            value=min(max(int(current_ctl * 1.2), lo), hi), step=1,
            help="The fitness (CTL) you want to arrive at race day with, before the taper drops it.",
        )
        phase_label = st.selectbox("Phase focus", list(planning.PHASE_LABELS.values()))
        phase_key = next(k for k, v in planning.PHASE_LABELS.items() if v == phase_label)

        if st.button("Generate training block", width="stretch", type="primary",
                     disabled=chosen_race is None):
            drafted = planning.generate_block(
                current_ctl, target_ctl, race_date, phase_key,
                days_per_week=int(float(get_setting("days_per_week", 0) or 0)) or None)
            new_ids = [add_workout({
                "date": w["date"], "name": w["name"], "workout_type": w["workout_type"],
                "description": w["description"], "structured_json": None,
                "tss_planned": w["tss_planned"], "notes": "",
                "phase": w.get("phase"), "week_number": w.get("week_number"),
                "purpose": w.get("purpose"), "feel": w.get("feel"),
            }) for w in drafted]
            save_phase_notes([{"name": w["phase"], **w["phase_note"]}
                              for w in drafted if w.get("phase") and w.get("phase_note")])
            if get_setting("ftp_estimated", "") == "1" and get_setting("ftp_choice", "") != "estimate":
                test_id = ftp_help.plan_test_in_block([w["date"] for w in drafted])
                if test_id:
                    new_ids.append(test_id)
            st.session_state["wizard_generated_ids"] = new_ids
            st.session_state["wizard_msg"] = (f"Generated {len(drafted)} workouts over {weeks_out} "
                                              f"weeks, targeting CTL {target_ctl} before the taper.")
            st.rerun()

        if gen_ids := st.session_state.get("wizard_generated_ids"):
            # Resolve ids to current rows once, so the count reflects workouts
            # that still exist (some may have been deleted since generating)
            # rather than the original, possibly-stale generated count.
            still_there = [w for w in (get_workout(wid) for wid in gen_ids) if w]
            if still_there:
                if msg := st.session_state.get("wizard_msg"):
                    st.success(msg)
                with st.container(horizontal=True):
                    st.button("View on calendar", key="wizard_view_cal",
                              icon=":material/calendar_month:", on_click=jump_to_day,
                              args=(min(w["date"] for w in still_there),))
                    if st.button(f"Download this block as .fit ({len(still_there)})",
                                 key="fit_wizard_block", icon=":material/download:"):
                        queue_fit_download(still_there)
            else:
                st.session_state.pop("wizard_generated_ids", None)
                st.session_state.pop("wizard_msg", None)


def render_manage_tab() -> None:
    plan_export.render(today)
    render_quick_generate()

    view = st.segmented_control("Show", ["This week", "All upcoming"], default="This week",
                                required=True, key="manage_view", label_visibility="collapsed")

    if view == "This week":
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        week = get_workouts(monday.isoformat(), sunday.isoformat())
        st.markdown(f"**{monday.strftime('%b %-d')} to {sunday.strftime('%b %-d, %Y')}**")

        to_send = [w for w in week if can_send(w) and garmin_status(w) != "sent"]
        gc1, gc2 = st.columns(2)
        with gc1:
            if garmin_auth.is_connected():
                if st.button(f"Send this week to Garmin ({len(to_send)})" if to_send
                             else "This week is on Garmin",
                             icon=":material/watch:", disabled=not to_send, key="garmin_week"):
                    queue_garmin_send(to_send)
            elif week:
                st.caption("Connect Garmin in Settings to send these workouts to your Edge or watch.")
        with gc2:
            if st.button(f"Download this week as .fit ({len(week)})" if week
                         else "No workouts this week",
                         icon=":material/download:", disabled=not week, key="fit_week"):
                queue_fit_download(week)

        render_send_panels()
        if week:
            for w in week:
                manage_row(w, "mw")
        else:
            st.info("No workouts planned for this week.")
    else:
        render_send_panels()
        upcoming = get_workouts(today.isoformat(), (today + timedelta(days=90)).isoformat())
        if not upcoming:
            st.info("No upcoming workouts in the next 90 days.")
            return
        by_week: dict[str, list] = {}
        for w in upcoming:
            d = date.fromisoformat(w["date"])
            by_week.setdefault((d - timedelta(days=d.weekday())).isoformat(), []).append(w)

        this_monday = (today - timedelta(days=today.weekday())).isoformat()
        for wk_start in sorted(by_week):
            wk = date.fromisoformat(wk_start)
            wk_tss = sum(w.get("tss_planned") or 0 for w in by_week[wk_start])
            label = (f"Week of {wk.strftime('%b %-d')} to {(wk + timedelta(days=6)).strftime('%b %-d')}"
                     f" · {wk_tss:.0f} TSS planned")
            with st.expander(label, expanded=(wk_start == this_monday)):
                if st.button("Download week as .fit", key=f"fit_wk_{wk_start}",
                             icon=":material/download:"):
                    queue_fit_download(by_week[wk_start])
                for w in by_week[wk_start]:
                    manage_row(w, "ma")


# ── Tabs ───────────────────────────────────────────────────────────────────────

_races = get_races(upcoming_only=True)
_next_race = _races[0] if _races else None

tab_cal, tab_coach, tab_manage = st.tabs([TAB_CAL, TAB_COACH, TAB_MANAGE],
                                         key="plan_tab", on_change="rerun")

with tab_cal:
    if tab_cal.open:
        render_calendar_tab()

with tab_coach:
    if tab_coach.open:
        render_coach_tab(_next_race)

with tab_manage:
    if tab_manage.open:
        render_manage_tab()
