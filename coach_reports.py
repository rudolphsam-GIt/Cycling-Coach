"""
Ride reviews, weekly check ins and race day plans written by the AI coach.

Each builder returns (ref_key, title, prompt). The page streams the reply with
components.coach_ui.stream_reply and saves it with db.queries.save_report, so a
report is only written once and can be read again later.
"""

from __future__ import annotations

from datetime import date, timedelta

REPORT_RULES = """You are writing a saved report the athlete will read on its own page, not a chat
reply. Start with a one line headline in bold that sums up the verdict. Use short sections with
### headings. Look up whatever data you need with your tools before writing, and only quote
numbers you found. Don't call remember while writing a report; notes are only for things the
athlete tells you in conversation."""

EFFORT = {"ride_review": "medium", "weekly": "high", "race_plan": "high"}


def _fmt_minutes(seconds) -> str:
    if not seconds:
        return "?"
    m = int(seconds // 60)
    return f"{m // 60}h{m % 60:02d}m"


def ride_review(ride: dict) -> tuple[str, str, str]:
    facts = {
        "date": ride["date"], "name": ride.get("name"), "type": ride.get("sport_type"),
        "moving_time": _fmt_minutes(ride.get("duration_seconds")),
        "distance_km": round((ride.get("distance_meters") or 0) / 1000, 1),
        "climbing_m": round(ride.get("elevation_gain_meters") or 0),
        "avg_power_w": ride.get("avg_power_watts"), "normalized_power_w": ride.get("normalized_power"),
        "intensity_factor": ride.get("if_value"), "tss": ride.get("tss"),
        "avg_hr": ride.get("avg_hr"), "max_hr": ride.get("max_hr"),
    }
    facts_text = "\n".join(f"- {k}: {v}" for k, v in facts.items() if v not in (None, "", 0))
    next_day = date.fromisoformat(ride["date"]) + timedelta(days=1)
    if next_day >= date.today():
        tomorrow = ("### Tomorrow\nWhat tomorrow should look like given this ride and my recovery. "
                    f"If nothing is planned for {next_day} yet, propose one workout for it with "
                    "propose_workouts.")
    else:
        tomorrow = ("### Takeaway\nThis ride is in the past, so skip planning. Give one lesson "
                    "from it that still applies to my training now.")
    prompt = f"""Write a post ride review of this ride.

{facts_text}

Look up what was planned for {ride['date']}, the training load in the days around it, and my
sleep and recovery that morning. Then cover:
### How it went
Compare it to the plan (or to what the day called for if nothing was planned). Judge the
intensity from IF, normalized power and heart rate.
### What it did
Its effect on fitness, fatigue and form.
{tomorrow}

Keep it under 220 words."""
    return str(ride["id"]), f"{ride.get('name') or 'Ride'} · {ride['date']}", prompt


def week_bounds(day: date) -> tuple[date, date]:
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def checkin_week(today: date | None = None) -> date:
    """The week to review: this week from Saturday on, otherwise last week."""
    today = today or date.today()
    start, _ = week_bounds(today)
    return start if today.weekday() >= 5 else start - timedelta(days=7)


def weekly_checkin(week_start: date) -> tuple[str, str, str]:
    week_end = week_start + timedelta(days=6)
    # Plan the 7 days ahead, starting next Monday or today, whichever is later.
    next_start = max(week_end + timedelta(days=1), date.today())
    next_end = next_start + timedelta(days=6)
    prompt = f"""It's my weekly check in for {week_start:%a %b %d} to {week_end:%a %b %d}.

Look up that week's rides, the weekly summary for the last 4 weeks, my sleep and recovery,
my daily check ins, my races, and what's already planned for {next_start} to {next_end}.
Then write:
### How the week went
Planned vs actual TSS, the key sessions, and the recovery trend.
### What I noticed
Anything worth changing, grounded in the numbers and in what you know about me.
### The next 7 days
The focus and why. Then call propose_workouts with the plan for {next_start} to {next_end},
working around anything already planned and any race. Include rest days only as gaps, not as
workouts.

Keep the written part under 350 words."""
    title = f"Week of {week_start:%b %d}"
    return week_start.isoformat(), title, prompt


def race_plan(race: dict) -> tuple[str, str, str]:
    race_day = date.fromisoformat(race["date"])
    days_out = (race_day - date.today()).days
    details = [f"- name: {race['name']}", f"- date: {race['date']} ({days_out} days away)"]
    for key, label in (("distance_km", "distance_km"), ("elevation_gain_meters", "climbing_m"),
                       ("category", "category"), ("notes", "notes")):
        if race.get(key):
            details.append(f"- {label}: {race[key]}")
    if days_out > 21:
        timing = (f"The race is {days_out} days out, so outline the build and the taper by week, "
                  "and propose workouts for the next 7 days only.")
    else:
        timing = ("Lay out the taper day by day up to race day, and propose the taper workouts "
                  "that aren't already on my planner.")
    prompt = f"""Build my race day plan.

{chr(10).join(details)}

Look up my training load, recent rides, sleep and recovery, and my planned workouts. {timing}
Then cover:
### Taper
### Race morning
Sleep, meal timing, and a warm up that fits this event.
### Pacing
Power and heart rate targets from my FTP and LTHR, matched to the distance and climbing.
### Fueling
Carbs per hour and fluids for the expected duration, plus what to eat the day before.
### Checklist
A short packing and prep list.

Keep it under 450 words."""
    return str(race["id"]), f"Race plan · {race['name']}", prompt
