"""
Send planned workouts to Garmin Connect as structured cycling workouts.

A planned workout is plain text ("3x12 min at 90% FTP"). Claude turns it into
steps (warm up, intervals with power ranges as % of FTP, repeats, cool down);
we check the numbers, convert them to watts, upload the workout and schedule it
on its date so it syncs to the athlete's Edge or watch.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import claude_client
from db.queries import get_setting, set_workout_garmin

APP_TAG = "Sent from Cycling Coach"

STEP_KINDS = ["warmup", "interval", "recovery", "cooldown"]
STEP_IDS = {"warmup": 1, "cooldown": 2, "interval": 3, "recovery": 4, "repeat": 6}

_SIMPLE_STEP = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": STEP_KINDS},
        "minutes": {"type": "number"},
        "low_pct": {"type": ["number", "null"]},
        "high_pct": {"type": ["number", "null"]},
    },
    "required": ["kind", "minutes", "low_pct", "high_pct"],
    "additionalProperties": False,
}

SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": STEP_KINDS + ["repeat"]},
                    "minutes": {"type": ["number", "null"]},
                    "low_pct": {"type": ["number", "null"]},
                    "high_pct": {"type": ["number", "null"]},
                    "repeat_count": {"type": ["integer", "null"]},
                    "repeat_steps": {"type": ["array", "null"], "items": _SIMPLE_STEP},
                },
                "required": ["kind", "minutes", "low_pct", "high_pct", "repeat_count", "repeat_steps"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["steps"],
    "additionalProperties": False,
}

SYSTEM = """You convert a cyclist's planned workout into structured steps for a Garmin bike computer.

Rules:
- Power targets are a range in percent of FTP (low_pct to high_pct). Convert any watts in the
  description to percent of the FTP given. Use null for both only when a step should have no
  power target at all.
- Use a "repeat" step for repeated intervals: set repeat_count and put the work and recovery
  steps in repeat_steps. For repeat steps, minutes, low_pct and high_pct are null.
- For non-repeat steps, repeat_count and repeat_steps are null.
- Include a warm up and cool down if the description has them. If it names none and the
  workout has hard intervals, add a 10 minute warm up at 50 to 65% and a 10 minute cool down
  at 45 to 60%.
- Steady rides with no intervals become a single interval step at the described intensity,
  or 56 to 75% (zone 2) for easy or endurance rides.
- Match the total duration to the description as closely as you can.
- When the description gives no durations (for example "Steady ride · Base · week 6"), size the
  ride from the planned TSS: hours = TSS / (100 x IF squared), using an intensity factor of about
  0.65 for recovery, 0.70 for endurance and long rides, 0.82 for tempo, 0.90 for threshold and
  0.85 for VO2 or sprint sessions once warm up, recoveries and cool down are counted."""


class WorkoutError(Exception):
    pass


def _ftp() -> float:
    ftp = float(get_setting("ftp_watts", 0) or 0)
    if ftp <= 0:
        raise WorkoutError("Set your FTP in Settings first, so power targets can be worked out.")
    return ftp


def _check_step(step: dict, where: str) -> None:
    if step["kind"] not in STEP_KINDS:
        raise WorkoutError(f"{where}: unexpected step type")
    minutes = step.get("minutes")
    if not isinstance(minutes, (int, float)) or not 0.1 <= minutes <= 600:
        raise WorkoutError(f"{where}: duration must be between 6 seconds and 10 hours")
    low, high = step.get("low_pct"), step.get("high_pct")
    if (low is None) != (high is None):
        raise WorkoutError(f"{where}: power range is missing one end")
    if low is not None and not (0 < low <= high <= 300):
        raise WorkoutError(f"{where}: power range {low} to {high}% of FTP doesn't make sense")


def check_steps(steps: list) -> list:
    if not isinstance(steps, list) or not steps:
        raise WorkoutError("No steps came back for this workout.")
    total = 0.0
    for i, step in enumerate(steps, 1):
        if step.get("kind") == "repeat":
            count, inner = step.get("repeat_count"), step.get("repeat_steps")
            if not isinstance(count, int) or not 1 <= count <= 50 or not inner:
                raise WorkoutError(f"Step {i}: repeat needs a count from 1 to 50 and some steps")
            for j, s in enumerate(inner, 1):
                _check_step(s, f"Step {i}.{j}")
            total += count * sum(s["minutes"] for s in inner)
        else:
            _check_step(step, f"Step {i}")
            total += step["minutes"]
    if total > 12 * 60:
        raise WorkoutError("The steps add up to more than 12 hours.")
    return steps


def build_steps(workout: dict) -> list:
    """Ask Claude to turn a planned workout's text into checked steps."""
    ftp = _ftp()
    prompt = (f"FTP: {ftp:.0f} W\n"
              f"Workout name: {workout['name']}\n"
              f"Type: {workout.get('workout_type') or 'unknown'}\n"
              f"Planned TSS: {workout.get('tss_planned') or 'unknown'}\n"
              f"Description: {workout.get('description') or '(none)'}")
    try:
        data = claude_client.structured(SYSTEM, prompt, SCHEMA, effort="low")
    except claude_client.ClaudeError as e:
        raise WorkoutError(str(e)) from e
    return check_steps(data.get("steps"))


