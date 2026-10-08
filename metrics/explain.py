"""
Plain language wording for the app, in one place so every page says the same
thing: what each training term is, why it matters, what the rider's own number
means, what a workout should feel like, and the steps a newcomer works through.

Everything here is pure. Pages and components pass in the rider's numbers.
Rules of thumb are labelled as such and use the same cut offs as the form
banner on the Today page.
"""
from __future__ import annotations

from datetime import date, timedelta

from metrics.zones import get_power_zones

# Form (TSB) bands, shared with components.cards.tsb_banner.
FRESH_TSB = 10
FRESH_MIN_CTL = 20
FATIGUED_TSB = -30


def form_state(tsb: float, ctl: float) -> str:
    """fresh, building or fatigued, the same bands as the Today banner."""
    if tsb >= FRESH_TSB and ctl > FRESH_MIN_CTL:
        return "fresh"
    if tsb <= FATIGUED_TSB:
        return "fatigued"
    return "building"


# ── What each term is and why it matters ──────────────────────────────────────

TERMS: dict[str, dict] = {
    "ftp": {
        "title": "FTP (functional threshold power)",
        "what": "The most power you can hold for about an hour, in watts. It is your yardstick. "
                "Every training zone, and every training stress score, is measured against it.",
        "why": "If your FTP is set too high, workouts are too hard and the numbers look worse "
               "than they are. Too low and they are too easy. Re-test every 6 to 8 weeks, or let the "
               "app suggest a new value from your best 20 minutes.",
    },
    "zones": {
        "title": "Power zones",
        "what": "Seven effort bands set as a percentage of your FTP. Zone 1 is very easy spinning, "
                "zone 2 is steady endurance riding, zone 3 is tempo, zone 4 is threshold, zone 5 is "
                "hard intervals, and above that is sprinting.",
        "why": "Different zones train different things. Most of your riding should be easy "
               "(zone 2) so you can ride a lot, with a smaller share of hard work that makes you "
               "faster. Riding everything at medium effort tends to leave you tired but not faster.",
    },
    "hr_zones": {
        "title": "Heart rate zones",
        "what": "Five effort bands set as a percentage of your lactate threshold heart rate (LTHR), "
                "the heart rate you can hold for about an hour of hard riding.",
        "why": "Heart rate is a good guide when you have no power meter. It lags behind effort, "
               "so it is less precise for short intervals.",
    },
    "tss": {
        "title": "TSS (training stress score)",
        "what": "One number for how big a ride was, counting both how long it was and how hard. "
                "One hour riding exactly at your FTP scores 100. An easy hour scores around 40 to 50. "
                "A long, hard day scores 200 or more.",
        "why": "It lets you compare very different rides, add them up for a week, and see how much "
               "load your body is taking on. Progress comes from adding load gradually, so TSS is "
               "the number that keeps you from doing too much or too little.",
    },
    "if": {
        "title": "IF (intensity factor)",
        "what": "How hard a ride was compared with your FTP. 1.00 means the ride averaged your "
                "threshold. 0.70 is a comfortable endurance ride.",
        "why": "Two rides with the same TSS can be very different. A long easy ride and a short "
               "hard one can score the same. IF tells you which one it was.",
    },
    "np": {
        "title": "NP (normalized power)",
        "what": "Your average power, adjusted for how uneven the ride was. Surges and hard efforts "
                "cost more than steady riding at the same average, and NP accounts for that.",
        "why": "NP is the power the training stress score is built from. If it is much higher than "
               "your plain average, the ride had a lot of hard bursts in it.",
    },
    "kj": {
        "title": "Work (kilojoules)",
        "what": "The total energy you put into the pedals. It is roughly the same number as the "
                "calories you burned on the bike.",
        "why": "It is useful for fuelling. Longer rides with more kilojoules need more food and "
               "drink during the ride.",
    },
    "ctl": {
        "title": "Fitness (CTL)",
        "what": "A running average of your daily training stress over roughly the last six weeks. "
                "It rises when you train consistently and drifts down when you stop.",
        "why": "It is the best single number for how much training your body has adapted to. "
               "A higher fitness number means you can handle more, and it is what builds toward "
               "race form.",
    },
    "atl": {
        "title": "Fatigue (ATL)",
        "what": "The same kind of running average but over about the last week, so it reacts fast. "
                "It jumps after hard days and falls quickly when you rest.",
        "why": "Fatigue is the cost of training. When it is far above your fitness, you are "
               "carrying a lot of tiredness. That is fine for a few days in a block, but it needs "
               "to come back down.",
    },
    "tsb": {
        "title": "Form (TSB)",
        "what": "Yesterday's fitness minus yesterday's fatigue. Positive means you are fresh. "
                "Negative means you are carrying tiredness from recent training.",
        "why": "Most of your training happens at slightly negative form, which is normal and "
               "productive. You want to be positive, around plus 5 to plus 25, on race day. "
               "Staying very negative for weeks is a warning sign.",
    },
    "key_numbers": {
        "title": "Fitness, fatigue and form",
        "what": "Fitness (CTL) is your long term training load. Fatigue (ATL) is your short term "
                "load. Form (TSB) is fitness minus fatigue, which tells you how fresh you are.",
        "why": "Together they answer three questions. How much have I built? How tired am I? "
               "Am I ready to go hard or race?",
    },
    "ramp": {
        "title": "Ramp rate",
        "what": "How much your fitness changed over the last 7 days.",
        "why": "Fitness that climbs steadily is what you want. Climbing too fast is a common way "
               "to get injured, ill or burnt out.",
    },
    "performance_chart": {
        "title": "Performance chart",
        "what": "Your fitness (blue), fatigue (orange) and form (green) over time, with the bars "
                "showing each day's training stress.",
        "why": "Look for the blue line rising over weeks, orange spiking after hard blocks and "
               "dropping during rest, and green climbing back above zero before a race.",
    },
    "weekly_volume": {
        "title": "Weekly volume",
        "what": "How much you rode each week, as training stress, hours, distance or climbing.",
        "why": "Steady weeks that grow a little at a time are the goal. A lighter week every "
               "third or fourth week lets your body absorb the work.",
    },
    "planned_vs_done": {
        "title": "Planned vs done",
        "what": "The training stress you planned for each week next to what you actually rode.",
        "why": "Done close to planned means the plan fits your life. Far below it, week after week, "
               "means the plan is too much and should change. Far above it can mean you are "
               "overdoing it.",
    },
    "plan_impact": {
        "title": "Plan impact",
        "what": "A forecast of your fitness, fatigue and form if you ride every planned workout "
                "exactly as written, up to your next race or four weeks out.",
        "why": "It shows what a change does before you make it. Move a hard day and see how your "
               "form on race day changes. It is a projection, not a prediction.",
    },
    "peak_power": {
        "title": "Peak power curve",
        "what": "The best average power you have ever held for each length of time, from 1 second "
                "up to 2 hours.",
        "why": "It shows what kind of rider you are. High short bars point to sprinting, a high "
               "20 minute number to strong endurance and climbing. Watch how it changes block to block.",
    },
    "wkg": {
        "title": "Watts per kilo",
        "what": "Your power divided by your body weight.",
        "why": "It decides how you climb. Two riders with the same watts are not equal if one weighs less.",
    },
    "power_profile": {
        "title": "Power profile",
        "what": "Your best power per kilo at 5 seconds, 1, 5, 20 and 60 minutes, placed on "
                "published categories from untrained up to world class.",
        "why": "It shows your strongest and weakest areas at a glance. A low bar is the best "
               "place to look for easy gains, if it matters for your racing.",
    },
    "ef": {
        "title": "Efficiency factor",
        "what": "Normalized power divided by average heart rate for a ride.",
        "why": "If you can put out more power at the same heart rate over the weeks, your aerobic "
               "fitness is improving. It is most useful for steady endurance rides.",
    },
    "hrv": {
        "title": "HRV (heart rate variability)",
        "what": "The small changes in timing between heartbeats, measured overnight by your watch.",
        "why": "A reading that is well below your own normal for several days in a row can mean "
               "you are tired, sick or stressed. Look at the trend, not a single day.",
    },
    "resting_hr": {
        "title": "Resting heart rate",
        "what": "Your heart rate while asleep or at rest.",
        "why": "A resting heart rate that creeps up several beats over your normal can be an early "
               "sign of fatigue or illness.",
    },
    "history": {
        "title": "Fitness history",
        "what": "Your best power and heart rate for key durations, by week, by month and of all time, "
                "next to how much you rode.",
        "why": "It is the long view. Are your best efforts going up across months? The week and "
               "month still in progress are shown in grey because they are not finished.",
    },
    "ride_numbers": {
        "title": "Reading a ride",
        "what": "Duration and distance say how long. Normalized power and intensity factor say how hard. "
                "TSS combines the two into one score.",
        "why": "Compare a ride against what the workout was meant to be. An endurance ride with a "
               "high intensity factor was probably too hard.",
    },
}

