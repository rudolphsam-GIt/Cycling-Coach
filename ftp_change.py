"""
One path for changing FTP, so every place that sets it (Settings, the FTP card, onboarding) has
the same effects:

- the new value is saved and logged in FTP history, dated today;
- past rides keep the TSS they earned on the FTP they were ridden at;
- upcoming workouts follow the new number by themselves: their steps and the watts in their words
  are stored as % of FTP (see workout_watts);
- nothing is sent anywhere yet. The change waits for the rider to review it and choose where to
  send it (TrainingPeaks, intervals.icu, Garmin), and TrainingPeaks' automatic sync holds off
  until they answer, so new watts never reach another service unasked.
"""
from __future__ import annotations

import json
import threading
from datetime import date, datetime

from db import queries as q
import workout_watts

GARMIN_RESULT_SETTING = "garmin_ftp_resend_result"
PENDING_SETTING = "ftp_push_pending"        # {"old", "new", "at"} until the rider answers the review


def apply_new_ftp(new_ftp: int, note: str = "") -> dict:
    """Save a new FTP. Returns {"workouts": n upcoming workouts whose watts changed}. When any did,
    the change waits in pending() for the rider to review."""
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
    out = {"workouts": 0}
    if new_ftp <= 0 or old_ftp <= 0 or new_ftp == old_ftp:
        return out

    # Rides from today on are scored on the new FTP; earlier rides keep theirs.
    q.recalculate_all_tss(since=today)

    # Measured from the FTP last sent out, so two changes before an answer are one review.
    sent_ftp = (pending() or {}).get("old", old_ftp)
    upcoming = q.get_upcoming_workouts(today, raw=True)
    changed = [w for w in upcoming if _has_watts(w)]
    out["workouts"] = len(changed)
    on_garmin = any(w.get("garmin_workout_id") for w in upcoming)    # its watts are fixed at send
    if int(sent_ftp) == new_ftp or not (changed or on_garmin):
        clear_pending()
    else:
        q.set_setting(PENDING_SETTING, json.dumps({"old": int(sent_ftp), "new": new_ftp,
                                                   "at": datetime.utcnow().isoformat()}))
    return out


def _has_watts(w: dict) -> bool:
    return any(workout_watts.has_tokens(w.get(f)) for f in workout_watts.FIELDS)


def pending() -> dict | None:
    """The FTP change waiting for the rider's review, or None."""
    raw = q.get_setting(PENDING_SETTING, "")
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def clear_pending() -> None:
    q.set_setting(PENDING_SETTING, "")


def preview(limit: int = 3) -> dict:
    """What the pending change does: {"old", "new", "count", "examples": [(name, before, after)]},
    one example per kind of workout. Empty when nothing is pending."""
    p = pending()
    if not p:
        return {}
    rows = [w for w in q.get_upcoming_workouts(date.today().isoformat(), raw=True) if _has_watts(w)]
    examples, names = [], set()
    for w in rows:
        name = (w.get("name") or "Workout").split(") ")[-1]
        if name in names:
            continue
        lines = workout_watts.changed_lines(w.get("description"), p["old"], p["new"], limit=1)
        if lines:
            names.add(name)
            examples.append((f"{w['date']} {name}", *lines[0]))
        if len(examples) >= limit:
            break
    return {"old": p["old"], "new": p["new"], "count": len(rows), "examples": examples}


def destinations() -> list[dict]:
    """Connected places that hold copies of upcoming workouts, as {"key", "label", "count"}."""
    from auth import intervals, trainingpeaks as tp
    today = date.today().isoformat()
    upcoming = q.get_upcoming_workouts(today, raw=True)
    out = []
    if tp.is_enabled() and not tp.needs_signin():
        on = set(q.get_synced(tp.SERVICE))
        out.append({"key": "trainingpeaks", "label": "TrainingPeaks",
                    "count": sum(1 for w in upcoming if w["id"] in on)})
    if intervals.is_connected():
        on = set(q.get_synced(intervals.SERVICE))
        n = sum(1 for w in upcoming if w["id"] in on)
        if n:
            out.append({"key": "intervals", "label": "intervals.icu", "count": n})
    garmin = [w for w in upcoming if w.get("garmin_workout_id") and w.get("structured_json")]
    if garmin:
        out.append({"key": "garmin", "label": "Garmin", "count": len(garmin)})
    return out


def service_ftps() -> dict[str, int]:
    """The FTP each connected service has set, where it can be read. Best effort: a service that
    can't be reached is left out. Their workout targets are % of their own FTP."""
    from auth import intervals, trainingpeaks as tp
    out = {}
    try:
        if tp.is_enabled() and not tp.needs_signin():
            ftp = tp.Client().thresholds().get("ftp")
            if ftp:
                out["TrainingPeaks"] = int(ftp)
    except Exception:
        pass
    try:
        if intervals.is_connected():
            ftp = intervals.thresholds().get("ftp")
            if ftp:
                out["intervals.icu"] = int(ftp)
    except Exception:
        pass
    return out


def push(keys: list[str]) -> list[str]:
    """Send the upcoming workouts, as they read now, to the chosen places and end the review.
    TrainingPeaks and Garmin run in the background; intervals.icu is sent here. Returns one line
    per place for the rider."""
    from auth import intervals, trainingpeaks as tp
    import garmin_workouts
    clear_pending()
    today = date.today().isoformat()
    msgs = []
    if "trainingpeaks" in keys:
        tp.start_background_sync()
        msgs.append("Sending to TrainingPeaks in the background.")
    if "intervals" in keys:
        on = q.get_synced(intervals.SERVICE)
        ends = [r["date"] for r in on.values() if r["date"] >= today]
        if ends:
            end = max(ends)
            rows = [(w, steps) for w in q.get_workouts(today, end)
                    if w["id"] in on and (steps := garmin_workouts.saved_steps(w)) is not None]
            try:
                out = intervals.sync(rows, today, end)
                msgs.append(f"Updated {out['sent']} rides on intervals.icu.")
            except intervals.IntervalsError as e:
                msgs.append(f"Couldn't update intervals.icu. {e}")
    if "garmin" in keys:
        ids = [w["id"] for w in q.get_upcoming_workouts(today)
               if w.get("garmin_workout_id") and w.get("structured_json")]
        if ids and start_garmin_resend(ids):
            msgs.append(f"Sending {len(ids)} workout{'s' if len(ids) != 1 else ''} to your Garmin again.")
    return msgs


def keep_old_elsewhere() -> None:
    """End the review without sending. TrainingPeaks keeps the copies it has: they are marked up to
    date so its automatic sync doesn't send the new watts later on its own."""
    from auth import trainingpeaks as tp
    clear_pending()
    if tp.is_enabled():
        tp.accept_current()


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
    from db import schema

    def run():
        try:
            resend_to_garmin(workout_ids)
        except Exception as e:
            q.set_setting(GARMIN_RESULT_SETTING, json.dumps(
                {"at": datetime.utcnow().isoformat(), "text": f"Couldn't update Garmin: {e}", "ok": False}))
        finally:
            _resend_lock.release()

    threading.Thread(target=schema.pinned(run), name="garmin-ftp-resend", daemon=True).start()
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
    n = out.get("workouts") or 0
    if not n:
        return ""
    text = f"{n} upcoming workout{'s' if n != 1 else ''} now show{'' if n != 1 else 's'} watts for the new FTP."
    if pending() and destinations():
        text += " Choose where to send them in the review."
    return text
