"""Turn-brief compiler — informs the incoming boss before ignition (P4.1 T4).

The conductor is a deterministic postman (design spec section 7): it decides
WHO gets the turn, never WHAT to build. Before this module every ignited
boss started blind and had to re-explore the repo, re-derive the ready unit,
and hand-run CORTEX lookups before doing anything useful. The conductor now
compiles one small file, ``.danza/runtime/turn-brief.md``, before every
ignite so any CLI reads the same brief regardless of activation mechanism —
it is a file on disk, not prompt injection, so it works identically for
every runner.

Four sections, always in this order:

  1. Your turn      — boss/runner, turn number, quota, the stop rule.
  2. Assigned units  — up to quota dependency-ready units (id, description,
                       verification command). Readiness is never
                       re-derived here: `_preview_ready_units` rides
                       ``workstation.execution``'s own
                       ``next_ready_unit``/``execution_records`` primitives.
  3. Last turn       — units the previous boss concluded, from the
                       execution ledger's ``completed_turn`` plus
                       ``TeamState.previous_boss``. TeamState carries no
                       handoff-note/summary field, so none is invented here.
  4. What the team already knows — a role-budgeted CORTEX package for the
     boss driver (``tony-d-orchestrator``: intent "planning", budget
     2400/ceiling 4000, cortex/budgets.py DRIVER_CORTEX).

Critical rule: section 4 can NEVER block a turn. Any exception raised while
touching cortex (missing store, corrupt DB, whatever) is swallowed and
replaced with a single fallback line; sections 1-3 do not depend on cortex
and are computed first regardless of what section 4 does.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Optional

from danzaboss.kernel.state import TeamState
from danzaboss.workstation import execution as execution_mod

TURN_BRIEF_RELPATH = ".danza/runtime/turn-brief.md"

# The boss's own CORTEX driver key (cortex/budgets.py DRIVER_CORTEX):
# forced intent "planning", budget 2400 / ceiling 4000.
BOSS_DRIVER = "tony-d-orchestrator"

# Continuous mode has no per-turn cap (TeamState.max_features_per_turn is
# None); the preview still needs a bound so an unbounded plan cannot produce
# an unbounded brief. Five matches the relay quota's own maximum
# (kernel/state.py _MAX_FEATURES_PER_TURN) — informational only, not a stop
# rule for continuous mode.
_CONTINUOUS_PREVIEW = 5

_FOOTER = ("Need more? `danza cortex search '<query>' | danza cortex get "
          "<id>` — pull only what you need.")


def _preview_ready_units(plan_data: dict, quota: int):
    """Up to `quota` upcoming dependency-ready units, in execution order.

    Reuses ``execution.next_ready_unit``'s own readiness predicate instead
    of re-deriving it: after each pick, a throwaway deep copy of the plan is
    marked as though that unit had just passed verification (with every
    field ``execution_records`` requires of a completed record), so the next
    call surfaces whatever unit it would unblock. Nothing here recomputes
    the dependency graph, status rules, or hard-stop flags — those stay
    solely in ``workstation/execution.py``.
    """
    if not quota or quota < 1:
        quota = _CONTINUOUS_PREVIEW
    working = copy.deepcopy(plan_data)
    working["execution"] = execution_mod.execution_records(working)
    picks = []
    for _ in range(quota):
        selection = execution_mod.next_ready_unit(working)
        if selection is None:
            break
        task = execution_mod._task_for_unit(working, selection.id)
        picks.append((selection, task))
        working["execution"][selection.id] = {
            **working["execution"][selection.id],
            "status": "completed",
            "completed_at": "1970-01-01T00:00:00+00:00",
            "actual_minutes": 0,
            "verification_attempts": 1,
            "verification_passed": True,
            "verification_evidence": [{"passed": True}],
        }
    return picks


def _last_turn_units(plan_data: dict, state: TeamState) -> list[dict]:
    """Units whose ``completed_turn`` matches the turn just handed off —
    i.e. what ``state.previous_boss`` finished before this handoff."""
    if state.previous_boss is None or state.turn_number < 1:
        return []
    last_turn_number = state.turn_number - 1
    records = execution_mod.execution_records(plan_data)
    return [
        {"id": unit_id, "completed_at": record.get("completed_at")}
        for unit_id, record in records.items()
        if record["status"] == "completed"
        and record.get("completed_turn") == last_turn_number
    ]


def _section_your_turn(state: TeamState, runner: str) -> str:
    quota = state.max_features_per_turn
    quota_text = "no cap (continuous mode)" if quota is None else str(quota)
    return "\n".join([
        "## Your turn",
        f"- Boss/runner: **{runner}** (turn {state.turn_number})",
        f"- Quota this turn: {quota_text} verified atomic units",
        "- Stop rule: when quota is reached, no ready work remains, or you "
        "are blocked, conclude via `danza unit conclude` and follow the "
        "returned decision exactly. Never continue past it.",
    ])


def _section_assigned_units(plan_data: dict,
                            state: TeamState) -> tuple[str, list[str]]:
    picks = _preview_ready_units(plan_data, state.max_features_per_turn)
    descriptions = [task.description for _, task in picks]
    lines = ["## Assigned units"]
    if not picks:
        lines.append(
            "No dependency-ready units are available this turn. Confirm "
            "with `danza unit conclude`.")
        return "\n".join(lines), descriptions
    for selection, task in picks:
        verification = (task.verification.detail
                        if task.verification is not None else "(none)")
        lines.append(f"- `{selection.id}` — {task.description}\n"
                     f"  verify: `{verification}`")
    return "\n".join(lines), descriptions


def _section_last_turn(plan_data: dict, state: TeamState) -> str:
    lines = ["## Last turn"]
    units = _last_turn_units(plan_data, state)
    if not units:
        lines.append("No prior turn recorded yet.")
        return "\n".join(lines)
    ids = ", ".join(f"`{u['id']}`" for u in units)
    lines.append(f"- {state.previous_boss} concluded: {ids}")
    return "\n".join(lines)


def _section_cortex(root: Path, task_text: str) -> str:
    """Section 4. ANY exception here degrades to a one-line fallback with
    no section header — sections 1-3 must never depend on cortex health."""
    try:
        from danzaboss.cortex.driver_context import compile_driver_context
        from danzaboss.cortex.events import CaptureLog
        from danzaboss.cortex.factory import db_path, open_store
        from danzaboss.cortex.identity import resolve_project

        project = resolve_project(str(root))
        store = open_store(str(root))
        ctx = compile_driver_context(
            store, BOSS_DRIVER, task_text or "team turn planning", project)
        for item in ctx.package.items:
            store.record_use(item.observation.id, source="turn-brief")
        CaptureLog(db_path(str(root))).record_context_read(
            project, BOSS_DRIVER, ctx.used, ctx.budget, ctx.adaptation)
    except Exception as exc:  # noqa: BLE001 - fail-open by design (critical rule)
        return f"Memory unavailable ({exc}) — proceed with the plan above."

    lines = ["## What the team already knows"]
    if not ctx.package.items:
        lines.append("(no relevant CORTEX observations yet)")
    else:
        for item in ctx.package.items:
            why = item.reasons[-1] if item.reasons else item.category
            lines.append(f"- **{item.observation.title}** — "
                         f"{item.observation.summary} _({why})_")
    return "\n".join(lines)


def compile_turn_brief(root: str | os.PathLike, state: TeamState,
                       plan_data: dict, runner: str,
                       work_type: Optional[str]) -> str:
    """Markdown brief for the boss about to be ignited.

    Sections 1-3 are pure functions of ``plan_data``/``state`` and never
    touch cortex; only section 4 can fail, and it fails into one line rather
    than raising.
    """
    root = Path(root)
    your_turn = _section_your_turn(state, runner)
    assigned, descriptions = _section_assigned_units(plan_data, state)
    last_turn = _section_last_turn(plan_data, state)
    cortex_section = _section_cortex(root, "; ".join(descriptions))
    return "\n\n".join([your_turn, assigned, last_turn, cortex_section,
                        _FOOTER])


def write_turn_brief(root: str | os.PathLike, state: TeamState,
                     plan_data: dict, runner: str,
                     work_type: Optional[str]) -> Path:
    """Compile the brief and atomically write it to ``TURN_BRIEF_RELPATH``.

    Same tmp-then-``os.replace`` pattern as ``workstation/state.py``'s
    atomic write — a crash mid-write can never leave a torn brief.
    """
    text = compile_turn_brief(root, state, plan_data, runner, work_type)
    path = Path(root) / TURN_BRIEF_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path
