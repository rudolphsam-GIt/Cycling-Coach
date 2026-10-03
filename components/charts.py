"""
Shared Plotly styling so every chart in the app looks the same. Build the
figure with its data and colors (see SERIES and theme.ZONE_COLORS), then call
apply_theme and show.
"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from components import theme

SERIES = {"ctl": theme.FITNESS, "atl": theme.FATIGUE, "tsb": theme.GOOD}


def apply_theme(fig: go.Figure, height: int = 300, legend: str = "top",
                dual_y: bool = False) -> go.Figure:
    """Dark friendly look: transparent background, readable text, visible grid."""
    axis = dict(automargin=True, gridcolor=theme.GRID, zerolinecolor=theme.GRID,
                linecolor=theme.BORDER,
                tickfont=dict(size=12, color=theme.TEXT2),
                title_font=dict(size=12, color=theme.TEXT2))
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=theme.FONT_STACK, size=13, color=theme.TEXT2),
        margin=dict(l=8, r=8, t=36 if legend == "top" else 12, b=8),
        hoverlabel=dict(bgcolor=theme.RAISED, bordercolor=theme.BORDER,
                        font=dict(family=theme.FONT_STACK, size=13, color=theme.TEXT1)),
        legend=(dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                     font=dict(size=12, color=theme.TEXT2), bgcolor="rgba(0,0,0,0)")
                if legend == "top" else dict(font=dict(size=12, color=theme.TEXT2))),
        showlegend=legend != "none",
        xaxis=axis,
        yaxis=axis,
    )
    if dual_y:
        fig.update_layout(yaxis2=dict(axis, showgrid=False))
    return fig


def show(fig: go.Figure, key: str | None = None, **kwargs):
    """Render a themed figure. Extra keyword arguments (on_select, selection_mode)
    pass straight to st.plotly_chart, whose return value is passed back."""
    return st.plotly_chart(fig, theme=None, width="stretch", key=key,
                           config={"displayModeBar": False}, **kwargs)
