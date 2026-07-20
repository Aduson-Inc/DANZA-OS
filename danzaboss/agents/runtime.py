"""Runtime authority for model-neutral DANZA agents.

Prompt files are presentation adapters. This module owns the identity,
capability, assignment, spawn-receipt, and scope checks that decide whether a
connected model may cause a project mutation.
"""
from __future__ import annotations

import datetime as _dt
import json
import secrets
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Optional


class AuthorizationError(PermissionError):
    """An agent tried to act without a valid runtime authorization."""


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    display_name: str
    role: str
    responsibility: str
    capabilities: frozenset[str]
    spawn_allowlist: frozenset[str]
    forbidden: frozenset[str]


@dataclass(frozen=True)
class Assignment:
    id: str
    parent: str
    child: str
    task_id: str
    scope: tuple[str, ...]
    status: str = "assigned"
    child_session_id: Optional[str] = None
    reason: str = ""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def load_agent_definitions() -> dict[str, AgentDefinition]:
    """Load and validate the single packaged vendor-neutral manifest."""
    path = files("danzaboss.agents") / "definitions.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorizationError(f"agent definition manifest unavailable: {exc}") from exc
    if raw.get("schema_version") != 1 or not isinstance(raw.get("agents"), list):
        raise AuthorizationError("invalid agent definition manifest")
    result: dict[str, AgentDefinition] = {}
    for item in raw["agents"]:
        required = ("id", "display_name", "role", "responsibility",
                    "capabilities", "spawn_allowlist", "forbidden")
        if not all(isinstance(item.get(key), (str, list)) for key in required):
            raise AuthorizationError(f"invalid agent definition: {item!r}")
        agent_id = item["id"]
        if agent_id in result:
            raise AuthorizationError(f"duplicate agent definition: {agent_id}")
        result[agent_id] = AgentDefinition(
            id=agent_id,
            display_name=item["display_name"],
            role=item["role"],
            responsibility=item["responsibility"],
            capabilities=frozenset(item["capabilities"]),
            spawn_allowlist=frozenset(item["spawn_allowlist"]),
            forbidden=frozenset(item["forbidden"]),
        )
    ids = set(result)
    for definition in result.values():
        if not definition.spawn_allowlist <= ids:
            raise AuthorizationError(
                f"{definition.id} references an unknown spawn target")
        if definition.capabilities & definition.forbidden:
            raise AuthorizationError(
                f"{definition.id} grants and forbids the same capability")
    return result


