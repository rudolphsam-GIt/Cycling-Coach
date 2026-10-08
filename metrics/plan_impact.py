"""
What a change to the plan does to fitness, fatigue and form.

Everything here is pure (plain dicts in, plain dicts out) apart from
load_plan_state, which reads the database once. The projection uses the same
EWMA as metrics.training_load, so numbers match the Today page and
TrainingPeaks.

A "plan" is a {iso_date: tss} dict. Past days carry what was ridden, today and
later carry what is planned (today counts the plan only while nothing has been
ridden yet).
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from metrics.training_load import ATL_ALPHA, CTL_ALPHA

HARD_TSS = 90            # a day at or above this counts as hard
WEEK_JUMP = 0.20         # weekly TSS growth that is worth a warning
MIN_WEEK_FOR_JUMP = 100  # ignore the jump rule for very light weeks
MAX_HORIZON = 120
DEFAULT_HORIZON = 28


def _num(v) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else 0.0
    except (TypeError, ValueError):
        return 0.0


def plan_from_rows(workouts: list, actual_by_day: dict, today: date) -> dict:
    """Combine ridden TSS (past and today) with planned TSS (today and later).

    Today counts the plan only when no ride has been logged yet, so a ride that
    was done is never counted twice."""
    plan = {d: _num(t) for d, t in actual_by_day.items() if d <= today.isoformat()}
    for w in workouts:
        day = str(w.get("date") or "")[:10]
        if not day or day < today.isoformat():
            continue
        if day == today.isoformat() and _num(actual_by_day.get(day)) > 0:
            continue
        plan[day] = plan.get(day, 0.0) + _num(w.get("tss_planned"))
    return plan


def shift(plan: dict, tss: float, from_day: str, to_day: str) -> dict:
    """The plan with `tss` taken off one day and put on another (a copy)."""
    out = dict(plan)
    out[from_day] = max(out.get(from_day, 0.0) - tss, 0.0)
    out[to_day] = out.get(to_day, 0.0) + tss
    return out


def with_change(plan: dict, *, remove: tuple[str, float] | None = None,
                add: tuple[str, float] | None = None) -> dict:
    """The plan with one workout taken out and/or put in (a copy)."""
    out = dict(plan)
    if remove:
        day, tss = remove
        out[day] = max(out.get(day, 0.0) - tss, 0.0)
    if add:
        day, tss = add
        out[day] = out.get(day, 0.0) + tss
    return out


def project(plan: dict, start: date, end: date, ctl: float, atl: float) -> list[dict]:
    """Daily CTL, ATL and TSB from `start` to `end`.

    `ctl` and `atl` are the values at the end of the day before `start`.
    TSB for a day is the form going into it (yesterday's CTL minus ATL)."""
    rows = []
    day = start
    while day <= end:
        tss = _num(plan.get(day.isoformat()))
        prev_ctl, prev_atl = ctl, atl
        ctl = prev_ctl + (tss - prev_ctl) * CTL_ALPHA
        atl = prev_atl + (tss - prev_atl) * ATL_ALPHA
        rows.append({"date": day.isoformat(), "tss": tss, "ctl": round(ctl, 1),
                     "atl": round(atl, 1), "tsb": round(prev_ctl - prev_atl, 1)})
        day += timedelta(days=1)
    return rows


def focus_day(races: list, today: date) -> tuple[date, str | None]:
    """The day to judge the plan on: the next race inside the horizon, else four
    weeks out. Returns (day, race name or None)."""
    upcoming = sorted((str(r.get("date") or "")[:10], r.get("name")) for r in races
                      if str(r.get("date") or "")[:10] >= today.isoformat())
    for iso, name in upcoming:
        try:
            d = date.fromisoformat(iso)
        except ValueError:
            continue
        if (d - today).days <= MAX_HORIZON:
            return d, name or "Race"
    return today + timedelta(days=DEFAULT_HORIZON), None


def impact(before: dict, after: dict, *, today: date, ctl: float, atl: float,
           focus: date) -> dict:
    """Compare two plans on `focus`. `ctl` and `atl` are as of yesterday.

    Returns the focus day numbers for both plans, the change, and both series
    from today to the focus day (at least a week, so the chart is never a dot)."""
    end = max(focus, today + timedelta(days=7))
    s_before = project(before, today, end, ctl, atl)
    s_after = project(after, today, end, ctl, atl)
    iso = focus.isoformat()
    at = lambda series: next((r for r in series if r["date"] == iso), series[-1])
    b, a = at(s_before), at(s_after)
    return {
        "focus": iso,
        "before": {k: b[k] for k in ("ctl", "atl", "tsb")},
        "after": {k: a[k] for k in ("ctl", "atl", "tsb")},
        "delta": {k: round(a[k] - b[k], 1) for k in ("ctl", "atl", "tsb")},
        "series_before": s_before,
        "series_after": s_after,
    }


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _fmt(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%a} {d.day} {d:%b}"


def warnings(plan: dict, races: list, today: date, horizon_end: date) -> list[str]:
    """Plain rule based flags, each with the numbers behind it. Nothing is
    reported without a number."""
    out: list[str] = []
    start, end = today, horizon_end
    race_days = {}
    for r in races:
        iso = str(r.get("date") or "")[:10]
        if iso:
            race_days[iso] = r.get("name") or "Race"

    day = start
    while day < end:
        a, b = day.isoformat(), (day + timedelta(days=1)).isoformat()
        ta, tb = _num(plan.get(a)), _num(plan.get(b))
        if ta >= HARD_TSS and tb >= HARD_TSS:
            out.append(f"Hard days back to back, {_fmt(a)} ({ta:.0f} TSS) and {_fmt(b)} ({tb:.0f} TSS).")
        if ta >= HARD_TSS and b in race_days:
            out.append(f"{_fmt(a)} is a hard day ({ta:.0f} TSS) right before {race_days[b]}.")
        day += timedelta(days=1)

    week = _monday(start)
    prev_total = None
    while week <= end:
        days = [(week + timedelta(days=i)).isoformat() for i in range(7)]
        total = sum(_num(plan.get(d)) for d in days)
        label = _fmt(week.isoformat())
        if prev_total is not None and prev_total >= MIN_WEEK_FOR_JUMP and \
                total > prev_total * (1 + WEEK_JUMP):
            out.append(f"Week of {label} is {total:.0f} TSS, up "
                       f"{(total / prev_total - 1) * 100:.0f}% on the week before ({prev_total:.0f}).")
        if all(_num(plan.get(d)) > 0 for d in days) and week + timedelta(days=6) >= start:
            out.append(f"No rest day in the week of {label}.")
        prev_total = total
        week += timedelta(days=7)
    return out


def load_plan_state(today: date | None = None) -> dict:
    """Read what the projection needs: the plan so far, CTL and ATL as of
    yesterday, and the races. One call per page run."""
    from db.queries import get_daily_tss, get_races, get_workouts
    from metrics.training_load import compute_pmc

    today = today or date.today()
    yesterday = today - timedelta(days=1)
    pmc = compute_pmc(yesterday, yesterday)
    ctl = float(pmc.iloc[0]["ctl"]) if not pmc.empty else 0.0
    atl = float(pmc.iloc[0]["atl"]) if not pmc.empty else 0.0

    races = get_races()
    focus, race_name = focus_day(races, today)
    last = max(focus, today + timedelta(days=7)) + timedelta(days=14)
    first = _monday(today)
    workouts = get_workouts(first.isoformat(), last.isoformat())
    actual = get_daily_tss(first.isoformat(), today.isoformat())
    return {
        "today": today, "ctl": ctl, "atl": atl, "races": races, "focus": focus,
        "actual": actual,
        "race_name": race_name, "workouts": workouts,
        "plan": plan_from_rows(workouts, actual, today),
        "horizon_end": focus,
    }
