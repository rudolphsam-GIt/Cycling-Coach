from __future__ import annotations
import sqlite3
import json
from datetime import datetime, date, timedelta
from db.schema import get_conn


# Every sport_type a ride can be stored as, lowercased: Strava names, Garmin type
# keys, and the labels written by .fit/.csv imports.
CYCLING_SPORT_TYPES = (
    "ride", "virtualride", "gravelride", "mountainbikeride", "cycling",
    "road_biking", "gravel_cycling", "virtual_ride", "indoor_cycling",
    "cycling_training", "mountain_biking",
    "road cycling", "gravel cycling", "mountain biking", "virtual cycling", "indoor cycling",
)
_CYCLING_PLACEHOLDERS = ",".join("?" * len(CYCLING_SPORT_TYPES))


def is_ride(activity: dict) -> bool:
    return (activity.get("sport_type") or "").lower() in CYCLING_SPORT_TYPES


# ── Athlete Settings ──────────────────────────────────────────────────────────

# Pages read a dozen or more settings per rerun. Keep them all in memory,
# keyed by database file, and reload after a write or a short expiry so a
# background sync in another process is still picked up.
_SETTINGS_TTL = 30.0
_settings_cache: dict = {}


def get_all_settings() -> dict:
    from db import schema
    import time
    path = schema.current_path()
    hit = _settings_cache.get(path)
    if hit and time.monotonic() - hit[0] < _SETTINGS_TTL:
        return hit[1]
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM athlete_settings").fetchall()
    conn.close()
    values = {r["key"]: r["value"] for r in rows}
    _settings_cache[path] = (time.monotonic(), values)
    return values


def get_setting(key: str, default=None):
    value = get_all_settings().get(key)
    return default if value is None else value


