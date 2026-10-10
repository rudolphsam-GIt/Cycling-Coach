"""
Athlete profiles. Each athlete has their own database file, so nothing can mix between them.
The owner's file is config.DB_PATH (data/cycling.db) and never moves. Athletes you coach live
in data/profiles/<slug>.db next to it.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
from datetime import datetime

from db import schema

OWNER = "me"


def profiles_dir() -> str:
    return os.path.join(os.path.dirname(schema.DB_PATH), "profiles")


def backups_dir() -> str:
    return os.path.join(os.path.dirname(schema.DB_PATH), "backups")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:40] or "athlete"


def path_for(slug: str) -> str:
    if slug == OWNER:
        return schema.DB_PATH
    if slugify(slug) != slug:
        raise ValueError(f"Not a profile name: {slug!r}")
    return os.path.join(profiles_dir(), f"{slug}.db")


def _name_in(path: str) -> str:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT value FROM athlete_settings WHERE key IN "
                               "('athlete_name','strava_athlete_name') AND value != '' "
                               "ORDER BY key='athlete_name' DESC LIMIT 1").fetchone()
        finally:
            conn.close()
        return (row[0] or "").strip() if row else ""
    except sqlite3.Error:
        return ""


_names: dict = {}


def _cached_name(path: str) -> str:
    # Names only change when a file changes, so key them by modification time.
    try:
        stamp = max(os.path.getmtime(p) for p in (path, path + "-wal") if os.path.exists(p))
    except ValueError:
        return ""
    hit = _names.get(path)
    if hit and hit[0] == stamp:
        return hit[1]
    name = _name_in(path)
    _names[path] = (stamp, name)
    return name


def owner_name() -> str:
    """The owner's name, as saved in their own database."""
    return _cached_name(schema.DB_PATH) or "the coach"


def list_profiles() -> list[dict]:
    """The owner first, then coached athletes by name. Each is {slug, name, path, owner}."""
    out = [{"slug": OWNER, "name": _cached_name(schema.DB_PATH) or "Me", "path": schema.DB_PATH,
            "owner": True}]
    folder = profiles_dir()
    others = []
    if os.path.isdir(folder):
        for fn in os.listdir(folder):
            if fn.endswith(".db"):
                slug = fn[:-3]
                path = os.path.join(folder, fn)
                others.append({"slug": slug, "name": _cached_name(path) or slug.replace("-", " ").title(),
                               "path": path, "owner": False})
    return out + sorted(others, key=lambda p: p["name"].lower())


def create_profile(name: str) -> dict:
    """Make a new, migrated database for an athlete and save their name in it."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Give the athlete a name.")
    base = slugify(name)
    slug, n = base, 2
    if base == OWNER:
        slug = f"{base}-2"
    while os.path.exists(path_for(slug)):
        slug, n = f"{base}-{n}", n + 1
    path = path_for(slug)
    os.makedirs(profiles_dir(), exist_ok=True)
    with schema.use(path):
        schema.run_migrations()
        from db.queries import set_setting
        set_setting("athlete_name", name)
    return {"slug": slug, "name": name, "path": path, "owner": False}


def delete_profile(slug: str) -> str:
    """Move an athlete's database to data/backups (never deleted outright). The owner's
    profile can't be removed. Returns where the file went."""
    if slug == OWNER:
        raise ValueError("Your own profile can't be removed.")
    path = path_for(slug)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    os.makedirs(backups_dir(), exist_ok=True)
    dest = os.path.join(backups_dir(), f"profile-{slug}-{datetime.now():%Y%m%d-%H%M%S}.db")
    shutil.move(path, dest)
    for extra in ("-wal", "-shm"):
        if os.path.exists(path + extra):
            shutil.move(path + extra, dest + extra)
    return dest
