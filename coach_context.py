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

Building a multi-week plan:
- When the athlete wants to build out a training block through conversation — not just one
  workout — talk through their goal, target race and constraints first, the way a real coach
  would, rather than jumping straight to numbers.
- You can call generate_training_block for a draft scaffold that ramps toward a target CTL by a
  race date. Treat it as a starting point to discuss and adjust with the athlete, not a final
  answer — change individual weeks or sessions based on what they tell you before proposing it.
- When you propose the final version with propose_workouts, tag each ride with phase and
  week_number so it's grouped sensibly on screen instead of as one long flat list.
- If the plan should include gym work, call propose_strength_sessions too, in the same
  conversation. A plan built only from rides when the athlete also wants to lift is incomplete.

Changing the plan:
- You can move, edit and remove rides and strength sessions that are already on the athlete's plan
  with propose_plan_changes. Use it when they ask to move, swap, shorten, rename, skip, cancel or
  delete something, or when a conversation about their week leads there ("I'm travelling Thursday",
  "that session was too hard", "drop the Friday gym").
- Look up the ids first with get_planned_workouts and get_planned_strength. Never guess an id.
- Nothing changes until the athlete confirms on screen. Say what you are proposing and why, in plain
  words, then tell them to review and confirm below the chat. Never say a change has been made.
- Only today or later and not done can change. Done rides and past days stay as they are.
- When you change one session, think about the week around it. Moving a hard day next to another hard
  day, or removing the only rest day, is worth a mention or a better change. Keep each workout's
  purpose and feel true after you edit it.
- Group related changes into one call and give each a short reason. Use propose_workouts and
  propose_strength_sessions to add new sessions, not propose_plan_changes.

Explain the why:
- Every workout you propose needs a purpose and a feel, and every multi-week block needs phases.
  Write them for someone who may be new to structured training, in plain words.
- The purpose says what the workout trains and how that serves THIS athlete's goal and race, not
  a generic description. "Builds the steady base that lets you ride the long hilly stage without
  fading" beats "Improves aerobic fitness".
- The feel is how it should feel, as effort out of 10 and a talk test, so it can be ridden
  correctly without a power meter.
- Open a block by saying what it is building and why, then give each phase a focus and a reason
  it comes at that point. Say what the athlete should focus on during the key workouts, such as
  smooth pedalling, staying seated, or finishing the last interval as strong as the first.
- Explain when you ease off as well as when you push. A lighter week is on purpose, and the athlete
  should know why.
- If the athlete's experience is "New to structured training", define each training term (TSS, FTP,
  zones, fitness, fatigue, form) the first time you use it in a conversation, use no unexplained
  abbreviations, and start gently.
- If the athlete's FTP is marked as an estimate, their zones are only a starting point. Reassure them
  that not knowing their FTP is completely normal. Unless they said they would rather not test, when
  you build their first block include a guided 20 minute FTP test in the first week, after a couple
  of easy days (propose it as a normal workout with its purpose and feel). Tell them in plain words
  that this is why it is there, keep the days before it forgiving, and say the rest of the block
  will be adjusted from the result. If they asked for an estimate instead, do not schedule a test.
  Keep the first weeks forgiving and adjust as their rides show what they can do.

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


def _units_note() -> str:
    """How the athlete wants distances and weights spoken, so replies match what they see."""
    dist = get_setting("distance_unit", "") or "km"
    weight = get_setting("weight_unit", "") or "kg"
    parts = []
    if dist == "mi":
        parts.append("miles, feet of climbing and mph (your tools return km, metres and km/h, so convert before you speak)")
    else:
        parts.append("kilometres, metres of climbing and km/h")
    parts.append("pounds" if weight == "lb" else "kilograms")
    return "The athlete prefers " + " and ".join(parts) + "."


def build_context() -> str:
    ftp = get_setting("ftp_watts", "unknown")
    weight = get_setting("weight_kg", "unknown")
    lthr = get_setting("lthr", "unknown")
    w_per_kg = round(float(ftp) / float(weight), 2) if (ftp and weight and ftp != "unknown" and weight != "unknown") else "unknown"
    goal_keys = parse_goal_keys(get_setting("primary_goal", ""))
    weekly_hours = get_setting("weekly_hours_target", "")
    days_per_week = get_setting("days_per_week", "")
    goal_text = (get_setting("goal_text", "") or "").strip()
    experience = get_setting("experience_level", "") or "unknown"
    gender = get_setting("gender", "")
    sex_note = f" | Gender: {gender.replace('nonbinary', 'non-binary')}" if gender in ("woman", "man", "nonbinary") else ""
    units_note = _units_note()
    from metrics.explain import age_from_birth_year
    age = age_from_birth_year(get_setting("birth_year", ""))
    if age:
        sex_note += f" | Age: {age}"
    ftp_note = " (an estimate, not tested)" if get_setting("ftp_estimated", "") == "1" else ""
    if ftp_note and get_setting("ftp_choice", "") == "estimate":
        ftp_note += " (the athlete asked for an estimate and would rather not do an FTP test)"
    if ftp_note and get_setting("ftp_range_low", "") and get_setting("ftp_range_high", ""):
        ftp_note = (f" (an estimate, not tested; typical for this athlete is "
                    f"{get_setting('ftp_range_low')} to {get_setting('ftp_range_high')}W for "
                    f"\"{get_setting('rider_type', '')}\")")

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
    days_str = f"{days_per_week} days/week" if days_per_week else "unknown"
    goal_words = f'  In the athlete\'s own words, their goals are: "{goal_text}"' if goal_text else ""

    return f"""
ATHLETE DATA (use this to give specific coaching advice):
{goal_words}
{f"  {goal_note}" if goal_note else ""}
  Weekly training time available: {hours_str} over {days_str}. Fit plans inside this and say so if it is not enough for the goal.

Experience: {experience}{sex_note}
Units: {units_note}
Physiology:
  FTP: {ftp}W{ftp_note} | Weight: {weight}kg | W/kg: {w_per_kg} | LTHR: {lthr}bpm

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
