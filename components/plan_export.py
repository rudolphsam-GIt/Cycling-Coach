"""
Export your plan: every planned ride in a date range to TrainingPeaks, Zwift and Garmin.

Each ride's steps are built once (garmin_workouts.ensure_steps) and saved, then reused by every
route here, the Garmin send and the single .fit download.

  Download for TrainingPeaks   .zwo files titled with their dates, for the TrainingPeaks library
  Download all files           .zwo, .fit, plan.csv and how to import
  Share package                one folder to send an athlete: plan PDF, import guide, calendar file and workouts
  Sync to intervals.icu        dated, on to Zwift on every computer and to Garmin (official API)
  TrainingPeaks calendar       synced on its own once signed in (unofficial, needs Premium)
"""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

import exporters
import garmin_workouts
import programs
from auth import intervals, trainingpeaks
from db.queries import get_setting, get_workouts
from metrics.training_load import get_current_metrics

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


def share_package(rows: list, folder_program: dict | None) -> bytes:
    """The zip to send an athlete. `folder_program` is the active program when the range is the
    program, so its full PDF leads the plan."""
    ftp = float(get_setting("ftp_watts", 0) or 0)
    ctl = None
    if folder_program:
        m = get_current_metrics()
        ctl = programs.weekly_ctl(folder_program, programs.projected_fitness(folder_program, m["ctl"], m["atl"]))
    return exporters.share_package_zip(rows, get_setting("athlete_name", "") or "", ftp, folder_program, ctl)


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
        c1, c2, c3 = st.columns(3)
        c1.download_button("Download for TrainingPeaks", data=lambda: exporters.trainingpeaks_zip(rows, folder),
                           file_name=f"{exporters.slug(folder)}_trainingpeaks.zip", mime="application/zip",
                           icon=":material/download:", width="stretch", on_click="ignore",
                           help="For free TrainingPeaks accounts. Zwift workout files with the date in each "
                                "title. Import them all into one TrainingPeaks library folder, then drag each "
                                "onto its day.")
        c2.download_button("Download all files", data=lambda: exporters.all_files_zip(rows, folder),
                           file_name=f"{exporters.slug(folder)}_workouts.zip", mime="application/zip",
                           icon=":material/folder_zip:", width="stretch", on_click="ignore",
                           help="Zwift and TrainingPeaks (.zwo), Garmin and Wahoo (.fit), a list of the plan "
                                "and how to import each.")
        has_ftp = float(get_setting("ftp_watts", 0) or 0) > 0
        c3.download_button("Share package", data=lambda: share_package(rows, program if choice == PROGRAM else None),
                           file_name=f"{exporters.slug(folder)}_share.zip", mime="application/zip",
                           icon=":material/send:", width="stretch", on_click="ignore", disabled=not has_ftp,
                           help="One zip to send to someone else. It has the plan as a PDF, a one page guide to "
                                "importing it, a calendar file, and the workout files." if has_ftp else
                                "Set your FTP in Settings first, so power targets can be worked out.")

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
                        intervals.start_background_compare()    # its scores, to check the app's against
                        gone = f" Took off {out['removed']} you removed." if out["removed"] else ""
                        st.session_state[MSG_KEY] = (
                            "ok", f"Synced {out['sent']} rides to intervals.icu.{gone} In Zwift they appear "
                                  "under Custom Workouts, intervals.icu, on their days.")
                st.rerun()
        else:
            s1.caption("Connect intervals.icu in Settings to get these into Zwift on their dates, on any computer.")
        with s2:
            tp_status()


def tp_status(key: str = "export_tp", invite: bool = True) -> None:
    """One line on the TrainingPeaks calendar sync, with Sync now. Also used on the Plan calendar,
    where `invite` is off so riders who don't use TrainingPeaks see nothing."""
    if not trainingpeaks.is_enabled():
        if invite:
                st.caption("Have TrainingPeaks Premium? Sign in from Settings and your rides go onto your "
                       "TrainingPeaks calendar on their own.")
        return
    if trainingpeaks.needs_signin():
        st.caption("TrainingPeaks signed you out, so syncing has paused.")
        st.page_link("pages/07_Settings.py", label="Sign in to TrainingPeaks again", icon=":material/login:")
        return
    if trainingpeaks.is_syncing():
        st.caption("Syncing to TrainingPeaks in the background…")
        return
    line, btn = st.columns([3, 1.3], vertical_alignment="center")
    line.caption(f"TrainingPeaks syncs on its own. {trainingpeaks.last_sync_text()}.")
    if btn.button("Sync now", key=f"{key}_now", icon=":material/sync:", width="stretch",
                  help="Send every upcoming ride to your TrainingPeaks calendar now"):
        with st.spinner("Sending to TrainingPeaks…"):
            try:
                ran = trainingpeaks.run_locked()
            except trainingpeaks.TPError:
                ran = True      # recorded as the last result, which the app shows as a toast
        if ran is None:
            st.toast("A sync is already running. It will finish on its own.")
        st.rerun()