# Short text for tooltips on numbers, tiles and table columns.
TIPS = {
    "tss": "Training stress. One hour at your FTP scores 100.",
    "if": "Intensity factor. How hard the ride was compared with your FTP. 0.70 is easy, 1.00 is threshold.",
    "np": "Normalized power. Average power adjusted for surges, so hard efforts count for more.",
    "avg_w": "Average power over the whole ride.",
    "kj": "Work. Energy put into the pedals, roughly equal to calories burned.",
    "ef": "Efficiency factor. Normalized power divided by average heart rate. Rising over weeks is good.",
    "rides": "How many rides match your dates and search.",
    "hours": "Total moving time on the bike.",
    "km": "Total distance ridden.",
    "climb": "Total climbing, the sum of every ride's elevation gain.",
    "avg_if": "Average intensity factor, how hard your rides were compared with your FTP. 0.70 is easy, 1.00 is threshold.",
    "avg_ef": "Average efficiency factor. Normalized power divided by average heart rate. Rising over weeks is good.",
    "ctl": "Fitness. Your training load averaged over about six weeks.",
    "atl": "Fatigue. Your training load averaged over about one week.",
    "tsb": "Form. Fitness minus fatigue. Positive is fresh, negative is tired.",
    "ftp": "The most power you can hold for about an hour. Your zones and TSS are based on it.",
    "wkg": "Your FTP divided by your weight. It decides how you climb.",
    "compare": "Change against the period of the same length just before.",
}

