from __future__ import annotations
import streamlit as st
import plotly.graph_objects as go
import json
from datetime import date, timedelta
from components import inject_styles, section_header

from db.schema import run_migrations
from db.queries import (get_workouts, add_workout, update_workout, delete_workout,
                         get_activities, get_setting, get_races)
from metrics.training_load import get_current_metrics

run_migrations()

st.set_page_config(page_title="Training Planner", page_icon="🗓️", layout="wide")
inject_styles()
st.title("🗓️ Training Planner")

ftp = float(get_setting("ftp_watts", 200) or 200)

WORKOUT_TYPES = ["Endurance", "Tempo", "Threshold", "VO2 Max", "Sprint/Anaerobic",
                 "Recovery", "Long Ride", "Race", "Other"]

TSS_DEFAULTS = {
    "Endurance": 60, "Tempo": 80, "Threshold": 90,
    "VO2 Max": 85, "Sprint/Anaerobic": 70, "Recovery": 30,
    "Long Ride": 150, "Race": 120, "Other": 60,
}

# ── Week navigation ───────────────────────────────────────────────────────────
today = date.today()
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
                ec1, ec2 = st.columns(2)
                if ec1.button("✏️", key=f"edit_cal_{w['id']}", use_container_width=True,
                              help="Edit"):
                    st.session_state["editing_workout_id"] = w["id"]
                if ec2.button("✕", key=f"del_cal_{w['id']}", use_container_width=True,
                              help=f"Remove {w['name']}"):
                    delete_workout(w["id"])
                    st.rerun()
        elif has_activity:
            act = next((a for a in activities if a["date"] == day_str), None)
            if act:
                tss_str = f" · {act['tss']:.0f} TSS" if act.get("tss") else ""
                st.markdown(f"🚴 {act['name']}{tss_str}")
        else:
            st.markdown("—")

        if st.button("+ Add", key=f"add_{day_str}", use_container_width=True):
            st.session_state["add_workout_date"] = day_str
            st.session_state.pop("editing_workout_id", None)

st.caption(f"Week total — Planned: **{week_tss_planned:.0f} TSS** · Actual: **{week_tss_actual:.0f} TSS**")
st.divider()

# ── Add / Edit workout form ───────────────────────────────────────────────────
left, right = st.columns([1, 1])

