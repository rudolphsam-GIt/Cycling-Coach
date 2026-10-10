"""
Workout files for other apps, built from the same saved steps as the Garmin send.

to_zwo        a Zwift workout (.zwo), which TrainingPeaks also imports into its Workout Library
file_base     "2026-10-12_Tempo_blocks", so files sort by date
dated_title   "2026-10-12 Tempo blocks", the title inside a file, so a library lists in date order
plan_ics      the plan as a calendar file (.ics)
*_zip         a whole plan in one download, share_package_zip being the one to send to someone else

Steps are the shape garmin_workouts.check_steps returns: warmup, interval, recovery and cooldown
steps with a power range in percent of FTP (or none), and repeat steps holding a list of those.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime, timedelta, timezone
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


# ── Calendar file ─────────────────────────────────────────────────────────────

def _ics_text(value) -> str:
    """Escape text for an iCalendar value (RFC 5545 section 3.3.11)."""
    s = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Fold a content line at 75 octets, never splitting a UTF-8 character. Each continuation
    line starts with one space, which counts toward its 75."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > 75:
            out.append(cur)
            cur, size = " ", 1
        cur += ch
        size += n
    out.append(cur)
    return "\r\n".join(out)


def _watt_range(step: dict, ftp: float) -> str:
    from garmin_workouts import _watts
    lo, hi = step.get("low_pct"), step.get("high_pct")
    if lo is None:
        return "no power target"
    if lo == hi:
        return f"{_watts(lo, ftp):g} W ({lo:g}% FTP)"
    return f"{_watts(lo, ftp):g} to {_watts(hi, ftp):g} W ({lo:g} to {hi:g}% FTP)"


STEP_LABEL = {"warmup": "Warm up", "cooldown": "Cool down", "recovery": "Easy", "interval": "Ride"}


def _leaf_text(step: dict, ftp: float, in_repeat: bool = False) -> str:
    mins = f"{step['minutes']:g} min"
    if in_repeat:
        # "4 rounds of 5 min at 228 to 252 W, then 3 min easy at ..." reads better than labels.
        mins += " easy" if step["kind"] == "recovery" else ""
        if step.get("low_pct") is None:
            return f"{mins} with no power target"
        return f"{mins} at {_watt_range(step, ftp)}"
    label = STEP_LABEL.get(step["kind"], "Ride")
    if step.get("low_pct") is None:
        return f"{label} {mins} with no power target"
    return f"{label} {mins} at {_watt_range(step, ftp)}"


def step_lines(steps: list, ftp: float, main_only: bool = False) -> list[str]:
    """Plain sentences for the steps in watts and percent of FTP. With main_only the warm up,
    cool down and easy parts are left out (unless nothing else is left)."""
    def one(s):
        if s["kind"] == "repeat":
            inner = ", then ".join(_leaf_text(x, ftp, in_repeat=True) for x in s["repeat_steps"])
            return f"{s['repeat_count']} rounds of {inner}"
        return _leaf_text(s, ftp)
    keep = [s for s in steps if not main_only or s["kind"] in ("interval", "repeat")]
    return [one(s) for s in (keep or steps)]


def plan_ics(rows: list[tuple[dict, list]], athlete_name: str = "", ftp: float | None = None) -> str:
    """The plan as an iCalendar file with one all day event per workout. The event text says what
    the ride is for, how long it is, the planned load and, when `ftp` is known, the steps in watts."""
    from garmin_workouts import total_minutes
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    who = (athlete_name or "").strip()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Cycling Coach//Training plan//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{_ics_text(f'{who} training plan' if who else 'Training plan')}"]
    for workout, steps in rows:
        day = date.fromisoformat(workout["date"])
        purpose = (workout.get("purpose") or "").strip()
        if purpose and purpose[-1] not in ".!?":
            purpose += "."
        facts = [purpose, f"{round(total_minutes(steps))} minutes."]
        if workout.get("tss_planned"):
            facts.append(f"Planned training load {round(workout['tss_planned'])} TSS.")
        if workout.get("feel"):
            feel = workout["feel"].strip().rstrip(".")
            facts.append(f"It should feel {feel[:1].lower()}{feel[1:]}.")
        text = " ".join(x for x in facts if x)
        if ftp:
            text += "\n\n" + "\n".join(step_lines(steps, ftp))
        lines += ["BEGIN:VEVENT",
                  f"UID:cc-{workout['id']}-{workout['date']}@cycling-coach",
                  f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
                  f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
                  f"SUMMARY:{_ics_text(workout.get('name') or 'Workout')}",
                  f"DESCRIPTION:{_ics_text(text)}",
                  "TRANSP:TRANSPARENT",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "".join(_fold(x) + "\r\n" for x in lines)


# ── How to import ─────────────────────────────────────────────────────────────

# Each section is (heading, lines), plain sentences. {folder} is the TrainingPeaks library folder
# to suggest. Only what the apps' own help pages confirm is said here. TrainingPeaks .fit import,
# which plans sync to devices, and Forerunner file copy are left out on purpose.
GUIDE = {
    "zwift": ("Zwift", [
        "Do this on a computer. The Zwift app on iPhone or Apple TV cannot import files.",
        "1. Copy the files from the zwo folder.",
        "2. On a Mac, paste them into Documents > Zwift > Workouts > the folder named with your Zwift number. "
        "On Windows the place is Documents\\Zwift\\Workouts\\your Zwift number.",
        "3. Restart Zwift. The workouts are under Custom Workouts, and they show on your other devices too."]),
    "trainingpeaks": ("TrainingPeaks", [
        "TrainingPeaks imports .zwo files only, so use the zwo folder.",
        "1. Open the Workout Library and make a folder, for example {folder}.",
        "2. Open the three dot menu on that folder, choose Import Workout, and pick the zwo files.",
        "3. Each title starts with its date. Drag every workout onto the day in its title.",
        "A free Basic account can keep only 5 workouts in its library, so a whole plan needs a Premium account."]),
    "garmin": ("Garmin", [
        "Garmin Connect has no way to import workout files. If you upload a .fit file there it is treated "
        "as a ride you already did, so please do not.",
        "The reliable way is to bring the workouts into TrainingPeaks or intervals.icu, which send them to your "
        "Garmin Connect calendar and on to your device.",
        "For a Garmin Edge bike computer you can also plug it in with a USB cable, copy the files from the fit "
        "folder into GARMIN > NewFiles, eject it, then look under Training > Workouts. This varies by "
        "model. We have not confirmed it for Forerunner watches."]),
    "wahoo": ("Wahoo", [
        "Wahoo does not describe a way to put workout files straight on a device. Use intervals.icu "
        "(Settings > Connections > Wahoo) or TrainingPeaks, and they send the workouts for you."]),
    "intervals": ("intervals.icu", [
        "Import the files from the fit folder into the Workout Library, then drag each onto its day on the calendar.",
        "Once Garmin or Wahoo is connected, intervals.icu passes the workouts on to your device."]),
    "calendar": ("The calendar file", [
        "plan.ics shows every ride as an all day event with its details, so you can see the plan next to the "
        "rest of your life. It does not load workouts onto a device.",
        "Apple Calendar on a Mac. Choose File > Import, or double click the file. On an iPhone, open it from "
        "Mail or Files and tap Add All.",
        "Google Calendar. Use a computer, not the phone app. Open Settings > Import & export > Import.",
        "Outlook on a computer. Choose File > Open & Export > Import/Export > Import an iCalendar file."]),
}

CONTENTS = [
    "Plan.pdf is the plan on paper, week by week.",
    "The zwo folder has one Zwift workout file per ride. Zwift and TrainingPeaks both read these.",
    "The fit folder has the same rides as .fit files, for intervals.icu and some Garmin Edge bike computers.",
    "plan.ics puts every ride on a calendar. plan.csv lists them for a spreadsheet.",
]


def guide_sections(folder: str = "Cycling Coach plan", only: tuple = ()) -> list[tuple[str, list[str]]]:
    return [(h, [l.replace("{folder}", folder) for l in lines])
            for key, (h, lines) in GUIDE.items() if not only or key in only]


def guide_text(folder: str = "Cycling Coach plan", contents: list[str] | None = None, only: tuple = ()) -> str:
    out = ["How to import this plan", ""]
    if contents:
        out += ["What is in the folder", *[f"  {c}" for c in contents], ""]
    for heading, lines in guide_sections(folder, only):
        out += [heading, *[f"  {l}" for l in lines], ""]
    return "\n".join(out)


HOW_TO = guide_text("{folder}", only=("zwift", "trainingpeaks"))      # for the TrainingPeaks zip


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


def trainingpeaks_zip(rows: list[tuple[dict, list]], folder: str = "Cycling Coach plan") -> bytes:
    """Only the .zwo files, titled with their dates, plus the how to."""
    buf, used = io.BytesIO(), set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for workout, steps in rows:
            zf.writestr(_unique(f"{file_base(workout)}.zwo", used),
                        to_zwo(workout, steps, dated_title(workout)))
        zf.writestr("HOW_TO_IMPORT.txt", HOW_TO.replace("{folder}", folder))
    return buf.getvalue()


def _write_workouts(zf: zipfile.ZipFile, rows: list, prefix: str = "") -> None:
    """zwo/ and fit/ files for each ride, named by date, under `prefix`."""
    from garmin_workouts import to_fit_bytes
    used: set = set()
    for workout, steps in rows:
        base = file_base(workout)
        zf.writestr(_unique(f"{prefix}zwo/{base}.zwo", used), to_zwo(workout, steps, dated_title(workout)))
        zf.writestr(_unique(f"{prefix}fit/{base}.fit", used), to_fit_bytes(workout, steps))


def all_files_zip(rows: list[tuple[dict, list]], folder: str = "Cycling Coach plan") -> bytes:
    """zwo/ for Zwift and TrainingPeaks, fit/ for Garmin and others, plan.csv and the how to."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        _write_workouts(zf, rows)
        zf.writestr("plan.csv", plan_csv(rows))
        zf.writestr("HOW_TO_IMPORT.txt", guide_text(folder, CONTENTS[1:3]))
    return buf.getvalue()


def share_package_zip(rows: list[tuple[dict, list]], athlete_name: str = "", ftp: float | None = None,
                      program: dict | None = None, ctl_by_week: dict | None = None) -> bytes:
    """One folder to send to an athlete: the plan on paper, a one page import guide, the same guide
    as text, the calendar file, the spreadsheet, and the zwo and fit workouts."""
    import program_pdf
    who = re.sub(r"[\\/:*?\"<>|]+", " ", (athlete_name or "").strip()).strip()
    folder = f"{who} training plan" if who else "Training plan"
    prefix = f"{folder}/"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{prefix}Plan.pdf", program_pdf.schedule_pdf(rows, who, ftp, program, ctl_by_week))
        zf.writestr(f"{prefix}How to import.pdf", program_pdf.import_guide_pdf(folder, CONTENTS))
        zf.writestr(f"{prefix}HOW_TO_IMPORT.txt", guide_text(folder, CONTENTS))
        zf.writestr(f"{prefix}plan.ics", plan_ics(rows, who, ftp))
        zf.writestr(f"{prefix}plan.csv", plan_csv(rows))
        _write_workouts(zf, rows, prefix)
    return buf.getvalue()
