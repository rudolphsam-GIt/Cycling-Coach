"""
Best average values over fixed durations (mean maximal power or heart rate)
from second by second ride data, and reading that data out of a FIT file.
"""
from __future__ import annotations

import io
import zipfile

import numpy as np

HR_DURATIONS = (5, 10, 30, 60, 120, 300, 600, 1200, 1800, 3600)
MAX_GAP_S = 5   # gaps up to this long are filled with the last value; longer ones are pauses


def _series(samples: list, max_gap: int, zero_is_missing: bool) -> np.ndarray:
    """One value per second of riding. Gaps up to max_gap are filled with the last
    value. Longer gaps are pauses and are cut out, so the riding before and after
    joins up, the way TrainingPeaks drops paused time. Missing values (and zero
    heart rate, a sensor dropout) are skipped."""
    out, last_t, last_v = [], None, None
    for t, v in sorted((float(t), v) for t, v in samples if t is not None):
        if v is None or (zero_is_missing and v <= 0):
            continue
        if last_t is not None:
            gap = t - last_t
            if gap <= 0:
                continue
            if gap <= max_gap:
                out.extend([last_v] * (int(round(gap)) - 1))
        out.append(float(v))
        last_t, last_v = t, float(v)
    return np.asarray(out, dtype=float)


def mean_max(samples: list, durations=HR_DURATIONS, *, max_gap: int = MAX_GAP_S,
             zero_is_missing: bool = False) -> dict[int, float]:
    """Best average value for each duration in seconds. Durations longer than the
    riding time are left out."""
    run = _series(samples, max_gap, zero_is_missing)
    best: dict[int, float] = {}
    if len(run):
        csum = np.concatenate(([0.0], np.cumsum(run)))
        for d in durations:
            if d <= len(run):
                best[d] = float(np.max(csum[d:] - csum[:-d]) / d)
    return {d: round(v, 1) for d, v in sorted(best.items())}


def fit_from_download(raw: bytes) -> bytes:
    """Garmin's original download is a zip holding one .fit file; plain .fit passes through."""
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".fit"))
            return z.read(name)
    return raw


def fit_streams(fit_bytes: bytes) -> tuple[list, list]:
    """(heart rate samples, power samples) as (seconds from start, value) lists."""
    from fitparse import FitFile

    hr, power, start = [], [], None
    for msg in FitFile(io.BytesIO(fit_bytes)).get_messages("record"):
        values = msg.get_values()
        ts = values.get("timestamp")
        if ts is None:
            continue
        start = start or ts
        t = (ts - start).total_seconds()
        hr.append((t, values.get("heart_rate")))
        power.append((t, values.get("power")))
    return hr, power


def hr_peaks_from_fit(fit_bytes: bytes) -> dict[int, float]:
    hr, _ = fit_streams(fit_bytes)
    return mean_max(hr, HR_DURATIONS, zero_is_missing=True)
