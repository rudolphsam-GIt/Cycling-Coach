from __future__ import annotations

import html
import streamlit as st
import plotly.graph_objects as go
from datetime import date, datetime, timedelta

from db.queries import (get_activities, get_setting, get_workouts,
                        get_weekly_tss_summary, log_wellness, get_wellness,
                        get_recovery_range, is_ride)
from metrics.training_load import get_current_metrics
from components import charts, checklist, ftp_help, ride_analysis, ride_detail, theme
from components.explain import help_icon, tip
from components.cards import metric_card, section_header, tsb_banner, page_header
from components.theme import rgba as _rgba
import auth.garmin as _garmin

SETTINGS_PAGE = "pages/07_Settings.py"
PLAN_PAGE = "pages/02_Training_Planner.py"
PROGRESS_PAGE = "pages/05_Dashboard_Charts.py"


def _see_all_rides() -> None:
    st.session_state["progress_tab"] = "Rides"
    st.switch_page(PROGRESS_PAGE)



# ── Load settings and metrics ─────────────────────────────────────────────────
ftp    = float(get_setting("ftp_watts", 200) or 200)
weight = float(get_setting("weight_kg", 70) or 70)
lthr   = float(get_setting("lthr", 155) or 155)

metrics = get_current_metrics()
ctl = metrics["ctl"]
atl = metrics["atl"]
tsb = metrics["tsb"]
ramp = metrics["ramp_rate"]
w_per_kg = round(ftp / weight, 2) if weight else 0.0

# ── Header ────────────────────────────────────────────────────────────────────
_hour = datetime.now().hour
_greeting = "Good morning" if _hour < 12 else "Good afternoon" if _hour < 18 else "Good evening"
_first_name = (get_setting("strava_athlete_name", "") or "").split(" ")[0]
_head, _sync = st.columns([3, 1.5], vertical_alignment="bottom")
with _head:
    page_header(f"{_greeting}{', ' + _first_name if _first_name else ''}",
                date.today().strftime("%A, %B %-d"), eyebrow="Today")
from db import schema as _schema
_owner = _schema.is_owner()
with _sync:
    if _garmin.is_connected():
        if st.button("Sync now", icon=":material/sync:", width="stretch",
                     help="Pull new rides, sleep and recovery from Garmin"):
            with st.spinner("Syncing from Garmin…"):
                _, _msg = _garmin.sync_recent()
            st.toast(_msg)
            st.rerun()
        st.caption(_garmin.last_sync_text())
    elif _owner:
        st.page_link(SETTINGS_PAGE, label="Connect Garmin", icon=":material/link:")
    else:
        st.page_link(SETTINGS_PAGE, label="Import rides", icon=":material/upload:")

from components.onboarding import render_onboarding_welcome_banner
render_onboarding_welcome_banner()

checklist.render()

tsb_banner(tsb, ctl)

# ── Today: planned workout · recovery · how you feel ──────────────────────────
today_str = date.today().isoformat()
col_plan, col_recovery, col_feel = st.columns([1.2, 1.2, 1])

with col_plan:
    _todays = get_workouts(today_str, today_str)
    if _todays:
        _w = _todays[0]
        _more = f" · +{len(_todays) - 1} more" if len(_todays) > 1 else ""
        _tss = f"{_w['tss_planned']:.0f} TSS planned" if _w.get("tss_planned") else ""
        _body = html.escape((_w.get("description") or "")[:220])
        st.markdown(
            f"<div class='today-card'><div class='today-card-label'>Today's workout{_more}</div>"
            f"<div class='today-card-title'>{html.escape(_w['name'])}</div>"
            f"<div class='today-card-body'>{html.escape(_w.get('workout_type') or '')}"
            f"{' · ' + _tss if _tss else ''}<br>{_body}</div></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div class='today-card'><div class='today-card-label'>Today's workout</div>"
            "<div class='today-card-title'>Nothing planned</div>"
            "<div class='today-card-body'>Rest, ride by feel, or ask your coach for a workout. "
            "Your weekly check in on the Plan page can fill the week for you.</div></div>",
            unsafe_allow_html=True,
        )

