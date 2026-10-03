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

run_migrations()
for key, value in {"ftp_watts": 250, "weight_kg": 72, "lthr": 165, "ctl_start": 40,
                   "primary_goal": "speed", "weekly_hours_target": 8,
                   "onboarding_complete": "1"}.items():
    q.set_setting(key, value)
q.log_ftp_history(250, "Demo")

if args.empty:
    print(f"Wrote empty demo database to {target}")
    sys.exit(0)

rng = random.Random(7)
today = date.today()
FTP = 250
# weekday (Mon = 0) -> (type, name, planned TSS); Mon and Fri are rest days
WEEK = {1: ("Threshold", "Threshold 4x8", 90), 2: ("Endurance", "Endurance Z2", 65),
        3: ("VO2 Max", "VO2 Max 5x4", 85), 5: ("Long Ride", "Long ride", 150),
        6: ("Recovery", "Recovery spin", 30)}


def add_ride(day: date, tss: float, name: str) -> None:
    intensity = min(max(0.5 + tss / 260, 0.55), 1.0)
    hours = tss / (intensity ** 2 * 100)
    shares = [0.25, 0.45, 0.15, 0.1, 0.05] if tss > 70 else [0.4, 0.5, 0.1, 0.0, 0.0]
    secs = int(hours * 3600)
    q.upsert_activity({
        "source": "demo", "external_id": f"demo-{day.isoformat()}-{name}",
        "date": day.isoformat(), "name": name, "sport_type": "ride",
        "duration_seconds": secs, "elapsed_seconds": secs + 240,
        "distance_meters": hours * 3600 * 8.2, "elevation_gain_meters": hours * 280,
        "avg_power_watts": round(intensity * FTP * 0.88), "avg_hr": int(115 + intensity * 45),
        "max_hr": 178, "normalized_power": round(intensity * FTP), "tss": round(tss),
        "if_value": round(intensity, 2), "raw_json": "{}",
        "zone_time_json": json.dumps({f"z{i + 1}_s": int(secs * s) for i, s in enumerate(shares)}
                                     | {"source": "estimated"}),
    })


outcomes = ["done", "done", "done", "short", "done", "missed", "done", "marked"]
k = 0
for offset in range(-90, 22):
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
                       "tss_planned": float(wtss), "notes": "demo", "phase": "Build",
                       "week_number": 1 + (offset + 28) // 7})
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
            add_ride(day, rng.uniform(40, 120), "Road ride")

for offset, name in ((2, "Lower body A"), (5, "Lower body B")):
    q.add_strength_session({
        "date": (today + timedelta(days=offset)).isoformat(), "plan_week": 1, "phase": "Build",
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
