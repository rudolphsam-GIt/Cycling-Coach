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


def sync(rows: list[tuple[dict, list]], start: str, end: str, client: Client | None = None) -> dict:
    """Put these rides on the TrainingPeaks calendar. Unchanged ones are skipped, changed or moved
    ones are replaced, and ones removed from the plan in this range are deleted. A failure on one
    ride is reported and the rest carry on, except a sign in failure, which stops the sync."""
    c = client or Client()
    synced = q.get_synced(SERVICE)
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
            remote = c.create(payload(c.user_id, workout, steps))
            done.append({"workout_id": workout["id"], "remote_id": remote, "date": workout["date"],
                         "fingerprint": fp})
        except TPAuthError:
            q.save_synced(SERVICE, done)
            raise
        except (TPError, requests.RequestException) as e:
            failed.append({"name": f"{workout['date']} {workout.get('name')}", "why": str(e)})
    q.save_synced(SERVICE, done)
    current = {w["id"] for w, _ in rows}
    stale = [wid for wid, r in synced.items() if start <= r["date"] <= end and wid not in current]
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
