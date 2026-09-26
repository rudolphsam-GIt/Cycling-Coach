"""
Global CSS for the dark theme. Base colors, fonts and widget styling come
from .streamlit/config.toml; this adds the custom cards, headers and banners.
Call inject_styles() at the top of every page.
"""
from __future__ import annotations
import streamlit as st


def inject_styles() -> None:
    st.markdown("""
    <style>
    :root {
        --bg: #0F1117;
        --surface: #1A1D2B;
        --raised: #22263A;
        --border: #2A2F45;
        --text-1: #E6EAF2;
        --text-2: #9AA6BF;
        --text-3: #636E88;
        --accent: #4D9FFF;
        --fitness: #4D9FFF;
        --fatigue: #FF8A4C;
        --good: #34D399;
        --warn: #FBBF24;
        --bad: #F87171;
    }

    /* ── Streamlit chrome ──────────────────────────────────────────────── */
    #MainMenu, footer { visibility: hidden; }
    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stMainBlockContainer"] { padding-top: 2.2rem; max-width: 1280px; }

    /* ── Sidebar navigation ────────────────────────────────────────────── */
    [data-testid="stSidebar"] { border-right: 1px solid var(--border); }
    [data-testid="stSidebarNavSeparator"] { border-color: var(--border); }
    [data-testid="stNavSectionHeader"] {
        font-size: 0.68rem !important; font-weight: 700 !important;
        letter-spacing: 0.09em; text-transform: uppercase; color: var(--text-3) !important;
    }
    [data-testid="stSidebarNavLink"] { border-radius: 8px; }
    [data-testid="stSidebarNavLink"][aria-current="page"] {
        background: rgba(77, 159, 255, 0.14) !important;
    }
    [data-testid="stSidebarNavLink"][aria-current="page"] span { color: var(--text-1) !important; }

    /* ── Page header ───────────────────────────────────────────────────── */
    .page-header { margin: 0 0 1.4rem 0; }
    .page-header-eyebrow {
        font-size: 0.72rem; font-weight: 700; letter-spacing: 0.09em;
        text-transform: uppercase; color: var(--accent); margin-bottom: 4px;
    }
    .page-header-title {
        font-size: 1.75rem; font-weight: 700; color: var(--text-1);
        letter-spacing: -0.02em; line-height: 1.2;
    }
    .page-header-subtitle { font-size: 0.92rem; color: var(--text-2); margin-top: 4px; }

    /* ── Section headers ───────────────────────────────────────────────── */
    .section-header { margin: 1.6rem 0 0.8rem 0; }
    .section-header-title { font-size: 1.02rem; font-weight: 650; color: var(--text-1); }
    .section-header-subtitle { font-size: 0.82rem; color: var(--text-2); margin-top: 2px; }

    /* ── Metric cards ──────────────────────────────────────────────────── */
    .metric-card {
        background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
        padding: 16px 18px 14px; display: flex; flex-direction: column; gap: 4px;
        min-height: 118px;
    }
    .metric-label {
        font-size: 0.7rem; font-weight: 600; color: var(--text-2);
        text-transform: uppercase; letter-spacing: 0.07em;
    }
    .metric-value, .metric-value-sm {
        font-weight: 700; color: var(--tone, var(--accent));
        line-height: 1.1; letter-spacing: -0.02em;
        font-variant-numeric: tabular-nums;
    }
    .metric-value    { font-size: 2.1rem; }
    .metric-value-sm { font-size: 1.6rem; }
    .metric-hint     { font-size: 0.76rem; color: var(--text-3); }
    .metric-delta-up      { font-size: 0.76rem; font-weight: 600; color: var(--good); }
    .metric-delta-down    { font-size: 0.76rem; font-weight: 600; color: var(--bad); }
    .metric-delta-neutral { font-size: 0.76rem; font-weight: 500; color: var(--text-3); }

    /* ── Status badges ─────────────────────────────────────────────────── */
    .status-badge {
        display: inline-block; padding: 3px 10px; border-radius: 999px;
        font-size: 0.7rem; font-weight: 700; letter-spacing: 0.05em;
        text-transform: uppercase; line-height: 1.4;
    }

    /* ── Form banner ───────────────────────────────────────────────────── */
    .tsb-banner {
        border-radius: 10px; padding: 11px 16px; margin: 4px 0 8px;
        font-size: 0.88rem; display: flex; align-items: center; gap: 10px;
        background: var(--surface); border: 1px solid var(--border); color: var(--text-2);
    }
    .tsb-banner strong { color: var(--text-1); }
    .tsb-dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
    .tsb-banner-fresh .tsb-dot    { background: var(--good); box-shadow: 0 0 0 4px rgba(52,211,153,.15); }
    .tsb-banner-building .tsb-dot { background: var(--warn); box-shadow: 0 0 0 4px rgba(251,191,36,.15); }
    .tsb-banner-fatigued .tsb-dot { background: var(--bad);  box-shadow: 0 0 0 4px rgba(248,113,113,.15); }

    /* ── Today card (planned workout, recovery) ────────────────────────── */
    .today-card {
        background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
        padding: 16px 18px; min-height: 212px;
    }
    .today-card-label {
        font-size: 0.7rem; font-weight: 600; color: var(--text-2);
        text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 6px;
    }
    .today-card-title { font-size: 1.05rem; font-weight: 650; color: var(--text-1); }
    .today-card-body  { font-size: 0.86rem; color: var(--text-2); margin-top: 4px; line-height: 1.5; }
    .today-stats { display: flex; flex-wrap: wrap; gap: 18px; margin-top: 6px; }
    .today-stat-value { font-size: 1.15rem; font-weight: 700; color: var(--text-1);
                        font-variant-numeric: tabular-nums; }
    .today-stat-label { font-size: 0.68rem; color: var(--text-3); text-transform: uppercase;
                        letter-spacing: 0.06em; }

    /* ── Activity cards ────────────────────────────────────────────────── */
    .activity-card {
        background: var(--surface); border-radius: 10px; border: 1px solid var(--border);
        padding: 12px 16px; margin-bottom: 8px; display: flex; align-items: center; gap: 14px;
    }
    .activity-card-icon   { font-size: 1.3rem; min-width: 32px; text-align: center; }
    .activity-card-body   { flex: 1; min-width: 0; }
    .activity-card-name   {
        font-size: 0.9rem; font-weight: 600; color: var(--text-1);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 4px;
    }
    .activity-card-stats  { display: flex; flex-wrap: wrap; gap: 12px; }
    .activity-stat        { display: flex; flex-direction: column; gap: 1px; }
    .activity-stat-value  { font-size: 0.85rem; font-weight: 700; color: #CBD5E1; }
    .activity-stat-label  {
        font-size: 0.64rem; font-weight: 600; color: var(--text-3);
        text-transform: uppercase; letter-spacing: 0.05em;
    }
    .activity-card-tss       { text-align: right; min-width: 48px; }
    .activity-card-tss-value { font-size: 1.25rem; font-weight: 700; color: var(--accent); line-height: 1; }
    .activity-card-tss-label {
        font-size: 0.62rem; font-weight: 600; color: var(--text-3);
        text-transform: uppercase; letter-spacing: 0.05em;
    }

    /* ── st.metric ─────────────────────────────────────────────────────── */
    [data-testid="stMetric"] {
        background: var(--surface); border-radius: 12px; padding: 14px 16px;
        border: 1px solid var(--border);
    }
    [data-testid="stMetricValue"] { font-weight: 700 !important; font-variant-numeric: tabular-nums; }
    [data-testid="stMetricLabel"] p {
        font-size: 0.7rem !important; font-weight: 600 !important; color: var(--text-2) !important;
        text-transform: uppercase; letter-spacing: 0.07em;
    }

    /* ── Tabs ──────────────────────────────────────────────────────────── */
    [data-testid="stTabs"] [role="tab"] p { font-size: 0.88rem; font-weight: 600; }

    /* ── Containers, expanders, charts, tables ─────────────────────────── */
    [data-testid="stExpander"] details { background: var(--surface); border-radius: 10px; }
    [data-testid="stPlotlyChart"] {
        border-radius: 12px; overflow: hidden; background: var(--surface);
        border: 1px solid var(--border);
    }
    [data-testid="stChatMessage"] {
        background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    }
    hr { border-color: var(--border) !important; }
    </style>
    """, unsafe_allow_html=True)