SETTINGS_HELP = {
    "ftp": "The most power you can hold for about an hour. Every zone and training stress score is "
           "based on it. Not sure? Ride a hard, even 20 minutes and use 95% of your average power, "
           "or use the Plan an FTP test button on the Today page.",
    "lthr": "Your lactate threshold heart rate, the heart rate you can hold for about an hour of "
            "hard riding. Used for heart rate zones and for rides without power. A good estimate is "
            "your average heart rate over the last 20 minutes of a hard 30 minute solo effort.",
    "weight": "Used for watts per kilo, which decides how you climb, and for the power profile.",
    "ctl_start": "How fit you were at the start of your history, on the fitness scale. It only matters "
                 "for the first weeks, because older training fades out of the average. If unsure, "
                 "use 25 if you are new to training, 45 for some experience and 65 if you have raced.",
}


# ── Your number ───────────────────────────────────────────────────────────────

def _w(n) -> str:
    return f"{float(n):.0f} W"


def your_ftp(ftp=None, weight=None, estimated=False, **_) -> str | None:
    if not ftp:
        return None
    zones = get_power_zones(float(ftp))
    z2, z4 = zones[1], zones[3]
    out = f"Your FTP is set to {_w(ftp)}"
    if weight:
        out += f", which is {float(ftp) / float(weight):.2f} watts per kilo"
    out += (f". That puts easy endurance riding (zone 2) at about {z2['min_watts']} to {z2['max_watts']} W "
            f"and threshold work (zone 4) at {z4['min_watts']} to {z4['max_watts']} W.")
    if estimated:
        out += (" This FTP is an estimate. Treat your zones as a starting point until you test or "
                "let the app suggest a value from your rides.")
    return out


def your_tss(week_tss=None, hours=None, **_) -> str | None:
    if not week_tss:
        return None
    out = f"This week you have {float(week_tss):.0f} TSS"
    if hours:
        out += f" from {float(hours):.1f} hours of riding"
    out += ". For comparison, one hour at your FTP is 100."
    return out


