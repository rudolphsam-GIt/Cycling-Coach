from __future__ import annotations

"""
Power profiling — estimate competitor FTP and W/kg from OBRA category + race results.

Standards sourced from:
- USA Cycling category upgrade criteria
- Training Peaks power profiling tables (Coggan/Allen)
- Academic literature on amateur road cyclists (Lucia et al., Rønnestad et al.)

These are ranges for the *mid-pack rider at that category level*.
Elite within a category will be at the top of the range; newer/back-of-pack at the bottom.
"""

import re

# ── Category power standards ─────────────────────────────────────────────────
# W/kg at FTP for male road cyclists
STANDARDS_MEN = {
    1: {"wkg_low": 4.5, "wkg_mid": 5.0, "wkg_high": 5.8,
        "label": "Cat 1 — Elite amateur"},
    2: {"wkg_low": 3.8, "wkg_mid": 4.2, "wkg_high": 4.7,
        "label": "Cat 2 — Advanced"},
    3: {"wkg_low": 3.2, "wkg_mid": 3.6, "wkg_high": 3.9,
        "label": "Cat 3 — Intermediate"},
    4: {"wkg_low": 2.6, "wkg_mid": 3.0, "wkg_high": 3.3,
        "label": "Cat 4 — Developing"},
    5: {"wkg_low": 1.9, "wkg_mid": 2.4, "wkg_high": 2.7,
        "label": "Cat 5 — Beginner"},
}

# W/kg at FTP for female road cyclists (roughly 10-15% lower due to physiology)
STANDARDS_WOMEN = {
    1: {"wkg_low": 3.8, "wkg_mid": 4.2, "wkg_high": 5.0,
        "label": "Women Cat 1/2 — Elite"},
    2: {"wkg_low": 3.2, "wkg_mid": 3.6, "wkg_high": 4.0,
        "label": "Women Cat 3 — Advanced"},
    3: {"wkg_low": 2.6, "wkg_mid": 3.0, "wkg_high": 3.3,
        "label": "Women Cat 4 — Intermediate"},
    4: {"wkg_low": 2.0, "wkg_mid": 2.4, "wkg_high": 2.7,
        "label": "Women Cat 5 — Developing"},
    5: {"wkg_low": 1.5, "wkg_mid": 1.9, "wkg_high": 2.2,
        "label": "Women Cat 5 — Beginner"},
}

# Assumed average weights for FTP watt conversion when no weight is known
AVG_WEIGHT_MEN_KG = 73.0
AVG_WEIGHT_WOMEN_KG = 62.0


def _parse_placement(result_text: str) -> int | None:
    """Extract numeric placement from a result string like '1st', '3rd', '12th'."""
    m = re.search(r'\b(\d+)(st|nd|rd|th)\b', result_text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # "Place 3" style
    m = re.search(r'place\s+(\d+)', result_text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _parse_field_size(result_text: str) -> int | None:
    """Extract field size from text like '3rd of 24' or '/ 24'."""
    m = re.search(r'\bof\s+(\d+)\b', result_text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r'/\s*(\d+)', result_text)
    if m:
        return int(m.group(1))
    return None


def _result_adjustment(results: list[str]) -> tuple[float, str]:
    """
    Analyse result strings and return (wkg_adjustment, confidence).
    Positive adjustment → upper portion of category range.
    Negative → lower portion.
    """
    if not results:
        return 0.0, "Low — no results found"

    placements = []
    pct_finishes = []  # placement as % of field (0=win, 1=last)

    for r in results:
        place = _parse_placement(r)
        field = _parse_field_size(r)
        if place:
            placements.append(place)
            if field and field > 0:
                pct_finishes.append((place - 1) / field)

    total = len(placements)
    if total == 0:
        return 0.0, "Low — results found but no placements parsed"

    # Confidence scales with number of parseable results
    if total >= 8:
        confidence = "High"
    elif total >= 4:
        confidence = "Medium"
    else:
        confidence = "Low-medium"

    # Adjustment: based on median finish percentile (0=always wins, 1=always last)
    if pct_finishes:
        median_pct = sorted(pct_finishes)[len(pct_finishes) // 2]
        # Top 20% of field → +0.15 W/kg; bottom 50% → -0.15 W/kg
        if median_pct < 0.10:
            adj = 0.20   # dominant — likely upgrading or at ceiling of category
        elif median_pct < 0.25:
            adj = 0.12
        elif median_pct < 0.40:
            adj = 0.05
        elif median_pct < 0.60:
            adj = 0.0    # mid-pack
        elif median_pct < 0.80:
            adj = -0.08
        else:
            adj = -0.15  # consistently back — lower end of category range
    else:
        # Fall back to raw placement count
        top3 = sum(1 for p in placements if p <= 3)
        top10 = sum(1 for p in placements if p <= 10)
        if top3 / total > 0.4:
            adj = 0.15
        elif top10 / total > 0.5:
            adj = 0.05
        else:
            adj = -0.05

    return adj, confidence


def estimate_power_profile(
    category: int | None,
    results: list[str] | None = None,
    gender: str = "M",
    known_weight_kg: float | None = None,
) -> dict | None:
    """
    Estimate FTP and W/kg for a rider.

    Returns dict with:
      wkg_est, wkg_low, wkg_high,
      ftp_est, ftp_low, ftp_high,
      assumed_weight_kg, confidence, note
    Returns None if category is unknown.
    """
    if not category or category not in range(1, 6):
        return None

    standards = STANDARDS_MEN if gender != "F" else STANDARDS_WOMEN
    avg_weight = known_weight_kg or (
        AVG_WEIGHT_MEN_KG if gender != "F" else AVG_WEIGHT_WOMEN_KG
    )

    std = standards[category]
    adj, confidence = _result_adjustment(results or [])

    wkg_est = std["wkg_mid"] + adj
    wkg_est = max(std["wkg_low"], min(std["wkg_high"], wkg_est))

    ftp_est = round(wkg_est * avg_weight)
    ftp_low = round(std["wkg_low"] * avg_weight)
    ftp_high = round(std["wkg_high"] * avg_weight)

    note_parts = [f"Category {category} power standards"]
    if results:
        note_parts.append(f"{len(results)} OBRA results analysed")
    if adj > 0.05:
        note_parts.append("adjusted up — strong results")
    elif adj < -0.05:
        note_parts.append("adjusted down — mid/back-of-pack results")

    return {
        "wkg_est": round(wkg_est, 2),
        "wkg_low": std["wkg_low"],
        "wkg_high": std["wkg_high"],
        "ftp_est": ftp_est,
        "ftp_low": ftp_low,
        "ftp_high": ftp_high,
        "assumed_weight_kg": avg_weight,
        "confidence": confidence,
        "label": std["label"],
        "note": " · ".join(note_parts),
    }


def threat_level(profile: dict, your_wkg: float) -> str:
    """
    Compare estimated W/kg to yours and return a threat label.
    """
    if not profile:
        return "Unknown"
    gap = profile["wkg_est"] - your_wkg
    if gap > 0.4:
        return "High threat 🔴"
    elif gap > 0.1:
        return "Moderate threat 🟡"
    elif gap > -0.2:
        return "Similar 🟢"
    else:
        return "Likely slower 🔵"
