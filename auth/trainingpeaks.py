"""
TrainingPeaks calendar, unofficial and optional.

TrainingPeaks has no public API for individual athletes. This uses the same private website API
the TrainingPeaks web app uses, the way the open source tp2intervals tool does: the browser's
Production_tpAuth cookie is exchanged for a short lived token, then planned workouts are created
on their dates with their structure in percent of FTP. It can stop working whenever TrainingPeaks
changes its site, so it is off until the athlete turns it on in Settings, and the official
routes (the .zwo download and intervals.icu) never depend on it.

Calls (from tp2intervals, github.com/freekode/tp2intervals):
  GET    /users/v3/token                                   Cookie header -> {"token": {"access_token"}}
  GET    /users/v3/user                                    -> {"user": {"userId"}}
  POST   /fitness/v6/athletes/{id}/workouts                create and plan a workout
  GET    /fitness/v6/athletes/{id}/workouts/{start}/{end}  workouts on the calendar
  DELETE /fitness/v6/athletes/{id}/workouts/{workoutId}
"""
from __future__ import annotations

import hashlib
import threading
import json

import requests

from db import queries as q

API = "https://tpapi.trainingpeaks.com"
SERVICE = "trainingpeaks"
COOKIE_SETTING = "tp_auth_cookie"
ENABLED_SETTING = "tp_calendar_enabled"
BIKE = 2
TIMEOUT = 30
OPEN_TARGET = (40, 55)          # TrainingPeaks needs a target; an easy range stands in for "ride freely"
STEP_NAMES = {"warmup": "Warm up", "interval": "Work", "recovery": "Recover", "cooldown": "Cool down"}


class TPError(Exception):
    """A readable problem talking to TrainingPeaks."""


class TPAuthError(TPError):
    """The cookie was refused. A fresh one is needed."""


def clean_cookie(raw: str | None) -> str:
    """The cookie's value, whether the whole "Production_tpAuth=..." pair or just the value was pasted."""
    return (raw or "").strip().split("Production_tpAuth=", 1)[-1].split(";", 1)[0].strip()


def cookie_value() -> str:
    return clean_cookie(q.get_setting(COOKIE_SETTING, ""))


def is_enabled() -> bool:
    return q.get_setting(ENABLED_SETTING, "") == "1" and bool(cookie_value())


def _token(s: requests.Session, cookie: str) -> str:
    resp = s.get(f"{API}/users/v3/token", headers={"Cookie": f"Production_tpAuth={cookie}"}, timeout=TIMEOUT)
    if resp.status_code in (401, 403):
        raise TPAuthError("TrainingPeaks didn't accept the sign in cookie. Copy a fresh one (see Settings).")
    if resp.status_code >= 400:
        raise TPError(f"TrainingPeaks said {resp.status_code} when signing in.")
    try:
        return resp.json()["token"]["access_token"]
    except (ValueError, KeyError, TypeError):
        raise TPAuthError("TrainingPeaks didn't send a sign in token. The cookie may have expired, so copy a "
                          "fresh one.")


