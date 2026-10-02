"""
CTL / ATL / TSB calculations using the standard Coggan Performance Manager
model (the same one TrainingPeaks uses) — exponentially weighted moving
averages of daily TSS, not a flat windowed average.

Fitness (CTL) = CTL_yesterday + (TSS_today - CTL_yesterday) * (1 - exp(-1/42))
Fatigue (ATL) = ATL_yesterday + (TSS_today - ATL_yesterday) * (1 - exp(-1/7))
Form (TSB)    = yesterday's CTL minus yesterday's ATL
"""

import math
from datetime import date, timedelta
import pandas as pd
from db.queries import get_daily_tss, get_setting

CTL_DAYS = 42
ATL_DAYS = 7
CTL_ALPHA = 1 - math.exp(-1 / CTL_DAYS)
ATL_ALPHA = 1 - math.exp(-1 / ATL_DAYS)


def compute_pmc(
    start: date,
    end: date,
    initial_ctl: float = 0.0,
    initial_atl: float = 0.0,
) -> pd.DataFrame:
    """
    Return a DataFrame [date, tss, ctl, atl, tsb] for every day in [start, end].

    initial_ctl/initial_atl seed the EWMA as of the day before the lookback
    window starts, then the exponential average is carried forward day by
    day through to `end` — the same recursive update TrainingPeaks uses,
    so a fitness/fatigue baseline set once continues to evolve correctly
    rather than needing re-seeding.
    """
    # Lookback lets the EWMA settle before `start` so the seed value isn't
    # still dominating the displayed range.
    lookback_start = start - timedelta(days=CTL_DAYS)
    tss_map = get_daily_tss(lookback_start.isoformat(), end.isoformat())

    all_days = []
    current = lookback_start
    while current <= end:
        all_days.append((current, tss_map.get(current.isoformat(), 0.0)))
        current += timedelta(days=1)

    rows = []
    ctl, atl = initial_ctl, initial_atl
    for day, tss in all_days:
        prev_ctl, prev_atl = ctl, atl
        ctl = round(prev_ctl + (tss - prev_ctl) * CTL_ALPHA, 2)
        atl = round(prev_atl + (tss - prev_atl) * ATL_ALPHA, 2)
        # TSB uses yesterday's CTL/ATL, i.e. the values going into today's update.
        tsb = round(prev_ctl - prev_atl, 2)
        if day >= start:
            rows.append({"date": day, "tss": tss, "ctl": ctl, "atl": atl, "tsb": tsb})

    return pd.DataFrame(rows)


def get_current_metrics() -> dict:
    """Return today's CTL/ATL/TSB and 7-day ramp rate."""
    initial_ctl = float(get_setting("ctl_start", 0) or 0)
    initial_atl = float(get_setting("atl_start", 0) or 0)

    start = date.today() - timedelta(days=90)
    end = date.today()

    df = compute_pmc(start, end, initial_ctl, initial_atl)
    if df.empty:
        return {"ctl": 0, "atl": 0, "tsb": 0, "ramp_rate": 0}

    today = df.iloc[-1]
    week_ago = df.iloc[-8] if len(df) >= 8 else df.iloc[0]
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
