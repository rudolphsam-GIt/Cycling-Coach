from __future__ import annotations
import sqlite3
import json
from datetime import datetime, date, timedelta
from db.schema import get_conn


# ── Athlete Settings ──────────────────────────────────────────────────────────

def get_setting(key: str, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM athlete_settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO athlete_settings (key, value, updated_at) VALUES (?,?,?)",
        (key, str(value), datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_all_settings() -> dict:
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM athlete_settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


# ── Activities ────────────────────────────────────────────────────────────────

def _activity_score(row: dict) -> int:
    """Higher = more data. Used to decide which duplicate to keep."""
    score = 0
    if row.get("normalized_power"): score += 4
    if row.get("avg_power_watts"):  score += 3
    if row.get("tss"):              score += 2
    if row.get("avg_hr"):           score += 1
    if row.get("zone_time_json"):   score += 1
    return score


def _find_cross_source_duplicate(conn, data: dict):
    """
    Return an existing activity row from a different source that matches
    on date + duration within 5 min + distance within 10% (or 500 m).
    Returns None if no duplicate found.
    """
    duration = data.get("elapsed_seconds") or data.get("duration_seconds") or 0
    if not duration:
        return None

    rows = conn.execute(
        """SELECT * FROM activities
           WHERE date = ? AND source != ?
             AND ABS(COALESCE(elapsed_seconds, duration_seconds, 0) - ?) <= 300""",
        (data["date"], data["source"], duration),
    ).fetchall()

    dist_new = data.get("distance_meters") or 0
    for row in rows:
        dist_old = row["distance_meters"] or 0
        if dist_new and dist_old:
            pct = abs(dist_new - dist_old) / max(dist_old, 1)
            if pct > 0.10 and abs(dist_new - dist_old) > 500:
                continue
        return row
    return None


def upsert_activity(data: dict):
    conn = get_conn()
    data.setdefault("elapsed_seconds", None)
    data.setdefault("zone_time_json", None)

    dup = _find_cross_source_duplicate(conn, data)
    if dup:
        dup = dict(dup)
        # Keep whichever record has more data; merge missing fields from the other
        incoming_score = _activity_score(data)
        existing_score = _activity_score(dup)
        if incoming_score > existing_score:
            # Incoming is richer — update the existing row in place, keep its external_id
            conn.execute(
                """UPDATE activities SET
                   avg_power_watts  = COALESCE(?, avg_power_watts),
                   normalized_power = COALESCE(?, normalized_power),
                   tss              = COALESCE(?, tss),
                   if_value         = COALESCE(?, if_value),
                   avg_hr           = COALESCE(?, avg_hr),
                   max_hr           = COALESCE(?, max_hr),
                   zone_time_json   = COALESCE(?, zone_time_json)
                   WHERE id = ?""",
                (
                    data.get("avg_power_watts"), data.get("normalized_power"),
                    data.get("tss"), data.get("if_value"),
                    data.get("avg_hr"), data.get("max_hr"),
                    data.get("zone_time_json"), dup["id"],
                ),
            )
            conn.commit()
        # Either way, don't insert a second row
        conn.close()
        return

    conn.execute(
        """INSERT INTO activities
           (source, external_id, date, name, sport_type, duration_seconds,
            elapsed_seconds, distance_meters, elevation_gain_meters, avg_power_watts, avg_hr,
            max_hr, normalized_power, tss, if_value, raw_json, zone_time_json)
           VALUES (:source,:external_id,:date,:name,:sport_type,:duration_seconds,
                   :elapsed_seconds,:distance_meters,:elevation_gain_meters,:avg_power_watts,:avg_hr,
                   :max_hr,:normalized_power,:tss,:if_value,:raw_json,:zone_time_json)
           ON CONFLICT(external_id) DO UPDATE SET
               tss=excluded.tss, if_value=excluded.if_value,
               normalized_power=excluded.normalized_power,
               avg_power_watts=excluded.avg_power_watts,
               elapsed_seconds=excluded.elapsed_seconds,
               avg_hr=excluded.avg_hr, max_hr=excluded.max_hr,
               zone_time_json=COALESCE(excluded.zone_time_json, zone_time_json)""",
        data,
    )
    conn.commit()
    conn.close()


def deduplicate_activities() -> int:
    """
    Find and remove cross-source duplicates already in the DB.
    Keeps the higher-scoring row, deletes the other.
    Returns number of rows deleted.
    """
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM activities ORDER BY date, elapsed_seconds"""
    ).fetchall()
    rows = [dict(r) for r in rows]

    to_delete = set()
    for i, a in enumerate(rows):
        if a["id"] in to_delete:
            continue
        dur_a = a.get("elapsed_seconds") or a.get("duration_seconds") or 0
        for b in rows[i + 1:]:
            if b["id"] in to_delete:
                continue
            if b["date"] != a["date"]:
                break
            if b["source"] == a["source"]:
                continue
            dur_b = b.get("elapsed_seconds") or b.get("duration_seconds") or 0
            if abs(dur_a - dur_b) > 300:
                continue
            dist_a = a.get("distance_meters") or 0
            dist_b = b.get("distance_meters") or 0
            if dist_a and dist_b:
                pct = abs(dist_a - dist_b) / max(dist_a, 1)
                if pct > 0.10 and abs(dist_a - dist_b) > 500:
                    continue
            # Duplicate found — delete the lower-scoring one
            keep, drop = (a, b) if _activity_score(a) >= _activity_score(b) else (b, a)
            to_delete.add(drop["id"])

    if to_delete:
        conn.execute(
            f"DELETE FROM activities WHERE id IN ({','.join('?' * len(to_delete))})",
            list(to_delete),
        )
        conn.commit()
    conn.close()
    return len(to_delete)


def get_activities(days_back: int = 90) -> list:
    since = (date.today() - timedelta(days=days_back)).isoformat()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM activities WHERE date >= ? ORDER BY date DESC", (since,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_daily_tss(start: str, end: str) -> dict:
    """Return {date_str: total_tss} for the given date range."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT date, SUM(COALESCE(tss,0)) as total_tss
           FROM activities
           WHERE date BETWEEN ? AND ?
             AND sport_type IN ('Ride','VirtualRide','GravelRide','MountainBikeRide','Cycling')
           GROUP BY date""",
        (start, end),
    ).fetchall()
    conn.close()
    return {r["date"]: r["total_tss"] for r in rows}


# ── Workouts ──────────────────────────────────────────────────────────────────

def add_workout(data: dict) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO workouts (date, name, workout_type, description,
           structured_json, tss_planned, notes)
           VALUES (:date,:name,:workout_type,:description,:structured_json,:tss_planned,:notes)""",
        data,
    )
    conn.commit()
    wid = cur.lastrowid
    conn.close()
    return wid


def get_workouts(start: str, end: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM workouts WHERE date BETWEEN ? AND ? ORDER BY date",
        (start, end),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_workout(wid: int, data: dict):
    conn = get_conn()
    conn.execute(
        """UPDATE workouts SET name=:name, workout_type=:workout_type,
           description=:description, tss_planned=:tss_planned,
           completed=:completed, notes=:notes WHERE id=:id""",
        {**data, "id": wid},
    )
    conn.commit()
    conn.close()


def delete_workout(wid: int):
    conn = get_conn()
    conn.execute("DELETE FROM workouts WHERE id=?", (wid,))
    conn.commit()
    conn.close()


# ── Races ─────────────────────────────────────────────────────────────────────

def add_race(data: dict) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO races (name, date, distance_km, elevation_gain_meters,
           category, target_time_seconds, notes)
           VALUES (:name,:date,:distance_km,:elevation_gain_meters,
                   :category,:target_time_seconds,:notes)""",
        data,
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def get_races(upcoming_only: bool = False) -> list:
    conn = get_conn()
    if upcoming_only:
        rows = conn.execute(
            "SELECT * FROM races WHERE date >= ? ORDER BY date",
            (date.today().isoformat(),),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM races ORDER BY date DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_race(rid: int):
    conn = get_conn()
    conn.execute("DELETE FROM races WHERE id=?", (rid,))
    conn.commit()
    conn.close()


_CYCLING_SPORT_TYPES = (
    "'Ride'", "'VirtualRide'", "'GravelRide'", "'MountainBikeRide'",
    "'cycling'", "'road_biking'", "'gravel_cycling'", "'virtual_ride'",
    "'indoor_cycling'", "'cycling_training'", "'mountain_biking'",
)
_CYCLING_IN = f"({','.join(_CYCLING_SPORT_TYPES)})"


def get_weekly_tss_summary(weeks: int = 5) -> list[dict]:
    """
    Return one row per week for the past `weeks` weeks (oldest first).
    Each row: {week_start, week_end, planned_tss, actual_tss, rides, zone_hours}
    zone_hours is a 5-element list [z1_hrs, z2_hrs, z3_hrs, z4_hrs, z5_hrs].
    """
    from datetime import date, timedelta

    today = date.today()
    # Start of current ISO week (Monday)
    week_start = today - timedelta(days=today.weekday())

    results = []
    conn = get_conn()
    for i in range(weeks - 1, -1, -1):
        ws = week_start - timedelta(weeks=i)
        we = ws + timedelta(days=6)
        ws_iso, we_iso = ws.isoformat(), we.isoformat()

        # Planned TSS from workouts
        plan_rows = conn.execute(
            "SELECT COALESCE(tss_planned,0) AS tp FROM workouts WHERE date BETWEEN ? AND ?",
            (ws_iso, we_iso),
        ).fetchall()
        planned = sum(r["tp"] for r in plan_rows)

        # Actual TSS + zone breakdown from cycling activities
        act_rows = conn.execute(
            f"""SELECT tss, duration_seconds, zone_time_json
                FROM activities
                WHERE date BETWEEN ? AND ?
                  AND LOWER(sport_type) IN
                      ('ride','virtualride','gravelride','mountainbikeride',
                       'cycling','road_biking','gravel_cycling','virtual_ride',
                       'indoor_cycling','cycling_training','mountain_biking')""",
            (ws_iso, we_iso),
        ).fetchall()

        actual = sum(r["tss"] or 0 for r in act_rows)
        zone_seconds = [0.0] * 5
        for r in act_rows:
            if r["zone_time_json"]:
                z = json.loads(r["zone_time_json"])
                for j in range(5):
                    zone_seconds[j] += z.get(f"z{j + 1}_s", 0)

        results.append({
            "week_start": ws_iso,
            "week_end": we_iso,
            "planned_tss": round(planned, 1),
            "actual_tss": round(actual, 1),
            "rides": len(act_rows),
            "zone_hours": [round(s / 3600, 2) for s in zone_seconds],
        })

    conn.close()
    return results


def recalculate_all_tss():
    """Recompute TSS and zone estimates for every stored activity."""
    from auth.strava import _compute_tss, _compute_hr_tss, _estimate_tss
    from metrics.zones import estimate_zone_seconds

    ftp = float(get_setting("ftp_watts", 0) or 0)
    lthr = float(get_setting("lthr", 0) or 0)

    conn = get_conn()
    rows = conn.execute(
        """SELECT id, duration_seconds, elapsed_seconds, normalized_power,
                  avg_power_watts, avg_hr, max_hr FROM activities"""
    ).fetchall()
    updated = 0
    for row in rows:
        duration_s = row["elapsed_seconds"] or row["duration_seconds"] or 0
        np = row["normalized_power"]
        avg_hr = row["avg_hr"]
        max_hr = row["max_hr"]

        tss = _compute_tss(duration_s, np, ftp) if np else None
        if tss is None:
            tss = _compute_hr_tss(duration_s, avg_hr, lthr)
        if tss is None:
            tss = _estimate_tss(duration_s, None, avg_hr, max_hr)

        if_value = (np / ftp) if (np and ftp) else None

        zones = estimate_zone_seconds(
            duration_s, avg_hr, max_hr,
            row["avg_power_watts"], np, ftp, lthr,
        )
        zone_json = json.dumps(zones) if zones else None

        conn.execute(
            "UPDATE activities SET tss=?, if_value=?, zone_time_json=? WHERE id=?",
            (
                round(tss, 1) if tss else None,
                round(if_value, 3) if if_value else None,
                zone_json,
                row["id"],
            ),
        )
        updated += 1
    conn.commit()
    conn.close()
    return updated


# ── Strength Sessions ─────────────────────────────────────────────────────────

def add_strength_session(data: dict) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO strength_sessions (date, plan_week, exercises_json,
           duration_minutes, notes) VALUES (:date,:plan_week,:exercises_json,
           :duration_minutes,:notes)""",
        data,
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def get_strength_sessions(days_back: int = 60) -> list:
    since = (date.today() - timedelta(days=days_back)).isoformat()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM strength_sessions WHERE date >= ? ORDER BY date DESC",
        (since,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_strength_complete(sid: int, duration_minutes: int, notes: str = ""):
    conn = get_conn()
    conn.execute(
        "UPDATE strength_sessions SET completed=1, duration_minutes=?, notes=? WHERE id=?",
        (duration_minutes, notes, sid),
    )
    conn.commit()
    conn.close()


# ── Daily Wellness ────────────────────────────────────────────────────────────

def log_wellness(data: dict) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO daily_wellness (date, legs_feel, energy, sleep_hours, notes, created_at)
           VALUES (:date, :legs_feel, :energy, :sleep_hours, :notes, :created_at)
           ON CONFLICT(date) DO UPDATE SET
               legs_feel=excluded.legs_feel, energy=excluded.energy,
               sleep_hours=excluded.sleep_hours, notes=excluded.notes""",
        {**data, "created_at": datetime.utcnow().isoformat()},
    )
    conn.commit()
    conn.close()


def get_wellness(day: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM daily_wellness WHERE date=?", (day,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_wellness_range(start: str, end: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM daily_wellness WHERE date BETWEEN ? AND ? ORDER BY date",
        (start, end),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── FTP History ───────────────────────────────────────────────────────────────

def log_ftp_history(ftp_watts: int, notes: str = "") -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO ftp_history (date, ftp_watts, notes, created_at) VALUES (?,?,?,?)",
        (date.today().isoformat(), ftp_watts, notes, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_ftp_history(limit: int = 30) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM ftp_history ORDER BY date DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


# ── Race Results ──────────────────────────────────────────────────────────────

def log_race_result(race_id: int, data: dict) -> None:
    conn = get_conn()
    conn.execute(
        """UPDATE races SET placing=:placing, field_size=:field_size,
           finish_time_seconds=:finish_time_seconds, race_avg_power=:race_avg_power,
           race_avg_hr=:race_avg_hr, legs_feel=:legs_feel,
           result_notes=:result_notes, result_logged=1
           WHERE id=:id""",
        {**data, "id": race_id},
    )
    conn.commit()
    conn.close()


# ── AI Conversations ──────────────────────────────────────────────────────────

def save_message(role: str, content: str, context_snapshot: dict = None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO ai_conversations (timestamp, role, content, context_snapshot) VALUES (?,?,?,?)",
        (
            datetime.utcnow().isoformat(),
            role,
            content,
            json.dumps(context_snapshot) if context_snapshot else None,
        ),
    )
    conn.commit()
    conn.close()


def get_conversation_history(limit: int = 20) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT role, content FROM ai_conversations ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
