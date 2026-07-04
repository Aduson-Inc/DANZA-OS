"""SQLite storage adapter for CORTEX (ADR-005 default, stdlib sqlite3).

Local-first, zero-config. List/dict fields are JSON-encoded columns. This adapter
is deliberately dumb: all evolution/merge/scoring logic lives in the store, so a
Postgres/Neon adapter only needs to reimplement these four methods.
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Optional

from .codec import COLUMNS, decode_row, encode_row
from .observation import Observation
from .ports import StorageBackend

_QUERY_TOKEN = re.compile(r"[A-Za-z0-9_]+")


class SqliteBackend(StorageBackend):
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        # check_same_thread False so a background extractor thread can share it
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # C6: the global store (~/.danza/cortex/global.db) is shared by every
        # repo's sessions — WAL + busy_timeout let concurrent writers queue
        # instead of erroring (spec §16 Q4 stance: no locking layer).
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        cols = ", ".join(f'"{c}" TEXT' for c in COLUMNS if c != "id")
        self.conn.execute(f"CREATE TABLE IF NOT EXISTS observations (id TEXT PRIMARY KEY, {cols})")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_project ON observations(project)")
        self.conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5("
            "obs_id UNINDEXED, title, summary, tags, concepts, "
            "tokenize='porter unicode61')")
        # C5: replayable usage log — the learning engine's training signal
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS usage_log ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, obs_id TEXT NOT NULL, "
            "ts TEXT NOT NULL, source TEXT DEFAULT '')")
        self.conn.commit()

    def put(self, obs: Observation) -> None:
        row = encode_row(obs)
        names = list(row.keys())
        placeholders = ", ".join("?" for _ in names)
        cols = ", ".join(f'"{n}"' for n in names)
        self.conn.execute(
            f"INSERT OR REPLACE INTO observations ({cols}) VALUES ({placeholders})",
            [row[n] for n in names])
        self.conn.execute("DELETE FROM observations_fts WHERE obs_id = ?", (obs.id,))
        self.conn.execute(
            "INSERT INTO observations_fts (obs_id, title, summary, tags, concepts) "
            "VALUES (?, ?, ?, ?, ?)",
            (obs.id, obs.title, obs.summary, " ".join(obs.tags), " ".join(obs.concepts)))
        self.conn.commit()

    def get(self, obs_id: str) -> Optional[Observation]:
        cur = self.conn.execute("SELECT * FROM observations WHERE id = ?", (obs_id,))
        r = cur.fetchone()
        return decode_row(r) if r else None

    def delete(self, obs_id: str) -> None:
        self.conn.execute("DELETE FROM observations WHERE id = ?", (obs_id,))
        self.conn.execute("DELETE FROM observations_fts WHERE obs_id = ?", (obs_id,))
        self.conn.commit()

    def log_use(self, obs_id: str, ts: str, source: str = "") -> None:
        self.conn.execute(
            "INSERT INTO usage_log (obs_id, ts, source) VALUES (?, ?, ?)",
            (obs_id, ts, source))
        self.conn.commit()

    def usage_log(self, limit: int = 1000) -> list[dict]:
        rows = self.conn.execute(
            "SELECT obs_id, ts, source FROM usage_log "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def all(self, project: Optional[str] = None) -> list[Observation]:
        if project:
            cur = self.conn.execute("SELECT * FROM observations WHERE project = ?", (project,))
        else:
            cur = self.conn.execute("SELECT * FROM observations")
        return [decode_row(r) for r in cur.fetchall()]

    def search(self, text: str, project: Optional[str] = None,
               limit: int = 10) -> list[Observation]:
        """BM25-ranked keyword search. Each token is quoted so user text can
        never inject FTS5 query syntax."""
        tokens = _QUERY_TOKEN.findall(text)
        if not tokens:
            return []
        match = " OR ".join(f'"{t}"' for t in tokens)
        sql = ("SELECT o.* FROM observations_fts f "
               "JOIN observations o ON o.id = f.obs_id "
               "WHERE observations_fts MATCH ?")
        params: list = [match]
        if project:
            sql += " AND o.project = ?"
            params.append(project)
        sql += " ORDER BY bm25(observations_fts) LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [decode_row(r) for r in rows]