def your_if(if_value=None, **_) -> str | None:
    if not if_value:
        return None
    v = float(if_value)
    if v < 0.55:
        band = "a recovery ride"
    elif v < 0.75:
        band = "an endurance ride"
    elif v < 0.85:
        band = "a tempo ride"
    elif v < 0.95:
        band = "a hard ride, around sweet spot or threshold"
    elif v < 1.05:
        band = "a threshold ride"
    else:
        band = "a very hard ride, such as a race or a test"
    return f"An intensity factor of {v:.2f} is {band}. This is a rule of thumb."


def your_np(np=None, avg=None, **_) -> str | None:
    if not np or not avg:
        return None
    gap = (float(np) / float(avg) - 1) * 100
    if gap < 5:
        feel = "a steady ride with few surges"
    elif gap < 12:
        feel = "some surging, like rolling terrain or group riding"
    else:
        feel = "a lot of hard bursts, like intervals, a race or a hilly route"
    return f"Your normalized power was {_w(np)} against an average of {_w(avg)}, which is {feel}."


def _ramp_text(r: float) -> str:
    if r > 8:
        return (f"It rose {r:.1f} over the last week, which is faster than most people can "
                "absorb. Watch for fatigue. This is a rule of thumb.")
    if r >= 2:
        return f"It rose {r:.1f} over the last week, a healthy build."
    if r > -2:
        return f"It changed {r:+.1f} over the last week, so you are holding steady."
    return f"It fell {abs(r):.1f} over the last week, which is expected during rest or a lighter week."


def your_ctl(ctl=None, ramp=None, **_) -> str | None:
    if ctl is None:
        return None
    out = f"Your fitness is {float(ctl):.0f}."
    if ramp is not None:
        out += " " + _ramp_text(float(ramp))
    return out


def your_atl(atl=None, ctl=None, **_) -> str | None:
    if atl is None:
        return None
    out = f"Your fatigue is {float(atl):.0f}"
    if ctl:
        gap = float(atl) - float(ctl)
        if gap > 20:
            out += f", well above your fitness of {float(ctl):.0f}. You are carrying a lot of tiredness right now."
        elif gap > 5:
            out += f", a little above your fitness of {float(ctl):.0f}. That is normal in a training week."
        else:
            out += f", close to or below your fitness of {float(ctl):.0f}. You are rested."
        return out
    return out + "."


def your_tsb(tsb=None, ctl=None, **_) -> str | None:
    if tsb is None:
        return None
    t = float(tsb)
    state = form_state(t, float(ctl) if ctl is not None else 100.0)
    if state == "fresh":
        tail = "You are fresh. This is a good place to be for a race or a hard session."
    elif state == "fatigued":
        tail = "You are very tired. Take an easy day or rest before hard efforts."
    else:
        tail = "That is a normal, productive place to be during training. Hard days are fine."
    return f"Your form is {t:+.0f}. {tail}"


def your_ramp(ramp=None, **_) -> str | None:
    return ("Your fitness " + _ramp_text(float(ramp)).replace("It ", "", 1)) if ramp is not None else None


def your_ef(ef_now=None, ef_before=None, **_) -> str | None:
    if not ef_now:
        return None
    out = f"Your recent efficiency factor is {float(ef_now):.2f}."
    if ef_before:
        d = float(ef_now) - float(ef_before)
        if d > 0.03:
            out += " That is up on earlier in this period, a good sign for your aerobic fitness."
        elif d < -0.03:
            out += " That is down on earlier in this period. Tiredness or heat can cause this."
        else:
            out += " That is about the same as earlier in this period."
    return out


def your_peaks(best=None, weight=None, **_) -> str | None:
    if not best:
        return None
    parts = []
    for secs, label in ((300, "5 minutes"), (1200, "20 minutes")):
        entry = best.get(secs)
        watts = entry["watts"] if isinstance(entry, dict) else entry
        if watts:
            bit = f"{label} is {_w(watts)}"
            if weight:
                bit += f" ({watts / float(weight):.2f} W/kg)"
            parts.append(bit)
    return ("Your best " + " and your best ".join(parts) + ".") if parts else None


def your_profile(category=None, **_) -> str | None:
    return f"Your strongest bar is in the {category} range." if category else None


def your_wkg(ftp=None, weight=None, weight_unit="kg", **_) -> str | None:
    if not ftp or not weight:
        return None
    from metrics.units import fmt_weight
    return (f"Your FTP of {_w(ftp)} at {fmt_weight(weight, weight_unit)} is "
            f"{float(ftp) / float(weight):.2f} W/kg.")


