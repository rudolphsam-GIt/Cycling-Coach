from __future__ import annotations
import base64
import io
import streamlit as st
import pandas as pd
from PIL import Image
from datetime import date, timedelta
import json
from components import inject_styles, section_header

from db.schema import run_migrations
from db.queries import (get_setting, get_activities, get_races, add_workout,
                         save_message, get_conversation_history)
from metrics.training_load import get_current_metrics
from config import ANTHROPIC_API_KEY
from components.onboarding import parse_goal_keys

run_migrations()

st.set_page_config(page_title="AI Coach", page_icon="🤖", layout="wide")
inject_styles()
st.title("🤖 AI Cycling Coach")

if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "paste_your_key_here":
    st.error("Claude API key not configured. Add your ANTHROPIC_API_KEY to the .env file.")
    st.stop()

try:
    import claude_client
    import coach_tools
except ImportError:
    st.error("anthropic package not installed. Run: pip install -r requirements.txt")
    st.stop()

SYSTEM_PROMPT = """You are an expert road cycling coach with deep knowledge of:
- Periodization and training load management (CTL/ATL/TSB/PMC)
- FTP-based training zones and structured interval work
- Race strategy and tactics for road cycling
- Recovery, nutrition timing, and performance optimization
- Strength training for cyclists
- OBRA (Oregon Bicycle Racing Association) racing context

Your coaching style:
- Specific and data-driven — always reference the athlete's actual numbers when available
- Direct but supportive — give honest assessments without being harsh
- Practical — suggest workouts and tactics the athlete can actually execute
- Evidence-based — cite reasoning for recommendations

When prescribing workouts, be specific:
- Duration, intervals, power targets (% FTP or watts), rest periods
- Give alternatives if they don't have a power meter (use RPE or % of LTHR)

Keep responses focused and actionable. If the athlete's data suggests a specific issue, address it directly.

Using the athlete's data:
- The snapshot below covers the basics. Use your tools to look up anything beyond it, such as
  longer ride history, weekly zone totals, wellness check ins, FTP history or planned workouts.
- Only quote numbers that appear in the snapshot or a tool result. If the data you need isn't
  there, say what's missing instead of estimating it.
- When the athlete asks you to plan, schedule or import workouts, call propose_workouts. They
  confirm before anything is saved, so tell them to review the proposal below the chat.
- The athlete may attach screenshots, such as a workout from TrainingPeaks or Zwift, or a chart.
  Read them carefully, and if a workout screenshot should go on the planner, propose it."""


GOAL_COACHING_NOTES = {
    "speed": "Athlete's primary goal is GETTING FASTER — emphasize threshold/VO2max work and track FTP progress closely.",
    "endurance": "Athlete's primary goal is BUILDING ENDURANCE — prioritize long Z2 rides and steady weekly volume growth.",
    "weight_loss": "Athlete's primary goal is WEIGHT LOSS — favor consistent, sustainable training volume over extreme intensity; mention nutrition timing where relevant.",
    "race": "Athlete's primary goal is RACE PREP — tie recommendations back to their upcoming race and periodization.",
    "general_fitness": "Athlete's primary goal is GENERAL FITNESS — keep things low-pressure, ramp fitness gradually, avoid overtraining.",
}


def build_context() -> str:
    ftp = get_setting("ftp_watts", "unknown")
    weight = get_setting("weight_kg", "unknown")
    lthr = get_setting("lthr", "unknown")
    w_per_kg = round(float(ftp) / float(weight), 2) if (ftp and weight and ftp != "unknown" and weight != "unknown") else "unknown"
    goal_keys = parse_goal_keys(get_setting("primary_goal", ""))
    weekly_hours = get_setting("weekly_hours_target", "")

    metrics = get_current_metrics()
    activities = get_activities(days_back=14)
    races = get_races(upcoming_only=True)

    recent_rides = []
    for a in activities[:7]:
        dur = f"{int(a['duration_seconds']//3600)}h{int((a['duration_seconds']%3600)//60)}m" if a.get("duration_seconds") else "?"
        tss_str = f"TSS:{a['tss']:.0f}" if a.get("tss") else "no TSS"
        pwr_str = f"{a['avg_power_watts']:.0f}W" if a.get("avg_power_watts") else ""
        recent_rides.append(f"  - {a['date']} | {a.get('name','?')} | {dur} | {tss_str} {pwr_str}")

    next_race = races[0] if races else None
    race_str = "None scheduled"
    if next_race:
        days_out = (date.fromisoformat(next_race["date"]) - date.today()).days
        race_str = f"{next_race['name']} on {next_race['date']} ({days_out} days away)"

    newline = "\n"
    rides_str = newline.join(recent_rides) if recent_rides else "  No recent activities synced"
    tsb_label = "fresh and ready" if metrics["tsb"] > 5 else "fatigued" if metrics["tsb"] < -10 else "neutral"

    goal_notes = [GOAL_COACHING_NOTES[k] for k in goal_keys if k in GOAL_COACHING_NOTES]
    goal_note = "\n  ".join(goal_notes)
    hours_str = f"{weekly_hours} hrs/week" if weekly_hours else "unknown"

    context = f"""
ATHLETE DATA (use this to give specific coaching advice):
{f"  {goal_note}" if goal_note else ""}
  Weekly training time available: {hours_str}

Physiology:
  FTP: {ftp}W | Weight: {weight}kg | W/kg: {w_per_kg} | LTHR: {lthr}bpm

Current Training Load:
  CTL (Fitness): {metrics['ctl']:.1f}
  ATL (Fatigue): {metrics['atl']:.1f}
  TSB (Form): {metrics['tsb']:.1f} ({tsb_label})
  7-day ramp rate: {metrics['ramp_rate']:+.1f}

Recent Activities (last 14 days):
{rides_str}

Next Race: {race_str}

Today's date: {date.today().isoformat()}
"""
    return context


