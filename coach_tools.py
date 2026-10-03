"""
Tools the AI Coach can call to look up the athlete's data and propose workouts.

Every tool except propose_workouts is read only. propose_workouts never writes
to the database; it hands the workouts back to the page, which shows the
athlete a confirm button before anything is saved.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from db.queries import (get_activities, get_workouts, get_races, get_wellness_range,
                        get_ftp_history, get_weekly_tss_summary, get_setting, get_recovery_range,
                        add_memory,
                        WORKOUT_TYPES)
from metrics.training_load import compute_pmc, get_current_metrics
import planning


MEMORY_CATEGORIES = ["health", "schedule", "preferences", "goals", "training_response", "other"]


def _int_prop(description: str, minimum: int, maximum: int) -> dict:
    return {"type": "integer", "description": description, "minimum": minimum, "maximum": maximum}


TOOLS = [
    {
        "name": "get_rides",
        "description": "List the athlete's recorded rides and other activities, newest first, "
                       "with duration, distance, climbing, power, heart rate and TSS.",
        "input_schema": {
            "type": "object",
            "properties": {"days_back": _int_prop("How many days of history to include.", 1, 365)},
            "required": ["days_back"],
        },
    },
    {
        "name": "get_training_load",
        "description": "Daily fitness (CTL), fatigue (ATL), form (TSB) and TSS over a period. "
                       "Periods longer than 42 days return one row per week plus the last 14 days.",
        "input_schema": {
            "type": "object",
            "properties": {"days_back": _int_prop("How many days of history to include.", 7, 365)},
            "required": ["days_back"],
        },
    },
    {
        "name": "get_weekly_summary",
        "description": "Per week planned TSS, actual TSS, ride count and hours in power zones 1 to 5.",
        "input_schema": {
            "type": "object",
            "properties": {"weeks": _int_prop("How many weeks, ending with the current week.", 1, 26)},
            "required": ["weeks"],
        },
    },
    {
        "name": "get_planned_workouts",
        "description": "Workouts already on the athlete's Training Planner between two dates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["start_date", "end_date"],
        },
    },
    {
        "name": "get_races",
        "description": "The athlete's race calendar, including results logged for past races.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_wellness",
        "description": "Daily check ins: legs feel (1 to 5), energy (1 to 5), sleep hours and notes.",
        "input_schema": {
            "type": "object",
            "properties": {"days_back": _int_prop("How many days of history to include.", 1, 90)},
            "required": ["days_back"],
        },
    },
    {
        "name": "get_recovery",
        "description": "Daily recovery from the athlete's Garmin: sleep hours and score, overnight "
                       "HRV (ms) and status, resting heart rate, training readiness (0 to 100) "
                       "and peak body battery.",
        "input_schema": {
            "type": "object",
            "properties": {"days_back": _int_prop("How many days of history to include.", 1, 90)},
            "required": ["days_back"],
        },
    },
    {
        "name": "get_ftp_history",
        "description": "Past FTP values with the date each was set.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "remember",
        "description": "Save a short note about the athlete that will matter in future sessions, "
                       "such as an injury, schedule limit, preference, goal or how they respond "
                       "to training. The athlete can see and delete these notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "One sentence, under 200 characters"},
                "category": {"type": "string", "enum": MEMORY_CATEGORIES},
            },
            "required": ["note", "category"],
        },
    },
    {
        "name": "propose_workouts",
        "description": "Propose workouts to add to the athlete's Training Planner. Nothing is saved "
                       "until the athlete confirms, so call this whenever they ask you to plan, "
                       "schedule or import workouts, then tell them to review and confirm below. "
                       "For a multi-week block, tag each workout with phase and week_number so the "
                       "athlete sees it grouped sensibly instead of as one long flat list, and "
                       "describe every phase in phases. Every workout needs a purpose and a feel, "
                       "written for someone who may be new to structured training.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workouts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string", "description": "YYYY-MM-DD, today or later"},
                            "name": {"type": "string"},
                            "workout_type": {"type": "string", "enum": WORKOUT_TYPES},
                            "description": {"type": "string",
                                            "description": "Structure with durations and power targets"},
                            "tss_planned": {"type": "number"},
                            "purpose": {"type": "string",
                                        "description": "One or two plain sentences. What this workout "
                                                       "trains and how it serves this athlete's goal. "
                                                       "No unexplained jargon."},
                            "feel": {"type": "string",
                                     "description": "How it should feel, such as effort out of 10 and "
                                                    "a talk test, for example '4 out of 10, you can chat "
                                                    "in full sentences'"},
                            "phase": {"type": "string",
                                     "description": "Optional — e.g. 'Base / Endurance', only for "
                                                    "multi-week blocks, groups the proposal in the UI"},
                            "week_number": {"type": "integer",
                                           "description": "Optional — 1-based week within the block"},
                        },
                        "required": ["date", "name", "workout_type", "description", "tss_planned",
                                     "purpose", "feel"],
                    },
                },
                "phases": {
                    "type": "array",
                    "description": "For a multi-week block, one entry for every phase named in the "
                                   "workouts, explaining what that phase is building and why.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Exactly as used in the workouts' phase"},
                            "focus": {"type": "string", "description": "One short line, what this phase builds"},
                            "why": {"type": "string",
                                    "description": "Two or three plain sentences, why this phase comes "
                                                   "now and how it serves the athlete's goal"},
                        },
                        "required": ["name", "focus", "why"],
                    },
                },
            },
            "required": ["workouts"],
        },
    },
    {
        "name": "propose_strength_sessions",
        "description": "Propose strength sessions to add alongside rides from propose_workouts. "
                       "Nothing is saved until the athlete confirms. Use this when a plan should "
                       "include gym work, not just riding.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sessions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string", "description": "YYYY-MM-DD, today or later"},
                            "name": {"type": "string", "description": "e.g. 'Lower body — heavy'"},
                            "exercises": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "sets": {"type": "integer"},
                                        "reps": {"type": "string"},
                                        "intensity": {"type": "string"},
                                        "notes": {"type": "string"},
                                    },
                                    "required": ["name", "sets", "reps", "intensity"],
                                },
                            },
                            "duration_minutes": {"type": "integer"},
                            "purpose": {"type": "string",
                                        "description": "One or two plain sentences. What this session is "
                                                       "for and how it helps this athlete's riding"},
                            "phase": {"type": "string", "description": "Optional, as in propose_workouts"},
                            "week_number": {"type": "integer", "description": "Optional, as in propose_workouts"},
                        },
                        "required": ["date", "name", "exercises", "duration_minutes", "purpose"],
                    },
                },
            },
            "required": ["sessions"],
        },
    },
    {
        "name": "generate_training_block",
        "description": "Generate a draft periodized block of rides from today (or a given start "
                       "date) to a race date, ramping weekly training load toward a target CTL "
                       "with a taper worked into the end. This does not propose or save anything — "
                       "use it as a starting scaffold for a multi-week plan you're building with "
                       "the athlete in conversation, then adjust it based on what they tell you "
                       "before calling propose_workouts with the final version.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_ctl": {"type": "number", "description": "Target peak CTL (fitness) before the taper, roughly 10 to 200."},
                "race_date": {"type": "string", "description": "YYYY-MM-DD, the race or goal date, in the future"},
                "phase_focus": {"type": "string", "enum": list(planning.DAY_TEMPLATES.keys()),
                                "description": "The build phase's emphasis for the non-taper weeks"},
                "start_date": {"type": "string", "description": "YYYY-MM-DD, defaults to today if omitted"},
            },
            "required": ["target_ctl", "race_date", "phase_focus"],
        },
    },
]

STATUS_LABELS = {
    "get_rides": "Checking your rides",
    "get_training_load": "Checking your training load",
    "get_weekly_summary": "Checking your weekly totals",
    "get_planned_workouts": "Checking your planner",
    "get_races": "Checking your race calendar",
    "get_wellness": "Checking your check ins",
    "get_recovery": "Checking your sleep and recovery",
    "get_ftp_history": "Checking your FTP history",
    "remember": "Saving a note about you",
    "propose_workouts": "Drafting workouts",
    "propose_strength_sessions": "Drafting strength sessions",
    "generate_training_block": "Sketching a training block",
}


class ToolInputError(ValueError):
    pass


def _days(args: dict, key: str, low: int, high: int) -> int:
    value = args.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise ToolInputError(f"{key} must be a whole number from {low} to {high}")
    return value


def _iso_date(value, key: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ToolInputError(f"{key} must be a date in YYYY-MM-DD form")


def _ride_row(a: dict) -> dict:
    row = {
        "date": a["date"],
        "name": a.get("name"),
        "type": a.get("sport_type"),
        "minutes": round(a["duration_seconds"] / 60) if a.get("duration_seconds") else None,
        "km": round(a["distance_meters"] / 1000, 1) if a.get("distance_meters") else None,
        "climb_m": round(a["elevation_gain_meters"]) if a.get("elevation_gain_meters") else None,
        "avg_w": a.get("avg_power_watts"),
        "np_w": a.get("normalized_power"),
        "avg_hr": a.get("avg_hr"),
        "tss": round(a["tss"]) if a.get("tss") else None,
        "if": a.get("if_value"),
    }
    return {k: v for k, v in row.items() if v is not None}


def _training_load(days_back: int) -> list[dict]:
    start, end = date.today() - timedelta(days=days_back), date.today()
    df = compute_pmc(start, end,
                     float(get_setting("ctl_start", 0) or 0),
                     float(get_setting("atl_start", 0) or 0))
    rows = [
        {"date": str(r["date"])[:10], "tss": round(r["tss"]), "ctl": round(r["ctl"], 1),
         "atl": round(r["atl"], 1), "tsb": round(r["tsb"], 1)}
        for _, r in df.iterrows()
    ]
    if days_back > 42:
        weekly = rows[:-14][::7]
        return weekly + rows[-14:]
    return rows


def run_tool(name: str, args: dict, proposals: list[dict]) -> str:
    """Run one tool and return its result as a JSON string for Claude."""
    if not isinstance(args, dict):
        raise ToolInputError("input must be an object")

    if name == "get_rides":
        result = [_ride_row(a) for a in get_activities(days_back=_days(args, "days_back", 1, 365))]
    elif name == "get_training_load":
        result = _training_load(_days(args, "days_back", 7, 365))
    elif name == "get_weekly_summary":
        result = get_weekly_tss_summary(weeks=_days(args, "weeks", 1, 26))
    elif name == "get_planned_workouts":
        start = _iso_date(args.get("start_date"), "start_date")
        end = _iso_date(args.get("end_date"), "end_date")
        result = [
            {k: w.get(k) for k in ("date", "name", "workout_type", "description", "tss_planned", "completed")}
            for w in get_workouts(start.isoformat(), end.isoformat())
        ]
    elif name == "get_races":
        keys = ("name", "date", "distance_km", "elevation_gain_meters", "category", "notes",
                "placing", "field_size", "race_avg_power", "result_notes")
        result = [{k: r.get(k) for k in keys if r.get(k) is not None} for r in get_races()]
    elif name == "get_wellness":
        days_back = _days(args, "days_back", 1, 90)
        start = (date.today() - timedelta(days=days_back)).isoformat()
        result = [
            {k: w.get(k) for k in ("date", "legs_feel", "energy", "sleep_hours", "notes")}
            for w in get_wellness_range(start, date.today().isoformat())
        ]
    elif name == "get_recovery":
        days_back = _days(args, "days_back", 1, 90)
        start = (date.today() - timedelta(days=days_back)).isoformat()
        result = [
            {k: v for k, v in r.items() if k != "synced_at" and v is not None}
            for r in get_recovery_range(start, date.today().isoformat())
        ]
    elif name == "get_ftp_history":
        result = [{"date": f["date"], "ftp_watts": f["ftp_watts"]} for f in get_ftp_history()]
    elif name == "remember":
        note, category = args.get("note"), args.get("category")
        if not isinstance(note, str) or not 0 < len(note.strip()) <= 300:
            raise ToolInputError("note must be a sentence under 300 characters")
        if category not in MEMORY_CATEGORIES:
            raise ToolInputError(f"category must be one of {MEMORY_CATEGORIES}")
        add_memory(category, note.strip())
        return "Saved."
    elif name == "propose_workouts":
        result = _propose(args, proposals)
    elif name == "propose_strength_sessions":
        result = _propose_strength(args, proposals)
    elif name == "generate_training_block":
        result = _generate_block(args)
    else:
        raise ToolInputError(f"unknown tool {name}")

    if not result and name not in ("propose_workouts", "propose_strength_sessions"):
        return "No data found for that period."
    return json.dumps(result, default=str)


def _optional_str(w: dict, key: str, where: str) -> str | None:
    value = w.get(key)
    if value is not None and not isinstance(value, str):
        raise ToolInputError(f"{where} {key} must be a string")
    return value


def _optional_int(w: dict, key: str, where: str) -> int | None:
    value = w.get(key)
    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 52):
        raise ToolInputError(f"{where} {key} must be an integer from 1 to 52")
    return value


def _text(w: dict, key: str, where: str, limit: int) -> str:
    """A required, non empty string of at most `limit` characters."""
    value = w.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolInputError(f"{where} needs a {key}, written in plain words for the athlete")
    if len(value.strip()) > limit:
        raise ToolInputError(f"{where} {key} must be at most {limit} characters")
    return value.strip()


PURPOSE_MAX, FEEL_MAX, FOCUS_MAX, WHY_MAX = 400, 250, 150, 500


def _phases(args: dict) -> dict:
    """{phase name: {focus, why}} from the optional phases argument."""
    phases = args.get("phases")
    if phases is None:
        return {}
    if not isinstance(phases, list) or len(phases) > 20:
        raise ToolInputError("phases must be a list of at most 20 entries")
    out = {}
    for i, p in enumerate(phases):
        where = f"phase {i}"
        if not isinstance(p, dict):
            raise ToolInputError(f"{where} must be an object")
        name = p.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ToolInputError(f"{where} needs a name")
        out[name.strip()] = {"focus": _text(p, "focus", where, FOCUS_MAX),
                             "why": _text(p, "why", where, WHY_MAX)}
    return out


def _propose(args: dict, proposals: list[dict]) -> str:
    workouts = args.get("workouts")
    if not isinstance(workouts, list) or not workouts:
        raise ToolInputError("workouts must be a non empty list")
    if len(workouts) > 60:
        raise ToolInputError("propose at most 60 workouts at a time")

    phases = _phases(args)
    checked = []
    for i, w in enumerate(workouts):
        if not isinstance(w, dict):
            raise ToolInputError(f"workout {i} must be an object")
        where = f"workout {i}"
        day = _iso_date(w.get("date"), f"{where} date")
        if day < date.today():
            raise ToolInputError(f"{where} is dated in the past")
        if w.get("workout_type") not in WORKOUT_TYPES:
            raise ToolInputError(f"{where} workout_type must be one of {WORKOUT_TYPES}")
        name, desc, tss = w.get("name"), w.get("description"), w.get("tss_planned")
        if not isinstance(name, str) or not name.strip() or not isinstance(desc, str):
            raise ToolInputError(f"{where} needs a name and description")
        if not isinstance(tss, (int, float)) or isinstance(tss, bool) or not 0 <= tss <= 500:
            raise ToolInputError(f"{where} tss_planned must be a number from 0 to 500")
        phase = _optional_str(w, "phase", where)
        if phase is not None:
            phase = phase.strip() or None
        if phase and phase not in phases:
            raise ToolInputError(f"{where} is in phase '{phase}', which is missing from phases. "
                                 "Describe every phase you use in phases.")
        checked.append({"kind": "ride", "date": day.isoformat(), "name": name.strip(),
                        "workout_type": w["workout_type"], "description": desc.strip(),
                        "tss_planned": float(tss), "phase": phase,
                        "week_number": _optional_int(w, "week_number", where),
                        "purpose": _text(w, "purpose", where, PURPOSE_MAX),
                        "feel": _text(w, "feel", where, FEEL_MAX),
                        "phase_note": phases.get(phase) if phase else None})

    proposals.extend(checked)
    return (f"{len(checked)} rides are shown to the athlete with a confirm button. "
            "They are not saved yet; tell the athlete to review and confirm them below the chat.")


def _propose_strength(args: dict, proposals: list[dict]) -> str:
    sessions = args.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise ToolInputError("sessions must be a non empty list")
    if len(sessions) > 30:
        raise ToolInputError("propose at most 30 strength sessions at a time")

    checked = []
    for i, s in enumerate(sessions):
        if not isinstance(s, dict):
            raise ToolInputError(f"session {i} must be an object")
        where = f"session {i}"
        day = _iso_date(s.get("date"), f"{where} date")
        if day < date.today():
            raise ToolInputError(f"{where} is dated in the past")
        name = s.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ToolInputError(f"{where} needs a name")
        exercises = s.get("exercises")
        if not isinstance(exercises, list) or not exercises:
            raise ToolInputError(f"{where} needs at least one exercise")
        for j, ex in enumerate(exercises):
            if (not isinstance(ex, dict) or not isinstance(ex.get("name"), str) or not ex["name"].strip()
                    or not isinstance(ex.get("sets"), int) or isinstance(ex.get("sets"), bool)
                    or not isinstance(ex.get("reps"), str) or not ex["reps"].strip()
                    or not isinstance(ex.get("intensity"), str) or not ex["intensity"].strip()):
                raise ToolInputError(f"{where} exercise {j} needs a name, integer sets, reps and intensity")
        duration = s.get("duration_minutes")
        if not isinstance(duration, int) or isinstance(duration, bool) or not 5 <= duration <= 180:
            raise ToolInputError(f"{where} duration_minutes must be a whole number from 5 to 180")
        checked.append({"kind": "strength", "date": day.isoformat(), "name": name.strip(),
                        "exercises": exercises, "duration_minutes": duration,
                        "purpose": _text(s, "purpose", where, PURPOSE_MAX),
                        "phase": _optional_str(s, "phase", where),
                        "week_number": _optional_int(s, "week_number", where)})

    proposals.extend(checked)
    return (f"{len(checked)} strength sessions are shown to the athlete with a confirm button. "
            "They are not saved yet; tell the athlete to review and confirm them below the chat.")


def _generate_block(args: dict) -> list[dict]:
    target_ctl = args.get("target_ctl")
    if not isinstance(target_ctl, (int, float)) or isinstance(target_ctl, bool) or not 10 <= target_ctl <= 200:
        raise ToolInputError("target_ctl must be a number from 10 to 200")
    race_date = _iso_date(args.get("race_date"), "race_date")
    if race_date <= date.today():
        raise ToolInputError("race_date must be in the future")
    phase_focus = args.get("phase_focus")
    if not isinstance(phase_focus, str) or phase_focus not in planning.DAY_TEMPLATES:
        raise ToolInputError(f"phase_focus must be one of {list(planning.DAY_TEMPLATES.keys())}")
    start = _iso_date(args["start_date"], "start_date") if args.get("start_date") else date.today()
    if start >= race_date:
        raise ToolInputError("start_date must be before race_date")
    if (race_date - start).days > 104 * 7:
        raise ToolInputError("that's more than 2 years out — generate a shorter block and extend it later")
    current_ctl = get_current_metrics()["ctl"]
    try:
        days = int(float(get_setting("days_per_week", 0) or 0)) or None
    except (TypeError, ValueError):
        days = None
    return planning.generate_block(current_ctl, float(target_ctl), race_date, phase_focus, start,
                                   days_per_week=days)
