"""CORTEX raw capture — sessions + events tables with a redaction filter (C1).

Tier-0 of the write path: hook handlers append one row per tool event, nothing
here calls an LLM. Secrets are redacted BEFORE storage so they can never become
memory (spec section 13). The Stop-gate and the floor extractor read from here.

Stdlib only.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sqlite3
from typing import Optional

_REDACTION_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),                    # provider-style API keys
    re.compile(r"AKIA[0-9A-Z]{16}"),                           # AWS access key id
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),          # bearer tokens
    re.compile(r"(?i)(password|passwd|pwd|secret|token|api_?key)\s*[=:]\s*\S+"),
    re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^@\s]+@"),     # url with user:pass@
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]


def redact(text: str) -> str:
    """Replace secret-shaped substrings so they never reach the store."""
    for pat in _REDACTION_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class CaptureLog:
    """Sessions + raw tool events for one project store (repo-scoped DB)."""

    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, project TEXT NOT NULL, environment TEXT DEFAULT '',
            started_at TEXT NOT NULL, ended_at TEXT,
            prompt_count INTEGER DEFAULT 0, observations_written INTEGER DEFAULT 0,
            gate_blocked INTEGER DEFAULT 0, status TEXT DEFAULT 'active')""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
            ts TEXT NOT NULL, tool TEXT NOT NULL, file_path TEXT DEFAULT '',
            command TEXT DEFAULT '', outcome TEXT DEFAULT '', excerpt TEXT DEFAULT '',
            processed INTEGER DEFAULT 0)""")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, processed)")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS context_reads (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
            project TEXT NOT NULL, driver TEXT NOT NULL,
            tokens INTEGER NOT NULL, budget INTEGER NOT NULL,
            adaptation TEXT NOT NULL DEFAULT '{}')""")
        context_read_columns = {
            row["name"] for row in self.conn.execute(
                "PRAGMA table_info(context_reads)").fetchall()
        }
        if "adaptation" not in context_read_columns:
            self.conn.execute(
                "ALTER TABLE context_reads ADD COLUMN adaptation "
                "TEXT NOT NULL DEFAULT '{}'")
        self.conn.commit()

    # -- sessions --------------------------------------------------------------
    def open_session(self, session_id: str, project: str, environment: str = "") -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO sessions (id, project, environment, started_at) "
            "VALUES (?, ?, ?, ?)", (session_id, project, environment, _utcnow()))
        self.conn.commit()

    def end_session(self, session_id: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET ended_at = ?, status = 'completed' WHERE id = ?",
            (_utcnow(), session_id))
        self.conn.commit()

    def session(self, session_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM sessions WHERE id = ?",
                                (session_id,)).fetchone()
        return dict(row) if row else None

    def note_observations(self, session_id: str, n: int = 1) -> None:
        self.conn.execute(
            "UPDATE sessions SET observations_written = observations_written + ? "
            "WHERE id = ?", (n, session_id))
        self.conn.commit()

    def mark_gate_blocked(self, session_id: str) -> None:
        self.conn.execute("UPDATE sessions SET gate_blocked = 1 WHERE id = ?",
                          (session_id,))
        self.conn.commit()

    # -- events ----------------------------------------------------------------
    def record_event(self, session_id: str, tool: str, file_path: str = "",
                     command: str = "", outcome: str = "", excerpt: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO events (session_id, ts, tool, file_path, command, outcome, excerpt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, _utcnow(), tool, file_path,
             redact(command), redact(outcome), redact(excerpt)))
        self.conn.commit()
        return int(cur.lastrowid)

    def pending(self, session_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE session_id = ? AND processed = 0 ORDER BY id",
            (session_id,)).fetchall()
        return [dict(r) for r in rows]

    def mark_processed(self, session_id: str) -> int:
        cur = self.conn.execute(
            "UPDATE events SET processed = 1 WHERE session_id = ? AND processed = 0",
            (session_id,))
        self.conn.commit()
        return cur.rowcount

    # -- context reads (P4 T11 telemetry) ----------------------------------------
    def record_context_read(self, project: str, driver: str,
                            tokens: int, budget: int,
                            adaptation: Optional[dict] = None) -> int:
        """One driver-context compile: what `driver` just read vs its cap.
        The compile seat is the only path every driver context passes, so
        this table is the per-agent spend ledger the dashboard renders."""
        encoded = json.dumps(
            adaptation or {}, sort_keys=True, separators=(",", ":"))
        cur = self.conn.execute(
            "INSERT INTO context_reads "
            "(ts, project, driver, tokens, budget, adaptation) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_utcnow(), project, driver, int(tokens), int(budget), encoded))
        self.conn.commit()
        return int(cur.lastrowid)

    def context_read_stats(self, project: str) -> dict:
        """Per-driver context spend: {driver: {"reads": n, "tokens": n}}."""
        rows = self.conn.execute(
            "SELECT driver, COUNT(*) reads, COALESCE(SUM(tokens), 0) tokens "
            "FROM context_reads WHERE project = ? GROUP BY driver",
            (project,)).fetchall()
        return {r["driver"]: {"reads": r["reads"], "tokens": r["tokens"]}
                for r in rows}

    # -- stats -----------------------------------------------------------------
    def stats(self, project: Optional[str] = None) -> dict:
        if project:
            sess = self.conn.execute(
                "SELECT COUNT(*) c FROM sessions WHERE project = ?", (project,)).fetchone()["c"]
            base = ("SELECT COUNT(*) c FROM events e JOIN sessions s ON e.session_id = s.id "
                    "WHERE s.project = ?")
            events = self.conn.execute(base, (project,)).fetchone()["c"]
            pending = self.conn.execute(base + " AND e.processed = 0", (project,)).fetchone()["c"]
            obs = self.conn.execute(
                "SELECT COALESCE(SUM(observations_written), 0) c FROM sessions "
                "WHERE project = ?", (project,)).fetchone()["c"]
        else:
            sess = self.conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"]
            events = self.conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
            pending = self.conn.execute(
                "SELECT COUNT(*) c FROM events WHERE processed = 0").fetchone()["c"]
            obs = self.conn.execute(
                "SELECT COALESCE(SUM(observations_written), 0) c FROM sessions").fetchone()["c"]
        return {"sessions": sess, "events": events, "pending_events": pending,
                "observations_written": obs}
