"""CORTEX storage ports — the adapter backbone (ADR-005).

The store logic never talks to a database directly; it talks to a StorageBackend
port. SQLite is the local default adapter; a Neon/Postgres adapter can be dropped
in later behind the same interface without changing store.py. This is what makes
DANZA multi-DB / multi-stack.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from .observation import Observation


@dataclass
class Query:
    """A retrieval request against the observation store."""
    text: str = ""
    project: Optional[str] = None
    types: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    intent: Optional[str] = None          # drives anti-relevance matching
    entities: list[str] = field(default_factory=list)  # extracted from the prompt
    limit: int = 10
    include_archived: bool = False


@dataclass
class Scored:
    observation: Observation
    score: float
    reasons: list[str] = field(default_factory=list)  # explainability


class StorageBackend(Protocol):
    """Persistence port. Implementations: SqliteBackend (default), NeonBackend (C6)."""
    def put(self, obs: Observation) -> None: ...
    def get(self, obs_id: str) -> Optional[Observation]: ...
    def delete(self, obs_id: str) -> None: ...
    def all(self, project: Optional[str] = None) -> list[Observation]: ...
    def search(self, text: str, project: Optional[str] = None,
               limit: int = 10) -> list[Observation]: ...
    def log_use(self, obs_id: str, ts: str, source: str = "") -> None: ...
    def usage_log(self, limit: int = 1000) -> list[dict]: ...
