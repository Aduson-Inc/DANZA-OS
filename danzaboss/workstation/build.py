"""BUILD backend projections, progress transactions, and queued additions.

The active approved ``features.json``/``plan.json`` pair is never replaced
mid-turn. Product additions are drafted separately, replanned against only
unfinished product work, and stored as one next-handoff bundle. Execution
progress updates use a small write-ahead journal so plan and scope status
cannot remain split after an interrupted multi-file update.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Callable

from danzaboss.kernel.state import StateError, StateManager
from danzaboss.workstation import execution, planner, product_scope, project
from danzaboss.workstation.conductor import TEAM_STATE_RELPATH


SCHEMA_VERSION = 1
ADDITIONS_RELPATH = Path(".danza") / "build-additions.json"
QUEUE_RELPATH = Path(".danza") / "build-next-handoff.json"
PROGRESS_TX_RELPATH = (Path(".danza") / "runtime" /
                       "build-progress-transaction.json")


class BuildError(ValueError):
    """BUILD state is missing, corrupt, stale, or violates its contract."""


class BuildRevisionConflict(BuildError):
    """A BUILD mutation targeted a stale additions or active revision."""


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(value, encoding="utf-8")
    os.replace(tmp, path)


def _load_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"cannot read {label} at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BuildError(f"{label} at {path} must be a JSON object")
    return value


def _active(root: str | os.PathLike) -> tuple[dict, dict]:
    recover_progress(root)
    try:
        scope = project.require_approved_scope(root)
        plan = execution.load_execution_plan(root)
        project.require_plan_matches_scope(root, plan)
    except (ValueError, OSError) as exc:
        raise BuildError(f"valid approved PROJECT and execution state required: {exc}") from exc
    return scope, plan


def _leaf_dicts(tasks: list[dict]) -> dict[str, dict]:
    leaves: dict[str, dict] = {}

    def visit(task: object) -> None:
        if not isinstance(task, dict):
            raise BuildError("plan tasks must be objects")
        children = task.get("subtasks", [])
        if children:
            if not isinstance(children, list):
                raise BuildError("plan subtasks must be an array")
            for child in children:
                visit(child)
            return
        unit_id = task.get("id")
        if not isinstance(unit_id, str) or not unit_id:
            raise BuildError("plan leaf id must be a non-empty string")
        leaves[unit_id] = copy.deepcopy(task)

    for item in tasks:
        visit(item)
    return leaves


def _unit_tasks(plan: dict) -> dict[str, object]:
    tasks = planner.parse_plan(plan)
    leaves: dict[str, object] = {}

    def visit(task) -> None:
        if task.is_leaf():
            leaves[task.id] = task
        for child in task.subtasks:
            visit(child)

    for task in tasks:
        visit(task)
    return leaves


def _feature_projection(scope: dict, plan: dict) -> tuple[list[dict], dict]:
    """Return product features with status derived only from linked units."""
    records = execution.execution_records(plan)
    tasks = _unit_tasks(plan)
    by_feature: dict[int, list[dict]] = {
        feature["id"]: [] for feature in scope["features"]}
    for unit_id in plan["order"]:
        task = tasks[unit_id]
        if task.feature_id not in by_feature:
            raise BuildError(
                f"unit {unit_id!r} references out-of-scope feature "
                f"{task.feature_id!r}")
        record = records[unit_id]
        by_feature[task.feature_id].append({
            "id": task.id,
            "description": task.description,
            "kind": task.kind,
            "size_est": task.size_est,
            "writes": list(task.writes),
            "verification": (task.verification.detail
                             if task.verification else None),
            "depends_on": list(task.depends_on),
            "flags": list(task.flags),
            **copy.deepcopy(record),
        })

    projected: list[dict] = []
    for feature in scope["features"]:
        units = by_feature[feature["id"]]
        if not units:
            raise BuildError(
                f"product feature {feature['id']} has no atomic plan units")
        statuses = [unit["status"] for unit in units]
        if all(status == "completed" for status in statuses):
            status = "completed"
        elif "blocked" in statuses:
            status = "blocked"
        elif any(status in {"in_progress", "completed"}
                 for status in statuses):
            status = "in_progress"
        else:
            status = "pending"
        if feature["status"] == "completed" and status != "completed":
            raise BuildError(
                f"completed product feature {feature['id']} cannot regress")
        projected.append({**copy.deepcopy(feature), "status": status,
                          "units": units})

    status_scope = copy.deepcopy(scope)
    status_scope["features"] = [
        {key: value for key, value in feature.items() if key != "units"}
        for feature in projected
    ]
    return projected, status_scope


def _validate_transaction(value: object) -> tuple[dict, dict]:
    if (not isinstance(value, dict)
            or set(value) != {"version", "plan", "scope"}
            or value.get("version") != SCHEMA_VERSION):
        raise BuildError("progress transaction has an invalid shape")
    try:
        scope = product_scope.validate_scope(value["scope"])
        plan = value["plan"]
        if not isinstance(plan, dict):
            raise BuildError("progress transaction plan must be an object")
        execution.execution_records(plan)
        if plan.get("spec_ref") != project.scope_ref(scope):
            raise BuildError(
                "progress transaction scope and plan revisions differ")
        _feature_projection(scope, plan)
    except BuildError:
        raise
    except ValueError as exc:
        raise BuildError(f"progress transaction is invalid: {exc}") from exc
    return scope, plan


def recover_progress(root: str | os.PathLike) -> bool:
    """Finish a journaled plan/scope update left by an interrupted writer."""
    journal = Path(root) / PROGRESS_TX_RELPATH
    if not journal.exists():
        return False
    value = _load_json(journal, "BUILD progress transaction")
    scope, plan = _validate_transaction(value)
    _atomic_json(Path(root) / planner.PLAN_JSON_RELPATH, plan)
    tasks = _unit_tasks(plan)
    ordered = tuple(tasks[unit_id] for unit_id in plan["order"])
    _atomic_text(Path(root) / planner.PLAN_MD_RELPATH,
                 planner.render_plan_md(plan["spec_ref"], ordered))
    current = product_scope.load_scope(root)
    try:
        if scope["revision"] == current["revision"]:
            product_scope.write_scope(root, scope)
        else:
            product_scope.activate_queued_scope(root, scope)
    except product_scope.ProductScopeError as exc:
        raise BuildError(
            f"cannot apply BUILD progress transaction: {exc}") from exc
    journal.unlink()
    return True


def _commit_bundle(root: str | os.PathLike, scope: dict, plan: dict) -> None:
    journal = Path(root) / PROGRESS_TX_RELPATH
    _atomic_json(journal, {"version": SCHEMA_VERSION,
                           "scope": scope, "plan": plan})
    recover_progress(root)


def commit_progress(root: str | os.PathLike, plan: dict) -> dict:
    """Commit an execution-ledger change and its derived product statuses."""
    try:
        scope = project.require_approved_scope(root)
    except project.ProjectGateConflict as exc:
        raise BuildError(
            f"valid approved PROJECT state required for progress: {exc}") from exc
    if plan.get("spec_ref") != project.scope_ref(scope):
        raise BuildRevisionConflict(
            "execution plan does not match the active approved scope")
    _, status_scope = _feature_projection(scope, plan)
    _commit_bundle(root, status_scope, plan)
    return status_scope


def _load_additions(root: str | os.PathLike) -> dict | None:
    path = Path(root) / ADDITIONS_RELPATH
    if not path.exists():
        return None
    value = _load_json(path, "BUILD additions")
    if (set(value) != {"version", "revision", "approval", "features"}
            or value.get("version") != SCHEMA_VERSION
            or type(value.get("revision")) is not int
            or value["revision"] < 1):
        raise BuildError("BUILD additions have an invalid shape")
    approval = value.get("approval")
    if (not isinstance(approval, dict)
            or set(approval) != {"state", "approved_revision"}
            or approval.get("state") not in {"draft", "approved"}):
        raise BuildError("BUILD additions approval is invalid")
    approved_revision = approval.get("approved_revision")
    if ((approval["state"] == "draft" and approved_revision is not None)
            or (approval["state"] == "approved"
                and approved_revision != value["revision"])):
        raise BuildError("BUILD additions approval revision is invalid")
    return value


def _validate_addition_features(scope: dict, additions: object) -> list[dict]:
    if not isinstance(additions, list) or not additions:
        raise BuildError("additions must be a non-empty array")
    existing = {feature["id"] for feature in scope["features"]}
    copied = copy.deepcopy(additions)
    for item in copied:
        if isinstance(item, dict) and item.get("id") in existing:
            raise BuildError(
                f"product feature id {item.get('id')} already exists")
        if isinstance(item, dict) and item.get("status") != "pending":
            raise BuildError("new product features must start pending")
    probe = {"version": product_scope.SCHEMA_VERSION, "revision": 1,
             "approval": {"state": "draft", "approved_revision": None},
             "features": copied}
    try:
        product_scope.validate_scope(probe)
    except product_scope.ProductScopeError as exc:
        raise BuildError(str(exc)) from exc
    return copied


def draft_additions(root: str | os.PathLike, *, additions: list[dict],
                    expected_revision: int | None = None) -> dict:
    """Create or revise the isolated additions draft without active writes."""
    scope, _ = _active(root)
    if (Path(root) / QUEUE_RELPATH).exists():
        raise BuildRevisionConflict(
            "activate the queued additions before drafting another revision")
    features = _validate_addition_features(scope, additions)
    current = _load_additions(root)
    if current is None:
        if expected_revision is not None:
            raise BuildRevisionConflict(
                "expected_revision must be omitted for the first additions draft")
        revision = 1
    else:
        if (type(expected_revision) is not int
                or expected_revision != current["revision"]):
            raise BuildRevisionConflict(
                f"stale additions revision {expected_revision!r}; current "
                f"revision is {current['revision']}")
        if current["approval"]["state"] == "approved":
            raise BuildRevisionConflict("approved additions are immutable")
        revision = current["revision"] + 1
    value = {"version": SCHEMA_VERSION, "revision": revision,
             "approval": {"state": "draft", "approved_revision": None},
             "features": features}
    _atomic_json(Path(root) / ADDITIONS_RELPATH, value)
    return value


def _planning_scope(scope: dict, feature_ids: set[int]) -> dict:
    pending = [copy.deepcopy(feature) for feature in scope["features"]
               if feature["id"] in feature_ids]
    if not pending:
        raise BuildError("queued scope contains no unfinished product work")
    for feature in pending:
        feature["status"] = "pending"
    return {"version": scope["version"], "revision": scope["revision"],
            "approval": copy.deepcopy(scope["approval"]),
            "features": pending}


def approve_additions(
        root: str | os.PathLike, *, expected_revision: int,
        propose: Callable[[dict, str, set[str]], dict]) -> dict:
    """Approve exact additions, replan unfinished work, and queue activation."""
    scope, active_plan = _active(root)
    additions = _load_additions(root)
    if additions is None:
        raise BuildRevisionConflict("there is no additions draft to approve")
    if (type(expected_revision) is not int
            or expected_revision != additions["revision"]):
        raise BuildRevisionConflict(
            f"stale additions revision {expected_revision!r}; current revision "
            f"is {additions['revision']}")
    if additions["approval"]["state"] != "draft":
        raise BuildRevisionConflict("additions revision is already approved")
    if (Path(root) / QUEUE_RELPATH).exists():
        raise BuildRevisionConflict("a next-handoff build is already queued")

    projected, status_scope = _feature_projection(scope, active_plan)
    next_revision = scope["revision"] + 1
    candidate = copy.deepcopy(status_scope)
    candidate.update({
        "revision": next_revision,
        "approval": {"state": "approved",
                     "approved_revision": next_revision},
        "features": [
            *[{key: value for key, value in item.items() if key != "units"}
              for item in projected],
            *copy.deepcopy(additions["features"]),
        ],
    })
    product_scope.validate_scope(candidate)
    spec_ref = project.scope_ref(candidate)
    records = execution.execution_records(active_plan)
    active_tasks = _unit_tasks(active_plan)
    carry_ids = {unit_id for unit_id, record in records.items()
                 if record["status"] != "pending"}
    replanned_feature_ids = {
        active_tasks[unit_id].feature_id
        for unit_id, record in records.items()
        if record["status"] == "pending"
    }
    replanned_feature_ids.update(
        feature["id"] for feature in additions["features"])
    planning_scope = _planning_scope(candidate, replanned_feature_ids)
    proposed = propose(copy.deepcopy(planning_scope), spec_ref,
                       set(carry_ids))
    if not isinstance(proposed, dict) or proposed.get("spec_ref") != spec_ref:
        raise BuildError("replanned work must reference the queued scope revision")
    proposed_tasks = planner.parse_plan(proposed)
    violations = planner.validate_plan(proposed_tasks, require_atomic=True)
    violations.extend(planner.validate_scope_coverage(
        proposed_tasks, planning_scope))
    if violations:
        raise BuildError("replanned pending work is invalid: "
                         + "; ".join(violations))
    proposed_records = execution.execution_records(proposed)
    if carry_ids & set(proposed_records):
        reused = sorted(carry_ids & set(proposed_records))
        raise BuildError(f"replanning reused reserved unit ids {reused!r}")

    old_leaves = _leaf_dicts(active_plan["tasks"])
    carry_order = [unit_id for unit_id in active_plan["order"]
                   if unit_id in carry_ids]
    merged_order = [*carry_order, *proposed["order"]]
    merged = {
        "spec_ref": spec_ref,
        "tasks": [*[old_leaves[unit_id] for unit_id in carry_order],
                  *copy.deepcopy(proposed["tasks"])],
        "order": merged_order,
        "execution": {
            **{unit_id: copy.deepcopy(records[unit_id])
               for unit_id in carry_order},
            **copy.deepcopy(proposed_records),
        },
        "calibration": copy.deepcopy(active_plan.get("calibration", [])),
    }
    execution.execution_records(merged)
    _, candidate = _feature_projection(candidate, merged)
    approved_additions = copy.deepcopy(additions)
    approved_additions["approval"] = {
        "state": "approved", "approved_revision": expected_revision}
    queue = {"version": SCHEMA_VERSION,
             "base_spec_ref": active_plan["spec_ref"],
             "activate_at": "next_handoff",
             "additions_revision": expected_revision,
             "carry_unit_ids": carry_order,
             "scope": candidate, "plan": merged}
    _atomic_json(Path(root) / QUEUE_RELPATH, queue)
    _atomic_json(Path(root) / ADDITIONS_RELPATH, approved_additions)
    return {"scope_revision": next_revision,
            "activate_at": "next_handoff", "unit_count": len(merged_order)}


def _load_queue(root: str | os.PathLike) -> dict | None:
    path = Path(root) / QUEUE_RELPATH
    if not path.exists():
        return None
    value = _load_json(path, "next-handoff build")
    if (set(value) != {"version", "base_spec_ref", "activate_at",
                       "additions_revision", "carry_unit_ids", "scope",
                       "plan"}
            or value.get("version") != SCHEMA_VERSION
            or value.get("activate_at") != "next_handoff"
            or type(value.get("additions_revision")) is not int
            or not isinstance(value.get("carry_unit_ids"), list)
            or not all(isinstance(item, str)
                       for item in value["carry_unit_ids"])):
        raise BuildError("next-handoff build has an invalid shape")
    try:
        scope = product_scope.validate_scope(value["scope"])
        plan = value["plan"]
        if (not isinstance(plan, dict)
                or plan.get("spec_ref") != project.scope_ref(scope)):
            raise BuildError("next-handoff scope and plan revisions differ")
        execution.execution_records(plan)
        _feature_projection(scope, plan)
    except BuildError:
        raise
    except ValueError as exc:
        raise BuildError(f"next-handoff build is invalid: {exc}") from exc
    additions = _load_additions(root)
    if (additions is None
            or additions["revision"] != value["additions_revision"]
            or additions["approval"] != {
                "state": "approved",
                "approved_revision": value["additions_revision"]}):
        raise BuildError(
            "next-handoff build lacks exact approved additions evidence")
    scope_by_id = {feature["id"]: feature for feature in scope["features"]}
    if any(scope_by_id.get(feature["id"]) != feature
           for feature in additions["features"]):
        raise BuildError(
            "next-handoff scope does not match exact approved additions")
    return value


def activate_queued_build(root: str | os.PathLike) -> bool:
    """Atomically promote the queued approved scope/plan at a handoff."""
    queue = _load_queue(root)
    if queue is None:
        return False
    scope, plan = _active(root)
    if plan["spec_ref"] != queue["base_spec_ref"]:
        raise BuildRevisionConflict(
            "active build changed after the next-handoff build was queued")
    active_records = execution.execution_records(plan)
    active_leaves = _leaf_dicts(plan["tasks"])
    queued_plan = copy.deepcopy(queue["plan"])
    queued_leaves = _leaf_dicts(queued_plan["tasks"])
    for unit_id in queue["carry_unit_ids"]:
        if (unit_id not in active_records or unit_id not in queued_leaves
                or queued_leaves[unit_id] != active_leaves[unit_id]):
            raise BuildRevisionConflict(
                f"carried unit {unit_id!r} changed after queue approval")
        queued_plan["execution"][unit_id] = copy.deepcopy(
            active_records[unit_id])
    _, queued_scope = _feature_projection(queue["scope"], queued_plan)
    _commit_bundle(root, queued_scope, queued_plan)
    (Path(root) / QUEUE_RELPATH).unlink()
    additions_path = Path(root) / ADDITIONS_RELPATH
    if additions_path.exists():
        additions_path.unlink()
    return True


def queue_waiting(root: str | os.PathLike) -> bool:
    """Whether an approved next-handoff bundle is present and valid."""
    return _load_queue(root) is not None


def live_payload(root: str | os.PathLike) -> dict:
    """Validated BUILD product payload for the dashboard/API."""
    scope, plan = _active(root)
    features, status_scope = _feature_projection(scope, plan)
    quota = {"completed": 0, "limit": None, "remaining": None}
    try:
        state = StateManager(str(Path(root) / TEAM_STATE_RELPATH)).load()
    except (StateError, OSError, json.JSONDecodeError):
        state = None
    if state is not None:
        limit = state.max_features_per_turn
        quota = {"completed": state.features_completed_this_turn,
                 "limit": limit,
                 "remaining": (None if limit is None else
                               max(0, limit - state.features_completed_this_turn))}
    additions = _load_additions(root)
    queue = _load_queue(root)
    return {
        "scope": {"version": status_scope["version"],
                  "revision": status_scope["revision"],
                  "approval": status_scope["approval"]},
        "progress": product_scope.derive_progress(status_scope),
        "features": features,
        "quota": quota,
        "additions": additions,
        "next_handoff": (None if queue is None else {
            "scope_revision": queue["scope"]["revision"],
            "activate_at": queue["activate_at"],
            "unit_count": len(queue["plan"]["order"]),
        }),
    }
