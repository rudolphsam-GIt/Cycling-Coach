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
from metrics.training_load import compute_pmc


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
                       "schedule or import workouts, then tell them to review and confirm below.",
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
                        },
                        "required": ["date", "name", "workout_type", "description", "tss_planned"],
                    },
                },
            },
            "required": ["workouts"],
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
    else:
        raise ToolInputError(f"unknown tool {name}")

    if not result and name != "propose_workouts":
        return "No data found for that period."
    return json.dumps(result, default=str)


def _propose(args: dict, proposals: list[dict]) -> str:
    workouts = args.get("workouts")
    if not isinstance(workouts, list) or not workouts:
        raise ToolInputError("workouts must be a non empty list")
    if len(workouts) > 42:
        raise ToolInputError("propose at most 42 workouts at a time")

    checked = []
    for i, w in enumerate(workouts):
        if not isinstance(w, dict):
            raise ToolInputError(f"workout {i} must be an object")
        day = _iso_date(w.get("date"), f"workout {i} date")
        if day < date.today():
            raise ToolInputError(f"workout {i} is dated in the past")
        if w.get("workout_type") not in WORKOUT_TYPES:
            raise ToolInputError(f"workout {i} workout_type must be one of {WORKOUT_TYPES}")
        name, desc, tss = w.get("name"), w.get("description"), w.get("tss_planned")
        if not isinstance(name, str) or not name.strip() or not isinstance(desc, str):
            raise ToolInputError(f"workout {i} needs a name and description")
        if not isinstance(tss, (int, float)) or isinstance(tss, bool) or not 0 <= tss <= 500:
            raise ToolInputError(f"workout {i} tss_planned must be a number from 0 to 500")
        checked.append({"date": day.isoformat(), "name": name.strip(), "workout_type": w["workout_type"],
                        "description": desc.strip(), "tss_planned": float(tss)})

    proposals.extend(checked)
    return (f"{len(checked)} workouts are shown to the athlete with a confirm button. "
            "They are not saved yet; tell the athlete to review and confirm them below the chat.")
