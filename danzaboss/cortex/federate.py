"""L2/L3 project + L4/L5 global federation (C6).

Precedence (spec §16 Q2, user-approved): PROJECT TRUTH WINS. A global
observation that near-duplicates a project observation (same type, similar
title or link bag — the same fingerprint upsert uses for merging) is shadowed
out of every read path. Cross-project knowledge surfaces only where the
project has no counterpart of its own.

Writes route by layer: <= 3 stays in the repo store, >= 4 goes to the shared
global store. Concurrency on the shared store (spec §16 Q4, user-approved):
WAL + busy_timeout on SQLite / native transactions on Postgres,
last-writer-wins at row level — safe because evolution history is append-only
and merges are monotonic. No locking layer.
"""
from __future__ import annotations

from typing import Optional

from .observation import Observation
from .ports import Query, Scored, StorageBackend
from .store import ObservationStore, _jaccard, _tokens, _utcnow

GLOBAL_LAYER = 4          # first layer that lives in the shared store
SHADOW_THRESHOLD = 0.5    # same bar as ObservationStore.merge_threshold


def _shadowed(g: Observation, local: list[Observation]) -> bool:
    """True when a live project observation makes the global one redundant."""
    g_title, g_links = _tokens(g.title), g.link_bag()
    for loc in local:
        if loc.type != g.type or loc.superseded_by:
            continue
        if _jaccard(_tokens(loc.title), g_title) >= SHADOW_THRESHOLD:
            return True
        if _jaccard(loc.link_bag(), g_links) >= SHADOW_THRESHOLD:
            return True
    return False


class FederatedBackend:
    """StorageBackend over (project, global). The project filter applies to
    the project store only — global rows are cross-project by definition.
    Rows in the global store below GLOBAL_LAYER are ignored: they can only
    get there by misuse, and surfacing them would bypass repo scoping."""

    def __init__(self, project: "StorageBackend", global_: "StorageBackend"):
        self.project = project
        self.global_ = global_

    def all(self, project: Optional[str] = None) -> list[Observation]:
        local = self.project.all(project)
        merged = list(local)
        for g in self.global_.all():
            if g.layer >= GLOBAL_LAYER and not _shadowed(g, local):
                merged.append(g)
        return merged

    def get(self, obs_id: str) -> Optional[Observation]:
        return self.project.get(obs_id) or self.global_.get(obs_id)

    def put(self, obs: Observation) -> None:
        # Residency wins over layer: updates (record_use, learn, age) must land
        # where the row actually lives, or a legacy layer>=4 row in the project
        # DB would fork into a shadowed global twin and its usage would vanish.
        if self.project.get(obs.id):
            self.project.put(obs)
        elif self.global_.get(obs.id):
            self.global_.put(obs)
        else:
            target = self.global_ if obs.layer >= GLOBAL_LAYER else self.project
            target.put(obs)

    def delete(self, obs_id: str) -> None:
        if self.project.get(obs_id):
            self.project.delete(obs_id)
        else:
            self.global_.delete(obs_id)

    def search(self, text: str, project: Optional[str] = None,
               limit: int = 10) -> list[Observation]:
        local = self.project.search(text, project=project, limit=limit)
        seen = {o.id for o in local}
        local_all = self.project.all(project)
        globals_ = [g for g in self.global_.search(text, limit=limit)
                    if g.id not in seen and g.layer >= GLOBAL_LAYER
                    and not _shadowed(g, local_all)]
        # Global knowledge must not be starved when weak local matches already
        # fill the limit: trim the local tail (weakest BM25 ranks) to make room.
        if globals_:
            local = local[:max(0, limit - len(globals_))]
        return (local + globals_)[:limit]

    def log_use(self, obs_id: str, ts: str, source: str = "") -> None:
        target = self.project if self.project.get(obs_id) else self.global_
        target.log_use(obs_id, ts, source)

    def usage_log(self, limit: int = 1000) -> list[dict]:
        rows = self.project.usage_log(limit) + self.global_.usage_log(limit)
        rows.sort(key=lambda r: r["ts"], reverse=True)
        return rows[:limit]


class FederatedStore:
    """Duck-types ObservationStore. Reads (get/query/record_use and everything
    retrieve/inject/learn reach through .backend) see both stores with L2
    precedence; upsert routes whole observations by layer so each store's own
    merge logic only ever sees its own rows."""

    def __init__(self, project_store: ObservationStore,
                 global_store: ObservationStore):
        self.project_store = project_store
        self.global_store = global_store
        self.backend = FederatedBackend(project_store.backend,
                                        global_store.backend)
        self._reader = ObservationStore(self.backend)

    def upsert(self, obs: Observation) -> Observation:
        target = (self.global_store if obs.layer >= GLOBAL_LAYER
                  else self.project_store)
        other = (self.project_store if target is self.global_store
                 else self.global_store)
        # Cross-store supersession: the old row may live in the other store;
        # mark it there so the replacement is not shadowed by its predecessor.
        if obs.supersedes and target.backend.get(obs.supersedes) is None:
            old = other.backend.get(obs.supersedes)
            if old:
                old.superseded_by = obs.id
                old.history.append({"ts": _utcnow(), "event": "superseded_by",
                                    "id": obs.id})
                other.backend.put(old)
        return target.upsert(obs)

    def get(self, obs_id: str) -> Optional[Observation]:
        return self._reader.get(obs_id)

    def record_use(self, obs_id: str, source: str = "",
                   now: Optional[str] = None) -> None:
        self._reader.record_use(obs_id, source, now)

    def query(self, q: Query) -> list[Scored]:
        return self._reader.query(q)

    def age(self, now: Optional[str] = None) -> dict:
        a = self.project_store.age(now)
        b = self.global_store.age(now)
        return {"archived": a["archived"] + b["archived"],
                "kept": a["kept"] + b["kept"]}
