"""
Second by second ride data, and what can be worked out from it for a ride analysis.

A ride's streams are stored as one dict of equal length lists at one sample per
second: {"power", "hr", "cad", "speed", "alt", "dist"}. A channel the ride doesn't
have is left out, and a missing moment inside a channel is None.

Everything here is pure, so it is tested without a database or a file.
"""
from __future__ import annotations

import io
import math
from typing import Iterable

import numpy as np

from metrics.peaks import fit_from_download, mean_max
from metrics.zones import HR_ZONE_PCT, POWER_ZONE_PCT
from metrics.units import num as _num

CHANNELS = ("power", "hr", "cad", "speed", "alt", "dist")
FILL_GAP_S = 10            # a gap this short repeats the last value, longer stays empty
MAX_SECONDS = 24 * 3600
ROUND = {"power": 0, "hr": 0, "cad": 0, "speed": 2, "alt": 1, "dist": 1}


def from_records(records: Iterable[dict]) -> dict | None:
    """Build streams from records that each carry `t` (seconds from the start) and any
    of the channels. Resamples to one per second. None if there is nothing usable."""
    pts = [(t, r) for r in records if (t := _num(r.get("t"))) is not None and t >= 0]
    if not pts:
        return None
    pts.sort(key=lambda p: p[0])
    n = min(int(pts[-1][0]) + 1, MAX_SECONDS)
    out = {}
    for ch in CHANNELS:
        arr = np.full(n, np.nan)
        for t, r in pts:
            i = int(t)
            v = _num(r.get(ch))
            if i < n and v is not None:
                arr[i] = v
        if np.isnan(arr).all():
            continue
        _fill_short_gaps(arr)
        out[ch] = [None if np.isnan(x) else round(float(x), ROUND[ch]) if ROUND[ch] else int(round(x))
                   for x in arr]
    return out or None


def _fill_short_gaps(arr: np.ndarray) -> None:
    """Repeat the last value across a gap of up to FILL_GAP_S seconds, in place. A longer
    gap, like a stop with the head unit paused, is left empty."""
    n, i = len(arr), 0
    while i < n:
        if not np.isnan(arr[i]):
            i += 1
            continue
        j = i
        while j < n and np.isnan(arr[j]):
            j += 1
        if i > 0 and j < n and j - i <= FILL_GAP_S:
            arr[i:j] = arr[i - 1]
        i = j


def fit_records(fit_bytes: bytes) -> list[dict]:
    """The per second records of a .fit file (or the zip Garmin sends), as dicts for from_records."""
    from fitparse import FitFile

    data = fit_from_download(fit_bytes)
    start, records = None, []
    for msg in FitFile(io.BytesIO(data)).get_messages("record"):
        v = msg.get_values()
        ts = v.get("timestamp")
        if ts is None:
            continue
        start = start or ts
        records.append({
            "t": (ts - start).total_seconds(), "power": v.get("power"), "hr": v.get("heart_rate"),
            "cad": v.get("cadence"), "speed": v.get("enhanced_speed", v.get("speed")),
            "alt": v.get("enhanced_altitude", v.get("altitude")), "dist": v.get("distance")})
    return records


def from_fit(fit_bytes: bytes) -> dict | None:
    return from_records(fit_records(fit_bytes))


def from_strava(streams: dict) -> dict | None:
    """Streams from Strava's streams API, requested with key_by_type=true."""
    def data(name):
        s = streams.get(name) if isinstance(streams, dict) else None
        return s.get("data") if isinstance(s, dict) else None

    t = data("time")
    if not t:
        return None
    channels = {"power": data("watts"), "hr": data("heartrate"), "cad": data("cadence"),
                "speed": data("velocity_smooth"), "alt": data("altitude"), "dist": data("distance")}
    records = []
    for i, sec in enumerate(t):
        rec = {"t": sec}
        for ch, arr in channels.items():
            if arr and i < len(arr):
                rec[ch] = arr[i]
        records.append(rec)
    return from_records(records)


# ── Derived series ────────────────────────────────────────────────────────────

def _arr(values) -> np.ndarray:
    return np.array([np.nan if v is None else v for v in values], dtype=float)


