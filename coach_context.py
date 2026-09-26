"""
The coach's persona and the athlete snapshot shared by every AI feature:
chat, ride reviews, weekly check ins and race day plans.
"""

from __future__ import annotations

from datetime import date, timedelta

from components.onboarding import parse_goal_keys
from db.queries import (get_setting, get_activities, get_races, get_memories,
                        get_recovery_range)
from metrics.training_load import get_current_metrics

SYSTEM_PROMPT = """You are an expert road cycling coach with deep knowledge of:
- Periodization and training load management (CTL/ATL/TSB/PMC)
- FTP-based training zones and structured interval work
- Race strategy and tactics for road cycling
- Recovery, sleep, HRV, nutrition timing, and performance optimization
- Strength training for cyclists
- OBRA (Oregon Bicycle Racing Association) racing context

Your coaching style:
- Specific and data-driven — always reference the athlete's actual numbers when available
- Direct but supportive — give honest assessments without being harsh
- Practical — suggest workouts and tactics the athlete can actually execute
- Evidence-based — cite reasoning for recommendations

When prescribing workouts, be specific:
- Duration, intervals, power targets (% FTP or watts), rest periods
- Give alternatives if they don't have a power meter (use RPE or % of LTHR)

Keep responses focused and actionable. If the athlete's data suggests a specific issue, address it directly.

Using the athlete's data:
- The snapshot below covers the basics. Use your tools to look up anything beyond it, such as
  longer ride history, weekly zone totals, sleep and recovery, check ins, FTP history or
  planned workouts.
- Only quote numbers that appear in the snapshot or a tool result. If the data you need isn't
  there, say what's missing instead of estimating it.
- When the athlete asks you to plan, schedule or import workouts, call propose_workouts. They
  confirm before anything is saved, so tell them to review the proposal on screen.
- The athlete may attach screenshots, such as a workout from TrainingPeaks or Zwift, or a chart.
  Read them carefully, and if a workout screenshot should go on the planner, propose it.

Remembering the athlete:
- "What you know about the athlete" below holds notes from earlier conversations. Use them.
- When the athlete tells you something that will still matter weeks from now (an injury, a
  schedule limit, a preference, how they respond to hard blocks, a goal), call remember with a
  short note. Don't save passing details or anything already in your notes."""

GOAL_COACHING_NOTES = {
    "speed": "Athlete's primary goal is GETTING FASTER — emphasize threshold/VO2max work and track FTP progress closely.",
    "endurance": "Athlete's primary goal is BUILDING ENDURANCE — prioritize long Z2 rides and steady weekly volume growth.",
    "weight_loss": "Athlete's primary goal is WEIGHT LOSS — favor consistent, sustainable training volume over extreme intensity; mention nutrition timing where relevant.",
    "race": "Athlete's primary goal is RACE PREP — tie recommendations back to their upcoming race and periodization.",
    "general_fitness": "Athlete's primary goal is GENERAL FITNESS — keep things low-pressure, ramp fitness gradually, avoid overtraining.",
}


def _recovery_line() -> str:
    rows = get_recovery_range((date.today() - timedelta(days=1)).isoformat(), date.today().isoformat())
    if not rows:
        return "  No Garmin recovery data synced for today"
    r = rows[-1]
    parts = []
    if r.get("sleep_hours"):
        parts.append(f"sleep {r['sleep_hours']}h" + (f" (score {r['sleep_score']})" if r.get("sleep_score") else ""))
    if r.get("hrv_ms"):
        parts.append(f"HRV {r['hrv_ms']}ms" + (f" {r['hrv_status'].lower()}" if r.get("hrv_status") else ""))
    if r.get("resting_hr"):
        parts.append(f"resting HR {r['resting_hr']}")
    if r.get("readiness") is not None:
        parts.append(f"readiness {r['readiness']}/100")
    if r.get("body_battery") is not None:
        parts.append(f"body battery peak {r['body_battery']}")
    return f"  {r['date']}: " + ", ".join(parts) if parts else "  No Garmin recovery data synced for today"


def memory_block() -> str:
    notes = get_memories()
    if not notes:
        return "  Nothing saved yet."
    return "\n".join(f"  - [{m['category']}] {m['note']} (noted {m['created_at'][:10]})" for m in notes)


def build_context() -> str:
    ftp = get_setting("ftp_watts", "unknown")
    weight = get_setting("weight_kg", "unknown")
    lthr = get_setting("lthr", "unknown")
    w_per_kg = round(float(ftp) / float(weight), 2) if (ftp and weight and ftp != "unknown" and weight != "unknown") else "unknown"
    goal_keys = parse_goal_keys(get_setting("primary_goal", ""))
    weekly_hours = get_setting("weekly_hours_target", "")

    metrics = get_current_metrics()
    activities = get_activities(days_back=14)
    races = get_races(upcoming_only=True)

    recent_rides = []
    for a in activities[:7]:
        dur = f"{int(a['duration_seconds']//3600)}h{int((a['duration_seconds']%3600)//60)}m" if a.get("duration_seconds") else "?"
        tss_str = f"TSS:{a['tss']:.0f}" if a.get("tss") else "no TSS"
        pwr_str = f"{a['avg_power_watts']:.0f}W" if a.get("avg_power_watts") else ""
        recent_rides.append(f"  - {a['date']} | {a.get('name','?')} | {dur} | {tss_str} {pwr_str}")

    next_race = races[0] if races else None
    race_str = "None scheduled"
    if next_race:
        days_out = (date.fromisoformat(next_race["date"]) - date.today()).days
        race_str = f"{next_race['name']} on {next_race['date']} ({days_out} days away)"

    newline = "\n"
    rides_str = newline.join(recent_rides) if recent_rides else "  No recent activities synced"
    tsb_label = "fresh and ready" if metrics["tsb"] > 5 else "fatigued" if metrics["tsb"] < -10 else "neutral"

    goal_notes = [GOAL_COACHING_NOTES[k] for k in goal_keys if k in GOAL_COACHING_NOTES]
    goal_note = "\n  ".join(goal_notes)
    hours_str = f"{weekly_hours} hrs/week" if weekly_hours else "unknown"

    return f"""
ATHLETE DATA (use this to give specific coaching advice):
{f"  {goal_note}" if goal_note else ""}
  Weekly training time available: {hours_str}

Physiology:
  FTP: {ftp}W | Weight: {weight}kg | W/kg: {w_per_kg} | LTHR: {lthr}bpm

Current Training Load:
  CTL (Fitness): {metrics['ctl']:.1f}
  ATL (Fatigue): {metrics['atl']:.1f}
  TSB (Form): {metrics['tsb']:.1f} ({tsb_label})
  7-day ramp rate: {metrics['ramp_rate']:+.1f}

Latest recovery (Garmin):
{_recovery_line()}

Recent Activities (last 14 days):
{rides_str}

Next Race: {race_str}

What you know about the athlete:
{memory_block()}

Today's date: {date.today().isoformat()} ({date.today().strftime("%A")})
"""


def system_blocks(extra: str = "") -> list[dict]:
    """System prompt plus the athlete snapshot, ready to send to Claude."""
    text = SYSTEM_PROMPT + (f"\n\n{extra}" if extra else "")
    return [{"type": "text", "text": text}, {"type": "text", "text": build_context()}]
