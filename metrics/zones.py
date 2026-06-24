"""Power and HR zone calculations."""
from __future__ import annotations

import math

POWER_ZONE_NAMES = [
    "Z1 Active Recovery",
    "Z2 Endurance",
    "Z3 Tempo",
    "Z4 Threshold",
    "Z5 VO2 Max",
    "Z6 Anaerobic",
    "Z7 Neuromuscular",
]

# Lower bound as % of FTP (upper is next zone's lower - 1)
POWER_ZONE_PCT = [0, 55, 75, 90, 105, 121, 151, 999]

HR_ZONE_NAMES = [
    "Z1 Active Recovery",
    "Z2 Endurance",
    "Z3 Tempo",
    "Z4 Threshold",
    "Z5 VO2 Max",
]

# Lower bound as % of LTHR
HR_ZONE_PCT = [0, 69, 84, 95, 105, 999]

ZONE_COLORS = ["#9ecae1", "#41ab5d", "#fdae6b", "#e6550d", "#bd0026", "#6a51a3", "#252525"]


def get_power_zones(ftp: float) -> list[dict]:
    if not ftp:
        return []
    zones = []
    for i, name in enumerate(POWER_ZONE_NAMES):
        lo = round(ftp * POWER_ZONE_PCT[i] / 100)
        hi = round(ftp * POWER_ZONE_PCT[i + 1] / 100) - 1
        zones.append({
            "zone": i + 1,
            "name": name,
            "min_watts": lo,
            "max_watts": hi if i < 6 else None,
            "color": ZONE_COLORS[i],
        })
    return zones


def get_hr_zones(lthr: float) -> list[dict]:
    if not lthr:
        return []
    zones = []
    for i, name in enumerate(HR_ZONE_NAMES):
        lo = round(lthr * HR_ZONE_PCT[i] / 100)
        hi = round(lthr * HR_ZONE_PCT[i + 1] / 100) - 1
        zones.append({
            "zone": i + 1,
            "name": name,
            "min_bpm": lo,
            "max_bpm": hi if i < 4 else None,
            "color": ZONE_COLORS[i],
        })
    return zones


def watts_to_zone(watts: float, ftp: float) -> int:
    if not ftp or not watts:
        return 0
    pct = watts / ftp * 100
    for i in range(len(POWER_ZONE_PCT) - 1):
        if pct < POWER_ZONE_PCT[i + 1]:
            return i + 1
    return 7


def _hr_to_zone(hr: float, lthr: float) -> int:
    """Map an HR value to zone 1-5."""
    pct = hr / lthr * 100
    for i in range(len(HR_ZONE_PCT) - 1):
        if pct < HR_ZONE_PCT[i + 1]:
            return i + 1
    return 5


def estimate_zone_seconds(
    duration_s: float,
    avg_hr: float | None,
    max_hr: float | None,
    avg_power: float | None,
    norm_power: float | None,
    ftp: float,
    lthr: float,
) -> dict | None:
    """
    Estimate seconds in each HR zone (Z1–Z5) from ride summary stats.

    Uses a Gaussian distribution centered on the avg HR zone. The spread
    (sigma) widens with variability index (NP/avg_power), so interval
    workouts show a broader zone distribution than steady endurance rides.
    """
    if not lthr or not avg_hr or not duration_s:
        return None

    avg_zone = _hr_to_zone(avg_hr, lthr)           # 1-5
    max_zone = _hr_to_zone(max_hr, lthr) if max_hr else 5

    # Variability index: how evenly-paced was the effort?
    if norm_power and avg_power and avg_power > 0:
        vi = norm_power / avg_power
    else:
        vi = 1.05  # assume mild variability when unknown

    if vi < 1.05:
        sigma = 0.4   # steady state — tight distribution
    elif vi < 1.12:
        sigma = 0.75  # moderate variation
    else:
        sigma = 1.2   # intervals — wide spread

    center = avg_zone - 1  # convert to 0-indexed
    weights = []
    for i in range(5):
        if i > max_zone - 1:
            # Can't spend time above max achieved zone
            weights.append(0.0)
        else:
            weights.append(math.exp(-((i - center) ** 2) / (2 * sigma ** 2)))

    total = sum(weights)
    if total == 0:
        return None
    weights = [w / total for w in weights]

    return {
        "z1_s": round(duration_s * weights[0]),
        "z2_s": round(duration_s * weights[1]),
        "z3_s": round(duration_s * weights[2]),
        "z4_s": round(duration_s * weights[3]),
        "z5_s": round(duration_s * weights[4]),
        "source": "estimated",
    }
