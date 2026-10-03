"""
Help icons and tooltips that explain a number or chart in plain words.
The wording lives in metrics/explain.py, so every page says the same thing.
"""
from __future__ import annotations

import streamlit as st

from metrics import explain


@st.cache_data(ttl=15, show_spinner=False)
def rider_numbers() -> dict:
    """The rider's own numbers for the "Your number" part of a help card."""
    from db.queries import get_setting
    from metrics.training_load import get_current_metrics

    def num(key):
        try:
            return float(get_setting(key, 0) or 0) or None
        except (TypeError, ValueError):
            return None

    from components.units import weight_unit
    m = get_current_metrics()
    return {"ftp": num("ftp_watts"), "weight": num("weight_kg"), "weight_unit": weight_unit(),
            "estimated": get_setting("ftp_estimated", "") == "1",
            "ctl": m["ctl"], "atl": m["atl"], "tsb": m["tsb"], "ramp": m["ramp_rate"]}


def help_icon(term: str, key: str, label: str = "", **numbers) -> None:
    """A small help icon (or a labelled button when `label` is given) that opens
    what the term is, why it matters and what the rider's own number means.
    Numbers not passed in are filled from the rider's current values."""
    numbers = {**rider_numbers(), **numbers}
    with st.popover(label, icon=":material/help:", key=f"help_{key}",
                    help="What is this?" if not label else None):
        st.markdown(explain.card(term, **numbers))


def tip(name: str) -> str | None:
    """Short text for the help= tooltip on a tile, column or input."""
    return explain.TIPS.get(name)


def setting_help(name: str) -> str | None:
    return explain.SETTINGS_HELP.get(name)
