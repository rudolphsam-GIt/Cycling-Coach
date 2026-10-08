"""
Month calendar for the Plan page.

Pure part: build_month_data turns workouts, activities, strength sessions and
races into one DayData per date of the displayed grid (Monday first, including
the leading and trailing days of the neighbouring months). The status of each
day is derived from those inputs and never written to the database. Matching is
by date only, because planned workouts are not linked to activities.

build_payload turns that data into the JSON the interactive grid draws.

Streamlit part: render_month_calendar draws the navigation, the month totals,
the interactive grid (components/calendar_dnd.py: hover for details, drag a
workout to another day, click a workout to open it) and a fallback day picker.
It keeps the month in st.session_state["cal_ym"] and the selected day in
st.session_state["cal_sel"], and returns the selected ISO date or None.
apply_move and undo_last_move change the plan from a drop or the edit dialog.
render_day_readonly draws the read only parts of one day.
"""
from __future__ import annotations

import calendar as pycal
import html
import json
import re
import textwrap
from dataclasses import dataclass, field
from datetime import date, timedelta

from components import theme
from components.theme import rgba as _rgba
from db.queries import is_ride
from metrics.units import fmt_climb, fmt_distance, num as _num

# A ride that reaches less than this share of its planned TSS counts as short.
SHORT_RATIO = 0.70
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class DayData:
    date: str                       # ISO date
    in_month: bool = True
    planned: list = field(default_factory=list)   # workout dicts
    rides: list = field(default_factory=list)     # activity dicts where is_ride
    other: list = field(default_factory=list)     # non ride activity dicts
    strength: list = field(default_factory=list)  # {name, planned, duration_minutes, exercises}
    races: list = field(default_factory=list)     # race dicts
    planned_tss: float = 0.0
    actual_tss: float = 0.0
    status: str = "rest"


# ── Small helpers ─────────────────────────────────────────────────────────────

def _day_key(value) -> str:
    """ISO date part of a stored date or datetime string, '' when missing."""
    return str(value)[:10] if value else ""


def _strength_row(row: dict) -> dict:
    notes = str(row.get("notes") or "")
    name = notes.split(" | ")[0].strip()
    if not name or name.startswith("Planned by AI Coach"):
        name = "Strength session"
    exercises = []
    try:
        data = json.loads(row.get("exercises_json") or "[]")
        for ex in data if isinstance(data, list) else []:
            nm = ex.get("name") if isinstance(ex, dict) else ex
            if nm:
                exercises.append(str(nm))
    except (TypeError, ValueError):
        pass
    return {
        "id": row.get("id"),
        "name": name,
        "planned": (not row.get("completed")) and "Planned by AI Coach" in notes,
        "duration_minutes": row.get("duration_minutes"),
        "exercises": exercises,
        "purpose": row.get("purpose"),
    }


def derive_status(day: date, today: date, planned: list, rides: list,
                  planned_tss: float, actual_tss: float) -> str:
    """Status of one day. Strength and races never change it."""
    if planned:
        if day > today:
            return "planned"
        all_completed = all(w.get("completed") for w in planned)
        if all_completed or rides:
            if all_completed:
                return "done"
            # Only judge "short" when the rides carry TSS to compare with.
            has_tss = any(_num(r.get("tss")) is not None for r in rides)
            if has_tss and planned_tss > 0 and actual_tss < SHORT_RATIO * planned_tss:
                return "short"
            return "done"
        return "missed" if day < today else "planned"
    return "extra" if rides else "rest"


def grid_dates(year: int, month: int) -> list[date]:
    """Every date shown in the month grid, Monday first."""
    return [d for week in pycal.Calendar(0).monthdatescalendar(year, month) for d in week]


