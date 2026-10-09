"""Training Stress Score for a ride, in one place so every source agrees.

The app scores rides like one of three standards (STANDARDS), chosen in Settings as "Score like":

- TrainingPeaks: Coggan power TSS, the fitted TrainingPeaks heart rate curve, timer time.
- intervals.icu: Coggan power TSS, HRSS for heart rate (normalized TRIMP, second by second, as
  intervals.icu takes from Elevate) and moving time, since intervals.icu leaves out time stopped.
- The published standard: Coggan power TSS, Banister's TRIMP for heart rate, timer time.

Duration follows the standard's time rule. Timer time is the device's timer (Garmin, FIT files),
the time Garmin and TrainingPeaks score against; moving time leaves out stops. Each falls back
to the other, then to elapsed time, which counts coffee stops. Timer and moving time are both
stored, so recalculating a ride gives back the TSS it was synced with.

Power TSS is Coggan's: hours x IF squared x 100, where IF is NP / FTP.

Heart rate TSS (hrTSS) has two methods:

- "trainingpeaks" (the default) works like TrainingPeaks: each second's heart rate becomes an
  intensity factor from its share of threshold heart rate, then TSS = hours x IF squared x 100,
  as for power. TrainingPeaks doesn't publish its curve, so HR_IF_CURVE was fitted to 64 of the
  rider's workouts that TrainingPeaks scored from heart rate (strength, road, mountain bike, ski)
  using Garmin's second by second heart rate: a typical workout lands within 1.3% of
  TrainingPeaks' number and 90% within 7%, and fitting on half the workouts gave the same curve
  for the other half. Its bends sit on the top of zone 1 (80% of LTHR) and zone 2 (89%), and
  easy efforts never score under IF 0.56, which is why a quiet strength hour still scores about 30.
  The time is the device's timer time, as TrainingPeaks uses.

- "trimp" is Banister's TRIMP, the published method intervals.icu and Elevate use, which weights
  each minute by heart rate reserve on an exponential curve:

    TRIMP per minute = HRR x 0.64 x e^(k x HRR),  HRR = (HR - resting) / (max - resting)

  with k = 1.92 for men and 1.67 for women, scaled by the TRIMP of an hour at threshold heart rate.
  Scored second by second, this is intervals.icu's HRSS.

Both score an hour at LTHR as 100, the same as an hour at FTP.

The source of each ride's number is kept (power, hr, mixed, estimate, manual) so the app can say
when a ride was scored from heart rate.
"""
from __future__ import annotations

import numpy as np

# (heart rate / LTHR, intensity factor). Fitted against TrainingPeaks, see the module notes.
HR_IF_CURVE = ((0.50, 0.56), (0.80, 0.65), (0.89, 0.80), (1.00, 1.00), (1.30, 1.30))
HR_METHODS = {"trainingpeaks": "TrainingPeaks style", "trimp": "TRIMP (Banister)"}
DEFAULT_HR_METHOD = "trainingpeaks"

# What "Score like" can be set to. `compare` is the service whose numbers rides are checked
# against; the published standard checks against whichever service is connected.
STANDARDS = {
    "trainingpeaks": {"label": "TrainingPeaks", "hr_method": "trainingpeaks", "time": "timer",
                      "compare": "trainingpeaks",
                      "about": "Heart rate on the curve fitted to TrainingPeaks' hrTSS, on timer time."},
    "intervals": {"label": "intervals.icu", "hr_method": "trimp", "time": "moving",
                  "compare": "intervals",
                  "about": "Heart rate as HRSS (normalized TRIMP), on moving time, as intervals.icu does."},
    "standard": {"label": "Published standard", "hr_method": "trimp", "time": "timer",
                 "compare": None,
                 "about": "Coggan's power TSS and Banister's TRIMP for heart rate, on timer time."},
}
DEFAULT_STANDARD = "trainingpeaks"
SERVICE_NAMES = {"trainingpeaks": "TrainingPeaks", "intervals": "intervals.icu"}

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


def hr_if(hr, lthr: float):
    """Intensity factor for a heart rate (scalar or numpy array), TrainingPeaks style."""
    xs = np.array([x for x, _ in HR_IF_CURVE]); ys = np.array([y for _, y in HR_IF_CURVE])
    ratio = np.asarray(hr, dtype=float) / lthr
    return np.where(ratio > xs[-1], ratio, np.interp(ratio, xs, ys))


def _method(profile: dict | None) -> str:
    return (profile or {}).get("method") or DEFAULT_HR_METHOD


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
    """hrTSS from average heart rate, when there's no second by second data. TrainingPeaks style by
    default; TRIMP when chosen and resting and max heart rate are known, else (HR / LTHR) squared."""
    if not lthr or lthr <= 0 or not avg_hr or avg_hr <= 0:
        return None
    if _method(profile) == "trainingpeaks":
        return (duration_s / 3600) * float(hr_if(avg_hr, lthr)) ** 2 * 100
    if profile_ok(profile, lthr):
        return (duration_s / 3600) * float(_weight(avg_hr, profile) / _weight(lthr, profile)) * 100
    return (duration_s / 3600) * ((avg_hr / lthr) ** 2) * 100