PERSONAL = {
    "ftp": your_ftp, "tss": your_tss, "if": your_if, "np": your_np, "ctl": your_ctl,
    "atl": your_atl, "tsb": your_tsb, "ramp": your_ramp, "ef": your_ef,
    "peak_power": your_peaks, "power_profile": your_profile, "wkg": your_wkg,
}


def key_numbers_line(ctl=None, atl=None, tsb=None, ramp=None, **_) -> str | None:
    parts = [p for p in (your_ctl(ctl=ctl, ramp=ramp), your_atl(atl=atl, ctl=ctl),
                         your_tsb(tsb=tsb, ctl=ctl)) if p]
    return " ".join(parts) or None


PERSONAL["key_numbers"] = key_numbers_line


def card(term: str, **numbers) -> str:
    """The finished help text for one term: what it is, why it matters, and the
    rider's own number when it can be worked out."""
    entry = TERMS[term]
    out = [f"**{entry['title']}**", f"**What it is.** {entry['what']}",
           f"**Why it matters.** {entry['why']}"]
    fn = PERSONAL.get(term)
    mine = fn(**numbers) if fn else None
    if mine:
        out.append(f"**Your number.** {mine}")
    return "\n\n".join(out)


# ── What a workout should feel like ───────────────────────────────────────────

FEEL = {
    "Recovery": "2 out of 10. Very easy. You could talk the whole time and it should feel almost too slow.",
    "Endurance": "3 to 4 out of 10. Steady and comfortable. You can chat in full sentences.",
    "Long Ride": "3 to 4 out of 10 at the start and still controlled at the end. Chat in full sentences, "
                 "and eat and drink on a schedule.",
    "Tempo": "5 to 6 out of 10. Working but sustainable. You can talk in short sentences.",
    "Threshold": "7 to 8 out of 10. Hard but even. You can say a few words at a time, no more.",
    "VO2 Max": "9 out of 10 in each interval. Very hard, one or two words at a time. "
               "The rest between intervals should feel like real recovery.",
    "Sprint/Anaerobic": "10 out of 10 for the short bursts, then fully easy in between.",
    "Race": "Whatever the race asks for. Start controlled and save your hardest efforts for the key moments.",
    "Other": "Follow the description. If you are unsure, ride it by effort and keep it conversational.",
}


def feel_for(workout_type: str | None) -> str:
    return FEEL.get(workout_type or "Other", FEEL["Other"])


# What each kind of workout is for, in plain words, used when a plan was made
# without the coach (Quick Generate).
PURPOSE = {
    "Recovery": "Gentle spinning to get blood moving and help your legs absorb the harder days. "
                "Easier is better here.",
    "Endurance": "Builds your aerobic base, the foundation that everything else sits on. "
                 "It also teaches your body to burn fat and ride for longer.",
    "Long Ride": "Builds endurance and mental toughness, and practises eating and drinking on the bike.",
    "Tempo": "Teaches you to hold a firm, steady effort. It raises the pace you can sustain without "
             "costing as much recovery as threshold work.",
    "Threshold": "Raises the power you can hold for a long time, which is the biggest single driver "
                 "of how fast you ride.",
    "VO2 Max": "Hard intervals that raise your top end, the ceiling for everything below it. "
               "Short but demanding, so the rest of the week stays easy.",
    "Sprint/Anaerobic": "Short, all out efforts that build sprint power and your ability to handle surges.",
    "Race": "A chance to practise racing, or a hard effort that tests your fitness.",
    "Other": "A session set by you or your coach.",
}

PHASE_NOTES = {
    "Base / Endurance": {
        "focus": "Build your aerobic base.",
        "why": "A strong base lets you handle harder training later and recover faster from it. "
               "Most of this block is steady and comfortable on purpose.",
    },
    "Build / Threshold": {
        "focus": "Raise the power you can hold.",
        "why": "With a base in place, harder threshold and VO2 work turns that fitness into speed. "
               "Expect the hard days to feel hard and the easy days to stay easy.",
    },
    "Peak / Sharpening": {
        "focus": "Arrive fresh and sharp.",
        "why": "Volume comes down so fatigue drains away while short, race like efforts keep your "
               "legs sharp. Feeling a bit restless is normal.",
    },
}

