"""
Numbers for the Dashboard and Data pages. Everything here is pure: lists of
activity dicts in, plain values out, so it is tested without a database.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from metrics.units import num as _num

# Durations shown on the peak power curve and in the key durations table, in seconds.
PEAK_DURATIONS = (1, 2, 5, 10, 20, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200)
KEY_DURATIONS = (5, 60, 300, 1200, 3600)

RIDE_KINDS = {
    "Indoor": ("virtualride", "virtual_ride", "indoor_cycling", "virtual cycling", "indoor cycling"),
    "Gravel": ("gravelride", "gravel_cycling", "gravel cycling"),
    "Mountain": ("mountainbikeride", "mountain_biking", "mountain biking"),
}


def ride_kind(row: dict) -> str:
    """A short label for a ride type: Indoor, Gravel, Mountain or Road."""
    sport = (row.get("sport_type") or "").lower()
    for label, keys in RIDE_KINDS.items():
        if sport in keys:
            return label
    return "Road"


def duration_label(secs: int) -> str:
    if secs < 60:
        return f"{secs} s"
    if secs < 3600:
        return f"{secs // 60} min"
    return f"{secs // 3600} h"


# ── Filters ───────────────────────────────────────────────────────────────────

@dataclass
class Filters:
    start: date
    end: date
    text: str = ""
    kinds: tuple = ()                       # ride_kind labels; empty means all
    tss: tuple | None = None                # (low, high)
    intensity: tuple | None = None          # IF (low, high)
    minutes: tuple | None = None            # moving time (low, high)
    km: tuple | None = None                 # distance (low, high)
    has_power: bool = False
    has_hr: bool = False

    def narrowed(self) -> bool:
        """True when anything beyond the date range is set."""
        return bool(self.text.strip() or self.kinds or self.tss or self.intensity
                    or self.minutes or self.km or self.has_power or self.has_hr)

    def previous(self) -> "Filters":
        """The same filters over the period of equal length just before."""
        days = (self.end - self.start).days + 1
        return Filters(**{**self.__dict__, "start": self.start - timedelta(days=days),
                          "end": self.start - timedelta(days=1)})


def _within(value, rng) -> bool:
    if not rng:
        return True
    if value is None:
        return False
    low, high = rng
    return low <= value <= high


def filter_rides(rows: list, f: Filters) -> list:
    """Rides in the date range that match every filter. Name search ignores case
    and needs every word to appear somewhere in the name."""
    from db.queries import is_ride
    words = f.text.lower().split()
    out = []
    for r in rows:
        day = str(r.get("date") or "")[:10]
        if not is_ride(r) or not (f.start.isoformat() <= day <= f.end.isoformat()):
            continue
        name = (r.get("name") or "").lower()
        if any(w not in name for w in words):
            continue
        if f.kinds and ride_kind(r) not in f.kinds:
            continue
        if not _within(_num(r.get("tss")), f.tss):
            continue
        if not _within(_num(r.get("if_value")), f.intensity):
            continue
        secs = _num(r.get("duration_seconds"))
        if not _within(secs / 60 if secs is not None else None, f.minutes):
            continue
        meters = _num(r.get("distance_meters"))
        if not _within(meters / 1000 if meters is not None else None, f.km):
            continue
        if f.has_power and not _num(r.get("avg_power_watts")):
            continue
        if f.has_hr and not _num(r.get("avg_hr")):
            continue
        out.append(r)
    return out


# ── Summaries ─────────────────────────────────────────────────────────────────

def _ef(r: dict) -> float | None:
    np_, hr = _num(r.get("normalized_power")), _num(r.get("avg_hr"))
    return np_ / hr if np_ and hr else None


def summary(rows: list) -> dict:
    """Totals for a list of rides. Averages skip rides without the value."""
    def total(key):
        return sum(_num(r.get(key)) or 0.0 for r in rows)

    kj = sum((_num(r.get("avg_power_watts")) or 0) * (_num(r.get("duration_seconds")) or 0)
             for r in rows) / 1000
    ifs = [x for x in (_num(r.get("if_value")) for r in rows) if x]
    efs = [x for x in (_ef(r) for r in rows) if x]
    return {
        "rides": len(rows),
        "hours": total("duration_seconds") / 3600,
        "km": total("distance_meters") / 1000,
        "climb_m": total("elevation_gain_meters"),
        "tss": total("tss"),
        "kj": kj,
        "avg_if": sum(ifs) / len(ifs) if ifs else None,
        "avg_ef": sum(efs) / len(efs) if efs else None,
    }


def deltas(now: dict, before: dict) -> dict:
    """Change from the previous period, None where either side has no value."""
    out = {}
    for k, v in now.items():
        b = before.get(k)
        out[k] = (v - b) if v is not None and b is not None else None
    return out


# ── Over time ─────────────────────────────────────────────────────────────────

def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def weeks_between(start: date, end: date) -> list[date]:
    out, w = [], _monday(start)
    while w <= end:
        out.append(w)
        w += timedelta(days=7)
    return out


WEEKLY_METRICS = {
    "TSS": lambda r: _num(r.get("tss")) or 0.0,
    "Hours": lambda r: (_num(r.get("duration_seconds")) or 0.0) / 3600,
    "Distance km": lambda r: (_num(r.get("distance_meters")) or 0.0) / 1000,
    "Elevation m": lambda r: _num(r.get("elevation_gain_meters")) or 0.0,
}


def weekly(rows: list, metric: str, start: date, end: date) -> list[tuple[str, float]]:
    """(Monday ISO date, total) for every week touching the range, zeros included."""
    fn = WEEKLY_METRICS[metric]
    totals = {w.isoformat(): 0.0 for w in weeks_between(start, end)}
    for r in rows:
        try:
            week = _monday(date.fromisoformat(str(r.get("date"))[:10])).isoformat()
        except ValueError:
            continue
        if week in totals:
            totals[week] += fn(r)
    return sorted(totals.items())


def planned_vs_done(workouts: list, rows: list, start: date, end: date) -> list[dict]:
    """Planned TSS against ridden TSS per week."""
    planned = dict(weekly([{"date": w.get("date"), "tss": w.get("tss_planned")} for w in workouts],
                          "TSS", start, end))
    done = dict(weekly(rows, "TSS", start, end))
    return [{"week": w, "planned": planned[w], "done": done[w]} for w in sorted(planned)]


def efficiency(rows: list, window: int = 5) -> list[dict]:
    """Efficiency factor (NP divided by average heart rate) per ride, oldest first,
    with a rolling mean over the last `window` rides. Rides without both are skipped."""
    points = sorted(({"date": str(r.get("date"))[:10], "name": r.get("name") or "Ride", "ef": _ef(r)}
                     for r in rows if _ef(r)), key=lambda p: p["date"])
    for i, p in enumerate(points):
        recent = [q["ef"] for q in points[max(0, i - window + 1): i + 1]]
        p["rolling"] = sum(recent) / len(recent)
    return points


def zone_hours(rows: list) -> list[float]:
    """Hours in each of the five heart rate zones, from the stored estimates
    (metrics.zones.estimate_zone_seconds writes {"z1_s": ..., "z5_s": ...})."""
    hours = [0.0] * 5
    for r in rows:
        try:
            secs = json.loads(r.get("zone_time_json") or "null")
        except (TypeError, ValueError):
            continue
        if isinstance(secs, dict):
            for i in range(5):
                hours[i] += (_num(secs.get(f"z{i + 1}_s")) or 0.0) / 3600
    return hours


def peak_curve(peak_rows: list, activity_ids: set | None = None) -> dict[int, dict]:
    """Best watts per duration with the ride that set it. `peak_rows` come from
    db.queries.get_peaks_between; `activity_ids` limits it to filtered rides."""
    best: dict[int, dict] = {}
    for p in peak_rows:
        if activity_ids is not None and p["activity_id"] not in activity_ids:
            continue
        d, w = int(p["duration_s"]), _num(p["watts"])
        if w is None:
            continue
        if d not in best or w > best[d]["watts"]:
            best[d] = {"watts": w, "date": p["date"], "name": p.get("name") or "Ride"}
    return dict(sorted(best.items()))


# ── Fitness history (weeks, months, all time) ─────────────────────────────────

HISTORY_DURATIONS = (5, 60, 300, 1200, 3600)


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _add_months(d: date, n: int) -> date:
    idx = d.year * 12 + d.month - 1 + n
    return date(idx // 12, idx % 12 + 1, 1)


def period_history(rides: list, power_rows: list, hr_rows: list, today: date, *,
                   weeks: int = 4, months: int = 13,
                   durations=HISTORY_DURATIONS) -> list[dict]:
    """Rows for the fitness history tables, like TrainingPeaks: the current week
    and the ones before it, the current month and the ones before it, then all time.
    Each row has totals (seconds, meters, tss, kj) and the best power and heart rate
    for each duration. `current` marks the week and month still in progress."""
    from db.queries import is_ride

    def blank(section, label, start, end, current=False):
        return {"section": section, "label": label, "start": start, "end": end, "current": current,
                "rides": 0, "seconds": 0.0, "meters": 0.0, "tss": 0.0, "kj": 0.0,
                "power": {}, "hr": {}}

    rows = []
    this_week = _monday(today)
    for i in range(weeks):
        start = this_week - timedelta(days=7 * i)
        rows.append(blank("week", f"{start.month}/{start.day}/{start.year}", start,
                          start + timedelta(days=6), current=i == 0))
    this_month = _month_start(today)
    for i in range(months):
        start = _add_months(this_month, -i)
        rows.append(blank("month", f"{start:%B} '{start:%y}", start,
                          _add_months(start, 1) - timedelta(days=1), current=i == 0))
    rows.append(blank("all", "All time", date.min, date.max))

    def rows_for(day_iso: str):
        try:
            d = date.fromisoformat(str(day_iso)[:10])
        except ValueError:
            return []
        return [r for r in rows if r["start"] <= d <= r["end"]]

    for ride in rides:
        if not is_ride(ride):
            continue
        for r in rows_for(ride.get("date")):
            r["rides"] += 1
            r["seconds"] += _num(ride.get("duration_seconds")) or 0
            r["meters"] += _num(ride.get("distance_meters")) or 0
            r["tss"] += _num(ride.get("tss")) or 0
            r["kj"] += ((_num(ride.get("avg_power_watts")) or 0)
                        * (_num(ride.get("duration_seconds")) or 0)) / 1000

    for source, key, field in ((power_rows, "power", "watts"), (hr_rows, "hr", "bpm")):
        for p in source:
            d, v = int(p["duration_s"]), _num(p.get(field))
            if d not in durations or v is None:
                continue
            for r in rows_for(p.get("date")):
                if v > r[key].get(d, 0):
                    r[key][d] = v
    return rows


# ── Power profile (Allen and Coggan) ──────────────────────────────────────────
# Lower bound in W/kg of each category, from untrained up to world class, as
# published in Allen and Coggan's power profile chart ("Training and Racing with
# a Power Meter"). Values from github.com/pulmark/cycling-power-profile
# (misc/CyclingPowerProfileChartSimple.json); the last number is the top of the chart.

PROFILE_CATEGORIES = ["Untrained", "Fair (Cat 5)", "Moderate (Cat 4)", "Good (Cat 3)",
                      "Very good (Cat 2)", "Excellent (Cat 1)", "Exceptional (domestic pro)",
                      "World class (international pro)"]
PROFILE_TABLES = {
    "Men": {
        "5s": [10.17, 11.80, 13.44, 15.07, 16.97, 18.60, 20.23, 21.86, 24.04],
        "1min": [5.64, 6.33, 7.02, 7.71, 8.51, 9.20, 9.89, 10.58, 11.50],
        "5min": [2.33, 2.95, 3.57, 4.19, 4.91, 5.53, 6.15, 6.77, 7.60],
        "ft": [1.86, 2.40, 2.93, 3.47, 4.09, 4.62, 5.15, 5.69, 6.40],
    },
    "Women": {
        "5s": [8.43, 9.72, 11.01, 12.31, 13.82, 15.11, 16.40, 17.70, 19.42],
        "1min": [4.67, 5.21, 5.76, 6.30, 6.93, 7.48, 8.02, 8.56, 9.29],
        "5min": [1.89, 2.45, 3.00, 3.56, 4.20, 4.76, 5.31, 5.87, 6.61],
        "ft": [1.50, 1.99, 2.49, 2.98, 3.55, 4.05, 4.54, 5.03, 5.69],
    },
}
# Which column each duration is read against. 20 minute power is taken at 95% as
# an estimate of functional threshold; 60 minute power is threshold itself.
PROFILE_DURATIONS = ((5, "5s", 1.0), (60, "1min", 1.0), (300, "5min", 1.0),
                     (1200, "ft", 0.95), (3600, "ft", 1.0))


def profile_level(wkg: float, bounds: list[float]) -> float:
    """Position on the chart from 0 (bottom of Untrained) to 8 (top of World class),
    linear within each category."""
    if wkg <= bounds[0]:
        return max(0.0, wkg / bounds[0] * 0.5)   # below the chart: a stub inside Untrained
    for i in range(8):
        low, high = bounds[i], bounds[i + 1]
        if wkg < high:
            return i + (wkg - low) / (high - low)
    return 8.0


def power_profile(best: dict, weight_kg: float, table: str = "Men") -> list[dict]:
    """For 5 s, 1, 5, 20 and 60 min: watts, W/kg, the category and the chart level.
    Durations without data are left out."""
    if not weight_kg or weight_kg <= 0:
        return []
    out = []
    for secs, column, factor in PROFILE_DURATIONS:
        entry = best.get(secs)
        watts = entry["watts"] if isinstance(entry, dict) else entry
        if not watts:
            continue
        wkg = watts / weight_kg
        level = profile_level(wkg * factor, PROFILE_TABLES[table][column])
        out.append({"secs": secs, "label": duration_label(secs), "watts": watts, "wkg": wkg,
                    "level": level, "category": PROFILE_CATEGORIES[min(int(level), 7)]})
    return out
