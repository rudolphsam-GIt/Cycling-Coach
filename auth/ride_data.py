"""
Second by second data for one ride, fetched when the rider opens it.

The order of tries: the copy already kept in the database, then Garmin (the ride's
original file), then Strava (its streams). A ride that was merged from both
sources is looked up wherever the app can still reach it. Whatever is fetched is
kept, so each ride is only fetched once.
"""
from __future__ import annotations

import json
import requests

from db.queries import get_activity, get_streams, save_streams
from metrics import streams as st

STRAVA_API = "https://www.strava.com/api/v3"
STRAVA_KEYS = "time,watts,heartrate,cadence,velocity_smooth,altitude,distance"


def _raw(activity: dict) -> dict:
    try:
        return json.loads(activity.get("raw_json") or "{}")
    except (TypeError, ValueError):
        return {}


def garmin_id(activity: dict) -> str | None:
    """The Garmin activity id, when the row came from Garmin."""
    ext = str(activity.get("external_id") or "")
    if ext.startswith("garmin_") and ext[7:].isdigit():
        return ext[7:]
    gid = _raw(activity).get("activityId")
    return str(gid) if gid and activity.get("source") == "garmin" else None


def strava_id(activity: dict) -> str | None:
    ext = str(activity.get("external_id") or "")
    return ext[7:] if ext.startswith("strava_") and ext[7:].isdigit() else None


def _from_garmin(activity: dict, api=None) -> dict | None:
    import auth.garmin as garmin_auth
    if not garmin_auth.is_connected():
        return None
    api = api or garmin_auth._client()
    gid = garmin_id(activity) or garmin_auth.find_garmin_activity_id(api, activity)
    if not gid:
        return None
    raw = api.download_activity(gid, dl_fmt=api.ActivityDownloadFormat.ORIGINAL)
    return st.from_fit(raw)


def _from_strava(activity: dict) -> dict | None:
    import auth.strava as strava_auth
    from config import STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET
    sid = strava_id(activity)
    if not sid or not strava_auth.is_connected():
        return None
    token = strava_auth.get_valid_token(STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET)
    if not token:
        return None
    resp = requests.get(f"{STRAVA_API}/activities/{sid}/streams", timeout=20,
                        headers={"Authorization": f"Bearer {token}"},
                        params={"keys": STRAVA_KEYS, "key_by_type": "true"})
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return st.from_strava(resp.json())


def load_streams(activity_id: int) -> tuple[dict | None, str]:
    """(streams, note). `streams` is None when there is no second by second data for
    this ride, and `note` then says why in words for the rider."""
    cached = get_streams(activity_id)
    if cached:
        return cached, ""
    activity = get_activity(activity_id)
    if not activity:
        return None, "That ride is no longer in the app."

    errors = []
    tries = ([_from_strava, _from_garmin] if strava_id(activity) else [_from_garmin, _from_strava])
    for fetch in tries:
        try:
            data = fetch(activity)
        except Exception as e:                      # network, login, parsing: try the next source
            errors.append(str(e))
            continue
        if data:
            save_streams(activity_id, data, fetch.__name__.removeprefix("_from_"))
            return data, ""
    if errors:
        return None, "Couldn't load the detailed data right now. " + errors[0]
    return None, ("No second by second data for this ride. It comes from Garmin or Strava when "
                  "they are connected in Settings, or from a .fit file you import.")