TAPER_NOTE = {"focus": "Taper before the race.",
              "why": "Less riding in the final days lets your fatigue fall while your fitness stays. "
                     "You should feel fresher each day."}


# ── FTP help ──────────────────────────────────────────────────────────────────

# ── A friendly starting FTP ───────────────────────────────────────────────────
# Rough typical FTP in watts per kilo for each kind of rider, so a newcomer who
# does not know their FTP gets a believable range instead of a blank. These are
# deliberately modest rules of thumb, and the first block's FTP test replaces them.

# One question covers both "how experienced are you" and "how long have you ridden".
# `wkg` is the typical FTP range in watts per kilo for a man at that level.
RIDER_TYPES = {
    "New to cycling": {
        "experience": "New to structured training", "wkg": (1.2, 1.8),
        "detail": "I'm just starting out, or getting back on a bike after a long break."},
    "I ride, but without a plan": {
        "experience": "New to structured training", "wkg": (2.0, 2.7),
        "detail": "I ride fairly regularly for fun or fitness, but I don't follow a training plan."},
    "I've followed a training plan": {
        "experience": "Some structured training experience", "wkg": (2.6, 3.3),
        "detail": "I've done structured training before, with intervals or power or heart rate zones."},
    "I race or have raced": {
        "experience": "Experienced racer", "wkg": (3.2, 4.0),
        "detail": "I train seriously and race, or used to."},
}
DEFAULT_RIDER_TYPE = "New to cycling"

# Typical power per kilo for women is lower than for men. The published Allen and Coggan
# tables put it at about 0.81 to 0.89 of the male values, and 0.85 suits the beginner range
# used here. This is only about picking a typical range, not about anyone's identity.
# Non-binary riders, and anyone who would rather not say, get the middle of the two.
GENDER_LABELS = {"Woman": "woman", "Man": "man", "Non-binary": "nonbinary",
                 "Prefer not to say": "unspecified"}
GENDER_FACTOR = {"man": 1.0, "woman": 0.85, "nonbinary": 0.925, "unspecified": 0.925}
GENDER_PROFILE_TABLE = {"man": "Men", "woman": "Women"}      # others pick on the Progress page
DEFAULT_GENDER = "unspecified"


def experience_for(rider_type: str | None) -> str:
    """The app's experience level (new, some, experienced) for a rider type."""
    return RIDER_TYPES.get(rider_type or DEFAULT_RIDER_TYPE, RIDER_TYPES[DEFAULT_RIDER_TYPE])["experience"]


ACTIVITY_LEVEL = {
    "Mostly inactive": -0.2,
    "Lightly active": 0.0,
    "Moderately active": 0.15,
    "Very active": 0.35,
}
# What each level means in plain numbers, shown under the option so nobody has to guess.
ACTIVITY_DETAILS = {
    "Mostly inactive": "Little or no planned exercise. Under 1 hour a week, mostly walking day to day.",
    "Lightly active": "1 to 3 sessions a week, about 1 to 3 hours in total, at an easy to moderate effort. "
                      "For example walks, easy rides or light gym.",
    "Moderately active": "3 to 4 sessions a week, about 3 to 5 hours in total, with some harder efforts "
                         "where you get properly out of breath. For example jogging, sport or the gym.",
    "Very active": "5 or more sessions a week, 6 or more hours in total, with regular hard efforts. "
                   "For example training for a sport or race.",
}
DEFAULT_ACTIVITY = "Lightly active"


def _round5(w: float) -> int:
    return int(round(w / 5.0) * 5)


# Age. Power falls by roughly 1 percent a year in the masters years, and maximum heart
# rate falls with age too. Both are rules of thumb for a starting point, not for judging anyone.
PRIME_UNTIL_AGE = 35
FTP_LOSS_PER_YEAR = 0.008
FTP_AGE_FLOOR = 0.65
YOUTH_FACTOR = 0.9           # under 18, still developing
MIN_AGE, MAX_AGE = 12, 95


def age_from_birth_year(birth_year: int | None, today: date | None = None) -> int | None:
    """Age this year, or None when the birth year is missing or not believable."""
    try:
        age = (today or date.today()).year - int(birth_year)
    except (TypeError, ValueError):
        return None
    return age if MIN_AGE <= age <= MAX_AGE else None


