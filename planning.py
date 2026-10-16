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
import workout_recipes
from metrics.training_load import CTL_ALPHA

DAY_TEMPLATES = {
    "Endurance": [
        ("Mon", "Recovery",  0.45), ("Tue", "Endurance", 0.85),
        ("Wed", "Sweet Spot", 1.10), ("Thu", "Endurance", 0.80),
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


def target_ctl_range(current_ctl: float, race: bool = True) -> tuple[int, int, int]:
    """Slider bounds and a default for the target peak CTL. Someone with little or no ride
    history still gets a useful range rather than one capped near zero. With no race
    (`race` off) the default holds today's fitness, and the range also goes a little below it
    for an easier off season block."""
    if not race:
        cur = max(round(current_ctl or 0), 0)       # holds the fitness shown, so round rather than cut
        lo = max(int(cur * 0.8), 20)
        hi = max(min(max(cur + 40, 60), 150), lo + 1)
        return lo, hi, min(max(cur, lo), hi)
    cur = max(int(current_ctl or 0), 0)
    lo = max(cur, 20)
    hi = max(min(max(cur + 40, 60), 150), lo + 1)
    default = min(max(int(cur * 1.2), 30, lo), hi)
    return lo, hi, default


# How the weekly load is worked out. Fitness (CTL) trails training load by weeks, so the load
# is chosen week by week to land fitness where it should be, instead of ramping the load itself.
MAX_RAMP = 5.0            # CTL points a week at most, the gentle ramp the coach also uses
RECOVERY_FACTOR = 0.65    # a lighter week's load against the last normal week
TAPER_FACTORS = {2: (0.6, 0.4), 1: (0.5,)}   # taper weeks' load against the last build week
REACH_MARGIN = 2.0        # a peak this close to the target counts as reaching it
BOUNCE_BACK_MAX = 1.10    # a normal week's load at most 10% above the last normal week (coaching convention)
_WEEK_DECAY = (1 - CTL_ALPHA) ** 7

# The taper keeps a little intensity and drops volume. No race simulations, and the two days
# before the race are only easy spinning and openers.
TAPER_TEMPLATE = [
    ("Mon", None,        0.0), ("Tue", "Threshold", 1.00),
    ("Wed", "Recovery",  0.45), ("Thu", "VO2 Max",  0.80),
    ("Fri", None,        0.0), ("Sat", "Endurance", 1.10),
    ("Sun", "Recovery",  0.50),
]
HARD_TYPES = {"Sweet Spot", "Threshold", "VO2 Max", "Sprint/Anaerobic", "Race"}
FINAL_WEEK_HARD_MAX = 60  # TSS cap on a hard session in the last 7 days before the race
OPENERS_MAX = 40          # the day before the race
EASY_MAX = 35             # two days before the race
OPENERS_PURPOSE = ("Short openers the day before your race. A few brief efforts wake your legs up "
                   "without tiring them, so you start fresh and ready.")
OPENERS_FEEL = ("Easy spinning, 2 to 3 out of 10, with three or four 30 second efforts at about "
                "8 out of 10 and full rest between them. Stop while you feel good.")


def _is_recovery_week(wk: int, build_weeks: int, easing: bool = False) -> bool:
    """Every 4th week is lighter, except the last build week, since the taper follows it. A block
    that eases fitness down (`easing`) is light already, so it has no extra lighter weeks."""
    return not easing and (wk + 1) % 4 == 0 and wk < build_weeks - 1


def _easing(current_ctl: float, target_ctl: float) -> bool:
    """True when the target is clearly below today's fitness, as in an off season block."""
    return target_ctl < current_ctl - REACH_MARGIN


def _build_loads(current_ctl: float, target_ctl: float, build_weeks: int, ramp: float) -> tuple[list, float]:
    """Weekly TSS for the build weeks when fitness climbs by at most `ramp` a week and stops at
    the target, plus the peak fitness it reaches. Assumes an even load across each week."""
    ctl, peak, last_normal, loads = current_ctl, current_ctl, None, []
    level = current_ctl     # the fitness the last normal week reached, to climb back to after a lighter week
    easing = _easing(current_ctl, target_ctl)
    for wk in range(build_weeks):
        if _is_recovery_week(wk, build_weeks, easing):
            load = (last_normal if last_normal is not None else ctl * 7) * RECOVERY_FACTOR
        else:
            # Up by at most `ramp`, and down by at most MAX_RAMP when the target is below today.
            # After a lighter week it may also climb back to where it was, by at most MAX_RAMP,
            # so a gentle or zero ramp doesn't leave fitness stuck at the lighter week's dip.
            if target_ctl >= ctl:
                goal = min(max(ctl + ramp, min(level, ctl + MAX_RAMP)), target_ctl)
            else:
                goal = max(ctl - MAX_RAMP, target_ctl)
            load = max((goal - ctl * _WEEK_DECAY) / (1 - _WEEK_DECAY), 0.0) * 7
            if last_normal is not None:
                # Spread a climb back over a few weeks, but never below the load that holds `goal`.
                load = min(load, max(last_normal * BOUNCE_BACK_MAX, goal * 7))
            last_normal = load
            level = max(goal, level) if target_ctl >= current_ctl else goal
        ctl = load / 7 + (ctl - load / 7) * _WEEK_DECAY
        peak = max(peak, ctl)
        loads.append(load)
    return loads, peak


def _gentlest_ramp(current_ctl: float, target_ctl: float, build_weeks: int) -> float:
    """The smallest weekly ramp, up to MAX_RAMP, that reaches the target by the end of the build.
    Spreading the climb evenly is easier on the body than front loading it."""
    if _build_loads(current_ctl, target_ctl, build_weeks, MAX_RAMP)[1] < target_ctl - 0.25:
        return MAX_RAMP
    lo, hi = 0.0, MAX_RAMP
    for _ in range(30):
        mid = (lo + hi) / 2
        if _build_loads(current_ctl, target_ctl, build_weeks, mid)[1] >= target_ctl - 0.25:
            hi = mid
        else:
            lo = mid
    return hi


def _taper_day(w_type: str, day_tss: float, days_to_race: int) -> tuple[str, str, float, str | None, str | None]:
    """The taper session for a day, made easy in the last two days before the race and short in
    the final week. Returns (workout_type, name, tss, purpose, feel); purpose and feel are None
    when the usual wording for the type fits."""
    if days_to_race == 1:
        tss = round(workout_recipes.steps_tss(workout_recipes.OPENERS))
        return "Recovery", workout_recipes.OPENERS_NAME, tss, OPENERS_PURPOSE, OPENERS_FEEL
    if days_to_race == 2:
        return "Recovery", "Recovery", min(day_tss, EASY_MAX), None, None
    if days_to_race <= 7 and w_type in HARD_TYPES:
        return w_type, f"Short {w_type}", min(day_tss, FINAL_WEEK_HARD_MAX), None, None
    return w_type, w_type, day_tss, None, None


def weeks_to_race(today: date, race_date: date) -> int:
    """Weeks in a block to race_date, counting a part week as a week."""
    return max(1, -(-(race_date - today).days // 7))


def plan_block(current_ctl: float, target_ctl: float, race_date: date,
               phase_key: str, start_date: date | None = None,
               days_per_week: int | None = None,
               available_days: list[str] | str | None = None,
               taper: bool = True) -> dict:
    """
    A periodized block of ride workouts from start_date (default today) to race_date, with
    an outlook saying whether the target fitness is reachable.

    With `taper` off there is no race: race_date is just the day after the block ends, every
    week is a build (or lighter) week and nothing is tapered, for the off season or a block
    that only holds fitness.

    The weekly load is chosen so fitness (CTL) climbs evenly toward target_ctl, by no more than
    MAX_RAMP points a week, with every 4th week lighter and a 1 or 2 week taper at the end.
    When the target can't be reached that way, the block builds as far as it safely can and the
    outlook says so. Returns {"workouts": [...], "outlook": {...}}. Workouts are plain dicts
    (date, name, workout_type, description, tss_planned, phase, week_number, purpose, feel,
    phase_note). Nothing is written to the database. `days_per_week` limits how many days a
    week get a ride. `available_days` (weekday names) puts the rides on those weekdays instead,
    and wins over `days_per_week` when both are given.
    """
    today = start_date or date.today()
    # Count a part week before the race as a week, so the days just before it are planned too.
    weeks_out = weeks_to_race(today, race_date)
    taper_weeks = (2 if weeks_out >= 6 else 1) if taper else 0
    # A race a week or less away is all taper.
    build_weeks = weeks_out - taper_weeks
    # Weeks are counted back from the race, so the taper is always the last 7 or 14 days before
    # it. The first week may start before today, and its past days are skipped.
    first_week = race_date - timedelta(weeks=weeks_out)

    ramp = _gentlest_ramp(current_ctl, target_ctl, build_weeks)
    build_loads, _ = _build_loads(current_ctl, target_ctl, build_weeks, ramp)
    easing = _easing(current_ctl, target_ctl)
    last_build = next((build_loads[i] for i in reversed(range(build_weeks))
                       if not _is_recovery_week(i, build_weeks, easing)), current_ctl * 7)
    taper_factors = TAPER_FACTORS.get(taper_weeks, ())

    if phase_key not in DAY_TEMPLATES:
        phase_key = "Endurance"
    phase_label = PHASE_LABELS[phase_key]
    days = parse_days(available_days)

    def week_template(tmpl: list) -> list:
        if days:
            return _place_on_days(tmpl, days)
        return _fit_to_days(tmpl, days_per_week)

    workouts: list[dict] = []
    for wk in range(weeks_out):
        is_taper = wk >= build_weeks
        recovery = (not is_taper) and _is_recovery_week(wk, build_weeks, easing)
        if is_taper:
            week_tss = last_build * taper_factors[min(wk - build_weeks, len(taper_factors) - 1)]
            tmpl = week_template(TAPER_TEMPLATE)
        else:
            week_tss = build_loads[wk]
            tmpl = week_template(DAY_TEMPLATES[phase_key])

        active_days = [(d, t, wt) for d, t, wt in tmpl if t and wt > 0]
        total_weight = sum(wt for _, _, wt in active_days)

        week_start = first_week + timedelta(weeks=wk)
        for day_offset in range(7):
            w_date = week_start + timedelta(days=day_offset)
            if w_date < today:
                continue
            if w_date >= race_date:
                break
            # Each date takes its own weekday's session, so the long ride stays on the weekend
            # whatever day the block starts on.
            _, w_type, weight_frac = tmpl[w_date.weekday()]
            days_to_race = (race_date - w_date).days
            # Openers go on the day before the race even when the template rests that day, unless
            # the athlete can't ride that weekday.
            openers = is_taper and days_to_race == 1 and (not days or WEEKDAYS[w_date.weekday()] in days)
            if not openers and (not w_type or weight_frac == 0):
                continue
            day_tss = round(week_tss * (weight_frac / total_weight)) if total_weight else 0
            name, purpose, feel = w_type, None, None
            if is_taper:
                w_type, name, day_tss, purpose, feel = _taper_day(w_type, day_tss, days_to_race)
            if day_tss < 10:
                continue
            label = "(Taper) " if is_taper else ("(Recovery) " if recovery else "")
            week_phase = TAPER_LABEL if is_taper else phase_label
            purpose = purpose or explain.PURPOSE.get(w_type, explain.PURPOSE["Other"])
            if recovery:
                purpose = ("This is a lighter week on purpose. Your body gets stronger while it recovers, "
                           "so keep it easy. " + purpose)
            description = f"{workout_recipes.AUTO_MARK} · {week_phase} · week {wk + 1}"
            try:
                description = (workout_recipes.describe(workout_recipes.steps_for(
                    {"name": name, "workout_type": w_type, "tss_planned": day_tss})) + "\n" + description)
            except (KeyError, workout_recipes.RecipeError):
                pass
            workouts.append({
                "date": w_date.isoformat(),
                "name": f"{label}{name}",
                "workout_type": w_type,
                "description": description,
                "tss_planned": float(day_tss),
                "phase": week_phase,
                "week_number": wk + 1,
                "purpose": purpose,
                "feel": feel or explain.feel_for(w_type),
                "phase_note": PHASE_NOTES.get(week_phase),
            })

    # Openers added on a rest day can push race week past the riding days the athlete has. Keep
    # the openers and drop the week's smallest other rides instead.
    if taper and not days and days_per_week:
        last_week = [w for w in workouts if w["week_number"] == weeks_out]
        extra = len(last_week) - int(days_per_week)
        drop = sorted((w for w in last_week if workout_recipes.OPENERS_NAME not in w["name"]),
                      key=lambda w: w["tss_planned"])[:max(extra, 0)]
        workouts = [w for w in workouts if not any(w is d for d in drop)]

    return {"workouts": workouts,
            "outlook": block_outlook(workouts, current_ctl, target_ctl, today, race_date, ramp)}


def block_outlook(workouts: list[dict], current_ctl: float, target_ctl: float,
                  start: date, race_date: date, ramp: float | None = None) -> dict:
    """What a block does to fitness, day by day as written: the peak before the taper, the
    fitness on race day, and whether that peak reaches the target."""
    daily: dict[str, float] = {}
    for w in workouts:
        daily[w["date"]] = daily.get(w["date"], 0.0) + float(w["tss_planned"] or 0)
    taper_start = min((w["date"] for w in workouts if w["phase"] == TAPER_LABEL), default=race_date.isoformat())
    ctl, peak, day = float(current_ctl), float(current_ctl), start
    while day < race_date:
        ctl += (daily.get(day.isoformat(), 0.0) - ctl) * CTL_ALPHA
        if day.isoformat() < taper_start:
            peak = max(peak, ctl)
        day += timedelta(days=1)
    return {
        "target_ctl": round(float(target_ctl), 1),
        "peak_ctl": round(peak, 1),
        "race_day_ctl": round(ctl, 1),
        "reachable": peak >= target_ctl - REACH_MARGIN,
        "ramp_per_week": round(ramp, 1) if ramp is not None else None,
        "max_ramp_per_week": MAX_RAMP,
    }


def generate_block(current_ctl: float, target_ctl: float, race_date: date,
                   phase_key: str, start_date: date | None = None,
                   days_per_week: int | None = None,
                   available_days: list[str] | str | None = None,
                   taper: bool = True) -> list[dict]:
    """Just the workouts of plan_block."""
    return plan_block(current_ctl, target_ctl, race_date, phase_key, start_date,
                      days_per_week, available_days, taper)["workouts"]


# ── Target plan (set when a coach adds an athlete) ────────────────────────────

PLAN_WEEKS_DEFAULT = 8
PLAN_WEEKS_MIN, PLAN_WEEKS_MAX = 2, 60          # the same limits programs.validate uses


def next_monday(today: date | None = None) -> date:
    """Today if it is a Monday, else the coming Monday."""
    today = today or date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7)


def target_plan(today: date | None = None) -> dict | None:
    """The plan start date and length in weeks the coach set for this athlete, with its last day.
    None when they aren't set or the plan has already ended."""
    from db.queries import get_setting
    try:
        start = date.fromisoformat(get_setting("plan_start_date", "") or "")
        weeks = int(float(get_setting("plan_weeks", 0) or 0))
    except (TypeError, ValueError):
        return None
    if not PLAN_WEEKS_MIN <= weeks <= PLAN_WEEKS_MAX:
        return None
    end = start + timedelta(weeks=weeks) - timedelta(days=1)
    if end < (today or date.today()):
        return None
    return {"start": start, "weeks": weeks, "end": end}


def save_target_plan(start: date | None, weeks: int | None) -> None:
    from db.queries import set_setting
    set_setting("plan_start_date", start.isoformat() if start and weeks else "")
    set_setting("plan_weeks", int(weeks) if start and weeks else "")


def plan_span_text(start: date, weeks: int) -> str:
    end = start + timedelta(weeks=weeks) - timedelta(days=1)
    return f"{start:%a %b} {start.day} to {end:%a %b} {end.day}, {end.year}"
