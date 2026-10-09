"""Training Stress Score for a ride, in one place so every source agrees.

Duration is the device's timer time when the source gives it (Garmin, FIT files), the same time
Garmin and TrainingPeaks score against, else moving time (Strava). Elapsed time is only a
fallback, since it counts coffee stops. The timer time is stored, so recalculating a ride gives
back the TSS it was synced with.
"""


def power_tss(duration_s: float, norm_power: float | None, ftp: float | None) -> float | None:
    if not ftp or ftp <= 0 or not norm_power or norm_power <= 0:
        return None
    return (duration_s / 3600) * ((norm_power / ftp) ** 2) * 100


def hr_tss(duration_s: float, avg_hr: float | None, lthr: float | None) -> float | None:
    if not lthr or lthr <= 0 or not avg_hr or avg_hr <= 0:
        return None
    return (duration_s / 3600) * ((avg_hr / lthr) ** 2) * 100


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
             perceived_exertion: float | None = None) -> tuple[float | None, float | None]:
    """(tss, intensity factor) for a ride: from power, else heart rate, else an estimate."""
    if not duration_s or duration_s <= 0:
        return None, None
    tss = power_tss(duration_s, norm_power, ftp)
    if tss is None:
        tss = hr_tss(duration_s, avg_hr, lthr)
    if tss is None:
        tss = estimated_tss(duration_s, perceived_exertion, avg_hr, max_hr)
    if_value = (norm_power / ftp) if (norm_power and ftp) else None
    return tss, if_value
