from __future__ import annotations
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import json
from datetime import date, timedelta
from components import inject_styles, section_header

from db.schema import run_migrations
from db.queries import (add_strength_session, get_strength_sessions,
                         mark_strength_complete, get_setting)

run_migrations()

st.set_page_config(page_title="Strength Training", page_icon="💪", layout="wide")
inject_styles()
st.title("💪 Strength Training")

# ── Cycling-specific strength plans ──────────────────────────────────────────

PLANS = {
    "Off-Season / Base (Power Development)": {
        "focus": "Build raw strength and power through heavy compound movements.",
        "frequency": "2-3x per week",
        "sessions": [
            {
                "name": "Session A — Lower Power",
                "exercises": [
                    {"name": "Back Squat", "sets": 4, "reps": "6", "intensity": "75-85% 1RM",
                     "notes": "Full depth, controlled descent. Core of this phase."},
                    {"name": "Romanian Deadlift", "sets": 3, "reps": "8", "intensity": "Moderate-heavy",
                     "notes": "Hip hinge — loads glutes and hamstrings critical for cycling power."},
                    {"name": "Bulgarian Split Squat", "sets": 3, "reps": "10 each", "intensity": "Moderate",
                     "notes": "Single-leg stability and strength."},
                    {"name": "Hip Thrust", "sets": 3, "reps": "12", "intensity": "Moderate-heavy",
                     "notes": "Glute max activation — direct carryover to pedaling."},
                    {"name": "Standing Calf Raises", "sets": 3, "reps": "15", "intensity": "Heavy",
                     "notes": "Ankle push-off strength."},
                ],
            },
            {
                "name": "Session B — Upper + Core",
                "exercises": [
                    {"name": "Single-leg Leg Press", "sets": 3, "reps": "10 each", "intensity": "Moderate",
                     "notes": "Isolates each leg — catches imbalances."},
                    {"name": "Bent-over Row", "sets": 3, "reps": "10", "intensity": "Moderate",
                     "notes": "Postural strength for riding position."},
                    {"name": "Push-up / Bench Press", "sets": 3, "reps": "12", "intensity": "Moderate",
                     "notes": "Upper body balance."},
                    {"name": "Plank", "sets": 3, "reps": "45-60 sec", "intensity": "Bodyweight",
                     "notes": "Core stability reduces power leakage."},
                    {"name": "Dead Bug", "sets": 3, "reps": "10 each side", "intensity": "Bodyweight",
                     "notes": "Anti-extension core. Essential for power transfer."},
                    {"name": "Nordic Hamstring Curl", "sets": 3, "reps": "6", "intensity": "Bodyweight",
                     "notes": "Injury prevention — reduces hamstring strain risk significantly."},
                ],
            },
        ],
    },
    "Build Phase (Explosive Power)": {
        "focus": "Shift from strength to power — speed of movement matters now.",
        "frequency": "2x per week",
        "sessions": [
            {
                "name": "Session A — Power Lower",
                "exercises": [
                    {"name": "Jump Squat", "sets": 4, "reps": "6", "intensity": "30-40% 1RM",
                     "notes": "Explode up as fast as possible. Rest 2-3 min between sets."},
                    {"name": "Box Jump", "sets": 3, "reps": "5", "intensity": "Bodyweight",
                     "notes": "Maximal intent. Step down, don't jump down."},
                    {"name": "Single-leg Deadlift", "sets": 3, "reps": "8 each", "intensity": "Moderate",
                     "notes": "Balance + posterior chain."},
                    {"name": "Step-up with Knee Drive", "sets": 3, "reps": "10 each", "intensity": "Light-moderate",
                     "notes": "Mimics pedaling motion."},
                    {"name": "Hip Thrust", "sets": 3, "reps": "10", "intensity": "Heavy",
                     "notes": "Maintain glute strength from base phase."},
                ],
            },
            {
                "name": "Session B — Maintenance + Core",
                "exercises": [
                    {"name": "Goblet Squat", "sets": 3, "reps": "10", "intensity": "Moderate",
                     "notes": "Maintain squat pattern at reduced volume."},
                    {"name": "Nordic Hamstring Curl", "sets": 3, "reps": "6", "intensity": "Bodyweight",
                     "notes": "Keep this year-round for injury prevention."},
                    {"name": "Pallof Press", "sets": 3, "reps": "12 each side", "intensity": "Light",
                     "notes": "Anti-rotation core stability."},
                    {"name": "Copenhagen Plank", "sets": 3, "reps": "20-30 sec each", "intensity": "Bodyweight",
                     "notes": "Adductor and groin strength — often neglected by cyclists."},
                    {"name": "Calf Raises (single leg)", "sets": 3, "reps": "15 each", "intensity": "Bodyweight/weighted",
                     "notes": "Maintain ankle power."},
                ],
            },
        ],
    },
    "Race Season (Maintenance)": {
        "focus": "Minimize fatigue impact. Maintain neuromuscular activation at low volume.",
        "frequency": "1-2x per week",
        "sessions": [
            {
                "name": "Session A — Full Body Express (45 min)",
                "exercises": [
                    {"name": "Back Squat", "sets": 2, "reps": "5", "intensity": "80% 1RM",
                     "notes": "Keep heavy — you're just maintaining. Don't go to failure."},
                    {"name": "Deadlift", "sets": 2, "reps": "5", "intensity": "80% 1RM",
                     "notes": "Same — quality over quantity."},
                    {"name": "Hip Thrust", "sets": 2, "reps": "10", "intensity": "Heavy",
                     "notes": "Glute activation."},
                    {"name": "Nordic Hamstring Curl", "sets": 2, "reps": "6", "intensity": "Bodyweight",
                     "notes": "Never skip this in-season — injury prevention."},
                    {"name": "Core Circuit", "sets": 2, "reps": "10 min", "intensity": "Bodyweight",
                     "notes": "Plank, dead bug, pallof press — mix it up."},
                ],
            },
        ],
    },
}

