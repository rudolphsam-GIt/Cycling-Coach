from __future__ import annotations

"""
Estimate competitor power using Strava's public segment leaderboards.

Strategy:
1. Discover popular climb segments in Oregon via Strava's explore API
2. For each segment, fetch the leaderboard and look for the competitor by name
3. When found, use the segment's distance/elevation + their elapsed time to
   calculate an estimated FTP using VAM (Vertical Ascent Meters/hour)

This uses only the authenticated user's Strava token — no scraping Strava HTML.
All data accessed is publicly visible on Strava.
"""

import re
import time
import requests
from math import sqrt

STRAVA_API = "https://www.strava.com/api/v3"

# Oregon bounding box [sw_lat, sw_lng, ne_lat, ne_lng]
OREGON_BBOX = "42.0,-124.5,46.3,-116.5"

# Typical road cyclist aerodynamic constants for flat-road power estimation
CD_A = 0.32       # drag area (m²) — hoods position
RHO = 1.18        # air density kg/m³ (sea level, mild temp)
CRR = 0.004       # rolling resistance
G = 9.81          # m/s²
ASSUMED_MASS_KG = 73.0  # used when we don't know rider weight
DRIVETRAIN_EFF = 0.976  # 97.6% drivetrain efficiency


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _get(path: str, token: str, params: dict | None = None) -> dict | list | None:
    try:
        r = requests.get(f"{STRAVA_API}{path}", headers=_headers(token),
                         params=params or {}, timeout=10)
        if r.status_code == 429:
            return None  # rate limited
        r.raise_for_status()
        time.sleep(0.3)
        return r.json()
    except Exception:
        return None


# ── Segment discovery ─────────────────────────────────────────────────────────

def _explore_segments(token: str, activity_type: str = "riding") -> list[dict]:
    """Return popular segments in Oregon from Strava's explore endpoint."""
    data = _get("/segments/explore", token, {
        "bounds": OREGON_BBOX,
        "activity_type": activity_type,
    })
    if not data or "segments" not in data:
        return []
    return data["segments"]


def _get_segment_detail(segment_id: int, token: str) -> dict | None:
    return _get(f"/segments/{segment_id}", token)


def _get_leaderboard(segment_id: int, token: str,
                     per_page: int = 200) -> list[dict]:
    """
    Fetch all pages of a segment leaderboard.
    Returns list of {athlete_name, elapsed_time, ...}
    """
    entries = []
    page = 1
    while True:
        data = _get(f"/segments/{segment_id}/leaderboard", token, {
            "per_page": per_page,
            "page": page,
        })
        if not data or not data.get("entries"):
            break
        entries.extend(data["entries"])
        if len(data["entries"]) < per_page:
            break
        page += 1
        if page > 5:  # cap at 1000 entries to avoid hammering API
            break
    return entries


# ── Name matching ─────────────────────────────────────────────────────────────

def _name_score(strava_name: str, search_name: str) -> float:
    """
    Return match score 0-1 between a Strava athlete name and search name.
    1.0 = exact match, 0 = no match.
    """
    s = strava_name.lower().strip()
    q = search_name.lower().strip()

    if s == q:
        return 1.0

    s_parts = set(s.split())
    q_parts = set(q.split())

    # Both first and last name present
    if len(q_parts) >= 2 and q_parts.issubset(s_parts):
        return 0.95

    # Last name + first initial
    q_words = q.split()
    if len(q_words) >= 2:
        last = q_words[-1]
        first_init = q_words[0][0]
        if last in s and s.startswith(first_init):
            return 0.80

    # Last name only (if long enough to be distinctive)
    if len(q_words) >= 1 and len(q_words[-1]) >= 5 and q_words[-1] in s:
        return 0.60

    return 0.0


# ── Power calculation from segment ───────────────────────────────────────────

def _power_from_climb(elapsed_s: float, distance_m: float,
                      elevation_m: float, mass_kg: float = ASSUMED_MASS_KG) -> float | None:
    """
    Estimate average power for a climb segment using a physics model.
    Ignores wind (conservative indoor assumption).
    Returns watts or None if inputs are invalid.
    """
    if elapsed_s <= 0 or distance_m <= 0:
        return None

    speed_ms = distance_m / elapsed_s
    grade = elevation_m / distance_m if distance_m > 0 else 0

    # Climbing power
    p_climb = mass_kg * G * speed_ms * grade

    # Rolling resistance
    p_roll = CRR * mass_kg * G * speed_ms

    # Aerodynamic drag (less important on steep climbs)
    p_aero = 0.5 * CD_A * RHO * speed_ms ** 3

    total = (p_climb + p_roll + p_aero) / DRIVETRAIN_EFF
    return round(total, 1) if total > 0 else None


