"""
Shared training-block generation math.

Used by both the Periodization Wizard (the no-conversation fallback on the
Plan page) and the AI coach's generate_training_block tool, so the two paths
produce consistent plans instead of two copies of the same formula drifting
apart. Nothing here touches the database — callers decide whether to write
the result straight to the planner (Wizard) or stage it as a proposal the
athlete confirms (coach chat).
"""

from __future__ import annotations

from datetime import date, timedelta

from metrics import explain

DAY_TEMPLATES = {
    "Endurance": [
        ("Mon", "Recovery",  0.45), ("Tue", "Endurance", 0.85),
        ("Wed", "Tempo",     1.10), ("Thu", "Endurance", 0.80),
        ("Fri", None,        0.0),  ("Sat", "Long Ride", 1.75),
        ("Sun", "Recovery",  0.50),
    ],
    "Threshold": [
        ("Mon", "Recovery",  0.35), ("Tue", "Threshold", 1.25),
        ("Wed", "Endurance", 0.90), ("Thu", "VO2 Max",   1.20),
        ("Fri", None,        0.0),  ("Sat", "Long Ride", 2.00),
        ("Sun", "Endurance", 0.85),
    ],
    "Peak": [
        ("Mon", None,              0.0),  ("Tue", "Threshold",      1.10),
        ("Wed", "Recovery",        0.40), ("Thu", "Sprint/Anaerobic", 0.95),
        ("Fri", None,              0.0),  ("Sat", "Race",            1.40),
        ("Sun", "Recovery",        0.40),
    ],
}

PHASE_LABELS = {
    "Endurance": "Base / Endurance",
    "Threshold": "Build / Threshold",
    "Peak": "Peak / Sharpening",
}
TAPER_LABEL = "Taper"
PHASE_NOTES = {**explain.PHASE_NOTES, TAPER_LABEL: explain.TAPER_NOTE}


def _fit_to_days(template: list, days_per_week: int | None) -> list:
    """The week's template cut down to the riding days the athlete has. The biggest
    sessions are kept, the smallest dropped first, and the days stay in order."""
    if not days_per_week:
        return template
    active = [(i, wt) for i, (_, t, wt) in enumerate(template) if t and wt > 0]
    if days_per_week >= len(active):
        return template
    keep = {i for i, _ in sorted(active, key=lambda x: -x[1])[:max(int(days_per_week), 1)]}
    return [(d, t if i in keep else None, wt if i in keep else 0.0)
            for i, (d, t, wt) in enumerate(template)]


WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def parse_days(raw) -> list[str]:
    """Weekday names from the available_days setting ("Mon,Wed,Sat"), in week order.
    Unknown names are ignored, so an empty or broken value means no limit."""
    if isinstance(raw, str):
        raw = raw.split(",")
    picked = {str(d).strip()[:3].title() for d in (raw or [])}
    return [d for d in WEEKDAYS if d in picked]


def _place_on_days(template: list, days: list[str]) -> list:
    """The week's template moved onto the weekdays the athlete can ride. The biggest sessions
    are kept, the biggest of all (the long ride) goes on a weekend day when one is free, and
    the rest keep their order through the week. Returns seven entries, Monday first."""
    active = [(i, wt) for i, (_, t, wt) in enumerate(template) if t and wt > 0]
    keep = sorted(active, key=lambda x: -x[1])[:len(days)]
    if not keep:
        return [(d, None, 0.0) for d in WEEKDAYS]
    slots = list(days)
    placed = {}
    big = keep[0][0]
    weekend = [d for d in ("Sat", "Sun") if d in slots]
    placed[weekend[0] if weekend else slots[-1]] = big
    slots.remove(weekend[0] if weekend else slots[-1])
    for (i, _), d in zip(sorted(k for k in keep if k[0] != big), slots):
        placed[d] = i
    out = []
    for d in WEEKDAYS:
        i = placed.get(d)
        out.append((d, template[i][1], template[i][2]) if i is not None else (d, None, 0.0))
    return out


