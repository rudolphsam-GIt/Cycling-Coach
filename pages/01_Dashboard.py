from __future__ import annotations

import json
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import date, timedelta

from db.schema import run_migrations
from db.queries import (get_activities, get_setting, get_races,
                        get_weekly_tss_summary, log_wellness, get_wellness)
from metrics.training_load import compute_pmc, get_current_metrics
from metrics.zones import get_power_zones, get_hr_zones
from components.styles import inject_styles
from components.cards import metric_card, section_header, tsb_banner, activity_card

run_migrations()

st.set_page_config(page_title="Dashboard", page_icon="🚴", layout="wide")
inject_styles()

# ── Sidebar: today's check-in only ───────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📋 How do you feel today?")
    today_str = date.today().isoformat()
    existing_wellness = get_wellness(today_str)

    legs_default   = existing_wellness["legs_feel"] if existing_wellness else 3
    energy_default = existing_wellness["energy"]    if existing_wellness else 3

    legs = st.select_slider(
        "Legs", options=[1, 2, 3, 4, 5], value=legs_default,
        format_func=lambda v: ["💀 Dead", "😓 Heavy", "😐 OK", "😊 Good", "🔥 Fresh"][v - 1],
    )
    energy = st.select_slider(
        "Energy", options=[1, 2, 3, 4, 5], value=energy_default,
        format_func=lambda v: ["😴 Crashed", "😩 Low", "😐 OK", "😊 Good", "⚡ High"][v - 1],
    )
    btn_label = "Update" if existing_wellness else "Log"
    if st.button(btn_label, use_container_width=True):
        log_wellness({"date": today_str, "legs_feel": legs, "energy": energy,
                      "sleep_hours": None, "notes": ""})
        st.success("Logged!")
        st.rerun()

# ── Page title ────────────────────────────────────────────────────────────────
st.markdown(
    "<h1 style='font-size:1.7rem;font-weight:700;color:#111827;"
    "margin-bottom:0.1rem;'>Training Dashboard</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    f"<p style='font-size:0.82rem;color:#9CA3AF;margin-top:0;margin-bottom:1.2rem;'>"
    f"{date.today().strftime('%A, %B %-d, %Y')}</p>",
    unsafe_allow_html=True,
)

from components.onboarding import render_onboarding_welcome_banner
render_onboarding_welcome_banner()

# ── Load settings ────────────────────────────────────────────────────────────
ftp    = float(get_setting("ftp_watts", 200) or 200)
weight = float(get_setting("weight_kg", 70) or 70)
lthr   = float(get_setting("lthr", 155) or 155)

# ── Compute metrics ───────────────────────────────────────────────────────────
metrics = get_current_metrics()
ctl = metrics["ctl"]
atl = metrics["atl"]
tsb = metrics["tsb"]
ramp = metrics["ramp_rate"]
w_per_kg = round(ftp / weight, 2) if weight else 0.0

# ── Metric cards row ──────────────────────────────────────────────────────────
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    delta_label = f"{ramp:+.1f} /wk" if ramp is not None else None
    metric_card(
        label="CTL — Fitness",
        value=f"{ctl:.1f}",
        delta=delta_label,
        icon="📈",
    )

with col2:
    metric_card(
        label="ATL — Fatigue",
        value=f"{atl:.1f}",
        icon="🔥",
    )

with col3:
    tsb_delta_class = "metric-delta-up" if tsb >= 0 else "metric-delta-down"
    metric_card(
        label="TSB — Form",
        value=f"{tsb:+.1f}",
        icon="⚖️",
    )

with col4:
    metric_card(
        label="FTP",
        value=f"{ftp}w",
        icon="⚡",
        small_value=True,
    )

with col5:
    metric_card(
        label="W / kg",
        value=f"{w_per_kg:.2f}",
        icon="🏋️",
        small_value=True,
    )

st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

# ── TSB Status banner ─────────────────────────────────────────────────────────
tsb_banner(tsb, ctl)

st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

# ── Today's wellness strip ────────────────────────────────────────────────────
_today_w = get_wellness(date.today().isoformat())
if _today_w:
    _leg_labels  = ["💀 Dead", "😓 Heavy", "😐 OK", "😊 Good", "🔥 Fresh"]
    _eng_labels  = ["😴 Crashed", "😩 Low", "😐 OK", "😊 Good", "⚡ High"]
    _leg_str = _leg_labels[(_today_w["legs_feel"] or 3) - 1]
    _eng_str = _eng_labels[(_today_w["energy"]    or 3) - 1]
    _note_part = f" · {_today_w['notes']}" if _today_w.get("notes") else ""
    st.markdown(
        f"<div style='background:#1C1F2E;border:1px solid #2E3250;border-radius:8px;"
        f"padding:8px 16px;font-size:0.82rem;color:#94A3B8;margin-bottom:12px;'>"
        f"<b style='color:#E8ECF4'>Today</b> &nbsp;·&nbsp; "
        f"Legs: <b style='color:#CBD5E1'>{_leg_str}</b> &nbsp;·&nbsp; "
        f"Energy: <b style='color:#CBD5E1'>{_eng_str}</b>{_note_part}</div>",
        unsafe_allow_html=True,
    )

