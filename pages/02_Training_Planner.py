from __future__ import annotations
import base64
import io
import json
import re
import zipfile
import streamlit as st
from datetime import date, timedelta
from PIL import Image
from components import inject_styles, section_header, page_header

from db.schema import run_migrations
from db.queries import (get_workouts, add_workout, update_workout, delete_workout,
                         get_activities, get_setting, get_races, WORKOUT_TYPES,
                         get_workout, garmin_status, save_message, get_conversation_history,
                         get_memories, forget_memory)
import auth.garmin as garmin_auth
import garmin_workouts
import planning
from metrics.training_load import get_current_metrics
from config import ANTHROPIC_API_KEY

run_migrations()

st.set_page_config(page_title="Plan · Cycling Coach", layout="wide")
inject_styles()
page_header("Plan", "Chat with your coach to build the plan, then manage it below.")

ftp = float(get_setting("ftp_watts", 200) or 200)
today = date.today()
metrics = get_current_metrics()

GARMIN_BADGE = {"sent": "On Garmin", "changed": "Edited, resend to Garmin"}

coach_available = bool(ANTHROPIC_API_KEY) and ANTHROPIC_API_KEY != "paste_your_key_here"
coach_import_error = False
if coach_available:
    try:
        import coach_context
        from components import coach_ui
    except ImportError:
        coach_available = False
        coach_import_error = True


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "workout"


def remove_workout(w: dict) -> None:
    """Delete a planned workout, and the copy we sent to Garmin if there is one."""
    garmin_workouts.remove_from_garmin(w)
    delete_workout(w["id"])


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


def _saved_steps(w: dict):
    try:
        return garmin_workouts.check_steps(json.loads(w["structured_json"]))
    except Exception:
        return None


def _steps_for(w: dict, cache: dict):
    """
    Get or build this workout's structured steps, caching failures as error
    strings too. `cache` is the single shared step_cache (see garmin_send_panel
    and fit_download_panel) so previewing the same unconfirmed workout in both
    panels only ever calls Claude once.
    """
    wid = w["id"]
    if wid not in cache:
        steps = _saved_steps(w) if w.get("structured_json") else None
        if steps is None:
            with st.spinner(f"Turning {w['name']} into structured steps…"):
                try:
                    steps = garmin_workouts.build_steps(w)
                except garmin_workouts.WorkoutError as e:
                    steps = str(e)
        cache[wid] = steps
    return cache[wid]


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
                                   file_name=f"{w['date']}_{_slug(w['name'])}.fit",
                                   mime="application/octet-stream", width="stretch", type="primary")
            except Exception as e:
                fit_error = str(e)
        elif ready:
            try:
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w") as zf:
                    for w, steps in ready:
                        zf.writestr(f"{w['date']}_{_slug(w['name'])}.fit",
                                   garmin_workouts.to_fit_bytes(w, steps))
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


# ── Coach chat ─────────────────────────────────────────────────────────────────