# ── Phase selector ────────────────────────────────────────────────────────────
col_plan, col_log = st.columns([2, 1])

with col_plan:
    selected_phase = st.selectbox("Training Phase", list(PLANS.keys()))
    plan = PLANS[selected_phase]
    st.info(f"**Focus:** {plan['focus']} · **Frequency:** {plan['frequency']}")

    for session in plan["sessions"]:
        st.subheader(session["name"])
        df = pd.DataFrame(session["exercises"])
        st.dataframe(
            df.rename(columns={"name": "Exercise", "sets": "Sets", "reps": "Reps",
                                "intensity": "Intensity", "notes": "Notes"}),
            hide_index=True, use_container_width=True,
        )

        if st.button(f"Log: {session['name']}", key=f"log_{session['name']}"):
            st.session_state["log_session"] = session["name"]
            st.session_state["log_exercises"] = session["exercises"]

# ── Log a session ─────────────────────────────────────────────────────────────
with col_log:
    st.subheader("Log Completed Session")

    if "log_session" in st.session_state:
        session_name = st.session_state["log_session"]
        exercises = st.session_state["log_exercises"]

        with st.form("log_form"):
            st.markdown(f"**{session_name}**")
            log_date = st.date_input("Date", value=date.today())
            duration = st.number_input("Duration (minutes)", 20, 180, 60)
            notes = st.text_area("Notes", placeholder="How did it go? Any PRs?")

            # Quick weight logging for key lifts
            weights = {}
            for ex in exercises:
                if ex.get("intensity") not in ("Bodyweight",) and "%" not in ex.get("intensity", ""):
                    w = st.number_input(f"{ex['name']} — weight used (kg)",
                                        min_value=0.0, max_value=300.0,
                                        value=0.0, step=2.5, key=f"w_{ex['name']}")
                    weights[ex["name"]] = w

            if st.form_submit_button("Save Session ✅"):
                # Attach logged weights to exercises
                enriched = []
                for ex in exercises:
                    row = dict(ex)
                    if ex["name"] in weights:
                        row["weight_kg"] = weights[ex["name"]]
                    enriched.append(row)

                add_strength_session({
                    "date": log_date.isoformat(),
                    "plan_week": None,
                    "exercises_json": json.dumps(enriched),
                    "duration_minutes": duration,
                    "notes": f"{session_name} | {notes}",
                })
                st.session_state.pop("log_session", None)
                st.session_state.pop("log_exercises", None)
                st.success("Session logged!")
                st.rerun()
    else:
        st.info("Click 'Log' next to a session to record it here.")

    # ── Session history ───────────────────────────────────────────────────────
    st.subheader("Recent Sessions")
    sessions = get_strength_sessions(days_back=60)
    if sessions:
        for s in sessions[:10]:
            exercises = json.loads(s["exercises_json"]) if s.get("exercises_json") else []
            ex_names = ", ".join(e["name"] for e in exercises[:3])
            if len(exercises) > 3:
                ex_names += f" +{len(exercises)-3} more"
            st.markdown(f"**{s['date']}** · {s.get('notes', '')[:50]}")
            st.caption(f"{s.get('duration_minutes', '?')} min · {ex_names}")
    else:
        st.info("No sessions logged yet.")