def saved_steps(workout: dict) -> list | None:
    """The steps already built for this workout, or None."""
    if not workout.get("structured_json"):
        return None
    try:
        return check_steps(json.loads(workout["structured_json"]))
    except (WorkoutError, TypeError, ValueError):
        return None


def ensure_steps(workouts: list[dict], progress=None, max_workers: int = 4) -> dict:
    """{workout id: steps, or an error message} for each workout. Saved steps are reused. The
    rest are built with Claude, several at once, and saved so they are never built twice.
    `progress(done, total)` is called as each one finishes."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from db.queries import save_workout_steps

    out, todo = {}, []
    for w in workouts:
        steps = saved_steps(w)
        if steps is None:
            todo.append(w)
        else:
            out[w["id"]] = steps
    if todo:
        _ftp()                               # a missing FTP is one clear message, not one per workout
    done = 0
    from db import schema
    build = schema.pinned(build_steps)       # workers read this athlete's FTP, not the owner's
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(build, w): w for w in todo}
        for f in as_completed(futures):
            w = futures[f]
            try:
                steps = f.result()
                save_workout_steps(w["id"], json.dumps(steps))
                out[w["id"]] = steps
            except WorkoutError as e:
                out[w["id"]] = str(e)
            except Exception as e:           # one bad workout never stops the rest
                out[w["id"]] = f"Couldn't build the steps: {e}"
            done += 1
            if progress:
                progress(done, len(todo))
    return out


def _watts(pct: float | None, ftp: float) -> float | None:
    return None if pct is None else round(pct / 100 * ftp)


def _walk_steps(steps: list):
    """Flatten `steps` into leaf steps, yielding (step, enclosing_repeat) pairs.

    `enclosing_repeat` is the repeat dict a leaf step belongs to (so callers
    can read its `repeat_count`, or detect a new repeat block by identity),
    or None for a top-level step. This only flattens repeat_steps into leaves
    once each (not expanded per-repetition) — callers that need the
    multiplier use enclosing_repeat["repeat_count"] themselves. Shared by
    preview_rows and total_minutes; to_garmin_json and to_fit_bytes need
    different per-step output shapes and are intentionally left separate.
    """
    for s in steps:
        if s["kind"] == "repeat":
            for inner in s["repeat_steps"]:
                yield inner, s
        else:
            yield s, None


def preview_rows(steps: list) -> list[dict]:
    """Readable rows for showing the steps before sending."""
    ftp = _ftp()
    rows = []
    last_group = None

    def row(s, prefix=""):
        low, high = _watts(s["low_pct"], ftp), _watts(s["high_pct"], ftp)
        target = f"{low:.0f} to {high:.0f} W" if low is not None else "No target"
        rows.append({"Step": prefix + s["kind"].title(), "Time": f"{s['minutes']:g} min",
                     "Target": target})

    for s, group in _walk_steps(steps):
        if group is not None:
            if group is not last_group:
                rows.append({"Step": f"Repeat {group['repeat_count']}×", "Time": "", "Target": ""})
                last_group = group
            row(s, "    ")
        else:
            last_group = None
            row(s)
    return rows


def total_minutes(steps: list) -> float:
    return sum(s["minutes"] * (group["repeat_count"] if group is not None else 1)
               for s, group in _walk_steps(steps))


def to_garmin_json(workout: dict, steps: list) -> dict:
    ftp = _ftp()
    order = 0

    def executable(s: dict, in_repeat: bool) -> dict:
        nonlocal order
        order += 1
        low, high = _watts(s["low_pct"], ftp), _watts(s["high_pct"], ftp)
        step = {
            "type": "ExecutableStepDTO",
            "stepOrder": order,
            "stepType": {"stepTypeId": STEP_IDS[s["kind"]], "stepTypeKey": s["kind"],
                         "displayOrder": STEP_IDS[s["kind"]]},
            "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time",
                             "displayOrder": 2, "displayable": True},
            "endConditionValue": round(s["minutes"] * 60),
            "targetValueOne": low,
            "targetValueTwo": high,
            "zoneNumber": None,
        }
        step["targetType"] = (
            {"workoutTargetTypeId": 2, "workoutTargetTypeKey": "power.zone", "displayOrder": 2}
            if low is not None else
            {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
        )
        if in_repeat:
            step["childStepId"] = 1
        return step

    garmin_steps = []
    for s in steps:
        if s["kind"] == "repeat":
            order += 1
            group = {
                "type": "RepeatGroupDTO",
                "stepOrder": order,
                "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
                "childStepId": 1,
                "numberOfIterations": s["repeat_count"],
                "smartRepeat": False,
                "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations",
                                 "displayOrder": 7, "displayable": False},
                "endConditionValue": float(s["repeat_count"]),
                "skipLastRestStep": False,
            }
            group["workoutSteps"] = [executable(inner, True) for inner in s["repeat_steps"]]
            garmin_steps.append(group)
        else:
            garmin_steps.append(executable(s, False))

    sport = {"sportTypeId": 2, "sportTypeKey": "cycling", "displayOrder": 2}
    description = (workout.get("description") or "").strip()
    # What the workout is for and how it should feel travel with it to the bike computer.
    extra = [f"{label}. {text.strip()}" for label, text in
             (("How it should feel", workout.get("feel")), ("Why", workout.get("purpose")))
             if text and text.strip()]
    description = "\n\n".join([p for p in [description, *extra] if p])
    return {
        "workoutName": workout["name"][:80],
        "description": f"{description}\n\n{APP_TAG}".strip(),
        "sportType": sport,
        "estimatedDurationInSecs": round(total_minutes(steps) * 60),
        "workoutSegments": [{"segmentOrder": 1, "sportType": sport, "workoutSteps": garmin_steps}],
    }


def send(workout: dict, steps: list) -> None:
    """Upload the workout, schedule it on its date, and remember the Garmin ids."""
    import auth.garmin as garmin_auth

    if date.fromisoformat(workout["date"]) < date.today():
        raise WorkoutError("That workout is in the past.")
    try:
        api = garmin_auth._client()
        if workout.get("garmin_workout_id"):
            # Replace the copy we sent before rather than leaving two on the calendar.
            try:
                api.delete_workout(workout["garmin_workout_id"])
            except Exception:
                pass  # it may already be gone from Garmin
        created = api.upload_workout(to_garmin_json(workout, steps))
        workout_id = created.get("workoutId")
        if not workout_id:
            raise WorkoutError("Garmin didn't return an id for the new workout.")
        scheduled = api.schedule_workout(workout_id, workout["date"])
    except WorkoutError:
        raise
    except Exception as e:
        raise WorkoutError(garmin_auth.friendly_error(e)) from e

    schedule_id = (scheduled or {}).get("workoutScheduleId") or (scheduled or {}).get("scheduleId")
    set_workout_garmin(workout["id"], str(workout_id), str(schedule_id) if schedule_id else None,
                       json.dumps(steps), datetime.utcnow().isoformat())


def to_fit_bytes(workout: dict, steps: list) -> bytes:
    """
    Build a standalone .fit workout file from the same steps used to send to
    Garmin, for athletes who want to import the workout somewhere else (e.g.
    TrainingPeaks accepts a manually-uploaded .fit file) instead of, or in
    addition to, sending it straight to a Garmin device.

    FIT represents a repeated interval as a flat list of steps followed by a
    trailing marker step (duration_type REPEAT_UNTIL_STEPS_CMPLT) that uses
    two separate fields: duration_step holds the message_index of the first
    step in the repeated block (i.e. which step to repeat from), and
    target_repeat_steps holds the actual repeat count. The repeated block is
    the run of steps between duration_step's index and this marker — unlike
    Garmin Connect's nested RepeatGroupDTO JSON, so this is a separate
    serializer, not a reuse of to_garmin_json's shape, even though both start
    from the same `steps`. workout.num_valid_steps must count only the real
    steps, not these repeat meta-steps (confirmed against fit_tool's own
    validator).
    """
    from fit_tool.fit_file_builder import FitFileBuilder
    from fit_tool.profile.messages.file_id_message import FileIdMessage
    from fit_tool.profile.messages.workout_message import WorkoutMessage
    from fit_tool.profile.messages.workout_step_message import WorkoutStepMessage
    from fit_tool.profile.profile_type import (Sport, Intensity, WorkoutStepDuration,
                                                WorkoutStepTarget, Manufacturer, FileType)

    ftp = _ftp()
    intensity_for = {
        "warmup": Intensity.WARMUP, "interval": Intensity.INTERVAL,
        "recovery": Intensity.RECOVERY, "cooldown": Intensity.COOLDOWN,
    }

    fit_steps: list = []
    next_index = 0
    valid_step_count = 0

    def add_step(s: dict) -> int:
        nonlocal next_index, valid_step_count
        step = WorkoutStepMessage()
        step.message_index = next_index
        step.workout_step_name = s["kind"].title()[:16]
        step.intensity = intensity_for.get(s["kind"], Intensity.ACTIVE)
        step.duration_type = WorkoutStepDuration.TIME
        step.duration_time = round(s["minutes"] * 60, 1)
        low, high = _watts(s["low_pct"], ftp), _watts(s["high_pct"], ftp)
        if low is not None:
            step.target_type = WorkoutStepTarget.POWER
            step.custom_target_power_low = int(low)
            step.custom_target_power_high = int(high)
        else:
            step.target_type = WorkoutStepTarget.OPEN
        fit_steps.append(step)
        this_index = next_index
        next_index += 1
        valid_step_count += 1
        return this_index

    for s in steps:
        if s["kind"] == "repeat":
            first_index = None
            for inner in s["repeat_steps"]:
                i = add_step(inner)
                if first_index is None:
                    first_index = i
            # Repeat meta-step: duration_step holds the index of the first
            # step in the repeated block, and target_repeat_steps holds the
            # repeat count. Not counted in num_valid_steps (see docstring).
            marker = WorkoutStepMessage()
            marker.message_index = next_index
            marker.duration_type = WorkoutStepDuration.REPEAT_UNTIL_STEPS_CMPLT
            marker.duration_step = first_index
            marker.target_type = WorkoutStepTarget.OPEN
            marker.target_repeat_steps = s["repeat_count"]
            fit_steps.append(marker)
            next_index += 1
        else:
            add_step(s)

    file_id = FileIdMessage()
    file_id.type = FileType.WORKOUT
    file_id.manufacturer = Manufacturer.DEVELOPMENT.value
    file_id.product = 0
    file_id.time_created = round(datetime.utcnow().timestamp() * 1000)
    file_id.serial_number = 0x1E4C7

    workout_msg = WorkoutMessage()
    workout_msg.workout_name = workout["name"][:40]
    workout_msg.sport = Sport.CYCLING
    workout_msg.num_valid_steps = valid_step_count

    builder = FitFileBuilder(auto_define=True, min_string_size=50)
    builder.add(file_id)
    builder.add(workout_msg)
    builder.add_all(fit_steps)
    return builder.build().to_bytes()


def remove_from_garmin(workout: dict) -> None:
    """Delete the copy of this workout we sent to Garmin, if any. Best effort."""
    if not workout.get("garmin_workout_id"):
        return
    import auth.garmin as garmin_auth
    try:
        garmin_auth._client().delete_workout(workout["garmin_workout_id"])
    except Exception:
        pass
