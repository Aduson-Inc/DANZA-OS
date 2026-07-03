"""SQLite storage adapter for CORTEX (ADR-005 default, stdlib sqlite3).

Local-first, zero-config. List/dict fields are JSON-encoded columns. This adapter
is deliberately dumb: all evolution/merge/scoring logic lives in the store, so a
Postgres/Neon adapter only needs to reimplement these four methods.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import fields
from typing import Optional

from .observation import Observation
from .ports import StorageBackend

_LIST_FIELDS = {"tags", "concepts", "files", "symbols", "dependencies",
                "related_observations", "related_docs", "related_commits",
                "related_issues", "evidence", "when_relevant", "when_not_relevant",
                "history"}

_QUERY_TOKEN = re.compile(r"[A-Za-z0-9_]+")


class SqliteBackend(StorageBackend):
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        # check_same_thread False so a background extractor thread can share it
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        cols = ", ".join(f'"{f.name}" TEXT' for f in fields(Observation) if f.name != "id")
        self.conn.execute(f"CREATE TABLE IF NOT EXISTS observations (id TEXT PRIMARY KEY, {cols})")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_project ON observations(project)")
        self.conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5("
            "obs_id UNINDEXED, title, summary, tags, concepts, "
            "tokenize='porter unicode61')")
        self.conn.commit()

    @staticmethod
    def _encode(obs: Observation) -> dict:
        row = obs.to_row()
        for k in _LIST_FIELDS:
            row[k] = json.dumps(row[k])
        return row

    @staticmethod
    def _decode(row: sqlite3.Row) -> Observation:
        data = dict(row)
        data.pop("id_dup", None)
        for k in _LIST_FIELDS:
            data[k] = json.loads(data[k]) if data.get(k) else []
        # ints
        data["confidence"] = int(data["confidence"])
        data["layer"] = int(data["layer"])
        data["usage_count"] = int(data["usage_count"])
        return Observation(**data)

    def put(self, obs: Observation) -> None:
        row = self._encode(obs)
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
        return self._decode(r) if r else None

    def delete(self, obs_id: str) -> None:
        self.conn.execute("DELETE FROM observations WHERE id = ?", (obs_id,))
        self.conn.execute("DELETE FROM observations_fts WHERE obs_id = ?", (obs_id,))
        self.conn.commit()

    def all(self, project: Optional[str] = None) -> list[Observation]:
        if project:
            cur = self.conn.execute("SELECT * FROM observations WHERE project = ?", (project,))
        else:
            cur = self.conn.execute("SELECT * FROM observations")
        return [self._decode(r) for r in cur.fetchall()]

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
        return [self._decode(r) for r in rows]
