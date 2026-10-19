"""
A record of every Claude call: which feature made it, the tokens it used and what that cost.

Rows always go to the owner's database, whichever athlete is open, since every call is billed to
the one API key. The athlete column says whose profile the call was made from. Costs are estimates
from the per token prices in claude_client.PRICES, at the time of the call.
"""
from __future__ import annotations

import os
from datetime import date, datetime

from db import schema

TABLE = """
CREATE TABLE IF NOT EXISTS claude_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    feature TEXT NOT NULL,
    model TEXT NOT NULL,
    athlete TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_5m_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_1h_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL
);
CREATE INDEX IF NOT EXISTS idx_claude_usage_created ON claude_usage(created_at);
"""

# How each feature is named on the Settings page.
FEATURE_LABELS = {
    "chat": "Coach chat",
    "program": "Program planning chat",
    "weekly": "Weekly check in",
    "ride_review": "Ride review",
    "race_plan": "Race day plan",
    "tactics": "Tactics brief",
    "workout_steps": "Workout steps for Garmin, Zwift and TrainingPeaks",
    "other": "Other",
}


def _athlete() -> str:
    path = schema.current_path()
    if os.path.abspath(path) == os.path.abspath(schema.DB_PATH):
        return "owner"
    return os.path.splitext(os.path.basename(path))[0]


def record(feature: str, model: str, *, input_tokens: int = 0, cache_read: int = 0, cache_write_5m: int = 0,
           cache_write_1h: int = 0, output_tokens: int = 0, cost_usd: float | None = None) -> None:
    """Save one call. Never raises, so a logging problem can't break a reply."""
    try:
        athlete = _athlete()
        with schema.use(schema.DB_PATH):
            conn = schema.get_conn()
            try:
                conn.executescript(TABLE)
                conn.execute(
                    "INSERT INTO claude_usage (created_at, feature, model, athlete, input_tokens, cache_read_tokens, "
                    "cache_write_5m_tokens, cache_write_1h_tokens, output_tokens, cost_usd) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (datetime.utcnow().isoformat(), feature, model, athlete, input_tokens, cache_read,
                     cache_write_5m, cache_write_1h, output_tokens, cost_usd))
                conn.commit()
            finally:
                conn.close()
    except Exception:
        pass


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """The local calendar month as UTC times, to compare with created_at."""
    from datetime import timezone
    local = datetime.now().astimezone().tzinfo
    first = datetime(year, month, 1, tzinfo=local)
    after = datetime(year + month // 12, month % 12 + 1, 1, tzinfo=local)
    to_utc = lambda d: d.astimezone(timezone.utc).replace(tzinfo=None)
    return to_utc(first), to_utc(after)


def summary(start: date | datetime, end: date | datetime) -> list[dict]:
    """Totals per feature for calls from start up to (not including) end, most expensive first.
    Datetimes are UTC, like created_at."""
    with schema.use(schema.DB_PATH):
        conn = schema.get_conn()
        try:
            conn.executescript(TABLE)
            rows = conn.execute(
                "SELECT feature, COUNT(*) AS calls, SUM(input_tokens) AS input_tokens, "
                "SUM(cache_read_tokens) AS cache_read_tokens, "
                "SUM(cache_write_5m_tokens + cache_write_1h_tokens) AS cache_write_tokens, "
                "SUM(output_tokens) AS output_tokens, SUM(cost_usd) AS cost_usd "
                "FROM claude_usage WHERE created_at >= ? AND created_at < ? "
                "GROUP BY feature ORDER BY SUM(cost_usd) DESC",
                (start.isoformat(), end.isoformat())).fetchall()
        finally:
            conn.close()
    return [dict(r) for r in rows]
