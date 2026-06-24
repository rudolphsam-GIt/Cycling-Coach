"""
Reusable card components for the cycling coach app.
Requires inject_styles() to have been called on the page first.
"""
from __future__ import annotations

from typing import Optional

import streamlit as st


def metric_card(
    label: str,
    value: str,
    delta: Optional[str] = None,
    delta_label: Optional[str] = None,
    icon: Optional[str] = None,
    small_value: bool = False,
) -> None:
    """
    Render a styled metric card.

    Parameters
    ----------
    label:
        Short uppercase label shown above the value (e.g. "CTL (Fitness)").
    value:
        The primary metric value as a string (e.g. "78.3" or "280w").
    delta:
        Optional delta string, prefixed with + or - (e.g. "+2.1 /week").
        A leading '+' or positive number gets the green up-delta style;
        a leading '-' gets the red down-delta style.
    delta_label:
        Optional secondary label shown next to the delta (e.g. "vs last week").
    icon:
        Optional emoji icon shown above the label (e.g. "⚡").
    small_value:
        Use a slightly smaller font for longer values (e.g. "280w" vs large numbers).
    """
    icon_html = f'<div class="metric-icon">{icon}</div>' if icon else ""

    value_class = "metric-value-sm" if small_value else "metric-value"

    if delta is not None:
        stripped = delta.lstrip()
        if stripped.startswith("+") or (
            stripped and stripped[0].isdigit() and not stripped.startswith("-")
        ):
            delta_class = "metric-delta-up"
            arrow = "↑"
        elif stripped.startswith("-"):
            delta_class = "metric-delta-down"
            arrow = "↓"
        else:
            delta_class = "metric-delta-neutral"
            arrow = ""
        dl = f"&nbsp;{delta_label}" if delta_label else ""
        delta_html = (
            f'<div class="{delta_class}">{arrow} {delta}{dl}</div>'
        )
    else:
        delta_html = ""

    st.markdown(
        f"""
        <div class="metric-card">
            {icon_html}
            <div class="metric-label">{label}</div>
            <div class="{value_class}">{value}</div>
            {delta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_header(title: str, subtitle: Optional[str] = None) -> None:
    """
    Render a styled section header with a colored left border.

    Parameters
    ----------
    title:
        Main heading text.
    subtitle:
        Optional secondary line shown below the title in muted text.
    """
    sub_html = (
        f'<div class="section-header-subtitle">{subtitle}</div>'
        if subtitle
        else ""
    )
    st.markdown(
        f"""
        <div class="section-header">
            <div class="section-header-title">{title}</div>
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def status_badge(text: str, color: str) -> str:
    """
    Return HTML for a colored pill badge.

    The returned string can be embedded inside a larger markdown block.
    Typical color values: '#059669' (green), '#D97706' (amber), '#DC2626' (red),
    '#0066CC' (blue), '#6B7280' (gray).

    Parameters
    ----------
    text:
        Badge label text (e.g. "Fresh", "Fatigued").
    color:
        CSS color string for the badge background. The text color is auto-
        calculated to be white for dark backgrounds.
    """
    return (
        f'<span class="status-badge" '
        f'style="background:{color};color:#ffffff;">{text}</span>'
    )


def tsb_banner(tsb: float, ctl: float) -> None:
    """
    Render a color-coded TSB status banner.

    Parameters
    ----------
    tsb:
        Current Training Stress Balance value.
    ctl:
        Current Chronic Training Load (fitness score).
    """
    if tsb >= 10 and ctl > 20:
        css_class = "tsb-banner tsb-banner-fresh"
        icon = "✅"
        message = (
            f"<strong>FRESH</strong> &nbsp;(TSB {tsb:+.1f}) — "
            "Good day to race or go hard."
        )
    elif tsb <= -30:
        css_class = "tsb-banner tsb-banner-fatigued"
        icon = "⚠️"
        message = (
            f"<strong>FATIGUED</strong> &nbsp;(TSB {tsb:+.1f}) — "
            "Consider an easy day or rest before hard efforts."
        )
    else:
        css_class = "tsb-banner tsb-banner-building"
        icon = "📈"
        message = (
            f"<strong>BUILDING</strong> &nbsp;(TSB {tsb:+.1f}) — "
            "Productive training zone. Monitor fatigue accumulation."
        )

    st.markdown(
        f'<div class="{css_class}">{icon}&nbsp;&nbsp;{message}</div>',
        unsafe_allow_html=True,
    )


def activity_card(
    name: str,
    sport_type: str,
    activity_date: str,
    duration: str,
    distance: str,
    power: str,
    hr: str,
    tss: str,
    zone_seconds: list | None = None,
) -> None:
    """
    Render a single styled activity card.

    Parameters
    ----------
    name:
        Activity name.
    sport_type:
        Sport type string (used to pick icon).
    activity_date:
        Display date string.
    duration:
        Formatted duration string (e.g. "1h 45m").
    distance:
        Formatted distance string (e.g. "52.3 km").
    power:
        Formatted average power string (e.g. "215w") or "—".
    hr:
        Formatted average HR string (e.g. "148 bpm") or "—".
    tss:
        Formatted TSS string (e.g. "124") or "—".
    """
    sport_lower = (sport_type or "").lower()
    if "run" in sport_lower:
        icon = "🏃"
    elif "swim" in sport_lower:
        icon = "🏊"
    elif "hike" in sport_lower or "walk" in sport_lower:
        icon = "🥾"
    elif "strength" in sport_lower or "weight" in sport_lower:
        icon = "🏋️"
    else:
        icon = "🚴"

    stats_html = ""
    stat_pairs = [
        (duration, "Duration"),
        (distance, "Distance"),
        (power, "Avg Power"),
        (hr, "Avg HR"),
    ]
    for val, lbl in stat_pairs:
        if val and val != "—":
            stats_html += f"""
            <div class="activity-stat">
                <div class="activity-stat-value">{val}</div>
                <div class="activity-stat-label">{lbl}</div>
            </div>"""

    tss_display = tss if tss and tss != "—" else "—"

    # Build zone strip as a sibling div (rendered after the card closes, same st.markdown call)
    zone_suffix = ""
    if zone_seconds and len(zone_seconds) == 5:
        total_s = sum(zone_seconds)
        if total_s > 0:
            z_colors = ["#9ecae1", "#41ab5d", "#fdae6b", "#e6550d", "#bd0026"]
            z_names = ["Z1", "Z2", "Z3", "Z4", "Z5"]
            segs = ""
            labels = []
            for i in range(5):
                s = zone_seconds[i]
                color = z_colors[i]
                pct = s / total_s * 100
                if pct > 0.5:
                    segs += (
                        "<div style='flex:" + f"{pct:.1f}" +
                        ";background:" + color +
                        ";height:100%'></div>"
                    )
                mins = int(s // 60)
                if mins > 0:
                    labels.append(
                        "<span style='color:" + color + ";font-weight:600'>" +
                        z_names[i] + "</span> " + str(mins) + "m"
                    )
            label_str = " · ".join(labels)
            zone_suffix = (
                "<div style='margin-top:-6px;padding:3px 18px 9px 68px;"
                "background:#1C1F2E;border:1px solid #2E3250;border-top:none;"
                "border-radius:0 0 10px 10px'>"
                "<div style='display:flex;height:4px;overflow:hidden;gap:1px;"
                "border-radius:2px'>" + segs + "</div>"
                "<div style='font-size:0.63rem;color:#5B657D;margin-top:3px'>"
                + label_str + "</div></div>"
            )

    st.markdown(
        f"""
        <div class="activity-card">
            <div class="activity-card-icon">{icon}</div>
            <div class="activity-card-body">
                <div class="activity-card-name">{name}</div>
                <div style="font-size:0.72rem;color:#9CA3AF;margin-bottom:6px;">{activity_date}</div>
                <div class="activity-card-stats">{stats_html}</div>
            </div>
            <div class="activity-card-tss">
                <div class="activity-card-tss-value">{tss_display}</div>
                <div class="activity-card-tss-label">TSS</div>
            </div>
        </div>
        {zone_suffix}
        """,
        unsafe_allow_html=True,
    )
