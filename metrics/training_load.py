"""
CTL / ATL / TSB calculations using the standard Coggan Performance Manager
model (the same one TrainingPeaks uses) — exponentially weighted moving
averages of daily TSS, not a flat windowed average.

Fitness (CTL) = CTL_yesterday + (TSS_today - CTL_yesterday) * (1 - exp(-1/42))
Fatigue (ATL) = ATL_yesterday + (TSS_today - ATL_yesterday) * (1 - exp(-1/7))
Form (TSB)    = yesterday's CTL minus yesterday's ATL
"""

from __future__ import annotations
import math
from datetime import date, timedelta
import pandas as pd
from db.queries import get_daily_tss, get_setting

CTL_DAYS = 42
ATL_DAYS = 7
CTL_ALPHA = 1 - math.exp(-1 / CTL_DAYS)
ATL_ALPHA = 1 - math.exp(-1 / ATL_DAYS)


def _seeds() -> tuple[float, float]:
    return (float(get_setting("ctl_start", 0) or 0),
            float(get_setting("atl_start", 0) or 0))


# compute_pmc carries the seed in from the day before the first ride and lets it fade like any old
# training: after six weeks (one CTL time constant) about a third of it is left, after three months
# about a tenth. It is never dropped outright, since rides alone would start fitness from zero and
# read about a third low at six weeks.
SEED_COVER_DAYS = 42
# Under four weeks of rides, CTL and ATL still lean mostly on the seed.
ESTIMATED_UNDER_DAYS = 28


# How much ride history to ask a new rider for. Six weeks is one CTL time constant and the window
# the FTP suggestion reads. Three months lets fitness settle and matches Garmin's first sync. A year
# also covers max heart rate (read over 12 months) and season bests; older rides add little.
HISTORY_MIN_DAYS = SEED_COVER_DAYS
HISTORY_GOOD_DAYS = 90
HISTORY_FULL_DAYS = 365
HISTORY_ASK = ("Best is the last 3 months of rides, and at least 6 weeks. Up to a year also "
               "brings in season bests and max heart rate. Rides older than a year add little.")


def history_note(days: int) -> str:
    """What a stretch of ride history is enough for, in words for the rider or coach."""
    if days <= 0:
        return ""
    if days < HISTORY_MIN_DAYS:
        return (f"Rides go back {_span(days)}. Fitness and the FTP suggestion need at least 6 weeks, "
                "so add older rides if there are any.")
    if days < HISTORY_GOOD_DAYS:
        return (f"Rides go back {_span(days)}, enough for fitness and the FTP suggestion. "
                "3 months makes fitness more accurate.")
    if days < HISTORY_FULL_DAYS:
        return (f"Rides go back {_span(days)}, enough for fitness and FTP. Up to a year also brings in "
                "season bests and max heart rate.")
    return "Rides go back a year or more, everything the app uses."


def _span(days: int) -> str:
    if days < 14:
        return f"{days} day" + ("s" if days != 1 else "")
    if days < 90:
        return f"{days // 7} weeks"
    return f"{round(days / 30.4)} months"


def history_days(today: date | None = None) -> int:
    """Days of activity history up to today, 0 when there is none."""
    from db.queries import first_activity_date
    first = first_activity_date()
    if not first:
        return 0
    return max(((today or date.today()) - date.fromisoformat(first[:10])).days, 0)


def compute_pmc(
    start: date,
    end: date,
    initial_ctl: float | None = None,
    initial_atl: float | None = None,
) -> pd.DataFrame:
    """
    Return a DataFrame [date, tss, ctl, atl, tsb] for every day in [start, end].

    The EWMA always starts the day before the first recorded ride, seeded with
    the rider's starting fitness/fatigue (ctl_start / atl_start settings unless
    passed in), and is carried forward day by day. Anchoring to the start of
    history rather than to `start` means every page shows the same CTL for a
    given day, whatever window it asks for.
    """
    if initial_ctl is None or initial_atl is None:
        ctl_seed, atl_seed = _seeds()
        initial_ctl = ctl_seed if initial_ctl is None else initial_ctl
        initial_atl = atl_seed if initial_atl is None else initial_atl

    # One grouped query covers all of history; a rider has at most a few
    # hundred ride days, so this is cheaper than a second lookup for the anchor.
    tss_map = get_daily_tss("0000-01-01", end.isoformat())
    anchor = date.fromisoformat(min(tss_map)) if tss_map else start

    rows = []
    ctl, atl = initial_ctl, initial_atl
    current = min(start, anchor)
    while current <= end:
        tss = tss_map.get(current.isoformat(), 0.0)
        prev_ctl, prev_atl = ctl, atl
        if current >= anchor:
            ctl = round(prev_ctl + (tss - prev_ctl) * CTL_ALPHA, 2)
            atl = round(prev_atl + (tss - prev_atl) * ATL_ALPHA, 2)
        # TSB uses yesterday's CTL/ATL, i.e. the values going into today's update.
        tsb = round(prev_ctl - prev_atl, 2)
        if current >= start:
            rows.append({"date": current, "tss": tss, "ctl": ctl, "atl": atl, "tsb": tsb})
        current += timedelta(days=1)

    return pd.DataFrame(rows)


def get_current_metrics() -> dict:
    """Return today's CTL/ATL/TSB and 7-day ramp rate."""
    end = date.today()
    df = compute_pmc(end - timedelta(days=7), end)
    if df.empty:
        return {"ctl": 0, "atl": 0, "tsb": 0, "ramp_rate": 0}

    today = df.iloc[-1]
    week_ago = df.iloc[0]
    ramp_rate = round(today["ctl"] - week_ago["ctl"], 2)

    return {
        "ctl": today["ctl"],
        "atl": today["atl"],
        "tsb": today["tsb"],
        "ramp_rate": ramp_rate,
    }


def project_future(
    current_ctl: float,
    current_atl: float,
    planned_tss: dict,   # {date_str: tss}
    days_ahead: int = 42,
) -> pd.DataFrame:
    """Project CTL/ATL/TSB forward from today's actual values using a planned
    TSS schedule, via the same EWMA update compute_pmc uses."""
    rows = []
    ctl, atl = current_ctl, current_atl
    for i in range(days_ahead):
        day = date.today() + timedelta(days=i + 1)
        tss = planned_tss.get(day.isoformat(), 0.0)
        prev_ctl, prev_atl = ctl, atl
        ctl = round(prev_ctl + (tss - prev_ctl) * CTL_ALPHA, 2)
        atl = round(prev_atl + (tss - prev_atl) * ATL_ALPHA, 2)
        tsb = round(prev_ctl - prev_atl, 2)
        rows.append({"date": day, "tss": tss, "ctl": ctl, "atl": atl, "tsb": tsb})

    return pd.DataFrame(rows)
