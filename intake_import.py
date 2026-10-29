"""
Reads the intake form's response sheet (File, Download, CSV in Google Sheets) and turns each
response into the answers the Add athlete form saves with. Nothing is saved here. Sam checks the
answers on Add athlete first, so anything the importer can't use goes in notes instead of failing.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime

import planning
from intake_form import DAY_NAMES, FTP_TEST_CHOICES, QUESTIONS, UNIT_CHOICES
from metrics.explain import DEFAULT_GENDER, GENDER_LABELS
from metrics.units import to_kg

BY_TITLE = {q.title: q for q in QUESTIONS}
BY_KEY = {q.key: q for q in QUESTIONS}

# The same limits as the weight box on Add athlete, so a prefilled value always fits.
WEIGHT_KG_MIN, WEIGHT_KG_MAX = 30.0, 200.0


@dataclass
class Intake:
    submitted: str                  # the sheet's Timestamp, as written
    answers: dict                   # for athlete_form.save_athlete. ftp_choice None means Sam picks
    extras: dict                    # every answer by question key, as the rider gave it
    flags: list[str] = field(default_factory=list)    # health answers the coach must see
    notes: list[str] = field(default_factory=list)    # what the importer changed or couldn't use

    @property
    def name(self) -> str:
        return self.answers["name"]


def read_responses(data: bytes | str) -> list[Intake]:
    """Every response in the downloaded sheet, newest first. Raises ValueError when the file
    isn't this form's responses."""
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    reader = csv.DictReader(io.StringIO(text))
    if BY_KEY["name"].title not in {(h or "").strip() for h in reader.fieldnames or []}:
        raise ValueError("This doesn't look like the intake form's responses. Download the response "
                         "sheet from Google Sheets with File, Download, CSV.")
    out = [parse_row(r) for r in reader if (r.get(BY_KEY["name"].title) or "").strip()]
    return sorted(out, key=lambda i: _timestamp(i.submitted), reverse=True)


def parse_row(row: dict, today: date | None = None) -> Intake:
    today = today or date.today()
    extras = {}
    for title, cell in row.items():
        q = BY_TITLE.get((title or "").strip())
        if q and (cell or "").strip():
            extras[q.key] = cell.strip()
    intake = Intake(submitted=(row.get("Timestamp") or "").strip(), answers={}, extras=extras)
    intake.answers = _answers(extras, intake.notes, today)
    intake.flags = health_flags(extras)
    return intake


def _answers(x: dict, notes: list[str], today: date) -> dict:
    unit, dist_unit = UNIT_CHOICES.get(x.get("units"), ("lb", "mi"))

    weight = _number(x.get("weight"))
    if weight is not None:
        kg = to_kg(weight, unit)
        if WEIGHT_KG_MIN <= kg <= WEIGHT_KG_MAX:
            weight = round(kg, 1)
        else:
            notes.append(f"Weight {x['weight']} {unit} looks wrong, so it was left blank.")
            weight = None

    ftp = _number(x.get("ftp_input"))
    ftp_choice = FTP_TEST_CHOICES.get(x.get("ftp_test"))
    if ftp_choice == "known" and not ftp:
        notes.append("They asked to use their FTP but didn't give one. Pick an FTP option.")
        ftp_choice = None

    race_date = _future(_date(x.get("race_date")), "Event date", notes, today)
    plan_start = _future(_date(x.get("plan_start")), "Plan start", notes, today)
    plan_weeks = _plan_weeks(plan_start or planning.next_monday(today), _date(x.get("plan_end")), notes)

    return {
        "name": x.get("name", ""),
        "goal_text": x.get("goal_text", ""),
        "rider_type": x.get("rider_type"),
        "activity": x.get("activity"),
        "gender": GENDER_LABELS.get(x.get("gender"), DEFAULT_GENDER),
        "age": _whole(x.get("age")),
        "weekly_hours": _whole(x.get("weekly_hours")),
        "available_days": [DAY_NAMES[d] for d in DAY_NAMES if d in x.get("available_days", "")],
        "weight": weight,
        "unit": unit,
        "dist_unit": dist_unit,
        "ftp_choice": ftp_choice,
        "ftp_input": _whole(x.get("ftp_input")),
        "lthr_input": _whole(x.get("lthr_input")),
        "max_hr": _whole(x.get("max_hr")),
        "resting_hr": _whole(x.get("resting_hr")),
        "current_ctl": _whole(x.get("current_ctl")),
        "plan_start": plan_start,
        "plan_weeks": plan_weeks,
        "race_name": x.get("race_name", ""),
        "race_date": race_date,
    }


def health_flags(x: dict) -> list[str]:
    """The health answers worth stopping for, in plain words. Empty when there are none."""
    flags = []
    if x.get("doctor_limit") == "Yes":
        flags.append("A doctor has told them to limit exercise, or that they have a heart condition.")
    if x.get("warning_signs") == "Yes":
        flags.append("They get chest pain, fainting, dizziness or a racing heartbeat when exercising. "
                     "No hard training until a doctor has seen them.")
    if x.get("hr_meds") == "Yes":
        flags.append("They take medicine that changes heart rate, so heart rate zones may not be reliable.")
    elif x.get("hr_meds") == "Not sure":
        flags.append("They aren't sure whether a medicine changes their heart rate. Check before "
                     "trusting heart rate zones.")
    if x.get("injuries"):
        flags.append(f'Injuries or pain, in their words. "{x["injuries"]}"')
    if x.get("conditions"):
        flags.append(f'Medical conditions or limits, in their words. "{x["conditions"]}"')
    return flags


def _plan_weeks(start: date, end: date | None, notes: list[str]) -> int | None:
    if not end:
        return None
    weeks = round((end - start).days / 7)
    clamped = min(max(weeks, planning.PLAN_WEEKS_MIN), planning.PLAN_WEEKS_MAX)
    if clamped != weeks:
        notes.append(f"Their plan dates give {weeks} weeks, so it was set to {clamped}, "
                     f"the nearest length the app allows.")
    return clamped


def _future(d: date | None, label: str, notes: list[str], today: date) -> date | None:
    """Add athlete only takes dates from today on, so a past one is dropped with a note."""
    if d and d < today:
        notes.append(f"{label} {d:%b %-d, %Y} has passed, so it was left blank.")
        return None
    return d


def _date(s: str | None) -> date | None:
    """Google Sheets writes dates in the sheet's locale. ISO and US month first are both read."""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime((s or "").strip(), fmt).date()
        except ValueError:
            pass
    return None


def _timestamp(s: str) -> datetime:
    for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return datetime.min


def _number(s: str | None) -> float | None:
    try:
        return float((s or "").replace(",", "").strip())
    except ValueError:
        return None


def _whole(s: str | None) -> int | None:
    n = _number(s)
    return int(round(n)) if n is not None else None
