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


def widget_key(key: str) -> str:
    """The key a zoomable chart is really drawn under. It changes each time Reset zoom
    is pressed, which is how the chart is put back to its full range."""
    return f"{key}_{st.session_state.get(f'_zoom_{key}', 0)}"


def clear(key: str) -> None:
    """Clear a chart's zoom or selection, as its own reset button does. Safe as a callback."""
    _bump_zoom(f"_zoom_{key}")


def selected_range(key: str) -> tuple[float, float] | None:
    """The left and right edge, in the chart's x units, of the box the rider dragged on a
    chart drawn with zoom="select". None when nothing is selected. Read from the chart's own
    state, so it is already up to date at the top of the run that follows a drag."""
    state = st.session_state.get(widget_key(key))
    try:
        boxes = state["selection"]["box"]
    except (KeyError, TypeError):
        return None
    xs = [x for b in boxes for x in (b.get("x") or []) if isinstance(x, (int, float))]
    if len(xs) < 2 or max(xs) <= min(xs):
        return None
    return float(min(xs)), float(max(xs))


def show(fig: go.Figure, key: str | None = None, *, zoom: str | None = "x", reset_button: bool = True,
         **kwargs):
    """Render a themed figure. Extra keyword arguments (on_select, selection_mode)
    pass straight to st.plotly_chart, whose return value is passed back.

    zoom="x" (the default, for charts over time): drag across the dates you want
    and only the dates zoom, the values fit themselves. A Reset zoom button above
    the chart (and a double click on it) goes back to the full range. The button
    works by giving the chart a fresh key. zoom=None turns zooming off, for charts
    that aren't over time.

    zoom="select": dragging across highlights that part of the chart and reruns the
    page, so the numbers around it can describe what is highlighted (see
    selected_range). The button above the chart then says Clear selection."""
    config = {"displayModeBar": False}
    if zoom is None:
        fig.update_layout(dragmode=False)
        fig.update_xaxes(fixedrange=True)
        fig.update_yaxes(fixedrange=True)
        return st.plotly_chart(fig, theme=None, width="stretch", key=key, config=config, **kwargs)

    selecting = zoom == "select"
    fig.update_layout(dragmode="select" if selecting else "zoom")
    if selecting:
        fig.update_layout(selectdirection="h")
        kwargs.setdefault("on_select", "rerun")
        kwargs.setdefault("selection_mode", ("box",))
    fig.update_yaxes(fixedrange=True)
    config["doubleClick"] = "reset"
    if key and not reset_button:
        key = widget_key(key)
    elif key:
        counter = f"_zoom_{key}"
        with st.container(horizontal=True, horizontal_alignment="right"):
            st.button("Clear selection" if selecting else "Reset zoom", key=f"{key}_reset",
                      icon=":material/refresh:", type="tertiary", on_click=_bump_zoom, args=(counter,),
                      help=("Drag across the part you want to look at. The numbers follow it. "
                            "This clears the selection." if selecting else
                            "Drag across the dates you want to zoom in. This puts the full range back."))
        key = f"{key}_{st.session_state.get(counter, 0)}"
    return st.plotly_chart(fig, theme=None, width="stretch", key=key, config=config, **kwargs)
