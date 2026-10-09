"""Training Stress Score for a ride, in one place so every source agrees.

Duration is the device's timer time when the source gives it (Garmin, FIT files), the same time
Garmin and TrainingPeaks score against, else moving time (Strava). Elapsed time is only a
fallback, since it counts coffee stops. The timer time is stored, so recalculating a ride gives
back the TSS it was synced with.

Power TSS is Coggan's: hours x IF squared x 100, where IF is NP / FTP.

Heart rate TSS (hrTSS) is Banister's TRIMP, which weights each minute by heart rate reserve on
an exponential curve so hard minutes count for much more than easy ones:

    TRIMP per minute = HRR x 0.64 x e^(k x HRR),  HRR = (HR - resting) / (max - resting)

with k = 1.92 for men and 1.67 for women. As TrainingPeaks does, it is scaled by the TRIMP of an
hour at threshold heart rate, so an hour at LTHR scores 100, the same as an hour at FTP. The 0.64
cancels out in that ratio.

The source of each ride's number is kept (power, hr, mixed, estimate, manual) so the app can say
when a ride was scored from heart rate.
"""
from __future__ import annotations

import numpy as np

K_BY_GENDER = {"man": 1.92, "woman": 1.67}
DEFAULT_K = (1.92 + 1.67) / 2          # non-binary or not given
MIN_GAP_S = 60                         # a power dropout shorter than this isn't worth patching

SOURCE_LABEL = {"power": "TSS", "hr": "hrTSS", "mixed": "TSS + hrTSS",
                "estimate": "est. TSS", "manual": "TSS"}
SOURCE_FROM = {"power": "Power", "hr": "Heart rate", "mixed": "Power + HR",
               "estimate": "Estimate", "manual": "You"}


def k_for(gender: str | None) -> float:
    return K_BY_GENDER.get(gender or "", DEFAULT_K)


def profile_ok(profile: dict | None, lthr: float | None) -> bool:
    """True when resting, threshold and max heart rate are in a sensible order."""
    if not profile or not lthr:
        return False
    rest, mx = profile.get("rest"), profile.get("max")
    return bool(rest and mx and 25 <= rest < lthr < mx <= 230)


def _weight(hr, profile: dict):
    """TRIMP weight of a heart rate (scalar or numpy array): HRR x e^(k x HRR)."""
    hrr = np.clip((np.asarray(hr, dtype=float) - profile["rest"]) / (profile["max"] - profile["rest"]), 0, 1)
    return hrr * np.exp(profile.get("k", DEFAULT_K) * hrr)


def power_tss(duration_s: float, norm_power: float | None, ftp: float | None) -> float | None:
    if not ftp or ftp <= 0 or not norm_power or norm_power <= 0:
        return None
    return (duration_s / 3600) * ((norm_power / ftp) ** 2) * 100


def hr_tss(duration_s: float, avg_hr: float | None, lthr: float | None,
           profile: dict | None = None) -> float | None:
    """hrTSS from average heart rate. Uses TRIMP when resting and max heart rate are known,
    else the simpler (HR / LTHR) squared."""
    if not lthr or lthr <= 0 or not avg_hr or avg_hr <= 0:
        return None
    if profile_ok(profile, lthr):
        return (duration_s / 3600) * float(_weight(avg_hr, profile) / _weight(lthr, profile)) * 100
    return (duration_s / 3600) * ((avg_hr / lthr) ** 2) * 100


def hr_tss_seconds(hr_values, lthr: float | None, profile: dict | None = None) -> float | None:
    """hrTSS from second by second heart rate (one value per second, no gaps). Scoring each
    second rather than the average counts hard surges properly, since the curve is steep."""
    hr = np.asarray([h for h in hr_values if h is not None and h > 0], dtype=float)
    if not len(hr) or not lthr or lthr <= 0:
        return None
    if profile_ok(profile, lthr):
        per_sec = _weight(hr, profile) / _weight(lthr, profile)
    else:
        per_sec = (hr / lthr) ** 2
    return float(per_sec.sum()) / 3600 * 100