def build_month_data(year: int, month: int, workouts: list, activities: list,
                     strength: list, races: list, today: date) -> dict:
    """One DayData per date in the displayed grid, keyed by ISO date. Pure."""
    days = {d.isoformat(): DayData(date=d.isoformat(), in_month=(d.month == month))
            for d in grid_dates(year, month)}

    for w in workouts or []:
        dd = days.get(_day_key(w.get("date")))
        if dd:
            dd.planned.append(w)
    for a in activities or []:
        dd = days.get(_day_key(a.get("date")))
        if dd:
            (dd.rides if is_ride(a) else dd.other).append(a)
    for s in strength or []:
        dd = days.get(_day_key(s.get("date")))
        if dd:
            dd.strength.append(_strength_row(s))
    for r in races or []:
        dd = days.get(_day_key(r.get("date")))
        if dd:
            dd.races.append(r)

    for iso, dd in days.items():
        dd.planned_tss = sum(_num(w.get("tss_planned")) or 0.0 for w in dd.planned)
        dd.actual_tss = sum(_num(r.get("tss")) or 0.0 for r in dd.rides)
        dd.status = derive_status(date.fromisoformat(iso), today, dd.planned,
                                  dd.rides, dd.planned_tss, dd.actual_tss)
    return days


def month_totals(days: dict, today: date) -> dict:
    """Planned and ridden TSS over the days of the month itself."""
    plan = plan_to_date = actual = 0.0
    rides = 0
    for iso, dd in days.items():
        if not dd.in_month:
            continue
        plan += dd.planned_tss
        actual += dd.actual_tss
        rides += len(dd.rides)
        if date.fromisoformat(iso) <= today:
            plan_to_date += dd.planned_tss
    return {"plan": plan, "plan_to_date": plan_to_date, "actual": actual, "rides": rides}


# ── Text formatting ───────────────────────────────────────────────────────────

def _esc(s) -> str:
    return html.escape(str(s), quote=False)


def _short(s, n: int) -> str:
    """Collapse whitespace and truncate to n characters (raw text, escape after)."""
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: max(n - 1, 1)].rstrip() + "…"


def _hmm(seconds) -> str:
    s = _num(seconds)
    if s is None or s <= 0:
        return ""
    minutes = int(round(s / 60))
    return f"{minutes // 60}:{minutes % 60:02d}"


def _km(meters, unit: str = "km") -> str:
    """Distance in the rider's unit, for example 34.2 km or 21.3 mi."""
    return fmt_distance(_num(meters), unit)


def _ride_facts(r: dict, unit: str = "km") -> list[str]:
    """Ride numbers as short labels, skipping anything missing."""
    facts = []
    dur = _hmm(r.get("duration_seconds") or r.get("elapsed_seconds"))
    if dur:
        facts.append(dur)
    if _km(r.get("distance_meters"), unit):
        facts.append(_km(r.get("distance_meters"), unit))
    if _num(r.get("avg_power_watts")):
        facts.append(f"{round(_num(r['avg_power_watts']))} W avg")
    if _num(r.get("normalized_power")):
        facts.append(f"NP {round(_num(r['normalized_power']))}")
    if _num(r.get("avg_hr")):
        facts.append(f"{round(_num(r['avg_hr']))} bpm")
    if _num(r.get("tss")) is not None:
        facts.append(f"{round(_num(r['tss']))} TSS")
    if _num(r.get("if_value")):
        facts.append(f"IF {_num(r['if_value']):.2f}")
    return facts


def _wrap(text: str, width: int = 44) -> str:
    """Wrap raw text, then escape each line and join with <br>."""
    lines = textwrap.wrap(text, width=width, break_long_words=True) or [""]
    return "<br>".join(_esc(x) for x in lines)


def _fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%a} {d.day} {d:%b %Y}"


