"""Hybrid multi-signal retrieval + RRF fusion — CORTEX read path, C3 (spec §8).

Every enabled signal independently ranks the candidate observations; the lists
are fused with Reciprocal Rank Fusion so no single method can dominate ("never
trust embeddings alone" — or BM25 alone). Fused scores are then shaped by
importance/confidence/recency/usage multipliers and the anti-relevance penalty:
an observation whose when_not_relevant matches the live intent is *killed*, not
demoted — precision beats recall in injected context.

Reason strings accumulate on items as they flow through the pipeline —
explainability lives in the data path (explain.py only formats).

The graph signal (C4) rides the knowledge graph's impact closure: observations
attached to files that depend on what the workspace just changed. Callers that
pass no graph get the pre-C4 behavior — RRF is indifferent to absent signals.

Stdlib only.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # import only for annotations: the hook path stays lean
    from .graph import GraphStore

from .intent import Intent, WorkspaceState, tokens
from .observation import Observation, Importance
from .store import ObservationStore, _IMPORTANCE_WEIGHT

RRF_K = 60           # standard RRF constant: flattens the head, keeps the tail
SIGNAL_CAP = 25      # each signal contributes at most this many ranked items


@dataclass
class RetrievedItem:
    observation: Observation
    signal_ranks: dict[str, int] = field(default_factory=dict)  # 1-based
    fused: float = 0.0        # pure RRF sum
    final: float = 0.0        # fused x multipliers
    reasons: list[str] = field(default_factory=list)


@dataclass
class Kill:
    """An anti-relevance suppression, kept for the explain playground."""
    observation_id: str
    title: str
    trigger: str              # the when_not_relevant term that fired


@dataclass
class RetrievalResult:
    items: list[RetrievedItem]                    # sorted by final, desc
    killed: list[Kill] = field(default_factory=list)
    signals: dict[str, list[str]] = field(default_factory=dict)  # signal -> obs ids


def _age_days(iso: str) -> float:
    try:
        then = _dt.datetime.fromisoformat(iso)
        if then.tzinfo is None:
            then = then.replace(tzinfo=_dt.timezone.utc)
        return (_dt.datetime.now(_dt.timezone.utc) - then).total_seconds() / 86400
    except ValueError:
        return 9999.0


def _candidates(store: ObservationStore, project: str,
                types: Optional[list[str]] = None) -> list[Observation]:
    out = []
    for o in store.backend.all(project):
        if o.superseded_by or o.importance == Importance.ARCHIVE.value:
            continue
        if types and o.type not in types:
            continue
        out.append(o)
    return out


# ---- signals: each returns obs ids, best first --------------------------------

def _sig_fts(store, prompt, project, allowed: dict[str, Observation]) -> list[str]:
    search = getattr(store.backend, "search", None)
    if search is None or not prompt.strip():
        return []
    hits = search(prompt, project=project, limit=SIGNAL_CAP * 2)
    return [o.id for o in hits if o.id in allowed][:SIGNAL_CAP]


def _sig_tags(prompt_terms: set[str], cands: list[Observation]) -> list[str]:
    scored = []
    for o in cands:
        bag = {t.lower() for t in o.tags} | {c.lower() for c in o.concepts}
        hit = len(prompt_terms & bag)
        if hit:
            scored.append((hit, o.id))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [oid for _, oid in scored[:SIGNAL_CAP]]


def _sig_when_relevant(intent_terms: set[str], cands: list[Observation]) -> list[str]:
    scored = []
    for o in cands:
        wr = set()
        for phrase in o.when_relevant:
            wr |= tokens(phrase)
        hit = len(intent_terms & wr)
        if hit:
            scored.append((hit, o.id))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [oid for _, oid in scored[:SIGNAL_CAP]]


def _sig_recency(cands: list[Observation]) -> list[str]:
    ranked = sorted(cands, key=lambda o: (o.updated, o.id), reverse=True)
    return [o.id for o in ranked[:SIGNAL_CAP]]


def _sig_importance(cands: list[Observation]) -> list[str]:
    ranked = sorted(cands, key=lambda o: (-_IMPORTANCE_WEIGHT[o.importance],
                                          -o.confidence, o.id))
    return [o.id for o in ranked[:SIGNAL_CAP]]


def _sig_usage(cands: list[Observation]) -> list[str]:
    used = [o for o in cands if o.usage_count > 0]
    used.sort(key=lambda o: (-o.usage_count, o.id))
    return [o.id for o in used[:SIGNAL_CAP]]


def _sig_links(fts_ids: list[str], cands: list[Observation],
               workspace: Optional[WorkspaceState]) -> list[str]:
    """Expansion: observations linked from the top lexical hits, plus
    observations touching files the workspace just changed."""
    by_id = {o.id: o for o in cands}
    out: list[str] = []
    for seed_id in fts_ids[:5]:
        seed = by_id.get(seed_id)
        if not seed:
            continue
        for rel in seed.related_observations:
            if rel in by_id and rel not in out and rel not in fts_ids:
                out.append(rel)
    if workspace and workspace.changed_files:
        changed = set(workspace.changed_files)
        for o in cands:
            if o.id not in out and set(o.files) & changed:
                out.append(o.id)
    return out[:SIGNAL_CAP]


def _sig_graph(graph: Optional["GraphStore"], cands: list[Observation],
               workspace: Optional[WorkspaceState]) -> list[str]:
    """Impact-closure signal (C4): observations attached to files that depend
    on what the workspace just changed. This is reach no lexical signal has —
    the observation may share zero words with the prompt."""
    if graph is None or workspace is None or not workspace.changed_files:
        return []
    allowed = {o.id for o in cands}
    best: dict[str, tuple[int, int]] = {}   # obs id -> (min depth, -hits)
    for path in workspace.changed_files[:10]:
        fid = graph.resolve_file(path)
        if not fid:
            continue
        for node, depth in [(fid, 0)] + graph.impact(fid, max_depth=3):
            for oid in graph.attached_observations(node):
                if oid not in allowed:
                    continue
                d, h = best.get(oid, (99, 0))
                best[oid] = (min(d, depth), h - 1)
    ranked = sorted(best.items(), key=lambda kv: (kv[1][0], kv[1][1], kv[0]))
    return [oid for oid, _ in ranked[:SIGNAL_CAP]]


# ---- fusion --------------------------------------------------------------------

def _anti_relevance_trigger(o: Observation, intent: Intent) -> Optional[str]:
    """The when_not_relevant term that intersects the live intent, if any."""
    live = intent.terms | tokens(intent.name)
    for phrase in o.when_not_relevant:
        overlap = tokens(phrase) & live
        if overlap:
            return sorted(overlap)[0]
    return None


def hybrid_retrieve(store: ObservationStore, prompt: str, intent: Intent,
                    project: str, *, limit: int = 20,
                    types: Optional[list[str]] = None,
                    workspace: Optional[WorkspaceState] = None,
                    graph: Optional["GraphStore"] = None) -> RetrievalResult:
    cands = _candidates(store, project, types)
    by_id = {o.id: o for o in cands}
    prompt_terms = intent.terms
    intent_terms = prompt_terms | tokens(intent.name)

    fts_ids = _sig_fts(store, prompt, project, by_id)
    signals: dict[str, list[str]] = {
        "fts": fts_ids,
        "tags": _sig_tags(prompt_terms, cands),
        "when_relevant": _sig_when_relevant(intent_terms, cands),
        "recency": _sig_recency(cands),
        "importance": _sig_importance(cands),
        "usage": _sig_usage(cands),
        "links": _sig_links(fts_ids, cands, workspace),
        "graph": _sig_graph(graph, cands, workspace),
    }

    weights = intent.weights
    fused: dict[str, RetrievedItem] = {}
    for name, ranked in signals.items():
        w = weights.get(name, 0.0)
        if w <= 0:
            continue
        for rank, oid in enumerate(ranked, start=1):
            item = fused.setdefault(oid, RetrievedItem(observation=by_id[oid]))
            item.signal_ranks[name] = rank
            item.fused += w / (RRF_K + rank)

    items: list[RetrievedItem] = []
    killed: list[Kill] = []
    for item in fused.values():
        o = item.observation
        trigger = _anti_relevance_trigger(o, intent)
        if trigger:
            killed.append(Kill(observation_id=o.id, title=o.title, trigger=trigger))
            continue

        imp_mult = _IMPORTANCE_WEIGHT[o.importance]
        conf_mult = 0.5 + o.confidence / 200.0
        age = _age_days(o.updated)
        rec_mult = 1.15 if age <= 7 else (1.05 if age <= 30 else 1.0)
        use_mult = 1.0 + min(0.3, 0.05 * o.usage_count)
        item.final = item.fused * imp_mult * conf_mult * rec_mult * use_mult

        for name, rank in sorted(item.signal_ranks.items()):
            item.reasons.append(f"{name} rank {rank}")
        item.reasons.append(
            f"importance={o.importance} x{imp_mult}, confidence={o.confidence}, "
            f"age {age:.0f}d" + (f", used {o.usage_count}x" if o.usage_count else ""))
        items.append(item)

    items.sort(key=lambda i: (-i.final, i.observation.id))
    return RetrievalResult(items=items[:limit], killed=killed, signals=signals)