def estimated_tss(duration_s: float, perceived_exertion: float | None,
                  avg_hr: float | None, max_hr: float | None) -> float:
    """Fallback when there's no power and no threshold heart rate. Uses perceived exertion
    (1-10) if given, then average over max heart rate, then assumes an easy ride."""
    duration_h = duration_s / 3600
    if perceived_exertion and 1 <= perceived_exertion <= 10:
        intensity = 0.4 + (perceived_exertion - 1) * 0.072
    elif avg_hr and max_hr and max_hr > 0:
        intensity = max(0.4, min(1.05, avg_hr / max_hr * 1.05))
    else:
        intensity = 0.65
    return round(duration_h * intensity ** 2 * 100, 1)


def tss_duration(moving_s: float | None, elapsed_s: float | None = None,
                 timer_s: float | None = None) -> float:
    """The seconds TSS is scored against: the device's timer time when known (what Garmin and
    TrainingPeaks score on), else moving time, else elapsed."""
    return float(timer_s or moving_s or elapsed_s or 0)


def ride_tss(duration_s: float, norm_power: float | None, avg_hr: float | None,
             max_hr: float | None, ftp: float | None, lthr: float | None,
             perceived_exertion: float | None = None,
             profile: dict | None = None) -> tuple[float | None, float | None, str | None]:
    """(tss, intensity factor, source) for a ride from its summary numbers: power, else heart
    rate (hrTSS), else an estimate."""
    if not duration_s or duration_s <= 0:
        return None, None, None
    if_value = (norm_power / ftp) if (norm_power and ftp) else None
    tss = power_tss(duration_s, norm_power, ftp)
    if tss is not None:
        return tss, if_value, "power"
    tss = hr_tss(duration_s, avg_hr, lthr, profile)
    if tss is not None:
        return tss, if_value, "hr"
    return estimated_tss(duration_s, perceived_exertion, avg_hr, max_hr), if_value, "estimate"


def stream_tss(streams: dict | None, ftp: float | None, lthr: float | None,
               profile: dict | None = None) -> tuple[float, str] | None:
    """(tss, source) from second by second data, when it says more than the ride summary:
    - no power at all but heart rate: hrTSS scored second by second ("hr");
    - power that drops out for MIN_GAP_S or more while heart rate keeps recording: power TSS for
      the seconds with power plus hrTSS for the gap ("mixed").
    None when power covers the ride (the summary number is right) or there's nothing to go on.
    A gap means no power reading at all; zeros are real coasting and count as power."""
    if not streams:
        return None
    power, hr = streams.get("power") or [], streams.get("hr") or []
    if not hr:
        return None
    n = max(len(power), len(hr))
    has_power = any(p is not None for p in power)

    if not has_power:
        tss = hr_tss_seconds(hr, lthr, profile)
        return (tss, "hr") if tss and len([h for h in hr if h]) >= MIN_GAP_S else None

    gap_hr = [hr[i] for i in range(min(n, len(hr)))
              if (i >= len(power) or power[i] is None) and hr[i] is not None]
    if len(gap_hr) < MIN_GAP_S:
        return None
    from metrics.streams import normalized_power
    with_power = [p for p in power if p is not None]
    np_w = normalized_power(with_power)
    p_tss = power_tss(len(with_power), np_w, ftp)
    h_tss = hr_tss_seconds(gap_hr, lthr, profile)
    if p_tss is None or h_tss is None:
        return None
    return p_tss + h_tss, "mixed"


def label(source: str | None) -> str:
    """What to call a ride's number: TSS, hrTSS, TSS + hrTSS or est. TSS."""
    return SOURCE_LABEL.get(source or "", "TSS")


def robust_max_hr(maxes: list[float], within: float = 5) -> float | None:
    """The highest max heart rate that another ride comes close to, so a one off strap glitch
    (208 when every other ride tops out under 198) doesn't set it. If no two rides are that
    close, the second highest; with a single ride, that ride."""
    vals = sorted((float(m) for m in maxes if m and 100 <= m <= 230), reverse=True)
    if not vals:
        return None
    for i, v in enumerate(vals[:-1]):
        if v - vals[i + 1] <= within:
            return v
    return vals[0] if len(vals) == 1 else vals[1]