def day_tooltip(day: DayData, unit: str = "km") -> str:
    """Hover text for one day. Every user string is truncated, then escaped."""
    parts = [f"<b>{_esc(_fmt_date(day.date))}</b> ({_esc(theme.STATUS_LABELS.get(day.status, day.status))})"]

    if day.planned:
        parts.append("<b>Planned</b>")
        for w in day.planned[:3]:
            head = _short(w.get("name") or "Workout", 40)
            if w.get("workout_type"):
                head += f" ({_short(w['workout_type'], 20)})"
            tss = _num(w.get("tss_planned"))
            if tss:
                head += f", {round(tss)} TSS"
            if w.get("completed"):
                head += ", marked done"
            parts.append(_esc(head))
            desc = _short(w.get("description"), 120)
            if desc:
                parts.append("<i>" + _wrap(desc) + "</i>")
            if w.get("purpose"):
                parts.append("<b>Why.</b> " + _wrap(_short(w["purpose"], 170)))
            if w.get("feel"):
                parts.append("<b>Feel.</b> " + _wrap(_short(w["feel"], 110)))
        if len(day.planned) > 3:
            parts.append(f"+{len(day.planned) - 3} more")

    if day.rides:
        parts.append("<b>Done</b>")
        for r in day.rides[:3]:
            facts = ", ".join(_ride_facts(r, unit))
            parts.append(_esc(_short(r.get("name") or "Ride", 40) + (f", {facts}" if facts else "")))
        if len(day.rides) > 3:
            parts.append(f"+{len(day.rides) - 3} more")
    if day.other:
        for o in day.other[:2]:
            kind = _short(o.get("sport_type") or "Activity", 16)
            dur = _hmm(o.get("duration_seconds"))
            parts.append(_esc(f"Also logged, {_short(o.get('name') or kind, 30)}"
                              + (f", {dur}" if dur else "")))

    for s in day.strength:
        label = "Strength planned" if s["planned"] else "Strength done"
        parts.append(f"<b>{label}</b>")
        parts.append(_esc(_short(s["name"], 40)))
        if s["exercises"]:
            more = len(s["exercises"]) - 4
            names = ", ".join(_short(x, 24) for x in s["exercises"][:4])
            parts.append(_esc(names + (f" and {more} more" if more > 0 else "")))
        if s.get("purpose"):
            parts.append("<b>Why.</b> " + _wrap(_short(s["purpose"], 170)))

    for r in day.races:
        parts.append("<b>Race</b>")
        bits = [_short(r.get("name") or "Race", 40)]
        if r.get("category"):
            bits.append(_short(r["category"], 20))
        if _num(r.get("distance_km")):
            bits.append(fmt_distance(_num(r["distance_km"]) * 1000, unit))
        parts.append(_esc(", ".join(bits)))

    if day.planned_tss > 0 and day.actual_tss > 0:
        pct = round(100 * day.actual_tss / day.planned_tss)
        parts.append(f"<b>Planned {round(day.planned_tss)} TSS, "
                     f"Actual {round(day.actual_tss)} TSS ({pct}%)</b>")

    if len(parts) == 1:
        parts.append("Nothing planned or recorded")
    return "<br>".join(parts)


# ── Grid payload ──────────────────────────────────────────────────────────────

MAX_CHIPS = 3


def _chips(day: DayData, today: date) -> list[dict]:
    """The items drawn inside one cell. Unfinished planned rides and planned strength can be
    dragged, including skipped ones from days that have passed. `kind` is what the page acts on."""
    upcoming = date.fromisoformat(day.date) >= today
    status_color = theme.STATUS_COLORS.get(day.status, theme.ACCENT)
    chips = []
    for w in day.planned:
        done = bool(w.get("completed"))
        tss = _num(w.get("tss_planned"))
        chips.append({
            "kind": "ride", "id": w.get("id"), "label": _short(w.get("name") or "Workout", 22),
            "tss": round(tss) if tss else None, "done": done,
            "locked": done,
            "color": theme.GOOD if done else (theme.STATUS_COLORS["planned"] if upcoming else status_color),
        })
    for s in day.strength:
        chips.append({
            "kind": "strength", "id": s.get("id"), "label": _short(s["name"], 22), "tss": None,
            "done": not s["planned"], "locked": not s["planned"],
            "color": theme.STRENGTH,
        })
    for r in day.rides:
        tss = _num(r.get("tss"))
        chips.append({
            "kind": "done", "id": r.get("id"), "label": _short(r.get("name") or "Ride", 22),
            "tss": round(tss) if tss else None, "done": True, "locked": True, "color": theme.GOOD,
        })
    return chips