def hr_tss_seconds(hr_values, lthr: float | None, profile: dict | None = None,
                   duration_s: float | None = None) -> float | None:
    """hrTSS from second by second heart rate (one value per second). Scoring each second rather
    than the average counts hard surges properly, since the curve is steep. With `duration_s`
    (the standard's ride time), the average over the recorded seconds is spread over that time,
    as TrainingPeaks does when a strap drops a few seconds, and as intervals.icu's HRSS does
    on moving time."""
    hr = np.asarray([h for h in hr_values if h is not None and h > 0], dtype=float)
    if not len(hr) or not lthr or lthr <= 0:
        return None
    seconds = duration_s if duration_s and duration_s > 0 else len(hr)
    if _method(profile) == "trainingpeaks":
        return float((hr_if(hr, lthr) ** 2).mean()) * 100 * seconds / 3600
    if profile_ok(profile, lthr):
        per_sec = _weight(hr, profile) / _weight(lthr, profile)
    else:
        per_sec = (hr / lthr) ** 2
    return float(per_sec.mean()) * 100 * seconds / 3600


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
                 timer_s: float | None = None, rule: str = "timer") -> float:
    """The seconds TSS is scored against. "timer" (TrainingPeaks and the standard): the device's
    timer time when known, else moving time. "moving" (intervals.icu): moving time, else timer.
    Elapsed time last either way."""
    first, second = (moving_s, timer_s) if rule == "moving" else (timer_s, moving_s)
    return float(first or second or elapsed_s or 0)


def time_rule(profile: dict | None) -> str:
    """The time rule ("timer" or "moving") of an hr_profile()."""
    return (profile or {}).get("time") or "timer"


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
               profile: dict | None = None, duration_s: float | None = None) -> tuple[float, str] | None:
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
        tss = hr_tss_seconds(hr, lthr, profile, duration_s)
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


# ── Comparing with TrainingPeaks or intervals.icu ─────────────────────────────

MISMATCH_TSS = 10        # flag a ride when the app and the service differ by this much
MISMATCH_SHARE = 0.15    # and by this share of the service's number


def ref_numbers(act: dict, service: str | None) -> dict | None:
    """What a service ("trainingpeaks" or "intervals") has for this activity (tss, hours, np,
    avg_hr, scored_by), or None."""
    import json
    raw = act.get("ref_json")
    if not raw or not service:
        return None
    try:
        ref = (json.loads(raw) or {}).get(service)
    except (TypeError, ValueError, AttributeError):
        return None
    return ref if ref and ref.get("tss") is not None else None


def mismatch(act: dict, service: str | None = None) -> dict | None:
    """When the app's TSS and the service's differ a lot: {app, ref, diff, share, reasons,
    service, name}. The service defaults to the one the current "Score like" compares against.
    Reasons are the differences in the inputs that explain it, in words."""
    if not act.get("ref_json"):
        return None
    if service is None:
        import compare
        service = compare.compare_service()
    ref = ref_numbers(act, service)
    app = act.get("tss")
    if not ref or app is None:
        return None
    diff = float(app) - float(ref["tss"])
    share = abs(diff) / max(float(ref["tss"]), 1.0)
    if abs(diff) < MISMATCH_TSS or share < MISMATCH_SHARE:
        return None
    name = SERVICE_NAMES.get(service, service)
    reasons = []
    app_kind = act.get("tss_source") or ""
    ref_kind = ref.get("scored_by") or ""
    if app_kind in ("power", "mixed") and ref_kind == "hr":
        reasons.append(f"{name} scored it from heart rate; the app has power for it.")
    elif app_kind in ("hr", "estimate") and ref_kind == "power":
        reasons.append(f"{name} has power for it; the app only has heart rate.")
    elif ref_kind == "manual":
        reasons.append(f"The number in {name} was typed in by hand.")
    if act.get("tss_locked"):
        reasons.append("You set this ride's TSS by hand in the app.")
    # Compare like with like: intervals.icu reports moving time, TrainingPeaks timer time.
    if service == "intervals":
        hours = (act.get("duration_seconds") or act.get("timer_seconds") or 0) / 3600
    else:
        hours = (act.get("timer_seconds") or act.get("duration_seconds") or 0) / 3600
    if ref.get("hours") and hours and abs(ref["hours"] / hours - 1) > 0.05:
        reasons.append(f"Different ride time: {ref['hours'] * 60:.0f} min in {name}, {hours * 60:.0f} min here.")
    if ref.get("np") and act.get("normalized_power") and abs(ref["np"] / act["normalized_power"] - 1) > 0.03:
        reasons.append(f"Different normalized power: {ref['np']:.0f} W in {name}, "
                       f"{act['normalized_power']:.0f} W here.")
    if ref.get("avg_hr") and act.get("avg_hr") and abs(ref["avg_hr"] - act["avg_hr"]) > 3:
        reasons.append(f"Different average heart rate: {ref['avg_hr']:.0f} bpm in {name}, "
                       f"{act['avg_hr']:.0f} here.")
    if not reasons and ref.get("hours") is None:
        reasons.append(f"{name}'s number comes from its fitness chart for that day (the session isn't in "
                       f"its workout list), so its time and heart rate can't be compared. Check the session "
                       f"in {name}.")
    elif not reasons:
        reasons.append("The inputs match, so the difference is in how the number was worked out, "
                       "for example FTP or threshold heart rate on that date.")
    return {"app": float(app), "ref": float(ref["tss"]), "diff": diff, "share": share,
            "reasons": reasons, "service": service, "name": name}