def age_factor(age: float | None) -> float:
    """How much of a prime age rider's power to expect. 1.0 from 18 to 35, about 8 percent
    less at 45, 20 percent less at 60. No age means no adjustment."""
    if not age:
        return 1.0
    if age < 18:
        return YOUTH_FACTOR
    if age <= PRIME_UNTIL_AGE:
        return 1.0
    return max(1 - FTP_LOSS_PER_YEAR * (age - PRIME_UNTIL_AGE), FTP_AGE_FLOOR)


def max_hr_from_age(age: float) -> int:
    """Estimated maximum heart rate, from the Tanaka formula (208 minus 0.7 x age)."""
    return round(208 - 0.7 * float(age))


def lthr_from_age(age: float) -> int:
    """A starting threshold heart rate, about 89 percent of the estimated maximum."""
    return round(0.89 * max_hr_from_age(age))


def starting_ftp_range(weight_kg: float, rider_type: str | None = None, activity: str | None = None,
                       gender: str | None = None, age: float | None = None) -> dict:
    """A typical FTP range and a starting value for someone who doesn't know theirs.
    From what kind of rider they are, how active they are, gender (woman, man,
    nonbinary or unspecified), age (optional) and weight. Returns {low, high, start} in watts and
    {low_wkg, high_wkg, start_wkg}."""
    base_low, base_high = RIDER_TYPES.get(rider_type or DEFAULT_RIDER_TYPE,
                                          RIDER_TYPES[DEFAULT_RIDER_TYPE])["wkg"]
    adj = ACTIVITY_LEVEL.get(activity or DEFAULT_ACTIVITY, 0.0)
    factor = GENDER_FACTOR.get(gender or DEFAULT_GENDER, GENDER_FACTOR[DEFAULT_GENDER]) * age_factor(age)
    low_wkg = max((base_low + adj) * factor, 0.9)
    high_wkg = max((base_high + adj) * factor, 1.3)
    mid_wkg = (low_wkg + high_wkg) / 2
    low, high, start = (_round5(weight_kg * x) for x in (low_wkg, high_wkg, mid_wkg))
    low, high = min(low, start), max(high, start)
    return {"low": low, "high": high, "start": start,
            "low_wkg": round(low_wkg, 2), "high_wkg": round(high_wkg, 2), "start_wkg": round(mid_wkg, 2)}


def ftp_reassurance(low: float, high: float, start: float | None = None) -> str:
    """A kind explanation of the starting range, for a rider who doesn't know their FTP."""
    out = f"People like you usually start somewhere between {low:.0f} and {high:.0f} watts."
    if start:
        out += f" We have started you at {start:.0f} W."
    out += (" That is only a starting point, and being well below what you will reach in a few months is "
            "completely normal. Everyone starts somewhere, and your first block will find your real number.")
    return out


def suggest_ftp(peak_rows: list, today: date, days: int = 42) -> dict | None:
    """95% of the best 20 minute power in the last `days`, with the ride it came
    from. None when there is no 20 minute power in that window."""
    since = (today - timedelta(days=days)).isoformat()
    best = None
    for p in peak_rows:
        if int(p.get("duration_s", 0)) != 1200 or str(p.get("date"))[:10] < since:
            continue
        if best is None or p["watts"] > best["watts"]:
            best = p
    if not best:
        return None
    return {"ftp": round(best["watts"] * 0.95), "watts": round(best["watts"]),
            "date": str(best["date"])[:10], "name": best.get("name") or "Ride"}