class AgentRuntime:
    """Fail-closed assignment and capability gate for one project."""

    # A feature normally needs a builder plus one or two focused specialists.
    # This is deliberately a runtime ceiling: Tony-D cannot fan out the full
    # roster because a prompt claimed that doing so would be useful.
    MAX_SPECIALISTS_PER_TASK = 3

    STATE_RELPATH = Path(".danza") / "runtime" / "assignments.json"
    RECEIPTS_RELPATH = Path(".danza") / "runtime" / "delegations.jsonl"

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.definitions = load_agent_definitions()
        self.state_path = self.root / self.STATE_RELPATH
        self.receipts_path = self.root / self.RECEIPTS_RELPATH
        self._assignments = self._load()

    def _load(self) -> dict[str, dict]:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._assignments, indent=2, sort_keys=True),
                       encoding="utf-8")
        tmp.replace(self.state_path)

    def _receipt(self, payload: dict) -> None:
        self.receipts_path.parent.mkdir(parents=True, exist_ok=True)
        with self.receipts_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": _now(), **payload}, sort_keys=True) + "\n")

    def _validate_assignment(self, *, parent: str, child: str, task_id: str,
                             scope: list[str] | tuple[str, ...], reason: str,
                             check_budget: bool = True) -> None:
        parent_def = self.definitions.get(parent)
        child_def = self.definitions.get(child)
        if parent_def is None or child_def is None:
            raise AuthorizationError("assignment references an unknown agent")
        if "spawn_agent" not in parent_def.capabilities:
            raise AuthorizationError(f"{parent} may not spawn agents")
        if child not in parent_def.spawn_allowlist:
            raise AuthorizationError(f"{parent} may not spawn {child}")
        if not task_id or not scope:
            raise AuthorizationError("assignment requires task_id and non-empty scope")
        if not isinstance(reason, str) or not reason.strip():
            raise AuthorizationError(
                "assignment requires a specific reason for this specialist")
        if check_budget:
            active = sum(1 for row in self._assignments.values()
                         if row.get("task_id") == task_id
                         and row.get("status") in {"assigned", "spawned"})
            if active >= self.MAX_SPECIALISTS_PER_TASK:
                raise AuthorizationError(
                    f"specialist spawn budget exceeded for task {task_id} "
                    f"(maximum {self.MAX_SPECIALISTS_PER_TASK} specialists)")

    def assign(self, *, parent: str, child: str, task_id: str,
               scope: list[str] | tuple[str, ...], reason: str) -> Assignment:
        self._validate_assignment(parent=parent, child=child, task_id=task_id,
                                  scope=scope, reason=reason)
        assignment = Assignment(
            id="asg_" + secrets.token_hex(10), parent=parent, child=child,
            task_id=task_id, scope=tuple(scope), reason=reason.strip(),
        )
        self._assignments[assignment.id] = {
            "id": assignment.id, "parent": parent, "child": child,
            "task_id": task_id, "scope": list(scope), "status": "assigned",
            "child_session_id": None, "reason": reason.strip(),
        }
        self._save()
        self._receipt({"event": "assignment_created", **self._assignments[assignment.id]})
        return assignment

    def plan_spawn(self, *, parent: str, task_id: str,
                   scope: list[str] | tuple[str, ...],
                   specialists: list[str],
                   reasons: dict[str, str]) -> list[Assignment]:
        """Create the minimal justified specialist set for one task.

        The whole plan is validated before any assignment is written. This is
        the production delegation path; callers cannot use a full-roster fanout
        as a substitute for task analysis.
        """
        if not isinstance(specialists, list) or not specialists:
            raise AuthorizationError("spawn plan must name needed specialists")
        if len(specialists) > self.MAX_SPECIALISTS_PER_TASK:
            raise AuthorizationError(
                f"spawn plan may contain at most {self.MAX_SPECIALISTS_PER_TASK} "
                "specialists")
        if len(set(specialists)) != len(specialists):
            raise AuthorizationError("spawn plan contains duplicate specialists")
        if not isinstance(reasons, dict) or set(reasons) != set(specialists):
            raise AuthorizationError(
                "spawn plan requires one specific reason per specialist")
        existing = {row.get("child") for row in self._assignments.values()
                    if row.get("task_id") == task_id
                    and row.get("status") in {"assigned", "spawned"}}
        if existing.intersection(specialists):
            raise AuthorizationError("specialist is already assigned to this task")
        for child in specialists:
            self._validate_assignment(parent=parent, child=child,
                                      task_id=task_id, scope=scope,
                                      reason=reasons[child], check_budget=False)
        assignments = [self.assign(parent=parent, child=child, task_id=task_id,
                                   scope=scope, reason=reasons[child])
                       for child in specialists]
        self._receipt({"event": "spawn_plan_created", "parent": parent,
                       "task_id": task_id,
                       "specialists": list(specialists),
                       "reasons": {k: reasons[k] for k in specialists}})
        return assignments

    def record_spawn(self, assignment_id: str, *, child_session_id: str) -> None:
        row = self._assignments.get(assignment_id)
        if row is None:
            raise AuthorizationError("unknown assignment")
        if row["status"] != "assigned":
            raise AuthorizationError("assignment already has a spawn outcome")
        if not child_session_id:
            raise AuthorizationError("spawn receipt requires child session identity")
        row["status"] = "spawned"
        row["child_session_id"] = child_session_id
        self._save()
        self._receipt({"event": "spawn_receipt", **row})

    def has_spawn_receipt(self, assignment_id: str) -> bool:
        row = self._assignments.get(assignment_id)
        return bool(row and row.get("status") == "spawned"
                    and row.get("child_session_id"))

    def _assignment_for(self, actor: str, task_id: str) -> dict:
        rows = [row for row in self._assignments.values()
                if row.get("child") == actor and row.get("task_id") == task_id]
        if not rows or not any(row.get("status") == "spawned" for row in rows):
            raise AuthorizationError(
                f"{actor} has no verified spawn receipt for task {task_id}")
        return next(row for row in rows if row.get("status") == "spawned")

    def authorize(self, *, actor: str, action: str, task_id: Optional[str] = None,
                  path: str = "") -> bool:
        definition = self.definitions.get(actor)
        if definition is None:
            raise AuthorizationError(f"unknown agent: {actor}")
        if action not in definition.capabilities:
            raise AuthorizationError(f"{actor} lacks capability {action}")
        if action in {"write_code", "write_design", "run_tests", "verify",
                      "research_net", "security_scan"}:
            if not task_id:
                raise AuthorizationError(f"{action} requires an assigned task")
            assignment = self._assignment_for(actor, task_id)
            if path:
                target = (self.root / path).resolve()
                if not any(self._within(target, self.root / allowed)
                           for allowed in assignment["scope"]):
                    raise AuthorizationError(
                        f"{actor} path {path!r} is outside assignment scope")
        self._receipt({"event": "authorization", "actor": actor,
                       "action": action, "task_id": task_id, "path": path,
                       "allowed": True})
        return True

    def start_task(self, *, actor: str, task_id: str, task: str,
                   seed=None):
        """Start a task through the runtime authority and CORTEX memory gate.

        Tony-D may start the first orchestration task. A specialist must have
        a real spawn receipt for the task before it can receive task context.
        The CORTEX function then applies the first-task seed/second-task
        injection rule and records the result in project-local state.
        """
        if actor not in self.definitions:
            raise AuthorizationError(f"unknown agent: {actor}")
        if actor != "tony-d-orchestrator":
            self._assignment_for(actor, task_id)
        from ..cortex.tasks import start_task
        result = start_task(self.root, task_id, actor, task, seed=seed)
        self._receipt({"event": "task_started", "actor": actor,
                       "task_id": task_id, "task_number": result.task_number,
                       "seeded": result.seeded,
                       "context_injected": bool(result.context)})
        return result

    @staticmethod
    def _within(target: Path, allowed: Path) -> bool:
        try:
            target.relative_to(allowed.resolve())
            return True
        except ValueError:
            return False
