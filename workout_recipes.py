"""
Fixed recipes for the standard workout types, sized to a planned TSS.

A planned workout with no written detail (an empty description, or one Quick Generate wrote)
gets its steps from here instead of from Claude, so the steps always add up to the TSS the plan
counted. Targets are percent of FTP, in the same step format garmin_workouts uses. Race and
Other have no recipe and still go to Claude, as does any workout with its own description.

Each recipe is a warm up, a repeated work and rest set, steady riding to make up the rest of
the load, and a cool down. The number of repeats is the most that fits the TSS (within the
recipe's limits), then the steady part fills the gap.
"""
from __future__ import annotations

AUTO_MARK = "Auto-generated"         # Quick Generate's descriptions start a line with this
TOLERANCE = 0.10                     # steps land within 10% of the planned TSS

WARMUP = {"kind": "warmup", "minutes": 10, "low_pct": 50, "high_pct": 65}
COOLDOWN = {"kind": "cooldown", "minutes": 10, "low_pct": 45, "high_pct": 60}

# work and rest are (minutes, low %, high %). steady is the zone that fills the rest of the load.
RECIPES = {
    "Recovery": {"steady": (50, 60), "warm": False},
    "Endurance": {"steady": (65, 75)},
    "Long Ride": {"steady": (62, 72)},
    "Tempo": {"work": (15, 80, 87), "rest": (5, 55, 65), "reps": (2, 4), "steady": (65, 75)},
    "Threshold": {"work": (10, 95, 100), "rest": (5, 50, 60), "reps": (2, 5), "steady": (65, 75)},
    "VO2 Max": {"work": (4, 110, 120), "rest": (4, 50, 60), "reps": (3, 6), "steady": (65, 75)},
    "Sprint/Anaerobic": {"work": (0.5, 150, 170), "rest": (4.5, 50, 60), "reps": (4, 10), "steady": (65, 75)},
}
MAX_STEADY_MIN = 480


def has_recipe(workout_type: str | None) -> bool:
    return workout_type in RECIPES


def uses_recipe(workout: dict) -> bool:
    """True when this workout's steps should come from a recipe: a standard type with no
    written detail of its own."""
    if not has_recipe(workout.get("workout_type")):
        return False
    desc = (workout.get("description") or "").strip()
    return not desc or any(line.strip().startswith(AUTO_MARK) for line in desc.splitlines())


def _leaves(steps: list):
    for s in steps:
        if s["kind"] == "repeat":
            for _ in range(s["repeat_count"]):
                yield from s["repeat_steps"]
        else:
            yield s


def steps_tss(steps: list) -> float:
    """TSS of a set of steps, each ridden at the middle of its range: hours x IF squared x 100,
    with IF from the fourth power average, as normalized power is."""
    secs = sum4 = 0.0
    for s in _leaves(steps):
        t = s["minutes"] * 60
        if s.get("low_pct") is None:
            continue
        secs += t
        sum4 += t * ((s["low_pct"] + s["high_pct"]) / 200) ** 4
    if not secs:
        return 0.0
    intensity = (sum4 / secs) ** 0.25
    return secs / 3600 * intensity ** 2 * 100


def _step(kind: str, minutes: float, lo: float, hi: float) -> dict:
    return {"kind": kind, "minutes": round(minutes, 2), "low_pct": lo, "high_pct": hi}


def _assemble(r: dict, reps: int, steady_min: float) -> list:
    steps = [dict(WARMUP)] if r.get("warm", True) else []
    if reps:
        (wm, wl, wh), (rm, rl, rh) = r["work"], r["rest"]
        steps.append({"kind": "repeat", "repeat_count": reps, "minutes": None, "low_pct": None,
                      "high_pct": None, "repeat_steps": [_step("interval", wm, wl, wh),
                                                         _step("recovery", rm, rl, rh)]})
    if steady_min >= 1:
        steps.append(_step("interval", steady_min, *r["steady"]))
    if r.get("warm", True):
        steps.append(dict(COOLDOWN))
    return steps


class RecipeError(ValueError):
    """The recipe can't make this workout within TOLERANCE of its TSS (for example a threshold
    session planned at 15 TSS)."""


def build(workout_type: str, tss: float) -> list:
    """Steps for a standard workout that add up to `tss`, within TOLERANCE. Raises KeyError for
    a type without a recipe and RecipeError when the TSS is out of the recipe's reach."""
    steps = _fit(workout_type, tss)
    got = steps_tss(steps)
    if not tss or abs(got / float(tss) - 1) > TOLERANCE:
        raise RecipeError(f"a {workout_type} recipe can't be sized to {float(tss or 0):.0f} TSS")
    return steps


def _fit(workout_type: str, tss: float) -> list:
    r = RECIPES[workout_type]
    tss = max(float(tss or 0), 10.0)
    reps = 0
    if "work" in r:
        lo_reps, hi_reps = r["reps"]
        fitting = [n for n in range(1, hi_reps + 1) if steps_tss(_assemble(r, n, 0)) <= tss]
        reps = max(fitting) if fitting else 1
        reps = max(reps, min(lo_reps, max(fitting, default=1)))
    lo, hi = 0.0, float(MAX_STEADY_MIN)
    if steps_tss(_assemble(r, reps, 0)) >= tss:
        return _assemble(r, reps, 0)
    for _ in range(40):
        mid = (lo + hi) / 2
        if steps_tss(_assemble(r, reps, mid)) < tss:
            lo = mid
        else:
            hi = mid
    return _assemble(r, reps, round(hi))


def _fmt_min(m: float) -> str:
    return f"{int(m * 60)} s" if m < 1 else f"{m:g} min"


def describe(steps: list) -> str:
    """The steps in one plain line, for the workout's description."""
    parts = []
    for s in steps:
        if s["kind"] == "repeat":
            work, rest = s["repeat_steps"]
            parts.append(f"{s['repeat_count']} x {_fmt_min(work['minutes'])} at {work['low_pct']:g} to "
                         f"{work['high_pct']:g}% FTP with {_fmt_min(rest['minutes'])} easy")
        elif s["kind"] == "warmup":
            parts.append(f"{_fmt_min(s['minutes'])} warm up")
        elif s["kind"] == "cooldown":
            parts.append(f"{_fmt_min(s['minutes'])} cool down")
        else:
            parts.append(f"{_fmt_min(s['minutes'])} steady at {s['low_pct']:g} to {s['high_pct']:g}% FTP")
    return ", ".join(parts)
