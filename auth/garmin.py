from __future__ import annotations

"""
Garmin Connect sync: rides plus daily recovery (sleep, HRV, resting HR,
training readiness, body battery).

Uses garminconnect >= 0.3, which logs in the way the Garmin phone app does and
refreshes its tokens automatically. You connect once from Settings (with your
2FA code if Garmin asks); after that every sync reuses the saved tokens in
~/.cycling_coach_garmin/ and never needs your password again.
"""

import json
import os
from datetime import datetime, timedelta, date

from db.queries import (get_setting, set_setting, upsert_activity, upsert_recovery,
                        match_activity_id, save_peaks, save_hr_peaks, has_hr_peaks)
from metrics.zones import estimate_zone_seconds

TOKEN_DIR = os.path.join(os.path.expanduser("~"), ".cycling_coach_garmin")
TOKEN_FILE = os.path.join(TOKEN_DIR, "garmin_tokens.json")

CYCLING_TYPES = {
    "cycling", "road_biking", "mountain_biking", "gravel_cycling",
    "virtual_ride", "indoor_cycling", "cycling_training",
}

# Only sync automatically if the last sync is older than this.
AUTO_SYNC_AFTER = timedelta(hours=3)


class GarminNotConnected(Exception):
    pass


# ── Connecting ────────────────────────────────────────────────────────────────

def is_connected() -> bool:
    return os.path.isfile(TOKEN_FILE)


def start_login(email: str, password: str):
    """
    Begin a login. Returns ("done", None) on success, or ("needs_code", state)
    when Garmin wants a 2FA code; pass state to finish_login with the code.
    """
    from garminconnect import Garmin

    os.makedirs(TOKEN_DIR, mode=0o700, exist_ok=True)
    api = Garmin(email, password, return_on_mfa=True)
    status, client_state = api.login()
    if status == "needs_mfa":
        return "needs_code", (api, client_state)
    api.client.dump(TOKEN_DIR)
    set_setting("garmin_connected_at", datetime.utcnow().isoformat())
    return "done", None


def finish_login(state, code: str) -> None:
    api, client_state = state
    api.resume_login(client_state, code.strip())
    api.client.dump(TOKEN_DIR)
    set_setting("garmin_connected_at", datetime.utcnow().isoformat())


def disconnect() -> None:
    if os.path.isfile(TOKEN_FILE):
        os.remove(TOKEN_FILE)
    set_setting("garmin_connected_at", "")


def _client():
    """Return a logged in client using the saved tokens (no password needed)."""
    from garminconnect import Garmin, GarminConnectAuthenticationError

    if not is_connected():
        raise GarminNotConnected("Garmin isn't connected yet. Connect it in Settings.")
    api = Garmin()
    try:
        api.login(TOKEN_DIR)
    except GarminConnectAuthenticationError:
        # The saved login was revoked or expired. Clear it so Settings offers to connect again.
        disconnect()
        raise GarminNotConnected("Garmin signed you out. Connect it again in Settings.")
    return api


def friendly_error(e: Exception) -> str:
    from garminconnect import (GarminConnectAuthenticationError,
                               GarminConnectTooManyRequestsError,
                               GarminConnectConnectionError)
    if isinstance(e, GarminNotConnected):
        return str(e)
    if isinstance(e, GarminConnectTooManyRequestsError):
        return "Garmin is limiting requests right now. Wait an hour, then sync again."
    if isinstance(e, GarminConnectAuthenticationError):
        return ("Garmin didn't accept the login. Check your email and password, "
                "or reconnect Garmin in Settings if it was working before.")
    if isinstance(e, GarminConnectConnectionError):
        return "Couldn't reach Garmin. Check your internet connection and try again."
    return f"Garmin sync failed: {e}"


# ── TSS calculation ───────────────────────────────────────────────────────────

def _power_tss(duration_s: float, norm_power: float, ftp: float) -> float | None:
    if not ftp or ftp <= 0 or not norm_power or norm_power <= 0:
        return None
    if_val = norm_power / ftp
    return (duration_s / 3600) * (if_val ** 2) * 100


def _hr_tss(duration_s: float, avg_hr: float, lthr: float) -> float | None:
    if not lthr or lthr <= 0 or not avg_hr or avg_hr <= 0:
        return None
    return (duration_s / 3600) * ((avg_hr / lthr) ** 2) * 100


# ── Rides ─────────────────────────────────────────────────────────────────────

