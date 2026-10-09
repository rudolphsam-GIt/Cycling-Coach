"""
Checking the app's scores against TrainingPeaks or intervals.icu.

Each service's completed workouts are mapped into one shape, so matching them to the app's
activities works the same for both:

    {"day": "2026-10-09", "hours": 1.5, "tss": 80.0, "np": 250, "avg_hr": 140,
     "kind": "bike" or "other", "scored_by": "power" / "hr" / "manual" / "other", "raw": {...}}

A service's numbers are only kept next to the app's own score (activities.ref_json) to flag big
differences. They never change the app's score.
"""
from __future__ import annotations

from metrics.tss import DEFAULT_STANDARD, SERVICE_NAMES, STANDARDS

MATCH_WITHIN_H = 0.75    # services often count stops the app leaves out


def standard() -> str:
    """The "Score like" setting: trainingpeaks, intervals or standard."""
    from db import queries as q
    s = q.get_setting("score_like", "") or ""
    return s if s in STANDARDS else DEFAULT_STANDARD


def connected(service: str) -> bool:
    if service == "trainingpeaks":
        from auth import trainingpeaks
        return trainingpeaks.is_enabled()
    if service == "intervals":
        from auth import intervals
        return intervals.is_connected()
    return False


def compare_service(score_like: str | None = None) -> str | None:
    """The service rides are checked against: the chosen standard's own service, or for the
    published standard whichever is connected (TrainingPeaks first), else None."""
    std = STANDARDS.get(score_like or standard(), STANDARDS[DEFAULT_STANDARD])
    if std["compare"]:
        return std["compare"]
    return next((s for s in ("trainingpeaks", "intervals") if connected(s)), None)


def service_name(service: str | None) -> str:
    return SERVICE_NAMES.get(service or "", service or "")


def match_completed(workouts: list[dict], rides: list[dict]) -> list[tuple[dict, dict]]:
    """Pair a service's completed workouts (normalized, see above) with the app's activities:
    same day, closest duration, within MATCH_WITHIN_H hours."""
    by_day: dict[str, list[dict]] = {}
    for r in rides:
        if r.get("duration_seconds"):
            by_day.setdefault(r["date"], []).append(r)
    pairs, used = [], set()
    for w in sorted(workouts, key=lambda w: w.get("day") or ""):
        if not w.get("tss") or not w.get("hours"):
            continue
        cands = [r for r in by_day.get(w.get("day") or "", []) if r["id"] not in used
                 and abs(r["duration_seconds"] / 3600 - w["hours"]) <= MATCH_WITHIN_H]
        if cands:
            r = min(cands, key=lambda r: match_cost(w, r))
            used.add(r["id"])
            pairs.append((w, r))
    return pairs


def match_cost(w: dict, r: dict) -> float:
    """How unlike a service's workout and an app ride are. Duration alone mixes up two rides of
    similar length on one day (a crit and the ride home), so power and heart rate count too."""
    cost = abs(r["duration_seconds"] / 3600 - w["hours"])
    if w.get("np") and r.get("normalized_power"):
        cost += abs(w["np"] - r["normalized_power"]) / 50
    if w.get("avg_hr") and r.get("avg_hr"):
        cost += abs(w["avg_hr"] - r["avg_hr"]) / 20
    return cost


def numbers(w: dict) -> dict:
    """What is kept from a matched workout, to compare against."""
    return {"tss": round(float(w["tss"]), 1), "hours": w.get("hours"), "np": w.get("np"),
            "avg_hr": w.get("avg_hr"), "scored_by": w.get("scored_by") or "other",
            "title": w.get("title")}


def match_and_store(service: str, workouts: list[dict], acts: list[dict]) -> list[tuple[dict, dict]]:
    """Match bike workouts to rides and other workouts to other sessions, and store the service's
    numbers on each matched activity. Returns the pairs."""
    from db import queries as q
    rides = [r for r in acts if q.is_ride(r)]
    others = [r for r in acts if not q.is_ride(r)]
    pairs = (match_completed([w for w in workouts if w.get("kind") == "bike"], rides)
             + match_completed([w for w in workouts if w.get("kind") != "bike"], others))
    for w, r in pairs:
        q.set_ref_numbers(r["id"], service, numbers(w))
    return pairs
