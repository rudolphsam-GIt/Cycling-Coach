"""
The rides table and the selected ride panel, shared by the Today and Progress pages
so they always look and behave the same.
"""
from __future__ import annotations

import html
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components import charts, theme
from components.explain import help_icon
from components.units import distance_unit
from metrics.analysis import ride_kind
from metrics.explain import TIPS
from metrics.tss import SOURCE_FROM, label as tss_label
from metrics.units import climb_from_m, climb_unit, dist_from_km, fmt_climb, fmt_distance
from metrics.units import num as _num

ZONE_NAMES = ["Z1 Active Recovery", "Z2 Endurance", "Z3 Tempo", "Z4 Threshold", "Z5 VO2 Max"]


def _fmt(val, fn) -> str:
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


def rides_frame(activities: list, unit: str = "km") -> pd.DataFrame:
    """One row per ride with the columns the table and the CSV use. Distance and climbing
    are in the rider's units (miles and feet, or kilometers and meters)."""
    dist, climb = f"Distance {unit}", f"Climb {climb_unit(unit)}"
    return pd.DataFrame([
        {
            "Date": a.get("date") or "",
            "Name": a.get("name") or "Untitled",
            "Type": ride_kind(a),
            "Duration": _hm(a.get("duration_seconds")),
            dist: (dist_from_km(_num(a.get("distance_meters")) / 1000, unit)
                   if _num(a.get("distance_meters")) is not None else None),
            climb: (climb_from_m(_num(a.get("elevation_gain_meters")), unit)
                    if _num(a.get("elevation_gain_meters")) is not None else None),
            "Avg W": _num(a.get("avg_power_watts")),
            "NP": _num(a.get("normalized_power")),
            "Avg HR": _num(a.get("avg_hr")),
            "TSS": _num(a.get("tss")),
            "TSS from": (SOURCE_FROM.get("manual" if a.get("tss_locked") else a.get("tss_source") or "", "")
                         if _num(a.get("tss")) else ""),
            "IF": _num(a.get("if_value")),
        }
        for a in activities
    ], columns=["Date", "Name", "Type", "Duration", dist, climb, "Avg W", "NP",
                "Avg HR", "TSS", "TSS from", "IF"])


def ride_table(activities: list, key: str, *, max_height: int = 420) -> dict | None:
    """A sortable table of rides with single row selection. Returns the selected
    ride, or None. `activities` should already be sorted the way you want."""
    unit = distance_unit()
    df = rides_frame(activities, unit)
    dist, climb = f"Distance {unit}", f"Climb {climb_unit(unit)}"
    event = st.dataframe(
        df,
        hide_index=True,
        width="stretch",
        height=min(38 + 35 * len(df), max_height),
        key=key,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Date": st.column_config.TextColumn("Date", width=100),
            "Name": st.column_config.TextColumn("Name", width="medium"),
            "Type": st.column_config.TextColumn("Type", width="small"),
            "Duration": st.column_config.TextColumn("Duration", width="small"),
            dist: st.column_config.NumberColumn(dist, format="%.1f", width="small"),
            climb: st.column_config.NumberColumn(climb, format="%d", width="small"),
            "Avg W": st.column_config.NumberColumn("Avg W", format="%d", width="small", help=TIPS["avg_w"]),
            "NP": st.column_config.NumberColumn("NP", format="%d", width="small", help=TIPS["np"]),
            "Avg HR": st.column_config.NumberColumn("Avg HR", format="%d", width="small"),
            "TSS": st.column_config.NumberColumn("TSS", format="%d", width="small", help=TIPS["tss"]),
            "TSS from": st.column_config.TextColumn(
                "TSS from", width="small",
                help="Power, or Heart rate (hrTSS) when the ride had no power. Power + HR means the "
                     "power dropped out and heart rate filled the gap."),
            "IF": st.column_config.NumberColumn("IF", format="%.2f", width="small", help=TIPS["if"]),
        },
    )
    rows = list(event.selection.rows) if event and event.selection else []
    if not rows or rows[0] >= len(activities):
        return None
    return activities[rows[0]]


