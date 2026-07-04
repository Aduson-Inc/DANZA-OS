"""Postgres/Neon storage adapter for CORTEX (C6, ADR-005).

Same dumb-adapter discipline as SqliteBackend: evolution/merge/scoring live in
the store; this module only persists. The engine stays stdlib-only (design D7)
— psycopg is imported lazily and required only when this adapter is actually
constructed; every other CORTEX path runs without it.

Search parity: SQLite runs FTS5 (porter) over OR-joined quoted tokens; here
the same sanitized tokens feed websearch_to_tsquery('english', ...) — snowball
stemming, immune to query-syntax injection by construction — against a stored
tsvector generated from title/summary/tags/concepts.
"""
from __future__ import annotations

import re
from typing import Optional

from .codec import COLUMNS, decode_row, encode_row
from .observation import Observation

_QUERY_TOKEN = re.compile(r"[A-Za-z0-9_]+")


def driver_available() -> bool:
    """True when the optional psycopg driver is importable."""
    try:
        import psycopg  # noqa: F401
        return True
    except ImportError:
        return False


class NeonBackend:
    """StorageBackend adapter for Neon/any Postgres. DSN example:
    postgresql://user:pass@host/dbname?sslmode=require"""

    def __init__(self, dsn: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as e:
            raise RuntimeError(
                "NeonBackend requires the optional 'psycopg' driver "
                "(pip install 'psycopg[binary]'). The CORTEX engine itself "
                "is stdlib-only; only this adapter needs it.") from e
        self.conn = psycopg.connect(dsn, row_factory=dict_row)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        cols = ", ".join(f'"{c}" TEXT' for c in COLUMNS if c != "id")
        with self.conn.cursor() as cur:
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS observations "
                f"(id TEXT PRIMARY KEY, {cols})")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_obs_project "
                "ON observations(project)")
            cur.execute(
                "ALTER TABLE observations ADD COLUMN IF NOT EXISTS fts tsvector "
                "GENERATED ALWAYS AS (to_tsvector('english', "
                "coalesce(title, '') || ' ' || coalesce(summary, '') || ' ' || "
                "coalesce(tags, '') || ' ' || coalesce(concepts, ''))) STORED")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_obs_fts "
                "ON observations USING GIN (fts)")
            cur.execute(
                "CREATE TABLE IF NOT EXISTS usage_log ("
                "id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
                "obs_id TEXT NOT NULL, ts TEXT NOT NULL, source TEXT DEFAULT '')")
        self.conn.commit()

    def put(self, obs: Observation) -> None:
        row = encode_row(obs)
        names = list(row.keys())
        cols = ", ".join(f'"{n}"' for n in names)
        placeholders = ", ".join(["%s"] * len(names))
        updates = ", ".join(f'"{n}" = EXCLUDED."{n}"' for n in names if n != "id")
        with self.conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO observations ({cols}) VALUES ({placeholders}) "
                f"ON CONFLICT (id) DO UPDATE SET {updates}",
                [row[n] for n in names])
        self.conn.commit()

    def get(self, obs_id: str) -> Optional[Observation]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM observations WHERE id = %s", (obs_id,))
            r = cur.fetchone()
        return decode_row(r) if r else None

    def delete(self, obs_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM observations WHERE id = %s", (obs_id,))
        self.conn.commit()

    def all(self, project: Optional[str] = None) -> list[Observation]:
        with self.conn.cursor() as cur:
            if project:
                cur.execute("SELECT * FROM observations WHERE project = %s",
                            (project,))
            else:
                cur.execute("SELECT * FROM observations")
            rows = cur.fetchall()
        return [decode_row(r) for r in rows]

    def search(self, text: str, project: Optional[str] = None,
               limit: int = 10) -> list[Observation]:
        """Rank-ordered keyword search. Tokens are sanitized to \\w+ then fed
        to websearch_to_tsquery, which treats them as plain words — user text
        can never inject tsquery syntax (same guarantee as the SQLite path)."""
        tokens = _QUERY_TOKEN.findall(text)
        if not tokens:
            return []
        query = " OR ".join(tokens)
        sql = ("SELECT * FROM observations "
               "WHERE fts @@ websearch_to_tsquery('english', %s)")
        params: list = [query]
        if project:
            sql += " AND project = %s"
            params.append(project)
        sql += (" ORDER BY ts_rank(fts, websearch_to_tsquery('english', %s)) "
                "DESC LIMIT %s")
        params.extend([query, limit])
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [decode_row(r) for r in rows]

    def log_use(self, obs_id: str, ts: str, source: str = "") -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO usage_log (obs_id, ts, source) VALUES (%s, %s, %s)",
                (obs_id, ts, source))
        self.conn.commit()

    def usage_log(self, limit: int = 1000) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT obs_id, ts, source FROM usage_log "
                "ORDER BY id DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
        return [dict(r) for r in rows]