class Client:
    """A signed in session. Created per sync, since the token is short lived."""

    def __init__(self, cookie: str | None = None, session: requests.Session | None = None):
        self.s = session or requests.Session()
        try:
            token = _token(self.s, clean_cookie(cookie) or cookie_value())
            self.s.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})
            user = self._json(self.s.get(f"{API}/users/v3/user", timeout=TIMEOUT))
        except requests.RequestException as e:
            raise TPError(f"Couldn't reach TrainingPeaks. {e}") from e
        u = user.get("user") or {}
        self.user_id = str(u.get("userId") or "")
        if not self.user_id:
            raise TPError("TrainingPeaks didn't say which athlete this is.")
        status = u.get("accountStatus") or user.get("accountStatus") or {}
        self.premium = status.get("isPremium")
        self.name = " ".join(x for x in (u.get("firstName"), u.get("lastName")) if x) or "your account"

    @staticmethod
    def _json(resp: requests.Response):
        if resp.status_code in (401, 403):
            raise TPAuthError("TrainingPeaks signed you out. Copy a fresh cookie (see Settings).")
        if resp.status_code >= 400:
            raise TPError(f"TrainingPeaks said {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json() if resp.content else {}
        except ValueError:
            return {}

    def workouts(self, start: str, end: str) -> list[dict]:
        return self._json(self.s.get(f"{API}/fitness/v6/athletes/{self.user_id}/workouts/{start}/{end}",
                                     timeout=TIMEOUT)) or []

    def daily_tss(self, start: str, end: str) -> dict[str, float]:
        """{day: total TSS} from TrainingPeaks' fitness chart, which counts every workout,
        including some its workout list leaves out."""
        rows = self._json(self.s.post(
            f"{API}/fitness/v1/athletes/{self.user_id}/reporting/performancedata/{start}/{end}",
            json={"atlConstant": 7, "atlStart": 0, "ctlConstant": 42, "ctlStart": 0, "workoutTypes": []},
            timeout=TIMEOUT)) or []
        return {(r.get("workoutDay") or "")[:10]: float(r.get("tssActual") or 0) for r in rows}

    def daily_fitness(self, start: str, end: str) -> dict[str, dict]:
        """{day: {"ctl", "atl"}} from TrainingPeaks' fitness chart."""
        rows = self._json(self.s.post(
            f"{API}/fitness/v1/athletes/{self.user_id}/reporting/performancedata/{start}/{end}",
            json={"atlConstant": 7, "atlStart": 0, "ctlConstant": 42, "ctlStart": 0, "workoutTypes": []},
            timeout=TIMEOUT)) or []
        return {(r.get("workoutDay") or "")[:10]: {"ctl": r.get("ctl"), "atl": r.get("atl")} for r in rows}

    def thresholds(self) -> dict:
        """{"ftp", "lthr", "max_hr", "rest_hr"} from the athlete's TrainingPeaks zones: the bike
        zones when set, else the ones for all sports. Missing values are None."""
        data = self._json(self.s.get(f"{API}/fitness/v1/athletes/{self.user_id}/settings", timeout=TIMEOUT)) or {}

        def pick(rows):
            rows = [r for r in rows or [] if isinstance(r, dict) and r.get("threshold")]
            return (next((r for r in rows if r.get("workoutTypeId") == BIKE), None)
                    or next((r for r in rows if r.get("workoutTypeId") == 0), None) or {})
        hr, power = pick(data.get("heartRateZones")), pick(data.get("powerZones"))
        return {"ftp": power.get("threshold"), "lthr": hr.get("threshold"),
                "max_hr": hr.get("maximumHeartRate"), "rest_hr": hr.get("restingHeartRate")}

    def create(self, payload: dict) -> str | None:
        data = self._json(self.s.post(f"{API}/fitness/v6/athletes/{self.user_id}/workouts",
                                      json=payload, timeout=TIMEOUT))
        wid = data.get("workoutId") if isinstance(data, dict) else None
        if wid:
            return str(wid)
        # The create call's answer isn't documented, so find the new workout on its day by title.
        day = payload["workoutDay"]
        found = [w for w in self.workouts(day, day) if w.get("title") == payload["title"]]
        return str(max(int(w["workoutId"]) for w in found)) if found else None

    def delete(self, workout_id: str) -> None:
        resp = self.s.delete(f"{API}/fitness/v6/athletes/{self.user_id}/workouts/{workout_id}", timeout=TIMEOUT)
        if resp.status_code != 404:
            self._json(resp)


def check(cookie: str | None = None, session: requests.Session | None = None) -> dict:
    """{"name", "premium"} when the cookie works. Raises TPError otherwise."""
    c = Client(cookie, session)
    return {"name": c.name, "premium": c.premium}


def _tp_step(step: dict) -> dict:
    lo, hi = step.get("low_pct"), step.get("high_pct")
    if lo is None:
        lo, hi = OPEN_TARGET
    return {"name": STEP_NAMES.get(step["kind"], "Work"),
            "length": {"value": max(1, round(step["minutes"] * 60)), "unit": "second"},
            "targets": [{"minValue": round(lo), "maxValue": round(hi)}]}


def to_tp_structure(steps: list) -> dict:
    """The saved steps in TrainingPeaks' structure format, targets in percent of FTP."""
    out = []
    for s in steps:
        if s["kind"] == "repeat":
            out.append({"type": "repetition", "length": {"value": s["repeat_count"], "unit": "repetition"},
                        "steps": [_tp_step(x) for x in s["repeat_steps"]]})
        else:
            out.append({"type": "step", "length": {"value": 1, "unit": "repetition"}, "steps": [_tp_step(s)]})
    return {"structure": out, "primaryLengthMetric": "duration", "primaryIntensityMetric": "percentOfFtp"}


def payload(user_id: str, workout: dict, steps: list) -> dict:
    from garmin_workouts import total_minutes
    about = " ".join(x for x in (workout.get("purpose"), workout.get("feel") and f"Feel. {workout['feel']}",
                                 workout.get("description")) if x)
    return {"athleteId": user_id, "workoutDay": workout["date"], "workoutTypeValueId": BIKE,
            "title": workout.get("name") or "Workout", "description": about,
            "totalTimePlanned": round(total_minutes(steps) / 60, 3),
            "tssPlanned": round(workout.get("tss_planned") or 0),
            "structure": json.dumps(to_tp_structure(steps))}


def fingerprint(workout: dict, steps: list) -> str:
    return hashlib.sha1(json.dumps([workout["date"], workout.get("name"), workout.get("tss_planned"),
                                    workout.get("purpose"), workout.get("feel"), steps]).encode()).hexdigest()


def _planned_only(tp_workout: dict) -> bool:
    """True for a workout that is only a plan, with no ride recorded against it."""
    return not any(tp_workout.get(k) for k in ("totalTime", "distance", "tssActual", "completed"))


def _clear_imports(c: Client, workout: dict, listings: dict, known: set) -> None:
    """Delete planned workouts on this ride's day that are copies of it this app didn't send, such
    as ones dragged in from the .zwo download, so the calendar never shows the ride twice. Only
    matching titles, only plans with nothing ridden, and never a copy this app tracks."""
    from exporters import dated_title
    day = workout["date"]
    if day not in listings:
        listings[day] = c.workouts(day, day)
    titles = {(workout.get("name") or "Workout").strip().lower(), dated_title(workout).strip().lower()}
    for w in listings[day]:
        wid = str(w.get("workoutId") or "")
        if (wid and wid not in known and (w.get("title") or "").strip().lower() in titles
                and _planned_only(w)):
            c.delete(wid)
            known.add(wid)          # gone now, never delete it twice


def sync(rows: list[tuple[dict, list]], start: str, end: str, client: Client | None = None,
         keep_ids: set | None = None) -> dict:
    """Put these rides on the TrainingPeaks calendar. Unchanged ones are skipped, changed or moved
    ones are replaced, and ones removed from the plan are deleted. A ride sent for the first time
    replaces a matching plan already on that day (a .zwo import), so nothing is duplicated.
    `keep_ids` are workouts still in the plan that aren't being sent (done, or no steps yet), which
    must not be deleted. A failure on one ride is reported and the rest carry on, except a sign in
    failure, which stops the sync."""
    c = client or Client()
    synced = q.get_synced(SERVICE)
    known = {str(r["remote_id"]) for r in synced.values() if r.get("remote_id")}
    listings: dict[str, list] = {}
    done, failed, unchanged = [], [], 0
    for workout, steps in rows:
        fp = fingerprint(workout, steps)
        old = synced.get(workout["id"])
        if old and old.get("fingerprint") == fp and old.get("remote_id"):
            unchanged += 1
            continue
        try:
            if old and old.get("remote_id"):
                c.delete(old["remote_id"])
            else:
                _clear_imports(c, workout, listings, known)
            remote = c.create(payload(c.user_id, workout, steps))
            if remote:
                known.add(str(remote))
            done.append({"workout_id": workout["id"], "remote_id": remote, "date": workout["date"],
                         "fingerprint": fp})
        except TPAuthError:
            q.save_synced(SERVICE, done)
            raise
        except (TPError, requests.RequestException) as e:
            failed.append({"name": f"{workout['date']} {workout.get('name')}", "why": str(e)})
    q.save_synced(SERVICE, done)
    # Anything sent for today or later that is no longer in the plan comes off, even past `end`,
    # so deleting the last ride of a plan still removes its copy.
    keep = {w["id"] for w, _ in rows} | set(keep_ids or ())
    stale = [wid for wid, r in synced.items() if r["date"] >= start and wid not in keep]
    removed = []
    for wid in stale:
        try:
            if synced[wid].get("remote_id"):
                c.delete(synced[wid]["remote_id"])
            removed.append(wid)
        except (TPError, requests.RequestException) as e:
            failed.append({"name": f"removing {synced[wid]['date']}", "why": str(e)})
    q.drop_synced(SERVICE, removed)
    return {"sent": len(done), "unchanged": unchanged, "removed": len(removed), "failed": failed}


def remove(workout_ids: list[int]) -> None:
    """Take these workouts off the TrainingPeaks calendar, if they were sent. Best effort."""
    synced = q.get_synced(SERVICE)
    ids = [w for w in workout_ids if w in synced]
    if not ids or not is_enabled():
        return
    try:
        c = Client()
        for wid in ids:
            if synced[wid].get("remote_id"):
                c.delete(synced[wid]["remote_id"])
    except (TPError, requests.RequestException):
        return
    q.drop_synced(SERVICE, ids)


# ── Connecting and automatic sync ─────────────────────────────────────────────

PREMIUM_SETTING = "tp_premium"
NAME_SETTING = "tp_name"
NEEDS_SIGNIN_SETTING = "tp_needs_signin"
LAST_SYNC_SETTING = "tp_last_sync"
LAST_RESULT_SETTING = "tp_last_result"
FREE_DAYS = 2            # without Premium, TrainingPeaks only holds planned workouts for today and tomorrow
RESYNC_AFTER_HOURS = 24  # sync again at least daily, so a free account rolls forward


def connect(cookie: str, session: requests.Session | None = None) -> dict:
    """Check the cookie, then save it and turn the calendar sync on. Returns {"name", "premium"}."""
    info = check(cookie, session)
    q.set_setting(COOKIE_SETTING, clean_cookie(cookie))
    q.set_setting(ENABLED_SETTING, "1")
    q.set_setting(PREMIUM_SETTING, "" if info["premium"] is None else ("1" if info["premium"] else "0"))
    q.set_setting(NAME_SETTING, info["name"])
    q.set_setting(NEEDS_SIGNIN_SETTING, "")
    q.set_setting(LAST_SYNC_SETTING, "")     # sync everything on the next page load
    return info


def disconnect() -> None:
    from auth import tp_login
    for key in (ENABLED_SETTING, COOKIE_SETTING, PREMIUM_SETTING, NAME_SETTING, NEEDS_SIGNIN_SETTING,
                LAST_SYNC_SETTING, LAST_RESULT_SETTING):
        q.set_setting(key, "")
    tp_login.forget()


def is_premium() -> bool | None:
    v = q.get_setting(PREMIUM_SETTING, "")
    return None if v == "" else v == "1"


def needs_signin() -> bool:
    return q.get_setting(NEEDS_SIGNIN_SETTING, "") == "1"


def sync_range(today) -> tuple[str, str]:
    """Premium: today through the last planned ride, however far out. Free accounts: today and
    tomorrow, all TrainingPeaks lets them plan."""
    from datetime import timedelta
    if is_premium() is False:
        return today.isoformat(), (today + timedelta(days=FREE_DAYS - 1)).isoformat()
    planned = [w["date"] for w in q.get_workouts(today.isoformat(), "9999-12-31") if not w.get("completed")]
    return today.isoformat(), max(planned, default=today.isoformat())


def sync_due(now=None) -> bool:
    """True when the plan changed since the last sync, or it has been a day."""
    from datetime import datetime, timedelta
    if not is_enabled() or needs_signin():
        return False
    last = q.get_setting(LAST_SYNC_SETTING, "")
    if not last:
        return True
    changed = q.get_setting("plan_changed_at", "")
    if changed and changed > last:
        return True
    try:
        return (now or datetime.utcnow()) - datetime.fromisoformat(last) > timedelta(hours=RESYNC_AFTER_HOURS)
    except ValueError:
        return True


def _signed_in_client() -> Client:
    """A client, fetching a fresh cookie from the saved Chrome profile once if the stored one was
    refused. Marks that a real sign in is needed when that fails too."""
    try:
        return Client()
    except TPAuthError:
        from auth import tp_login
        cookie = tp_login.refresh()
        if cookie:
            try:
                c = Client(cookie)
                q.set_setting(COOKIE_SETTING, clean_cookie(cookie))
                return c
            except TPAuthError:
                pass
        q.set_setting(NEEDS_SIGNIN_SETTING, "1")
        raise TPAuthError("TrainingPeaks signed you out. Sign in again in Settings.")


def result_text(out: dict) -> str:
    bits = [f"Sent {out['sent']} ride{'s' if out['sent'] != 1 else ''} to TrainingPeaks"]
    if out.get("unchanged"):
        bits.append(f"{out['unchanged']} already up to date")
    if out.get("removed"):
        bits.append(f"took off {out['removed']} you removed")
    text = ", ".join(bits) + "."
    if out.get("failed"):
        text += " Couldn't send " + "; ".join(f"{f['name']} ({f['why']})" for f in out["failed"])
    return text


def sync_upcoming(today=None, client: Client | None = None, build_steps=None) -> dict:
    """Put every upcoming planned ride on the TrainingPeaks calendar. Steps a ride doesn't have yet
    are built once with the coach (and saved). Records when it ran and what happened."""
    from datetime import date, datetime
    import garmin_workouts
    today = today or date.today()
    start, end = sync_range(today)
    started = datetime.utcnow().isoformat()
    rides = [w for w in q.get_workouts(start, end) if not w.get("completed")]
    missing = [w for w in rides if garmin_workouts.saved_steps(w) is None]
    skipped = 0
    if missing:
        try:
            (build_steps or garmin_workouts.ensure_steps)(missing)
        except garmin_workouts.WorkoutError:
            pass
        rides = [w for w in q.get_workouts(start, end) if not w.get("completed")]
    rows = []
    for w in rides:
        steps = garmin_workouts.saved_steps(w)
        if steps is None:
            skipped += 1
        else:
            rows.append((w, steps))
    # Every ride still in the plan stays on TrainingPeaks, even ones not sent this time
    # (done today, or steps not built), so planned vs done survives in TrainingPeaks.
    keep = {w["id"] for w in q.get_workouts(start, end)}
    try:
        out = sync(rows, start, end, client or _signed_in_client(), keep_ids=keep)
    except TPError as e:
        q.set_setting(LAST_RESULT_SETTING, f"err|{started}|{e}")
        raise
    out["skipped"] = skipped
    text = result_text(out)
    if skipped:
        text += f" {skipped} ride{'s' if skipped != 1 else ''} waiting for steps, which the coach couldn't build."
    q.set_setting(LAST_SYNC_SETTING, started)
    kind = "warn" if out["failed"] or skipped else "ok"
    q.set_setting(LAST_RESULT_SETTING, f"{kind}|{started}|{text}")
    return out


BIKE_TYPES = (2, 8)          # TrainingPeaks' bike and mountain bike workout types


SCORED_BY = {1: "power", 4: "hr", 0: "manual"}   # TrainingPeaks' tssSource codes seen so far


def normalize(w: dict) -> dict:
    """A TrainingPeaks workout in the shape compare.py matches on."""
    return {"day": (w.get("workoutDay") or "")[:10], "hours": w.get("totalTime"), "tss": w.get("tssActual"),
            "np": w.get("normalizedPowerActual"), "avg_hr": w.get("heartRateAverage"),
            "kind": "bike" if w.get("workoutTypeValueId") in BIKE_TYPES else "other",
            "scored_by": SCORED_BY.get(w.get("tssSource"), "other"), "title": w.get("title")}


def compare_with_trainingpeaks(days_back: int = 60, client: Client | None = None) -> int:
    """Read TrainingPeaks' TSS for the app's rides and sessions and keep it next to the app's own
    score, so big differences can be flagged. Never changes the app's score. Returns how many
    activities were matched."""
    from datetime import date, timedelta
    end = date.today()
    start = end - timedelta(days=days_back)
    c = client or Client()                 # the plan sync just refreshed the sign in if it needed to
    tp_done = []
    day = start
    while day <= end:                      # TrainingPeaks answers at most about 6 months at a time
        chunk_end = min(day + timedelta(days=180), end)
        tp_done += c.workouts(day.isoformat(), chunk_end.isoformat())
        day = chunk_end + timedelta(days=1)
    import compare
    acts = q.get_activities(days_back=days_back + 1)
    others = [r for r in acts if not q.is_ride(r)]
    pairs = compare.match_and_store(SERVICE, [normalize(w) for w in tp_done], acts)

    # TrainingPeaks' fitness chart counts some sessions (often strength) that its workout list
    # leaves out. What's left on a day after the listed workouts is what it gave the app's
    # unmatched sessions that day, split by duration.
    matched = {r["id"] for _, r in pairs}
    listed: dict[str, float] = {}
    for w in tp_done:
        if w.get("tssActual"):
            d = (w.get("workoutDay") or "")[:10]
            listed[d] = listed.get(d, 0.0) + float(w["tssActual"])
    by_day: dict[str, list[dict]] = {}
    for r in others:
        if r["id"] not in matched:
            by_day.setdefault(r["date"], []).append(r)
    count = len(pairs)
    if by_day:
        chart = c.daily_tss(min(by_day), max(by_day))
        for d, items in by_day.items():
            left = chart.get(d, 0.0) - listed.get(d, 0.0)
            if left < 1:
                continue
            total = sum(r.get("duration_seconds") or 0 for r in items)
            for r in items:
                share = (r.get("duration_seconds") or 0) / total if total else 1 / len(items)
                q.set_ref_numbers(r["id"], SERVICE, {"tss": round(left * share, 1), "scored_by": "hr",
                                                     "title": "From TrainingPeaks' fitness chart"})
                count += 1
    return count


def last_result() -> tuple[str, str, str] | None:
    """(kind, when, text) of the last automatic or manual sync, or None."""
    raw = q.get_setting(LAST_RESULT_SETTING, "")
    parts = raw.split("|", 2)
    return tuple(parts) if len(parts) == 3 else None


def last_sync_text() -> str:
    from datetime import datetime
    last = q.get_setting(LAST_SYNC_SETTING, "")
    try:
        mins = int((datetime.utcnow() - datetime.fromisoformat(last)).total_seconds() // 60)
    except (TypeError, ValueError):
        return "Not synced yet"
    if mins < 2:
        return "Last synced just now"
    if mins < 60:
        return f"Last synced {mins} min ago"
    if mins < 48 * 60:
        return f"Last synced {mins // 60} h ago"
    return f"Last synced {mins // 1440} days ago"


_sync_lock = threading.Lock()


def run_locked(**kwargs) -> dict | None:
    """sync_upcoming, but only if no other sync is running, so two can never send the same ride
    twice. None when one was already running."""
    if not _sync_lock.acquire(blocking=False):
        return None
    try:
        out = sync_upcoming(**kwargs)
        if is_enabled() and not needs_signin():
            try:
                compare_with_trainingpeaks()   # keep TrainingPeaks' scores to compare
            except Exception:
                pass                       # best effort; the next sync tries again
        return out
    finally:
        _sync_lock.release()


def start_background_sync() -> bool:
    """Run a sync on a background thread so no page waits on TrainingPeaks. False when one is
    already running."""
    if is_syncing():
        return False

    def run():
        try:
            run_locked()
        except Exception:
            pass        # sync_upcoming records TrainingPeaks errors; anything else waits for the next try

    threading.Thread(target=run, name="tp-sync", daemon=True).start()
    return True


def is_syncing() -> bool:
    return _sync_lock.locked()
