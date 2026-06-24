"""
CTL / ATL / TSB calculations using simple rolling averages.

Fitness (CTL)  = 42-day rolling average of daily TSS
Fatigue (ATL)  = 7-day rolling average of daily TSS
Form (TSB)     = yesterday's CTL minus yesterday's ATL
"""

from datetime import date, timedelta
import pandas as pd
from db.queries import get_daily_tss, get_setting

CTL_DAYS = 42
ATL_DAYS = 7


def compute_pmc(
    start: date,
    end: date,
    initial_ctl: float = 0.0,
    initial_atl: float = 0.0,
) -> pd.DataFrame:
    """
    Return a DataFrame [date, tss, ctl, atl, tsb] for every day in [start, end].

    CTL = simple 42-day rolling average of daily TSS
    ATL = simple 7-day rolling average of daily TSS
    TSB = yesterday's CTL - yesterday's ATL
    """
    # Fetch enough history before start to fill the 42-day window
    lookback_start = start - timedelta(days=CTL_DAYS)
    tss_map = get_daily_tss(lookback_start.isoformat(), end.isoformat())

    # Build a full daily TSS list from lookback_start to end
    all_days = []
    current = lookback_start
    while current <= end:
        all_days.append((current, tss_map.get(current.isoformat(), 0.0)))
        current += timedelta(days=1)

    rows = []
    for i, (day, tss) in enumerate(all_days):
        if day < start:
            continue

        # 42-day window ending today
        ctl_window = [t for _, t in all_days[max(0, i - CTL_DAYS + 1): i + 1]]
        ctl = round(sum(ctl_window) / CTL_DAYS, 2)

        # 7-day window ending today
        atl_window = [t for _, t in all_days[max(0, i - ATL_DAYS + 1): i + 1]]
        atl = round(sum(atl_window) / ATL_DAYS, 2)

        # TSB = yesterday's CTL - yesterday's ATL
        if rows:
            tsb = round(rows[-1]["ctl"] - rows[-1]["atl"], 2)
        else:
            tsb = round(initial_ctl - initial_atl, 2)

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
    """Project CTL/ATL/TSB forward using a planned TSS schedule."""
    # Seed a TSS history window from recent actuals + planned
    from db.queries import get_daily_tss as _get_tss
    history_start = date.today() - timedelta(days=CTL_DAYS)
    history = _get_tss(history_start.isoformat(), date.today().isoformat())

    # Build combined window: past actuals + future planned
    all_days = []
    d = history_start
    while d <= date.today():
        all_days.append((d, history.get(d.isoformat(), 0.0)))
        d += timedelta(days=1)
    for i in range(days_ahead):
        d = date.today() + timedelta(days=i + 1)
        all_days.append((d, planned_tss.get(d.isoformat(), 0.0)))

    rows = []
    today_idx = next(i for i, (day, _) in enumerate(all_days) if day == date.today())

    prev_ctl, prev_atl = current_ctl, current_atl
    for i in range(today_idx + 1, len(all_days)):
        day, tss = all_days[i]

        ctl_window = [t for _, t in all_days[max(0, i - CTL_DAYS + 1): i + 1]]
        ctl = round(sum(ctl_window) / CTL_DAYS, 2)

        atl_window = [t for _, t in all_days[max(0, i - ATL_DAYS + 1): i + 1]]
        atl = round(sum(atl_window) / ATL_DAYS, 2)

        tsb = round(prev_ctl - prev_atl, 2)
        rows.append({"date": day, "tss": tss, "ctl": ctl, "atl": atl, "tsb": tsb})
        prev_ctl, prev_atl = ctl, atl

    return pd.DataFrame(rows)
