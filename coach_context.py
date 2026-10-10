"""
The coach's persona and the athlete snapshot shared by every AI feature:
chat, ride reviews, weekly check ins and race day plans.
"""

from __future__ import annotations

from datetime import date, timedelta

from components.onboarding import parse_goal_keys
from db.queries import (get_setting, get_activities, get_races, get_memories,
                        get_recovery_range, auto_max_hr, auto_resting_hr)
from metrics.training_load import ESTIMATED_UNDER_DAYS, get_current_metrics, history_days
from metrics.tss import label as tss_label

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
- Duration, intervals, power targets as % FTP (watts in brackets are fine), rest periods
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
- Anything not marked done can change. A workout whose day passed without being done was skipped, and
  you can move it to a later day or edit it. Done rides stay as they are, and an upcoming workout can't
  move into the past.
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

PROGRAM_RULES = """PROGRAM PLANNING MODE. The athlete wants to plan a multi month program with you (an off season,
a base block, a build to a goal) and then review it, change it and put it on their calendar.

Work in three steps and tell the athlete which step you are in.

Step 1, a short conversation. Ask ONE question at a time and wait for the answer. Never list several
questions. Use the snapshot and your tools first (recent weekly totals, FTP history, races, recovery,
what you remember) so you never ask what you already know. Cover what matters and skip what does not,
usually four to seven questions:
- how the season went and what they want next season to look like (events, dates, goals)
- whether they want a proper break off the bike, and for how long
- hours a week and which days they can ride over this period, indoors or outdoors, travel or busy spells
- gym work: whether they want it and what equipment they have
- what held them back this year, injuries, and anything they dislike in training
Reflect back what you heard in three or four lines and ask if you have it right before drafting.
If they say go ahead, or give you enough in one message, move on without more questions.

Step 2, the draft. Call propose_program with the whole program. Build it the way a real coach would:
- Phases run back to back from a Monday start. Name them plainly. An off season usually starts with a
  short true break (no week_template, load 0), then an easy base that rebuilds routine, then longer steady
  base work with strength, then the first sharper work if the goal needs it. Shape it to THEIR goal and dates.
- Fit inside the hours and days they gave you. Weekly load numbers must make sense against their current
  CTL, which is in the snapshot: a week of load about 7 times their target CTL holds that fitness,
  and ramps should be gentle, roughly 3 to 6 CTL points a week at most. Use lighter weeks every 3rd or
  4th week.
- Every template day has a purpose written for this athlete and a feel. Give each phase a focus and a
  reason. Add checkpoints such as an FTP test and say why they are placed there.
- A program is a plan for how a normal week looks. The app turns it into dated workouts, so do not
  write out every week yourself.
After the call, explain the shape in plain words: the phases and why, the hardest week, where the easy
weeks are. Then ask what they would change. Say the PDF and the Add to my calendar button are under the
chat once they are happy. Never say it is on their calendar.

Step 3, revising. When they want changes, talk it through, then call propose_program again with the whole
revised program. It replaces the draft. Say what changed. Do not add it to the calendar yourself: they
press Add to my calendar when they are ready.

The athlete can set a week's training load (TSS) by hand on the card. Those weeks show in the draft as
tss_overrides. Keep them when you revise, and mention it if a change you make would clash with one. If
you change phase lengths, week numbers shift, so check each override still makes sense.

Write plainly. Do not use em dashes."""

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


def _hr_line() -> str:
    """Max and resting heart rate, set by hand or worked out from rides and recovery."""
    parts = []
    for label, key, auto in (("Max HR", "max_hr_manual", auto_max_hr), ("Resting HR", "resting_hr_manual",
                                                                       auto_resting_hr)):
        val = get_setting(key, "") or ""
        if val:
            parts.append(f"{label}: {val}bpm")
        else:
            found = auto()
            parts.append(f"{label}: {found:.0f}bpm (from their data)" if found else f"{label}: unknown")
    return " | ".join(parts)


def _days_line() -> str:
    from planning import parse_days
    days = parse_days(get_setting("available_days", ""))
    if not days:
        return ""
    return (f"  Days they can ride: {', '.join(days)}. Put every ride and gym session you propose on these "
            "weekdays only, including programs, and keep the long ride on a weekend day if one is listed.")


def _load_note(ctl_seed: float) -> str:
    """A warning when the training load numbers are still mostly the starting estimate."""
    days = history_days()
    if days >= ESTIMATED_UNDER_DAYS:
        return ""
    have = f"only {days} days of ride history" if days else "no rides recorded yet"
    if ctl_seed:
        return (f"  Note: there is {have}. CTL and ATL above start from an estimated seed of {ctl_seed:.0f} "
                "set from their experience, not measured from rides. Do not quote them as measured "
                "fitness. Treat them as a rough starting guess and say so if you use them.")
    return (f"  Note: there is {have}, so CTL and ATL above are built from very little data and "
            "understate real fitness. Do not quote them as measured fitness.")


