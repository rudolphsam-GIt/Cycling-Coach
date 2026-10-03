"""
Dashboard: charts for a date range and search, in the spirit of the
TrainingPeaks dashboard. It only runs when the page is open, and each tab only
draws when it is selected.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from components import charts, data_filters, history_table, theme
from components.cards import page_header, section_header
from db.queries import (get_activities_between, get_ftp_history, get_hr_peaks_between,
                        get_peaks_between, get_races, get_recovery_range, get_setting,
                        get_workouts, set_setting)
from db.schema import run_migrations
from metrics import analysis as an
from metrics.training_load import compute_pmc

run_migrations()

page_header("Dashboard", "Training load, power and recovery for the dates and search you pick.")

ctx = data_filters.render()
f = ctx["filters"]
st.caption(data_filters.describe(ctx)
           + (" Fitness, fatigue and form always count every ride, since all of it is load."
              if f.narrowed() else ""))
data_filters.summary_tiles(ctx)

TAB_LOAD, TAB_POWER, TAB_HISTORY, TAB_RECOVERY = "Load", "Power", "History", "Recovery"
tab_load, tab_power, tab_hist, tab_rec = st.tabs([TAB_LOAD, TAB_POWER, TAB_HISTORY, TAB_RECOVERY],
                                                 key="dash_tab", on_change="rerun")


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def _pmc() -> pd.DataFrame:
    df = compute_pmc(f.start, f.end, float(get_setting("ctl_start", 0) or 0),
                     float(get_setting("atl_start", 0) or 0))
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def _date_ticks(fig) -> None:
    fig.update_xaxes(showgrid=False, tickformat="%b %-d")


# ── Load ──────────────────────────────────────────────────────────────────────

def performance_chart(pmc: pd.DataFrame) -> None:
    section_header("Performance chart", "Fitness (CTL), fatigue (ATL), form (TSB) and daily TSS",
                   explain="performance_chart")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=pmc["date"], y=pmc["tss"], name="Daily TSS",
                         marker_color=_rgba(theme.TEXT3, 0.35), marker_line_width=0,
                         hovertemplate="<b>TSS</b>: %{y:.0f}<extra></extra>"), secondary_y=False)
    for key, label in (("ctl", "CTL (fitness)"), ("atl", "ATL (fatigue)")):
        fig.add_trace(go.Scatter(x=pmc["date"], y=pmc[key], name=label,
                                 line=dict(color=charts.SERIES[key], width=2.5),
                                 hovertemplate=f"<b>{key.upper()}</b>: %{{y:.1f}}<extra></extra>"),
                      secondary_y=False)
    fig.add_trace(go.Scatter(x=pmc["date"], y=pmc["tsb"], name="TSB (form)",
                             line=dict(color=charts.SERIES["tsb"], width=2.5), fill="tozeroy",
                             fillcolor=_rgba(charts.SERIES["tsb"], 0.08),
                             hovertemplate="<b>TSB</b>: %{y:+.1f}<extra></extra>"), secondary_y=True)
    for r in get_races():
        if f.start.isoformat() <= str(r["date"]) <= f.end.isoformat():
            fig.add_vline(x=pd.Timestamp(r["date"]).value, line_dash="dash", line_color=theme.RACE,
                          line_width=1.5)
    charts.apply_theme(fig, height=380, legend="top", dual_y=True)
    fig.update_layout(hovermode="x unified")
    _date_ticks(fig)
    fig.update_yaxes(title_text="CTL / ATL / TSS", secondary_y=False)
    fig.update_yaxes(title_text="TSB", secondary_y=True, tickformat=".0f")
    charts.show(fig, key="dsh_pmc")


def weekly_volume() -> None:
    section_header("Weekly volume", "Totals per week for the rides you selected", explain="weekly_volume")
    metric = st.segmented_control("Show", list(an.WEEKLY_METRICS), default="TSS",
                                  key="dsh_week_metric", label_visibility="collapsed") or "TSS"
    weeks = an.weekly(ctx["rides"], metric, f.start, f.end)
    fig = go.Figure(go.Bar(x=[w for w, _ in weeks], y=[v for _, v in weeks], name=metric,
                           marker_color=theme.ACCENT, marker_line_width=0,
                           hovertemplate="Week of %{x|%b %-d}<br>%{y:,.1f}<extra></extra>"))
    charts.apply_theme(fig, height=280, legend="none")
    _date_ticks(fig)
    fig.update_yaxes(title_text=metric)
    charts.show(fig, key="dsh_weekly")


def planned_vs_done() -> None:
    workouts = get_workouts(f.start.isoformat(), f.end.isoformat())
    if not workouts:
        return
    section_header("Planned vs done", "Planned TSS against ridden TSS per week, every ride counted",
                   explain="planned_vs_done")
    weeks = an.planned_vs_done(workouts, ctx["all"], f.start, f.end)
    x = [w["week"] for w in weeks]
    fig = go.Figure()
    fig.add_bar(x=x, y=[w["planned"] for w in weeks], name="Planned",
                marker_color=_rgba(theme.ACCENT, 0.35), marker_line=dict(color=theme.ACCENT, width=1))
    fig.add_bar(x=x, y=[w["done"] for w in weeks], name="Done", marker_color=theme.GOOD,
                marker_line_width=0)
    charts.apply_theme(fig, height=260, legend="top")
    fig.update_layout(barmode="group", hovermode="x unified")
    _date_ticks(fig)
    charts.show(fig, key="dsh_planned")


# ── Power ─────────────────────────────────────────────────────────────────────

def peak_power() -> None:
    section_header("Peak power", "Best average power for each duration", explain="peak_power")
    ride_ids = {r["id"] for r in ctx["rides"]}
    now_rows = get_peaks_between(f.start.isoformat(), f.end.isoformat())
    curve = an.peak_curve(now_rows, ride_ids)
    with_peaks = len({p["activity_id"] for p in now_rows if p["activity_id"] in ride_ids})
    if not curve:
        st.info("No peak power yet for these rides. Peak power comes from Garmin. "
                "Open Settings and use Load peak power history to fill in past rides.",
                icon=":material/bolt:")
        return

    compare = st.segmented_control("Compare with", ["Period before", "All time"], default="Period before",
                                   key="dsh_peak_compare") or "Period before"
    if compare == "All time":
        other = an.peak_curve(get_peaks_between("0000-01-01", "9999-12-31"))
    else:
        prev = f.previous()
        prev_ids = {r["id"] for r in (ctx["previous"] or [])}
        other = an.peak_curve(get_peaks_between(prev.start.isoformat(), prev.end.isoformat()), prev_ids)

    weight = float(get_setting("weight_kg", 0) or 0)
    fig = go.Figure()
    if other:
        fig.add_scatter(x=list(other), y=[v["watts"] for v in other.values()], name=compare,
                        mode="lines", line=dict(color=theme.TEXT3, width=2, dash="dot"),
                        customdata=[[an.duration_label(d), v["date"], v["name"]] for d, v in other.items()],
                        hovertemplate="%{customdata[0]}: %{y:.0f} W<br>%{customdata[1]}, %{customdata[2]}"
                                      "<extra>" + compare + "</extra>")
    fig.add_scatter(x=list(curve), y=[v["watts"] for v in curve.values()], name="Selected rides",
                    mode="lines+markers", line=dict(color=theme.FATIGUE, width=3), marker=dict(size=6),
                    customdata=[[an.duration_label(d), v["date"], v["name"]] for d, v in curve.items()],
                    hovertemplate="%{customdata[0]}: %{y:.0f} W<br>%{customdata[1]}, %{customdata[2]}"
                                  "<extra>Selected rides</extra>")
    ticks = [d for d in an.PEAK_DURATIONS if d in curve or d in other]
    charts.apply_theme(fig, height=340, legend="top")
    fig.update_xaxes(type="log", tickvals=ticks, ticktext=[an.duration_label(d) for d in ticks],
                     showgrid=True)
    fig.update_yaxes(title_text="Watts")
    charts.show(fig, key="dsh_peaks")
    st.caption(f"From {with_peaks} of {len(ctx['rides'])} selected rides. Rides without Garmin "
               "power data (for example older Strava rides) aren't in the curve.")

    table = []
    for d in an.KEY_DURATIONS:
        best = curve.get(d)
        ref = other.get(d)
        table.append({
            "Duration": an.duration_label(d),
            "Best W": best["watts"] if best else None,
            "W/kg": round(best["watts"] / weight, 2) if best and weight else None,
            compare: ref["watts"] if ref else None,
            "Set on": best["date"] if best else "",
            "Ride": best["name"] if best else "",
        })
    st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch", column_config={
        "Best W": st.column_config.NumberColumn(format="%d"),
        compare: st.column_config.NumberColumn(format="%d"),
        "W/kg": st.column_config.NumberColumn(format="%.2f")})


def power_per_ride() -> None:
    rows = [r for r in ctx["rides"] if r.get("normalized_power") or r.get("avg_power_watts")]
    if not rows:
        return
    rows.sort(key=lambda r: r["date"])
    section_header("Power per ride", "Normalized and average power, with intensity factor", explain="np")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    names = [r.get("name") or "Ride" for r in rows]
    for key, label, color in (("normalized_power", "NP", theme.FATIGUE),
                              ("avg_power_watts", "Avg power", theme.ACCENT)):
        fig.add_trace(go.Scatter(x=[r["date"] for r in rows], y=[r.get(key) for r in rows],
                                 mode="markers", name=label, marker=dict(color=color, size=8),
                                 customdata=names,
                                 hovertemplate="%{customdata}<br>%{y:.0f} W<extra>" + label + "</extra>"),
                      secondary_y=False)
    fig.add_trace(go.Scatter(x=[r["date"] for r in rows], y=[r.get("if_value") for r in rows],
                             mode="lines", name="IF", line=dict(color=theme.TEXT3, width=1.5),
                             hovertemplate="IF %{y:.2f}<extra></extra>"), secondary_y=True)
    charts.apply_theme(fig, height=300, legend="top", dual_y=True)
    _date_ticks(fig)
    fig.update_yaxes(title_text="Watts", secondary_y=False)
    fig.update_yaxes(title_text="IF", secondary_y=True, tickformat=".2f")
    charts.show(fig, key="dsh_power_rides")


def efficiency_chart() -> None:
    pts = an.efficiency(ctx["rides"])
    if not pts:
        return
    section_header("Efficiency factor", "NP divided by average heart rate. Rising means fitter at the same effort.",
                   explain="ef")
    fig = go.Figure()
    fig.add_scatter(x=[p["date"] for p in pts], y=[p["ef"] for p in pts], mode="markers", name="Ride",
                    marker=dict(color=theme.GOOD, size=7, opacity=0.6), customdata=[p["name"] for p in pts],
                    hovertemplate="%{customdata}<br>EF %{y:.2f}<extra></extra>")
    fig.add_scatter(x=[p["date"] for p in pts], y=[p["rolling"] for p in pts], mode="lines",
                    name="5 ride average", line=dict(color=theme.GOOD, width=2.5),
                    hovertemplate="Average %{y:.2f}<extra></extra>")
    charts.apply_theme(fig, height=260, legend="top")
    _date_ticks(fig)
    charts.show(fig, key="dsh_ef")


def ftp_and_zones() -> None:
    left, right = st.columns(2)
    with left:
        hist = [h for h in get_ftp_history(limit=100) if str(h["date"]) <= f.end.isoformat()]
        section_header("FTP history", "Your FTP over time", explain="ftp")
        if len(hist) >= 2:
            x = [str(h["date"])[:10] for h in hist] + [f.end.isoformat()]
            y = [h["ftp_watts"] for h in hist] + [hist[-1]["ftp_watts"]]
            fig = go.Figure(go.Scatter(x=x, y=y, mode="lines+markers",
                                       line=dict(color=theme.ACCENT, width=2.5, shape="hv"),
                                       hovertemplate="%{x|%b %-d, %Y}: %{y} W<extra></extra>"))
            charts.apply_theme(fig, height=240, legend="none")
            fig.update_yaxes(tickformat="d", title_text="Watts")
            charts.show(fig, key="dsh_ftp")
        elif hist:
            st.metric("FTP", f"{hist[-1]['ftp_watts']} W",
                      help=f"Set on {str(hist[-1]['date'])[:10]}. Update it in Settings after a test "
                           "and the history fills in here.")
        else:
            st.caption("No FTP history yet. Set your FTP in Settings.")
    with right:
        section_header("Time in zones", "Estimated heart rate zones", explain="hr_zones")
        hours = an.zone_hours(ctx["rides"])
        if sum(hours) <= 0:
            st.caption("No zone estimates for these rides. Use Recalculate TSS in Settings.")
        else:
            total = sum(hours)
            fig = go.Figure(go.Bar(
                x=[f"Z{i + 1}" for i in range(5)], y=hours, marker_color=theme.ZONE_COLORS,
                marker_line_width=0, customdata=[h / total * 100 for h in hours],
                hovertemplate="%{x}: %{y:.1f} h (%{customdata:.0f}%)<extra></extra>"))
            charts.apply_theme(fig, height=240, legend="none")
            fig.update_yaxes(title_text="Hours")
            charts.show(fig, key="dsh_zones", zoom=None)


# ── History ───────────────────────────────────────────────────────────────────

ALL_DATES = ("0001-01-01", "9999-12-31")


def _saved_choice(label: str, options: list, setting: str, key: str) -> str:
    """A segmented control whose choice is remembered in the athlete settings."""
    saved = get_setting(setting, options[0])
    choice = st.segmented_control(label, options, key=key,
                                  default=saved if saved in options else options[0]) or saved
    if choice != saved:
        set_setting(setting, choice)
    return choice


def fitness_history() -> None:
    head, unit_col = st.columns([4, 1.2], vertical_alignment="bottom")
    with head:
        section_header("Fitness history", "Every ride, whatever the search. The week and month "
                                          "still in progress are in grey.", explain="history")
    with unit_col:
        unit = _saved_choice("Distance", ["km", "mi"], "distance_unit", "dsh_unit")

    rides = get_activities_between(*ALL_DATES)
    power, hr = get_peaks_between(*ALL_DATES), get_hr_peaks_between(*ALL_DATES)
    rows = an.period_history(rides, power, hr, date.today())

    st.markdown("**Peak power (W)**")
    history_table.render(rows, "power", unit)
    st.markdown("**Peak heart rate (bpm)**")
    if hr:
        history_table.render(rows, "hr", unit)
    else:
        st.info("No peak heart rate yet. It comes from each ride's file on Garmin. New rides get it "
                "when they sync. For older rides, open Settings and use Load peak power and heart "
                "rate history.", icon=":material/favorite:")
    if not power:
        st.caption("No peak power yet. Settings, Load peak power and heart rate history fills it in.")


def power_profile_chart() -> None:
    section_header("Power profile", "Your best power per kilo against the Allen and Coggan categories",
                   explain="power_profile")
    weight = float(get_setting("weight_kg", 0) or 0)
    if not weight:
        st.info("Add your weight in Settings to see your power profile.", icon=":material/scale:")
        return
    c1, c2 = st.columns(2)
    with c1:
        span = st.segmented_control("Rides", ["Selected dates", "All time"], default="Selected dates",
                                    key="dsh_profile_span") or "Selected dates"
    with c2:
        table = _saved_choice("Chart", ["Men", "Women"], "power_profile_table", "dsh_profile_table")

    if span == "All time":
        best = an.peak_curve(get_peaks_between(*ALL_DATES))
    else:
        best = an.peak_curve(get_peaks_between(f.start.isoformat(), f.end.isoformat()),
                             {r["id"] for r in ctx["rides"]})
    bars = an.power_profile(best, weight, table)
    if not bars:
        st.info("No peak power for these rides yet.", icon=":material/bolt:")
        return

    fig = go.Figure(go.Bar(
        x=[b["label"] for b in bars], y=[b["level"] for b in bars],
        marker_color=_rgba(theme.STRENGTH, 0.75), marker_line=dict(color=theme.STRENGTH, width=2),
        customdata=[[b["watts"], b["wkg"], b["category"], best[b["secs"]]["date"]] for b in bars],
        hovertemplate=("<b>%{x}</b><br>%{customdata[0]:.0f} W, %{customdata[1]:.2f} W/kg"
                       "<br>%{customdata[2]}<br>Set on %{customdata[3]}<extra></extra>")))
    charts.apply_theme(fig, height=420, legend="none")
    fig.update_yaxes(range=[0, 8], tickvals=[i + 0.5 for i in range(8)],
                     ticktext=an.PROFILE_CATEGORIES, showgrid=False, zeroline=False)
    for i in range(1, 8):
        fig.add_hline(y=i, line_color=theme.BORDER, line_width=1)
    fig.update_layout(bargap=0.45, margin=dict(l=8, r=8, t=12, b=8))
    charts.show(fig, key="dsh_profile", zoom=None)
    st.caption(f"{table}'s chart from Allen and Coggan, Training and Racing with a Power Meter, using "
               f"your weight of {weight:g} kg. The 20 minute bar uses 95% of your 20 minute power as an "
               "estimate of threshold. The 60 minute bar is read against threshold directly.")


# ── Recovery ──────────────────────────────────────────────────────────────────

def recovery(pmc: pd.DataFrame) -> None:
    rows = get_recovery_range(f.start.isoformat(), f.end.isoformat())
    if not rows:
        st.info("No recovery data for these dates. HRV, resting heart rate and sleep come from Garmin. "
                "Connect Garmin in Settings and sync.", icon=":material/bedtime:")
        return
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])

    section_header("HRV and resting heart rate", "With form (TSB) behind them, to read recovery against load",
                   explain="hrv")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if not pmc.empty:
        fig.add_trace(go.Scatter(x=pmc["date"], y=pmc["tsb"], name="Form (TSB)", fill="tozeroy",
                                 line=dict(color=_rgba(charts.SERIES["tsb"], 0.5), width=1),
                                 fillcolor=_rgba(charts.SERIES["tsb"], 0.08),
                                 hovertemplate="TSB %{y:+.1f}<extra></extra>"), secondary_y=True)
    if df["hrv_ms"].notna().any():
        fig.add_trace(go.Scatter(x=df["date"], y=df["hrv_ms"], name="HRV (ms)", mode="lines+markers",
                                 line=dict(color=theme.ACCENT, width=2), marker=dict(size=4),
                                 hovertemplate="HRV %{y:.0f} ms<extra></extra>"), secondary_y=False)
    if df["resting_hr"].notna().any():
        fig.add_trace(go.Scatter(x=df["date"], y=df["resting_hr"], name="Resting HR", mode="lines",
                                 line=dict(color=theme.BAD, width=2),
                                 hovertemplate="Resting HR %{y:.0f}<extra></extra>"), secondary_y=False)
    charts.apply_theme(fig, height=320, legend="top", dual_y=True)
    fig.update_layout(hovermode="x unified")
    _date_ticks(fig)
    fig.update_yaxes(title_text="ms / bpm", secondary_y=False)
    fig.update_yaxes(title_text="TSB", secondary_y=True, tickformat=".0f")
    charts.show(fig, key="dsh_hrv")

    section_header("Sleep and readiness", "")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if df["sleep_hours"].notna().any():
        fig.add_trace(go.Bar(x=df["date"], y=df["sleep_hours"], name="Sleep (h)",
                             marker_color=_rgba(theme.STRENGTH, 0.6), marker_line_width=0,
                             hovertemplate="Sleep %{y:.1f} h<extra></extra>"), secondary_y=False)
    if df["readiness"].notna().any():
        fig.add_trace(go.Scatter(x=df["date"], y=df["readiness"], name="Readiness", mode="lines",
                                 line=dict(color=theme.WARN, width=2),
                                 hovertemplate="Readiness %{y:.0f}<extra></extra>"), secondary_y=True)
    charts.apply_theme(fig, height=280, legend="top", dual_y=True)
    fig.update_layout(hovermode="x unified")
    _date_ticks(fig)
    fig.update_yaxes(title_text="Hours", secondary_y=False)
    fig.update_yaxes(title_text="Readiness", secondary_y=True, tickformat="d")
    charts.show(fig, key="dsh_sleep")


# ── Tabs ──────────────────────────────────────────────────────────────────────

with tab_load:
    if tab_load.open:
        pmc = _pmc()
        if pmc.empty or not pmc["tss"].any():
            st.info("No rides in this date range yet.")
        else:
            performance_chart(pmc)
        weekly_volume()
        planned_vs_done()

with tab_power:
    if tab_power.open:
        if not ctx["rides"]:
            st.info("No rides match. Pick a longer range or Clear filters.")
        else:
            peak_power()
            power_per_ride()
            efficiency_chart()
            ftp_and_zones()

with tab_hist:
    if tab_hist.open:
        fitness_history()
        power_profile_chart()

with tab_rec:
    if tab_rec.open:
        recovery(_pmc())
