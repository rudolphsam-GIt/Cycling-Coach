from __future__ import annotations

"""
Strava OAuth2 flow for a local Streamlit app.

Flow:
1. User clicks "Connect Strava" → opens auth URL in browser
2. Strava redirects to http://localhost/?code=XXXX (browser shows connection refused — that's fine)
3. User copies the full URL from the address bar and pastes it into the app
4. We extract the code and exchange it for tokens
"""

import requests
import time
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta
from db.queries import get_setting, set_setting, upsert_activity, get_daily_tss
from metrics.zones import estimate_zone_seconds
import json

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"
REDIRECT_URI = "http://localhost"


def get_auth_url(client_id: str) -> str:
    return (
        f"{STRAVA_AUTH_URL}?client_id={client_id}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=read,activity:read_all"
    )


def extract_code_from_redirect(redirect_url: str) -> str | None:
    """Parse the code parameter out of the redirect URL the user pastes."""
    try:
        parsed = urlparse(redirect_url)
        params = parse_qs(parsed.query)
        codes = params.get("code", [])
        return codes[0] if codes else None
    except Exception:
        return None


def exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    resp = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    _save_tokens(data)
    return data


def _save_tokens(token_data: dict):
    set_setting("strava_access_token", token_data["access_token"])
    set_setting("strava_refresh_token", token_data["refresh_token"])
    set_setting("strava_token_expires_at", str(token_data["expires_at"]))
    if "athlete" in token_data:
        set_setting("strava_athlete_name",
                    f"{token_data['athlete'].get('firstname','')} {token_data['athlete'].get('lastname','')}".strip())


def get_valid_token(client_id: str, client_secret: str) -> str | None:
    access_token = get_setting("strava_access_token")
    refresh_token = get_setting("strava_refresh_token")
    expires_at = get_setting("strava_token_expires_at")

    if not access_token or not refresh_token:
        return None

    # Refresh if expiring within 5 minutes
    if expires_at and int(expires_at) < (time.time() + 300):
        try:
            resp = requests.post(
                STRAVA_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=15,
            )
            resp.raise_for_status()
            _save_tokens(resp.json())
            return resp.json()["access_token"]
        except Exception:
            return None

    return access_token


def is_connected() -> bool:
    return bool(get_setting("strava_access_token"))


def _compute_tss(duration_s: float, normalized_power: float, ftp: float) -> float | None:
    if not ftp or ftp <= 0 or not normalized_power or normalized_power <= 0:
        return None
    intensity_factor = normalized_power / ftp
    return (duration_s * normalized_power * intensity_factor) / (ftp * 3600) * 100


def _compute_hr_tss(duration_s: float, avg_hr: float, lthr: float) -> float | None:
    if not lthr or lthr <= 0 or not avg_hr or avg_hr <= 0:
        return None
    duration_h = duration_s / 3600
    return duration_h * ((avg_hr / lthr) ** 2) * 100


def _estimate_tss(duration_s: float, perceived_exertion: float | None,
                  avg_hr: float | None, max_hr: float | None) -> float:
    """
    Fallback TSS estimate when no power meter and no LTHR is set.
    Uses Strava's perceived_exertion (1-10 scale) if available,
    otherwise estimates from HR ratio or defaults to a moderate effort assumption.
    TSS ≈ duration_hours × IF² × 100
    """
    duration_h = duration_s / 3600

    # Strava perceived_exertion is 1-10; map to intensity factor 0.4-1.05
    if perceived_exertion and 1 <= perceived_exertion <= 10:
        intensity_factor = 0.4 + (perceived_exertion - 1) * 0.072
        return round(duration_h * intensity_factor ** 2 * 100, 1)

    # HR ratio fallback: if we have avg and max HR, estimate relative intensity
    if avg_hr and max_hr and max_hr > 0:
        hr_ratio = avg_hr / max_hr
        intensity_factor = max(0.4, min(1.05, hr_ratio * 1.05))
        return round(duration_h * intensity_factor ** 2 * 100, 1)

    # Last resort: assume moderate Z2 effort (IF ~0.65, ~42 TSS/hour)
    return round(duration_h * 0.65 ** 2 * 100, 1)


def sync_activities(client_id: str, client_secret: str, days_back: int = 60) -> tuple[int, str]:
    """Fetch recent activities from Strava and store them. Returns (count, message)."""
    token = get_valid_token(client_id, client_secret)
    if not token:
        return 0, "Not connected to Strava. Please authorize first."

    ftp = float(get_setting("ftp_watts", 0) or 0)
    lthr = float(get_setting("lthr", 0) or 0)
    since_ts = int((datetime.utcnow() - timedelta(days=days_back)).timestamp())

    headers = {"Authorization": f"Bearer {token}"}
    page, count = 1, 0

    while True:
        resp = requests.get(
            f"{STRAVA_API_BASE}/athlete/activities",
            headers=headers,
            params={"after": since_ts, "per_page": 50, "page": page},
            timeout=20,
        )
        resp.raise_for_status()
        activities = resp.json()
        if not activities:
            break

        for act in activities:
            np = act.get("weighted_average_watts")
            moving_s = act.get("moving_time", 0)
            elapsed_s = act.get("elapsed_time", moving_s)  # use elapsed for TSS
            avg_power = act.get("average_watts")
            avg_hr = act.get("average_heartrate")
            max_hr = act.get("max_heartrate")

            tss = _compute_tss(elapsed_s, np, ftp) if np else None
            if tss is None:
                tss = _compute_hr_tss(elapsed_s, avg_hr, lthr)
            if tss is None:
                tss = _estimate_tss(elapsed_s, act.get("perceived_exertion"),
                                    avg_hr, max_hr)

            if_value = (np / ftp) if (np and ftp) else None

            zones = estimate_zone_seconds(
                elapsed_s, avg_hr, max_hr, avg_power, np, ftp, lthr,
            )

            upsert_activity({
                "source": "strava",
                "elapsed_seconds": elapsed_s,
                "external_id": f"strava_{act['id']}",
                "date": act["start_date_local"][:10],
                "name": act.get("name", ""),
                "sport_type": act.get("sport_type", act.get("type", "")),
                "duration_seconds": moving_s,
                "distance_meters": act.get("distance", 0),
                "elevation_gain_meters": act.get("total_elevation_gain", 0),
                "avg_power_watts": avg_power,
                "avg_hr": avg_hr,
                "max_hr": max_hr,
                "normalized_power": np,
                "tss": round(tss, 1) if tss else None,
                "if_value": round(if_value, 3) if if_value else None,
                "zone_time_json": json.dumps(zones) if zones else None,
                "raw_json": json.dumps({k: act[k] for k in
                                        ["id", "name", "sport_type", "start_date_local",
                                         "distance", "moving_time", "total_elevation_gain"]
                                        if k in act}),
            })
            count += 1

        if len(activities) < 50:
            break
        page += 1

    set_setting("strava_last_sync", datetime.utcnow().isoformat())
    return count, f"Synced {count} activities from Strava."