def target_ctl_range(current_ctl: float) -> tuple[int, int, int]:
    """Slider bounds and a default for the target peak CTL. Someone with little or no ride
    history still gets a useful range rather than one capped near zero."""
    cur = max(int(current_ctl or 0), 0)
    lo = max(cur, 20)
    hi = max(min(max(cur + 40, 60), 150), lo + 1)
    default = min(max(int(cur * 1.2), 30, lo), hi)
    return lo, hi, default


def generate_block(current_ctl: float, target_ctl: float, race_date: date,
                    phase_key: str, start_date: date | None = None,
                    days_per_week: int | None = None,
                    available_days: list[str] | str | None = None) -> list[dict]:
    """
    Generate a periodized block of ride workouts from start_date (default
    today) to race_date, ramping weekly TSS from current_ctl toward
    target_ctl, with a 1-2 week taper worked into the end. Returns plain
    workout dicts — date, name, workout_type, description, tss_planned, plus
    phase/week_number for grouping a multi-week proposal in the UI. Nothing
    is written to the database. `days_per_week` limits how many days a week get a ride.
    `available_days` (weekday names) puts the rides on those weekdays instead, and wins
    over `days_per_week` when both are given.
    """
    today = start_date or date.today()
    weeks_out = max(1, (race_date - today).days // 7)
    taper_weeks = 2 if weeks_out >= 6 else 1
    build_weeks = max(1, weeks_out - taper_weeks)

    current_weekly_tss = current_ctl * 7
    target_weekly_tss = target_ctl * 7

    if phase_key not in DAY_TEMPLATES:
        phase_key = "Endurance"
    phase_label = PHASE_LABELS[phase_key]
    days = parse_days(available_days)

    def week_template(key: str) -> list:
        if days:
            return _place_on_days(DAY_TEMPLATES[key], days)
        return _fit_to_days(DAY_TEMPLATES[key], days_per_week)

    workouts: list[dict] = []
    for wk in range(weeks_out):
        is_taper = wk >= build_weeks
        recovery = (not is_taper) and ((wk + 1) % 4 == 0)

        if is_taper:
            taper_phase = wk - build_weeks  # 0 or 1
            multiplier = 0.6 if taper_phase == 0 else 0.4
            week_tss = target_weekly_tss * multiplier
            tmpl = week_template("Peak")
        elif recovery:
            progress = wk / max(build_weeks - 1, 1)
            week_tss = (current_weekly_tss + progress *
                        (target_weekly_tss - current_weekly_tss)) * 0.65
            tmpl = week_template(phase_key)
        else:
            progress = wk / max(build_weeks - 1, 1)
            week_tss = (current_weekly_tss +
                        progress * (target_weekly_tss - current_weekly_tss))
            tmpl = week_template(phase_key)

        active_days = [(d, t, wt) for d, t, wt in tmpl if t and wt > 0]
        total_weight = sum(wt for _, _, wt in active_days)

        week_start = today + timedelta(weeks=wk)
        for day_offset in range(7):
            w_date = week_start + timedelta(days=day_offset)
            # With chosen weekdays each date takes that weekday's session. Without them the
            # template simply runs from the start date, as it always has.
            _, w_type, weight_frac = tmpl[w_date.weekday()] if days else tmpl[day_offset]
            if not w_type or weight_frac == 0:
                continue
            day_tss = round(week_tss * (weight_frac / total_weight))
            if day_tss < 10:
                continue
            if w_date >= race_date:
                break
            label = "(Taper) " if is_taper else ("(Recovery) " if recovery else "")
            week_phase = TAPER_LABEL if is_taper else phase_label
            purpose = explain.PURPOSE.get(w_type, explain.PURPOSE["Other"])
            if recovery:
                purpose = ("This is a lighter week on purpose. Your body gets stronger while it recovers, "
                           "so keep it easy. " + purpose)
            workouts.append({
                "date": w_date.isoformat(),
                "name": f"{label}{w_type}",
                "workout_type": w_type,
                "description": f"Auto-generated · {week_phase} · week {wk + 1}",
                "tss_planned": float(day_tss),
                "phase": week_phase,
                "week_number": wk + 1,
                "purpose": purpose,
                "feel": explain.feel_for(w_type),
                "phase_note": PHASE_NOTES.get(week_phase),
            })

    return workouts
