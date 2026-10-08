"""
Global CSS for the dark theme. Base colors, fonts and widget styling come
from .streamlit/config.toml; this adds the custom cards, headers and banners.
The color variables are written from components.theme so there is one source
of truth. Call inject_styles() at the top of every page.
"""
from __future__ import annotations
import streamlit as st

from components import theme

# The CSS below is a plain string with __TOKEN__ placeholders for theme colors,
# so CSS braces never need escaping.
_CSS = """
<style>
:root {
    --bg: __BG__;
    --surface: __SURFACE__;
    --raised: __RAISED__;
    --border: __BORDER__;
    --text-1: __TEXT1__;
    --text-2: __TEXT2__;
    --text-3: __TEXT3__;
    --accent: __ACCENT__;
    --fitness: __FITNESS__;
    --fatigue: __FATIGUE__;
    --good: __GOOD__;
    --warn: __WARN__;
    --bad: __BAD__;
    --strength: __STRENGTH__;
    --race: __RACE__;
}

/* Streamlit chrome */
#MainMenu, footer { visibility: hidden; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"] { padding-top: 2.2rem; max-width: 1280px; }

/* Sidebar navigation */
[data-testid="stSidebar"] { border-right: 1px solid var(--border); }
[data-testid="stSidebarNavSeparator"] { border-color: var(--border); }
[data-testid="stNavSectionHeader"] {
    font-size: 0.8rem !important; font-weight: 700 !important;
    letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-3) !important;
}
[data-testid="stSidebarNavLink"] { border-radius: 8px; }
[data-testid="stSidebarNavLink"][aria-current="page"] {
    background: rgba(77, 159, 255, 0.14) !important;
}
[data-testid="stSidebarNavLink"][aria-current="page"] span { color: var(--text-1) !important; }

/* Page header */
.page-header { margin: 0 0 1.4rem 0; }
.page-header-eyebrow {
    font-size: 0.8rem; font-weight: 700; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--accent); margin-bottom: 4px;
}
.page-header-title {
    font-size: 1.9rem; font-weight: 700; color: var(--text-1);
    letter-spacing: -0.02em; line-height: 1.2;
}
.page-header-subtitle { font-size: 1rem; color: var(--text-2); margin-top: 4px; }

/* Section headers */
.section-header { margin: 1.6rem 0 0.8rem 0; }
.section-header-title { font-size: 1.2rem; font-weight: 650; color: var(--text-1); }
.section-header-subtitle { font-size: 0.9rem; color: var(--text-2); margin-top: 2px; }

/* Metric cards */
.metric-card {
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 16px 18px 14px; display: flex; flex-direction: column; gap: 4px;
    min-height: 118px;
}
.metric-label {
    font-size: 0.8rem; font-weight: 600; color: var(--text-2);
    text-transform: uppercase; letter-spacing: 0.06em;
}
.metric-value, .metric-value-sm {
    font-weight: 700; color: var(--tone, var(--accent));
    line-height: 1.1; letter-spacing: -0.02em;
    font-variant-numeric: tabular-nums;
}
.metric-value    { font-size: 2.1rem; }
.metric-value-sm { font-size: 1.6rem; }
.metric-hint     { font-size: 0.85rem; color: var(--text-3); }
.metric-delta-up      { font-size: 0.85rem; font-weight: 600; color: var(--good); }
.metric-delta-down    { font-size: 0.85rem; font-weight: 600; color: var(--bad); }
.metric-delta-neutral { font-size: 0.85rem; font-weight: 500; color: var(--text-3); }

/* Status badges */
.status-badge {
    display: inline-block; padding: 3px 10px; border-radius: 999px;
    font-size: 0.8rem; font-weight: 700; letter-spacing: 0.04em;
    text-transform: uppercase; line-height: 1.4;
}

/* Sport chip (short text label) */
.sport-chip {
    display: inline-block; padding: 2px 9px; border-radius: 6px;
    font-size: 0.8rem; font-weight: 700; letter-spacing: 0.04em;
    text-transform: uppercase; color: var(--text-2);
    background: var(--raised); border: 1px solid var(--border);
    min-width: 40px; text-align: center;
}

/* Form banner */
.tsb-banner {
    border-radius: 10px; padding: 11px 16px; margin: 4px 0 8px;
    font-size: 0.95rem; display: flex; align-items: center; gap: 10px;
    background: var(--surface); border: 1px solid var(--border); color: var(--text-2);
}
.tsb-banner strong { color: var(--text-1); }
.tsb-dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
.tsb-banner-fresh .tsb-dot    { background: var(--good); box-shadow: 0 0 0 4px rgba(52,211,153,.15); }
.tsb-banner-building .tsb-dot { background: var(--warn); box-shadow: 0 0 0 4px rgba(251,191,36,.15); }
.tsb-banner-fatigued .tsb-dot { background: var(--bad);  box-shadow: 0 0 0 4px rgba(248,113,113,.15); }

/* Today card (planned workout, recovery) */
.today-card {
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 16px 18px; min-height: 212px;
}
.today-card-label {
    font-size: 0.8rem; font-weight: 600; color: var(--text-2);
    text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px;
}
.today-card-title { font-size: 1.15rem; font-weight: 650; color: var(--text-1); }
.today-card-body  { font-size: 0.95rem; color: var(--text-2); margin-top: 4px; line-height: 1.5; }
.today-stats { display: flex; flex-wrap: wrap; gap: 18px; margin-top: 6px; }
.today-stat-value { font-size: 1.2rem; font-weight: 700; color: var(--text-1);
                    font-variant-numeric: tabular-nums; }
.today-stat-label { font-size: 0.8rem; color: var(--text-3); text-transform: uppercase;
                    letter-spacing: 0.05em; }

/* Activity cards */
.activity-card {
    background: var(--surface); border-radius: 10px; border: 1px solid var(--border);
    padding: 12px 16px; margin-bottom: 8px; display: flex; align-items: center; gap: 14px;
}
.activity-card-icon   { min-width: 48px; text-align: center; }
.activity-card-body   { flex: 1; min-width: 0; }
.activity-card-name   {
    font-size: 1rem; font-weight: 600; color: var(--text-1);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 4px;
}
.activity-card-date   { font-size: 0.85rem; color: var(--text-2); margin-bottom: 6px; }
.activity-card-stats  { display: flex; flex-wrap: wrap; gap: 14px; }
.activity-stat        { display: flex; flex-direction: column; gap: 1px; }
.activity-stat-value  { font-size: 0.95rem; font-weight: 700; color: var(--text-1); }
.activity-stat-label  {
    font-size: 0.8rem; font-weight: 600; color: var(--text-3);
    text-transform: uppercase; letter-spacing: 0.04em;
}
.activity-card-tss       { text-align: right; min-width: 52px; }
.activity-card-tss-value { font-size: 1.3rem; font-weight: 700; color: var(--accent); line-height: 1; }
.activity-card-tss-label {
    font-size: 0.8rem; font-weight: 600; color: var(--text-3);
    text-transform: uppercase; letter-spacing: 0.04em;
}
.activity-zones {
    margin-top: -6px; padding: 4px 18px 10px 18px; background: var(--raised);
    border: 1px solid var(--border); border-top: none; border-radius: 0 0 10px 10px;
}
.activity-zones-bar { display: flex; height: 4px; overflow: hidden; gap: 1px; border-radius: 2px; }
.activity-zones-labels { font-size: 0.8rem; color: var(--text-3); margin-top: 4px; }

/* Compact key/value table */
table.kv-table {
    width: 100%; border-collapse: collapse; margin: 0.25rem 0 0.75rem 0;
    font-size: 0.95rem; font-variant-numeric: tabular-nums;
}
table.kv-table tr { border-bottom: 1px solid var(--border); }
table.kv-table tr:last-child { border-bottom: none; }
table.kv-table td { padding: 7px 4px; vertical-align: baseline; background: transparent; border: none; }
table.kv-table td.k { color: var(--text-2); }
table.kv-table td.v { color: var(--text-1); font-weight: 600; text-align: right; }

/* Fitness history tables (Dashboard, History tab) */
.hist-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; margin: 0.25rem 0 1rem; }
table.hist-table {
    width: 100%; border-collapse: collapse; font-size: 0.92rem;
    font-variant-numeric: tabular-nums; white-space: nowrap;
}
table.hist-table th {
    background: var(--raised); color: var(--text-1); font-weight: 650; text-align: right;
    padding: 8px 10px; border: none; border-bottom: 1px solid var(--border);
}
table.hist-table th:first-child, table.hist-table td:first-child { text-align: left; }
table.hist-table td {
    padding: 5px 10px; text-align: right; color: var(--text-1); border: none;
    border-bottom: 1px solid rgba(255,255,255,0.04); background: transparent;
}
table.hist-table td.pk { color: var(--accent); font-weight: 600; }
table.hist-table tr.cur td { color: var(--text-3); font-style: italic; font-weight: 400; }
table.hist-table tr.sec td {
    background: var(--raised); color: var(--text-1); font-weight: 650; text-align: left;
    padding: 6px 10px;
}
table.hist-table tr.all td { border-top: 2px solid var(--border); font-weight: 700; }

/* Calendar legend */
.cal-legend { display: flex; flex-wrap: wrap; gap: 8px 10px; margin: 8px 0 4px; }
.cal-chip {
    display: inline-flex; align-items: center; gap: 7px; padding: 3px 11px 3px 9px;
    border-radius: 999px; background: var(--surface); border: 1px solid var(--border);
    font-size: 0.85rem; color: var(--text-2); line-height: 1.4;
}
.cal-chip::before {
    content: ""; width: 9px; height: 9px; border-radius: 50%; flex: none;
    background: var(--dot, var(--text-3));
}

/* st.metric */
[data-testid="stMetric"] {
    background: var(--surface); border-radius: 12px; padding: 14px 16px;
    border: 1px solid var(--border);
}
[data-testid="stMetricValue"] { font-weight: 700 !important; font-variant-numeric: tabular-nums; }
[data-testid="stMetricLabel"] p {
    font-size: 0.8rem !important; font-weight: 600 !important; color: var(--text-2) !important;
    text-transform: uppercase; letter-spacing: 0.06em;
}

/* Tabs */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: 4px; border-bottom: 1px solid var(--border);
}
[data-testid="stTabs"] [role="tab"] {
    padding: 10px 18px; height: auto; border-radius: 8px 8px 0 0;
    color: var(--text-2);
}
[data-testid="stTabs"] [role="tab"] p { font-size: 1.05rem; font-weight: 600; }
[data-testid="stTabs"] [role="tab"]:hover { background: rgba(77, 159, 255, 0.08); color: var(--text-1); }
[data-testid="stTabs"] [role="tab"][aria-selected="true"] { color: var(--text-1); }
[data-testid="stTabs"] [data-baseweb="tab-highlight"] { height: 3px; background-color: var(--accent); }
[data-testid="stTabs"] [data-baseweb="tab-border"] { background-color: var(--border); }

/* Containers, expanders, charts, tables */
[data-testid="stExpander"] details { background: var(--surface); border-radius: 10px; }
[data-testid="stPlotlyChart"] {
    border-radius: 12px; overflow: hidden; background: var(--surface);
    border: 1px solid var(--border);
}
hr { border-color: var(--border) !important; }

/* Chat */
[data-testid="stChatMessage"] {
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 1rem 1.15rem; margin-bottom: 0.7rem; gap: 0.9rem;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    background: var(--raised);
}
[data-testid="stChatMessage"] p,
[data-testid="stChatMessage"] li { font-size: 1.02rem; line-height: 1.65; }
[data-testid="stChatMessage"] p { margin-bottom: 0.6rem; }
[data-testid="stChatMessage"] p:last-child { margin-bottom: 0; }
[data-testid="stChatMessage"] ul, [data-testid="stChatMessage"] ol { margin-bottom: 0.6rem; }
[data-testid="stChatInput"] {
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 4px 6px; margin-top: 0.4rem;
}
[data-testid="stChatInput"] textarea { font-size: 1rem; line-height: 1.5; }
[data-testid="stChatInput"]:focus-within { border-color: var(--accent); }

/* Setup and welcome pages */
.hero { max-width: 640px; margin: 36px auto 22px; text-align: center; }
.hero-eyebrow {
    font-size: 0.85rem; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; color: var(--accent); margin-bottom: 8px;
}
.hero-title {
    font-size: 2.2rem; font-weight: 700; color: var(--text-1);
    letter-spacing: -0.02em; line-height: 1.15; margin-bottom: 8px;
}
.hero-sub { font-size: 1.05rem; color: var(--text-2); line-height: 1.5; }
</style>
"""


def _build_css() -> str:
    tokens = {
        "__BG__": theme.BG, "__SURFACE__": theme.SURFACE, "__RAISED__": theme.RAISED,
        "__BORDER__": theme.BORDER, "__TEXT1__": theme.TEXT1, "__TEXT2__": theme.TEXT2,
        "__TEXT3__": theme.TEXT3, "__ACCENT__": theme.ACCENT, "__FITNESS__": theme.FITNESS,
        "__FATIGUE__": theme.FATIGUE, "__GOOD__": theme.GOOD, "__WARN__": theme.WARN,
        "__BAD__": theme.BAD, "__STRENGTH__": theme.STRENGTH, "__RACE__": theme.RACE,
    }
    css = _CSS
    for key, value in tokens.items():
        css = css.replace(key, value)
    return css


def inject_styles() -> None:
    st.markdown(_build_css(), unsafe_allow_html=True)
