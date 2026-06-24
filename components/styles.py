"""
Global CSS — dark mode theme.
Call inject_styles() at the top of every page.
"""
from __future__ import annotations
import streamlit as st


def inject_styles() -> None:
    st.markdown("""
    <style>
    /* ── Hide Streamlit chrome ─────────────────────────────────────────── */
    #MainMenu { visibility: hidden; }
    footer    { visibility: hidden; }
    header    { visibility: hidden; }

    /* ── Palette (dark mode) ───────────────────────────────────────────── */
    /*
        bg-base    #0F1117   page background
        bg-surface #1C1F2E   cards, panels
        bg-raised  #252840   elevated elements
        border     #2E3250   subtle dividers
        accent     #4D9FFF   primary blue
        accent-alt #FF6B35   power orange
        text-1     #E8ECF4   headings
        text-2     #94A3B8   secondary labels
        text-3     #5B657D   muted/placeholder
    */

    /* ── Base background ───────────────────────────────────────────────── */
    html, body,
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    .main .block-container {
        background-color: #0F1117 !important;
        color: #E8ECF4 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                     "Helvetica Neue", Arial, sans-serif;
    }

    /* ── Sidebar ───────────────────────────────────────────────────────── */
    [data-testid="stSidebar"],
    [data-testid="stSidebar"] > div:first-child {
        background-color: #13151F !important;
        border-right: 1px solid #2E3250;
    }
    [data-testid="stSidebarContent"] { padding-top: 1.25rem; }

    /* Sidebar text */
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] .stMarkdown p,
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        color: #CBD5E1 !important;
    }

    /* ── Inputs ────────────────────────────────────────────────────────── */
    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input,
    [data-testid="stTextArea"] textarea,
    [data-testid="stSelectbox"] div,
    [data-testid="stMultiSelect"] div {
        background-color: #1C1F2E !important;
        color: #E8ECF4 !important;
        border-color: #2E3250 !important;
        border-radius: 8px !important;
    }

    /* ── Metric cards ──────────────────────────────────────────────────── */
    .metric-card {
        background: #1C1F2E;
        border-radius: 12px;
        border: 1px solid #2E3250;
        padding: 20px 20px 16px 20px;
        display: flex;
        flex-direction: column;
        gap: 4px;
        min-height: 100px;
    }
    .metric-icon   { font-size: 1.1rem; margin-bottom: 2px; line-height: 1; }
    .metric-label  {
        font-size: 0.72rem; font-weight: 600; color: #94A3B8;
        text-transform: uppercase; letter-spacing: 0.07em; line-height: 1.2;
    }
    .metric-value {
        font-size: 2.5rem; font-weight: 700; color: #4D9FFF;
        line-height: 1.1; letter-spacing: -0.02em;
    }
    .metric-value-sm {
        font-size: 1.9rem; font-weight: 700; color: #4D9FFF;
        line-height: 1.1; letter-spacing: -0.02em;
    }
    .metric-delta-up      { font-size: 0.78rem; font-weight: 600; color: #34D399; }
    .metric-delta-down    { font-size: 0.78rem; font-weight: 600; color: #F87171; }
    .metric-delta-neutral { font-size: 0.78rem; font-weight: 500; color: #5B657D; }

    /* ── Section headers ───────────────────────────────────────────────── */
    .section-header {
        display: flex; flex-direction: column; gap: 2px;
        margin-bottom: 16px; padding-left: 14px;
        border-left: 4px solid #4D9FFF;
    }
    .section-header-title    { font-size: 1.05rem; font-weight: 700; color: #E8ECF4; }
    .section-header-subtitle { font-size: 0.82rem; color: #94A3B8; font-weight: 400; }

    /* ── Status badges ─────────────────────────────────────────────────── */
    .status-badge {
        display: inline-block; padding: 3px 10px; border-radius: 999px;
        font-size: 0.72rem; font-weight: 700; letter-spacing: 0.05em;
        text-transform: uppercase; line-height: 1.4;
    }

    /* ── TSB banners ───────────────────────────────────────────────────── */
    .tsb-banner {
        border-radius: 10px; padding: 12px 18px; margin-bottom: 8px;
        font-size: 0.88rem; font-weight: 600;
        display: flex; align-items: center; gap: 10px;
    }
    .tsb-banner-fresh    { background:#0D2B20; color:#6EE7B7; border:1px solid #065F46; }
    .tsb-banner-building { background:#2B2005; color:#FCD34D; border:1px solid #92400E; }
    .tsb-banner-fatigued { background:#2B0A0A; color:#FCA5A5; border:1px solid #991B1B; }

    /* ── Activity cards ────────────────────────────────────────────────── */
    .activity-card {
        background: #1C1F2E; border-radius: 10px;
        border: 1px solid #2E3250;
        padding: 14px 18px; margin-bottom: 8px;
        display: flex; align-items: center; gap: 14px;
    }
    .activity-card-icon   { font-size: 1.5rem; min-width: 36px; text-align: center; }
    .activity-card-body   { flex: 1; min-width: 0; }
    .activity-card-name   {
        font-size: 0.9rem; font-weight: 600; color: #E8ECF4;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 4px;
    }
    .activity-card-stats  { display: flex; flex-wrap: wrap; gap: 12px; }
    .activity-stat        { display: flex; flex-direction: column; gap: 1px; }
    .activity-stat-value  { font-size: 0.85rem; font-weight: 700; color: #CBD5E1; }
    .activity-stat-label  {
        font-size: 0.65rem; font-weight: 600; color: #5B657D;
        text-transform: uppercase; letter-spacing: 0.05em;
    }
    .activity-card-tss       { text-align: right; min-width: 48px; }
    .activity-card-tss-value { font-size: 1.3rem; font-weight: 700; color: #4D9FFF; line-height: 1; }
    .activity-card-tss-label {
        font-size: 0.62rem; font-weight: 600; color: #5B657D;
        text-transform: uppercase; letter-spacing: 0.05em;
    }

    /* ── st.metric override ────────────────────────────────────────────── */
    [data-testid="stMetric"] {
        background: #1C1F2E !important;
        border-radius: 12px; padding: 16px;
        border: 1px solid #2E3250;
    }
    [data-testid="stMetricValue"] {
        font-size: 2rem !important; font-weight: 700 !important;
        color: #4D9FFF !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.72rem !important; font-weight: 600 !important;
        color: #94A3B8 !important; text-transform: uppercase; letter-spacing: 0.07em;
    }

    /* ── Tabs ──────────────────────────────────────────────────────────── */
    [data-testid="stTabs"] [role="tablist"] {
        border-bottom: 1px solid #2E3250; gap: 0;
    }
    [data-testid="stTabs"] [role="tab"] {
        font-size: 0.85rem; font-weight: 600; color: #5B657D;
        padding: 8px 16px; border-bottom: 2px solid transparent;
        margin-bottom: -1px; transition: color 0.15s, border-color 0.15s;
    }
    [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
        color: #4D9FFF !important; border-bottom: 2px solid #4D9FFF !important;
    }

    /* ── Buttons ───────────────────────────────────────────────────────── */
    [data-testid="stBaseButton-primary"],
    [data-testid="stBaseButton-primaryFormSubmit"] {
        background-color: #4D9FFF !important; border-color: #4D9FFF !important;
        color: #ffffff !important; border-radius: 8px !important;
        font-weight: 600 !important;
    }
    [data-testid="stBaseButton-primary"]:hover {
        background-color: #2E86F5 !important; border-color: #2E86F5 !important;
    }
    [data-testid="stBaseButton-secondary"] {
        background-color: #1C1F2E !important;
        border-color: #2E3250 !important; color: #CBD5E1 !important;
        border-radius: 8px !important; font-weight: 600 !important;
    }

    /* ── Divider ───────────────────────────────────────────────────────── */
    hr { border-color: #2E3250 !important; margin: 16px 0 !important; }

    /* ── Expander ──────────────────────────────────────────────────────── */
    [data-testid="stExpander"] {
        background: #1C1F2E !important;
        border: 1px solid #2E3250 !important;
        border-radius: 10px !important; box-shadow: none !important;
    }
    [data-testid="stExpander"] summary {
        color: #CBD5E1 !important;
    }

    /* ── Plotly charts ─────────────────────────────────────────────────── */
    [data-testid="stPlotlyChart"] {
        border-radius: 12px; overflow: hidden;
        background: #1C1F2E; border: 1px solid #2E3250;
    }

    /* ── Dataframes ────────────────────────────────────────────────────── */
    [data-testid="stDataFrame"] {
        background: #1C1F2E !important; border-radius: 10px !important;
        border: 1px solid #2E3250 !important;
    }

    /* ── Alerts / info boxes ───────────────────────────────────────────── */
    [data-testid="stAlert"] {
        border-radius: 10px !important;
    }
    [data-testid="stAlert"][data-baseweb="notification"] {
        background: #1C1F2E !important;
    }

    /* ── Chat messages ─────────────────────────────────────────────────── */
    [data-testid="stChatMessage"] {
        background: #1C1F2E !important;
        border: 1px solid #2E3250 !important;
        border-radius: 12px !important;
    }

    /* ── Main content padding ──────────────────────────────────────────── */
    [data-testid="stMain"] > div:first-child { padding-top: 1rem; }
    </style>
    """, unsafe_allow_html=True)