def build_payload(days: dict, selected: str | None, today: date, unit: str = "km") -> dict:
    """The data the interactive grid draws. Pure, JSON safe. Strings are plain text
    except `tip`, which day_tooltip has already escaped."""
    out = []
    for iso in sorted(days):
        day = days[iso]
        d = date.fromisoformat(iso)
        color = theme.STATUS_COLORS.get(day.status, theme.BORDER)
        alpha = 0.28 if day.status == "rest" else 0.24
        if not day.in_month:
            alpha *= 0.4
        chips = _chips(day, today)
        out.append({
            "date": iso, "num": d.day, "in_month": day.in_month,
            "tint": _rgba(color, alpha), "today": d == today, "past": d < today,
            "race": (day.races[0].get("name") or "Race") if day.races else None,
            "tip": day_tooltip(day, unit), "chips": chips[:MAX_CHIPS],
            "more": max(len(chips) - MAX_CHIPS, 0),
        })
    return {
        "today": today.isoformat(), "selected": selected, "days": out,
        "weekdays": WEEKDAYS,
        "colors": {"text1": theme.TEXT1, "text2": theme.TEXT2, "text3": theme.TEXT3,
                   "surface": theme.SURFACE, "raised": theme.RAISED, "border": theme.BORDER,
                   "accent": theme.ACCENT, "race": theme.RACE, "strength": theme.STRENGTH,
                   "good": theme.GOOD},
    }


# ── DB loading ────────────────────────────────────────────────────────────────

def load_month(year: int, month: int) -> dict:
    """Read the month's data with db.queries and build the grid."""
    from db import queries as q

    dates = grid_dates(year, month)
    first, last = dates[0], dates[-1]
    today = date.today()
    in_grid = lambda row: first.isoformat() <= _day_key(row.get("date")) <= last.isoformat()

    workouts = q.get_workouts(first.isoformat(), last.isoformat())
    activities = q.get_activities_between(first.isoformat(), last.isoformat())
    back = max((today - first).days + 1, 1)
    strength = [s for s in q.get_strength_sessions(days_back=back) if in_grid(s)]
    races = [r for r in q.get_races() if in_grid(r)]
    return build_month_data(year, month, workouts, activities, strength, races, today)


def get_day(day_iso: str, month_days: dict | None = None) -> DayData:
    """DayData for any date. Pass the grid already loaded this run to skip a
    second read; otherwise the month that contains the day is loaded."""
    d = date.fromisoformat(day_iso)
    if month_days and d.isoformat() in month_days:
        return month_days[d.isoformat()]
    return load_month(d.year, d.month)[d.isoformat()]


# ── Streamlit rendering ───────────────────────────────────────────────────────

def _valid_iso(v) -> str | None:
    try:
        return date.fromisoformat(str(v)[:10]).isoformat() if v else None
    except ValueError:
        return None


def _set_sel(d: date) -> None:
    import streamlit as st
    st.session_state["cal_sel"] = d.isoformat()
    st.session_state["cal_ym"] = (d.year, d.month)


