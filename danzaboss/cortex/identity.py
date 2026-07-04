"""Stable project identity — CORTEX.

The project name scopes every observation, session, and graph row in the
repo-local store. Deriving it from the directory basename alone broke
silently when the repo directory was renamed ("DANZA OS" -> "DANZA-OS"):
every scoped query filtered out all existing rows while the data sat intact.

Identity is therefore pinned in a marker file next to the DB
(`.danza/cortex/project.json`, gitignored like the DB it describes) and the
store self-heals exactly once: if no marker exists but the DB already holds
rows under a different project name, those rows are migrated to the current
name before the marker is written. The DB is repo-scoped by construction,
so every row in it belongs to this repo regardless of what the directory
was called when the row was written.

Resolution fails open (falls back to the basename) — a broken marker or a
locked DB must never crash a capture hook.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Optional

# Tables that carry a `project` column and must follow a rename.
_SCOPED_TABLES = ("observations", "sessions", "graph_nodes")


def marker_path(root: str) -> str:
    return os.path.join(root, ".danza", "cortex", "project.json")


def _db_path(root: str) -> str:
    return os.path.join(root, ".danza", "cortex", "cortex.db")


def _read_marker(root: str) -> Optional[str]:
    try:
        with open(marker_path(root), "r", encoding="utf-8") as fh:
            name = json.load(fh).get("project", "")
        return name or None
    except (OSError, ValueError):
        return None


def _write_marker(root: str, project: str) -> None:
    path = marker_path(root)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"project": project}, fh)
    except OSError:
        pass  # fail open: identity still resolves, just un-pinned this run


def migrate_project(root: str, project: str) -> dict:
    """Point every scoped row in the repo DB at `project`.

    Idempotent; returns per-table counts of rows moved. The DB is
    repo-scoped, so rows under any other name are strays from a previous
    directory name, never another project's data.
    """
    moved = {t: 0 for t in _SCOPED_TABLES}
    db = _db_path(root)
    if not os.path.exists(db):
        return moved
    conn = sqlite3.connect(db)
    try:
        existing = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table in _SCOPED_TABLES:
            if table in existing:
                cur = conn.execute(
                    f"UPDATE {table} SET project = ? WHERE project != ?",
                    (project, project))
                moved[table] = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return moved


def resolve_project(root: str) -> str:
    """Return the pinned project name for `root`, healing a rename once."""
    root = os.path.abspath(root)
    pinned = _read_marker(root)
    if pinned:
        return pinned
    name = os.path.basename(root)
    try:
        migrate_project(root, name)
    except sqlite3.Error:
        return name  # fail open: unscoped basename beats a crashed hook
    _write_marker(root, name)
    return name
