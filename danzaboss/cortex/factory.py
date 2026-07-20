"""Store factory (C6) — the one place that decides where memory lives.

Project store (L0-L3): <repo>/.danza/cortex/cortex.db — SQLite, always.
Global store (L4/L5):  DANZA_CORTEX_GLOBAL_DSN -> Neon/Postgres (VPS, shared)
                       DANZA_CORTEX_GLOBAL_DB  -> SQLite at that path
                       default                 -> ~/.danza/cortex/global.db

The DSN path fails closed with a clear message when the optional psycopg
driver is missing; the hook entry points wrap store access in their own
fail-open guard so a misconfigured global store can never brick a session.
"""
from __future__ import annotations

import os

from .sqlite_backend import SqliteBackend
from .store import ObservationStore

GLOBAL_DSN_ENV = "DANZA_CORTEX_GLOBAL_DSN"
GLOBAL_DB_ENV = "DANZA_CORTEX_GLOBAL_DB"


def db_path(root: str) -> str:
    return os.path.join(root, ".danza", "cortex", "cortex.db")


def global_db_path() -> str:
    return os.environ.get(GLOBAL_DB_ENV) or os.path.join(
        os.path.expanduser("~"), ".danza", "cortex", "global.db")


def open_project_store(root: str) -> ObservationStore:
    return ObservationStore(SqliteBackend(db_path(root)))


def open_global_store() -> ObservationStore:
    dsn = os.environ.get(GLOBAL_DSN_ENV, "")
    if dsn:
        from .neon_backend import NeonBackend  # optional driver — lazy
        return ObservationStore(NeonBackend(dsn))
    return ObservationStore(SqliteBackend(global_db_path()))


def open_store(root: str) -> ObservationStore:
    """Return the authoritative project-local CORTEX store.

    Global stores remain available only through the explicit
    ``open_global_store`` development/tooling API. Runtime hooks, UI, MCP,
    retrieval, and agent context all use this project-only path so one project
    can never read or write another project's memory.
    """
    return open_project_store(root)