def set_setting(key: str, value):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO athlete_settings (key, value, updated_at) VALUES (?,?,?)",
        (key, str(value), datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    _settings_cache.clear()


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


MILES_TO_KM = 1.609344


def _times(row: dict) -> set:
    return {t for t in (row.get("elapsed_seconds"), row.get("duration_seconds")) if t}


def _same_ride(a: dict, b: dict) -> bool:
    """
    True when two records from different sources look like the same ride.

    Sources measure time differently (Strava's elapsed time includes stops,
    Garmin's timer time doesn't), so the closest pairing of elapsed or moving
    time is compared: within 5 minutes, or within 10 minutes / 10% when the
    distances agree within 3%. Distances must agree within 10% (or 500 m),
    allowing for older .csv imports that stored miles as kilometers.
    Records need a "source" key for that allowance to apply.
    """
    ta, tb = _times(a), _times(b)
    if not ta or not tb:
        return False
    if a.get("sport_type") and b.get("sport_type") and is_ride(a) != is_ride(b):
        return False                    # a strength session is never the same thing as a ride
    time_gap = min(abs(x - y) for x in ta for y in tb)

    da, db_ = a.get("distance_meters") or 0, b.get("distance_meters") or 0
    # Only older .csv imports ever stored miles as kilometers; Strava and Garmin store meters.
    maybe_miles = "csv_import" in (a.get("source"), b.get("source"))
    close_distance = False
    if da and db_:
        big, small = max(da, db_), min(da, db_)
        ratio = big / small
        miles_mixup = maybe_miles and abs(ratio / MILES_TO_KM - 1) <= 0.03
        close_distance = big - small <= 300 or ratio <= 1.03 or miles_mixup
        if not close_distance and big - small > 500 and (big - small) / big > 0.10:
            return False

    # A near exact distance match is strong evidence, so allow a bigger time gap for stops.
    limit = max(600, 0.10 * max(ta | tb)) if close_distance else 300
    return time_gap <= limit


def _find_cross_source_duplicate(conn, data: dict):
    """Return an existing row from a different source that is the same ride, or None."""
    if not _times(data):
        return None
    rows = conn.execute(
        "SELECT * FROM activities WHERE date = ? AND source != ?",
        (data["date"], data["source"]),
    ).fetchall()
    for row in rows:
        candidate = dict(row)
        # A ride the rider corrected by hand is matched on its time and distance as first synced.
        if candidate.get("original_json"):
            try:
                candidate.update(json.loads(candidate["original_json"]))
            except (TypeError, ValueError):
                pass
        if _same_ride(data, candidate):
            return row
    return None


def upsert_activity(data: dict):
    conn = get_conn()
    data.setdefault("elapsed_seconds", None)
    data.setdefault("timer_seconds", None)
    data.setdefault("tss_source", None)
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
                   avg_power_watts  = CASE WHEN edited = 1 THEN avg_power_watts ELSE COALESCE(?, avg_power_watts) END,
                   normalized_power = CASE WHEN edited = 1 THEN normalized_power ELSE COALESCE(?, normalized_power) END,
                   tss              = CASE WHEN tss_locked = 1 OR edited = 1 THEN tss ELSE COALESCE(?, tss) END,
                   tss_source       = CASE WHEN tss_locked = 1 OR edited = 1 OR ? IS NULL
                                           THEN tss_source ELSE ? END,
                   if_value         = CASE WHEN edited = 1 THEN if_value ELSE COALESCE(?, if_value) END,
                   avg_hr           = CASE WHEN edited = 1 THEN avg_hr ELSE COALESCE(?, avg_hr) END,
                   max_hr           = CASE WHEN edited = 1 THEN max_hr ELSE COALESCE(?, max_hr) END,
                   zone_time_json   = CASE WHEN edited = 1 THEN zone_time_json ELSE COALESCE(?, zone_time_json) END,
                   timer_seconds    = COALESCE(timer_seconds, ?)
                   WHERE id = ?""",
                (
                    data.get("avg_power_watts"), data.get("normalized_power"),
                    data.get("tss"), data.get("tss"), data.get("tss_source"), data.get("if_value"),
                    data.get("avg_hr"), data.get("max_hr"),
                    data.get("zone_time_json"), data.get("timer_seconds"), dup["id"],
                ),
            )
            conn.commit()
        # Either way, don't insert a second row
        conn.close()
        return dup["id"]

    conn.execute(
        """INSERT INTO activities
           (source, external_id, date, name, sport_type, duration_seconds,
            elapsed_seconds, distance_meters, elevation_gain_meters, avg_power_watts, avg_hr,
            max_hr, normalized_power, tss, if_value, raw_json, zone_time_json, timer_seconds,
            tss_source)
           VALUES (:source,:external_id,:date,:name,:sport_type,:duration_seconds,
                   :elapsed_seconds,:distance_meters,:elevation_gain_meters,:avg_power_watts,:avg_hr,
                   :max_hr,:normalized_power,:tss,:if_value,:raw_json,:zone_time_json,:timer_seconds,
                   :tss_source)
           ON CONFLICT(external_id) DO UPDATE SET
               timer_seconds=COALESCE(excluded.timer_seconds, activities.timer_seconds),
               tss=CASE WHEN activities.tss_locked = 1 OR activities.edited = 1
                        THEN activities.tss ELSE excluded.tss END,
               tss_source=CASE WHEN activities.tss_locked = 1 OR activities.edited = 1
                               THEN activities.tss_source ELSE excluded.tss_source END,
               if_value=CASE WHEN activities.edited = 1 THEN activities.if_value ELSE excluded.if_value END,
               normalized_power=CASE WHEN activities.edited = 1 THEN activities.normalized_power
                                     ELSE excluded.normalized_power END,
               avg_power_watts=CASE WHEN activities.edited = 1 THEN activities.avg_power_watts
                                    ELSE excluded.avg_power_watts END,
               elapsed_seconds=CASE WHEN activities.edited = 1 THEN activities.elapsed_seconds
                                    ELSE excluded.elapsed_seconds END,
               avg_hr=CASE WHEN activities.edited = 1 THEN activities.avg_hr ELSE excluded.avg_hr END,
               max_hr=CASE WHEN activities.edited = 1 THEN activities.max_hr ELSE excluded.max_hr END,
               zone_time_json=CASE WHEN activities.edited = 1 THEN activities.zone_time_json
                                   ELSE COALESCE(excluded.zone_time_json, activities.zone_time_json) END""",
        data,
    )
    conn.commit()
    row = conn.execute("SELECT id FROM activities WHERE external_id = ?",
                       (data.get("external_id"),)).fetchone()
    conn.close()
    return row["id"] if row else None


def set_ref_numbers(activity_id: int, service: str, numbers: dict | None) -> None:
    """Keep what a service ("trainingpeaks" or "intervals") has for this activity (tss, hours,
    np, avg_hr, scored_by), only to compare with the app's own score. None clears it."""
    conn = get_conn()
    row = conn.execute("SELECT ref_json FROM activities WHERE id=?", (activity_id,)).fetchone()
    try:
        ref = json.loads(row["ref_json"]) if row and row["ref_json"] else {}
    except (TypeError, ValueError):
        ref = {}
    if numbers:
        ref[service] = numbers
    else:
        ref.pop(service, None)
    conn.execute("UPDATE activities SET ref_json=? WHERE id=?", (json.dumps(ref) if ref else None, activity_id))
    conn.commit()
    conn.close()


def apply_device_numbers(activity_id: int, normalized_power: float | None,
                         timer_seconds: float | None) -> bool:
    """Take normalized power and timer time from the device's own record of a ride (Garmin) over
    what another source sent. Strava's "weighted average power" runs a few percent under true
    normalized power, which costs about twice that in TSS. Rides corrected by hand keep their
    numbers. True if anything changed."""
    row = get_activity(activity_id)
    if not row or row.get("edited"):
        return False
    np_w = round(float(normalized_power)) if normalized_power else None
    timer = int(timer_seconds) if timer_seconds else None
    if (np_w is None or np_w == row.get("normalized_power")) and \
            (timer is None or timer == row.get("timer_seconds")):
        return False
    conn = get_conn()
    conn.execute("""UPDATE activities SET normalized_power=COALESCE(?, normalized_power),
                    timer_seconds=COALESCE(?, timer_seconds) WHERE id=?""", (np_w, timer, activity_id))
    conn.commit()
    conn.close()
    return True


def match_activity_id(data: dict) -> int | None:
    """The id of the stored ride this record describes (same external id, or the
    same ride from another source), without writing anything."""
    conn = get_conn()
    row = conn.execute("SELECT id FROM activities WHERE external_id = ?",
                       (data.get("external_id"),)).fetchone()
    if not row:
        row = _find_cross_source_duplicate(conn, data)
    conn.close()
    return row["id"] if row else None


# ── Peak power (best average power per duration, per ride) ────────────────────

def save_peaks(activity_id: int, peaks: dict) -> None:
    """Store best average power by duration in seconds. Keeps the higher value if
    a ride already has one for that duration (another source may differ slightly)."""
    if not activity_id or not peaks:
        return
    conn = get_conn()
    conn.executemany(
        """INSERT INTO activity_peaks (activity_id, duration_s, watts) VALUES (?, ?, ?)
           ON CONFLICT(activity_id, duration_s) DO UPDATE SET watts = MAX(watts, excluded.watts)""",
        [(activity_id, int(d), float(w)) for d, w in peaks.items()],
    )
    conn.commit()
    conn.close()


def get_peaks_between(start: str, end: str) -> list:
    """Rows of {activity_id, date, name, duration_s, watts} for rides in the range."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT p.activity_id, a.date, a.name, p.duration_s, p.watts
           FROM activity_peaks p JOIN activities a ON a.id = p.activity_id
           WHERE a.date BETWEEN ? AND ? ORDER BY a.date""",
        (start, end),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_activities_between(start: str, end: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM activities WHERE date BETWEEN ? AND ? ORDER BY date DESC", (start, end)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_streams(activity_id: int, streams: dict, source: str = "") -> None:
    """Keep a ride's second by second data so it only has to be fetched once."""
    if not activity_id or not streams:
        return
    data = json.dumps(streams, separators=(",", ":"))
    if len(data) > 8_000_000:       # a very long ride, not worth keeping
        return
    conn = get_conn()
    conn.execute(
        """INSERT INTO activity_streams (activity_id, data, source, fetched_at) VALUES (?, ?, ?, ?)
           ON CONFLICT(activity_id) DO UPDATE SET data=excluded.data, source=excluded.source,
           fetched_at=excluded.fetched_at""",
        (activity_id, data, source, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def rescore_from_streams(activity_id: int) -> bool:
    """Rescore a ride once its second by second data is saved, when that data has no power or a
    power dropout (see metrics.tss.stream_tss). True if the TSS was recalculated."""
    from metrics.tss import stream_tss
    act = get_activity(activity_id)
    if not act or act.get("tss_locked"):
        return False
    from metrics.tss import time_rule, tss_duration
    lthr = float(get_setting("lthr", 0) or 0)
    profile = hr_profile()
    seconds = tss_duration(act.get("duration_seconds"), act.get("elapsed_seconds"), act.get("timer_seconds"),
                           time_rule(profile))
    if not stream_tss(get_streams(activity_id), ftp_on(act["date"]), lthr, profile, seconds):
        return False
    recalculate_all_tss(only_id=activity_id)
    return True


def get_streams(activity_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT data FROM activity_streams WHERE activity_id = ?", (activity_id,)).fetchone()
    conn.close()
    if not row:
        return None
    try:
        return json.loads(row["data"])
    except (TypeError, ValueError):
        return None


def set_activity_tss(activity_id: int, tss: float) -> None:
    """Set a ride's TSS by hand. The value is locked, so a later sync or a recalculation
    leaves it alone until clear_activity_tss is called."""
    conn = get_conn()
    conn.execute("UPDATE activities SET tss=?, tss_locked=1, tss_source='manual' WHERE id=?",
                 (round(float(tss), 1), activity_id))
    conn.commit()
    conn.close()


ACTIVITY_EDIT_FIELDS = ("name", "duration_seconds", "distance_meters", "elevation_gain_meters",
                        "avg_power_watts", "normalized_power", "avg_hr", "max_hr")
# Fields a sync would overwrite. Editing one of these marks the ride edited so the next sync keeps
# the rider's numbers. The name, distance and climbing are never overwritten by a sync.
SYNCED_FIELDS = ("duration_seconds", "avg_power_watts", "normalized_power", "avg_hr", "max_hr")
# What duplicate matching compares, kept as synced before the first edit.
MATCH_FIELDS = ("duration_seconds", "elapsed_seconds", "distance_meters")


def update_activity_details(activity_id: int, values: dict) -> None:
    """Correct a ride by hand. Only the fields in ACTIVITY_EDIT_FIELDS are written. A new duration
    also replaces the elapsed time, which the TSS maths prefers. The synced time and distance are
    kept in original_json the first time, so the same ride from another source still matches."""
    row = get_activity(activity_id)
    if not row:
        return
    fields = {k: values[k] for k in ACTIVITY_EDIT_FIELDS if k in values}
    if not fields:
        return
    if "duration_seconds" in fields:
        fields["elapsed_seconds"] = fields["duration_seconds"]
    sets = ", ".join(f"{k}=?" for k in fields)
    if any(k in fields for k in SYNCED_FIELDS):
        sets += ", edited=1"
    original = json.dumps({k: row.get(k) for k in MATCH_FIELDS})
    conn = get_conn()
    conn.execute(f"UPDATE activities SET {sets}, original_json=COALESCE(original_json, ?) WHERE id=?",
                 (*fields.values(), original, activity_id))
    conn.commit()
    conn.close()


def clear_activity_tss(activity_id: int) -> None:
    """Go back to the calculated TSS for one ride."""
    conn = get_conn()
    conn.execute("UPDATE activities SET tss_locked=0 WHERE id=?", (activity_id,))
    conn.commit()
    conn.close()
    recalculate_all_tss(only_id=activity_id)


def get_activity(activity_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM activities WHERE id = ?", (activity_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_hr_peaks(activity_id: int, peaks: dict) -> None:
    """Store best average heart rate by duration in seconds, keeping the higher value."""
    if not activity_id or not peaks:
        return
    conn = get_conn()
    conn.executemany(
        """INSERT INTO activity_hr_peaks (activity_id, duration_s, bpm) VALUES (?, ?, ?)
           ON CONFLICT(activity_id, duration_s) DO UPDATE SET bpm = MAX(bpm, excluded.bpm)""",
        [(activity_id, int(d), float(b)) for d, b in peaks.items()],
    )
    conn.commit()
    conn.close()


def get_hr_peaks_between(start: str, end: str) -> list:
    """Rows of {activity_id, date, name, duration_s, bpm} for rides in the range."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT p.activity_id, a.date, a.name, p.duration_s, p.bpm
           FROM activity_hr_peaks p JOIN activities a ON a.id = p.activity_id
           WHERE a.date BETWEEN ? AND ? ORDER BY a.date""",
        (start, end),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def has_hr_peaks(activity_id: int) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM activity_hr_peaks WHERE activity_id = ? LIMIT 1",
                       (activity_id,)).fetchone()
    conn.close()
    return row is not None


def first_activity_date() -> str | None:
    conn = get_conn()
    row = conn.execute("SELECT MIN(date) AS d FROM activities").fetchone()
    conn.close()
    return row["d"] if row else None


def deduplicate_activities() -> int:
    """
    Find and remove cross-source duplicates already in the DB.
    Keeps the higher-scoring row, deletes the other.
    Returns number of rows deleted.
    """
    conn = get_conn()
    rows = conn.execute("SELECT * FROM activities ORDER BY date, id").fetchall()
    rows = [dict(r) for r in rows]

    to_delete = set()
    kept_for = {}   # dropped id -> kept id, so peak power moves to the row that stays
    for i, a in enumerate(rows):
        if a["id"] in to_delete:
            continue
        for b in rows[i + 1:]:
            if b["date"] != a["date"]:
                break
            if b["id"] in to_delete or b["source"] == a["source"]:
                continue
            if _same_ride(a, b):
                # Duplicate found — delete the lower-scoring one
                keep, drop = (a, b) if _activity_score(a) >= _activity_score(b) else (b, a)
                to_delete.add(drop["id"])
                kept_for[drop["id"]] = keep["id"]
                if drop is a:
                    break

    if to_delete:
        for drop_id, keep_id in kept_for.items():
            conn.execute(
                """INSERT INTO activity_peaks (activity_id, duration_s, watts)
                   SELECT ?, duration_s, watts FROM activity_peaks WHERE activity_id = ?
                   ON CONFLICT(activity_id, duration_s) DO UPDATE SET watts = MAX(watts, excluded.watts)""",
                (keep_id, drop_id))
        for drop_id, keep_id in kept_for.items():
            conn.execute(
                """INSERT INTO activity_hr_peaks (activity_id, duration_s, bpm)
                   SELECT ?, duration_s, bpm FROM activity_hr_peaks WHERE activity_id = ?
                   ON CONFLICT(activity_id, duration_s) DO UPDATE SET bpm = MAX(bpm, excluded.bpm)""",
                (keep_id, drop_id))
        for drop_id, keep_id in kept_for.items():
            conn.execute(
                """INSERT OR IGNORE INTO activity_streams (activity_id, data, source, fetched_at)
                   SELECT ?, data, source, fetched_at FROM activity_streams WHERE activity_id = ?""",
                (keep_id, drop_id))
        for table in ("activity_peaks", "activity_hr_peaks", "activity_streams"):
            conn.execute(
                f"DELETE FROM {table} WHERE activity_id IN ({','.join('?' * len(to_delete))})",
                list(to_delete),
            )
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


def checklist_counts(today: str) -> dict:
    """Counts for the getting started checklist, in one round trip."""
    conn = get_conn()
    row = conn.execute(
        """SELECT (SELECT COUNT(*) FROM activities) AS rides,
                  (SELECT COUNT(*) FROM workouts) AS workouts,
                  (SELECT COUNT(*) FROM activities
                    WHERE date BETWEEN (SELECT MIN(date) FROM workouts) AND ?) AS rides_since_plan""",
        (today,)).fetchone()
    conn.close()
    return dict(row)


def get_daily_tss(start: str, end: str) -> dict:
    """Return {date_str: total_tss} for the given date range. Every sport counts, as in
    TrainingPeaks: strength, hikes and skiing add to fitness and fatigue as well as rides."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT date, SUM(COALESCE(tss,0)) as total_tss
           FROM activities
           WHERE date BETWEEN ? AND ?
           GROUP BY date""",
        (start, end),
    ).fetchall()
    conn.close()
    return {r["date"]: r["total_tss"] for r in rows}


# ── Workouts ──────────────────────────────────────────────────────────────────

WORKOUT_TYPES = ["Endurance", "Tempo", "Threshold", "VO2 Max", "Sprint/Anaerobic",
                 "Recovery", "Long Ride", "Race", "Other"]


def _plan_changed(conn) -> None:
    """Note that planned workouts changed, so the TrainingPeaks sync knows to run. Written in
    the caller's connection so it commits with the change itself."""
    conn.execute("INSERT OR REPLACE INTO athlete_settings (key, value, updated_at) VALUES (?,?,?)",
                 ("plan_changed_at", datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))
    _settings_cache.clear()


def _insert_workout(conn, data: dict) -> int:
    return conn.execute(
        """INSERT INTO workouts (date, name, workout_type, description,
           structured_json, tss_planned, notes, phase, week_number, purpose, feel)
           VALUES (:date,:name,:workout_type,:description,:structured_json,:tss_planned,:notes,
                   :phase,:week_number,:purpose,:feel)""",
        {**data, "phase": data.get("phase"), "week_number": data.get("week_number"),
         "purpose": data.get("purpose"), "feel": data.get("feel")},
    ).lastrowid


def add_workout(data: dict) -> int:
    conn = get_conn()
    wid = _insert_workout(conn, data)
    _plan_changed(conn)
    conn.commit()
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
    """Save edits. The date is not changed here, use move_workout for that."""
    conn = get_conn()
    conn.execute(
        """UPDATE workouts SET name=:name, workout_type=:workout_type,
           description=:description, tss_planned=:tss_planned,
           completed=:completed, notes=:notes,
           purpose=COALESCE(:purpose, purpose), feel=COALESCE(:feel, feel),
           -- Saved steps are rebuilt when what they were built from changes
           structured_json=CASE WHEN description IS :description AND name IS :name
                                     AND tss_planned IS :tss_planned AND workout_type IS :workout_type
                                THEN structured_json ELSE NULL END
           WHERE id=:id""",
        {**data, "purpose": data.get("purpose"), "feel": data.get("feel"), "id": wid},
    )
    _plan_changed(conn)
    conn.commit()
    conn.close()


def move_workout(wid: int, new_date: str) -> dict | None:
    """Move a planned workout to another day. The Garmin ids are cleared, since the
    copy on Garmin is scheduled for the old day. Returns the row as it was before
    the move (so the caller can remove the Garmin copy or undo), or None if the
    workout doesn't exist or is already on that day."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM workouts WHERE id=?", (wid,)).fetchone()
    if not row or row["date"] == new_date:
        conn.close()
        return None
    conn.execute(
        """UPDATE workouts SET date=?, garmin_workout_id=NULL, garmin_schedule_id=NULL,
           garmin_sent_at=NULL WHERE id=?""",
        (new_date, wid),
    )
    _plan_changed(conn)
    conn.commit()
    conn.close()
    return dict(row)


# ── Why a block is built the way it is ────────────────────────────────────────

def _upsert_phase_notes(conn, phases: list) -> None:
    rows = [(p["name"], p.get("focus"), p.get("why"), datetime.utcnow().isoformat())
            for p in phases or [] if p.get("name")]
    if rows:
        conn.executemany(
            """INSERT INTO plan_phases (phase, focus, why, updated_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(phase) DO UPDATE SET focus=excluded.focus, why=excluded.why,
               updated_at=excluded.updated_at""", rows)


def save_phase_notes(phases: list) -> None:
    """Store the focus and reason for each named phase of a plan. A later plan
    that reuses a phase name replaces its note."""
    conn = get_conn()
    _upsert_phase_notes(conn, phases)
    conn.commit()
    conn.close()


def get_phase_notes() -> dict:
    """{phase name: {focus, why}} for every stored phase."""
    conn = get_conn()
    rows = conn.execute("SELECT phase, focus, why FROM plan_phases").fetchall()
    conn.close()
    return {r["phase"]: {"focus": r["focus"], "why": r["why"]} for r in rows}


# ── Multi month programs ──────────────────────────────────────────────────────

def save_program_draft(title: str, start: str, end: str, content_json: str, version: int,
                       previous_id: int | None) -> int:
    """Save a draft program. A new draft replaces the previous one in place, so there is
    only ever one draft, and its version counts the revisions."""
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    if previous_id:
        conn.execute("""UPDATE programs SET title=?, start_date=?, end_date=?, content_json=?,
                        version=?, updated_at=? WHERE id=?""",
                     (title, start, end, content_json, version, now, previous_id))
        pid = previous_id
    else:
        pid = conn.execute(
            """INSERT INTO programs (title, status, start_date, end_date, content_json, version,
               created_at, updated_at) VALUES (?, 'draft', ?, ?, ?, ?, ?, ?)""",
            (title, start, end, content_json, version, now, now)).lastrowid
    conn.commit()
    conn.close()
    return pid


def get_program(status: str) -> dict | None:
    """The newest program with this status, or None."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM programs WHERE status=? ORDER BY id DESC LIMIT 1",
                       (status,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_program_by_id(pid: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM programs WHERE id=?", (pid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def set_program_status(pid: int, status: str) -> None:
    conn = get_conn()
    conn.execute("UPDATE programs SET status=?, updated_at=? WHERE id=?",
                 (status, datetime.utcnow().isoformat(), pid))
    conn.commit()
    conn.close()


def apply_program_rows(pid: int, *, remove_workout_ids: list, remove_strength_ids: list,
                       workouts: list, strength: list, phases: list) -> dict | None:
    """Put a draft program on the calendar in one transaction: make it the active program
    (archiving any earlier one), remove the planned items it replaces, and add its workouts,
    strength sessions and phase notes. Either all of it happens or none of it does. Returns the
    removed workout rows (so their Garmin copies can be deleted) and how many strength sessions
    went, or None when the program is not a draft any more, such as after a second click."""
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    try:
        if conn.execute("UPDATE programs SET status='active', executed_at=?, updated_at=? "
                        "WHERE id=? AND status='draft'", (now, now, pid)).rowcount != 1:
            conn.rollback()
            return None
        conn.execute("UPDATE programs SET status='archived', updated_at=? WHERE status='active' AND id != ?",
                     (now, pid))
        removed = []
        if remove_workout_ids:
            marks = ",".join("?" * len(remove_workout_ids))
            removed = [dict(r) for r in conn.execute(
                f"SELECT * FROM workouts WHERE id IN ({marks}) AND COALESCE(completed, 0) = 0",
                remove_workout_ids)]
            conn.executemany("DELETE FROM workouts WHERE id=?", [(r["id"],) for r in removed])
        strength_removed = 0
        if remove_strength_ids:
            marks = ",".join("?" * len(remove_strength_ids))
            strength_removed = conn.execute(
                f"DELETE FROM strength_sessions WHERE id IN ({marks}) AND COALESCE(completed, 0) = 0",
                remove_strength_ids).rowcount
        for w in workouts:
            _insert_workout(conn, w)
        for s_ in strength:
            _insert_strength(conn, s_)
        _upsert_phase_notes(conn, phases)
        _plan_changed(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"removed_workouts": removed, "strength_removed": strength_removed}


def get_workout(wid: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM workouts WHERE id=?", (wid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def set_workout_garmin(wid: int, garmin_workout_id: str, garmin_schedule_id: str | None,
                       steps_json: str, sent_at: str) -> None:
    conn = get_conn()
    conn.execute(
        """UPDATE workouts SET garmin_workout_id=?, garmin_schedule_id=?,
           structured_json=?, garmin_sent_at=? WHERE id=?""",
        (garmin_workout_id, garmin_schedule_id, steps_json, sent_at, wid),
    )
    conn.commit()
    conn.close()


def add_race_notes(race_id: int, text: str) -> None:
    """Append to a race's notes, keeping what's there (such as the OBRA link)."""
    conn = get_conn()
    row = conn.execute("SELECT notes FROM races WHERE id=?", (race_id,)).fetchone()
    if row is not None:
        existing = (row["notes"] or "").strip()
        notes = f"{existing}\n\n{text.strip()}" if existing else text.strip()
        conn.execute("UPDATE races SET notes=? WHERE id=?", (notes, race_id))
        conn.commit()
    conn.close()


def get_upcoming_workouts(since: str) -> list:
    """Planned workouts on or after `since` that aren't done yet."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM workouts WHERE date >= ? AND COALESCE(completed, 0) = 0 ORDER BY date",
        (since,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_workout_descriptions(updates: list[tuple[int, str]]) -> None:
    """Rewrite descriptions without touching saved steps (used when only the watt numbers
    follow a new FTP, since steps are stored as % of FTP)."""
    if not updates:
        return
    conn = get_conn()
    conn.executemany("UPDATE workouts SET description=? WHERE id=?",
                     [(text, wid) for wid, text in updates])
    _plan_changed(conn)
    conn.commit()
    conn.close()


def save_workout_steps(wid: int, steps_json: str) -> None:
    """Keep the structured steps built for a workout, so exports don't build them again.
    The Garmin ids are left alone, so a workout that was never sent still reads not sent."""
    conn = get_conn()
    conn.execute("UPDATE workouts SET structured_json=? WHERE id=?", (steps_json, wid))
    conn.commit()
    conn.close()


# ── What has been sent to intervals.icu and TrainingPeaks ─────────────────────

def get_synced(service: str) -> dict[int, dict]:
    """{workout id: row} for everything this app has put on `service`."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM external_sync WHERE service=?", (service,)).fetchall()
    conn.close()
    return {r["workout_id"]: dict(r) for r in rows}


def save_synced(service: str, rows: list[dict]) -> None:
    """Record workouts as sent. Each row has workout_id, remote_id, date and fingerprint."""
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    conn.executemany(
        """INSERT INTO external_sync (service, workout_id, remote_id, date, fingerprint, pushed_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(service, workout_id) DO UPDATE SET remote_id=excluded.remote_id,
           date=excluded.date, fingerprint=excluded.fingerprint, pushed_at=excluded.pushed_at""",
        [(service, r["workout_id"], r.get("remote_id"), r["date"], r.get("fingerprint"), now) for r in rows])
    conn.commit()
    conn.close()


def drop_synced(service: str, workout_ids: list[int]) -> None:
    if not workout_ids:
        return
    conn = get_conn()
    conn.executemany("DELETE FROM external_sync WHERE service=? AND workout_id=?",
                     [(service, w) for w in workout_ids])
    conn.commit()
    conn.close()


def garmin_status(workout: dict) -> str:
    """'not_sent', 'sent', or 'changed' (edited since it was sent)."""
    if not workout.get("garmin_workout_id"):
        return "not_sent"
    return "sent" if workout.get("structured_json") else "changed"


def delete_workout(wid: int):
    conn = get_conn()
    conn.execute("DELETE FROM workouts WHERE id=?", (wid,))
    _plan_changed(conn)
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
                  AND LOWER(sport_type) IN ({_CYCLING_PLACEHOLDERS})""",
            (ws_iso, we_iso, *CYCLING_SPORT_TYPES),
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


def hr_profile() -> dict:
    """How rides are scored: resting and max heart rate and the TRIMP curve constant for hrTSS,
    and from the "Score like" standard the heart rate method and time rule ("timer" or
    "moving"). Each heart rate is the rider's own number from Settings when set, else worked
    out: resting from Garmin's last 30 days, max from the highest reading another ride comes
    close to in the last year. Missing values are None, and TRIMP then falls back to
    (HR / LTHR) squared."""
    from metrics.tss import STANDARDS, k_for
    rest = float(get_setting("resting_hr_manual", 0) or 0) or auto_resting_hr()
    mx = float(get_setting("max_hr_manual", 0) or 0) or auto_max_hr()
    std = STANDARDS.get(get_setting("score_like", "") or "")
    if std:
        method, time = std["hr_method"], std["time"]
    else:   # settings from before "Score like": the old heart rate choice, on timer time
        method, time = get_setting("hr_tss_method", "") or "trainingpeaks", "timer"
    return {"rest": rest, "max": mx, "k": k_for(get_setting("gender", "")), "method": method, "time": time}


def auto_resting_hr() -> float | None:
    since = (date.today() - timedelta(days=30)).isoformat()
    conn = get_conn()
    row = conn.execute("SELECT AVG(resting_hr) AS r FROM recovery_daily WHERE date >= ? AND resting_hr > 0",
                       (since,)).fetchone()
    conn.close()
    return round(row["r"]) if row and row["r"] else None


def auto_max_hr() -> float | None:
    from metrics.tss import robust_max_hr
    since = (date.today() - timedelta(days=365)).isoformat()
    conn = get_conn()
    rows = conn.execute("SELECT max_hr FROM activities WHERE date >= ? AND max_hr > 0", (since,)).fetchall()
    conn.close()
    return robust_max_hr([r["max_hr"] for r in rows])


def ftp_on(day: str, history: list[dict] | None = None) -> float:
    """The FTP in effect on a date: the latest FTP history entry on or before it, else the
    earliest entry, else the current setting."""
    if history is None:
        history = _ftp_history_rows()
    on_or_before = [h for h in history if h["date"] <= day]
    if on_or_before:
        return float(on_or_before[-1]["ftp_watts"])
    if history:
        return float(history[0]["ftp_watts"])
    return float(get_setting("ftp_watts", 0) or 0)


def first_activity_date() -> str | None:
    conn = get_conn()
    row = conn.execute("SELECT MIN(date) AS d FROM activities").fetchone()
    conn.close()
    return row["d"] if row else None


def oldest_ride_missing_timer(source: str) -> str | None:
    """Date of the oldest ride from `source` saved before timer time was stored, or None."""
    conn = get_conn()
    row = conn.execute("SELECT MIN(date) AS d FROM activities WHERE source=? AND timer_seconds IS NULL",
                       (source,)).fetchone()
    conn.close()
    return row["d"] if row else None


def ftp_history_rows() -> list[dict]:
    return _ftp_history_rows()


def _ftp_history_rows() -> list[dict]:
    """Every FTP history entry, oldest first (later entries on the same day win)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, ftp_watts FROM ftp_history WHERE ftp_watts > 0 ORDER BY date, id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def recalculate_all_tss(only_id: int | None = None, since: str | None = None):
    """Recompute TSS and zone estimates for every stored activity, or just one, or those on or
    after `since`. Each ride is scored on the FTP it was ridden at (FTP history), so a new FTP
    never rewrites past fitness. Rides whose TSS was set by hand are left alone."""
    from metrics.tss import ride_tss, time_rule, tss_duration
    from metrics.zones import estimate_zone_seconds

    from metrics.tss import stream_tss

    history = _ftp_history_rows()
    lthr = float(get_setting("lthr", 0) or 0)
    profile = hr_profile()

    conn = get_conn()
    with_streams = {r["activity_id"] for r in conn.execute("SELECT activity_id FROM activity_streams")}
    rows = conn.execute(
        """SELECT id, date, duration_seconds, elapsed_seconds, timer_seconds, normalized_power,
                  avg_power_watts, avg_hr, max_hr FROM activities
           WHERE COALESCE(tss_locked, 0) = 0 AND (? IS NULL OR id = ?)
             AND (? IS NULL OR date >= ?)""",
        (only_id, only_id, since, since),
    ).fetchall()
    updated = 0
    for row in rows:
        duration_s = tss_duration(row["duration_seconds"], row["elapsed_seconds"], row["timer_seconds"],
                                  time_rule(profile))
        np = row["normalized_power"]
        avg_hr = row["avg_hr"]
        max_hr = row["max_hr"]
        ftp = ftp_on(row["date"], history)

        tss, if_value, source = ride_tss(duration_s, np, avg_hr, max_hr, ftp, lthr, profile=profile)
        if row["id"] in with_streams:
            # Second by second data can score a ride with no power, or patch a power dropout.
            better = stream_tss(get_streams(row["id"]), ftp, lthr, profile, duration_s)
            if better:
                tss, source = better

        zones = estimate_zone_seconds(
            duration_s, avg_hr, max_hr,
            row["avg_power_watts"], np, ftp, lthr,
        )
        zone_json = json.dumps(zones) if zones else None

        conn.execute(
            "UPDATE activities SET tss=?, if_value=?, zone_time_json=?, tss_source=? WHERE id=?",
            (
                round(tss, 1) if tss else None,
                round(if_value, 3) if if_value else None,
                zone_json,
                source if tss else None,
                row["id"],
            ),
        )
        updated += 1
    conn.commit()
    conn.close()
    return updated


# ── Strength Sessions ─────────────────────────────────────────────────────────

def _insert_strength(conn, data: dict) -> int:
    return conn.execute(
        """INSERT INTO strength_sessions (date, plan_week, exercises_json,
           duration_minutes, notes, phase, completed, purpose) VALUES (:date,:plan_week,
           :exercises_json,:duration_minutes,:notes,:phase,:completed,:purpose)""",
        {**data, "phase": data.get("phase"), "completed": data.get("completed", 0),
         "purpose": data.get("purpose")},
    ).lastrowid


def add_strength_session(data: dict) -> int:
    conn = get_conn()
    sid = _insert_strength(conn, data)
    conn.commit()
    conn.close()
    return sid


def get_strength_between(start: str, end: str) -> list:
    """Strength sessions, planned or logged, from start to end inclusive, oldest first."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM strength_sessions WHERE date BETWEEN ? AND ? ORDER BY date",
                        (start, end)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_strength_sessions(days_back: int = 60) -> list:
    since = (date.today() - timedelta(days=days_back)).isoformat()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM strength_sessions WHERE date >= ? ORDER BY date DESC",
        (since,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_strength_session(sid: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM strength_sessions WHERE id=?", (sid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_strength_session(sid: int) -> dict | None:
    """Remove a strength session, planned or logged. Returns the row that was removed,
    or None if it doesn't exist."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM strength_sessions WHERE id=?", (sid,)).fetchone()
    if not row:
        conn.close()
        return None
    conn.execute("DELETE FROM strength_sessions WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    return dict(row)


def update_strength_session(sid: int, *, name: str | None = None, exercises: list | None = None,
                            duration_minutes: int | None = None, purpose: str | None = None) -> dict | None:
    """Change what is in a strength session. Only the fields given are changed. The name
    lives at the front of the notes ("Lower body | Planned by AI Coach"), so it is rewritten
    there. Returns the row as it was before, or None if it doesn't exist."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM strength_sessions WHERE id=?", (sid,)).fetchone()
    if not row:
        conn.close()
        return None
    row = dict(row)
    notes = row.get("notes") or ""
    if name is not None:
        rest = notes.split(" | ", 1)[1] if " | " in notes else "Planned by AI Coach"
        notes = f"{name} | {rest}"
    conn.execute(
        """UPDATE strength_sessions SET notes=?, exercises_json=COALESCE(?, exercises_json),
           duration_minutes=COALESCE(?, duration_minutes), purpose=COALESCE(?, purpose) WHERE id=?""",
        (notes, json.dumps(exercises) if exercises is not None else None, duration_minutes, purpose, sid))
    conn.commit()
    conn.close()
    return row


def move_strength_session(sid: int, new_date: str) -> dict | None:
    """Move a strength session to another day. Returns the row as it was before,
    or None if it doesn't exist or is already on that day."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM strength_sessions WHERE id=?", (sid,)).fetchone()
    if not row or row["date"] == new_date:
        conn.close()
        return None
    conn.execute("UPDATE strength_sessions SET date=? WHERE id=?", (new_date, sid))
    conn.commit()
    conn.close()
    return dict(row)


def mark_strength_complete(sid: int, duration_minutes: int, notes: str = "",
                           exercises_json: str | None = None):
    """Mark a session done. Pass exercises_json to store what was actually lifted."""
    conn = get_conn()
    conn.execute(
        """UPDATE strength_sessions SET completed=1, duration_minutes=?, notes=?,
           exercises_json=COALESCE(?, exercises_json) WHERE id=?""",
        (duration_minutes, notes, exercises_json, sid),
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

def log_ftp_history(ftp_watts: int, notes: str = "", day: str | None = None) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO ftp_history (date, ftp_watts, notes, created_at) VALUES (?,?,?,?)",
        (day or date.today().isoformat(), ftp_watts, notes, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_ftp_history(limit: int = 30) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM ftp_history ORDER BY date DESC, id DESC LIMIT ?", (limit,)
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



def get_conversation_window(keep: int = 18, step: int = 10) -> list:
    """The chat history to send to Claude. The oldest message kept only moves
    forward `step` messages at a time, so for several turns in a row the
    conversation prefix is identical and Claude's prompt cache keeps hitting.
    Sends between `keep` and `keep + step - 1` messages once the chat is long."""
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM ai_conversations").fetchone()[0]
    start = 0 if total < keep + step else ((total - keep) // step) * step
    rows = conn.execute(
        "SELECT role, content FROM ai_conversations ORDER BY id LIMIT -1 OFFSET ?",
        (start,),
    ).fetchall()
    conn.close()
    return [{"role": r["role"], "content": r["content"]} for r in rows]

# ── Recovery (Garmin sleep, HRV, resting HR, readiness) ───────────────────────

RECOVERY_FIELDS = ("sleep_hours", "sleep_score", "hrv_ms", "hrv_status",
                   "resting_hr", "readiness", "body_battery")


def upsert_recovery(day: str, data: dict) -> None:
    row = {k: data.get(k) for k in RECOVERY_FIELDS}
    conn = get_conn()
    conn.execute(
        f"""INSERT INTO recovery_daily (date, {", ".join(RECOVERY_FIELDS)}, synced_at)
            VALUES (:date, {", ".join(":" + k for k in RECOVERY_FIELDS)}, :synced_at)
            ON CONFLICT(date) DO UPDATE SET
            {", ".join(f"{k}=excluded.{k}" for k in RECOVERY_FIELDS)},
            synced_at=excluded.synced_at""",
        {**row, "date": day, "synced_at": datetime.utcnow().isoformat()},
    )
    conn.commit()
    conn.close()


def get_latest_recovery() -> dict | None:
    """The most recent day Garmin sent any sleep or recovery numbers, or None."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM recovery_daily ORDER BY date DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def get_recovery_range(start: str, end: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM recovery_daily WHERE date BETWEEN ? AND ? ORDER BY date", (start, end)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Coach reports (ride reviews, weekly check ins, race plans) ────────────────

def save_report(kind: str, ref_key: str, title: str, content: str) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO coach_reports (kind, ref_key, title, content, created_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(kind, ref_key) DO UPDATE SET
               title=excluded.title, content=excluded.content, created_at=excluded.created_at""",
        (kind, ref_key, title, content, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_report(kind: str, ref_key: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM coach_reports WHERE kind=? AND ref_key=?", (kind, ref_key)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_reports(kind: str, limit: int = 10) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM coach_reports WHERE kind=? ORDER BY ref_key DESC LIMIT ?", (kind, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Coach memory (things the athlete has told the coach) ──────────────────────

def add_memory(category: str, note: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO coach_memory (category, note, created_at) VALUES (?,?,?)",
        (category, note, datetime.utcnow().isoformat()),
    )
    conn.commit()
    mid = cur.lastrowid
    conn.close()
    return mid


def get_memories(active_only: bool = True) -> list:
    conn = get_conn()
    sql = "SELECT * FROM coach_memory"
    if active_only:
        sql += " WHERE active=1"
    rows = conn.execute(sql + " ORDER BY created_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def forget_memory(mid: int) -> None:
    conn = get_conn()
    conn.execute("UPDATE coach_memory SET active=0 WHERE id=?", (mid,))
    conn.commit()
    conn.close()
