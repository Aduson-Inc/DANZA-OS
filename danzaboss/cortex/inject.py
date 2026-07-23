"""SessionStart context injection — CORTEX read path, C1/P4.1 T6 version.

Builds the block a new session sees. Ranking is deliberately simple
(importance x confidence x recency x usage, plus a changed-files boost); C3
replaces it with the hybrid retriever behind the same function signature.

P4.1 T6 made this lean and turn-brief-aware. Two shapes, in priority order:

  1. Active relay turn: the conductor already wrote a role-budgeted brief to
     ``.danza/runtime/turn-brief.md`` at ignition (workstation/turnbrief.py,
     P4.1 T4) — re-deriving another context package here would be pure waste.
     When that file exists AND team-state's status says the turn is live
     (``ready``/``in_progress``/``awaiting_handoff`` — the real values from
     ``kernel/state.py``'s ``_ALLOWED_STATUS``, minus ``blocked``/``done``),
     this returns ONLY a short pointer block: no index, no bodies.
  2. Otherwise: a compact titles+ids index capped to ~1200 estimated tokens,
     ordered by the existing ranking, plus the pull-by-id instruction line.
     Full bodies are gone entirely — memory is pulled on demand via
     ``danza cortex get``/``search``, never pushed wholesale on every
     SessionStart.

Determining "is the turn brief active" can fail for all sorts of reasons
(no root given, files missing, corrupt JSON, an invalid state document) —
none of that may ever crash session start, so any failure there is treated
as "not active" and the caller gets the compact index instead. The hook
entry point (cortex/commands.py::_hook_session_start, via _cmd_hook) already
wraps everything in its own fail-open/fail-closed contract; this module adds
a second, narrower safety net so a corrupt team-state.json degrades to the
compact index rather than falling all the way through to that outer catch.
"""
from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path
from typing import Optional

from ..kernel.state import StateManager
from .observation import Observation, Importance
from .store import ObservationStore, _IMPORTANCE_WEIGHT
from .tokens import est_tokens

_TYPE_GLYPH = {
    "bug_fix": "B", "decision": "D", "performance": "P", "dependency": "d",
    "security": "S", "api_behavior": "A", "milestone": "M", "lesson": "L",
    "root_cause": "R", "limitation": "l", "impl_detail": "i", "convention": "c",
}

# Relative paths of the two files a live relay turn writes (conductor.py /
# workstation/turnbrief.py). Duplicated as plain strings rather than
# importing workstation.conductor/turnbrief: cortex is the lower layer here
# (workstation depends on cortex, never the reverse).
_TURN_BRIEF_RELPATH = os.path.join(".danza", "runtime", "turn-brief.md")
_TEAM_STATE_RELPATH = os.path.join(".danza", "runtime", "team-state.json")

# kernel/state.py's _ALLOWED_STATUS = {ready, in_progress, blocked,
# awaiting_handoff, done}. A relay turn is "active" (the brief on disk is
# still the live one) in every status except blocked/done.
_ACTIVE_TURN_STATUSES = {"ready", "in_progress", "awaiting_handoff"}

_INDEX_TOKEN_CAP = 1200


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


def _active_turn_brief(root: Optional[str]) -> bool:
    """True when a turn-brief file exists AND team-state's status says the
    relay turn it describes is still live. Any failure at all (no root,
    missing files, corrupt JSON, an invalid state document) means "not
    active" — never raises, so a broken turn-brief/team-state pair simply
    falls through to the compact index rather than blocking session start.
    """
    if not root:
        return False
    try:
        root_path = Path(root)
        if not (root_path / _TURN_BRIEF_RELPATH).exists():
            return False
        state = StateManager(str(root_path / _TEAM_STATE_RELPATH)).load()
        return state.status in _ACTIVE_TURN_STATUSES
    except Exception:  # noqa: BLE001 - this check must never be why session
        return False   # start breaks; treat any surprise as "not active"


def _turn_brief_pointer_block(project: str) -> str:
    """The lean 2-line block returned when a relay turn is actively using
    its compiled turn brief: no index, no bodies — just where to look."""
    return "\n".join([
        f"[CORTEX] {project} — turn brief active",
        f"Turn brief ready at {_TURN_BRIEF_RELPATH} — read it first; "
        "memory on demand via `danza cortex search/get`.",
    ])


def _compact_index(ranked: list[Observation], project: str,
                   stats: Optional[dict],
                   index_token_cap: int) -> str:
    """Titles+ids only, capped to ~index_token_cap estimated tokens, ordered
    by the existing ranking. No full bodies — those are pulled on demand."""
    index_lines: list[str] = []
    used = 0
    for o in ranked:
        line = _index_line(o)
        cost = est_tokens(line)
        if used + cost > index_token_cap:
            break
        index_lines.append(line)
        used += cost

    parts = [f"[CORTEX] {project} — {len(ranked)} observations "
             f"(titles only, top {len(index_lines)} shown)",
             "Types: B bug_fix, D decision, S security, R root_cause, L lesson, "
             "i impl_detail, c convention, l limitation, M milestone, P perf, "
             "d dependency, A api",
             *index_lines]
    if stats:
        parts.append(f"Economics: {stats.get('events', 0)} events captured, "
                     f"{stats.get('observations_written', 0)} observations distilled "
                     f"across {stats.get('sessions', 0)} sessions")
    parts.append("Fetch details: danza cortex get <id> [<id>...]")
    return "\n".join(parts)


def build_context(store: ObservationStore, project: str,
                  root: Optional[str] = None, *,
                  changed_files: Optional[list[str]] = None,
                  stats: Optional[dict] = None,
                  index_token_cap: int = _INDEX_TOKEN_CAP) -> str:
    ranked = rank_for_injection(store, project, changed_files)
    if not ranked:
        return ""
    if _active_turn_brief(root):
        return _turn_brief_pointer_block(project)
    return _compact_index(ranked, project, stats, index_token_cap)