if coach_available:
    def get_quick_questions(next_race=None) -> list[str]:
        qs = [
            "Help me build a training block",
            "What should my focus be this week?",
            "Suggest a workout for today",
            "How is my training load looking — am I overdoing it?",
            "How should I structure my training zones?",
        ]
        if next_race:
            days_out = (date.fromisoformat(next_race["date"]) - today).days
            qs.insert(0, f"Build me a plan toward {next_race['name']} in {days_out} days")
        return qs

    MAX_IMAGE_BYTES = 3_500_000
    IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}

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
        history = get_conversation_history(limit=18)
        while history and history[0]["role"] != "user":
            history.pop(0)
        return history

    def respond(text: str, images: list) -> None:
        """Stream the coach's reply to one message, then save the exchange."""
        text = (text or "").strip()
        with st.chat_message("user"):
            for img in images:
                st.image(img, width=320)
            if text:
                st.markdown(text)

        content = [image_block(img) for img in images]
        content.append({"type": "text", "text": text or "Take a look at this."})
        proposals: list[dict] = []
        with st.chat_message("assistant"):
            reply, error = coach_ui.stream_reply(
                coach_context.system_blocks(),
                recent_history() + [{"role": "user", "content": content}],
                "medium", proposals,
            )

        if error or not reply.strip():
            return
        saved_text = text
        if images:
            saved_text += f"\n\n_({len(images)} image{'s' if len(images) > 1 else ''} attached)_"
        save_message("user", saved_text.strip(),
                     {"ctl": metrics["ctl"], "atl": metrics["atl"], "tsb": metrics["tsb"]})
        save_message("assistant", reply)
        if proposals:
            st.session_state["proposed_workouts"] = proposals
        st.rerun()

    races = get_races(upcoming_only=True)
    next_race = races[0] if races else None

    with st.expander("Your current stats (what the coach sees)", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("CTL", f"{metrics['ctl']:.1f}")
        c2.metric("ATL", f"{metrics['atl']:.1f}")
        c3.metric("TSB", f"{metrics['tsb']:.1f}")
        c4.metric("FTP", f"{get_setting('ftp_watts', '—')}W")
        if next_race:
            days_out = (date.fromisoformat(next_race["date"]) - today).days
            st.info(f"Next race: **{next_race['name']}** — {days_out} days away")
        st.caption("The coach can also look up your full ride history, weekly zone totals, "
                   "check ins, FTP history and planner when a question needs it.")

    st.subheader("Chat with your coach")
    st.caption("Talk through a goal and have the coach propose a block — rides and strength — "
               "then review and confirm it below before it lands on your calendar.")
    quick_qs = get_quick_questions(next_race)
    cols = st.columns(3)
    for i, q in enumerate(quick_qs[:6]):
        if cols[i % 3].button(q, width="stretch", key=f"qq_{i}"):
            st.session_state["pending_message"] = q

    history = get_conversation_history(limit=20)
    if not history:
        st.info("Ask your coach anything — building a plan, workouts, race prep, pacing, "
                "recovery, strength training. You can also attach a screenshot of a workout or chart.")
    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    coach_ui.proposal_card("proposed_workouts")

    if "pending_message" in st.session_state:
        respond(st.session_state.pop("pending_message"), [])

    if prompt := st.chat_input("Ask your coach, or attach a screenshot...",
                               accept_file="multiple", file_type=["png", "jpg", "jpeg", "gif", "webp"]):
        respond(prompt.text, list(prompt.files))

    with st.sidebar:
        st.subheader("Conversation")
        if st.button("Clear conversation history", width="stretch"):
            from db.schema import get_conn
            conn = get_conn()
            conn.execute("DELETE FROM ai_conversations")
            conn.commit()
            conn.close()
            st.success("Cleared.")
            st.rerun()
        st.caption("History is saved locally and used to give the coach context between questions.")

        st.subheader("What the coach remembers")
        notes = get_memories()
        if not notes:
            st.caption("Nothing yet. Tell the coach about injuries, your schedule or preferences "
                       "and it will remember them.")
        for m in notes:
            mc1, mc2 = st.columns([5, 1])
            mc1.caption(f"**{m['category'].replace('_', ' ').title()}** · {m['note']}")
            if mc2.button("✕", key=f"forget_{m['id']}", help="Forget this"):
                forget_memory(m["id"])
                st.rerun()
elif coach_import_error:
    st.error("A required package isn't installed. Run `pip install -r requirements.txt` to chat "
             "with your coach here. The calendar, Quick Generate and Garmin/.fit tools below all "
             "still work without it.")
else:
    st.info("Add `ANTHROPIC_API_KEY` to your `.env` file to chat with your coach here. "
            "The calendar, Quick Generate and Garmin/.fit tools below all still work without it.")

st.divider()

# ── Weekly check in ───────────────────────────────────────────────────────────
import coach_reports
from db.queries import get_reports

if coach_available:
    section_header("Weekly Check In", "Your coach reviews the week and drafts the next one")
    _checkin_start = coach_reports.checkin_week()
    _key, _title, _prompt = coach_reports.weekly_checkin(_checkin_start)
    coach_ui.report_block("weekly", _key, _title, _prompt, button_label="Run my weekly check in")
    _past = [r for r in get_reports("weekly", limit=7) if r["ref_key"] != _key]
    if _past:
        with st.expander("Past check ins"):
            for r in _past:
                st.markdown(f"**{r['title']}**")
                st.markdown(r["content"])
                st.divider()
    st.divider()

# ── Week navigation ───────────────────────────────────────────────────────────
monday = today - timedelta(days=today.weekday())

if "week_offset" not in st.session_state:
    st.session_state.week_offset = 0

col_prev, col_week, col_next = st.columns([1, 4, 1])
with col_prev:
    if st.button("◀ Prev"):
        st.session_state.week_offset -= 1
with col_next:
    if st.button("Next ▶"):
        st.session_state.week_offset += 1
with col_week:
    week_start = monday + timedelta(weeks=st.session_state.week_offset)
    week_end = week_start + timedelta(days=6)
    st.markdown(f"### {week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}")

workouts = get_workouts(week_start.isoformat(), week_end.isoformat())
activities = get_activities(days_back=max(14, abs(st.session_state.week_offset) * 7 + 14))
activity_dates = {a["date"] for a in activities}

workout_by_date: dict[str, list] = {}
for w in workouts:
    workout_by_date.setdefault(w["date"], []).append(w)

# ── Weekly calendar grid ──────────────────────────────────────────────────────
day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
cols = st.columns(7)

week_tss_planned = sum(w.get("tss_planned") or 0 for w in workouts)
week_tss_actual  = sum(a.get("tss") or 0 for a in activities
                       if week_start.isoformat() <= a["date"] <= week_end.isoformat())

for i, col in enumerate(cols):
    day = week_start + timedelta(days=i)
    day_str = day.isoformat()
    day_workouts = workout_by_date.get(day_str, [])
    is_today = day == today
    has_activity = day_str in activity_dates

    with col:
        header = f"**{day_names[i]}**\n{day.strftime('%m/%d')}"
        st.markdown(f"🔵 {header}" if is_today else header)

        if day_workouts:
            for w in day_workouts:
                tss_str = f" · {w['tss_planned']:.0f} TSS" if w.get("tss_planned") else ""
                done = "✅ " if w.get("completed") else ""
                st.markdown(f"{done}**{w['name']}**{tss_str}")
                st.caption(w.get("workout_type", ""))
                if garmin_status(w) in GARMIN_BADGE:
                    st.caption(GARMIN_BADGE[garmin_status(w)])
                ec1, ec2 = st.columns(2)
                if ec1.button("✏️", key=f"edit_cal_{w['id']}", width="stretch",
                              help="Edit"):
                    st.session_state["editing_workout_id"] = w["id"]
                if ec2.button("✕", key=f"del_cal_{w['id']}", width="stretch",
                              help=f"Remove {w['name']}"):
                    remove_workout(w)
                    st.rerun()
        elif has_activity:
            act = next((a for a in activities if a["date"] == day_str), None)
            if act:
                tss_str = f" · {act['tss']:.0f} TSS" if act.get("tss") else ""
                st.markdown(f"🚴 {act['name']}{tss_str}")
        else:
            st.markdown("—")

        if st.button("+ Add", key=f"add_{day_str}", width="stretch"):
            st.session_state["add_workout_date"] = day_str
            st.session_state.pop("editing_workout_id", None)

st.caption(f"Week total — Planned: **{week_tss_planned:.0f} TSS** · Actual: **{week_tss_actual:.0f} TSS**")

gc1, gc2 = st.columns(2)
_to_send = [w for w in workouts if can_send(w) and garmin_status(w) != "sent"]
with gc1:
    if garmin_auth.is_connected():
        if st.button(f"Send this week to Garmin ({len(_to_send)})" if _to_send else "This week is on Garmin",
                     icon=":material/watch:", disabled=not _to_send, key="garmin_week"):
            queue_garmin_send(_to_send)
    elif workouts:
        st.caption("Connect Garmin in Settings to send these workouts to your Edge or watch.")
with gc2:
    if st.button(f"Download this week as .fit ({len(workouts)})" if workouts else "No workouts this week",
                 icon=":material/download:", disabled=not workouts, key="fit_week"):
        queue_fit_download(workouts)

garmin_send_panel()
fit_download_panel()
st.divider()

# ── Add / Edit workout form ───────────────────────────────────────────────────
left, right = st.columns([1, 1])

with left:
    with st.expander("Add or edit a workout manually", expanded=bool(
            st.session_state.get("editing_workout_id") or st.session_state.get("add_workout_date"))):
        editing_id = st.session_state.get("editing_workout_id")
        editing_w  = None
        if editing_id:
            all_week = get_workouts(
                (week_start - timedelta(weeks=4)).isoformat(),
                (week_end   + timedelta(weeks=12)).isoformat(),
            )
            editing_w = next((w for w in all_week if w["id"] == editing_id), None)

        form_title = f"Edit Workout — {editing_w['name']}" if editing_w else "Add Workout"
        st.subheader(form_title)
        if editing_w and st.button("✕ Cancel edit"):
            st.session_state.pop("editing_workout_id", None)
            st.rerun()

        default_date = (date.fromisoformat(editing_w["date"]) if editing_w
                        else date.fromisoformat(st.session_state.get("add_workout_date", today.isoformat())))
        default_name = editing_w["name"]        if editing_w else ""
        default_type = editing_w["workout_type"] if editing_w and editing_w.get("workout_type") in WORKOUT_TYPES else WORKOUT_TYPES[0]
        default_tss  = int(editing_w["tss_planned"] or 60) if editing_w else 60
        default_desc = editing_w.get("description") or "" if editing_w else ""

        with st.form("workout_form", clear_on_submit=not editing_w):
            w_date = st.date_input("Date", value=default_date)
            w_name = st.text_input("Workout name", value=default_name,
                                   placeholder="e.g. Threshold intervals")
            w_type = st.selectbox("Type", WORKOUT_TYPES,
                                  index=WORKOUT_TYPES.index(default_type))
            w_tss  = st.number_input("Planned TSS", min_value=0, max_value=400,
                                      value=default_tss, step=5)
            w_desc = st.text_area("Description / notes", value=default_desc,
                                  placeholder="3x10 min @ 95% FTP, 5 min rest")

            if editing_w:
                submitted = st.form_submit_button("Save Changes", width="stretch",
                                                  type="primary")
                if submitted and w_name:
                    update_workout(editing_w["id"], {
                        "name": w_name, "workout_type": w_type,
                        "description": w_desc, "tss_planned": w_tss,
                        "completed": editing_w.get("completed", 0),
                        "notes": editing_w.get("notes", ""),
                    })
                    st.session_state.pop("editing_workout_id", None)
                    st.session_state.pop("add_workout_date", None)
                    st.success(f"Updated: {w_name}")
                    st.rerun()
            else:
                submitted = st.form_submit_button("Add to Planner", width="stretch")
                if submitted and w_name:
                    add_workout({
                        "date": w_date.isoformat(), "name": w_name,
                        "workout_type": w_type, "description": w_desc,
                        "structured_json": None, "tss_planned": w_tss, "notes": "",
                    })
                    st.session_state.pop("add_workout_date", None)
                    st.success(f"Added: {w_name}")
                    st.rerun()

    # Mark complete
    if workouts:
        st.subheader("Mark Complete")
        incomplete = [w for w in workouts if not w.get("completed")]
        if incomplete:
            names = {f"{w['date']} — {w['name']}": w["id"] for w in incomplete}
            chosen = st.selectbox("Select workout", list(names.keys()))
            if st.button("Mark as Done ✅"):
                wid = names[chosen]
                w = next(w for w in workouts if w["id"] == wid)
                update_workout(wid, {**w, "completed": 1})
                st.success("Marked complete!")
                st.rerun()
        else:
            st.success("All workouts this week are complete!")

with right:
    with st.expander("Quick Generate (no conversation)", expanded=False):
        st.caption("Auto-generate a training block scaled to your current fitness — a fast "
                   "fallback for when you just want something without a chat.")

        current_ctl = metrics["ctl"]

        upcoming_races = get_races(upcoming_only=True)
        race_options = {f"{r['name']} ({r['date']})": r for r in upcoming_races}

        if race_options:
            chosen_race_name = st.selectbox("Target race", list(race_options.keys()))
            chosen_race = race_options[chosen_race_name]
            race_date = date.fromisoformat(chosen_race["date"])
            weeks_out = max(1, (race_date - today).days // 7)
            st.info(f"{weeks_out} weeks to race · Current CTL: **{current_ctl:.0f}**")
        else:
            st.warning("No upcoming races. Add one in Race Prep first.")
            chosen_race = None
            weeks_out = 8
            race_date = today + timedelta(weeks=8)

        target_ctl = st.slider(
            "Target peak CTL",
            min_value=int(current_ctl),
            max_value=min(150, int(current_ctl * 1.6) + 10),
            value=min(150, int(current_ctl * 1.2)),
            step=1,
            help="The fitness (CTL) you want to arrive at race day with, before the taper drops it.",
        )

        phase_label = st.selectbox("Phase focus", list(planning.PHASE_LABELS.values()))
        phase_key = next(k for k, v in planning.PHASE_LABELS.items() if v == phase_label)

        if st.button("Generate Training Block", width="stretch",
                     type="primary", disabled=chosen_race is None):
            drafted = planning.generate_block(current_ctl, target_ctl, race_date, phase_key)
            new_ids = [add_workout({
                "date": w["date"], "name": w["name"], "workout_type": w["workout_type"],
                "description": w["description"], "structured_json": None,
                "tss_planned": w["tss_planned"], "notes": "",
                "phase": w.get("phase"), "week_number": w.get("week_number"),
            }) for w in drafted]
            st.session_state["wizard_generated_ids"] = new_ids
            st.success(f"Generated {len(drafted)} workouts over {weeks_out} weeks. "
                       f"Targeting CTL {target_ctl} before taper.")
            st.rerun()

        if gen_ids := st.session_state.get("wizard_generated_ids"):
            # Resolve ids to current rows once, so the count reflects workouts
            # that still exist (some may have been deleted since generating)
            # rather than the original, possibly-stale generated count.
            still_there = [w for w in (get_workout(wid) for wid in gen_ids) if w]
            if still_there:
                if st.button(f"Download this block as .fit ({len(still_there)})", key="fit_wizard_block"):
                    queue_fit_download(still_there)
            else:
                st.session_state.pop("wizard_generated_ids", None)

# ── Manage existing workouts ──────────────────────────────────────────────────
st.subheader("Manage Workouts")
tab_week, tab_all = st.tabs(["This Week", "All Upcoming"])

with tab_week:
    if workouts:
        for w in workouts:
            c1, c5, c6, c2, c3, c4 = st.columns([3.6, 1.4, 1.4, 1, 1, 1])
            done_icon = "✅ " if w.get("completed") else ""
            badge = f" · _{GARMIN_BADGE[garmin_status(w)]}_" if garmin_status(w) in GARMIN_BADGE else ""
            c1.markdown(f"{done_icon}**{w['date']} · {w['name']}** — "
                        f"{w['workout_type']} · {w.get('tss_planned', '—')} TSS{badge}")
            garmin_button(w, c5, f"garmin_week_{w['id']}")
            fit_button(w, c6, f"fit_week_{w['id']}")
            if c2.button("✏️", key=f"edit_week_{w['id']}", help="Edit"):
                st.session_state["editing_workout_id"] = w["id"]
                st.rerun()
            if not w.get("completed"):
                if c3.button("✅", key=f"done_week_{w['id']}", help="Mark complete"):
                    update_workout(w["id"], {**w, "completed": 1})
                    st.rerun()
            if c4.button("🗑", key=f"del_week_{w['id']}", help="Delete"):
                remove_workout(w)
                st.rerun()
    else:
        st.info("No workouts planned for this week.")

with tab_all:
    all_upcoming = get_workouts(today.isoformat(), (today + timedelta(days=90)).isoformat())
    if all_upcoming:
        by_week: dict[str, list] = {}
        for w in all_upcoming:
            w_date = date.fromisoformat(w["date"])
            wk_mon = (w_date - timedelta(days=w_date.weekday())).isoformat()
            by_week.setdefault(wk_mon, []).append(w)

        for wk_start_str in sorted(by_week.keys()):
            wk = date.fromisoformat(wk_start_str)
            wk_end = wk + timedelta(days=6)
            wk_tss = sum(w.get("tss_planned") or 0 for w in by_week[wk_start_str])
            label = (f"Week of {wk.strftime('%b %d')} – {wk_end.strftime('%b %d')}"
                     f"  ·  {wk_tss:.0f} TSS planned")
            with st.expander(label, expanded=(wk_start_str == week_start.isoformat())):
                wk_c1, wk_c2 = st.columns([5, 1.4])
                if wk_c2.button("Download week as .fit", key=f"fit_wk_{wk_start_str}"):
                    queue_fit_download(by_week[wk_start_str])
                for w in by_week[wk_start_str]:
                    c1, c4, c6, c2, c3 = st.columns([4, 1.4, 1.4, 1, 1])
                    done_icon = "✅ " if w.get("completed") else ""
                    badge = f" · _{GARMIN_BADGE[garmin_status(w)]}_" if garmin_status(w) in GARMIN_BADGE else ""
                    c1.markdown(f"{done_icon}**{w['date']} · {w['name']}** — "
                                f"{w['workout_type']} · {w.get('tss_planned', '—')} TSS{badge}")
                    garmin_button(w, c4, f"garmin_all_{w['id']}")
                    fit_button(w, c6, f"fit_all_{w['id']}")
                    if c2.button("✏️", key=f"edit_all_{w['id']}", help="Edit"):
                        st.session_state["editing_workout_id"] = w["id"]
                        st.rerun()
                    if c3.button("🗑", key=f"del_all_{w['id']}", help="Delete"):
                        remove_workout(w)
                        st.rerun()
    else:
        st.info("No upcoming workouts in the next 90 days.")
