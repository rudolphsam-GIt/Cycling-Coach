import json
import sqlite3
import os
import threading
from contextlib import contextmanager
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_wellness (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE NOT NULL,
    legs_feel INTEGER,
    energy INTEGER,
    sleep_hours REAL,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ftp_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    ftp_watts INTEGER NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT UNIQUE,
    date TEXT NOT NULL,
    name TEXT,
    sport_type TEXT,
    duration_seconds INTEGER,
    elapsed_seconds INTEGER,
    distance_meters REAL,
    elevation_gain_meters REAL,
    avg_power_watts REAL,
    avg_hr INTEGER,
    max_hr INTEGER,
    normalized_power REAL,
    tss REAL,
    if_value REAL,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS athlete_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    name TEXT NOT NULL,
    workout_type TEXT,
    description TEXT,
    structured_json TEXT,
    tss_planned REAL,
    completed INTEGER DEFAULT 0,
    activity_id INTEGER,
    notes TEXT,
    phase TEXT,
    week_number INTEGER
);

CREATE TABLE IF NOT EXISTS races (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    date TEXT NOT NULL,
    distance_km REAL,
    elevation_gain_meters REAL,
    category TEXT,
    target_time_seconds INTEGER,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS strength_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    plan_week INTEGER,
    exercises_json TEXT,
    completed INTEGER DEFAULT 0,
    duration_minutes INTEGER,
    notes TEXT,
    phase TEXT
);

CREATE TABLE IF NOT EXISTS recovery_daily (
    date TEXT PRIMARY KEY,
    sleep_hours REAL,
    sleep_score INTEGER,
    hrv_ms REAL,
    hrv_status TEXT,
    resting_hr INTEGER,
    readiness INTEGER,
    body_battery INTEGER,
    synced_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coach_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    ref_key TEXT NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(kind, ref_key)
);

CREATE TABLE IF NOT EXISTS coach_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS activity_peaks (
    activity_id INTEGER NOT NULL,
    duration_s INTEGER NOT NULL,
    watts REAL NOT NULL,
    PRIMARY KEY (activity_id, duration_s)
);

CREATE TABLE IF NOT EXISTS activity_streams (
    activity_id INTEGER PRIMARY KEY,
    data TEXT NOT NULL,
    source TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS external_sync (
    service TEXT NOT NULL,             -- intervals or trainingpeaks
    workout_id INTEGER NOT NULL,
    remote_id TEXT,
    date TEXT NOT NULL,
    fingerprint TEXT,
    pushed_at TEXT NOT NULL,
    PRIMARY KEY (service, workout_id)
);

CREATE TABLE IF NOT EXISTS programs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    status TEXT NOT NULL,              -- draft, active, archived or discarded
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    content_json TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    executed_at TEXT
);

CREATE TABLE IF NOT EXISTS plan_phases (
    phase TEXT PRIMARY KEY,
    focus TEXT,
    why TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_hr_peaks (
    activity_id INTEGER NOT NULL,
    duration_s INTEGER NOT NULL,
    bpm REAL NOT NULL,
    PRIMARY KEY (activity_id, duration_s)
);

CREATE TABLE IF NOT EXISTS ai_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    context_snapshot TEXT
);
"""

# Date lookups drive nearly every page, so index them. Created after the
# ALTER TABLE block so older databases have every column first.
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_activities_date ON activities(date);
CREATE INDEX IF NOT EXISTS idx_workouts_date ON workouts(date);
CREATE INDEX IF NOT EXISTS idx_workouts_activity ON workouts(activity_id);
CREATE INDEX IF NOT EXISTS idx_strength_date ON strength_sessions(date);
CREATE INDEX IF NOT EXISTS idx_races_date ON races(date);
CREATE INDEX IF NOT EXISTS idx_programs_status ON programs(status);
"""


# Which athlete's database a call uses. DB_PATH is the owner's (Sam's) file. Another athlete's
# profile is chosen per browser session (session_state["db_path"], set in app.py), and a
# background thread pins the path it started with via use(), so a profile switch mid sync
# never sends its writes to the wrong athlete.
_local = threading.local()


