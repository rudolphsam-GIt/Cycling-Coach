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
                        match_activity_id, save_peaks, save_hr_peaks, has_hr_peaks,
                        ftp_history_rows, ftp_on, oldest_ride_missing_timer,
                        get_activity, hr_profile, rescore_from_streams, save_streams,
                        apply_device_numbers, recalculate_all_tss, get_streams)
from metrics.tss import ride_tss, time_rule, tss_duration
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


# ── Rides ─────────────────────────────────────────────────────────────────────

def activity_row(act: dict, ftp: float, lthr: float, profile: dict | None = None) -> dict | None:
    """Map one Garmin activity to an activities row, or None if it isn't a ride."""
    activity_type = (
        (act.get("activityType") or {}).get("typeKey", "")
        .lower().replace(" ", "_")
    )
    if activity_type not in CYCLING_TYPES:
        return None

    duration_s = float(act.get("duration") or 0)          # timer time
    elapsed_s = float(act.get("elapsedDuration") or duration_s)  # includes stops, like Strava
    moving_s = float(act.get("movingDuration") or duration_s)
    avg_hr = act.get("averageHR")
    max_hr = act.get("maxHR")
    avg_power = act.get("avgPower")
    norm_power = act.get("normPower") or avg_power

    # Score on timer or moving time, as the "Score like" standard says. Both are stored, so a later
    # recalculation reads back the same duration.
    tss_s = tss_duration(moving_s, elapsed_s, duration_s, time_rule(profile))
    tss, if_value, tss_source = ride_tss(tss_s, norm_power, avg_hr, max_hr, ftp, lthr, profile=profile)
    zones = estimate_zone_seconds(tss_s, avg_hr, max_hr, avg_power, norm_power, ftp, lthr)

    return {
        "source": "garmin",
        "external_id": f"garmin_{act.get('activityId', '')}",
        "date": (act.get("startTimeLocal") or "")[:10],
        "name": act.get("activityName") or "Garmin Ride",
        "sport_type": activity_type,
        "duration_seconds": int(moving_s),
        "elapsed_seconds": int(elapsed_s),
        "timer_seconds": int(duration_s) if duration_s else None,
        "distance_meters": act.get("distance") or 0,
        "elevation_gain_meters": act.get("elevationGain") or 0,
        "avg_power_watts": avg_power,
        "normalized_power": norm_power,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "tss": round(tss, 1) if tss else None,
        "tss_source": tss_source if tss else None,
        "if_value": round(if_value, 3) if if_value else None,
        "zone_time_json": json.dumps(zones) if zones else None,
        "raw_json": json.dumps({
            "activityId": act.get("activityId"),
            "activityName": act.get("activityName"),
            "startTimeLocal": act.get("startTimeLocal"),
        }),
    }