def ftp_test_workout(day: date, has_power: bool = True, gentle: bool = False) -> dict:
    """A guided 20 minute FTP test, as a workout dict ready for the planner.
    `gentle` is for newcomers. The effort is the same one steady 20 minutes but described
    as a pace they can hold, with no pass or fail."""
    if has_power:
        steps = ("Warm up 15 minutes easy, then 3 x 1 minute at a hard cadence with 1 minute easy between. "
                 "Ride 5 minutes easy. Then 20 minutes as hard as you can hold evenly, starting a little "
                 "under what feels possible so you can finish strong. Cool down 10 minutes easy.")
        use = "Your FTP is 95% of your average power for the 20 minutes."
    else:
        steps = ("Warm up 15 minutes easy, then 3 x 1 minute at a hard cadence with 1 minute easy between. "
                 "Ride 5 minutes easy. Then 20 minutes as hard as you can hold evenly. Cool down 10 minutes easy.")
        use = "Your threshold heart rate is your average heart rate over the last 10 minutes of the 20."
    return {
        "date": day.isoformat(), "name": "FTP test (20 minutes)", "workout_type": "Threshold",
        "description": f"{steps} {use}", "tss_planned": 75.0,
        "purpose": "Finds your FTP so every zone and training stress number in the app fits you. "
                   "Do it fresh, after an easy day or two."
                   + (" There is no pass or fail, and any result is a good starting point." if gentle else ""),
        "feel": ("Hard but steady, about 8 out of 10, a pace you could just about hold for 20 minutes. "
                 "It is one steady effort, not a race. Start a little easier than feels necessary, and "
                 "if you can, finish a touch stronger than you began.") if gentle else
                ("10 out of 10 effort across the 20 minutes, but even. If you blow up in the first "
                 "5 minutes you started too hard."),
    }


# ── Getting started checklist ─────────────────────────────────────────────────

def checklist(state: dict) -> list[dict]:
    """Steps for a new rider, each with whether it is done. `state` keys, all
    optional and falsy when unknown: connected, ftp_confirmed, rides, workouts,
    rides_since_plan."""
    steps = [
        ("connect", "Connect Garmin or Strava",
         "So your rides come in on their own and your numbers stay up to date.",
         bool(state.get("connected"))),
        ("ftp", "Set your FTP",
         "Every zone and training stress number is based on it. Don't know it? No problem, "
         "your first block includes an FTP test to find it.",
         bool(state.get("ftp_confirmed"))),
        ("rides", "Sync your first rides",
         "Fitness, fatigue and form need a few weeks of rides to mean anything.",
         int(state.get("rides") or 0) > 0),
        ("block", "Build your first block with the coach",
         "A block is a few weeks of workouts that build on each other toward your goal.",
         int(state.get("workouts") or 0) > 0),
        ("week", "Ride your first week and check your form",
         "After a week, look at fitness, fatigue and form on the Today page to see what the work did.",
         int(state.get("rides_since_plan") or 0) >= 3),
    ]
    return [{"key": k, "title": t, "why": w, "done": d} for k, t, w, d in steps]


def first_block_message(*, goals: list[str], experience: str, hours: float | None,
                        ftp: float | None, ftp_estimated: bool, race: dict | None = None,
                        name: str | None = None, days: float | None = None,
                        skip_test: bool = False) -> str:
    """The first message sent to the coach for a new rider."""
    goal_text = "; ".join(goals) if goals else "general fitness"
    time = ""
    if hours and days:
        time = f" and I can train about {hours:g} hours a week, spread over {days:g} days"
    elif hours:
        time = f" and I can train about {hours:g} hours a week"
    elif days:
        time = f" and I can train {days:g} days a week"
    lines = [
        f"Hi, I'm {name}." if name else "Hi.",
        f"My goals, in my own words, are: {goal_text}. My training experience is {experience.lower()}"
        + time + ".",
    ]
    if race:
        lines.append(f"My main race is {race.get('name') or 'a race'} on {race.get('date')}.")
    if ftp:
        lines.append(f"My FTP is set to {float(ftp):.0f} W"
                     + (", but that is only an estimate because I do not know my real one." if ftp_estimated else "."))
    if ftp_estimated and skip_test:
        lines.append("I would rather not do an FTP test, so please plan around the estimate and keep the first "
                     "weeks forgiving. Say how the plan will be refined as my rides come in.")
    elif ftp_estimated:
        lines.append("Please build a guided 20 minute FTP test into the first week, after a couple of easy "
                     "days, and tell me how the rest of the block will be adjusted once we know the result. "
                     "Keep the days before the test forgiving.")
    lines.append(
        "Please build me a first training block of about four weeks, starting easy. Explain in plain "
        "words what the block is trying to build and why, what each week is for, and for every "
        "workout what it is for, what I should focus on, and how it should feel. Define any "
        "training terms the first time you use them. Include strength sessions if they fit my goals.")
    return " ".join(lines)