def _cb_nav(delta: int) -> None:
    import streamlit as st
    y, m = st.session_state.get("cal_ym") or (date.today().year, date.today().month)
    idx = y * 12 + (m - 1) + delta
    st.session_state["cal_ym"] = (idx // 12, idx % 12 + 1)


def _cb_today() -> None:
    _set_sel(date.today())


def _cb_shift_day(delta: int) -> None:
    import streamlit as st
    base = _valid_iso(st.session_state.get("cal_sel"))
    base_d = date.fromisoformat(base) if base else date.today()
    try:
        _set_sel(base_d + timedelta(days=delta))
    except OverflowError:
        pass


def _cb_pick(widget_key: str) -> None:
    import streamlit as st
    picked = st.session_state.get(widget_key)
    if isinstance(picked, date):
        _set_sel(picked)


def _legend_html() -> str:
    chips = [(theme.STATUS_COLORS["planned"], "Planned"), (theme.STATUS_COLORS["done"], "Done"),
             (theme.STATUS_COLORS["short"], "Short of plan"), (theme.STATUS_COLORS["missed"], "Missed"),
             (theme.STATUS_COLORS["extra"], "Unplanned ride"), (theme.STRENGTH, "Strength"),
             (theme.RACE, "Race")]
    items = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;margin:2px 14px 2px 0;'
        f'font-size:0.85rem;color:{theme.TEXT2}">'
        f'<span style="width:10px;height:10px;border-radius:50%;background:{c};display:inline-block"></span>'
        f'{label}</span>' for c, label in chips)
    return f'<div style="display:flex;flex-wrap:wrap;margin:4px 0 8px 0">{items}</div>'


def _totals_text(totals: dict, label: str) -> str:
    plan, actual, rides = totals["plan"], totals["actual"], totals["rides"]
    if not plan and not actual:
        return f"Nothing planned or ridden in {label} yet."
    if not plan:
        return f"Ridden {round(actual)} TSS in {label}, nothing planned."
    to_date = totals["plan_to_date"]
    if to_date <= 0:
        return f"Planned {round(plan)} TSS in {label}, nothing ridden yet."
    pct = round(100 * actual / to_date)
    tail = f" Month plan {round(plan)} TSS." if plan > to_date else ""
    return (f"Planned {round(to_date)} TSS so far, actual {round(actual)} TSS ({pct}%) "
            f"in {label}.{tail}")


# ── Moves ─────────────────────────────────────────────────────────────────────

LAST_MOVE_KEY = "last_move"
OPEN_KEY = "cal_open"


def apply_move(kind: str, item_id, to_iso, today: date | None = None) -> str | None:
    """Move an unfinished planned ride or strength session to another day. An upcoming one can go
    to today or later. One whose day has passed without it being done (a skipped workout) can go
    to any day, so it can be ridden later or filed on the day it really happened. A done one stays.

    Returns an error message when the move isn't allowed, None otherwise (also
    None when the item is already on that day). A ride that was sent to Garmin
    has its Garmin copy removed (best effort), and shows as not sent afterwards.
    The move is remembered in st.session_state["last_move"] for the Undo bar."""
    import streamlit as st
    from db import queries as q
    from plan_changes import move_error

    today = today or date.today()
    to = _valid_iso(to_iso)
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        return "That item can't be moved."
    if not to:
        return "That isn't a valid date."
    if kind == "ride":
        row = q.get_workout(item_id)
        if not row:
            return "That workout no longer exists."
        if (why := move_error(row, to, today)):
            return why
        old = q.move_workout(item_id, to)
        if old is None:
            return None
        from garmin_workouts import remove_from_garmin
        remove_from_garmin(old)
        label, tss = old["name"], _num(old.get("tss_planned")) or 0.0
    elif kind == "strength":
        row = q.get_strength_session(item_id)
        if not row:
            return "That session no longer exists."
        if (why := move_error(row, to, today, "session")):
            return why
        old = q.move_strength_session(item_id, to)
        if old is None:
            return None
        label, tss = _strength_row(old)["name"], 0.0
    else:
        return "That item can't be moved."

    st.session_state[LAST_MOVE_KEY] = {
        "kind": kind, "id": item_id, "label": label, "from": old["date"], "to": to,
        "tss": tss, "garmin": bool(old.get("garmin_workout_id")),
    }
    st.session_state["cal_sel"] = to
    st.session_state["cal_ym"] = (date.fromisoformat(to).year, date.fromisoformat(to).month)
    st.toast(f"Moved {label} to {date.fromisoformat(to):%a %b} {date.fromisoformat(to).day}")
    return None