with col_recovery:
    _rec = get_recovery_range((date.today() - timedelta(days=21)).isoformat(), today_str)
    _r = _rec[-1] if _rec else None
    _status = _garmin.recovery_status()
    if _r:
        _stats = []
        if _r.get("sleep_hours"):
            _stats.append((f"{_r['sleep_hours']:.1f}h", "sleep"))
        if _r.get("hrv_ms"):
            _stats.append((f"{_r['hrv_ms']:.0f}", "HRV ms"))
        if _r.get("resting_hr"):
            _stats.append((f"{_r['resting_hr']}", "resting HR"))
        if _r.get("readiness") is not None:
            _stats.append((f"{_r['readiness']}", "readiness"))
        _stats_html = "".join(
            f"<div><div class='today-stat-value'>{v}</div><div class='today-stat-label'>{l}</div></div>"
            for v, l in _stats)
        _hrv = f" · HRV {_r['hrv_status'].lower()}" if _r.get("hrv_status") else ""
        _when = ""
        if _status["stale"]:
            _d = date.fromisoformat(_r["date"])
            _when = f" · {_d:%b} {_d.day}"
        _stale_note = (
            f"<div class='today-card-body'>Garmin hasn't sent sleep or recovery since "
            f"{_d:%b} {_d.day}. Open the Garmin Connect app on your phone to sync your watch.</div>"
            if _status["stale"] else "")
        st.markdown(
            f"<div class='today-card'><div class='today-card-label'>Recovery · Garmin{_hrv}{_when}</div>"
            f"<div class='today-stats'>{_stats_html}</div>{_stale_note}</div>",
            unsafe_allow_html=True,
        )
    elif _garmin.is_connected():
        st.markdown(
            "<div class='today-card'><div class='today-card-label'>Recovery</div>"
            "<div class='today-card-title'>Waiting for Garmin</div>"
            "<div class='today-card-body'>Garmin is connected but hasn't sent any sleep or recovery "
            "numbers yet. Open the Garmin Connect app on your phone to sync your watch.</div></div>",
            unsafe_allow_html=True,
        )
    elif _owner:
        st.markdown(
            "<div class='today-card'><div class='today-card-label'>Recovery</div>"
            "<div class='today-card-title'>No recovery data yet</div>"
            "<div class='today-card-body'>Connect Garmin to see sleep, HRV, "
            "resting heart rate and readiness here.</div></div>",
            unsafe_allow_html=True,
        )
        st.page_link(SETTINGS_PAGE, label="Connect Garmin in Settings", icon=":material/link:")

with col_feel:
    with st.container(border=True):
        st.markdown("<div class='today-card-label'>How do you feel?</div>", unsafe_allow_html=True)
        existing_wellness = get_wellness(today_str)
        legs = st.select_slider(
            "Legs", options=[1, 2, 3, 4, 5],
            value=existing_wellness["legs_feel"] if existing_wellness else 3,
            format_func=lambda v: ["Dead", "Heavy", "OK", "Good", "Fresh"][v - 1],
        )
        energy = st.select_slider(
            "Energy", options=[1, 2, 3, 4, 5],
            value=existing_wellness["energy"] if existing_wellness else 3,
            format_func=lambda v: ["Crashed", "Low", "OK", "Good", "High"][v - 1],
        )
        if st.button("Update" if existing_wellness else "Log how I feel", width="stretch"):
            log_wellness({"date": today_str, "legs_feel": legs, "energy": energy,
                          "sleep_hours": None, "notes": ""})
            st.toast("Logged.")
            st.rerun()

# ── Key numbers ───────────────────────────────────────────────────────────────
_gap, _help = st.columns([3, 2])
with _help:
    help_icon("key_numbers", "today_numbers", label="What do these mean?")
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    metric_card("Fitness", f"{ctl:.1f}", delta=f"{ramp:+.1f} /wk" if ramp is not None else None,
                tone="var(--fitness)", hint="CTL", tip=tip("ctl"))
with col2:
    metric_card("Fatigue", f"{atl:.1f}", tone="var(--fatigue)", hint="ATL", tip=tip("atl"))
with col3:
    metric_card("Form", f"{tsb:+.1f}",
                tone="var(--good)" if tsb >= 5 else "var(--bad)" if tsb <= -20 else "var(--warn)",
                hint="TSB", tip=tip("tsb"))
with col4:
    metric_card("FTP", f"{ftp:.0f} W", small_value=True, tone="var(--text-1)", tip=tip("ftp"))
with col5:
    metric_card("W / kg", f"{w_per_kg:.2f}", small_value=True, tone="var(--text-1)", tip=tip("wkg"))

ftp_help.render("today_ftp")

# ── Coach: latest ride review and weekly check in ────────────────────────────
import coach_reports
from components.coach_ui import report_block
from db.queries import get_report

_recent_rides = [a for a in get_activities(days_back=90) if is_ride(a)]
if _recent_rides:
    section_header("Latest Ride", "Your coach's review")
    _latest = _recent_rides[0]
    _fresh = (date.today() - date.fromisoformat(_latest["date"])).days <= 3
    _key, _title, _prompt = coach_reports.ride_review(_latest)
    report_block("ride_review", _key, _title, _prompt,
                 button_label="Review this ride", auto=_fresh)
    if len(_recent_rides) > 1:
        with st.expander("Review another ride"):
            _pick = st.selectbox(
                "Ride", _recent_rides[1:15], key="review_pick",
                format_func=lambda a: f"{a['date']} · {a.get('name') or 'Ride'}",
            )
            _k, _t, _p = coach_reports.ride_review(_pick)
            report_block("ride_review", _k, _t, _p, button_label="Review this ride")

