"""
Build a fake training database so the app can be tried or tested without any
real ride data.

    venv/bin/python scripts/seed_demo_db.py /tmp/demo.db          # about 3 months of demo data
    venv/bin/python scripts/seed_demo_db.py /tmp/empty.db --empty # settings only, no rides

Then run the app against it with  CYCLING_COACH_DB=/tmp/demo.db  in front of the start command.
"""
import argparse
import json
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

parser = argparse.ArgumentParser()
parser.add_argument("path", help="where to write the demo database")
parser.add_argument("--empty", action="store_true", help="settings only, no rides or plans")
args = parser.parse_args()

target = Path(args.path).expanduser().resolve()
real = (ROOT / "data" / "cycling.db").resolve()
if target == real:
    sys.exit("Refusing to overwrite your real database. Pick another path.")
if target.exists():
    target.unlink()
target.parent.mkdir(parents=True, exist_ok=True)
os.environ["CYCLING_COACH_DB"] = str(target)  # must be set before the db modules import

from db.schema import run_migrations  # noqa: E402
from db import queries as q  # noqa: E402
from metrics import explain  # noqa: E402

run_migrations()
for key, value in {"ftp_watts": 250, "weight_kg": 72, "lthr": 165, "ctl_start": 40,
                   "primary_goal": "speed", "weekly_hours_target": 8, "days_per_week": 5,
                   "goal_text": "Get faster for road races next spring",
                   "onboarding_complete": "1",
                   # The empty database looks like a rider who has just finished onboarding.
                   "experience_level": "New to structured training" if args.empty
                   else "Some structured training experience",
                   "ftp_estimated": "1" if args.empty else "0"}.items():
    q.set_setting(key, value)
q.log_ftp_history(250, "Demo")

if args.empty:
    print(f"Wrote empty demo database to {target}")
    sys.exit(0)

q.save_phase_notes([{"name": "Build / Threshold", **explain.PHASE_NOTES["Build / Threshold"]}])
rng = random.Random(7)
today = date.today()
FTP = 250
# weekday (Mon = 0) -> (type, name, planned TSS); Mon and Fri are rest days
WEEK = {1: ("Threshold", "Threshold 4x8", 90), 2: ("Endurance", "Endurance Z2", 65),
        3: ("VO2 Max", "VO2 Max 5x4", 85), 5: ("Long Ride", "Long ride", 150),
        6: ("Recovery", "Recovery spin", 30)}


# Best power by duration for a fresh 250 W rider; each ride gets a scaled copy.
BASE_PEAKS = {1: 950, 2: 900, 5: 820, 10: 700, 20: 560, 30: 480, 60: 400, 120: 340, 300: 300,
              600: 280, 1200: 265, 1800: 255, 3600: 240, 7200: 215}


def add_ride(day: date, tss: float, name: str, sport: str = "ride") -> None:
    intensity = min(max(0.5 + tss / 260, 0.55), 1.0)
    hours = tss / (intensity ** 2 * 100)
    shares = [0.25, 0.45, 0.15, 0.1, 0.05] if tss > 70 else [0.4, 0.5, 0.1, 0.0, 0.0]
    secs = int(hours * 3600)
    indoor = sport == "virtual_ride"
    aid = q.upsert_activity({
        "source": "demo", "external_id": f"demo-{day.isoformat()}-{name}",
        "date": day.isoformat(), "name": name, "sport_type": sport,
        "duration_seconds": secs, "elapsed_seconds": secs + 240,
        "distance_meters": hours * 3600 * (9.0 if indoor else 8.2),
        "elevation_gain_meters": 0 if indoor else hours * rng.uniform(150, 450),
        "avg_power_watts": round(intensity * FTP * 0.88), "avg_hr": int(115 + intensity * 45),
        "max_hr": 178, "normalized_power": round(intensity * FTP), "tss": round(tss),
        "if_value": round(intensity, 2), "raw_json": "{}",
        "zone_time_json": json.dumps({f"z{i + 1}_s": int(secs * s) for i, s in enumerate(shares)}
                                     | {"source": "estimated"}),
    })
    if (today - day).days <= 45:
        q.save_streams(aid, fake_streams(name, secs, intensity), "demo")
    # Fitness improves a little over the months, harder rides hit higher peaks.
    form = 0.9 + 0.1 * (1 + (day - today).days / 180) + 0.15 * (intensity - 0.7)
    q.save_peaks(aid, {d: round(w * form * rng.uniform(0.9, 1.03)) for d, w in BASE_PEAKS.items()
                       if d <= secs})
    avg_hr = int(115 + intensity * 45)
    q.save_hr_peaks(aid, {d: min(186, avg_hr + bump + rng.randint(-2, 2))
                          for d, bump in ((5, 26), (10, 25), (30, 23), (60, 21), (120, 18), (300, 14),
                                          (600, 11), (1200, 8), (1800, 6), (3600, 3)) if d <= secs})