def undo_last_move() -> None:
    """Put the last moved item back on its original day."""
    import streamlit as st
    from db import queries as q

    last = st.session_state.pop(LAST_MOVE_KEY, None)
    if not last:
        return
    if last["kind"] == "ride":
        q.move_workout(last["id"], last["from"])
    else:
        q.move_strength_session(last["id"], last["from"])
    st.session_state["cal_sel"] = last["from"]
    st.toast(f"Moved {last['label']} back")


# ── Grid events ───────────────────────────────────────────────────────────────

def _event(key: str, name: str):
    """The latest value of one trigger from the grid component, or None."""
    import streamlit as st
    result = st.session_state.get(key)
    try:
        value = result[name]
    except (KeyError, TypeError):
        value = getattr(result, name, None)
    return value if isinstance(value, dict) else None


def _cb_grid(key: str) -> None:
    """Runs before the rerun when the grid reports a drop, a click on a workout
    or a click on a day."""
    import streamlit as st

    move = _event(key, "move")
    if move:
        err = apply_move(move.get("kind"), move.get("id"), move.get("to"))
        if err:
            st.toast(err, icon=":material/block:")
        return
    opened = _event(key, "open")
    if opened:
        iso = _valid_iso(opened.get("date"))
        if iso:
            st.session_state["cal_sel"] = iso
            st.session_state[OPEN_KEY] = {"kind": opened.get("kind"), "id": opened.get("id")}
        return
    picked = _event(key, "select")
    if picked and (iso := _valid_iso(picked.get("date"))):
        st.session_state["cal_sel"] = iso


MONTH_DAYS_KEY = "_cal_month_days"


def render_month_calendar(key: str = "cal"):
    """Month navigation, totals, the interactive grid, legend and fallback picker.
    Returns the selected ISO date or None."""
    import streamlit as st
    from components import calendar_dnd
    from components.units import distance_unit

    today = date.today()
    sel = _valid_iso(st.session_state.get("cal_sel"))
    st.session_state["cal_sel"] = sel

    ym = st.session_state.get("cal_ym")
    try:
        year, month = int(ym[0]), int(ym[1])
        if not 1 <= month <= 12:
            raise ValueError
    except (TypeError, ValueError, IndexError):
        base = date.fromisoformat(sel) if sel else today
        year, month = base.year, base.month
    st.session_state["cal_ym"] = (year, month)
    label = f"{pycal.month_name[month]} {year}"

    nav_prev, nav_next, nav_today, nav_label = st.columns([1.3, 1.1, 1, 4], vertical_alignment="center")
    nav_prev.button("Previous", key=f"{key}_prev", icon=":material/chevron_left:",
                    on_click=_cb_nav, args=(-1,), width="stretch")
    nav_next.button("Next", key=f"{key}_next", icon=":material/chevron_right:",
                    on_click=_cb_nav, args=(1,), width="stretch")
    nav_today.button("Today", key=f"{key}_today", on_click=_cb_today, width="stretch")
    nav_label.markdown(
        f'<div style="font-size:1.25rem;font-weight:600;color:{theme.TEXT1}">{label}</div>',
        unsafe_allow_html=True)

    days = load_month(year, month)
    st.session_state[MONTH_DAYS_KEY] = days     # reused by the day panel this run
    st.caption(_totals_text(month_totals(days, today), label))

    grid_key = f"{key}_grid_{year}_{month}"
    calendar_dnd.render_grid(build_payload(days, sel, today, distance_unit()), key=grid_key,
                             on_event=_cb_grid)
    st.markdown(_legend_html(), unsafe_allow_html=True)
    st.caption("Drag an upcoming workout to another day. Click a workout to open and edit it. "
               "The number on each workout is its planned TSS, the training stress it should add.")

    pick_key = f"{key}_pick"
    st.session_state[pick_key] = date.fromisoformat(sel) if sel else today
    b1, b2, b3, b4 = st.columns([1.4, 1.2, 1.1, 2.6], vertical_alignment="bottom")
    b1.button("Previous day", key=f"{key}_dprev", icon=":material/chevron_left:",
              on_click=_cb_shift_day, args=(-1,), width="stretch")
    b2.button("Next day", key=f"{key}_dnext", icon=":material/chevron_right:",
              on_click=_cb_shift_day, args=(1,), width="stretch")
    b3.button("Pick today", key=f"{key}_dtoday", on_click=_cb_today, width="stretch")
    b4.date_input("Jump to a day", key=pick_key, on_change=_cb_pick, args=(pick_key,))
    return sel


