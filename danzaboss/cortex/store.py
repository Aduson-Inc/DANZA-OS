"""CORTEX ObservationStore (L2) — DANZA cognitive memory (P1).

Owns evolution/merge on write and anti-relevance-aware scoring on read. All
persistence is delegated to a StorageBackend adapter (SQLite default; Neon later).

Two behaviours are the P1 acceptance criteria:
  1. upsert() MERGES a near-duplicate instead of inserting a second copy.
  2. query() applies when_not_relevant as a precision filter — an observation that
     is keyword-relevant but explicitly not-relevant to the intent is suppressed,
     measurably raising precision.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Optional

from .observation import Observation, Importance, ObsType
from .ports import StorageBackend, Query, Scored

_WORD = re.compile(r"[a-z0-9]+")


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


# importance -> ranking multiplier
_IMPORTANCE_WEIGHT = {
    Importance.CRITICAL.value: 2.0, Importance.HIGH.value: 1.5,
    Importance.MEDIUM.value: 1.0, Importance.LOW.value: 0.6,
    Importance.TEMPORARY.value: 0.4, Importance.ARCHIVE.value: 0.1,
}


class ObservationStore:
    def __init__(self, backend: StorageBackend, *, merge_threshold: float = 0.5):
        self.backend = backend
        self.merge_threshold = merge_threshold

    # -- write: evolve/merge, never blind-duplicate ---------------------------
    def upsert(self, obs: Observation) -> Observation:
        """Insert, or evolve an existing near-duplicate. Returns the stored obs."""
        if obs.supersedes:
            old = self.backend.get(obs.supersedes)
            if old:
                old.superseded_by = obs.id
                old.history.append({"ts": _utcnow(), "event": "superseded_by", "id": obs.id})
                self.backend.put(old)
            self.backend.put(obs)
            return obs

        match = self._find_duplicate(obs)
        if match is None:
            self.backend.put(obs)
            return obs
        merged = self._merge(match, obs)
        self.backend.put(merged)
        return merged

    def _find_duplicate(self, obs: Observation) -> Optional[Observation]:
        best, best_sim = None, 0.0
        for cand in self.backend.all(obs.project):
            if cand.type != obs.type or cand.superseded_by:
                continue
            title_sim = _jaccard(_tokens(cand.title), _tokens(obs.title))
            link_sim = _jaccard(cand.link_bag(), obs.link_bag())
            sim = max(title_sim, link_sim)
            if sim > best_sim:
                best, best_sim = cand, sim
        return best if best_sim >= self.merge_threshold else None

    def _merge(self, base: Observation, incoming: Observation) -> Observation:
        """Deterministic merge: keep higher-confidence body, union links, bump
        confidence, record history. No duplicate row is created."""
        keep_summary = (incoming.summary if incoming.confidence > base.confidence
                        else base.summary)
        def union(a, b):
            out = list(a)
            for x in b:
                if x not in out:
                    out.append(x)
            return out

        base.summary = keep_summary
        base.reasoning = incoming.reasoning or base.reasoning
        base.resolution = incoming.resolution or base.resolution
        base.tags = union(base.tags, incoming.tags)
        base.concepts = union(base.concepts, incoming.concepts)
        base.files = union(base.files, incoming.files)
        base.symbols = union(base.symbols, incoming.symbols)
        base.dependencies = union(base.dependencies, incoming.dependencies)
        base.evidence = union(base.evidence, incoming.evidence)
        base.when_relevant = union(base.when_relevant, incoming.when_relevant)
        base.when_not_relevant = union(base.when_not_relevant, incoming.when_not_relevant)
        # confidence climbs toward the stronger signal; repeated confirmation matters
        base.confidence = min(100, max(base.confidence, incoming.confidence) + 2)
        # importance is monotonic upward (never quietly downgrade)
        if _IMPORTANCE_WEIGHT[incoming.importance] > _IMPORTANCE_WEIGHT[base.importance]:
            base.importance = incoming.importance
        base.updated = _utcnow()
        base.history.append({"ts": base.updated, "event": "merged",
                             "from": incoming.id, "confidence": base.confidence})
        return base

    # -- read: anti-relevance-aware scoring -----------------------------------
    def get(self, obs_id: str) -> Optional[Observation]:
        return self.backend.get(obs_id)

    def record_use(self, obs_id: str) -> None:
        o = self.backend.get(obs_id)
        if o:
            o.usage_count += 1
            o.last_used = _utcnow()
            self.backend.put(o)

    def query(self, q: Query) -> list[Scored]:
        signal_terms = _tokens(q.text) | {e.lower() for e in q.entities}
        intent_terms = set()
        if q.intent:
            intent_terms |= _tokens(q.intent)
        intent_terms |= signal_terms

        results: list[Scored] = []
        for o in self.backend.all(q.project):
            if o.superseded_by:
                continue
            if o.importance == Importance.ARCHIVE.value and not q.include_archived:
                continue
            if q.types and o.type not in q.types:
                continue

            # --- anti-relevance gate (the precision differentiator) ---
            not_rel = {t.lower() for t in o.when_not_relevant}
            if not_rel & intent_terms:
                continue  # explicitly not relevant to this intent -> suppress

            haystack = _tokens(o.title) | _tokens(o.summary) \
                | {c.lower() for c in o.concepts} | {t.lower() for t in o.tags}
            overlap = len(signal_terms & haystack)
            if overlap == 0 and not (({t.lower() for t in o.when_relevant}) & intent_terms):
                continue

            reasons = []
            score = float(overlap)
            if overlap:
                reasons.append(f"matches {overlap} query term(s)")
            wr_hit = {t.lower() for t in o.when_relevant} & intent_terms
            if wr_hit:
                score += 2.0
                reasons.append("intent in when_relevant")
            score *= _IMPORTANCE_WEIGHT[o.importance]
            score *= (0.5 + o.confidence / 200.0)  # 0.5..1.0
            if o.usage_count:
                score += min(1.0, o.usage_count * 0.1)
                reasons.append(f"used {o.usage_count}x")
            reasons.append(f"importance={o.importance}, confidence={o.confidence}")
            results.append(Scored(observation=o, score=round(score, 3), reasons=reasons))

        results.sort(key=lambda s: s.score, reverse=True)
        return results[:q.limit]

    # -- aging ----------------------------------------------------------------
    def age(self, now: Optional[str] = None) -> dict:
        now = now or _utcnow()
        now_dt = _dt.datetime.fromisoformat(now)
        expired, kept = 0, 0
        for o in self.backend.all():
            if o.importance in (Importance.CRITICAL.value, Importance.ARCHIVE.value):
                kept += 1
                continue
            if o.expires and _dt.datetime.fromisoformat(o.expires) <= now_dt:
                o.importance = Importance.ARCHIVE.value
                o.history.append({"ts": now, "event": "archived_by_aging"})
                self.backend.put(o)
                expired += 1
            else:
                kept += 1
        return {"archived": expired, "kept": kept}
