"""
Intervals.icu: a free training calendar with an official API. The app puts planned rides on it
as dated Zwift workouts, and intervals.icu passes them on to Zwift (on every computer you log in
to) and Garmin. Sign in is a personal API key from intervals.icu Settings, Developer Settings,
sent as HTTP Basic auth with the user name API_KEY.

Every sync can be run again. Each ride carries our id ("cc-<workout id>"), so a moved or edited
ride updates in place, and rides removed in the app are removed there too.
"""
from __future__ import annotations

import hashlib
import json

import requests

from db import queries as q

API = "https://intervals.icu/api/v1"
SERVICE = "intervals"
KEY_SETTING = "intervals_api_key"
CHUNK = 50
TIMEOUT = 30


class IntervalsError(Exception):
    """A readable problem talking to intervals.icu."""


def api_key() -> str:
    return (q.get_setting(KEY_SETTING, "") or "").strip()


def is_connected() -> bool:
    return bool(api_key())


def _session(key: str | None = None) -> requests.Session:
    s = requests.Session()
    s.auth = ("API_KEY", key or api_key())
    s.headers["Accept"] = "application/json"
    return s


def _check(resp: requests.Response) -> requests.Response:
    if resp.status_code in (401, 403):
        raise IntervalsError("intervals.icu didn't accept the API key. Copy it again from intervals.icu "
                             "Settings, Developer Settings.")
    if resp.status_code >= 400:
        raise IntervalsError(f"intervals.icu said {resp.status_code}: {resp.text[:200]}")
    return resp


def check(key: str | None = None, session: requests.Session | None = None) -> str:
    """The athlete's name if the key works. Raises IntervalsError otherwise."""
    s = session or _session(key)
    try:
        data = _check(s.get(f"{API}/athlete/0", timeout=TIMEOUT)).json()
    except requests.RequestException as e:
        raise IntervalsError(f"Couldn't reach intervals.icu. {e}") from e
    return data.get("name") or data.get("firstname") or "your account"


def external_id(workout_id: int) -> str:
    return f"cc-{workout_id}"


def fingerprint(workout: dict, zwo: str) -> str:
    return hashlib.sha1(json.dumps([workout["date"], workout.get("name"), zwo]).encode()).hexdigest()


def event_payload(workout: dict, zwo: str) -> dict:
    """One planned ride for the bulk endpoint."""
    from exporters import file_base
    about = " ".join(x for x in (workout.get("purpose"), workout.get("feel") and f"Feel. {workout['feel']}") if x)
    return {"category": "WORKOUT", "type": "Ride",
            "start_date_local": f"{workout['date']}T00:00:00",
            "name": workout.get("name") or "Workout", "description": about,
            "filename": f"{file_base(workout)}.zwo", "file_contents": zwo,
            "external_id": external_id(workout["id"])}


def note_payload(day: str, name: str, text: str, key: str) -> dict:
    return {"category": "NOTE", "start_date_local": f"{day}T00:00:00", "name": name,
            "description": text, "external_id": key}


def stale_ids(synced: dict[int, dict], current_ids: set[int], start: str, end: str) -> list[int]:
    """Workouts sent before, dated inside the range, that are no longer in the plan there."""
    return [wid for wid, row in synced.items()
            if start <= row["date"] <= end and wid not in current_ids]


def sync(rows: list[tuple[dict, list]], start: str, end: str, notes: list[dict] | None = None,
         session: requests.Session | None = None) -> dict:
    """Put these rides on intervals.icu and take off ones removed from the plan in this range.
    Returns {"sent": n, "removed": n}. Raises IntervalsError when the service refuses."""
    from exporters import to_zwo
    s = session or _session()
    synced = q.get_synced(SERVICE)
    events, records = [], []
    for workout, steps in rows:
        zwo = to_zwo(workout, steps)
        events.append(event_payload(workout, zwo))
        records.append({"workout_id": workout["id"], "remote_id": external_id(workout["id"]),
                        "date": workout["date"], "fingerprint": fingerprint(workout, zwo)})
    events += notes or []
    try:
        for i in range(0, len(events), CHUNK):
            _check(s.post(f"{API}/athlete/0/events/bulk", params={"upsert": "true"},
                          json=events[i:i + CHUNK], timeout=TIMEOUT))
        stale = stale_ids(synced, {r["workout_id"] for r in records}, start, end)
        if stale:
            _check(s.put(f"{API}/athlete/0/events/bulk-delete",
                         json=[{"external_id": external_id(w)} for w in stale], timeout=TIMEOUT))
    except requests.RequestException as e:
        raise IntervalsError(f"Couldn't reach intervals.icu. {e}") from e
    q.save_synced(SERVICE, records)
    q.drop_synced(SERVICE, stale)
    return {"sent": len(records), "removed": len(stale)}


def remove(workout_ids: list[int], session: requests.Session | None = None) -> None:
    """Take these workouts off intervals.icu, if they were sent. Best effort."""
    synced = q.get_synced(SERVICE)
    ids = [w for w in workout_ids if w in synced]
    if not ids or not is_connected():
        return
    try:
        (session or _session()).put(f"{API}/athlete/0/events/bulk-delete",
                                    json=[{"external_id": external_id(w)} for w in ids], timeout=TIMEOUT)
    except requests.RequestException:
        return
    q.drop_synced(SERVICE, ids)
