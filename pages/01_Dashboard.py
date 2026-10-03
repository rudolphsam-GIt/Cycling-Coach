from __future__ import annotations

import html
import json
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import date, datetime, timedelta

from db.schema import run_migrations
from db.queries import (get_activities, get_setting, get_races, get_workouts,
                        get_weekly_tss_summary, log_wellness, get_wellness,
                        get_recovery_range, is_ride)
from metrics.training_load import compute_pmc, get_current_metrics
from metrics.zones import get_power_zones, get_hr_zones
from components import charts, theme
from components.cards import metric_card, section_header, tsb_banner, page_header

run_migrations()


def _rgba(hex_color: str, alpha: float) -> str:
    """Turn a theme hex color into an rgba() string with the given alpha."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


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
page_header(f"{_greeting}{', ' + _first_name if _first_name else ''}",
            date.today().strftime("%A, %B %-d"), eyebrow="Today")

from components.onboarding import render_onboarding_welcome_banner
render_onboarding_welcome_banner()

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
    _rec = get_recovery_range((date.today() - timedelta(days=1)).isoformat(), today_str)
    _r = _rec[-1] if _rec else None
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
        _status = f" · HRV {_r['hrv_status'].lower()}" if _r.get("hrv_status") else ""
        st.markdown(
            f"<div class='today-card'><div class='today-card-label'>Recovery · Garmin{_status}</div>"
            f"<div class='today-stats'>{_stats_html}</div></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div class='today-card'><div class='today-card-label'>Recovery</div>"
            "<div class='today-card-title'>No recovery data yet</div>"
            "<div class='today-card-body'>Connect Garmin in Settings to see sleep, HRV, "
            "resting heart rate and readiness here.</div></div>",
            unsafe_allow_html=True,
        )

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
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    metric_card("Fitness", f"{ctl:.1f}", delta=f"{ramp:+.1f} /wk" if ramp is not None else None,
                tone="var(--fitness)", hint="CTL")
with col2:
    metric_card("Fatigue", f"{atl:.1f}", tone="var(--fatigue)", hint="ATL")
with col3:
    metric_card("Form", f"{tsb:+.1f}",
                tone="var(--good)" if tsb >= 5 else "var(--bad)" if tsb <= -20 else "var(--warn)",
                hint="TSB")
with col4:
    metric_card("FTP", f"{ftp:.0f} W", small_value=True, tone="var(--text-1)")
with col5:
    metric_card("W / kg", f"{w_per_kg:.2f}", small_value=True, tone="var(--text-1)")

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
    st.info(f"Your weekly check in for the week of {_week:%b %d} is ready. "
            "Open **Plan** to run it.")

# ── PMC Chart ────────────────────────────────────────────────────────────────
section_header("Performance Management Chart", "120-day CTL, ATL, TSB and daily TSS")

start = date.today() - timedelta(days=120)
end = date.today()
init_ctl_val = float(get_setting("ctl_start", 0) or 0)
pmc = compute_pmc(start, end, init_ctl_val)

races = get_races(upcoming_only=False)
race_dates = {r["date"] for r in races if start.isoformat() <= r["date"] <= end.isoformat()}

pmc["date"] = pd.to_datetime(pmc["date"])

fig = make_subplots(specs=[[{"secondary_y": True}]])

# TSS bars (background layer, neutral so the lines stand out)
fig.add_trace(
    go.Bar(
        x=pmc["date"],
        y=pmc["tss"],
        name="Daily TSS",
        marker_color=_rgba(theme.TEXT3, 0.35),
        marker_line_width=0,
        width=86400000,
        hovertemplate="<b>TSS</b>: %{y:.0f}<extra></extra>",
    ),
    secondary_y=False,
)

fig.add_trace(
    go.Scatter(
        x=pmc["date"],
        y=pmc["ctl"],
        name="CTL (fitness)",
        line=dict(color=charts.SERIES["ctl"], width=2.5),
        hovertemplate="<b>CTL</b>: %{y:.1f}<extra></extra>",
    ),
    secondary_y=False,
)

fig.add_trace(
    go.Scatter(
        x=pmc["date"],
        y=pmc["atl"],
        name="ATL (fatigue)",
        line=dict(color=charts.SERIES["atl"], width=2.5),
        hovertemplate="<b>ATL</b>: %{y:.1f}<extra></extra>",
    ),
    secondary_y=False,
)

# TSB line on the secondary axis with a subtle fill
fig.add_trace(
    go.Scatter(
        x=pmc["date"],
        y=pmc["tsb"],
        name="TSB (form)",
        line=dict(color=charts.SERIES["tsb"], width=2.5),
        fill="tozeroy",
        fillcolor=_rgba(charts.SERIES["tsb"], 0.08),
        hovertemplate="<b>TSB</b>: %{y:+.1f}<extra></extra>",
    ),
    secondary_y=True,
)

for rd in race_dates:
    fig.add_vline(
        x=pd.Timestamp(rd).value,
        line_dash="dash",
        line_color=theme.RACE,
        line_width=1.5,
        annotation_text="Race",
        annotation_position="top",
        annotation_font_size=12,
        annotation_font_color=theme.RACE,
    )

charts.apply_theme(fig, height=380, legend="top", dual_y=True)
fig.update_layout(hovermode="x unified")
fig.update_xaxes(showgrid=False, tickformat="%b %-d")
fig.update_yaxes(title_text="CTL / ATL / TSS", secondary_y=False)
fig.update_yaxes(title_text="TSB (form)", secondary_y=True,
                 title_font=dict(size=12, color=charts.SERIES["tsb"]))

charts.show(fig, key="dash_pmc")

# ── Weekly Training Summary ───────────────────────────────────────────────────
section_header("Weekly Summary", "Planned vs actual TSS and zone distribution")

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
        charts.show(tss_fig, key="dash_weekly_tss")

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
            charts.show(zone_fig, key="dash_weekly_zones")
    else:
        st.caption("Zone distribution will appear after syncing rides and using Recalculate TSS in Settings.")
else:
    st.info("No training data yet. Sync rides and add planned workouts to see your weekly summary.")

# ── Recent Activities ─────────────────────────────────────────────────────────
section_header("Recent Activities", "Last 30 days. Select a ride to see its details.")

activities = get_activities(days_back=30)
if activities:
    def _num(val):
        """Return a float, or None when the value is missing or NaN."""
        try:
            if val is None or val != val:
                return None
            return float(val)
        except (TypeError, ValueError):
            return None

    def _fmt(val, fn):
        v = _num(val)
        if v is None:
            return ""
        try:
            return fn(v)
        except Exception:
            return ""

    def _hm(seconds):
        s = _num(seconds)
        if s is None:
            return None
        return f"{int(s // 3600)}:{int((s % 3600) // 60):02d}"

    activities = sorted(activities, key=lambda a: a.get("date") or "", reverse=True)
    ride_df = pd.DataFrame([
        {
            "Date": a.get("date") or "",
            "Name": a.get("name") or "Untitled",
            "Duration": _hm(a.get("duration_seconds")),
            "Distance km": (_num(a.get("distance_meters")) / 1000
                            if _num(a.get("distance_meters")) is not None else None),
            "Avg W": _num(a.get("avg_power_watts")),
            "NP": _num(a.get("normalized_power")),
            "Avg HR": _num(a.get("avg_hr")),
            "TSS": _num(a.get("tss")),
            "IF": _num(a.get("if_value")),
        }
        for a in activities
    ])

    ride_event = st.dataframe(
        ride_df,
        hide_index=True,
        width="stretch",
        height=min(38 + 35 * len(ride_df), 420),
        key="dash_recent_rides",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Date": st.column_config.TextColumn("Date", width="small"),
            "Name": st.column_config.TextColumn("Name", width="large"),
            "Duration": st.column_config.TextColumn("Duration", width="small"),
            "Distance km": st.column_config.NumberColumn("Distance km", format="%.1f", width="small"),
            "Avg W": st.column_config.NumberColumn("Avg W", format="%d", width="small"),
            "NP": st.column_config.NumberColumn("NP", format="%d", width="small"),
            "Avg HR": st.column_config.NumberColumn("Avg HR", format="%d", width="small"),
            "TSS": st.column_config.NumberColumn("TSS", format="%d", width="small"),
            "IF": st.column_config.NumberColumn("IF", format="%.2f", width="small"),
        },
    )

    _sel_rows = list(ride_event.selection.rows) if ride_event and ride_event.selection else []
    if not _sel_rows or _sel_rows[0] >= len(activities):
        st.caption("Select a ride to see its details.")
    else:
        act = activities[_sel_rows[0]]
        duration_str = _fmt(
            act.get("duration_seconds"),
            lambda v: f"{int(v // 3600)}h {int((v % 3600) // 60)}m" if v >= 3600
                      else f"{int(v // 60)}m",
        )
        distance_str = _fmt(act.get("distance_meters"), lambda v: f"{v / 1000:.1f} km")
        power_str = _fmt(act.get("avg_power_watts"), lambda v: f"{int(v)} W")
        hr_str = _fmt(act.get("avg_hr"), lambda v: f"{int(v)} bpm")
        tss_str = _fmt(act.get("tss"), lambda v: f"{v:.0f}")
        elev_str = _fmt(act.get("elevation_gain_meters"), lambda v: f"{int(v)} m")
        np_str = _fmt(act.get("normalized_power"), lambda v: f"{int(v)} W")
        if_str = _fmt(act.get("if_value"), lambda v: f"{v:.2f}")

        zone_secs = None
        if act.get("zone_time_json"):
            try:
                z = json.loads(act["zone_time_json"])
                zone_secs = [z.get(f"z{i}_s", 0) or 0 for i in range(1, 6)]
            except Exception:
                zone_secs = None

        with st.container(border=True):
            st.markdown(f"**{act.get('name') or 'Untitled'}**, {act.get('date') or ''}")
            dc1, dc2 = st.columns([1, 2])

            with dc1:
                rows = [
                    ("Duration",   duration_str),
                    ("Distance",   distance_str),
                    ("Elevation",  elev_str),
                    ("Avg Power",  power_str),
                    ("Norm Power", np_str),
                    ("Int Factor", if_str),
                    ("Avg HR",     hr_str),
                    ("TSS",        tss_str),
                ]
                tbl = "".join(
                    f"<tr><td class='k'>{html.escape(k)}</td>"
                    f"<td class='v'>{html.escape(v)}</td></tr>"
                    for k, v in rows if v
                )
                if tbl:
                    st.markdown(f"<table class=\"kv-table\">{tbl}</table>",
                                unsafe_allow_html=True)
                else:
                    st.caption("No metrics recorded for this ride.")

            with dc2:
                if zone_secs and sum(zone_secs) > 0:
                    total_s = sum(zone_secs)
                    z_full = [
                        "Z1 Active Recovery", "Z2 Endurance",
                        "Z3 Tempo", "Z4 Threshold", "Z5 VO2 Max",
                    ]
                    zfig = go.Figure()
                    for i in range(5):
                        s = zone_secs[i]
                        if s <= 0:
                            continue
                        mins_total = int(s // 60)
                        h_part = mins_total // 60
                        m_part = mins_total % 60
                        t_str = f"{h_part}h {m_part:02d}m" if h_part else f"{m_part}m"
                        pct = s / total_s * 100
                        zfig.add_trace(go.Bar(
                            name=z_full[i],
                            x=[s / 3600],
                            y=["Zones"],
                            orientation="h",
                            marker_color=theme.ZONE_COLORS[i],
                            marker_line_width=0,
                            hovertemplate=(
                                f"<b>{z_full[i]}</b><br>"
                                f"Time: {t_str}<br>"
                                f"Share: {pct:.1f}%"
                                "<extra></extra>"
                            ),
                        ))
                    charts.apply_theme(zfig, height=80, legend="none")
                    zfig.update_layout(barmode="stack", margin=dict(l=0, r=0, t=4, b=4))
                    zfig.update_xaxes(visible=False)
                    zfig.update_yaxes(visible=False)
                    charts.show(zfig, key="dash_ride_zones")

                    ztbl = "".join(
                        f"<tr><td class='k'><span style='color:{theme.ZONE_COLORS[i]};"
                        f"font-weight:700'>Z{i + 1}</span></td>"
                        f"<td class='v'>{int(zone_secs[i] // 60)}m, "
                        f"{zone_secs[i] / total_s * 100:.0f}%</td></tr>"
                        for i in range(5) if zone_secs[i] > 30
                    )
                    if ztbl:
                        st.markdown(f"<table class=\"kv-table\">{ztbl}</table>",
                                    unsafe_allow_html=True)
                else:
                    st.caption(
                        "Zone breakdown not available. "
                        "Use Recalculate TSS in Settings to estimate zones."
                    )
else:
    st.info("No activities yet. Connect Strava or Garmin in Settings to sync your rides.")

# ── Power & HR Zones + FTP History ───────────────────────────────────────────
with st.expander("Power & HR Zones"):
    z1, z2 = st.columns(2)
    with z1:
        st.markdown("**Power Zones**")
        zones = get_power_zones(ftp)
        if zones:
            zdf = pd.DataFrame(zones)[["zone", "name", "min_watts", "max_watts"]]
            zdf["max_watts"] = zdf["max_watts"].fillna("∞").astype(str)
            st.dataframe(
                zdf.rename(columns={
                    "zone": "Zone", "name": "Name",
                    "min_watts": "Min (W)", "max_watts": "Max (W)",
                }),
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("Set FTP above to see power zones.")
    with z2:
        st.markdown("**HR Zones**")
        hrzones = get_hr_zones(lthr)
        if hrzones:
            hzdf = pd.DataFrame(hrzones)[["zone", "name", "min_bpm", "max_bpm"]]
            hzdf["max_bpm"] = hzdf["max_bpm"].fillna("∞").astype(str)
            st.dataframe(
                hzdf.rename(columns={
                    "zone": "Zone", "name": "Name",
                    "min_bpm": "Min (bpm)", "max_bpm": "Max (bpm)",
                }),
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("Set LTHR above to see HR zones.")

    # FTP history
    from db.queries import get_ftp_history
    ftp_hist = get_ftp_history()
    if len(ftp_hist) > 1:
        st.divider()
        st.markdown("**FTP History**")
        ftp_fig = go.Figure(go.Scatter(
            x=[r["date"] for r in ftp_hist],
            y=[r["ftp_watts"] for r in ftp_hist],
            mode="lines+markers",
            line=dict(color=theme.ACCENT, width=2),
            marker=dict(size=7),
            hovertemplate="<b>%{x}</b><br>FTP: %{y} W<extra></extra>",
        ))
        charts.apply_theme(ftp_fig, height=220, legend="none")
        ftp_fig.update_yaxes(title_text="FTP (W)")
        charts.show(ftp_fig, key="dash_ftp_history")
