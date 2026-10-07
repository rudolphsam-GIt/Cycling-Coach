"""
Export your plan: every planned ride in a date range to TrainingPeaks, Zwift and Garmin.

Each ride's steps are built once (garmin_workouts.ensure_steps) and saved, then reused by every
route here, the Garmin send and the single .fit download.

  Download for TrainingPeaks   .zwo files titled with their dates, for the TrainingPeaks library
  Download all files           .zwo, .fit, plan.csv and how to import
  Sync to intervals.icu        dated, on to Zwift on every computer and to Garmin (official API)
  Send to TrainingPeaks        dated on the TrainingPeaks calendar (unofficial, off unless turned on)
"""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

import exporters
import garmin_workouts
import programs
from auth import intervals, trainingpeaks
from db.queries import get_workouts

RANGE_KEY = "export_range"
MSG_KEY = "export_msg"
ERR_KEY = "export_errors"
WEEK, FOUR, TWELVE, PROGRAM, CUSTOM = "This week", "Next 4 weeks", "Next 12 weeks", "This program", "Custom dates"


def choose_program_range() -> None:
    """Open the panel on the active program's dates (for the program card's Export button)."""
    st.session_state[RANGE_KEY] = PROGRAM


def date_range(choice: str, today: date, program: dict | None, custom=None) -> tuple[str, str]:
    """The first and last day for a range choice. Nothing before today is exported."""
    if choice == PROGRAM and program:
        start = max(date.fromisoformat(program["start_date"]), today)
        return start.isoformat(), program["end_date"]
    if choice == CUSTOM and custom and len(custom) == 2:
        return max(custom[0], today).isoformat(), custom[1].isoformat()
    if choice == WEEK:
        return today.isoformat(), (today + timedelta(days=6 - today.weekday())).isoformat()
    days = {FOUR: 28, TWELVE: 84}.get(choice, 28)
    return today.isoformat(), (today + timedelta(days=days - 1)).isoformat()


def phase_notes(program: dict, start: str, end: str) -> list[dict]:
    """A note on intervals.icu where each phase of the program begins."""
    out, seen = [], set()
    for w in programs.week_plan(program):
        if w["phase"] in seen:
            continue
        seen.add(w["phase"])
        if start <= w["start"] <= end:
            p = next(p for p in program["phases"] if p["name"] == w["phase"])
            out.append(intervals.note_payload(w["start"], f"{program['title']} · {p['name']}",
                                              f"{p['focus']} {p['why']}", f"cc-phase-{program['id']}-{w['week']}"))
    return out


def group_failures(rides: list[dict], errors: dict) -> dict[str, list[str]]:
    """{reason: ["Oct 7 Endurance", ...]} for rides whose steps couldn't be built, so one problem
    (such as a bad API key) is said once rather than once per ride."""
    out: dict[str, list[str]] = {}
    for w in rides:
        if w["id"] in errors and garmin_workouts.saved_steps(w) is None:
            out.setdefault(errors[w["id"]], []).append(f"{programs.day_label(w['date'])} {w['name']}")
    return out


def _show_message() -> None:
    msg = st.session_state.pop(MSG_KEY, None)
    if msg:
        {"ok": st.success, "warn": st.warning, "err": st.error}[msg[0]](msg[1])