def ride_detail(act: dict, key: str) -> None:
    """The numbers and zone breakdown for one ride."""
    duration_str = _fmt(
        act.get("duration_seconds"),
        lambda v: f"{int(v // 3600)}h {int((v % 3600) // 60)}m" if v >= 3600 else f"{int(v // 60)}m",
    )
    rows = [
        ("Duration", duration_str),
        ("Distance", fmt_distance(_num(act.get("distance_meters")), distance_unit())),
        ("Elevation", fmt_climb(_num(act.get("elevation_gain_meters")), distance_unit())),
        ("Avg Power", _fmt(act.get("avg_power_watts"), lambda v: f"{int(v)} W")),
        ("Norm Power", _fmt(act.get("normalized_power"), lambda v: f"{int(v)} W")),
        ("Int Factor", _fmt(act.get("if_value"), lambda v: f"{v:.2f}")),
        ("Avg HR", _fmt(act.get("avg_hr"), lambda v: f"{int(v)} bpm")),
        (tss_label(act.get("tss_source")), _fmt(act.get("tss"), lambda v: f"{v:.0f}")),
    ]

    zone_secs = None
    if act.get("zone_time_json"):
        try:
            z = json.loads(act["zone_time_json"])
            zone_secs = [z.get(f"z{i}_s", 0) or 0 for i in range(1, 6)]
        except Exception:
            zone_secs = None

    with st.container(border=True):
        title, helper = st.columns([3, 2], vertical_alignment="center")
        title.markdown(f"**{html.escape(act.get('name') or 'Untitled')}**, {act.get('date') or ''}")
        with helper:
            help_icon("ride_numbers", f"{key}_numbers", label="What do these mean?")
        dc1, dc2 = st.columns([1, 2])
        with dc1:
            tbl = "".join(
                f"<tr><td class='k'>{html.escape(k)}</td><td class='v'>{html.escape(v)}</td></tr>"
                for k, v in rows if v
            )
            if tbl:
                st.markdown(f"<table class=\"kv-table\">{tbl}</table>", unsafe_allow_html=True)
            else:
                st.caption("No metrics recorded for this ride.")

        with dc2:
            if not zone_secs or sum(zone_secs) <= 0:
                st.caption("No zone breakdown for this ride. It needs power or heart rate data.")
                return
            total_s = sum(zone_secs)
            zfig = go.Figure()
            for i in range(5):
                s = zone_secs[i]
                if s <= 0:
                    continue
                mins_total = int(s // 60)
                h_part, m_part = mins_total // 60, mins_total % 60
                t_str = f"{h_part}h {m_part:02d}m" if h_part else f"{m_part}m"
                zfig.add_trace(go.Bar(
                    name=ZONE_NAMES[i], x=[s / 3600], y=["Zones"], orientation="h",
                    marker_color=theme.ZONE_COLORS[i], marker_line_width=0,
                    hovertemplate=(f"<b>{ZONE_NAMES[i]}</b><br>Time: {t_str}<br>"
                                   f"Share: {s / total_s * 100:.1f}%<extra></extra>"),
                ))
            charts.apply_theme(zfig, height=80, legend="none")
            zfig.update_layout(barmode="stack", margin=dict(l=0, r=0, t=4, b=4))
            zfig.update_xaxes(visible=False)
            zfig.update_yaxes(visible=False)
            charts.show(zfig, key=f"{key}_zones", zoom=None)

            ztbl = "".join(
                f"<tr><td class='k'><span style='color:{theme.ZONE_COLORS[i]};font-weight:700'>"
                f"Z{i + 1}</span></td><td class='v'>{int(zone_secs[i] // 60)}m, "
                f"{zone_secs[i] / total_s * 100:.0f}%</td></tr>"
                for i in range(5) if zone_secs[i] > 30
            )
            if ztbl:
                st.markdown(f"<table class=\"kv-table\">{ztbl}</table>", unsafe_allow_html=True)