def _md(s) -> str:
    """Escape markdown, math and emoji shortcode characters in user text."""
    return re.sub(r"([\\`*_\[\]<>$~#|&:!])", r"\\\1", str(s))


def _zone_line(ride: dict) -> str:
    raw = ride.get("zone_time_json")
    if not raw:
        return ""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(data, dict):
            return ""
    except (TypeError, ValueError):
        return ""
    secs = []
    for i in range(1, 6):
        v = _num(data.get(f"z{i}_s"))
        secs.append(v if v is not None else _num(data.get(f"z{i}")))
    if not any(secs):
        return ""
    bits = [f"Z{i} {_hmm(s) or '0:00'}" for i, s in enumerate(secs, start=1) if s is not None]
    note = " (estimated)" if str(data.get("source") or "").lower() == "estimated" else ""
    return "Time in zones (h:mm) " + ", ".join(bits) + note


def render_day_readonly(day_iso: str, strength_actions=None, day: DayData | None = None) -> None:
    """Rides done, strength and races for one day. Planned workouts are drawn by the page.
    `strength_actions(session_info)`, if given, draws buttons inside each strength session."""
    import streamlit as st
    from components.units import distance_unit
    unit = distance_unit()

    try:
        day = day or get_day(day_iso)
    except (ValueError, KeyError):
        st.caption("Nothing recorded for this day.")
        return

    drew = False
    for r in day.rides:
        drew = True
        with st.container(border=True):
            st.markdown(f"**{_md(_short(r.get('name') or 'Ride', 80))}**")
            facts = _ride_facts(r, unit)
            if _num(r.get("elevation_gain_meters")):
                facts.append(f"{fmt_climb(_num(r['elevation_gain_meters']), unit)} climbing")
            st.caption("  |  ".join(facts) if facts else "No ride numbers recorded")
            zones = _zone_line(r)
            if zones:
                st.caption(zones)
    for o in day.other:
        drew = True
        dur = _hmm(o.get("duration_seconds"))
        st.caption(f"Also logged, {_md(_short(o.get('name') or o.get('sport_type') or 'activity', 60))}"
                   + (f", {dur}" if dur else ""))
    for s in day.strength:
        drew = True
        with st.container(border=True):
            status = "Planned" if s["planned"] else "Done"
            mins = _num(s.get("duration_minutes"))
            st.markdown(f"**{_md(_short(s['name'], 80))}**  \nStrength, {status.lower()}"
                        + (f", {round(mins)} min" if mins else ""))
            if s["exercises"]:
                st.caption(", ".join(_md(_short(x, 40)) for x in s["exercises"]))
            if strength_actions:
                strength_actions(s)
    for race in day.races:
        drew = True
        with st.container(border=True):
            bits = []
            if race.get("category"):
                bits.append(str(race["category"]))
            if _num(race.get("distance_km")):
                bits.append(fmt_distance(_num(race["distance_km"]) * 1000, unit))
            if _num(race.get("elevation_gain_meters")):
                bits.append(f"{fmt_climb(_num(race['elevation_gain_meters']), unit)} climbing")
            st.markdown(f"**Race, {_md(_short(race.get('name') or 'Race', 80))}**")
            if bits:
                st.caption(_md("  |  ".join(bits)))
    if not drew:
        st.caption("Nothing recorded for this day.")