def get_quick_questions(next_race=None) -> list[str]:
    qs = [
        "What should my focus be this week?",
        "Suggest a workout for today",
        "How is my training load looking — am I overdoing it?",
        "What are the best recovery strategies after a hard ride?",
        "How should I structure my training zones?",
    ]
    if next_race:
        days_out = (date.fromisoformat(next_race["date"]) - date.today()).days
        qs.insert(0, f"Am I ready for {next_race['name']} in {days_out} days?")
        qs.insert(1, f"What's my race strategy for {next_race['name']}?")
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
    # The conversation sent to Claude has to start with the athlete's message.
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
    system = [
        {"type": "text", "text": SYSTEM_PROMPT},
        {"type": "text", "text": build_context()},
    ]
    proposals: list[dict] = []
    reply, error, looked_up = "", None, []

    with st.chat_message("assistant"):
        status = st.empty()
        status.caption("Thinking…")
        body = st.empty()
        events = claude_client.stream_chat(
            system,
            recent_history() + [{"role": "user", "content": content}],
            coach_tools.TOOLS,
            lambda name, args: coach_tools.run_tool(name, args, proposals),
            effort="medium",
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
            status.caption("Looked at your data: " + ", ".join(l.replace("Checking your ", "") for l in looked_up))
        else:
            status.empty()
        if error:
            st.error(error)

    # Keep failed replies out of the saved history so they don't confuse later answers.
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


# ── UI ────────────────────────────────────────────────────────────────────────

# Show current athlete snapshot
metrics = get_current_metrics()
races = get_races(upcoming_only=True)
next_race = races[0] if races else None

with st.expander("Your current stats (what the coach sees)", expanded=False):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("CTL", f"{metrics['ctl']:.1f}")
    c2.metric("ATL", f"{metrics['atl']:.1f}")
    c3.metric("TSB", f"{metrics['tsb']:.1f}")
    c4.metric("FTP", f"{get_setting('ftp_watts', '—')}W")
    if next_race:
        days_out = (date.fromisoformat(next_race["date"]) - date.today()).days
        st.info(f"Next race: **{next_race['name']}** — {days_out} days away")
    st.caption("The coach can also look up your full ride history, weekly zone totals, "
               "check ins, FTP history and planner when a question needs it.")

# Quick question buttons
st.subheader("Quick Questions")
quick_qs = get_quick_questions(next_race)
cols = st.columns(3)
for i, q in enumerate(quick_qs[:6]):
    if cols[i % 3].button(q, use_container_width=True, key=f"qq_{i}"):
        st.session_state["pending_message"] = q

st.divider()

# Conversation display
st.subheader("Conversation")
history = get_conversation_history(limit=20)

if not history:
    st.info("Ask your coach anything — workouts, race prep, pacing, recovery, strength training. "
            "You can also attach a screenshot of a workout or chart.")

for msg in history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Workouts the coach proposed, waiting for the athlete to confirm
if added := st.session_state.pop("workouts_added", None):
    st.success(f"Added {added} workout{'s' if added > 1 else ''} to your Training Planner.")

proposed = st.session_state.get("proposed_workouts")
if proposed:
    with st.container(border=True):
        st.markdown("**Proposed workouts** — review before adding to your planner")
        st.dataframe(
            pd.DataFrame(proposed).rename(columns={
                "date": "Date", "name": "Workout", "workout_type": "Type",
                "description": "Details", "tss_planned": "TSS"}),
            hide_index=True, use_container_width=True,
        )
        c1, c2 = st.columns(2)
        if c1.button("Add to Training Planner", type="primary", use_container_width=True):
            for w in proposed:
                add_workout({**w, "structured_json": None, "notes": "Planned by AI Coach"})
            st.session_state.pop("proposed_workouts")
            st.session_state["workouts_added"] = len(proposed)
            st.rerun()
        if c2.button("Discard", use_container_width=True):
            st.session_state.pop("proposed_workouts")
            st.rerun()

# Handle quick question clicks
if "pending_message" in st.session_state:
    respond(st.session_state.pop("pending_message"), [])

# Chat input
if prompt := st.chat_input("Ask your coach, or attach a screenshot...",
                           accept_file="multiple", file_type=["png", "jpg", "jpeg", "gif", "webp"]):
    respond(prompt.text, list(prompt.files))

# Clear conversation
with st.sidebar:
    st.subheader("Conversation")
    if st.button("Clear conversation history", use_container_width=True):
        from db.schema import get_conn
        conn = get_conn()
        conn.execute("DELETE FROM ai_conversations")
        conn.commit()
        conn.close()
        st.success("Cleared.")
        st.rerun()
    st.caption("History is saved locally and used to give the coach context between questions.")
