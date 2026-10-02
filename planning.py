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


def generate_block(current_ctl: float, target_ctl: float, race_date: date,
                    phase_key: str, start_date: date | None = None) -> list[dict]:
    """
    Generate a periodized block of ride workouts from start_date (default
    today) to race_date, ramping weekly TSS from current_ctl toward
    target_ctl, with a 1-2 week taper worked into the end. Returns plain
    workout dicts — date, name, workout_type, description, tss_planned, plus
    phase/week_number for grouping a multi-week proposal in the UI. Nothing
    is written to the database.
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

    workouts: list[dict] = []
    for wk in range(weeks_out):
        is_taper = wk >= build_weeks
        recovery = (not is_taper) and ((wk + 1) % 4 == 0)

        if is_taper:
            taper_phase = wk - build_weeks  # 0 or 1
            multiplier = 0.6 if taper_phase == 0 else 0.4
            week_tss = target_weekly_tss * multiplier
            tmpl = DAY_TEMPLATES["Peak"]
        elif recovery:
            progress = wk / max(build_weeks - 1, 1)
            week_tss = (current_weekly_tss + progress *
                        (target_weekly_tss - current_weekly_tss)) * 0.65
            tmpl = DAY_TEMPLATES[phase_key]
        else:
            progress = wk / max(build_weeks - 1, 1)
            week_tss = (current_weekly_tss +
                        progress * (target_weekly_tss - current_weekly_tss))
            tmpl = DAY_TEMPLATES[phase_key]

        active_days = [(d, t, wt) for d, t, wt in tmpl if t and wt > 0]
        total_weight = sum(wt for _, _, wt in active_days)

        for day_offset, (day_name, w_type, weight_frac) in enumerate(tmpl):
            if not w_type or weight_frac == 0:
                continue
            day_tss = round(week_tss * (weight_frac / total_weight))
            if day_tss < 10:
                continue
            w_date = today + timedelta(weeks=wk, days=day_offset)
            if w_date >= race_date:
                break
            label = "(Taper) " if is_taper else ("(Recovery) " if recovery else "")
            workouts.append({
                "date": w_date.isoformat(),
                "name": f"{label}{w_type}",
                "workout_type": w_type,
                "description": f"Auto-generated · {phase_label} · week {wk + 1}",
                "tss_planned": float(day_tss),
                "phase": phase_label,
                "week_number": wk + 1,
            })

    return workouts
