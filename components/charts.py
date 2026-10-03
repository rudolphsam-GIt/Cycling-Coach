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


def _bump_zoom(counter_key: str) -> None:
    st.session_state[counter_key] = st.session_state.get(counter_key, 0) + 1


def show(fig: go.Figure, key: str | None = None, *, zoom: str | None = "x", **kwargs):
    """Render a themed figure. Extra keyword arguments (on_select, selection_mode)
    pass straight to st.plotly_chart, whose return value is passed back.

    zoom="x" (the default, for charts over time): drag across the dates you want
    and only the dates zoom, the values fit themselves. A Reset zoom button above
    the chart (and a double click on it) goes back to the full range. The button
    works by giving the chart a fresh key. zoom=None turns zooming off, for charts
    that aren't over time."""
    config = {"displayModeBar": False}
    if zoom is None:
        fig.update_layout(dragmode=False)
        fig.update_xaxes(fixedrange=True)
        fig.update_yaxes(fixedrange=True)
        return st.plotly_chart(fig, theme=None, width="stretch", key=key, config=config, **kwargs)

    fig.update_layout(dragmode="zoom")
    fig.update_yaxes(fixedrange=True)
    config["doubleClick"] = "reset"
    if key:
        counter = f"_zoom_{key}"
        with st.container(horizontal=True, horizontal_alignment="right"):
            st.button("Reset zoom", key=f"{key}_reset", icon=":material/refresh:",
                      type="tertiary", on_click=_bump_zoom, args=(counter,),
                      help="Drag across the dates you want to zoom in. This puts the full range back.")
        key = f"{key}_{st.session_state.get(counter, 0)}"
    return st.plotly_chart(fig, theme=None, width="stretch", key=key, config=config, **kwargs)
