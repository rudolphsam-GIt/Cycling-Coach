import sqlite3
import os
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
    notes TEXT
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
    notes TEXT
);

CREATE TABLE IF NOT EXISTS ai_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    context_snapshot TEXT
);
"""


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
    ]:
        try:
            conn.execute(col_sql)
            conn.commit()
        except Exception:
            pass
    conn.close()