def activity_row(act: dict, ftp: float, lthr: float) -> dict | None:
    """Map one Garmin activity to an activities row, or None if it isn't a ride."""
    activity_type = (
        (act.get("activityType") or {}).get("typeKey", "")
        .lower().replace(" ", "_")
    )
    if activity_type not in CYCLING_TYPES:
        return None

    duration_s = float(act.get("duration") or 0)          # timer time, used for TSS
    elapsed_s = float(act.get("elapsedDuration") or duration_s)  # includes stops, like Strava
    moving_s = float(act.get("movingDuration") or duration_s)
    avg_hr = act.get("averageHR")
    max_hr = act.get("maxHR")
    avg_power = act.get("avgPower")
    norm_power = act.get("normPower") or avg_power

    tss = _power_tss(duration_s, norm_power, ftp)
    if tss is None:
        tss = _hr_tss(duration_s, avg_hr, lthr)
    if_value = (norm_power / ftp) if norm_power and ftp else None
    zones = estimate_zone_seconds(duration_s, avg_hr, max_hr, avg_power, norm_power, ftp, lthr)

    return {
        "source": "garmin",
        "external_id": f"garmin_{act.get('activityId', '')}",
        "date": (act.get("startTimeLocal") or "")[:10],
        "name": act.get("activityName") or "Garmin Ride",
        "sport_type": activity_type,
        "duration_seconds": int(moving_s),
        "elapsed_seconds": int(elapsed_s),
        "distance_meters": act.get("distance") or 0,
        "elevation_gain_meters": act.get("elevationGain") or 0,
        "avg_power_watts": avg_power,
        "normalized_power": norm_power,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "tss": round(tss, 1) if tss else None,
        "if_value": round(if_value, 3) if if_value else None,
        "zone_time_json": json.dumps(zones) if zones else None,
        "raw_json": json.dumps({
            "activityId": act.get("activityId"),
            "activityName": act.get("activityName"),
            "startTimeLocal": act.get("startTimeLocal"),
        }),
    }


def peak_powers(act: dict) -> dict[int, float]:
    """Best average power by duration in seconds, from Garmin's maxAvgPower_<secs>
    fields. Empty for rides without power or that the rider excluded from power
    curve reports in Garmin Connect."""
    if act.get("excludeFromPowerCurveReports"):
        return {}
    peaks = {}
    for key, value in act.items():
        if not key.startswith("maxAvgPower_"):
            continue
        try:
            secs, watts = int(key.rsplit("_", 1)[1]), float(value)
        except (TypeError, ValueError):
            continue
        if secs > 0 and 0 < watts < 3000:
            peaks[secs] = watts
    return peaks


def find_garmin_activity_id(api, activity: dict) -> str | None:
    """The Garmin id of the same ride, for a ride stored from another source, found by date
    and matched on time and distance the same way duplicate rides are."""
    from db.queries import _same_ride
    ftp = float(get_setting("ftp_watts", 0) or 0)
    lthr = float(get_setting("lthr", 0) or 0)
    day = str(activity.get("date"))[:10]
    for act in api.get_activities_by_date(day, day):
        row = activity_row(act, ftp, lthr)
        if row and _same_ride(row, activity):
            return str(act.get("activityId"))
    return None


def _hr_peaks(api, activity_id) -> dict:
    """Best average heart rate by duration, from the ride's original FIT file.
    Empty when the download or parsing fails (sync carries on regardless)."""
    from metrics.peaks import fit_from_download, hr_peaks_from_fit
    try:
        raw = api.download_activity(str(activity_id), dl_fmt=api.ActivityDownloadFormat.ORIGINAL)
        return hr_peaks_from_fit(fit_from_download(raw))
    except Exception:
        return {}


def _sync_rides(api, days_back: int) -> int:
    ftp = float(get_setting("ftp_watts", 0) or 0)
    lthr = float(get_setting("lthr", 0) or 0)
    start = (date.today() - timedelta(days=days_back)).isoformat()
    count = 0
    for act in api.get_activities_by_date(start, date.today().isoformat()):
        row = activity_row(act, ftp, lthr)
        if row and row["date"]:
            activity_id = upsert_activity(row)
            save_peaks(activity_id, peak_powers(act))
            if activity_id and act.get("averageHR") and not has_hr_peaks(activity_id):
                save_hr_peaks(activity_id, _hr_peaks(api, act.get("activityId")))
            count += 1
    return count


