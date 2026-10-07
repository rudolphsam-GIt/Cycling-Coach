"""
Multi month training programs, such as an off season, built through a conversation.

The coach drafts a program with propose_program. It is checked here, saved as a draft,
shown as a card with a PDF download, and discussed and revised until the athlete is happy.
Only then does "Add to my calendar" turn it into dated workouts and strength sessions.

A program is a list of phases. Each phase says how many weeks it lasts, how the weekly
training load moves, and what a typical week looks like. Turning that into dates is plain
arithmetic (expand), so the calendar always matches what the athlete read and downloaded.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta

from db import queries as q

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAX_PHASES = 8
MAX_WEEKS = 60
MIN_WEEKS = 2
RECOVERY_FACTOR = 0.6
RECOVERY_CHOICES = (0, 2, 3, 4)
MIN_RIDE_TSS = 10

TITLE_MAX, GOAL_MAX, OVERVIEW_MAX = 80, 600, 1500
LINE_MAX = 220


class ProgramError(ValueError):
    """The program isn't well formed. The message is written for the coach."""


def _text(value, what: str, limit: int, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ProgramError(f"{what} must be a non empty string")
    if len(value.strip()) > limit:
        raise ProgramError(f"{what} must be at most {limit} characters")
    return value.strip()


def _lines(value, what: str, most: int, limit: int = LINE_MAX) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > most:
        raise ProgramError(f"{what} must be a list of at most {most} short strings")
    return [_text(v, f"{what} item", limit) for v in value]


def _number(value, what: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or not low <= value <= high:
        raise ProgramError(f"{what} must be a number from {low:g} to {high:g}")
    return float(value)


def _whole(value, what: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ProgramError(f"{what} must be a whole number from {low} to {high}")
    return value


def _exercises(value, where: str) -> list[dict]:
    if not isinstance(value, list) or not value or len(value) > 12:
        raise ProgramError(f"{where} exercises must be a list of 1 to 12 exercises")
    out = []
    for j, e in enumerate(value):
        if not isinstance(e, dict):
            raise ProgramError(f"{where} exercise {j} must be an object")
        out.append({"name": _text(e.get("name"), f"{where} exercise {j} name", 80),
                    "sets": _whole(e.get("sets"), f"{where} exercise {j} sets", 1, 10),
                    "reps": _text(e.get("reps"), f"{where} exercise {j} reps", 40),
                    "intensity": _text(e.get("intensity"), f"{where} exercise {j} intensity", 80)})
    return out


def _day_name(value, where: str) -> str:
    if value not in DAYS:
        raise ProgramError(f"{where} day must be one of {DAYS}")
    return value


def _template(value, where: str, workout_types: list) -> list[dict]:
    if not isinstance(value, list) or len(value) > 7:
        raise ProgramError(f"{where} week_template must be a list of at most 7 days")
    out, seen = [], set()
    for j, d in enumerate(value):
        w = f"{where} template day {j}"
        if not isinstance(d, dict):
            raise ProgramError(f"{w} must be an object")
        day = _day_name(d.get("day"), w)
        if day in seen:
            raise ProgramError(f"{w}: {day} appears twice. One ride a day, put the other work in the day's description")
        seen.add(day)
        wtype = d.get("workout_type")
        if wtype not in workout_types:
            raise ProgramError(f"{w} workout_type must be one of {workout_types}")
        out.append({"day": day, "workout_type": wtype,
                    "name": _text(d.get("name"), f"{w} name", 80),
                    "description": _text(d.get("description"), f"{w} description", 400),
                    "share": _number(d.get("share"), f"{w} share", 0.05, 10),
                    "purpose": _text(d.get("purpose"), f"{w} purpose", 400),
                    "feel": _text(d.get("feel"), f"{w} feel", 250)})
    out.sort(key=lambda d: DAYS.index(d["day"]))
    return out


def _strength(value, where: str) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ProgramError(f"{where} strength must be an object")
    days = value.get("days")
    if not isinstance(days, list) or not days or len(days) > 4:
        raise ProgramError(f"{where} strength days must be a list of 1 to 4 days")
    days = sorted({_day_name(d, f"{where} strength") for d in days}, key=DAYS.index)
    return {"days": days,
            "name": _text(value.get("name"), f"{where} strength name", 80),
            "duration_minutes": _whole(value.get("duration_minutes"), f"{where} strength duration_minutes", 5, 180),
            "purpose": _text(value.get("purpose"), f"{where} strength purpose", 400),
            "exercises": _exercises(value.get("exercises"), f"{where} strength")}


def _overrides(value, total: int) -> dict[str, int]:
    """{week number as text: TSS} for weeks the athlete set by hand."""
    if value in (None, {}):
        return {}
    if not isinstance(value, dict) or len(value) > MAX_WEEKS:
        raise ProgramError("tss_overrides must be an object of week number to TSS")
    out = {}
    for k, v in value.items():
        try:
            week = int(k)
        except (TypeError, ValueError):
            raise ProgramError("tss_overrides keys must be week numbers")
        if not 1 <= week <= total:
            raise ProgramError(f"tss_overrides week {week} is outside the program's {total} weeks")
        out[str(week)] = round(_number(v, f"tss_overrides week {week}", 0, 1500))
    return out


def validate(raw: dict, today: date | None = None, workout_types: list | None = None) -> dict:
    """Check a proposed program and return it in the form that is saved, with end_date and
    total_weeks worked out. Raises ProgramError with a message the coach can act on."""
    today = today or date.today()
    workout_types = workout_types or q.WORKOUT_TYPES
    if not isinstance(raw, dict):
        raise ProgramError("the program must be an object")
    try:
        start = date.fromisoformat(raw.get("start_date"))
    except (TypeError, ValueError):
        raise ProgramError("start_date must be a date in YYYY-MM-DD form")
    if start < today:
        raise ProgramError("start_date can't be a day that has passed. Use today or later, ideally a Monday")

    phases_raw = raw.get("phases")
    if not isinstance(phases_raw, list) or not phases_raw or len(phases_raw) > MAX_PHASES:
        raise ProgramError(f"phases must be a list of 1 to {MAX_PHASES} phases, in order")
    phases, names, total = [], set(), 0
    for i, p in enumerate(phases_raw):
        where = f"phase {i}"
        if not isinstance(p, dict):
            raise ProgramError(f"{where} must be an object")
        name = _text(p.get("name"), f"{where} name", 60)
        if name in names:
            raise ProgramError(f"{where}: the name '{name}' is used twice")
        names.add(name)
        weeks = _whole(p.get("weeks"), f"{where} weeks", 1, 26)
        tss_a = _number(p.get("weekly_tss_start"), f"{where} weekly_tss_start", 0, 1500)
        tss_b = _number(p.get("weekly_tss_end"), f"{where} weekly_tss_end", 0, 1500)
        template = _template(p.get("week_template", []), where, workout_types)
        if not template and (tss_a or tss_b):
            raise ProgramError(f"{where} has weekly training load but no week_template. Add the typical week, "
                               "or set both loads to 0 for a break with no structured rides")
        rec = p.get("recovery_every", 0)
        if isinstance(rec, bool) or not isinstance(rec, int) or rec not in RECOVERY_CHOICES:
            raise ProgramError(f"{where} recovery_every must be one of {list(RECOVERY_CHOICES)} (0 for none)")
        phases.append({
            "name": name, "weeks": weeks,
            "focus": _text(p.get("focus"), f"{where} focus", 150),
            "why": _text(p.get("why"), f"{where} why", 600),
            "weekly_hours": _number(p.get("weekly_hours"), f"{where} weekly_hours", 0, 30),
            "weekly_tss_start": tss_a, "weekly_tss_end": tss_b, "recovery_every": rec,
            "key_workouts": _lines(p.get("key_workouts"), f"{where} key_workouts", 6),
            "success_markers": _lines(p.get("success_markers"), f"{where} success_markers", 5),
            "week_template": template,
            "strength": _strength(p.get("strength"), where),
        })
        total += weeks
    if not MIN_WEEKS <= total <= MAX_WEEKS:
        raise ProgramError(f"the phases add up to {total} weeks. A program is {MIN_WEEKS} to {MAX_WEEKS} weeks")

    checkpoints = []
    cps = raw.get("checkpoints") or []
    if not isinstance(cps, list) or len(cps) > 10:
        raise ProgramError("checkpoints must be a list of at most 10")
    for j, c in enumerate(cps):
        if not isinstance(c, dict):
            raise ProgramError(f"checkpoint {j} must be an object")
        checkpoints.append({"week": _whole(c.get("week"), f"checkpoint {j} week", 1, total),
                            "what": _text(c.get("what"), f"checkpoint {j} what", 150),
                            "why": _text(c.get("why"), f"checkpoint {j} why", 300)})
    checkpoints.sort(key=lambda c: c["week"])

    overrides = _overrides(raw.get("tss_overrides"), total)

    return {"title": _text(raw.get("title"), "title", TITLE_MAX),
            "goal": _text(raw.get("goal"), "goal", GOAL_MAX),
            "overview": _text(raw.get("overview"), "overview", OVERVIEW_MAX),
            "assumptions": _lines(raw.get("assumptions"), "assumptions", 8),
            "notes": _lines(raw.get("notes"), "notes", 6, 300),
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(weeks=total) - timedelta(days=1)).isoformat(),
            "total_weeks": total, "phases": phases, "checkpoints": checkpoints,
            "tss_overrides": overrides}


# ── Turning phases into weeks and dates ───────────────────────────────────────

def week_plan(program: dict, with_overrides: bool = True) -> list[dict]:
    """One row per week: number, dates, phase, target training load and whether it is a
    lighter week. Weeks are seven day blocks counted from the start date. A week the athlete
    set by hand uses their TSS and is marked edited."""
    overrides = (program.get("tss_overrides") or {}) if with_overrides else {}
    start = date.fromisoformat(program["start_date"])
    rows, n = [], 0
    for p in program["phases"]:
        weeks = p["weeks"]
        every = p["recovery_every"]
        light = [bool(every) and (j + 1) % every == 0 and p["weekly_tss_end"] > 0 for j in range(weeks)]
        normal = [j for j in range(weeks) if not light[j]]
        rank = {j: i for i, j in enumerate(normal)}
        for j in range(weeks):
            # The ramp runs across the normal weeks, so the last normal week reaches weekly_tss_end.
            # A lighter week is 60 percent of the normal week before it.
            ref = j if not light[j] else max(k for k in normal if k < j)
            frac = rank[ref] / (len(normal) - 1) if len(normal) > 1 else 0.0
            tss = p["weekly_tss_start"] + (p["weekly_tss_end"] - p["weekly_tss_start"]) * frac
            if light[j]:
                tss *= RECOVERY_FACTOR
            first = start + timedelta(weeks=n)
            edited = str(n + 1) in overrides
            rows.append({"week": n + 1, "start": first.isoformat(),
                         "end": (first + timedelta(days=6)).isoformat(),
                         "phase": p["name"], "tss": overrides[str(n + 1)] if edited else round(tss),
                         "edited": edited, "recovery": light[j],
                         "hours": round(p["weekly_hours"] * (RECOVERY_FACTOR if light[j] else 1.0), 1)})
            n += 1
    return rows


def _offset(first: date, day: str) -> int:
    """Days after `first` that the named weekday falls, within the seven day block."""
    return (DAYS.index(day) - first.weekday()) % 7


def expand(program: dict, today: date | None = None) -> dict:
    """The dated rides and strength sessions the program means, in the same shape the
    coach's proposals use. Days before today are left out."""
    today = today or date.today()
    weeks = week_plan(program)
    by_phase = {p["name"]: p for p in program["phases"]}
    rides, strength = [], []
    for w in weeks:
        p = by_phase[w["phase"]]
        first = date.fromisoformat(w["start"])
        note = {"focus": p["focus"], "why": p["why"]}
        total_share = sum(d["share"] for d in p["week_template"]) or 1.0
        for d in p["week_template"]:
            day = first + timedelta(days=_offset(first, d["day"]))
            tss = round(w["tss"] * d["share"] / total_share)
            if day < today or tss < MIN_RIDE_TSS:
                continue
            purpose = d["purpose"]
            if w["recovery"]:
                purpose = "This is a lighter week on purpose. Your body gets stronger while it recovers. " + purpose
            rides.append({
                "kind": "ride", "date": day.isoformat(),
                "name": ("(Recovery) " if w["recovery"] else "") + d["name"],
                "workout_type": d["workout_type"],
                "description": f"{d['description']} · {p['name']} · week {w['week']}",
                "tss_planned": float(tss), "phase": p["name"], "week_number": w["week"],
                "purpose": purpose, "feel": d["feel"], "phase_note": note})
        s = p["strength"]
        if s:
            for sd in s["days"]:
                day = first + timedelta(days=_offset(first, sd))
                if day < today:
                    continue
                strength.append({
                    "kind": "strength", "date": day.isoformat(), "name": s["name"],
                    "exercises": s["exercises"], "duration_minutes": s["duration_minutes"],
                    "purpose": s["purpose"], "phase": p["name"], "week_number": w["week"]})
    rides.sort(key=lambda r: r["date"])
    strength.sort(key=lambda r: r["date"])
    return {"rides": rides, "strength": strength}


def projected_fitness(program: dict, ctl: float, atl: float, today: date | None = None) -> list[dict]:
    """Daily CTL, ATL and TSB across the program if it is ridden as written, starting from
    the athlete's current numbers. Uses the same maths as the Plan impact panel."""
    from metrics import plan_impact
    today = today or date.today()
    start = max(date.fromisoformat(program["start_date"]), today)
    end = date.fromisoformat(program["end_date"])
    if end < start:
        return []
    plan = {r["date"]: r["tss_planned"] for r in expand(program, today)["rides"]}
    return plan_impact.project(plan, start, end, ctl, atl)


def weekly_ctl(program: dict, days: list[dict]) -> dict[int, float]:
    """CTL at the end of each program week, from projected_fitness rows."""
    by_day = {d["date"]: d["ctl"] for d in days}
    out = {}
    for w in week_plan(program):
        end = w["end"]
        if end in by_day:
            out[w["week"]] = by_day[end]
        elif days and end > days[-1]["date"]:
            out[w["week"]] = days[-1]["ctl"]
    return out


def where_are_we(program: dict, today: date | None = None) -> dict | None:
    """Current week and phase, or None when the program hasn't started or has finished."""
    today = today or date.today()
    for w in week_plan(program):
        if w["start"] <= today.isoformat() <= w["end"]:
            return w
    return None


def summary_line(program: dict, today: date | None = None) -> str:
    """One line for the coach: what the program is and where the athlete is in it."""
    today = today or date.today()
    here = where_are_we(program, today)
    base = f"{program['title']} ({program['start_date']} to {program['end_date']}, {program['total_weeks']} weeks)"
    if here:
        p = next(p for p in program["phases"] if p["name"] == here["phase"])
        return f"{base}. Now in week {here['week']}, {p['name']}: {p['focus']}"
    if today.isoformat() < program["start_date"]:
        return f"{base}. Starts {program['start_date']}"
    return f"{base}. Finished"


# ── Saving, showing and applying ──────────────────────────────────────────────

def save_draft(raw: dict, today: date | None = None) -> dict:
    """Validate and save as the current draft, replacing any earlier draft. Returns the program
    with its id and version."""
    program = validate(raw, today)
    previous = q.get_program("draft")
    version = (previous["version"] + 1) if previous else 1
    pid = q.save_program_draft(program["title"], program["start_date"], program["end_date"],
                               json.dumps(program), version, previous["id"] if previous else None)
    return {**program, "id": pid, "version": version}


def set_week_tss(program_id: int, changes: dict[int, float | None]) -> dict:
    """Change the weekly TSS of a draft by hand. `changes` maps a week number to a TSS, or to
    None to go back to the planned number. Returns the draft as saved."""
    row = q.get_program_by_id(program_id)
    if not row or row["status"] != "draft":
        raise ProgramError("that program is not a draft any more")
    program = json.loads(row["content_json"])
    overrides = dict(program.get("tss_overrides") or {})
    for week, tss in changes.items():
        if tss is None:
            overrides.pop(str(week), None)
        else:
            overrides[str(week)] = tss
    program["tss_overrides"] = overrides
    program = validate(program, date.fromisoformat(program["start_date"]))
    q.save_program_draft(program["title"], program["start_date"], program["end_date"],
                         json.dumps(program), row["version"], program_id)
    return {**program, "id": program_id, "version": row["version"]}


def load(status: str) -> dict | None:
    """The program with this status ('draft' or 'active') as a dict, or None."""
    row = q.get_program(status)
    if not row:
        return None
    return {**json.loads(row["content_json"]), "id": row["id"], "version": row["version"],
            "status": row["status"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "executed_at": row["executed_at"]}


def conflicts(program: dict, today: date | None = None) -> dict:
    """Planned workouts and strength sessions already on the calendar inside the program's dates
    (not done, today or later). These are what 'replace' would remove. Planned race days stay."""
    today = today or date.today()
    start = max(date.fromisoformat(program["start_date"]), today).isoformat()
    end = program["end_date"]
    rides = [w for w in q.get_workouts(start, end)
             if not w.get("completed") and w.get("workout_type") != "Race"]
    strength = [s for s in q.get_strength_between(start, end) if not s.get("completed")]
    return {"rides": rides, "strength": strength}


def apply(program_id: int, *, replace_existing: bool = False, today: date | None = None) -> dict:
    """Put the draft on the calendar. With replace_existing, planned workouts and strength
    sessions already inside the program's dates are removed first. It all happens in one
    transaction, so a failure part way changes nothing. Returns counts."""
    from garmin_workouts import remove_from_garmin
    from sync import remove_everywhere

    today = today or date.today()
    row = q.get_program_by_id(program_id)
    if not row or row["status"] != "draft":
        raise ProgramError("that program is not a draft any more")
    program = json.loads(row["content_json"])
    found = conflicts(program, today) if replace_existing else {"rides": [], "strength": []}
    items = expand(program, today)
    tag = f"Planned by AI Coach · {program['title']}"
    done = q.apply_program_rows(
        program_id,
        remove_workout_ids=[w["id"] for w in found["rides"]],
        remove_strength_ids=[s["id"] for s in found["strength"]],
        workouts=[{"date": w["date"], "name": w["name"], "workout_type": w["workout_type"],
                   "description": w["description"], "structured_json": None,
                   "tss_planned": w["tss_planned"], "notes": tag, "phase": w["phase"],
                   "week_number": w["week_number"], "purpose": w["purpose"], "feel": w["feel"]}
                  for w in items["rides"]],
        strength=[{"date": s["date"], "plan_week": s["week_number"], "exercises_json": json.dumps(s["exercises"]),
                   "duration_minutes": s["duration_minutes"], "notes": f"{s['name']} | {tag}",
                   "phase": s["phase"], "purpose": s["purpose"]} for s in items["strength"]],
        phases=[{"name": p["name"], "focus": p["focus"], "why": p["why"]} for p in program["phases"]])
    if done is None:
        raise ProgramError("that program is not a draft any more")
    for old in done["removed_workouts"]:
        remove_from_garmin(old)          # after the commit, and best effort, since it goes over the network
    remove_everywhere([old["id"] for old in done["removed_workouts"]])
    first = min([w["date"] for w in items["rides"]] + [s["date"] for s in items["strength"]]
                or [program["start_date"]])
    return {"rides": len(items["rides"]), "strength": len(items["strength"]),
            "removed": len(done["removed_workouts"]) + done["strength_removed"], "first": first}


def day_label(iso: str) -> str:
    """'Oct 12' from '2026-10-12'."""
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}"


def span_label(a: str, b: str) -> str:
    """'Oct 12 to Oct 18'."""
    return f"{day_label(a)} to {day_label(b)}"


def friendly_range(program: dict) -> str:
    a, b = date.fromisoformat(program["start_date"]), date.fromisoformat(program["end_date"])
    fmt = lambda d: f"{d:%b} {d.day}, {d.year}"
    return f"{fmt(a)} to {fmt(b)}"

