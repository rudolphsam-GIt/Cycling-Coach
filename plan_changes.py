"""
Changes to workouts and strength sessions already on the plan: move, edit or remove.

The coach proposes them with propose_plan_changes. They are checked here, shown to
the athlete as a card with before and after, and only applied when the athlete
confirms. The same rules are checked again at apply time, because the plan may have
changed since the proposal was made.

Anything not done can be changed. That includes a workout whose day passed without it being
done (a skipped workout), which can be moved to any day. An upcoming one can't be moved into
the past, and done ones stay as they are. move_error holds that rule for the coach and the
calendar alike.
"""
from __future__ import annotations

from datetime import date

from db import queries as q

ACTIONS = ("move", "update", "remove")
RIDE_FIELDS = ("name", "workout_type", "description", "tss_planned", "purpose", "feel")
STRENGTH_FIELDS = ("name", "exercises", "duration_minutes", "purpose")
MAX_CHANGES = 40


class ChangeError(ValueError):
    """The change isn't allowed or isn't well formed. The message is written for the coach."""


def _iso(value, what: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ChangeError(f"{what} must be a date in YYYY-MM-DD form")


def _text(value, what: str, limit: int, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ChangeError(f"{what} must be a non empty string")
    if len(value.strip()) > limit:
        raise ChangeError(f"{what} must be at most {limit} characters")
    return value.strip()


def _row(target: str, item_id) -> dict | None:
    if isinstance(item_id, bool) or not isinstance(item_id, int):
        raise ChangeError("id must be the whole number id from get_planned_workouts or "
                          "get_planned_strength")
    return q.get_workout(item_id) if target == "ride" else q.get_strength_session(item_id)


def _label(target: str, row: dict) -> str:
    if target == "ride":
        return row.get("name") or "Workout"
    notes = (row.get("notes") or "").split(" | ")[0].strip()
    return notes if notes and not notes.startswith("Planned by AI Coach") else "Strength session"


def move_error(row: dict, to_iso: str, today: date, what: str = "workout") -> str | None:
    """Why `row` can't move to `to_iso`, or None when it can. Shared by the calendar and the coach."""
    if row.get("completed"):
        return f"Done {what}s stay where they are."
    if to_iso < today.isoformat() <= row["date"]:
        return f"{what.capitalize()}s can't be moved to a day that has passed."
    return None


def check_target(target: str, item_id, today: date | None = None) -> dict:
    """The stored row for something that can still be changed. Raises ChangeError when it
    doesn't exist or is done. A skipped workout from a day that has passed can still change."""
    today = today or date.today()
    row = _row(target, item_id)
    if not row:
        raise ChangeError(f"no {target} with id {item_id}. Look it up again with "
                          f"{'get_planned_workouts' if target == 'ride' else 'get_planned_strength'}")
    if row.get("completed"):
        raise ChangeError(f"'{_label(target, row)}' is already done, so it stays as it is")
    return row


def validate_change(raw: dict, today: date | None = None, workout_types: list | None = None) -> dict:
    """Check one proposed change against the plan and return it in the form the card and
    apply_changes use. Raises ChangeError with a message the coach can act on."""
    today = today or date.today()
    if not isinstance(raw, dict):
        raise ChangeError("each change must be an object")
    target, action = raw.get("target"), raw.get("action")
    if target not in ("ride", "strength"):
        raise ChangeError("target must be 'ride' or 'strength'")
    if action not in ACTIONS:
        raise ChangeError(f"action must be one of {list(ACTIONS)}")
    row = check_target(target, raw.get("id"), today)
    reason = _text(raw.get("reason"), "reason", 300)

    new_date = None
    if raw.get("new_date") is not None:
        d = _iso(raw["new_date"], "new_date")
        if (why := move_error(row, d.isoformat(), today)):
            raise ChangeError(f"new_date is not allowed. {why}")
        new_date = d.isoformat() if d.isoformat() != row["date"] else None

    fields: dict = {}
    if action == "move":
        if new_date is None:
            raise ChangeError("a move needs new_date, on a different day to the current one")
    elif action == "update":
        allowed = RIDE_FIELDS if target == "ride" else STRENGTH_FIELDS
        for key in allowed:
            if raw.get(key) is None:
                continue
            if key == "name":
                fields[key] = _text(raw[key], "name", 120)
            elif key in ("purpose", "feel"):
                fields[key] = _text(raw[key], key, 400 if key == "purpose" else 250)
            elif key == "description":
                if not isinstance(raw[key], str):
                    raise ChangeError("description must be a string")
                fields[key] = raw[key].strip()
            elif key == "workout_type":
                if workout_types is not None and raw[key] not in workout_types:
                    raise ChangeError(f"workout_type must be one of {workout_types}")
                fields[key] = raw[key]
            elif key == "tss_planned":
                v = raw[key]
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 500:
                    raise ChangeError("tss_planned must be a number from 0 to 500")
                fields[key] = float(v)
            elif key == "duration_minutes":
                v = raw[key]
                if isinstance(v, bool) or not isinstance(v, int) or not 5 <= v <= 180:
                    raise ChangeError("duration_minutes must be a whole number from 5 to 180")
                fields[key] = v
            elif key == "exercises":
                ex = raw[key]
                if not isinstance(ex, list) or not ex:
                    raise ChangeError("exercises must be a non empty list")
                for j, e in enumerate(ex):
                    if (not isinstance(e, dict) or not isinstance(e.get("name"), str) or not e["name"].strip()
                            or not isinstance(e.get("sets"), int) or isinstance(e.get("sets"), bool)
                            or not isinstance(e.get("reps"), str) or not e["reps"].strip()
                            or not isinstance(e.get("intensity"), str) or not e["intensity"].strip()):
                        raise ChangeError(f"exercise {j} needs a name, integer sets, reps and intensity")
                fields[key] = ex
        if not fields and new_date is None:
            raise ChangeError("an update needs at least one field to change, or a new_date")
    else:  # remove
        if new_date is not None or any(raw.get(k) is not None for k in RIDE_FIELDS + STRENGTH_FIELDS):
            raise ChangeError("a remove takes no other fields")

    return {"kind": "change", "target": target, "id": raw["id"], "action": action,
            "date": row["date"], "name": _label(target, row), "reason": reason,
            "new_date": new_date, "fields": fields,
            "before": {"name": _label(target, row), "date": row["date"],
                       "workout_type": row.get("workout_type"), "tss_planned": row.get("tss_planned"),
                       "duration_minutes": row.get("duration_minutes")}}


def key(change: dict) -> tuple:
    """Identity of a change, so a newer proposal for the same item replaces an older one."""
    return ("change", change["target"], change["id"])


def _day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%a %b} {d.day}"


def describe(change: dict) -> str:
    """One plain sentence for the card."""
    name = change["name"]
    what = "strength session" if change["target"] == "strength" else "workout"
    if change["action"] == "remove":
        return f"Remove {what} {name} on {_day(change['date'])}"
    parts = []
    if change["new_date"]:
        parts.append(f"from {_day(change['date'])} to {_day(change['new_date'])}")
    f = change["fields"]
    edits = []
    if "name" in f:
        edits.append(f"rename to {f['name']}")
    if "workout_type" in f:
        edits.append(f"type {f['workout_type']}")
    if "tss_planned" in f:
        before = change["before"].get("tss_planned")
        edits.append(f"TSS {before:.0f} to {f['tss_planned']:.0f}" if before is not None
                     else f"TSS {f['tss_planned']:.0f}")
    if "duration_minutes" in f:
        edits.append(f"{f['duration_minutes']} minutes")
    if "exercises" in f:
        edits.append("new exercises")
    for k, label in (("description", "new description"), ("purpose", "new purpose"), ("feel", "new feel")):
        if k in f:
            edits.append(label)
    if change["action"] == "move" or (change["new_date"] and not edits):
        return f"Move {what} {name} " + " ".join(parts)
    text = f"Change {what} {name}: " + ", ".join(edits)
    return text + (f", moved " + parts[0] if parts else "")


def affected_date(change: dict) -> str:
    """The day to open on the calendar after applying: where the item ends up."""
    return change["new_date"] or change["date"]


def apply_changes(changes: list[dict], today: date | None = None) -> dict:
    """Apply confirmed changes. Each is checked again first. Returns counts and the
    changes that were skipped with the reason, so one bad item never blocks the rest."""
    from garmin_workouts import remove_from_garmin
    from sync import remove_everywhere

    today = today or date.today()
    done = {"moved": 0, "updated": 0, "removed": 0, "skipped": [], "first": None}
    dates = []
    for c in changes:
        try:
            row = check_target(c["target"], c["id"], today)
            new_date = c.get("new_date")
            if new_date and (why := move_error(row, new_date, today)):
                raise ChangeError(why.rstrip("."))
        except ChangeError as e:
            done["skipped"].append({"name": c.get("name"), "why": str(e)})
            continue

        if c["target"] == "ride":
            if c["action"] == "remove":
                remove_from_garmin(row)
                q.delete_workout(c["id"])
                remove_everywhere([c["id"]])
                done["removed"] += 1
                continue
            f = c["fields"]
            if f:
                q.update_workout(c["id"], {
                    "name": f.get("name", row["name"]), "workout_type": f.get("workout_type", row["workout_type"]),
                    "description": f.get("description", row.get("description") or ""),
                    "tss_planned": f.get("tss_planned", row.get("tss_planned")),
                    "completed": row.get("completed", 0), "notes": row.get("notes") or "",
                    "purpose": f.get("purpose"), "feel": f.get("feel")})
                done["updated"] += 1
            if new_date:
                old = q.move_workout(c["id"], new_date)
                if old:
                    remove_from_garmin(old)
                done["moved"] += 0 if f else 1
        else:
            if c["action"] == "remove":
                q.delete_strength_session(c["id"])
                done["removed"] += 1
                continue
            f = c["fields"]
            if f:
                q.update_strength_session(c["id"], name=f.get("name"), exercises=f.get("exercises"),
                                          duration_minutes=f.get("duration_minutes"), purpose=f.get("purpose"))
                done["updated"] += 1
            if new_date:
                q.move_strength_session(c["id"], new_date)
                done["moved"] += 0 if f else 1
        dates.append(affected_date(c))
    done["first"] = min(dates) if dates else None
    return done
