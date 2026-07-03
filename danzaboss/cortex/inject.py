"""SessionStart context injection — CORTEX read path, C1 version.

Builds the block a new session sees: a cheap semantic index (one line per
observation) plus the top-K full observations under a token ceiling. Ranking
here is deliberately simple (importance x confidence x recency x usage, plus a
changed-files boost); C3 replaces it with the hybrid retriever behind the same
function signature.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from .observation import Observation, Importance
from .store import ObservationStore, _IMPORTANCE_WEIGHT

_TYPE_GLYPH = {
    "bug_fix": "B", "decision": "D", "performance": "P", "dependency": "d",
    "security": "S", "api_behavior": "A", "milestone": "M", "lesson": "L",
    "root_cause": "R", "limitation": "l", "impl_detail": "i", "convention": "c",
}


def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _recency_bonus(obs: Observation) -> float:
    try:
        updated = _dt.datetime.fromisoformat(obs.updated)
        age_days = (_dt.datetime.now(_dt.timezone.utc) - updated).days
    except ValueError:
        return 0.0
    return 1.0 if age_days <= 7 else (0.5 if age_days <= 30 else 0.0)


def rank_for_injection(store: ObservationStore, project: str,
                       changed_files: Optional[list[str]] = None) -> list[Observation]:
    changed = {f for f in (changed_files or [])}
    scored: list[tuple[float, Observation]] = []
    for o in store.backend.all(project):
        if o.superseded_by or o.importance == Importance.ARCHIVE.value:
            continue
        score = _IMPORTANCE_WEIGHT[o.importance] * (0.5 + o.confidence / 200.0)
        score += _recency_bonus(o)
        score += min(1.0, o.usage_count * 0.1)
        if changed and (set(o.files) & changed):
            score += 2.0
        scored.append((score, o))
    scored.sort(key=lambda t: (-t[0], t[1].id))
    return [o for _, o in scored]


def _index_line(o: Observation) -> str:
    glyph = _TYPE_GLYPH.get(o.type, "?")
    cost = est_tokens(o.summary + o.reasoning)
    return f"{o.id} [{glyph}] {o.title} (~{cost}t)"


def _full_entry(o: Observation) -> str:
    parts = [f"### {o.title}  ({o.type}, {o.importance}, conf {o.confidence})",
             o.summary]
    if o.reasoning:
        parts.append(f"Why: {o.reasoning}")
    if o.files:
        parts.append("Files: " + ", ".join(o.files[:6]))
    return "\n".join(parts)


def build_context(store: ObservationStore, project: str, *, max_full: int = 5,
                  token_ceiling: int = 2000,
                  changed_files: Optional[list[str]] = None,
                  stats: Optional[dict] = None) -> str:
    ranked = rank_for_injection(store, project, changed_files)
    if not ranked:
        return ""
    index_lines = [_index_line(o) for o in ranked[:50]]
    full_entries: list[str] = []
    used = 0
    for o in ranked[:max_full]:
        entry = _full_entry(o)
        cost = est_tokens(entry)
        if used + cost > token_ceiling:
            break
        full_entries.append(entry)
        used += cost

    parts = [f"[CORTEX] {project} — {len(ranked)} observations "
             f"(index below; bodies for top {len(full_entries)})",
             "Types: B bug_fix, D decision, S security, R root_cause, L lesson, "
             "i impl_detail, c convention, l limitation, M milestone, P perf, "
             "d dependency, A api",
             *index_lines]
    if full_entries:
        parts.append("── Top observations ──")
        parts.extend(full_entries)
    if stats:
        parts.append(f"Economics: {stats.get('events', 0)} events captured, "
                     f"{stats.get('observations_written', 0)} observations distilled "
                     f"across {stats.get('sessions', 0)} sessions")
    parts.append("Fetch details: danza cortex get <id> [<id>...]")
    return "\n".join(parts)