def _session_path() -> str | None:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx(suppress_warning=True)
        if ctx is None:
            return None
        ss = ctx.session_state
        return ss["db_path"] if "db_path" in ss else None
    except Exception:
        return None


def current_path() -> str:
    return getattr(_local, "path", None) or _session_path() or DB_PATH


def is_owner() -> bool:
    """True on the owner's own profile. Garmin, Strava, TrainingPeaks and intervals.icu
    connect only there."""
    return os.path.abspath(current_path()) == os.path.abspath(DB_PATH)


@contextmanager
def use(path: str):
    """Pin this thread to one athlete's database for the block."""
    old = getattr(_local, "path", None)
    _local.path = path
    try:
        yield
    finally:
        _local.path = old


def get_conn():
    path = current_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def run_migrations():
    conn = get_conn()
    conn.executescript(SCHEMA)
    # Add elapsed_seconds column if it doesn't exist yet (existing installs)
    for col_sql in [
        "ALTER TABLE activities ADD COLUMN elapsed_seconds INTEGER",
        "ALTER TABLE activities ADD COLUMN zone_time_json TEXT",
        "ALTER TABLE races ADD COLUMN placing INTEGER",
        "ALTER TABLE races ADD COLUMN field_size INTEGER",
        "ALTER TABLE races ADD COLUMN finish_time_seconds INTEGER",
        "ALTER TABLE races ADD COLUMN race_avg_power INTEGER",
        "ALTER TABLE races ADD COLUMN race_avg_hr INTEGER",
        "ALTER TABLE races ADD COLUMN legs_feel INTEGER",
        "ALTER TABLE races ADD COLUMN result_notes TEXT",
        "ALTER TABLE races ADD COLUMN result_logged INTEGER DEFAULT 0",
        "ALTER TABLE workouts ADD COLUMN garmin_workout_id TEXT",
        "ALTER TABLE workouts ADD COLUMN garmin_schedule_id TEXT",
        "ALTER TABLE workouts ADD COLUMN garmin_sent_at TEXT",
        "ALTER TABLE workouts ADD COLUMN phase TEXT",
        "ALTER TABLE workouts ADD COLUMN week_number INTEGER",
        "ALTER TABLE strength_sessions ADD COLUMN phase TEXT",
        "ALTER TABLE workouts ADD COLUMN purpose TEXT",
        "ALTER TABLE workouts ADD COLUMN feel TEXT",
        "ALTER TABLE strength_sessions ADD COLUMN purpose TEXT",
        "ALTER TABLE activities ADD COLUMN tss_locked INTEGER DEFAULT 0",
        "ALTER TABLE activities ADD COLUMN edited INTEGER DEFAULT 0",
        "ALTER TABLE activities ADD COLUMN original_json TEXT",
        "ALTER TABLE activities ADD COLUMN timer_seconds INTEGER",
        "ALTER TABLE activities ADD COLUMN tss_source TEXT",
        "ALTER TABLE activities ADD COLUMN tp_json TEXT",
        "ALTER TABLE activities ADD COLUMN ref_json TEXT",
    ]:
        try:
            conn.execute(col_sql)
            conn.commit()
        except Exception:
            pass
    # Scores once copied from TrainingPeaks are worked out by the app again (it now scores heart
    # rate the TrainingPeaks way itself); TrainingPeaks' numbers are kept only to compare.
    conn.execute("UPDATE activities SET tss_source=NULL, tss=NULL WHERE tss_source='trainingpeaks'")
    # Numbers from other services now live together in ref_json, keyed by service.
    for row in conn.execute("SELECT id, tp_json, ref_json FROM activities WHERE tp_json IS NOT NULL").fetchall():
        try:
            ref = json.loads(row[2]) if row[2] else {}
            ref.setdefault("trainingpeaks", json.loads(row[1]))
        except (TypeError, ValueError, AttributeError):
            continue
        conn.execute("UPDATE activities SET ref_json=?, tp_json=NULL WHERE id=?", (json.dumps(ref), row[0]))
    conn.commit()
    conn.executescript(INDEXES)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.close()
