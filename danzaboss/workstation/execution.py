"""Persistent execution ledger for product-linked atomic plan units.

``.danza/plan.json`` remains the authoritative record of internal work.  This
module owns the mutable ``execution`` and ``calibration`` sections while the
planner continues to own the immutable task definitions and canonical order.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from danzaboss.kernel.state import StateManager, TeamState
from danzaboss.workstation import planner


class ExecutionError(ValueError):
    """The persisted execution ledger is missing, corrupt, or inconsistent."""


class TurnConclusion(str, Enum):
    CONTINUE = "continue"
    QUOTA = "quota"
    NO_WORK = "no_work"
    BLOCKED = "blocked"
    HARD_STOP = "hard_stop"


UNIT_STATUSES = frozenset({"pending", "in_progress", "blocked", "completed"})


@dataclass(frozen=True)
class UnitSelection:
    id: str
    kind: str
    feature_id: int | None
    size_est: int
    flags: tuple[str, ...]
    status: str


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def initial_execution(order: list[str] | tuple[str, ...]) -> dict[str, dict]:
    """Create the durable status/timing record for a newly approved plan."""
    return {
        unit_id: {
            "status": "pending",
            "started_at": None,
            "completed_at": None,
            "actual_minutes": None,
            "verification_attempts": 0,
            "verification_passed": False,
            "blocker_reason": None,
            "completed_turn": None,
        }
        for unit_id in order
    }


def _ordered_units(plan_data: dict) -> tuple[dict[str, Any], ...]:
    tasks = planner.parse_plan(plan_data)
    leaves: dict[str, Any] = {}
    nodes: dict[str, Any] = {}

    def visit(task) -> None:
        nodes[task.id] = task
        if task.is_leaf():
            leaves[task.id] = task
        for child in task.subtasks:
            visit(child)

    for task in tasks:
        visit(task)
    order = plan_data.get("order")
    if (not isinstance(order, list) or not order
            or not all(isinstance(unit_id, str) for unit_id in order)
            or len(set(order)) != len(order)):
        raise ExecutionError("plan.order must be a non-empty unique list of unit ids")
    ordered = []
    for unit_id in order:
        if unit_id not in leaves:
            raise ExecutionError(f"plan.order names unknown unit {unit_id!r}")
        task = leaves[unit_id]
        dependencies: set[str] = set()
        for dependency_id in task.depends_on:
            if dependency_id not in nodes:
                raise ExecutionError(
                    f"unit {unit_id!r} depends on unknown task "
                    f"{dependency_id!r}")
            stack = [nodes[dependency_id]]
            while stack:
                item = stack.pop()
                if item.is_leaf():
                    dependencies.add(item.id)
                else:
                    stack.extend(item.subtasks)
        ordered.append({"task": task, "dependencies": dependencies})
    return tuple(ordered)


def execution_records(plan_data: dict) -> dict[str, dict]:
    """Return validated records, migrating pre-Task-5 plans in memory.

    Missing execution data means every ordered unit is pending.  The caller
    persists that normalized shape on its first mutation; reads stay compatible
    with historical plan artifacts.
    """
    ordered_ids = [item["task"].id for item in _ordered_units(plan_data)]
    raw = plan_data.get("execution")
    if raw is None:
        return initial_execution(ordered_ids)
    if not isinstance(raw, dict) or set(raw) != set(ordered_ids):
        raise ExecutionError("plan.execution must contain exactly every ordered unit")
    records: dict[str, dict] = {}
    for unit_id in ordered_ids:
        record = raw[unit_id]
        if not isinstance(record, dict):
            raise ExecutionError(f"execution record {unit_id!r} must be an object")
        status = record.get("status")
        if status not in UNIT_STATUSES:
            raise ExecutionError(
                f"execution record {unit_id!r} has invalid status {status!r}")
        if status == "completed":
            if (record.get("verification_passed") is not True
                    or not isinstance(record.get("completed_at"), str)
                    or isinstance(record.get("actual_minutes"), bool)
                    or not isinstance(record.get("actual_minutes"), (int, float))):
                raise ExecutionError(
                    f"completed execution record {unit_id!r} lacks passing "
                    "verification and timing")
        records[unit_id] = dict(record)
    return records


def next_ready_unit(plan_data: dict) -> UnitSelection | None:
    """Select the first incomplete unit whose unit dependencies completed."""
    records = execution_records(plan_data)
    completed = {unit_id for unit_id, record in records.items()
                 if record["status"] == "completed"}
    for item in _ordered_units(plan_data):
        task = item["task"]
        status = records[task.id]["status"]
        if status not in {"pending", "in_progress"}:
            continue
        if not item["dependencies"] <= completed:
            continue
        return UnitSelection(task.id, task.kind, task.feature_id,
                             task.size_est, tuple(task.flags), status)
    return None


def conclude_turn(plan_data: dict, state: TeamState) -> TurnConclusion:
    """Return the kernel stop/continue reason without mutating conductor state."""
    records = execution_records(plan_data)
    incomplete = {unit_id: record for unit_id, record in records.items()
                  if record["status"] != "completed"}
    if not incomplete:
        return TurnConclusion.NO_WORK
    if any(record["status"] == "blocked" for record in incomplete.values()):
        return TurnConclusion.BLOCKED
    if (state.mode == "relay" and state.max_features_per_turn is not None
            and state.features_completed_this_turn >= state.max_features_per_turn):
        return TurnConclusion.QUOTA
    selection = next_ready_unit(plan_data)
    if selection is None:
        return TurnConclusion.BLOCKED
    if selection.flags and selection.status == "pending":
        return TurnConclusion.HARD_STOP
    return TurnConclusion.CONTINUE


def apply_turn_conclusion(root: str | os.PathLike, manager: StateManager,
                          actor: str, *, next_boss: str | None = None) -> dict:
    """Let the kernel persist a terminal turn decision before conductor acts.

    A quota handoff snapshots the current routing setting for the *next* turn.
    The conductor remains a postman: it observes the resulting team-state and
    ignites or halts; it never chooses stop reasons or advances counters.
    """
    plan_data = load_execution_plan(root)
    state = manager.load()
    conclusion = conclude_turn(plan_data, state)
    if conclusion is TurnConclusion.CONTINUE:
        return {"conclusion": conclusion.value, "state": state}
    if conclusion is TurnConclusion.QUOTA:
        if not next_boss:
            raise ExecutionError("quota conclusion requires next_boss")
        # Local import avoids making routing depend on an eager import cycle.
        from danzaboss.workstation.routing import load_routing
        next_quota = load_routing(root)["features_per_turn"]
        state = manager.handoff(next_boss, actor=actor,
                                max_features_per_turn=next_quota)
    elif conclusion is TurnConclusion.NO_WORK:
        state = manager.transition(actor=actor, to_status="done")
    else:
        state = manager.transition(actor=actor, to_status="blocked")
    return {"conclusion": conclusion.value, "state": state}


def load_execution_plan(root: str | os.PathLike) -> dict:
    path = Path(root) / planner.PLAN_JSON_RELPATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionError(f"cannot read execution plan {path}: {exc}") from exc
    execution_records(data)
    return data


def _write_execution_plan(root: str | os.PathLike, plan_data: dict) -> None:
    path = Path(root) / planner.PLAN_JSON_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(plan_data, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def start_unit(root: str | os.PathLike, unit_id: str, *,
               started_at: str | None = None) -> dict:
    plan_data = load_execution_plan(root)
    records = execution_records(plan_data)
    if unit_id not in records:
        raise ExecutionError(f"unknown unit {unit_id!r}")
    record = records[unit_id]
    if record["status"] == "completed":
        raise ExecutionError(f"completed unit {unit_id!r} is immutable")
    if record["status"] == "blocked":
        raise ExecutionError(f"blocked unit {unit_id!r} requires acknowledgement")
    if record["status"] == "pending":
        record["status"] = "in_progress"
        record["started_at"] = started_at or _now()
    plan_data["execution"] = records
    plan_data.setdefault("calibration", [])
    _write_execution_plan(root, plan_data)
    return dict(record)


def block_unit(root: str | os.PathLike, unit_id: str, reason: str) -> dict:
    if not isinstance(reason, str) or not reason.strip():
        raise ExecutionError("blocker reason must be non-empty")
    plan_data = load_execution_plan(root)
    records = execution_records(plan_data)
    record = records.get(unit_id)
    if record is None:
        raise ExecutionError(f"unknown unit {unit_id!r}")
    if record["status"] == "completed":
        raise ExecutionError(f"completed unit {unit_id!r} is immutable")
    record["status"] = "blocked"
    record["blocker_reason"] = reason.strip()
    plan_data["execution"] = records
    _write_execution_plan(root, plan_data)
    return dict(record)


def record_verification_failure(root: str | os.PathLike,
                                unit_id: str) -> dict:
    """Persist a failed verification without counting or blocking the unit."""
    plan_data = load_execution_plan(root)
    records = execution_records(plan_data)
    record = records.get(unit_id)
    if record is None:
        raise ExecutionError(f"unknown unit {unit_id!r}")
    if record["status"] != "in_progress":
        raise ExecutionError(
            f"unit {unit_id!r} must be in_progress before verification")
    record["verification_attempts"] = int(
        record.get("verification_attempts", 0)) + 1
    record["verification_passed"] = False
    plan_data["execution"] = records
    _write_execution_plan(root, plan_data)
    return dict(record)


def record_verified_completion(
        root: str | os.PathLike, manager: StateManager, actor: str,
        unit_id: str, *, actual_minutes: int | float,
        completed_at: str | None = None) -> tuple[dict, TeamState, bool]:
    """Persist a passing verification and count its unit exactly once.

    Repeating the same successful report is idempotent in both artifacts.
    The state update is attempted even when the plan already says completed,
    allowing a retry to reconcile a crash between the two atomic file writes.
    """
    if (isinstance(actual_minutes, bool)
            or not isinstance(actual_minutes, (int, float))
            or actual_minutes < 0):
        raise ExecutionError("actual_minutes must be a non-negative number")
    plan_data = load_execution_plan(root)
    records = execution_records(plan_data)
    record = records.get(unit_id)
    if record is None:
        raise ExecutionError(f"unknown unit {unit_id!r}")
    counted = record["status"] != "completed"
    if counted:
        if record["status"] != "in_progress":
            raise ExecutionError(
                f"unit {unit_id!r} must be in_progress before verification")
        selection = next(item["task"] for item in _ordered_units(plan_data)
                         if item["task"].id == unit_id)
        when = completed_at or _now()
        record.update({
            "status": "completed",
            "completed_at": when,
            "actual_minutes": actual_minutes,
            "verification_attempts": int(record.get("verification_attempts", 0)) + 1,
            "verification_passed": True,
            "blocker_reason": None,
            "completed_turn": manager.load().turn_number,
        })
        observation = {
            "unit_id": unit_id,
            "estimated_minutes": selection.size_est,
            "actual_minutes": actual_minutes,
            "variance_minutes": actual_minutes - selection.size_est,
            "overrun": actual_minutes > selection.size_est,
            "recorded_at": when,
        }
        calibration = plan_data.setdefault("calibration", [])
        if not isinstance(calibration, list):
            raise ExecutionError("plan.calibration must be an array")
        calibration.append(observation)
        plan_data["execution"] = records
        _write_execution_plan(root, plan_data)
    state = manager.record_unit(actor, unit_id)
    return dict(record), state, counted
