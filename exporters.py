"""
Workout files for other apps, built from the same saved steps as the Garmin send.

to_zwo        a Zwift workout (.zwo), which TrainingPeaks also imports into its Workout Library
file_base     "2026-10-12_Tempo_blocks", so files sort by date
dated_title   "2026-10-12 Tempo blocks", the title inside a file, so a library lists in date order
*_zip         a whole plan in one download

Steps are the shape garmin_workouts.check_steps returns: warmup, interval, recovery and cooldown
steps with a power range in percent of FTP (or none), and repeat steps holding a list of those.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from xml.sax.saxutils import escape, quoteattr

OPEN_POWER = 0.5          # a step with no power target rides at half of FTP in ERG mode


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name or "").strip("_") or "workout"


def file_base(workout: dict) -> str:
    return f"{workout['date']}_{slug(workout.get('name') or 'workout')}"


def dated_title(workout: dict) -> str:
    return f"{workout['date']} {workout.get('name') or 'Workout'}"


def _frac(pct) -> float | None:
    return None if pct is None else round(pct / 100, 4)


def _mid(step: dict) -> float | None:
    lo, hi = step.get("low_pct"), step.get("high_pct")
    return None if lo is None else round((lo + hi) / 200, 4)


def _secs(step: dict) -> int:
    return max(1, round(step["minutes"] * 60))


def _step_xml(step: dict, text: str | None = None) -> str:
    """One Zwift element. Warm up and cool down are ramps; the rest are steady."""
    kind, dur = step["kind"], _secs(step)
    lo, hi = _frac(step.get("low_pct")), _frac(step.get("high_pct"))
    event = f'<textevent timeoffset="0" message={quoteattr(text[:120])}/>' if text else ""
    if kind == "warmup" and lo is not None:
        tag = f'<Warmup Duration="{dur}" PowerLow="{lo}" PowerHigh="{hi}" pace="0"'
    elif kind == "cooldown" and lo is not None:
        # Zwift's cool down runs from PowerLow at the start to PowerHigh at the end
        tag = f'<Cooldown Duration="{dur}" PowerLow="{hi}" PowerHigh="{lo}" pace="0"'
    elif lo is None:
        tag = f'<FreeRide Duration="{dur}" FlatRoad="1"'
    else:
        tag = f'<SteadyState Duration="{dur}" Power="{_mid(step)}" pace="0"'
    return f"{tag}>{event}</{tag[1:tag.index(' ')]}>" if event else f"{tag}/>"


def _repeat_xml(step: dict) -> list[str]:
    inner, count = step["repeat_steps"], step["repeat_count"]
    if len(inner) == 2 and all(s.get("low_pct") is not None for s in inner):
        on, off = inner
        return [f'<IntervalsT Repeat="{count}" OnDuration="{_secs(on)}" OffDuration="{_secs(off)}" '
                f'OnPower="{_mid(on)}" OffPower="{_mid(off)}" pace="0"/>']
    return [_step_xml({**s, "kind": "interval" if s["kind"] in ("warmup", "cooldown") else s["kind"]})
            for _ in range(count) for s in inner]


def to_zwo(workout: dict, steps: list, title: str | None = None) -> str:
    """The workout as a Zwift .zwo file. The feel cue shows as a message at the start of the
    first hard part, and the description carries what it is for and how it should feel."""
    about = " ".join(x for x in (workout.get("purpose"), workout.get("feel") and f"Feel. {workout['feel']}",
                                 workout.get("description")) if x)
    cue = workout.get("feel")
    body, cued = [], False
    for s in steps:
        if s["kind"] == "repeat":
            body.extend(_repeat_xml(s))
        else:
            text = cue if cue and not cued and s["kind"] == "interval" else None
            cued = cued or bool(text)
            body.append(_step_xml(s, text))
    lines = ["<workout_file>",
             "    <author>Cycling Coach</author>",
             f"    <name>{escape(title or workout.get('name') or 'Workout')}</name>",
             f"    <description>{escape(about)}</description>",
             "    <sportType>bike</sportType>",
             "    <tags/>",
             "    <workout>",
             *[f"        {b}" for b in body],
             "    </workout>",
             "</workout_file>", ""]
    return "\n".join(lines)


def _unique(name: str, used: set) -> str:
    base, ext = name.rsplit(".", 1)
    out, n = name, 2
    while out in used:
        out, n = f"{base}_{n}.{ext}", n + 1
    used.add(out)
    return out


def plan_csv(rows: list[tuple[dict, list]]) -> str:
    from garmin_workouts import total_minutes
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "name", "type", "minutes", "tss", "purpose", "feel"])
    for workout, steps in rows:
        w.writerow([workout["date"], workout.get("name"), workout.get("workout_type"),
                    round(total_minutes(steps)), round(workout.get("tss_planned") or 0),
                    workout.get("purpose") or "", workout.get("feel") or ""])
    return buf.getvalue()


HOW_TO = """How to use these files

TrainingPeaks (the zwo folder)
1. In TrainingPeaks open the Workout Library and make a folder, for example {folder}.
2. Open the menu next to that folder, choose Import, and select every file in the zwo folder at once.
3. Each workout title starts with its date, so the folder lists them in order. Drag each one onto
   the day in its title. Warm ups and cool downs become stepped ramps, which is normal.

Zwift (the zwo folder)
Copy the files into Documents/Zwift/Workouts/<your Zwift number> and restart Zwift. They show under
Custom Workouts. For workouts on their dates on every Zwift computer, sync the plan to intervals.icu
or the TrainingPeaks calendar from the app instead, and link that service to Zwift.

Garmin, Wahoo and others (the fit folder)
Each .fit file is a structured workout with power targets from your FTP. Copy it to your bike
computer or import it in the app that came with it.

plan.csv lists every workout with its date, length, training load, purpose and feel.
"""


def trainingpeaks_zip(rows: list[tuple[dict, list]], folder: str = "Cycling Coach plan") -> bytes:
    """Only the .zwo files, titled with their dates, plus the how to."""
    buf, used = io.BytesIO(), set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for workout, steps in rows:
            zf.writestr(_unique(f"{file_base(workout)}.zwo", used),
                        to_zwo(workout, steps, dated_title(workout)))
        zf.writestr("HOW_TO_IMPORT.txt", HOW_TO.format(folder=folder))
    return buf.getvalue()


def all_files_zip(rows: list[tuple[dict, list]], folder: str = "Cycling Coach plan") -> bytes:
    """zwo/ for Zwift and TrainingPeaks, fit/ for Garmin and others, plan.csv and the how to."""
    from garmin_workouts import to_fit_bytes
    buf, used = io.BytesIO(), set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for workout, steps in rows:
            base = file_base(workout)
            zf.writestr(_unique(f"zwo/{base}.zwo", used), to_zwo(workout, steps, dated_title(workout)))
            zf.writestr(_unique(f"fit/{base}.fit", used), to_fit_bytes(workout, steps))
        zf.writestr("plan.csv", plan_csv(rows))
        zf.writestr("HOW_TO_IMPORT.txt", HOW_TO.format(folder=folder))
    return buf.getvalue()
