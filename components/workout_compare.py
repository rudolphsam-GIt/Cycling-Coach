"""
Planned against ridden: one planned workout next to the ride that did it.

Pure part: planned_numbers reads what the plan asked for (planned TSS, and when the
workout has saved steps, its length, power, intensity and time in each power zone).
ridden_numbers reads the same things from the ride (time in zones needs the ride's
second by second power, which is only used when it is already saved). comparison_rows
puts them side by side, and summary_line says in one sentence how it went.

Which ride goes with which workout is decided by components.calendar.pair_day, so the
calendar, this view and the ride analysis popup all agree.

Streamlit part: render draws the comparison. The Plan page shows it when you open a
done workout, and the ride analysis popup shows it in its Plan tab.
"""
from __future__ import annotations

from metrics.units import num as _num
from metrics.zones import POWER_ZONE_NAMES, POWER_ZONE_PCT

# Below this share of the planned TSS a ride counts as short, the same rule the calendar uses.
from components.calendar import SHORT_RATIO

ON_TARGET = (0.9, 1.1)          # within 10% of the plan reads as on target


# ── Pure numbers ──────────────────────────────────────────────────────────────

def _leaf_steps(steps: list):
    """(step, times it is ridden) for every simple step, repeats expanded by count."""
    for s in steps or []:
        if s.get("kind") == "repeat":
            count = int(s.get("repeat_count") or 1)
            for inner in s.get("repeat_steps") or []:
                yield inner, count
        else:
            yield s, 1


def _zone_index(pct: float) -> int:
    """Power zone (0 based) for a share of FTP in percent, using metrics.zones bounds."""
    for z in range(len(POWER_ZONE_PCT) - 2, -1, -1):
        if pct >= POWER_ZONE_PCT[z]:
            return z
    return 0


def planned_numbers(workout: dict, steps: list | None, ftp: float | None) -> dict:
    """What the plan asked for. Anything the plan does not say is None.

    With steps, each step counts at the middle of its power range. Steps with no power
    target add time but no power. Intensity is normalized power over FTP, worked out the
    usual way (fourth power average) from the step targets."""
    out = {"secs": None, "tss": _num(workout.get("tss_planned")), "if": None, "np": None,
           "avg_w": None, "zones": None}
    if not steps:
        return out
    total = powered = sum4 = sum1 = 0.0
    zones = [0.0] * (len(POWER_ZONE_PCT) - 1)
    for s, count in _leaf_steps(steps):
        secs = (_num(s.get("minutes")) or 0.0) * 60 * count
        if secs <= 0:
            continue
        total += secs
        lo, hi = _num(s.get("low_pct")), _num(s.get("high_pct"))
        if lo is None or hi is None:
            continue
        mid = (lo + hi) / 2
        powered += secs
        sum4 += secs * (mid / 100) ** 4
        sum1 += secs * mid / 100
        zones[_zone_index(mid)] += secs
    out["secs"] = total or None
    if powered:
        if_ = (sum4 / powered) ** 0.25
        out["if"] = if_
        out["zones"] = zones
        if ftp:
            out["np"] = if_ * ftp
            out["avg_w"] = sum1 / powered * ftp
    return out


def ridden_numbers(ride: dict | None, streams: dict | None = None, ftp: float | None = None) -> dict:
    """The same numbers from the ride. Zones come from second by second power when given."""
    if not ride:
        return {"secs": None, "tss": None, "if": None, "np": None, "avg_w": None, "zones": None}
    zones = None
    power = (streams or {}).get("power") if streams else None
    if power and ftp:
        from metrics.streams import power_zone_seconds
        zones = power_zone_seconds(power, ftp)
        if not any(zones):
            zones = None
    np_w = _num(ride.get("normalized_power"))
    if_ = _num(ride.get("if_value")) or (np_w / ftp if np_w and ftp else None)
    return {
        "secs": _num(ride.get("duration_seconds")) or _num(ride.get("elapsed_seconds")),
        "tss": _num(ride.get("tss")), "if": if_, "np": np_w,
        "avg_w": _num(ride.get("avg_power_watts")), "zones": zones,
    }