# ── PMC Chart ────────────────────────────────────────────────────────────────
section_header("Performance Management Chart", "120-day CTL · ATL · TSB · Daily TSS")

start = date.today() - timedelta(days=120)
end = date.today()
init_ctl_val = float(get_setting("ctl_start", 0) or 0)
pmc = compute_pmc(start, end, init_ctl_val)

races = get_races(upcoming_only=False)
race_dates = {r["date"] for r in races if start.isoformat() <= r["date"] <= end.isoformat()}

pmc["date"] = pd.to_datetime(pmc["date"])

fig = make_subplots(specs=[[{"secondary_y": True}]])

# TSS bars (background layer)
fig.add_trace(
    go.Bar(
        x=pmc["date"],
        y=pmc["tss"],
        name="Daily TSS",
        marker_color="rgba(200,210,220,0.6)",
        marker_line_width=0,
        width=86400000,
        hovertemplate="<b>TSS</b>: %{y:.0f}<extra></extra>",
    ),
    secondary_y=False,
)

# CTL line
fig.add_trace(
    go.Scatter(
        x=pmc["date"],
        y=pmc["ctl"],
        name="CTL",
        line=dict(color="#0066CC", width=2.5),
        hovertemplate="<b>CTL</b>: %{y:.1f}<extra></extra>",
    ),
    secondary_y=False,
)

# ATL line
fig.add_trace(
    go.Scatter(
        x=pmc["date"],
        y=pmc["atl"],
        name="ATL",
        line=dict(color="#FF4D00", width=2.5),
        hovertemplate="<b>ATL</b>: %{y:.1f}<extra></extra>",
    ),
    secondary_y=False,
)

# TSB line (secondary axis, subtle fill)
fig.add_trace(
    go.Scatter(
        x=pmc["date"],
        y=pmc["tsb"],
        name="TSB",
        line=dict(color="#00AA44", width=2.5),
        fill="tozeroy",
        fillcolor="rgba(0,170,68,0.07)",
        hovertemplate="<b>TSB</b>: %{y:+.1f}<extra></extra>",
    ),
    secondary_y=True,
)

# Race markers
for rd in race_dates:
    fig.add_vline(
        x=pd.Timestamp(rd).value,
        line_dash="dash",
        line_color="rgba(139,92,246,0.7)",
        line_width=1.5,
        annotation_text="Race",
        annotation_position="top",
        annotation_font_size=10,
        annotation_font_color="#7C3AED",
    )

fig.update_layout(
    height=360,
    paper_bgcolor="#1C1F2E",
    plot_bgcolor="#1C1F2E",
    hovermode="x unified",
    legend=dict(
        orientation="h",
        y=-0.18,
        x=0,
        font=dict(size=12),
        bgcolor="rgba(0,0,0,0)",
    ),
    margin=dict(l=0, r=0, t=8, b=8),
    font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif", size=12),
)

fig.update_xaxes(
    showgrid=False,
    zeroline=False,
    tickfont=dict(size=11, color="#9CA3AF"),
    tickformat="%b %-d",
)

fig.update_yaxes(
    title_text="CTL / ATL / TSS",
    title_font=dict(size=11, color="#9CA3AF"),
    tickfont=dict(size=11, color="#9CA3AF"),
    gridcolor="rgba(0,0,0,0.05)",
    gridwidth=1,
    zeroline=True,
    zerolinecolor="rgba(0,0,0,0.1)",
    zerolinewidth=1,
    secondary_y=False,
)

fig.update_yaxes(
    title_text="TSB (Form)",
    title_font=dict(size=11, color="#00AA44"),
    tickfont=dict(size=11, color="#9CA3AF"),
    gridcolor="rgba(0,0,0,0)",
    zeroline=False,
    secondary_y=True,
)

st.plotly_chart(fig, use_container_width=True)

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# ── Weekly Training Summary ───────────────────────────────────────────────────
section_header("Weekly Summary", "Planned vs actual TSS · Zone distribution")

weekly = get_weekly_tss_summary(weeks=5)

