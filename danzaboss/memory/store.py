"""Layered memory subsystem — DANZABOSS Upgrade #7.

Consolidates the overlapping flat markdown memory files (decision-log, turn-log,
build-history, patterns, rankings, checkpoints) into three clearly-scoped stores
plus a hot working set, with token-budgeted retrieval so agents load only the
slices they need (serves the "avoid token overload" goal).

Scopes (industry-standard 2026 model):
  * semantic   : durable facts & patterns (was: patterns.md, parts of system-map)
  * episodic   : time-ordered events & decisions (was: decision-log, turn-log, build-history)
  * procedural : learned rules & build orders (was: build-orders, constitution-derived rules)

Design: append-only event log per scope (audit-safe, matches Constitution Rule 36),
with a keyword+recency retrieval that returns a *bounded* set of records so the
compiled context never blows the budget. No vector DB dependency — a deterministic
scorer keeps it stdlib-only and reproducible; the interface is built so a vector
backend could be dropped in later.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from dataclasses import dataclass, asdict, field
from typing import Iterable, Optional

SCOPES = ("semantic", "episodic", "procedural")
_WORD = re.compile(r"[a-z0-9]+")


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


@dataclass
class MemoryRecord:
    scope: str
    text: str
    tags: list[str] = field(default_factory=list)
    ts: str = field(default_factory=_utcnow)
    # rough token estimate for budgeting (~4 chars/token heuristic)
    def est_tokens(self) -> int:
        return max(1, len(self.text) // 4)


class MemoryStore:
    """One append-only JSONL file per scope under ``root``.

    Replaces six overlapping files with three owners, each single-responsibility.
    """

    def __init__(self, root: str):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, scope: str) -> str:
        if scope not in SCOPES:
            raise ValueError(f"unknown scope {scope!r}; use one of {SCOPES}")
        return os.path.join(self.root, f"{scope}.jsonl")

    # -- write (append-only) --------------------------------------------------
    def remember(self, scope: str, text: str, tags: Optional[list[str]] = None) -> MemoryRecord:
        rec = MemoryRecord(scope=scope, text=text, tags=tags or [])
        with open(self._path(scope), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(rec)) + "\n")
        return rec

    # -- read -----------------------------------------------------------------
    def _load(self, scope: str) -> list[MemoryRecord]:
        p = self._path(scope)
        if not os.path.exists(p):
            return []
        out = []
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(MemoryRecord(**json.loads(line)))
        return out

    def _score(self, rec: MemoryRecord, query_tokens: set[str], now_rank: int, idx: int) -> float:
        """Deterministic relevance: keyword overlap + tag hits + recency."""
        rec_tokens = _tokens(rec.text) | {t.lower() for t in rec.tags}
        overlap = len(query_tokens & rec_tokens)
        tag_bonus = 2 * len(query_tokens & {t.lower() for t in rec.tags})
        recency = idx / max(1, now_rank)  # newer records score higher (0..1)
        return overlap + tag_bonus + recency

    def retrieve(self, query: str, *, scopes: Iterable[str] = SCOPES,
                 token_budget: int = 1500, max_records: int = 20) -> list[MemoryRecord]:
        """Return the highest-scoring records across scopes, bounded by both a
        record count and a token budget. This is the anti-overload guarantee."""
        query_tokens = _tokens(query)
        scored: list[tuple[float, MemoryRecord]] = []
        for scope in scopes:
            records = self._load(scope)
            n = len(records)
            for i, rec in enumerate(records):
                scored.append((self._score(rec, query_tokens, n, i), rec))
        scored.sort(key=lambda x: x[0], reverse=True)

        chosen: list[MemoryRecord] = []
        used = 0
        for _, rec in scored:
            if len(chosen) >= max_records:
                break
            if used + rec.est_tokens() > token_budget:
                continue
            chosen.append(rec)
            used += rec.est_tokens()
        return chosen

    def stats(self) -> dict[str, int]:
        return {scope: len(self._load(scope)) for scope in SCOPES}
