"""
The fitness history tables on the Dashboard: recent weeks, recent months and
all time, with totals and the best power or heart rate for each duration.
Rows come from metrics.analysis.period_history.
"""
from __future__ import annotations

import html

import streamlit as st

from metrics.analysis import HISTORY_DURATIONS

MILES = 1609.344
COLUMN_LABELS = {5: "5s", 60: "1m", 300: "5m", 1200: "20m", 3600: "60m"}


def _hms(seconds: float) -> str:
    s = int(round(seconds or 0))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def table_html(rows: list, kind: str, unit: str) -> str:
    """kind is "power" or "hr"; unit is "km" or "mi"."""
    per_unit = MILES if unit == "mi" else 1000.0
    show_kj = kind == "power"
    peak_cols = [COLUMN_LABELS[d] for d in HISTORY_DURATIONS]
    head = ["Week of", "Duration", f"Distance ({unit})", "TSS"] + (["kJ"] if show_kj else []) + peak_cols
    width = len(head)

    def cells(r):
        out = [html.escape(r["label"]), _hms(r["seconds"]), f"{r['meters'] / per_unit:,.0f}",
               f"{r['tss']:,.0f}"]
        if show_kj:
            out.append(f"{r['kj']:,.0f}")
        tds = "".join(f"<td>{c}</td>" for c in out)
        for d in HISTORY_DURATIONS:
            v = r[kind].get(d)
            tds += f"<td class='pk'>{v:,.0f}</td>" if v else "<td>–</td>"
        return tds

    body = []
    for section, title in (("week", None), ("month", "Recent months"), ("all", None)):
        if title:
            body.append(f"<tr class='sec'><td colspan='{width}'>{title}</td></tr>")
        for r in rows:
            if r["section"] != section:
                continue
            cls = "all" if section == "all" else ("cur" if r["current"] else "")
            body.append(f"<tr class='{cls}'>{cells(r)}</tr>")
    header = "".join(f"<th>{h}</th>" for h in head)
    return (f"<div class='hist-wrap'><table class='hist-table'><thead><tr>{header}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>")


def render(rows: list, kind: str, unit: str) -> None:
    st.markdown(table_html(rows, kind, unit), unsafe_allow_html=True)
