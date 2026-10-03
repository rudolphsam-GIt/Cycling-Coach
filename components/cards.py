"""
Reusable card components for the cycling coach app.
Requires inject_styles() to have been called on the page first.
"""
from __future__ import annotations

import html
import zlib
from typing import Optional

import streamlit as st

from components import theme


def metric_card(
    label: str,
    value: str,
    delta: Optional[str] = None,
    delta_label: Optional[str] = None,
    icon: Optional[str] = None,
    small_value: bool = False,
    tone: Optional[str] = None,
    hint: Optional[str] = None,
    tip: Optional[str] = None,
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
        Optional short text or HTML mark shown above the label. Prefer leaving
        this empty; the label already says what the card is.
    small_value:
        Use a slightly smaller font for longer values (e.g. "280w" vs large numbers).
    tone:
        CSS color for the value (defaults to the theme accent color).
    hint:
        Optional muted line under the value (e.g. "fitness").
    tip:
        Optional plain words shown when hovering over the card.
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

    tone_style = f' style="--tone:{tone}"' if tone else ""
    hint_html = f'<div class="metric-hint">{hint}</div>' if hint else ""
    title_attr = f' title="{html.escape(tip, quote=True)}"' if tip else ""
    st.markdown(
        f'<div class="metric-card"{tone_style}{title_attr}>{icon_html}'
        f'<div class="metric-label">{label}</div>'
        f'<div class="{value_class}">{value}</div>{delta_html}{hint_html}</div>',
        unsafe_allow_html=True,
    )


def section_header(title: str, subtitle: Optional[str] = None, explain: Optional[str] = None,
                   **numbers) -> None:
    """
    Render a styled section header (title with an optional muted subtitle).

    Parameters
    ----------
    title:
        Main heading text.
    subtitle:
        Optional secondary line shown below the title in muted text.
    explain:
        Optional term from metrics.explain.TERMS. Adds a help icon at the right
        that explains it. Extra keyword arguments override the rider's numbers.
    """
    if explain:
        from components.explain import help_icon
        left, right = st.columns([12, 1], vertical_alignment="center")
        with left:
            section_header(title, subtitle)
        with right:
            help_icon(explain, key=f"sh_{explain}_{zlib.crc32(title.encode()) % 10**6}", **numbers)
        return
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


def status_badge(text: str, color: Optional[str] = None) -> str:
    """
    Return HTML for a colored pill badge.

    The returned string can be embedded inside a larger markdown block.
    Pass a theme color such as theme.GOOD, theme.WARN, theme.BAD or
    theme.ACCENT. The default is the theme accent.

    Parameters
    ----------
    text:
        Badge label text (e.g. "Fresh", "Fatigued"). It is HTML escaped.
    color:
        CSS color string for the badge background. The text is drawn in the
        page background color, which reads well on the bright theme colors.
    """
    bg = color or theme.ACCENT
    return (
        f'<span class="status-badge" '
        f'style="background:{bg};color:{theme.BG};">{html.escape(str(text))}</span>'
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
    from metrics.explain import form_state
    state = form_state(tsb, ctl)
    if state == "fresh":
        css_class = "tsb-banner tsb-banner-fresh"
        message = (
            f"<strong>Fresh</strong> · form {tsb:+.1f}. "
            "You have more fitness than fatigue, so it is a good day to race or go hard."
        )
    elif state == "fatigued":
        css_class = "tsb-banner tsb-banner-fatigued"
        message = (
            f"<strong>Fatigued</strong> · form {tsb:+.1f}. "
            "Recent training is catching up with you, so take an easy day or rest before hard efforts."
        )
    else:
        css_class = "tsb-banner tsb-banner-building"
        message = (
            f"<strong>Building</strong> · form {tsb:+.1f}. "
            "You are carrying some fatigue, which is normal while building. Keep an eye on it."
        )

    st.markdown(
        f'<div class="{css_class}"><span class="tsb-dot"></span><span>{message}</span></div>',
        unsafe_allow_html=True,
    )


def _sport_label(sport_type: str) -> str:
    """Short text label for a sport type, used in place of an icon."""
    sport_lower = (sport_type or "").lower()
    if "run" in sport_lower:
        return "Run"
    if "swim" in sport_lower:
        return "Swim"
    if "hike" in sport_lower or "walk" in sport_lower:
        return "Walk"
    if "strength" in sport_lower or "weight" in sport_lower:
        return "Gym"
    return "Ride"


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
        Sport type string (used to pick the short sport label chip).
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
    zone_seconds:
        Optional list of five values, seconds spent in power zones 1 to 5.
    """
    chip = html.escape(_sport_label(sport_type))

    stats_html = ""
    stat_pairs = [
        (duration, "Duration"),
        (distance, "Distance"),
        (power, "Avg Power"),
        (hr, "Avg HR"),
    ]
    for val, lbl in stat_pairs:
        if val and val != "—":
            stats_html += (
                '<div class="activity-stat">'
                f'<div class="activity-stat-value">{html.escape(str(val))}</div>'
                f'<div class="activity-stat-label">{lbl}</div>'
                '</div>'
            )

    tss_display = html.escape(str(tss)) if tss and tss != "—" else "—"

    # Zone strip drawn directly under the card, in the same st.markdown call.
    zone_suffix = ""
    if zone_seconds and len(zone_seconds) == 5:
        total_s = sum(zone_seconds)
        if total_s > 0:
            segs = ""
            labels = []
            for i in range(5):
                s = zone_seconds[i]
                color = theme.ZONE_COLORS[i]
                pct = s / total_s * 100
                if pct > 0.5:
                    segs += (
                        f'<div style="flex:{pct:.1f};background:{color};height:100%"></div>'
                    )
                mins = int(s // 60)
                if mins > 0:
                    labels.append(
                        f'<span style="color:{color};font-weight:600">'
                        f'{theme.ZONE_LABELS[i]}</span> {mins}m'
                    )
            label_str = " · ".join(labels)
            zone_suffix = (
                '<div class="activity-zones">'
                f'<div class="activity-zones-bar">{segs}</div>'
                f'<div class="activity-zones-labels">{label_str}</div></div>'
            )

    st.markdown(
        '<div class="activity-card">'
        f'<div class="activity-card-icon"><span class="sport-chip">{chip}</span></div>'
        '<div class="activity-card-body">'
        f'<div class="activity-card-name">{html.escape(str(name))}</div>'
        f'<div class="activity-card-date">{html.escape(str(activity_date))}</div>'
        f'<div class="activity-card-stats">{stats_html}</div>'
        '</div>'
        '<div class="activity-card-tss">'
        f'<div class="activity-card-tss-value">{tss_display}</div>'
        '<div class="activity-card-tss-label">TSS</div>'
        '</div></div>'
        f'{zone_suffix}',
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: Optional[str] = None, eyebrow: Optional[str] = None) -> None:
    """Render the page title block used at the top of every page."""
    eyebrow_html = f'<div class="page-header-eyebrow">{eyebrow}</div>' if eyebrow else ""
    sub_html = f'<div class="page-header-subtitle">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<div class="page-header">{eyebrow_html}'
        f'<div class="page-header-title">{title}</div>{sub_html}</div>',
        unsafe_allow_html=True,
    )