with left:
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
            submitted = st.form_submit_button("Save Changes", use_container_width=True,
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
            submitted = st.form_submit_button("Add to Planner", use_container_width=True)
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
    st.subheader("Periodization Wizard")
    st.caption("Auto-generate a training block scaled to your current fitness.")

    metrics = get_current_metrics()
    current_ctl = metrics["ctl"] or 40.0

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

    taper_weeks = 2 if weeks_out >= 6 else 1
    build_weeks = max(1, weeks_out - taper_weeks)

    current_weekly_tss = current_ctl * 7
    target_weekly_tss  = target_ctl  * 7

    st.caption(
        f"**{build_weeks} build weeks** → {taper_weeks} taper · "
        f"TSS ramp {current_weekly_tss:.0f} → {target_weekly_tss:.0f}/wk"
    )

    day_templates = {
        "Endurance": [
            ("Mon", "Recovery",  0.45), ("Tue", "Endurance", 0.85),
            ("Wed", "Tempo",     1.10), ("Thu", "Endurance", 0.80),
            ("Fri", None,        0.0),  ("Sat", "Long Ride", 1.75),
            ("Sun", "Recovery",  0.50),
        ],
        "Threshold": [
            ("Mon", "Recovery",  0.35), ("Tue", "Threshold", 1.25),
            ("Wed", "Endurance", 0.90), ("Thu", "VO2 Max",   1.20),
            ("Fri", None,        0.0),  ("Sat", "Long Ride", 2.00),
            ("Sun", "Endurance", 0.85),
        ],
        "Peak": [
            ("Mon", None,              0.0),  ("Tue", "Threshold",      1.10),
            ("Wed", "Recovery",        0.40), ("Thu", "Sprint/Anaerobic", 0.95),
            ("Fri", None,              0.0),  ("Sat", "Race",            1.40),
            ("Sun", "Recovery",        0.40),
        ],
    }
    phase_map = {
        "Base / Endurance": "Endurance",
        "Build / Threshold": "Threshold",
        "Peak / Sharpening": "Peak",
    }
    phase_label = st.selectbox("Phase focus", list(phase_map.keys()))
    phase_key   = phase_map[phase_label]

    if st.button("Generate Training Block", use_container_width=True,
                 type="primary", disabled=chosen_race is None):
        count = 0
        for wk in range(weeks_out):
            is_taper = wk >= build_weeks
            recovery = (not is_taper) and ((wk + 1) % 4 == 0)

            # Weekly TSS target
            if is_taper:
                taper_phase = wk - build_weeks  # 0 or 1
                multiplier  = 0.6 if taper_phase == 0 else 0.4
                week_tss = target_weekly_tss * multiplier
                tmpl = day_templates["Peak"]
            elif recovery:
                progress = wk / max(build_weeks - 1, 1)
                week_tss = (current_weekly_tss + progress *
                            (target_weekly_tss - current_weekly_tss)) * 0.65
                tmpl = day_templates[phase_key]
            else:
                progress = wk / max(build_weeks - 1, 1)
                week_tss = (current_weekly_tss +
                            progress * (target_weekly_tss - current_weekly_tss))
                tmpl = day_templates[phase_key]

            # Distribute TSS across days using template weights
            active_days = [(d, t, wt) for d, t, wt in tmpl if t and wt > 0]
            total_weight = sum(wt for _, _, wt in active_days)

            for day_offset, (day_name, w_type, weight_frac) in enumerate(tmpl):
                if not w_type or weight_frac == 0:
                    continue
                day_tss = round(week_tss * (weight_frac / total_weight))
                if day_tss < 10:
                    continue
                w_date = today + timedelta(weeks=wk, days=day_offset)
                if w_date >= race_date:
                    break
                label = "(Taper) " if is_taper else ("(Recovery) " if recovery else "")
                add_workout({
                    "date":         w_date.isoformat(),
                    "name":         f"{label}{w_type}",
                    "workout_type": w_type,
                    "description":  f"Auto-generated · {phase_label} · week {wk + 1}",
                    "structured_json": None,
                    "tss_planned":  day_tss,
                    "notes":        "",
                })
                count += 1

        st.success(f"Generated {count} workouts over {weeks_out} weeks. "
                   f"Targeting CTL {target_ctl} before taper.")
        st.rerun()

# ── Manage existing workouts ──────────────────────────────────────────────────
st.subheader("Manage Workouts")
tab_week, tab_all = st.tabs(["This Week", "All Upcoming"])

with tab_week:
    if workouts:
        for w in workouts:
            c1, c2, c3, c4 = st.columns([4, 1, 1, 1])
            done_icon = "✅ " if w.get("completed") else ""
            c1.markdown(f"{done_icon}**{w['date']} · {w['name']}** — "
                        f"{w['workout_type']} · {w.get('tss_planned', '—')} TSS")
            if c2.button("✏️", key=f"edit_week_{w['id']}", help="Edit"):
                st.session_state["editing_workout_id"] = w["id"]
                st.rerun()
            if not w.get("completed"):
                if c3.button("✅", key=f"done_week_{w['id']}", help="Mark complete"):
                    update_workout(w["id"], {**w, "completed": 1})
                    st.rerun()
            if c4.button("🗑", key=f"del_week_{w['id']}", help="Delete"):
                delete_workout(w["id"])
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
                for w in by_week[wk_start_str]:
                    c1, c2, c3 = st.columns([5, 1, 1])
                    done_icon = "✅ " if w.get("completed") else ""
                    c1.markdown(f"{done_icon}**{w['date']} · {w['name']}** — "
                                f"{w['workout_type']} · {w.get('tss_planned', '—')} TSS")
                    if c2.button("✏️", key=f"edit_all_{w['id']}", help="Edit"):
                        st.session_state["editing_workout_id"] = w["id"]
                        st.rerun()
                    if c3.button("🗑", key=f"del_all_{w['id']}", help="Delete"):
                        delete_workout(w["id"])
                        st.rerun()
    else:
        st.info("No upcoming workouts in the next 90 days.")
