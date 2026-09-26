from __future__ import annotations
import base64
import io
import streamlit as st
from PIL import Image
from datetime import date, timedelta
import json
from components import inject_styles, section_header

from db.schema import run_migrations
from db.queries import (get_setting, get_races, save_message, get_conversation_history,
                         get_memories, forget_memory)
from metrics.training_load import get_current_metrics
from config import ANTHROPIC_API_KEY

run_migrations()

st.set_page_config(page_title="AI Coach", page_icon="🤖", layout="wide")
inject_styles()
st.title("🤖 AI Cycling Coach")

if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "paste_your_key_here":
    st.error("Claude API key not configured. Add your ANTHROPIC_API_KEY to the .env file.")
    st.stop()

try:
    import coach_context
    from components import coach_ui
except ImportError:
    st.error("anthropic package not installed. Run: pip install -r requirements.txt")
    st.stop()

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
    proposals: list[dict] = []
    with st.chat_message("assistant"):
        reply, error = coach_ui.stream_reply(
            coach_context.system_blocks(),
            recent_history() + [{"role": "user", "content": content}],
            "medium", proposals,
        )

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
    if cols[i % 3].button(q, width="stretch", key=f"qq_{i}"):
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
coach_ui.proposal_card("proposed_workouts")

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
        c1, c2 = st.columns([5, 1])
        c1.caption(f"**{m['category'].replace('_', ' ').title()}** · {m['note']}")
        if c2.button("✕", key=f"forget_{m['id']}", help="Forget this"):
            forget_memory(m["id"])
            st.rerun()