def fake_streams(name: str, secs: int, intensity: float) -> dict:
    """A believable second by second ride for the demo, shaped by the workout name."""
    import math
    n = min(secs, 4 * 3600)
    plan = []                                   # (seconds, fraction of FTP)
    lower = name.lower()
    if "threshold" in lower:
        plan = [(600, 0.6)] + [(480, 0.97), (240, 0.5)] * 4 + [(600, 0.5)]
    elif "vo2" in lower:
        plan = [(720, 0.6)] + [(240, 1.18), (240, 0.45)] * 5 + [(600, 0.5)]
    else:
        plan = [(n, intensity * 0.85)]
    power, t = [], 0
    while len(power) < n:
        for length, frac in plan:
            for i in range(length):
                wobble = 1 + 0.07 * math.sin(i / 7) + rng.uniform(-0.05, 0.05)
                coast = 0.0 if rng.random() < 0.01 else 1.0
                power.append(max(0, round(FTP * frac * wobble * coast)))
            if len(power) >= n:
                break
        if len(plan) == 1:
            break
    power = power[:n]
    hr, h = [], 105.0
    for p in power:
        target = 105 + 62 * min(p / FTP, 1.25)
        h += (target - h) * 0.03
        hr.append(round(h + rng.uniform(-1, 1)))
    cad = [round(max(0, 88 + 6 * math.sin(i / 40) + rng.uniform(-4, 4)) * (0 if p == 0 else 1))
           for i, p in enumerate(power)]
    alt = [round(120 + 45 * math.sin(i / 700) + 25 * math.sin(i / 230), 1) for i in range(n)]
    speed = [round(max(0, 6 + 4 * min(p / FTP, 1.2)), 2) for p in power]
    return {"power": power, "hr": hr, "cad": cad, "speed": speed, "alt": alt}


UNPLANNED = [("Morning coffee ride", "ride"), ("Hill repeats", "ride"), ("Saturday group ride", "ride"),
             ("Zwift recovery", "virtual_ride"), ("Gravel loop", "gravel_cycling"),
             ("Road ride", "ride")]

outcomes = ["done", "done", "done", "short", "done", "missed", "done", "marked"]
k = 0
for offset in range(-180, 22):
    day = today + timedelta(days=offset)
    plan = WEEK.get(day.weekday())
    planned_here = plan is not None and offset >= -28
    if planned_here:
        wtype, wname, wtss = plan
        completed = 0
        outcome = "planned"
        if offset < 0:
            outcome = outcomes[k % len(outcomes)]
            k += 1
            completed = 1 if outcome == "marked" else 0
        q.add_workout({"date": day.isoformat(), "name": wname, "workout_type": wtype,
                       "description": f"{wname} at planned intensity", "structured_json": None,
                       "tss_planned": float(wtss), "notes": "demo", "phase": "Build / Threshold",
                       "week_number": 1 + (offset + 28) // 7,
                       "purpose": explain.PURPOSE.get(wtype), "feel": explain.feel_for(wtype)})
        if completed:
            wid = q.get_workouts(day.isoformat(), day.isoformat())[0]["id"]
            q.update_workout(wid, {"name": wname, "workout_type": wtype,
                                   "description": f"{wname} at planned intensity",
                                   "tss_planned": float(wtss), "completed": 1, "notes": "demo"})
        if outcome == "done":
            add_ride(day, wtss * rng.uniform(0.9, 1.1), wname)
        elif outcome == "short":
            add_ride(day, wtss * 0.5, wname)
    elif offset < 0:
        busy = day.weekday() not in (0, 4)
        if rng.random() < (0.7 if busy else 0.25):  # sometimes an unplanned ride on a rest day
            add_ride(day, rng.uniform(40, 120), *rng.choice(UNPLANNED))

for offset in range(-120, 1):
    day = today + timedelta(days=offset)
    q.upsert_recovery(day.isoformat(), {
        "sleep_hours": round(rng.uniform(6.2, 8.4), 1), "sleep_score": rng.randint(60, 92),
        "hrv_ms": round(62 + 6 * rng.uniform(-1, 1) + offset / 40, 1), "hrv_status": "BALANCED",
        "resting_hr": rng.randint(44, 52), "readiness": rng.randint(45, 90),
        "body_battery": rng.randint(40, 95)})

for offset, name in ((2, "Lower body A"), (5, "Lower body B")):
    q.add_strength_session({
        "date": (today + timedelta(days=offset)).isoformat(), "plan_week": 1, "phase": "Build",
        "purpose": "Builds the leg strength that lets you push a bigger gear up climbs and stay "
                   "stable late in a race.",
        "exercises_json": json.dumps([
            {"name": "Back squat", "sets": 3, "reps": "6", "intensity": "RPE 7"},
            {"name": "Romanian deadlift", "sets": 3, "reps": "8", "intensity": "RPE 7"},
            {"name": "Plank", "sets": 3, "reps": "45s", "intensity": "Bodyweight"}]),
        "duration_minutes": 45, "notes": f"{name} | Planned by AI Coach"})
q.add_strength_session({
    "date": (today - timedelta(days=3)).isoformat(), "plan_week": 1, "completed": 1,
    "exercises_json": json.dumps([{"name": "Back squat", "sets": 3, "reps": "6",
                                   "intensity": "RPE 7", "weight_kg": 80.0}]),
    "duration_minutes": 50, "notes": "Lower body A | felt good"})

q.add_race({"name": "Demo Road Race", "date": (today + timedelta(days=35)).isoformat(),
            "distance_km": 80, "elevation_gain_meters": 900, "category": "Cat 3",
            "target_time_seconds": None, "notes": "Demo race"})
q.add_race({"name": "Demo Criterium", "date": (today - timedelta(days=10)).isoformat(),
            "distance_km": 40, "elevation_gain_meters": 120, "category": "Cat 3",
            "target_time_seconds": None, "notes": "Demo race in the past"})
print(f"Wrote demo database to {target}")