def _hmm(secs) -> str:
    if secs is None:
        return ""
    minutes = int(round(secs / 60))
    return f"{minutes // 60}:{minutes % 60:02d}"


def _pct(actual, planned) -> str:
    return f" ({actual / planned * 100:.0f}%)" if actual is not None and planned else ""


ROWS = [  # key, label, how to show a value, how to show the difference
    ("secs", "Time (h:mm)", _hmm,
     lambda a, p: ("+" if a >= p else "-") + _hmm(abs(a - p)) + _pct(a, p)),
    ("tss", "TSS", lambda v: f"{v:.0f}", lambda a, p: f"{a - p:+.0f}" + _pct(a, p)),
    ("if", "Intensity (IF)", lambda v: f"{v:.2f}", lambda a, p: f"{a - p:+.2f}"),
    ("np", "Normalized power", lambda v: f"{v:.0f} W", lambda a, p: f"{a - p:+.0f} W"),
    ("avg_w", "Average power", lambda v: f"{v:.0f} W", lambda a, p: f"{a - p:+.0f} W"),
]


def comparison_rows(planned: dict, ridden: dict) -> list[dict]:
    """One row per number that the plan or the ride has. Blank where one side has none."""
    rows = []
    for key, label, show, diff in ROWS:
        p, a = planned.get(key), ridden.get(key)
        if p is None and a is None:
            continue
        rows.append({"What": label, "Planned": show(p) if p is not None else "",
                     "Ridden": show(a) if a is not None else "",
                     "Difference": diff(a, p) if p is not None and a is not None else ""})
    return rows


def zone_rows(planned: dict, ridden: dict) -> list[dict]:
    """Minutes in each power zone, planned and ridden, for zones either side used."""
    pz, rz = planned.get("zones"), ridden.get("zones")
    if not pz and not rz:
        return []
    n = len(POWER_ZONE_NAMES)
    pz = list(pz or [0.0] * n)[:n]
    rz = list(rz or [0.0] * n)[:n]
    return [{"zone": f"Z{i + 1}", "name": POWER_ZONE_NAMES[i],
             "planned_min": round(pz[i] / 60, 1) if planned.get("zones") else None,
             "ridden_min": round(rz[i] / 60, 1) if ridden.get("zones") else None}
            for i in range(n) if pz[i] >= 30 or rz[i] >= 30]      # half a minute or more


def tss_verdict(planned_tss, ridden_tss) -> str | None:
    """'on', 'under', 'short' or 'over' for the ridden share of the planned TSS."""
    if not planned_tss or ridden_tss is None:
        return None
    share = ridden_tss / planned_tss
    if share < SHORT_RATIO:
        return "short"
    if share < ON_TARGET[0]:
        return "under"
    if share > ON_TARGET[1]:
        return "over"
    return "on"


VERDICT_TEXT = {
    "on": "Right on plan.",
    "under": "A little under the plan.",
    "short": "Well short of the plan.",
    "over": "More than the plan asked for.",
}


def summary_line(planned: dict, ridden: dict, has_ride: bool) -> str:
    """One plain sentence on how the ride compared with the plan."""
    if not has_ride:
        return "Marked done. No ride was recorded on this day, so there is nothing to compare."
    bits = []
    if planned.get("tss") and ridden.get("tss") is not None:
        bits.append(f"{ridden['tss']:.0f} TSS against {planned['tss']:.0f} planned"
                    f"{_pct(ridden['tss'], planned['tss'])}")
    if planned.get("secs") and ridden.get("secs"):
        bits.append(f"{_hmm(ridden['secs'])} riding against {_hmm(planned['secs'])} planned")
    if not bits:
        return "The ride is recorded, but the plan has no numbers to compare it with."
    verdict = VERDICT_TEXT.get(tss_verdict(planned.get("tss"), ridden.get("tss")) or "", "")
    return ("You rode " + " and ".join(bits) + ". " + verdict).strip()


# ── Streamlit ─────────────────────────────────────────────────────────────────