if any(w["rides"] > 0 or w["planned_tss"] > 0 for w in weekly):
    week_labels = [f"{w['week_start'][5:]}–{w['week_end'][5:]}" for w in weekly]
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
            marker_color="rgba(100,140,200,0.5)",
            marker_line_width=0,
        ))
        tss_fig.add_trace(go.Bar(
            name="Actual",
            x=week_labels,
            y=actual_vals,
            marker_color=[
                "#22c55e" if (p == 0 or a >= p * 0.9) else
                "#f59e0b" if a >= p * 0.7 else "#ef4444"
                for a, p in zip(actual_vals, planned_vals)
            ],
            marker_line_width=0,
        ))
        tss_fig.update_layout(
            barmode="group",
            height=220,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=4, b=0),
            legend=dict(orientation="h", y=1.15, x=0, font=dict(size=11)),
            font=dict(size=11, color="#9CA3AF"),
            xaxis=dict(showgrid=False, tickfont=dict(size=10)),
            yaxis=dict(showgrid=True, gridcolor="rgba(150,150,150,0.15)",
                       title="TSS", title_font=dict(size=10)),
        )
        st.plotly_chart(tss_fig, use_container_width=True)

    if col_zone is not None:
        with col_zone:
            z_colors = ["#9ecae1", "#41ab5d", "#fdae6b", "#e6550d", "#bd0026"]
            z_names  = ["Z1", "Z2", "Z3", "Z4", "Z5"]
            week_zone_totals = [sum(w["zone_hours"]) for w in weekly]
            zone_fig = go.Figure()
            for i, (zname, color) in enumerate(zip(z_names, z_colors)):
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
            zone_fig.update_layout(
                barmode="stack",
                height=220,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=4, b=0),
                legend=dict(orientation="h", y=1.15, x=0, font=dict(size=11)),
                font=dict(size=11, color="#9CA3AF"),
                xaxis=dict(showgrid=False, tickfont=dict(size=10)),
                yaxis=dict(showgrid=True, gridcolor="rgba(150,150,150,0.15)",
                           title="Hours", title_font=dict(size=10)),
            )
            st.plotly_chart(zone_fig, use_container_width=True)
    else:
        st.caption("Zone distribution will appear after syncing rides and clicking 'Recalculate TSS'.")
else:
    st.info("No training data yet. Sync rides and add planned workouts to see your weekly summary.")

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# ── Recent Activities ─────────────────────────────────────────────────────────
section_header("Recent Activities", "Last 30 days")

