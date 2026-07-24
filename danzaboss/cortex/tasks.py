"""Project task memory gate.

The first task is the CORTEX seed point. It records the task's verified seed
without injecting prior memory. Every later task uses the existing role-aware
retrieval and adaptive context-budget pipeline, then records the context read
in the project-local spend ledger.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .driver_context import compile_driver_context, replaced_tokens
from .events import CaptureLog
from .factory import db_path, open_store
from .graph import GraphStore
from .identity import resolve_project
from .observation import Observation, ObsType
from ..runtime.events import DanzaEvent, EventKind, ProjectEventLog


TASK_STATE_RELPATH = Path(".danza") / "runtime" / "task-memory.json"


@dataclass(frozen=True)
class TaskStart:
    task_id: str
    actor: str
    task_number: int
    seeded: bool
    context: str
    context_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "actor": self.actor,
            "task_number": self.task_number,
            "seeded": self.seeded,
            "context": self.context,
            "context_tokens": self.context_tokens,
        }


def _read_state(root: Path) -> dict:
    try:
        raw = json.loads((root / TASK_STATE_RELPATH).read_text(
            encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "tasks": []}
    if not isinstance(raw, dict) or not isinstance(raw.get("tasks"), list):
        raise ValueError("task-memory.json is corrupt")
    return raw


def _write_state(root: Path, state: dict) -> None:
    path = root / TASK_STATE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, path)


def _seed_observation(seed: Observation | dict, project: str) -> Observation:
    if isinstance(seed, Observation):
        seed.project = project
        return seed
    if not isinstance(seed, dict):
        raise TypeError("first task seed must be an Observation or object")
    fields = dict(seed)
    fields.setdefault("type", ObsType.MILESTONE.value)
    fields.setdefault("title", "Initial task context")
    fields.setdefault("summary", "Verified initial task context")
    fields["project"] = project
    fields.setdefault("confidence", 95)
    fields.setdefault("confidence_source", "repo_verified")
    return Observation(**fields)


def start_task(root: str | os.PathLike, task_id: str, actor: str, task: str,
               *, seed: Observation | dict | None = None) -> TaskStart:
    """Start one project task under the first-task/second-task memory rule."""
    if not task_id.strip() or not actor.strip() or not task.strip():
        raise ValueError("task_id, actor, and task are required")
    project_root = Path(root).resolve()
    state = _read_state(project_root)
    completed = state["tasks"]
    if any(item.get("task_id") == task_id for item in completed):
        raise ValueError(f"task already started: {task_id}")
    number = len(completed) + 1
    project = resolve_project(str(project_root))
    store = open_store(str(project_root))
    seeded = False
    context = ""
    context_tokens = 0
    if number == 1:
        if seed is None:
            raise ValueError("the first task requires a verified CORTEX seed")
        observation = _seed_observation(seed, project)
        store.upsert(observation)
        seeded = True
    else:
        compiled = compile_driver_context(
            store, actor, task, project,
            graph=GraphStore(db_path(str(project_root))))
        context = compiled.render()
        context_tokens = compiled.used
        CaptureLog(db_path(str(project_root))).record_context_read(
            project, actor, compiled.used, compiled.budget,
            compiled.adaptation, replaced=replaced_tokens(compiled))

    completed.append({"task_id": task_id, "actor": actor,
                      "task_number": number, "seeded": seeded})
    state["schema_version"] = 1
    _write_state(project_root, state)
    ProjectEventLog(project_root).append(DanzaEvent(
        kind=EventKind.MEMORY, actor=actor, session_id=task_id,
        payload={"event": "task_started", "task_number": number,
                 "seeded": seeded, "context_injected": bool(context)},
    ))
    return TaskStart(task_id, actor, number, seeded, context, context_tokens)