def _zone_chart(rows: list[dict], key: str) -> None:
    import plotly.graph_objects as go
    from components import charts, theme

    fig = go.Figure()
    x = [r["zone"] for r in rows]
    names = [r["name"] for r in rows]
    if any(r["planned_min"] is not None for r in rows):
        fig.add_bar(name="Planned", x=x, y=[r["planned_min"] for r in rows], customdata=names,
                    marker=dict(color=theme.rgba(theme.ACCENT, 0.25), line=dict(color=theme.ACCENT, width=1.5)),
                    hovertemplate="%{customdata}<br>Planned %{y:.0f} min<extra></extra>")
    if any(r["ridden_min"] is not None for r in rows):
        fig.add_bar(name="Ridden", x=x, y=[r["ridden_min"] for r in rows], customdata=names,
                    marker=dict(color=theme.GOOD, line=dict(width=0)),
                    hovertemplate="%{customdata}<br>Ridden %{y:.0f} min<extra></extra>")
    charts.apply_theme(fig, height=220)
    fig.update_layout(barmode="group", bargap=0.25)
    fig.update_yaxes(title_text="Minutes")
    charts.show(fig, key=key, zoom=None)


def render(workout: dict, ride: dict | None, *, streams: dict | None = None, steps: list | None = None,
           ftp: float | None = None, key: str = "cmp") -> None:
    """The plan next to the ride: summary, the numbers side by side, time in zones, and what
    the workout was for. `steps` and `streams` are looked up when not given (saved ones only,
    nothing is fetched)."""
    import pandas as pd
    import streamlit as st
    from db import queries as q

    if steps is None:
        from garmin_workouts import saved_steps
        steps = saved_steps(workout)
    if steps is None:
        import workout_recipes          # a standard workout's recipe is known without building it
        if workout_recipes.uses_recipe(workout):
            try:
                steps = workout_recipes.steps_for(workout)
            except workout_recipes.RecipeError:
                steps = None
    if ftp is None:
        ftp = q.ftp_on(workout["date"])
    if streams is None and ride and ride.get("id"):
        streams = q.get_streams(ride["id"])

    planned = planned_numbers(workout, steps, ftp)
    ridden = ridden_numbers(ride, streams, ftp)
    verdict = tss_verdict(planned.get("tss"), ridden.get("tss")) if ride else None
    line = summary_line(planned, ridden, bool(ride))
    if verdict in ("on", "over") or (ride and verdict is None):
        st.success(line, icon=":material/check_circle:")
    elif verdict in ("under", "short"):
        st.warning(line, icon=":material/check_circle:")
    else:
        st.info(line, icon=":material/check_circle:")

    rows = comparison_rows(planned, ridden) if ride else []
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if ride and not steps:
        st.caption("The plan has no saved steps, so only its TSS can be compared. Steps are saved when "
                   "the workout is sent to Garmin or exported.")

    zr = zone_rows(planned, ridden) if ride else []
    if zr:
        st.markdown("**Time in power zones**")
        _zone_chart(zr, key=f"{key}_zones")
        if planned.get("zones") is None:
            st.caption("The plan has no power targets to compare with.")
        elif ridden.get("zones") is None:
            st.caption("This ride's second by second power is not saved yet. Open the full ride "
                       "analysis once to load it.")

    with st.container(border=True):
        st.markdown("**The plan**")
        if workout.get("description"):
            st.write(workout["description"])
        if steps:
            from garmin_workouts import _walk_steps
            lines = []
            last = None
            for s, group in _walk_steps(steps):
                if group is not None and group is not last:
                    lines.append(f"- {group['repeat_count']} times")
                last = group
                target = (f"{s['low_pct']:.0f} to {s['high_pct']:.0f}% of FTP"
                          if s.get("low_pct") is not None else "no target")
                lines.append(("    " if group is not None else "") +
                             f"- {s['kind'].title()}, {s['minutes']:g} min, {target}")
            st.markdown("\n".join(lines))
        if workout.get("purpose"):
            st.markdown(f"**Why.** {workout['purpose']}")
        if workout.get("feel"):
            st.markdown(f"**How it should feel.** {workout['feel']}")
        if not any(workout.get(k) for k in ("description", "purpose", "feel")) and not steps:
            st.caption("No description for this workout.")
