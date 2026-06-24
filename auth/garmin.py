from __future__ import annotations

"""
Garmin Connect sync.

Requires garminconnect >= 0.2.0 (uses garth for auth — fixes the JSON parse
error that broke 0.1.x when Garmin changed their login page format).

Token persistence: saved to ~/.cycling_coach_garmin/ so re-login is only
needed when tokens expire (typically every few months) or credentials change.
"""

import json
import os
from datetime import datetime, timedelta, date
from db.queries import get_setting, set_setting, upsert_activity
from metrics.zones import estimate_zone_seconds

_GARTH_DIR = os.path.join(os.path.expanduser("~"), ".cycling_coach_garmin")

CYCLING_TYPES = {
    "cycling", "road_biking", "mountain_biking", "gravel_cycling",
    "virtual_ride", "indoor_cycling", "cycling_training",
}


# ── Session management ────────────────────────────────────────────────────────

def _has_saved_tokens() -> bool:
    if not os.path.isdir(_GARTH_DIR):
        return False
    return any(
        os.path.isfile(os.path.join(_GARTH_DIR, f))
        for f in os.listdir(_GARTH_DIR)
    )


def _get_client(email: str, password: str):
    """
    Return an authenticated Garmin client.
    Tries saved garth tokens first; falls back to full login only when needed.
    """
    try:
        from garminconnect import Garmin
        import garth  # noqa: F401  — present in garminconnect >= 0.2.x
    except ImportError:
        raise RuntimeError(
            "garminconnect >= 0.2.0 required. "
            "Run: pip install 'garminconnect>=0.2.0'"
        )

    os.makedirs(_GARTH_DIR, exist_ok=True)

    # Try restoring saved tokens
    if _has_saved_tokens():
        try:
            client = Garmin()
            client.login(_GARTH_DIR)
            client.get_full_name()  # validate tokens are still alive
            return client, "session_reused"
        except Exception:
            pass  # tokens expired or invalid — fall through to full login

    # Full login
    client = Garmin(email, password)
    client.login()
    client.garth.dump(_GARTH_DIR)
    set_setting("garmin_session_saved_at", datetime.utcnow().isoformat())
    return client, "fresh_login"


def clear_session() -> None:
    """Force a fresh login on the next sync."""
    set_setting("garmin_session_saved_at", "")
    if os.path.isdir(_GARTH_DIR):
        for f in os.listdir(_GARTH_DIR):
            fp = os.path.join(_GARTH_DIR, f)
            if os.path.isfile(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass


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


# ── Main sync ─────────────────────────────────────────────────────────────────

def sync_activities(email: str, password: str, days_back: int = 30) -> tuple[int, str]:
    """Pull recent cycling activities from Garmin Connect."""
    try:
        from garminconnect import Garmin  # noqa: F401
    except ImportError:
        return 0, "garminconnect not installed. Run: pip install 'garminconnect>=0.2.0'"

    # ── Authenticate ──────────────────────────────────────────────────────────
    try:
        client, login_method = _get_client(email, password)
    except RuntimeError as e:
        return 0, str(e)
    except json.JSONDecodeError:
        # garth's OAuth exchange calls .json() on the Garmin response; if
        # Garmin returns an HTML rate-limit or challenge page instead of JSON
        # this surfaces as "Extra data" or "Expecting value". Clear saved
        # tokens so the next attempt does a clean re-login.
        clear_session()
        return 0, (
            "Garmin returned an unexpected response during login "
            "(likely a temporary rate-limit). "
            "Wait 15–30 minutes then try syncing again."
        )
    except Exception as e:
        msg = str(e)
        if "429" in msg or "too many" in msg.lower():
            return 0, (
                "Garmin has temporarily blocked login attempts from this IP "
                "(too many recent tries). Wait a few hours — do NOT retry — "
                "then run: venv/bin/python scripts/garmin_setup.py"
            )
        if "extra data" in msg.lower() or "expecting value" in msg.lower() or "unexpected error" in msg.lower():
            clear_session()
            return 0, (
                "Garmin is showing a reCaptcha/bot-protection page — "
                "this happens after repeated failed logins. "
                "Wait several hours without retrying, then run: "
                "venv/bin/python scripts/garmin_setup.py"
            )
        if "mfa" in msg.lower() or "2fa" in msg.lower() or "needs_mfa" in msg.lower():
            return 0, (
                "Garmin requires two-factor authentication. "
                "Open the Garmin Connect app, approve the login prompt, "
                "then click Sync again within 60 seconds."
            )
        if "auth" in msg.lower() or "password" in msg.lower() or "credential" in msg.lower():
            return 0, "Garmin login failed — check your email/password in the .env file."
        return 0, f"Garmin login failed: {msg}"

    # ── Fetch activities ──────────────────────────────────────────────────────
    ftp  = float(get_setting("ftp_watts", 0) or 0)
    lthr = float(get_setting("lthr", 0) or 0)

    end_date   = date.today()
    start_date = end_date - timedelta(days=days_back)

    try:
        activities = client.get_activities_by_date(
            start_date.isoformat(), end_date.isoformat()
        )
    except Exception as e:
        # Clear saved tokens so next sync forces a fresh login
        clear_session()
        return 0, f"Failed to fetch activities: {e}. Session cleared — try syncing again."

    count = 0
    for act in activities:
        activity_type = (
            act.get("activityType", {}).get("typeKey", "")
            .lower().replace(" ", "_")
        )
        if activity_type not in CYCLING_TYPES:
            continue

        duration_s  = float(act.get("duration") or 0)
        moving_s    = float(act.get("movingDuration") or duration_s)
        avg_hr      = act.get("averageHR")
        max_hr      = act.get("maxHR")
        avg_power   = act.get("avgPower")
        norm_power  = act.get("normPower") or avg_power

        tss = _power_tss(duration_s, norm_power, ftp)
        if tss is None:
            tss = _hr_tss(duration_s, avg_hr, lthr)

        if_value = (norm_power / ftp) if norm_power and ftp else None
        start_local = act.get("startTimeLocal", "")[:10]

        zones = estimate_zone_seconds(
            duration_s, avg_hr, max_hr, avg_power, norm_power, ftp, lthr,
        )

        upsert_activity({
            "source": "garmin",
            "external_id": f"garmin_{act.get('activityId', '')}",
            "date": start_local,
            "name": act.get("activityName", "Garmin Activity"),
            "sport_type": activity_type,
            "duration_seconds": int(moving_s),
            "elapsed_seconds": int(duration_s),
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
        })
        count += 1

    set_setting("garmin_last_sync", datetime.utcnow().isoformat())
    note = " (tokens reused — no re-login)" if login_method == "session_reused" else ""
    return count, f"Synced {count} cycling activities from Garmin.{note}"