def _power_from_flat(elapsed_s: float, distance_m: float,
                     mass_kg: float = ASSUMED_MASS_KG) -> float | None:
    """
    Estimate average power for a flat/rolling segment.
    Primarily aero-limited model.
    """
    if elapsed_s <= 0 or distance_m <= 0:
        return None

    speed_ms = distance_m / elapsed_s
    p_aero = 0.5 * CD_A * RHO * speed_ms ** 3
    p_roll = CRR * mass_kg * G * speed_ms
    total = (p_aero + p_roll) / DRIVETRAIN_EFF
    return round(total, 1) if total > 0 else None


def _segment_effort_to_ftp(avg_watts: float, duration_s: float) -> float:
    """
    Convert a segment average power to an FTP estimate.

    A segment is typically raced at above-FTP intensity, so we discount:
    - < 3 min  → likely VO2max effort → FTP ≈ avg × 0.72
    - 3-8 min  → above threshold    → FTP ≈ avg × 0.80
    - 8-20 min → near threshold     → FTP ≈ avg × 0.90
    - > 20 min → near FTP           → FTP ≈ avg × 0.95
    """
    min_ = duration_s / 60
    if min_ < 3:
        factor = 0.72
    elif min_ < 8:
        factor = 0.80
    elif min_ < 20:
        factor = 0.90
    else:
        factor = 0.95
    return round(avg_watts * factor, 1)


# ── Public entry point ────────────────────────────────────────────────────────

def estimate_strava_power(
    competitor_name: str,
    token: str,
    assumed_weight_kg: float = ASSUMED_MASS_KG,
) -> dict | None:
    """
    Try to find a competitor on Oregon Strava segment leaderboards and estimate
    their FTP from their segment times.

    Returns dict with ftp_est, wkg_est, source_segment, confidence, note
    or None if the competitor wasn't found on any leaderboard.
    """
    segments = _explore_segments(token)
    if not segments:
        return None

    best_match: dict | None = None
    best_score = 0.0

    for seg_summary in segments:
        seg_id = seg_summary.get("id")
        if not seg_id:
            continue

        # Prefer climb segments (more distinctive / power-revealing)
        elev = seg_summary.get("elev_difference", 0) or 0
        dist = seg_summary.get("distance", 0) or 0

        leaderboard = _get_leaderboard(seg_id, token)
        if not leaderboard:
            continue

        for entry in leaderboard:
            athlete = entry.get("athlete_name", "")
            score = _name_score(athlete, competitor_name)
            if score < 0.60:
                continue

            elapsed = entry.get("elapsed_time", 0)
            if not elapsed:
                continue

            # Calculate power
            if elev > 30:  # meaningful climb
                avg_w = _power_from_climb(elapsed, dist, elev, assumed_weight_kg)
            else:
                avg_w = _power_from_flat(elapsed, dist, assumed_weight_kg)

            if not avg_w:
                continue

            ftp_est = _segment_effort_to_ftp(avg_w, elapsed)
            wkg_est = round(ftp_est / assumed_weight_kg, 2)

            if score > best_score:
                best_score = score
                seg_name = seg_summary.get("name", "Oregon segment")
                dur_min = round(elapsed / 60, 1)
                best_match = {
                    "ftp_est": int(ftp_est),
                    "wkg_est": wkg_est,
                    "avg_watts_on_segment": int(avg_w),
                    "source_segment": seg_name,
                    "segment_elapsed_min": dur_min,
                    "segment_elevation_m": round(elev),
                    "assumed_weight_kg": assumed_weight_kg,
                    "name_match_score": round(score, 2),
                    "confidence": "High" if score >= 0.95 else "Medium",
                    "note": (
                        f"From Strava leaderboard: {seg_name} "
                        f"({dur_min} min, {round(elev)}m elev) → "
                        f"~{int(avg_w)}W avg → ~{int(ftp_est)}W FTP est."
                    ),
                }

        if best_match and best_score >= 0.95:
            break  # exact name match found — stop searching

    return best_match