# ── Progress tracker ──────────────────────────────────────────────────────────
st.divider()
st.subheader("Strength Progress")

sessions_all = get_strength_sessions(days_back=180)
lift_data: dict[str, list] = {}

for s in sessions_all:
    if not s.get("exercises_json"):
        continue
    try:
        exercises = json.loads(s["exercises_json"])
    except Exception:
        continue
    for ex in exercises:
        if ex.get("weight_kg") and ex["weight_kg"] > 0:
            lift_data.setdefault(ex["name"], []).append({
                "date": s["date"], "weight_kg": ex["weight_kg"]
            })

if lift_data:
    lift_names = list(lift_data.keys())
    selected_lift = st.selectbox("Track lift", lift_names)
    lift_df = pd.DataFrame(lift_data[selected_lift]).sort_values("date")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=lift_df["date"], y=lift_df["weight_kg"],
                              mode="lines+markers", name=selected_lift,
                              line=dict(color="#2196F3", width=2),
                              marker=dict(size=8)))
    fig.update_layout(height=280, plot_bgcolor="#1C1F2E",
                       yaxis_title="Weight (kg)", xaxis_title="Date",
                       margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Log sessions with weights to see your strength progress over time.")

# ── Cycling-specific guidance ─────────────────────────────────────────────────
with st.expander("Why these exercises? Cycling strength rationale"):
    st.markdown("""
**Key principles for cyclist strength training:**

- **Posterior chain dominance** — Glutes, hamstrings, and calves do most of the work on a bike.
  Squats, deadlifts, and hip thrusts build this foundation.

- **Single-leg focus** — Cycling is a unilateral sport. Bulgarian split squats and single-leg
  presses catch left/right imbalances that bilateral work hides.

- **Nordic curls are non-negotiable** — Studies show they reduce hamstring injury risk by ~50%.
  Cyclists are high-risk due to repetitive hip flexion.

- **Core = power transfer** — A weak core leaks power from the legs to the handlebars.
  Dead bugs and Pallof presses (anti-rotation) are more cycling-specific than crunches.

- **Race season: cut volume, keep intensity** — 2 sets at 80% 1RM maintains strength
  with minimal fatigue. Dropping to bodyweight-only during race season leads to fast
  detraining (4-6 weeks).

- **Time your sessions** — Never do heavy legs the day before a hard ride or race.
  Best slots: Monday (after rest day) and Thursday (well before weekend rides).
    """)