_week = coach_reports.checkin_week()
if date.today().weekday() in (5, 6, 0) and not get_report("weekly", _week.isoformat()):
    with st.container(border=True):
        st.markdown(f"**Your weekly check in for the week of {_week:%b %d} is ready.**")
        if st.button("Open the check in", icon=":material/forum:", key="open_checkin"):
            st.session_state["plan_jump"] = "coach"
            st.switch_page(PLAN_PAGE)

# ── Weekly Training Summary ───────────────────────────────────────────────────
section_header("Weekly Summary", "Planned vs actual TSS and zone distribution",
               explain="planned_vs_done")

weekly = get_weekly_tss_summary(weeks=5)

if any(w["rides"] > 0 or w["planned_tss"] > 0 for w in weekly):
    week_labels = [f"{w['week_start'][5:]} to {w['week_end'][5:]}" for w in weekly]
    planned_vals = [w["planned_tss"] for w in weekly]
    actual_vals  = [w["actual_tss"]  for w in weekly]
    has_zone_data = any(sum(w["zone_hours"]) > 0 for w in weekly)

    if has_zone_data:
        col_tss, col_zone = st.columns([3, 2])
    else:
        col_tss = st.container()
        col_zone = None

    with col_tss:
        tss_fig = go.Figure()
        tss_fig.add_trace(go.Bar(
            name="Planned",
            x=week_labels,
            y=planned_vals,
            marker_color=_rgba(theme.TEXT3, 0.5),
            marker_line_width=0,
        ))
        tss_fig.add_trace(go.Bar(
            name="Actual",
            x=week_labels,
            y=actual_vals,
            marker_color=[
                theme.GOOD if (p == 0 or a >= p * 0.9) else
                theme.WARN if a >= p * 0.7 else theme.BAD
                for a, p in zip(actual_vals, planned_vals)
            ],
            marker_line_width=0,
        ))
        charts.apply_theme(tss_fig, height=260, legend="top")
        tss_fig.update_layout(barmode="group")
        tss_fig.update_xaxes(showgrid=False)
        tss_fig.update_yaxes(title_text="TSS")
        charts.show(tss_fig, key="dash_weekly_tss", zoom=None)

    if col_zone is not None:
        with col_zone:
            z_names = ["Z1", "Z2", "Z3", "Z4", "Z5"]
            week_zone_totals = [sum(w["zone_hours"]) for w in weekly]
            zone_fig = go.Figure()
            for i, (zname, color) in enumerate(zip(z_names, theme.ZONE_COLORS)):
                zh = [w["zone_hours"][i] for w in weekly]
                pcts = [
                    (h / t * 100) if t > 0 else 0
                    for h, t in zip(zh, week_zone_totals)
                ]
                labels = [
                    f"{int(h)}h {int((h % 1)*60):02d}m" for h in zh
                ]
                zone_fig.add_trace(go.Bar(
                    name=zname,
                    x=week_labels,
                    y=zh,
                    marker_color=color,
                    marker_line_width=0,
                    customdata=list(zip(labels, pcts)),
                    hovertemplate=(
                        f"<b>{zname}</b><br>"
                        "Time: %{customdata[0]}<br>"
                        "Share: %{customdata[1]:.1f}%"
                        "<extra></extra>"
                    ),
                ))
            charts.apply_theme(zone_fig, height=260, legend="top")
            zone_fig.update_layout(barmode="stack")
            zone_fig.update_xaxes(showgrid=False)
            zone_fig.update_yaxes(title_text="Hours")
            charts.show(zone_fig, key="dash_weekly_zones", zoom=None)
    else:
        st.caption("Time in zones appears once synced rides have power or heart rate data.")
else:
    st.info("No training data yet. Sync rides and add planned workouts to see your weekly summary.")

# ── Recent Activities ─────────────────────────────────────────────────────────
_rh, _rl = st.columns([4, 1.3], vertical_alignment="bottom")
with _rh:
    section_header("Recent Activities", "Last 30 days. Select a ride to see its details.")
with _rl:
    if st.button("See all rides", icon=":material/arrow_forward:", type="tertiary", width="stretch"):
        _see_all_rides()

activities = get_activities(days_back=30)
if activities:
    activities = sorted(activities, key=lambda a: a.get("date") or "", reverse=True)
    picked = ride_detail.ride_table(activities, key="dash_recent_rides")
    if picked:
        if st.button("Analyze this ride", key="dash_analyze", type="primary", icon=":material/query_stats:"):
            ride_analysis.open_analysis(picked["id"])
        ride_detail.ride_detail(picked, key="dash_ride")
    else:
        st.caption("Select a ride to see its details.")
else:
    st.info("No activities yet. Connect Strava or Garmin to sync your rides.")
    st.page_link(SETTINGS_PAGE, label="Connect in Settings", icon=":material/link:")