activities = get_activities(days_back=30)
if activities:
    def _fmt(val, fn):
        try:
            return fn(val) if val is not None and val == val else "—"
        except Exception:
            return "—"

    for act in activities[:15]:  # cap at 15 to keep page responsive
        duration_str = _fmt(
            act.get("duration_seconds"),
            lambda v: f"{int(v // 3600)}h {int((v % 3600) // 60)}m" if v >= 3600
                      else f"{int(v // 60)}m",
        )
        distance_str = _fmt(
            act.get("distance_meters"),
            lambda v: f"{v / 1000:.1f} km",
        )
        power_str = _fmt(
            act.get("avg_power_watts"),
            lambda v: f"{int(v)}w",
        )
        hr_str = _fmt(
            act.get("avg_hr"),
            lambda v: f"{int(v)} bpm",
        )
        tss_str = _fmt(
            act.get("tss"),
            lambda v: f"{v:.0f}",
        )

        zone_secs = None
        if act.get("zone_time_json"):
            try:
                z = json.loads(act["zone_time_json"])
                zone_secs = [z.get(f"z{i}_s", 0) for i in range(1, 6)]
            except Exception:
                pass

        activity_card(
            name=act.get("name") or "Untitled",
            sport_type=act.get("sport_type") or "",
            activity_date=act.get("date") or "",
            duration=duration_str,
            distance=distance_str,
            power=power_str,
            hr=hr_str,
            tss=tss_str,
            zone_seconds=zone_secs,
        )

        # Per-activity detail expander
        with st.expander("Details", expanded=False):
            dc1, dc2 = st.columns([1, 2])

            with dc1:
                # Key metrics
                elev_str = _fmt(
                    act.get("elevation_gain_meters"),
                    lambda v: f"{int(v)} m",
                )
                np_str = _fmt(
                    act.get("normalized_power"),
                    lambda v: f"{int(v)}w",
                )
                if_str = _fmt(
                    act.get("if_value"),
                    lambda v: f"{v:.2f}",
                )
                rows = [
                    ("Duration",      duration_str),
                    ("Distance",      distance_str),
                    ("Elevation",     elev_str),
                    ("Avg Power",     power_str),
                    ("Norm Power",    np_str),
                    ("Int Factor",    if_str),
                    ("Avg HR",        hr_str),
                    ("TSS",           tss_str),
                ]
                rows = [(k, v) for k, v in rows if v and v != "—"]
                tbl = "".join(
                    f"<tr><td style='color:#5B657D;font-size:0.75rem;"
                    f"padding:3px 12px 3px 0;white-space:nowrap'>{k}</td>"
                    f"<td style='color:#CBD5E1;font-size:0.75rem;"
                    f"font-weight:600;padding:3px 0'>{v}</td></tr>"
                    for k, v in rows
                )
                st.markdown(
                    f"<table style='border-collapse:collapse'>{tbl}</table>",
                    unsafe_allow_html=True,
                )

            with dc2:
                if zone_secs and sum(zone_secs) > 0:
                    total_s = sum(zone_secs)
                    z_colors = ["#9ecae1", "#41ab5d", "#fdae6b", "#e6550d", "#bd0026"]
                    z_full   = [
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
                        t_str = (f"{h_part}h {m_part:02d}m" if h_part
                                 else f"{m_part}m")
                        pct = s / total_s * 100
                        zfig.add_trace(go.Bar(
                            name=z_full[i],
                            x=[s / 3600],
                            y=["Zones"],
                            orientation="h",
                            marker_color=z_colors[i],
                            marker_line_width=0,
                            hovertemplate=(
                                f"<b>{z_full[i]}</b><br>"
                                f"Time: {t_str}<br>"
                                f"Share: {pct:.1f}%"
                                "<extra></extra>"
                            ),
                        ))
                    zfig.update_layout(
                        barmode="stack",
                        height=90,
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        margin=dict(l=0, r=0, t=0, b=0),
                        showlegend=False,
                        xaxis=dict(
                            showgrid=False, zeroline=False,
                            showticklabels=False,
                        ),
                        yaxis=dict(showgrid=False, showticklabels=False),
                    )
                    st.plotly_chart(zfig, use_container_width=True,
                                    config={"displayModeBar": False})

                    # Zone breakdown table
                    ztbl = "".join(
                        "<tr>"
                        f"<td style='padding:2px 10px 2px 0;"
                        f"font-size:0.72rem;font-weight:700;"
                        f"color:{z_colors[i]}'>"
                        f"{'Z'+str(i+1)}</td>"
                        f"<td style='padding:2px 10px 2px 0;"
                        f"font-size:0.72rem;color:#CBD5E1'>"
                        f"{int(zone_secs[i]//60)}m</td>"
                        f"<td style='font-size:0.72rem;color:#5B657D'>"
                        f"{zone_secs[i]/total_s*100:.0f}%</td>"
                        "</tr>"
                        for i in range(5) if zone_secs[i] > 30
                    )
                    st.markdown(
                        f"<table style='border-collapse:collapse'>{ztbl}</table>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.caption(
                        "Zone breakdown not available. "
                        "Click 'Recalculate TSS' in the sidebar to estimate zones."
                    )
else:
    st.info("No activities yet. Connect Strava or Garmin in the sidebar to sync your rides.")

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# ── Power & HR Zones + FTP History ───────────────────────────────────────────
with st.expander("Power & HR Zones"):
    z1, z2 = st.columns(2)
    with z1:
        st.markdown(
            "<p style='font-size:0.85rem;font-weight:700;color:#374151;"
            "margin-bottom:8px;'>Power Zones</p>",
            unsafe_allow_html=True,
        )
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
                use_container_width=True,
            )
        else:
            st.info("Set FTP above to see power zones.")
    with z2:
        st.markdown(
            "<p style='font-size:0.85rem;font-weight:700;color:#374151;"
            "margin-bottom:8px;'>HR Zones</p>",
            unsafe_allow_html=True,
        )
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
                use_container_width=True,
            )
        else:
            st.info("Set LTHR above to see HR zones.")

    # FTP history
    from db.queries import get_ftp_history
    ftp_hist = get_ftp_history()
    if len(ftp_hist) > 1:
        st.markdown("---")
        ftp_fig = go.Figure(go.Scatter(
            x=[r["date"] for r in ftp_hist],
            y=[r["ftp_watts"] for r in ftp_hist],
            mode="lines+markers",
            line=dict(color="#4D9FFF", width=2),
            marker=dict(size=7),
            hovertemplate="<b>%{x}</b><br>FTP: %{y}W<extra></extra>",
        ))
        ftp_fig.update_layout(
            title=dict(text="FTP History", font=dict(size=12, color="#94A3B8")),
            height=180,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=28, b=0),
            xaxis=dict(showgrid=False, tickfont=dict(size=10, color="#9CA3AF")),
            yaxis=dict(showgrid=True, gridcolor="rgba(150,150,150,0.15)",
                       tickfont=dict(size=10, color="#9CA3AF")),
            font=dict(color="#9CA3AF"),
        )
        st.plotly_chart(ftp_fig, use_container_width=True)
