from __future__ import annotations
import streamlit as st
from datetime import date, timedelta
import json
from components import inject_styles, section_header

from db.schema import run_migrations
from db.queries import (get_setting, get_activities, get_races,
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
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
except ImportError:
    st.error("anthropic package not installed. Run: pip install anthropic")
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

Keep responses focused and actionable. If the athlete's data suggests a specific issue, address it directly."""


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


def ask_claude(user_message: str, history: list, context: str) -> str:
    messages = history + [{"role": "user", "content": user_message}]
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": context,
                },
            ],
            messages=messages,
        )
        return response.content[0].text
    except Exception as e:
        return f"Error reaching Claude: {e}\n\nCheck that your ANTHROPIC_API_KEY is correct in the .env file."


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
    st.info("Ask your coach anything — workouts, race prep, pacing, recovery, strength training.")

for msg in history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Handle quick question clicks
if "pending_message" in st.session_state:
    pending = st.session_state.pop("pending_message")
    with st.chat_message("user"):
        st.markdown(pending)
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            context = build_context()
            fresh_history = get_conversation_history(limit=18)
            reply = ask_claude(pending, fresh_history, context)
        st.markdown(reply)
    save_message("user", pending, {"ctl": metrics["ctl"], "atl": metrics["atl"], "tsb": metrics["tsb"]})
    save_message("assistant", reply)
    st.rerun()

# Chat input
if prompt := st.chat_input("Ask your coach..."):
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            context = build_context()
            fresh_history = get_conversation_history(limit=18)
            reply = ask_claude(prompt, fresh_history, context)
        st.markdown(reply)
    save_message("user", prompt, {"ctl": metrics["ctl"], "atl": metrics["atl"], "tsb": metrics["tsb"]})
    save_message("assistant", reply)
    st.rerun()

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
