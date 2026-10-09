"""
One path for changing FTP, so every place that sets it (Settings, the FTP card, onboarding) has
the same effects:

- the new value is saved and logged in FTP history, dated today;
- past rides keep the TSS they earned on the FTP they were ridden at;
- upcoming workouts follow the new number. Their steps are stored as % of FTP so they are
  already right, but watt figures in descriptions are rescaled, and workouts already on the
  Garmin calendar are sent again in the background (their watts are fixed at send time).
"""
from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime

from db import queries as q

GARMIN_RESULT_SETTING = "garmin_ftp_resend_result"

# "265 W", "250-270 W", "250 to 270 watts", but not "3.5 W/kg"
_WATTS = re.compile(r"\b(\d{2,4})(?:(\s*(?:-|–|to)\s*)(\d{2,4}))?(\s?)(W|watts)\b(?!/)")


def _round5(watts: float) -> int:
    return int(5 * round(watts / 5))


def rescale_watts(text: str | None, ratio: float) -> str | None:
    """Scale every watt figure in the text by `ratio`, rounded to 5 W."""
    if not text or ratio == 1:
        return text

    def scale(m: re.Match) -> str:
        low = str(_round5(int(m.group(1)) * ratio))
        high = (m.group(2) + str(_round5(int(m.group(3)) * ratio))) if m.group(3) else ""
        return f"{low}{high}{m.group(4)}{m.group(5)}"

    return _WATTS.sub(scale, text)


def apply_new_ftp(new_ftp: int, note: str = "") -> dict:
    """Save a new FTP and bring the plan in line with it. Returns what changed:
    {"descriptions": n, "garmin": n workouts being resent in the background}."""
    new_ftp = int(new_ftp)
    old_ftp = float(q.get_setting("ftp_watts", 0) or 0)
    today = date.today().isoformat()
    if old_ftp > 0 and old_ftp != new_ftp and not any(h["date"] < today for h in q.ftp_history_rows()):
        # No record of the FTP rides so far were scored on, so note it first. Otherwise the new
        # value would be the earliest entry and every past ride would fall back to it.
        q.log_ftp_history(int(old_ftp), "FTP before this change",
                          day=min(q.first_activity_date() or today, today))
    q.set_setting("ftp_watts", new_ftp)
    q.log_ftp_history(new_ftp, note)
    out = {"descriptions": 0, "garmin": 0}
    if new_ftp <= 0 or old_ftp <= 0 or new_ftp == old_ftp:
        return out

    # Rides from today on are scored on the new FTP; earlier rides keep theirs.
    q.recalculate_all_tss(since=today)

    upcoming = q.get_upcoming_workouts(today)
    ratio = new_ftp / old_ftp
    updates = []
    for w in upcoming:
        text = rescale_watts(w.get("description"), ratio)
        if text != w.get("description"):
            updates.append((w["id"], text))
    q.set_workout_descriptions(updates)    # also tells TrainingPeaks the plan changed
    out["descriptions"] = len(updates)

    to_resend = [w for w in upcoming if w.get("garmin_workout_id") and w.get("structured_json")]
    if to_resend:
        start_garmin_resend([w["id"] for w in to_resend])
        out["garmin"] = len(to_resend)
    return out


_resend_lock = threading.Lock()


def resend_to_garmin(workout_ids: list[int]) -> str:
    """Send these workouts to Garmin again with their saved steps, so the watch gets the watts
    for the current FTP. No Claude calls: the steps are already built."""
    import garmin_workouts

    by_id = {w["id"]: w for w in q.get_upcoming_workouts(date.today().isoformat())}
    sent, failed = 0, []
    for wid in workout_ids:
        w = by_id.get(wid)
        if not w or not w.get("structured_json"):
            continue
        try:
            garmin_workouts.send(w, json.loads(w["structured_json"]))
            sent += 1
        except Exception as e:      # one failure shouldn't stop the rest
            failed.append(f"{w['date']} {w['name']} ({e})")
    msg = f"Updated {sent} workout{'s' if sent != 1 else ''} on your Garmin for the new FTP."
    if failed:
        msg += " Couldn't update: " + "; ".join(failed[:3]) + (" and more" if len(failed) > 3 else "")
    q.set_setting(GARMIN_RESULT_SETTING, json.dumps({"at": datetime.utcnow().isoformat(), "text": msg,
                                                     "ok": not failed}))
    return msg


def start_garmin_resend(workout_ids: list[int]) -> bool:
    """Resend on a background thread so saving FTP never waits on Garmin. False when a resend
    is already running."""
    if not _resend_lock.acquire(blocking=False):
        return False

    def run():
        try:
            resend_to_garmin(workout_ids)
        except Exception as e:
            q.set_setting(GARMIN_RESULT_SETTING, json.dumps(
                {"at": datetime.utcnow().isoformat(), "text": f"Couldn't update Garmin: {e}", "ok": False}))
        finally:
            _resend_lock.release()

    threading.Thread(target=run, name="garmin-ftp-resend", daemon=True).start()
    return True


def is_resending() -> bool:
    return _resend_lock.locked()


def last_garmin_result() -> dict | None:
    raw = q.get_setting(GARMIN_RESULT_SETTING, "")
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def summary(out: dict) -> str:
    """One line for the rider about what followed the new FTP."""
    parts = []
    if out.get("descriptions"):
        n = out["descriptions"]
        parts.append(f"updated watts in {n} upcoming workout{'s' if n != 1 else ''}")
    if out.get("garmin"):
        n = out["garmin"]
        parts.append(f"sending {n} workout{'s' if n != 1 else ''} to your Garmin again")
    text = ("Also " + " and ".join(parts) + ". ") if parts else ""
    from auth import trainingpeaks
    if trainingpeaks.is_enabled():
        text += "Set the same FTP in TrainingPeaks so its targets match."
    return text.strip()