def other_activity_row(act: dict, lthr: float, profile: dict | None = None) -> dict | None:
    """Map a Garmin activity that isn't a ride (strength, hike, ski...) to an activities row,
    scored from heart rate, since these count toward fitness too. None for rides, or when there
    is no heart rate to score it with."""
    activity_type = ((act.get("activityType") or {}).get("typeKey", "") or "").lower().replace(" ", "_")
    if not activity_type or activity_type in CYCLING_TYPES:
        return None
    duration_s = float(act.get("duration") or 0)
    elapsed_s = float(act.get("elapsedDuration") or duration_s)
    moving_s = float(act.get("movingDuration") or duration_s)
    avg_hr, max_hr = act.get("averageHR"), act.get("maxHR")
    if duration_s <= 0 or not avg_hr:
        return None
    tss, _, tss_source = ride_tss(tss_duration(moving_s, elapsed_s, duration_s, time_rule(profile)), None,
                                  avg_hr, max_hr, None, lthr, profile=profile)
    return {
        "source": "garmin",
        "external_id": f"garmin_{act.get('activityId', '')}",
        "date": (act.get("startTimeLocal") or "")[:10],
        "name": act.get("activityName") or activity_type.replace("_", " ").title(),
        "sport_type": activity_type,
        "duration_seconds": int(moving_s),
        "elapsed_seconds": int(elapsed_s),
        "timer_seconds": int(duration_s),
        "distance_meters": act.get("distance") or 0,
        "elevation_gain_meters": act.get("elevationGain") or 0,
        "avg_power_watts": None, "normalized_power": None,
        "avg_hr": avg_hr, "max_hr": max_hr,
        "tss": round(tss, 1) if tss else None,
        "tss_source": tss_source if tss else None,
        "if_value": None, "zone_time_json": None,
        "raw_json": json.dumps({"activityId": act.get("activityId"), "activityName": act.get("activityName"),
                                "startTimeLocal": act.get("startTimeLocal")}),
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


def _ride_file(api, activity_id) -> bytes | None:
    """The ride's original FIT file as Garmin sends it, or None if the download fails."""
    try:
        return api.download_activity(str(activity_id), dl_fmt=api.ActivityDownloadFormat.ORIGINAL)
    except Exception:
        return None


def _hr_peaks(api, activity_id, raw: bytes | None = None) -> dict:
    """Best average heart rate by duration, from the ride's original FIT file.
    Empty when the download or parsing fails (sync carries on regardless)."""
    from metrics.peaks import fit_from_download, hr_peaks_from_fit
    raw = raw if raw is not None else _ride_file(api, activity_id)
    if not raw:
        return {}
    try:
        return hr_peaks_from_fit(fit_from_download(raw))
    except Exception:
        return {}


def _score_from_file(activity_id: int, raw: bytes | None) -> None:
    """Check the ride second by second. If power is missing for the whole ride or drops out
    while heart rate keeps recording, keep the data and rescore with hrTSS for those seconds.
    Rides with full power keep Garmin's summary numbers and their data isn't stored."""
    from metrics.streams import from_fit
    from metrics.tss import stream_tss
    if not raw:
        return
    try:
        streams = from_fit(raw)
    except Exception:
        return
    act = get_activity(activity_id)
    if not streams or not act:
        return
    lthr = float(get_setting("lthr", 0) or 0)
    profile = hr_profile()
    seconds = tss_duration(act.get("duration_seconds"), act.get("elapsed_seconds"), act.get("timer_seconds"),
                           time_rule(profile))
    if stream_tss(streams, ftp_on(act["date"]), lthr, profile, seconds):
        save_streams(activity_id, streams, "garmin")
        rescore_from_streams(activity_id)


def _sync_rides(api, days_back: int) -> int:
    ftp = float(get_setting("ftp_watts", 0) or 0)
    lthr = float(get_setting("lthr", 0) or 0)
    start = (date.today() - timedelta(days=days_back)).isoformat()
    history = ftp_history_rows()
    profile = hr_profile()
    count = 0
    for act in api.get_activities_by_date(start, date.today().isoformat()):
        # Score each ride on the FTP it was ridden at, so a re-sync never rewrites history.
        day = (act.get("startTimeLocal") or "")[:10]
        row = activity_row(act, ftp_on(day, history) if day else ftp, lthr, profile)
        if row is None:
            # Strength, hikes and skiing count toward fitness too, but aren't rides. Their heart
            # rate is scored second by second from the file, fetched once.
            other = other_activity_row(act, lthr, profile)
            if other and other["date"]:
                other_id = upsert_activity(other)
                if other_id and not get_streams(other_id):
                    _score_from_file(other_id, _ride_file(api, act.get("activityId")))
                elif other_id:
                    rescore_from_streams(other_id)
            continue
        if row and row["date"]:
            activity_id = upsert_activity(row)
            save_peaks(activity_id, peak_powers(act))
            if activity_id and act.get("averageHR") and not has_hr_peaks(activity_id):
                # One download serves both: heart rate peaks, and a check for power dropouts.
                raw = _ride_file(api, act.get("activityId"))
                save_hr_peaks(activity_id, _hr_peaks(api, act.get("activityId"), raw))
                _score_from_file(activity_id, raw)
            elif activity_id and not get_streams(activity_id) and not act.get("normPower") \
                    and act.get("averageHR"):
                # A heart rate only ride from before rides were checked second by second.
                _score_from_file(activity_id, _ride_file(api, act.get("activityId")))
            elif activity_id:
                # A re-sync writes Garmin's summary TSS back; a ride already checked second by
                # second (no power, or a dropout) keeps the score from that data.
                rescore_from_streams(activity_id)
            count += 1
    return count


def backfill_peaks(days_back: int = 365, progress=None) -> tuple[int, int]:
    """Read Garmin ride history and store peak power (from the ride summary) and
    peak heart rate (from the ride's FIT file, only when not stored yet) for rides
    already in the app, matched by Garmin id or as the same ride from Strava. Rides that came
    from Strava also take Garmin's normalized power and timer time, and are rescored.
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
            if apply_device_numbers(activity_id, act.get("normPower"), act.get("duration")):
                recalculate_all_tss(only_id=activity_id)
                changed = True
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
    msg = f"Synced {rides} rides and {recovery_days} days of sleep and recovery from Garmin."
    if recovery_status()["stale"]:
        msg += " Garmin has no recent sleep or recovery data. Sync your watch in the Garmin Connect app."
    return rides, msg


def recovery_status(today: date | None = None) -> dict:
    """Whether Garmin has been sending sleep and recovery numbers. Rides come from a bike
    computer or watch and sleep from a watch worn overnight, so one can be current while the
    other has stopped. Returns {last_date, days_old, stale}."""
    from db.queries import get_latest_recovery
    today = today or date.today()
    row = get_latest_recovery()
    if not row:
        return {"last_date": None, "days_old": None, "stale": True}
    days_old = (today - date.fromisoformat(row["date"])).days
    return {"last_date": row["date"], "days_old": days_old, "stale": days_old > 1}


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


def sync_recent() -> tuple[int, str]:
    """Sync from a couple of days before the last sync up to today."""
    last = get_setting("garmin_last_sync", "")
    days = 30
    if last:
        try:
            days = max(3, (datetime.utcnow() - datetime.fromisoformat(last)).days + 2)
        except ValueError:
            pass
    # Rides saved before timer time was stored are fetched once more to pick it up.
    if (oldest := oldest_ride_missing_timer("garmin")):
        days = max(days, (date.today() - date.fromisoformat(oldest)).days + 1)
    return sync(days_back=min(days, 90))


def auto_sync() -> tuple[int, str] | None:
    """Sync the last few days if it's been a while. Returns None if skipped."""
    if not needs_auto_sync():
        return None
    return sync_recent()


def last_sync_text() -> str:
    """For example "Synced 2 hours ago", or "" when Garmin has never synced."""
    last = get_setting("garmin_last_sync", "")
    try:
        mins = int((datetime.utcnow() - datetime.fromisoformat(last)).total_seconds() // 60)
    except (TypeError, ValueError):
        return ""
    if mins < 2:
        return "Synced just now"
    if mins < 60:
        return f"Synced {mins} min ago"
    if mins < 48 * 60:
        hours = mins // 60
        return f"Synced {hours} hour{'s' if hours != 1 else ''} ago"
    return f"Synced {mins // 1440} days ago"