def backfill_peaks(days_back: int = 365, progress=None) -> tuple[int, int]:
    """Read Garmin ride history and store peak power (from the ride summary) and
    peak heart rate (from the ride's FIT file, only when not stored yet) for rides
    already in the app, matched by Garmin id or as the same ride from Strava.
    Never adds rides. `progress(done, total)` is called as it goes.
    Returns (rides updated, Garmin rides seen)."""
    api = _client()
    ftp = float(get_setting("ftp_watts", 0) or 0)
    lthr = float(get_setting("lthr", 0) or 0)
    start = (date.today() - timedelta(days=days_back)).isoformat()
    acts = [a for a in api.get_activities_by_date(start, date.today().isoformat())
            if activity_row(a, ftp, lthr)]
    updated = 0
    for i, act in enumerate(acts):
        row = activity_row(act, ftp, lthr)
        activity_id = match_activity_id(row) if row and row["date"] else None
        if activity_id:
            changed = False
            if (peaks := peak_powers(act)):
                save_peaks(activity_id, peaks)
                changed = True
            if act.get("averageHR") and not has_hr_peaks(activity_id):
                if (hr := _hr_peaks(api, act.get("activityId"))):
                    save_hr_peaks(activity_id, hr)
                    changed = True
            updated += changed
        if progress:
            progress(i + 1, len(acts))
    return updated, len(acts)


# ── Recovery ──────────────────────────────────────────────────────────────────

def _dig(data, *keys):
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key)
        elif isinstance(data, list) and isinstance(key, int) and len(data) > key:
            data = data[key]
        else:
            return None
    return data


def recovery_row(sleep: dict | None, hrv: dict | None, summary: dict | None,
                 readiness) -> dict:
    """Pull the numbers we use out of Garmin's daily responses."""
    sleep_s = _dig(sleep, "dailySleepDTO", "sleepTimeSeconds")
    if isinstance(readiness, list):
        readiness = readiness[0] if readiness else None
    return {
        "sleep_hours": round(sleep_s / 3600, 2) if sleep_s else None,
        "sleep_score": _dig(sleep, "dailySleepDTO", "sleepScores", "overall", "value"),
        "hrv_ms": _dig(hrv, "hrvSummary", "lastNightAvg"),
        "hrv_status": _dig(hrv, "hrvSummary", "status"),
        "resting_hr": _dig(summary, "restingHeartRate"),
        "readiness": _dig(readiness, "score"),
        "body_battery": _dig(summary, "bodyBatteryHighestValue"),
    }


def _safe(call, *args):
    try:
        return call(*args)
    except Exception:
        return None  # not every watch records every metric


def _sync_recovery(api, days_back: int) -> int:
    count = 0
    for i in range(days_back, -1, -1):
        day = (date.today() - timedelta(days=i)).isoformat()
        row = recovery_row(
            _safe(api.get_sleep_data, day),
            _safe(api.get_hrv_data, day),
            _safe(api.get_user_summary, day),
            _safe(api.get_training_readiness, day),
        )
        if any(v is not None for v in row.values()):
            upsert_recovery(day, row)
            count += 1
    return count


# ── Main sync ─────────────────────────────────────────────────────────────────

def sync(days_back: int = 30) -> tuple[int, str]:
    """Sync rides and recovery. Returns (rides_synced, message)."""
    try:
        api = _client()
        rides = _sync_rides(api, days_back)
        # Recovery takes several calls per day, so only backfill the last two weeks.
        recovery_days = _sync_recovery(api, min(days_back, 14))
    except Exception as e:
        return 0, friendly_error(e)

    set_setting("garmin_last_sync", datetime.utcnow().isoformat())
    return rides, f"Synced {rides} rides and {recovery_days} days of sleep and recovery from Garmin."


def needs_auto_sync() -> bool:
    if not is_connected():
        return False
    last = get_setting("garmin_last_sync", "")
    if not last:
        return True
    try:
        return datetime.utcnow() - datetime.fromisoformat(last) > AUTO_SYNC_AFTER
    except ValueError:
        return True


def auto_sync() -> tuple[int, str] | None:
    """Sync the last few days if it's been a while. Returns None if skipped."""
    if not needs_auto_sync():
        return None
    last = get_setting("garmin_last_sync", "")
    days = 30
    if last:
        try:
            days = max(3, (datetime.utcnow() - datetime.fromisoformat(last)).days + 2)
        except ValueError:
            pass
    return sync(days_back=min(days, 90))