def render(today: date | None = None) -> None:
    today = today or date.today()
    program = programs.load("active")
    with st.container(border=True):
        st.markdown("**Export your plan** · to TrainingPeaks, Zwift and Garmin")
        options = [WEEK, FOUR, TWELVE] + ([PROGRAM] if program else []) + [CUSTOM]
        if st.session_state.get(RANGE_KEY) not in options:
            st.session_state[RANGE_KEY] = PROGRAM if program else FOUR
        choice = st.segmented_control("Which rides", options, key=RANGE_KEY, required=True,
                                      label_visibility="collapsed")
        custom = None
        if choice == CUSTOM:
            custom = st.date_input("From and to", value=(today, today + timedelta(days=27)), min_value=today,
                                   key="export_custom")
        start, end = date_range(choice, today, program, custom)
        rides = [w for w in get_workouts(start, end) if not w.get("completed")]
        missing = [w for w in rides if garmin_workouts.saved_steps(w) is None]
        span = programs.span_label(start, end)
        if not rides:
            st.caption(f"No planned rides from {span}.")
            _show_message()
            return
        st.caption(f"{len(rides)} planned ride{'s' if len(rides) != 1 else ''} from {span}.")

        if missing:
            st.caption(f"{len(missing)} still need their steps worked out (warm up, intervals, cool down). "
                       "Your coach does this once per workout, a few at a time, and the result is kept.")
            if st.button(f"Prepare steps for {len(missing)} ride{'s' if len(missing) != 1 else ''}",
                         type="primary", icon=":material/build:", key="export_prepare"):
                bar = st.progress(0.0, text="Working out the steps…")
                try:
                    out = garmin_workouts.ensure_steps(
                        missing, progress=lambda d, t: bar.progress(d / t, text=f"Worked out {d} of {t}…"))
                except garmin_workouts.WorkoutError as e:
                    st.session_state[MSG_KEY] = ("err", str(e))
                else:
                    st.session_state[ERR_KEY] = {w["id"]: out[w["id"]] for w in missing
                                                 if isinstance(out.get(w["id"]), str)}
                st.rerun()

        errors = st.session_state.get(ERR_KEY) or {}
        rows = [(w, steps) for w in rides if (steps := garmin_workouts.saved_steps(w)) is not None]
        for why, names in group_failures(rides, errors).items():
            if len(names) == 1:
                st.warning(f"{names[0]} was left out. {why}")
            else:
                st.warning(f"{len(names)} rides were left out ({', '.join(names[:4])}"
                           f"{', and more' if len(names) > 4 else ''}). {why}")
        _show_message()
        if not rows:
            return
        if len(rows) < len(rides):
            st.caption(f"{len(rows)} of {len(rides)} rides are ready. The rest are left out until their steps "
                       "are worked out.")

        folder = program["title"] if choice == PROGRAM and program else f"Plan {span}"
        c1, c2 = st.columns(2)
        c1.download_button("Download for TrainingPeaks", data=lambda: exporters.trainingpeaks_zip(rows, folder),
                           file_name=f"{exporters.slug(folder)}_trainingpeaks.zip", mime="application/zip",
                           icon=":material/download:", width="stretch", on_click="ignore",
                           help="Zwift workout files with the date in each title. Import them all into one "
                                "TrainingPeaks library folder, then drag each onto its day.")
        c2.download_button("Download all files", data=lambda: exporters.all_files_zip(rows, folder),
                           file_name=f"{exporters.slug(folder)}_workouts.zip", mime="application/zip",
                           icon=":material/folder_zip:", width="stretch", on_click="ignore",
                           help="Zwift and TrainingPeaks (.zwo), Garmin and Wahoo (.fit), a list of the plan "
                                "and how to import each.")

        s1, s2 = st.columns(2)
        if intervals.is_connected():
            if s1.button("Sync to intervals.icu", icon=":material/cloud_upload:", width="stretch",
                         key="export_intervals",
                         help="Puts each ride on its date in intervals.icu, which passes them to Zwift on every "
                              "computer and to Garmin. Run it again after changes."):
                notes = phase_notes(program, start, end) if choice == PROGRAM and program else []
                with st.spinner("Sending to intervals.icu…"):
                    try:
                        out = intervals.sync(rows, start, end, notes)
                    except intervals.IntervalsError as e:
                        st.session_state[MSG_KEY] = ("err", str(e))
                    else:
                        gone = f" Took off {out['removed']} you removed." if out["removed"] else ""
                        st.session_state[MSG_KEY] = (
                            "ok", f"Synced {out['sent']} rides to intervals.icu.{gone} In Zwift they appear "
                                  "under Custom Workouts, intervals.icu, on their days.")
                st.rerun()
        else:
            s1.caption("Connect intervals.icu in Settings to get these into Zwift on their dates, on any computer.")
        if trainingpeaks.is_enabled():
            if s2.button("Send to TrainingPeaks calendar", icon=":material/event_upcoming:", width="stretch",
                         key="export_tp",
                         help="Puts each ride on its date in TrainingPeaks. Uses TrainingPeaks' website, not an "
                              "official API, so it may stop working."):
                with st.spinner("Sending to TrainingPeaks…"):
                    try:
                        out = trainingpeaks.sync(rows, start, end)
                    except trainingpeaks.TPError as e:
                        st.session_state[MSG_KEY] = ("err", str(e))
                    else:
                        bits = [f"Sent {out['sent']} rides to TrainingPeaks"]
                        if out["unchanged"]:
                            bits.append(f"{out['unchanged']} were already up to date")
                        if out["removed"]:
                            bits.append(f"took off {out['removed']} you removed")
                        text = ", ".join(bits) + "."
                        if out["failed"]:
                            text += " Couldn't send " + "; ".join(f"{f['name']} ({f['why']})" for f in out["failed"])
                        st.session_state[MSG_KEY] = ("warn" if out["failed"] else "ok", text)
                st.rerun()
        else:
            s2.caption("To put rides straight onto your TrainingPeaks calendar, turn it on in Settings.")