def _coach_line() -> str:
    """For an athlete Sam coaches, who is actually reading the replies."""
    from db import profiles, schema
    if schema.is_owner():
        return ""
    name = (get_setting("athlete_name", "") or "this athlete").strip()
    coach = profiles.owner_name()
    return (f"WHO YOU ARE TALKING TO: {coach} is the coach and is planning for {name}, an athlete they coach. "
            f"{coach} is the one reading and writing these messages, not {name}. Address {coach} and talk "
            f"about {name} in the third person. Where these instructions say \"the athlete\", they mean "
            f"{name}, and confirmations on screen are made by {coach}.\n")


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
        tss_str = (f"{tss_label(a.get('tss_source')).replace(' ', '')}:{a['tss']:.0f}"
                   if a.get("tss") else "no TSS")
        pwr_str = f"{a['avg_power_watts']:.0f}W" if a.get("avg_power_watts") else ""
        recent_rides.append(f"  - {a['date']} | {a.get('name','?')} | {dur} | {tss_str} {pwr_str}")

    next_race = races[0] if races else None
    race_str = "None scheduled"
    if next_race:
        days_out = (date.fromisoformat(next_race["date"]) - date.today()).days
        race_str = f"{next_race['name']} on {next_race['date']} ({days_out} days away)"

    program = active_program_line()
    program_line = f"Active program: {program}\n" if program else ""
    newline = "\n"
    rides_str = newline.join(recent_rides) if recent_rides else "  No recent activities synced"
    tsb_label = "fresh and ready" if metrics["tsb"] > 5 else "fatigued" if metrics["tsb"] < -10 else "neutral"

    goal_notes = [GOAL_COACHING_NOTES[k] for k in goal_keys if k in GOAL_COACHING_NOTES]
    goal_note = "\n  ".join(goal_notes)
    hours_str = f"{weekly_hours} hrs/week" if weekly_hours else "unknown"
    days_str = f"{days_per_week} days/week" if days_per_week else "unknown"
    goal_words = f'  In the athlete\'s own words, their goals are: "{goal_text}"' if goal_text else ""
    athlete_name = (get_setting("athlete_name", "") or "").strip()
    name_line = f"  Name: {athlete_name}" if athlete_name else ""
    try:
        ctl_seed = float(get_setting("ctl_start", 0) or 0)
    except (TypeError, ValueError):
        ctl_seed = 0.0

    return f"""
{_coach_line()}ATHLETE DATA (use this to give specific coaching advice):
{name_line}
{goal_words}
{f"  {goal_note}" if goal_note else ""}
  Weekly training time available: {hours_str} over {days_str}. Fit plans inside this and say so if it is not enough for the goal.
{_days_line()}

Experience: {experience}{sex_note}
Units: {units_note}
Physiology:
  FTP: {ftp}W{ftp_note} | Weight: {weight}kg | W/kg: {w_per_kg} | LTHR: {lthr}bpm
  {_hr_line()}

Current Training Load:
  CTL (Fitness): {metrics['ctl']:.1f}
  ATL (Fatigue): {metrics['atl']:.1f}
  TSB (Form): {metrics['tsb']:.1f} ({tsb_label})
  7-day ramp rate: {metrics['ramp_rate']:+.1f}
{_load_note(ctl_seed)}

Latest recovery (Garmin):
{_recovery_line()}

Recent Activities (last 14 days):
{rides_str}

Next Race: {race_str}
{program_line}
What you know about the athlete:
{memory_block()}

Today's date: {date.today().isoformat()} ({date.today().strftime("%A")})
"""


def program_rules(draft: dict | None) -> str:
    """The extra instructions for the program conversation, with the current draft so the coach
    can discuss it and revise it exactly."""
    text = PROGRAM_RULES
    if draft:
        import json
        slim = {k: v for k, v in draft.items() if k not in ("id", "status", "created_at", "updated_at", "executed_at")}
        text += (f"\n\nCURRENT DRAFT (version {draft['version']}, not on the calendar yet). When you revise, "
                 f"send the whole program again.\n{json.dumps(slim)}")
    return text


def active_program_line() -> str:
    """One line about the program the athlete has put on their calendar, or ''."""
    import programs
    prog = programs.load("active")
    return programs.summary_line(prog) if prog else ""


def system_blocks(extra: str = "") -> list[dict]:
    """System prompt plus the athlete snapshot, ready to send to Claude."""
    text = SYSTEM_PROMPT + (f"\n\n{extra}" if extra else "")
    return [{"type": "text", "text": text}, {"type": "text", "text": build_context()}]
