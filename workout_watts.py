"""
Watt figures in a workout's words are kept as a percent of FTP, so they follow every FTP change.

A planned workout's steps are already stored as % of FTP. Its description, purpose and feel are
free text from the coach or the rider, so "60 min at 230 to 255W" would go stale the day FTP
changes. On the way into the database each watt figure becomes a token such as {66.7%FTP}, worked
out on the FTP in effect on the workout's date, and on the way out every token is turned back into
watts on the FTP for that date. Upcoming workouts then always read in today's watts, and past ones
read the way they were ridden.

Only plain watt figures are converted ("265 W", "250-270 W", "250 to 270 watts"), never W/kg.
Text with no FTP to work from is left as it is.
"""
from __future__ import annotations

import re

FIELDS = ("description", "purpose", "feel")

# "265 W", "250-270 W", "250 to 270 watts", but not "3.5 W/kg" (same as the old rescale)
_WATTS = re.compile(r"\b(\d{2,4})(?:(\s*(?:-|–|to)\s*)(\d{2,4}))?(\s?)(W|watts)\b(?!/)")
_TOKEN = re.compile(r"\{(\d+(?:\.\d+)?)%FTP\}")


def _round5(watts: float) -> int:
    return int(5 * round(watts / 5))


def _pct(watts: str, ftp: float) -> str:
    return "{" + f"{round(int(watts) / ftp * 100, 1):g}" + "%FTP}"


def to_pct(text: str | None, ftp: float) -> str | None:
    """Every watt figure in the text as a token in percent of `ftp`. Tokens already there stay."""
    if not text or not ftp or ftp <= 0:
        return text

    def swap(m: re.Match) -> str:
        high = (m.group(2) + _pct(m.group(3), ftp)) if m.group(3) else ""
        return f"{_pct(m.group(1), ftp)}{high}{m.group(4)}{m.group(5)}"

    return _WATTS.sub(swap, text)


def to_watts(text: str | None, ftp: float) -> str | None:
    """Every token in the text as watts on `ftp`, rounded to 5 W."""
    if not text or "%FTP}" not in text:
        return text
    if not ftp or ftp <= 0:
        return _TOKEN.sub(lambda m: f"{float(m.group(1)):g}% of FTP ", text)
    return _TOKEN.sub(lambda m: str(_round5(float(m.group(1)) / 100 * ftp)), text)


def has_tokens(text: str | None) -> bool:
    return bool(text) and _TOKEN.search(text) is not None


def store(row: dict, ftp: float, stored: dict | None = None) -> dict:
    """The row with its words ready to save. A field that still reads exactly as the stored copy
    renders keeps the stored tokens, so opening and saving a workout never drifts its numbers by
    the 5 W rounding."""
    out = dict(row)
    for f in FIELDS:
        text = out.get(f)
        if stored is not None and text is not None and text == to_watts(stored.get(f), ftp):
            out[f] = stored.get(f)
        else:
            out[f] = to_pct(text, ftp)
    return out


def show(row: dict, ftp: float) -> dict:
    """The row with its words in watts on `ftp`."""
    out = dict(row)
    for f in FIELDS:
        if f in out:
            out[f] = to_watts(out[f], ftp)
    return out


def changed_lines(text: str | None, old_ftp: float, new_ftp: float, limit: int = 2) -> list[tuple[str, str]]:
    """Up to `limit` sentences of stored text whose watts differ between two FTPs, as
    (before, after), for showing what an FTP change does to a workout."""
    out = []
    for part in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        if not has_tokens(part):
            continue
        before, after = to_watts(part, old_ftp).strip(), to_watts(part, new_ftp).strip()
        if before != after:
            out.append((before, after))
            if len(out) >= limit:
                break
    return out