def smooth(values: list, window: int) -> list:
    """A rolling average over `window` seconds, centred, that ignores missing values and
    keeps gaps as gaps. Works for any length, including a stretch shorter than the window.
    A window of 1 returns the values unchanged."""
    if window <= 1 or not values:
        return list(values)
    a = _arr(values)
    n = len(a)
    ok = ~np.isnan(a)
    sums = np.concatenate(([0.0], np.cumsum(np.where(ok, a, 0.0))))
    counts = np.concatenate(([0.0], np.cumsum(ok.astype(float))))
    idx = np.arange(n)
    lo = np.clip(idx - window // 2, 0, n)
    hi = np.clip(idx - window // 2 + window, 0, n)
    num, den = sums[hi] - sums[lo], counts[hi] - counts[lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        res = num / den
    res[~ok] = np.nan
    return [None if math.isnan(x) else float(x) for x in res]


def downsample(values: list, max_points: int = 1200) -> tuple[list[int], list]:
    """(seconds, values) reduced to at most max_points by averaging buckets."""
    n = len(values)
    if n <= max_points:
        return list(range(n)), list(values)
    step = math.ceil(n / max_points)
    xs, ys = [], []
    for start in range(0, n, step):
        chunk = [v for v in values[start:start + step] if v is not None]
        xs.append(start + step // 2)
        ys.append(sum(chunk) / len(chunk) if chunk else None)
    return xs, ys


def zone_seconds(values: list, reference: float, bounds_pct: list) -> list[float]:
    """Seconds in each zone. `bounds_pct` is metrics.zones.POWER_ZONE_PCT or HR_ZONE_PCT,
    the lower edge of each zone as a percentage of `reference` (FTP or LTHR)."""
    zones = len(bounds_pct) - 1
    secs = [0.0] * zones
    if not reference:
        return secs
    edges = [b * reference / 100 for b in bounds_pct]
    for v in values:
        if v is None:
            continue
        for z in range(zones - 1, -1, -1):
            if v >= edges[z]:
                secs[z] += 1
                break
    return secs


def power_zone_seconds(power: list, ftp: float) -> list[float]:
    return zone_seconds(power, ftp, POWER_ZONE_PCT)


def hr_zone_seconds(hr: list, lthr: float) -> list[float]:
    return zone_seconds(hr, lthr, HR_ZONE_PCT)


def normalized_power(power: list) -> float | None:
    """NP: 30 second rolling average, to the fourth power, averaged, fourth root."""
    vals = [p for p in power if p is not None]
    if len(vals) < 30:
        return None
    a = np.array(vals, dtype=float)
    roll = np.convolve(a, np.ones(30) / 30, mode="valid")
    return float(np.mean(roll ** 4) ** 0.25)


def average(values: list) -> float | None:
    v = [x for x in values if x is not None]
    return sum(v) / len(v) if v else None


def decoupling(power: list, hr: list) -> float | None:
    """Aerobic decoupling in percent. The ratio of power to heart rate in the first half
    of the ride against the second half. A rise of a few percent is normal on a long steady
    ride, much more means fatigue, heat or dehydration. None for rides under 40 minutes or
    without both channels."""
    n = min(len(power), len(hr))
    if n < 40 * 60:
        return None
    half = n // 2
    def ef(p, h):
        ap, ah = average(p), average(h)
        return ap / ah if ap and ah else None
    first, second = ef(power[:half], hr[:half]), ef(power[half:n], hr[half:n])
    if not first or not second:
        return None
    return (first - second) / first * 100


def ride_peaks(power: list, durations) -> dict[int, float]:
    """This ride's best average power for each duration in seconds."""
    return mean_max([(i, v) for i, v in enumerate(power) if v is not None], durations)


def find_efforts(power: list, ftp: float, hr: list | None = None, *, min_pct: float = 0.9,
                 min_seconds: int = 240) -> list[dict]:
    """Hard stretches: where 30 second smoothed power stays at or above min_pct of FTP for at
    least min_seconds. A short dip (about 15 seconds of real easing, which the smoothing stretches
    to roughly 45) doesn't end an effort."""
    if not ftp or len(power) < min_seconds:
        return []
    sm = smooth(power, 30)
    limit = ftp * min_pct
    efforts, start, below = [], None, 0
    for i, v in enumerate(sm + [None]):
        hard = v is not None and v >= limit
        if hard:
            start = i if start is None else start
            below = 0
        elif start is not None:
            below += 1
            if below > 45 or i == len(sm):
                end = i - below + 1
                if end - start >= min_seconds:
                    seg = power[start:end]
                    efforts.append({
                        "start": start, "seconds": end - start, "avg_power": average(seg),
                        "avg_hr": average(hr[start:end]) if hr else None})
                start, below = None, 0
    return efforts


def elapsed_label(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


# ── A highlighted part of the ride ────────────────────────────────────────────

def slice_streams(streams: dict, start: float, end: float) -> dict:
    """The part of the ride between two times in seconds, for every channel."""
    n = max((len(v) for v in streams.values()), default=0)
    a, b = max(int(start), 0), min(int(math.ceil(end)), n)
    return {k: v[a:b] for k, v in streams.items()}


def elevation_gain(alt: list, window: int = 5, noise: float = 0.5) -> float | None:
    """Total climbing in meters from an altitude stream. The altitude is smoothed first, and
    each step up has to clear a small noise threshold so a wobbling sensor doesn't add up."""
    vals = [v for v in smooth(alt, window) if v is not None]
    if len(vals) < 2:
        return None
    gain, ref = 0.0, vals[0]
    for v in vals[1:]:
        if v - ref >= noise:
            gain += v - ref
            ref = v
        elif v < ref:
            ref = v
    return gain


def distance_meters(streams: dict) -> float | None:
    """Distance covered, from the distance channel, or by adding up speed."""
    dist = [d for d in streams.get("dist") or [] if d is not None]
    if len(dist) >= 2 and dist[-1] >= dist[0]:
        return dist[-1] - dist[0]
    speed = [v for v in streams.get("speed") or [] if v is not None]
    return float(sum(speed)) if speed else None


def numbers_from_streams(streams: dict, ftp: float = 0.0, lthr: float = 0.0,
                         profile: dict | None = None) -> dict:
    """The ride numbers worked out from second by second data alone, for the whole ride
    or any part of it. Anything the data can't give is None. TSS comes from power, or from
    heart rate (hrTSS) where power is missing when `lthr` is given."""
    from metrics.tss import stream_tss
    power = streams.get("power") or []
    hr = streams.get("hr") or []
    speed = [v for v in streams.get("speed") or [] if v is not None]
    cad = [v for v in streams.get("cad") or [] if v]
    n = max((len(v) for v in streams.values()), default=0)
    avg_w = average(power)
    np_w = normalized_power(power)
    avg_hr = average(hr)
    iff = np_w / ftp if np_w and ftp else None
    tss, tss_source = (n * iff * iff / 36, "power") if iff else (None, None)   # seconds x IF² / 3600 x 100
    if lthr and (by_hr := stream_tss(streams, ftp, lthr, profile)):
        tss, tss_source = by_hr
    return {
        "secs": n or None,
        "meters": distance_meters(streams),
        "climb": elevation_gain(streams["alt"]) if streams.get("alt") else None,
        "avg_w": avg_w, "np": np_w, "if": iff,
        "tss": tss, "tss_source": tss_source,
        "vi": np_w / avg_w if np_w and avg_w else None,
        "avg_hr": avg_hr, "max_hr": max([h for h in hr if h is not None], default=None),
        "kj": avg_w * n / 1000 if avg_w and n else None,
        "ef": np_w / avg_hr if np_w and avg_hr else None,
        "max_w": max([p for p in power if p is not None], default=None) if power else None,
        "avg_speed": sum(speed) / len(speed) if speed else None,     # meters per second
        "max_speed": max(speed) if speed else None,
        "avg_cad": sum(cad) / len(cad) if cad else None,
        "decoupling": decoupling(power, hr) if power and hr else None,
    }


# ── Distance along the ride ───────────────────────────────────────────────────

NICE_STEPS = (0.1, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 500)


def cumulative_distance(streams: dict) -> list[float] | None:
    """Meters covered at each second. From the distance channel when there is one (gaps carry
    the last value, and the line never goes backwards), otherwise by adding up speed."""
    dist = streams.get("dist")
    if dist and any(v is not None for v in dist):
        out, last = [], 0.0
        for v in dist:
            last = max(last, v) if v is not None else last
            out.append(last)
        return out
    speed = streams.get("speed")
    if speed and any(v for v in speed):
        out, total = [], 0.0
        for v in speed:
            total += v or 0.0
            out.append(total)
        return out
    return None


def nice_step(raw: float) -> float:
    """The smallest round step (1, 2, 5, 10 and so on) that is at least `raw`."""
    for step in NICE_STEPS:
        if step >= raw:
            return step
    return NICE_STEPS[-1]


def distance_ticks(cumulative_m: list[float], start: int, end: int, meters_per_unit: float,
                   count: int = 8) -> list[tuple[float, int]]:
    """Round distances (in miles or km) inside the window from `start` to `end` seconds,
    each with the second it was reached, for labelling the timeline by distance."""
    if not cumulative_m or end - start < 2:
        return []
    window = cumulative_m[start:end]
    lo, hi = window[0] / meters_per_unit, window[-1] / meters_per_unit
    if hi - lo <= 0:
        return []
    step = nice_step((hi - lo) / count)
    arr = np.asarray(window, dtype=float)
    ticks, v = [], math.ceil(lo / step - 1e-9) * step
    while v <= hi + 1e-9:
        i = int(np.searchsorted(arr, v * meters_per_unit, side="left"))
        if i < len(arr):
            ticks.append((round(v, 6), start + i))
        v += step
    return ticks
