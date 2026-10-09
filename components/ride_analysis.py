"""
The ride analysis popup: open a ride from the calendar (or the Progress page) and see what
happened, with the right charts for it.

It shows the numbers, what was planned that day, a timeline of power, heart rate and
climbing you can zoom, time in each zone, the hard efforts, this ride's best power
against your best ever, and a review from your coach. The timeline and zone charts
need second by second data, which is fetched from Garmin or Strava the first time you
open a ride and then kept. Without it the popup still shows the numbers and the
estimated zones.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from auth import ride_data
from components import charts, ride_detail, theme
from components.units import climb_input, distance_input, distance_unit
from db.queries import (clear_activity_tss, ftp_on, get_activity, get_peaks_between, get_report, get_setting,
                        hr_profile,
                        get_workouts, recalculate_all_tss, save_report, set_activity_tss,
                        update_activity_details)
from metrics import analysis as an
from metrics import streams as sm
from metrics.explain import TIPS
from metrics.tss import label as tss_label, mismatch as tss_mismatch, ref_numbers as tss_numbers
from metrics.units import (climb_from_m, climb_unit, dist_from_km, fmt_climb, fmt_distance, speed_from_kph,
                           speed_unit)
from metrics.zones import HR_ZONE_NAMES, POWER_ZONE_NAMES, ZONE_COLORS, get_hr_zones, get_power_zones

SMOOTHING = {"Raw": 1, "10 s": 10, "30 s": 30, "60 s": 60}


def _n(v):
    try:
        return float(v) if v is not None and v == v else None
    except (TypeError, ValueError):
        return None


def _fmt(v, spec: str, unit: str = "") -> str:
    return f"{v:{spec}}{unit}" if v is not None else "–"


# ── Numbers ───────────────────────────────────────────────────────────────────

def summary_numbers(act: dict, streams: dict | None) -> dict:
    """The ride's headline numbers. Stored values win, and gaps are filled from the
    second by second data when there is any."""
    power = (streams or {}).get("power") or []
    hr = (streams or {}).get("hr") or []
    live = sm.numbers_from_streams(streams or {}, float(get_setting("ftp_watts", 0) or 0)) if streams else {}
    secs = _n(act.get("duration_seconds"))
    meters = _n(act.get("distance_meters")) or live.get("meters")
    avg_w = _n(act.get("avg_power_watts")) or live.get("avg_w")
    np_w = _n(act.get("normalized_power")) or live.get("np")
    avg_hr = _n(act.get("avg_hr")) or live.get("avg_hr")
    return {
        "secs": secs or live.get("secs"), "meters": meters,
        "climb": _n(act.get("elevation_gain_meters")) or live.get("climb"), "tss": _n(act.get("tss")),
        "tss_source": act.get("tss_source"),
        "avg_w": avg_w, "np": np_w, "if": _n(act.get("if_value")),
        "vi": np_w / avg_w if np_w and avg_w else None,
        "avg_hr": avg_hr, "max_hr": _n(act.get("max_hr")) or live.get("max_hr"),
        "kj": avg_w * (secs or live.get("secs") or 0) / 1000 if avg_w else None,
        "ef": np_w / avg_hr if np_w and avg_hr else None,
        "max_w": live.get("max_w"),
        "avg_speed": meters / secs if meters and secs else live.get("avg_speed"),   # meters per second
        "max_speed": live.get("max_speed"), "avg_cad": live.get("avg_cad"),
        "decoupling": sm.decoupling(power, hr) if power and hr else None,
    }


def _speed(ms: float | None, unit: str) -> str:
    """Speed from meters per second, in mph or km/h to match the distance unit."""
    if not ms:
        return "–"
    kph = ms * 3.6
    return f"{speed_from_kph(kph, unit):.1f} {speed_unit(unit)}"


def _tiles(n: dict) -> None:
    unit = distance_unit()
    h, m = (divmod(int(n["secs"] // 60), 60) if n["secs"] else (None, None))
    rows = [
        [("Time", f"{h}h {m:02d}m" if h else (f"{m} min {int(n['secs']) % 60:02d}s" if m is not None else "–"), None),
         ("Distance", fmt_distance(n["meters"], unit) or "–", None),
         ("Climbing", fmt_climb(n["climb"], unit) or (f"0 {climb_unit(unit)}" if n["climb"] == 0 else "–"), None),
         (tss_label(n.get("tss_source")), _fmt(n["tss"], ".0f"),
          TIPS["hrtss"] if n.get("tss_source") in ("hr", "mixed") else TIPS["tss"])],
        [("Avg power", _fmt(n["avg_w"], ".0f", " W"), TIPS["avg_w"]),
         ("Normalized", _fmt(n["np"], ".0f", " W"), TIPS["np"]),
         ("Intensity", _fmt(n["if"], ".2f"), TIPS["if"]),
         ("Variability", _fmt(n["vi"], ".2f"),
          "Normalized power divided by average power. Close to 1.00 is a steady ride, higher means surges.")],
        [("Avg speed", _speed(n["avg_speed"], unit), "Distance divided by time."),
         ("Max speed", _speed(n["max_speed"], unit), None),
         ("Avg cadence", _fmt(n["avg_cad"], ".0f", " rpm"), "Pedal revolutions per minute, not counting stops."),
         ("Max power", _fmt(n["max_w"], ".0f", " W"), None)],
        [("Avg heart rate", _fmt(n["avg_hr"], ".0f", " bpm"), None),
         ("Max heart rate", _fmt(n["max_hr"], ".0f", " bpm"), None),
         ("Work", _fmt(n["kj"], ".0f", " kJ"), TIPS["kj"]),
         ("Efficiency", _fmt(n["ef"], ".2f"), TIPS["ef"])],
    ]
    for row in rows:
        for col, (label, value, tip) in zip(st.columns(4), row):
            col.metric(label, value, help=tip)


def _same(a, b, digits: int = 0) -> bool:
    """Two optional numbers that agree once rounded."""
    return (round(a, digits) if a else None) == (round(b, digits) if b else None)


def _save_ride_edits(act: dict, new: dict, tss: float) -> bool:
    """Write the changes from the Edit ride form. Returns False when nothing changed.
    A TSS you typed is locked in. When only the inputs to the TSS maths changed (time, power,
    heart rate) and the TSS was not typed over, it is worked out again from the new values."""
    unit = distance_unit()
    changed = {k: new[k] for k in ("duration_seconds", "avg_power_watts", "normalized_power", "avg_hr", "max_hr")
               if not _same(new[k], act.get(k))}
    if new["name"] != act.get("name"):
        changed["name"] = new["name"]
    if not _same(dist_from_km(new["distance_meters"] / 1000, unit),
                 dist_from_km((act.get("distance_meters") or 0) / 1000, unit), 1):
        changed["distance_meters"] = new["distance_meters"]
    if not _same(climb_from_m(new["elevation_gain_meters"], unit),
                 climb_from_m(act.get("elevation_gain_meters") or 0, unit)):
        changed["elevation_gain_meters"] = new["elevation_gain_meters"]
    tss_changed = round(tss) != round(_n(act.get("tss")) or 0)
    if not changed and not tss_changed:
        return False
    if changed:
        update_activity_details(act["id"], changed)
    if tss_changed:
        set_activity_tss(act["id"], tss)
    elif any(k in changed for k in ("duration_seconds", "avg_power_watts", "normalized_power", "avg_hr")) \
            and not act.get("tss_locked"):
        recalculate_all_tss(only_id=act["id"])
    return True


def _whole_input(where, label: str, value, cap: int, key: str, **kwargs) -> int:
    """A whole number input that starts at the stored value. The maximum stretches to fit a
    stored value above the usual cap, so an unusual ride never stops the window opening."""
    start = int(round(_n(value) or 0))
    return where.number_input(label, 0, max(cap, start), start, key=key, **kwargs)


def _edit_ride(act: dict) -> None:
    """Let the rider correct a ride that is off, such as a power meter dropout, an indoor ride logged
    without power, or a wrong name. Edits are kept when the ride syncs again."""
    import zlib

    unit = distance_unit()
    edited = bool(act.get("edited") or act.get("tss_locked"))
    stored = (act.get("name"), act.get("duration_seconds"), act.get("distance_meters"),
              act.get("elevation_gain_meters"), act.get("avg_power_watts"), act.get("normalized_power"),
              act.get("avg_hr"), act.get("max_hr"), act.get("tss"))
    key = f"ra_edit_{act['id']}_{zlib.crc32(repr(stored).encode())}"
    text, button = st.columns([4, 1], vertical_alignment="center")
    text.caption("You corrected this ride by hand. Your numbers are kept when it syncs again."
                 if edited else "Something wrong with this ride? You can correct it.")
    with button.popover("Edit ride", icon=":material/edit:", width="stretch"):
        st.caption("Fix whatever is off. Your fitness, fatigue and form numbers use these values, and they are "
                   "kept when the ride syncs again. Leave a power or heart rate at 0 if the ride has none.")
        name = st.text_input("Name", value=act.get("name") or "", key=f"{key}_name")
        secs = int(_n(act.get("duration_seconds")) or 0)
        h, m = st.columns(2)
        hours = h.number_input("Hours", 0, max(48, secs // 3600), secs // 3600, key=f"{key}_h")
        mins = m.number_input("Minutes", 0, 59, (secs % 3600) // 60, key=f"{key}_m")
        d, c = st.columns(2)
        with d:
            km = (_n(act.get("distance_meters")) or 0) / 1000
            meters = distance_input("Distance", km, key=f"{key}_d", unit=unit, min_km=0,
                                    max_km=max(1500, km + 1), step_km=1.0, step_mi=1.0) * 1000
        with c:
            up = _n(act.get("elevation_gain_meters")) or 0
            climb = climb_input("Climbing", up, key=f"{key}_c", unit=unit, min_m=0, max_m=max(15000, up + 100))
        p1, p2 = st.columns(2)
        avg_w = _whole_input(p1, "Average power (W)", act.get("avg_power_watts"), 2000, f"{key}_aw")
        np_w = _whole_input(p2, "Normalized power (W)", act.get("normalized_power"), 2000, f"{key}_np")
        q1, q2 = st.columns(2)
        avg_hr = _whole_input(q1, "Average heart rate", act.get("avg_hr"), 250, f"{key}_ah")
        max_hr = _whole_input(q2, "Max heart rate", act.get("max_hr"), 250, f"{key}_mh")
        tss = _whole_input(st, "TSS", act.get("tss"), 1500, f"{key}_tss", step=5,
                              help="Training stress for the whole ride. One hour at your FTP is 100. If you only "
                                   "change the time, power or heart rate, it is worked out again for you.")
        new = {"name": name.strip() or act.get("name"), "duration_seconds": hours * 3600 + mins * 60,
               "distance_meters": meters, "elevation_gain_meters": climb,
               "avg_power_watts": avg_w or None, "normalized_power": np_w or None,
               "avg_hr": avg_hr or None, "max_hr": max_hr or None}
        if st.button("Save changes", key=f"{key}_save", type="primary", icon=":material/save:", width="stretch"):
            if new["duration_seconds"] <= 0:
                st.warning("Give the ride a time first.")
            elif _save_ride_edits(act, new, tss):
                st.rerun(scope="fragment")
            else:
                st.info("Nothing changed.")
        if act.get("tss_locked") and st.button("Use the calculated TSS", key=f"{key}_clear", width="stretch"):
            clear_activity_tss(act["id"])
            st.rerun(scope="fragment")


def _planned_tab(planned: list[dict], n: dict) -> None:
    for w in planned:
        with st.container(border=True):
            plan = _n(w.get("tss_planned"))
            line = f"**{w['name']}**" + (f", {plan:.0f} TSS planned" if plan else "")
            if plan and n["tss"]:
                line += f", {n['tss']:.0f} TSS ridden ({(n['tss'] - plan) / plan * 100:+.0f}%)"
            st.markdown(line)
            if w.get("purpose"):
                st.markdown(f"**Why.** {w['purpose']}")
            if w.get("feel"):
                st.markdown(f"**How it should feel.** {w['feel']}")
            if w.get("description"):
                st.caption(w["description"])
            if n["if"] and w.get("workout_type"):
                st.caption(f"It was meant to be a {w['workout_type'].lower()} workout. Your intensity factor "
                           f"was {n['if']:.2f}.")


# ── Charts ────────────────────────────────────────────────────────────────────

# ── The part of the ride being looked at ─────────────────────────────────────
# The popup keeps a stack of zoom levels. Each drag on the timeline narrows the view to the
# dragged part, and that part is locked in for everything in the popup: the numbers, the
# timeline, zones, efforts and the power curve. Dragging again inside it goes one level deeper.
# Back goes up a level. `gen` changes with every move so the chart starts fresh and an old
# drag box never lingers on a view it no longer belongs to.

MIN_SECONDS = 10


def _view_state(act_id: int) -> dict:
    return st.session_state.setdefault(f"ra_view_{act_id}", {"stack": [], "gen": 0})


def timeline_key(act_id: int) -> str:
    return f"ra_timeline_{act_id}_{_view_state(act_id)['gen']}"


def reset_view(act_id: int) -> None:
    """Start a ride at its whole length. Called when the popup is opened."""
    st.session_state[f"ra_view_{act_id}"] = {"stack": [], "gen": _view_state(act_id)["gen"] + 1}


def _back(act_id: int) -> None:
    vs = _view_state(act_id)
    if vs["stack"]:
        vs["stack"].pop()
    vs["gen"] += 1


def _whole(act_id: int) -> None:
    vs = _view_state(act_id)
    vs["stack"].clear()
    vs["gen"] += 1


def current_range(act_id: int, length: int) -> tuple[int, int]:
    """The seconds shown right now: the last zoom level, or the whole ride."""
    stack = _view_state(act_id)["stack"]
    return stack[-1] if stack else (0, length)


def take_drag(act_id: int, length: int) -> bool:
    """If the rider just dragged a box on the timeline, zoom into it. Returns True when the
    view changed, and the caller should rerun the popup so everything redraws for it."""
    box = charts.selected_range(timeline_key(act_id))     # minutes, from the chart
    if not box:
        return False
    lo, hi = current_range(act_id, length)
    start, end = max(int(box[0] * 60), lo), min(int(box[1] * 60) + 1, hi)
    if end - start < MIN_SECONDS or (start, end) == (lo, hi):
        return False
    vs = _view_state(act_id)
    vs["stack"].append((start, end))
    vs["gen"] += 1
    return True


def _timeline(act: dict, streams: dict, ftp: float, lthr: float, window_range: tuple[int, int]) -> None:
    unit = distance_unit()
    window = SMOOTHING[st.segmented_control("Smoothing", list(SMOOTHING), default="30 s",
                                            key=f"ra_smooth_{act['id']}") or "30 s"]
    kph_factor = 3.6 / (1.609344 if unit == "mi" else 1.0)
    rows = [(k, label, color) for k, label, color in (
        ("power", "Power (W)", theme.FATIGUE), ("hr", "Heart rate (bpm)", theme.BAD),
        ("speed", f"Speed ({speed_unit(unit)})", theme.GOOD),
        ("cad", "Cadence (rpm)", theme.ACCENT), ("alt", f"Elevation ({climb_unit(unit)})", theme.TEXT3))
        if streams.get(k)]
    if not rows:
        st.caption("This ride has no power, heart rate, speed or elevation data to chart.")
        return
    cum = sm.cumulative_distance(streams)
    fig = make_subplots(rows=len(rows), cols=1, shared_xaxes=True, vertical_spacing=0.04,
                        row_heights=[2 if k == "power" else 1 for k, _, _ in rows])
    for i, (key, label, color) in enumerate(rows, start=1):
        raw = streams[key]
        if key == "speed":
            raw = [None if v is None else v * kph_factor for v in raw]
        elif key == "alt":
            raw = [None if v is None else climb_from_m(v, unit) for v in raw]
        values = raw if key == "alt" else sm.smooth(raw, window)      # smoothed over the whole ride first
        xs, ys = sm.downsample(values[window_range[0]:window_range[1]])
        xs = [x + window_range[0] for x in xs]                         # keep the ride's own clock
        minutes = [x / 60 for x in xs]
        if i == 1:
            first_x, first_y = minutes, ys
        hover = [hover_label(x, cum, unit) for x in xs]
        kwargs = dict(fill="tozeroy", fillcolor=charts_rgba(color, 0.12)) if key == "alt" else {}
        fig.add_trace(go.Scatter(x=minutes, y=ys, mode="lines", name=label, line=dict(color=color, width=1.6),
                                 customdata=hover, connectgaps=False, selected=dict(marker=dict(opacity=0)),
                                 hovertemplate="%{customdata}  %{y:.1f}<extra>" + label + "</extra>", **kwargs),
                      row=i, col=1)
        fig.update_yaxes(title_text=label, row=i, col=1)
        if key == "alt":
            vals = [v for v in ys if v is not None]
            if vals:
                pad = 5 if unit == "km" else 16
                fig.update_yaxes(range=[min(vals) - pad, max(vals) + pad], row=i, col=1)
        if key == "power" and ftp:
            fig.add_hline(y=ftp, line_dash="dash", line_color=theme.TEXT3, line_width=1, row=i, col=1,
                          annotation_text="FTP", annotation_position="top left",
                          annotation_font_size=11, annotation_font_color=theme.TEXT3)
        if key == "hr" and lthr:
            fig.add_hline(y=lthr, line_dash="dash", line_color=theme.TEXT3, line_width=1, row=i, col=1)
    # Invisible markers on the first row give the drag something to land on, so Streamlit
    # reports the box that was dragged even though the lines themselves have no points.
    fig.add_trace(go.Scatter(x=first_x, y=first_y, mode="markers", marker=dict(size=14, opacity=0),
                             showlegend=False, hoverinfo="skip"), row=1, col=1)
    charts.apply_theme(fig, height=200 + 140 * len(rows), legend="none")
    # apply_theme styles the first axes only, so give every row the same quiet grid
    fig.update_xaxes(gridcolor=theme.GRID, linecolor=theme.BORDER, zeroline=False,
                     tickfont=dict(size=12, color=theme.TEXT2))
    fig.update_yaxes(gridcolor=theme.GRID, linecolor=theme.BORDER, zeroline=False, automargin=True,
                     tickfont=dict(size=12, color=theme.TEXT2), title_font=dict(size=12, color=theme.TEXT2))
    fig.update_layout(hovermode="x unified")
    cumulative = sm.cumulative_distance(streams)
    ticks = sm.distance_ticks(cumulative, window_range[0], window_range[1],
                              1609.344 if unit == "mi" else 1000.0) if cumulative else []
    if ticks:
        # Distance along the top and the bottom, with the clock time under the bottom labels,
        # so it is clear where on the road each part of the ride happened.
        values = [i / 60 for _, i in ticks]
        bottom = [f"{v:g} {unit}<br>{sm.elapsed_label(i)}" for v, i in ticks]
        top = [f"{v:g} {unit}" for v, _ in ticks]
        fig.update_xaxes(tickvals=values, ticktext=bottom, row=len(rows), col=1)
        fig.update_xaxes(tickvals=values, ticktext=top, side="top", showticklabels=True, row=1, col=1)
        fig.update_xaxes(title_text=f"Distance ({unit}) and elapsed time", title_standoff=14,
                         row=len(rows), col=1)
    else:
        fig.update_xaxes(title_text="Minutes", title_standoff=14, row=len(rows), col=1)
    fig.update_xaxes(automargin=True)
    fig.update_layout(margin=dict(t=44, b=70))
    charts.show(fig, key=timeline_key(act["id"]), zoom="select", reset_button=False)
    deeper = " Drag again inside it to zoom in further." if window_range != (0, length_of(streams)) else ""
    st.caption("Drag across a part of the ride to zoom in on it. The numbers, zones, efforts and power curve "
               f"all switch to that part.{deeper} The dashed lines are your FTP and threshold heart rate.")


def hover_label(second: int, cum: list[float] | None, unit: str) -> str:
    """The time into the ride, and how far along it was, for the hover text."""
    label = sm.elapsed_label(second)
    if cum and 0 <= second < len(cum):
        label += f" · {cum[second] / (1609.344 if unit == 'mi' else 1000.0):.1f} {unit}"
    return label


def length_of(streams: dict) -> int:
    return max((len(v) for v in streams.values()), default=0)


def charts_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def _zone_chart(act_id: int, secs: list[float], names: list[str], colors: list[str], key: str,
                ranges: list[str]) -> None:
    total = sum(secs)
    if total <= 0:
        st.caption("No data for these zones.")
        return
    fig = go.Figure(go.Bar(
        x=[f"Z{i + 1}" for i in range(len(secs))], y=[s / 60 for s in secs], marker_color=colors[:len(secs)],
        marker_line_width=0, customdata=[[names[i], ranges[i], sm.elapsed_label(s), s / total * 100]
                                         for i, s in enumerate(secs)],
        hovertemplate="%{customdata[0]}<br>%{customdata[1]}<br>%{customdata[2]}, %{customdata[3]:.0f}%"
                      "<extra></extra>"))
    charts.apply_theme(fig, height=230, legend="none")
    fig.update_yaxes(title_text="Minutes")
    charts.show(fig, key=f"{key}_{act_id}", zoom=None)
    table = pd.DataFrame([{"Zone": f"Z{i + 1} {names[i]}", "Range": ranges[i],
                           "Time": sm.elapsed_label(s), "Share": f"{s / total * 100:.0f}%"}
                          for i, s in enumerate(secs) if s > 0])
    st.dataframe(table, hide_index=True, width="stretch")


def _zones(act: dict, streams: dict, ftp: float, lthr: float, offset: int = 0) -> None:
    power = streams.get("power")
    if power and ftp:
        st.markdown("**Time in power zones**")
        zones = get_power_zones(ftp)
        ranges = [f"{z['min_watts']} to {z['max_watts']} W" if z["max_watts"] else f"{z['min_watts']} W and up"
                  for z in zones]
        _zone_chart(act["id"], sm.power_zone_seconds(power, ftp), POWER_ZONE_NAMES, ZONE_COLORS, "ra_pz", ranges)
    hr = streams.get("hr")
    if hr and lthr:
        st.markdown("**Time in heart rate zones**")
        zones = get_hr_zones(lthr)
        ranges = [f"{z['min_bpm']} to {z['max_bpm']} bpm" if z["max_bpm"] else f"{z['min_bpm']} bpm and up"
                  for z in zones]
        _zone_chart(act["id"], sm.hr_zone_seconds(hr, lthr), HR_ZONE_NAMES, ZONE_COLORS, "ra_hz", ranges)
    if not (power and ftp) and not (hr and lthr):
        st.caption("This ride has no power or heart rate data, so there are no zones to show.")

    if power and ftp:
        efforts = sm.find_efforts(power, ftp, hr)
        st.markdown("**Hard efforts**")
        if not efforts:
            st.caption("No stretch of 4 minutes or more at 90% of your FTP or higher.")
        else:
            st.dataframe(pd.DataFrame([{
                "Start": sm.elapsed_label(e["start"] + offset), "Length": sm.elapsed_label(e["seconds"]),
                "Avg W": round(e["avg_power"]), "% FTP": f"{e['avg_power'] / ftp * 100:.0f}%",
                "Avg HR": round(e["avg_hr"]) if e["avg_hr"] else None} for e in efforts]),
                hide_index=True, width="stretch")


def _peaks(act: dict, streams: dict, part: bool = False) -> None:
    power = streams.get("power")
    if not power:
        st.caption("This ride has no power data, so there is no power curve.")
        return
    secs = len(power)
    durations = [d for d in an.PEAK_DURATIONS if d <= secs]
    mine = sm.ride_peaks(power, durations)
    best = an.peak_curve(get_peaks_between("0000-01-01", "9999-12-31") + [
        {"activity_id": act["id"], "date": act["date"], "name": act.get("name"), "duration_s": d, "watts": w}
        for d, w in mine.items()])
    fig = go.Figure()
    fig.add_scatter(x=list(best), y=[v["watts"] for v in best.values()], mode="lines", name="Best ever",
                    line=dict(color=theme.TEXT3, width=2, dash="dot"),
                    customdata=[[an.duration_label(d), v["date"]] for d, v in best.items()],
                    hovertemplate="%{customdata[0]}: %{y:.0f} W<br>%{customdata[1]}<extra>Best ever</extra>")
    fig.add_scatter(x=list(mine), y=list(mine.values()), mode="lines+markers", name="This part" if part else "This ride",
                    line=dict(color=theme.FATIGUE, width=3), marker=dict(size=6),
                    customdata=[[an.duration_label(d)] for d in mine],
                    hovertemplate="%{customdata[0]}: %{y:.0f} W<extra>" + ("This part" if part else "This ride") + "</extra>")
    ticks = [d for d in durations if d in mine]
    charts.apply_theme(fig, height=300, legend="top")
    fig.update_xaxes(type="log", tickvals=ticks, ticktext=[an.duration_label(d) for d in ticks])
    fig.update_yaxes(title_text="Watts")
    charts.show(fig, key=f"ra_peaks_{act['id']}", zoom=None)
    rows = []
    for d in [d for d in an.KEY_DURATIONS if d in durations]:
        if d in mine:
            ever = best.get(d, {}).get("watts")
            rows.append({"Duration": an.duration_label(d), "This part" if part else "This ride": round(mine[d]),
                         "Best ever": round(ever) if ever else None,
                         "Share of best": f"{mine[d] / ever * 100:.0f}%" if ever else ""})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if any(r["Share of best"] == "100%" for r in rows):
        st.caption("A 100% means this ride set your best for that duration.")


# ── Coach ─────────────────────────────────────────────────────────────────────

def _coach(act: dict) -> None:
    import coach_context
    import coach_reports
    from components import coach_ui

    key, title, prompt = coach_reports.ride_review(act)
    existing = get_report("ride_review", key)
    if existing:
        st.markdown(existing["content"])
        st.caption(f"Written {coach_ui.local_time(existing['created_at'])}")
        return
    st.caption("Your coach reads this ride against your plan, your recovery and your training load.")
    if st.button("Review this ride with my coach", key=f"ra_review_{act['id']}", type="primary",
                 icon=":material/auto_awesome:"):
        proposals: list[dict] = []
        reply, error = coach_ui.stream_reply(
            coach_context.system_blocks(coach_reports.REPORT_RULES),
            [{"role": "user", "content": prompt}], coach_reports.EFFORT.get("ride_review", "medium"), proposals,
            coach_reports.MODEL.get("ride_review"))
        if not error and reply.strip():
            save_report("ride_review", key, title, reply)
            if proposals:
                st.session_state[f"proposals_ride_review_{key}"] = proposals
                st.info("Your coach suggested a workout. It is waiting for you to confirm on the Today page.")


# ── The popup ─────────────────────────────────────────────────────────────────

def _selection_banner(act_id: int, sel: tuple[int, int], whole: dict, now: dict) -> None:
    """Says plainly which part of the ride everything below is about, and how that part
    compares with the whole ride."""
    depth = len(_view_state(act_id)["stack"])
    with st.container(border=True):
        text, back, clear = st.columns([4, 1.3, 1.7], vertical_alignment="center")
        text.markdown(f"**Zoomed in.** {sm.elapsed_label(sel[0])} to {sm.elapsed_label(sel[1])}, "
                      f"{sm.elapsed_label(sel[1] - sel[0])} long. Everything in this window is for this part only.")
        back.button("Back", key=f"ra_back_{act_id}", icon=":material/arrow_back:", width="stretch",
                    on_click=_back, args=(act_id,), help="Zoom out one level")
        clear.button("Whole ride", key=f"ra_whole_{act_id}", icon=":material/zoom_out_map:", width="stretch",
                     on_click=_whole, args=(act_id,), disabled=depth == 0)
        bits = []
        if whole.get("avg_w") and now.get("avg_w"):
            bits.append(f"power {now['avg_w']:.0f} W against {whole['avg_w']:.0f} W for the whole ride")
        if whole.get("avg_hr") and now.get("avg_hr"):
            bits.append(f"heart rate {now['avg_hr']:.0f} bpm against {whole['avg_hr']:.0f}")
        if bits:
            st.caption("Average " + ", ".join(bits) + ".")


def render(act: dict) -> None:
    """The analysis for one ride, as drawn inside the popup."""
    ftp = ftp_on(act["date"])           # the FTP the ride was ridden at
    lthr = float(get_setting("lthr", 0) or 0)
    profile = hr_profile()
    st.markdown(f"### {act.get('name') or 'Ride'}")
    st.caption(f"{act['date']} · {an.ride_kind(act)} ride")

    with st.spinner("Loading the ride data…"):
        streams, note = ride_data.load_streams(act["id"])
    act = get_activity(act["id"]) or act    # loading the data can rescore a ride with heart rate
    whole = summary_numbers(act, streams)
    length = length_of(streams) if streams else 0
    if streams and take_drag(act["id"], length):
        st.rerun(scope="fragment")                  # redraw the whole popup for the new window
    lo, hi = current_range(act["id"], length) if streams else (0, 0)
    sel = (lo, hi) if streams and (lo, hi) != (0, length) else None
    view, offset, n = streams, 0, whole
    if sel:
        view, offset = sm.slice_streams(streams, lo, hi), lo
        n = sm.numbers_from_streams(view, ftp, lthr, profile)
        _selection_banner(act["id"], sel, whole, n)
    _tiles(n)
    _compare_with_service(act)
    _edit_ride(act)
    if n.get("decoupling") is not None:
        d = n["decoupling"]
        verdict = ("stayed steady" if d < 3 else "drifted a little" if d < 6 else
                   "drifted a lot, which can mean fatigue, heat or not enough fuel")
        st.caption(f"Pacing. From the first half {'of this part' if sel else 'of the ride'} to the second, your "
                   f"power to heart rate ratio {verdict} ({d:+.1f}%).")
    planned = get_workouts(act["date"], act["date"])

    if not streams:
        st.info(note, icon=":material/info:")
        if planned:
            st.markdown("**What was planned**")
            _planned_tab(planned, whole)
        ride_detail.ride_detail(act, key=f"ra_fallback_{act['id']}")
        if st.button("Try again", key=f"ra_retry_{act['id']}", icon=":material/refresh:"):
            st.rerun(scope="fragment")
        _coach(act)
        return

    labels = ["Timeline", "Zones and efforts", "Power curve"] + (["Plan"] if planned else []) + ["Coach"]
    tabs = dict(zip(labels, st.tabs(labels)))
    with tabs["Timeline"]:
        _timeline(act, streams, ftp, lthr, (lo, hi))
    with tabs["Zones and efforts"]:
        _zones(act, view, ftp, lthr, offset)
    with tabs["Power curve"]:
        _peaks(act, view, bool(sel))
    if planned:
        with tabs["Plan"]:
            _planned_tab(planned, whole)
    with tabs["Coach"]:
        _coach(act)


def _compare_with_service(act: dict) -> None:
    """The app's TSS next to the compared service's (TrainingPeaks or intervals.icu), with what
    explains a big difference."""
    import compare
    service = compare.compare_service()
    ref = tss_numbers(act, service)
    if not ref:
        return
    name = compare.service_name(service)
    gap = tss_mismatch(act, service)
    app = _n(act.get("tss"))
    line = (f"{name}: {ref['tss']:.0f} TSS"
            + (f" from {'heart rate' if ref.get('scored_by') == 'hr' else ref.get('scored_by')}"
               if ref.get("scored_by") in ("hr", "power") else "")
            + (f". This app: {app:.0f} {tss_label(act.get('tss_source'))}." if app is not None else "."))
    if not gap:
        st.caption(line + " They agree.")
        return
    with st.container(border=True):
        st.markdown(f":orange[**!**] **The app and {name} score this ride differently** "
                    f"({gap['diff']:+.0f} TSS, {gap['share'] * 100:.0f}%)")
        st.caption(line)
        for r in gap["reasons"]:
            st.markdown(f"- {r}")
        st.caption(f"If {name} has the right number, you can type it in with Edit ride below.")


def open_analysis(activity_id) -> None:
    """Open the popup for a ride, starting from the whole ride."""
    if activity_id is not None:
        reset_view(int(activity_id))
    ride_analysis_dialog(activity_id)


@st.dialog("Ride analysis", width="large")
def ride_analysis_dialog(activity_id) -> None:
    act = get_activity(int(activity_id)) if activity_id is not None else None
    if not act:
        st.info("That ride is no longer in the app.")
        return
    render(act)
