"""W1 decomposition bridge (design spec section 6).

spec.md -> headless planning call -> plan.json/plan.md -> machine
validation -> deterministic order -> button armed. The AI proposes;
this module refuses bad breakdowns. The 20-30 minute rule is enforced
by PROXY (files touched, single concern, one verification, size_est
cap) because real minutes are unknowable at planning time — actuals
calibrate later through CORTEX observations.
"""
from __future__ import annotations

import re

from danzaboss.planning.decompose import (HARD_STOP_FLAGS, TASK_KINDS, Task,
                                          Verification, VerificationKind)


class PlanningError(ValueError):
    """Unusable or invalid plan. Fail closed (CLAUDE.md standard)."""


class PlanningUnavailable(PlanningError):
    """The boss CLI could not be run at all. Unlike checkpoints there is
    no degraded continuation: nothing downstream can proceed unplanned."""


MAX_WRITES = 3
MAX_SIZE_EST = 30
_ID_RE = re.compile(r"^\d+(\.\d+){0,2}$")
_CHAIN_RE = re.compile(r"\b(and then|and also|as well as)\b")


def parse_plan(data: object) -> tuple[Task, ...]:
    """plan.json object -> Task tree. Shape errors raise one at a time;
    policy violations (ids, sizes, deps) are validate_plan's job so the
    planner AI gets them back as one list, not drip-fed."""
    if not isinstance(data, dict):
        raise PlanningError("plan must be a JSON object")
    spec_ref = data.get("spec_ref")
    if not isinstance(spec_ref, str) or not spec_ref.strip():
        raise PlanningError("plan.spec_ref must be a non-empty string")
    raw_tasks = data.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise PlanningError("plan.tasks must be a non-empty array")
    return tuple(_parse_task(t) for t in raw_tasks)


def _parse_task(raw: object) -> Task:
    if not isinstance(raw, dict):
        raise PlanningError(f"task must be an object: {raw!r}")
    for key in ("id", "description"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise PlanningError(f"task.{key} must be a non-empty string")
    tid = raw["id"].strip()
    verification = None
    if raw.get("verification") is not None:
        v = raw["verification"]
        if not isinstance(v, dict):
            raise PlanningError(f"{tid}: verification must be an object")
        try:
            v_kind = VerificationKind(v.get("kind"))
        except ValueError:
            raise PlanningError(
                f"{tid}: unknown verification kind {v.get('kind')!r}"
            ) from None
        if not isinstance(v.get("detail"), str):
            raise PlanningError(f"{tid}: verification.detail must be a string")
        verification = Verification(kind=v_kind, detail=v["detail"])
    size_est = raw.get("size_est")
    if size_est is not None and (isinstance(size_est, bool)
                                 or not isinstance(size_est, int)):
        raise PlanningError(f"{tid}: size_est must be an integer")
    for key in ("depends_on", "writes", "flags"):
        value = raw.get(key, [])
        if (not isinstance(value, list)
                or not all(isinstance(item, str) for item in value)):
            raise PlanningError(f"{tid}: {key} must be a list of strings")
    kind = raw.get("kind")
    if kind is not None and not isinstance(kind, str):
        raise PlanningError(f"{tid}: kind must be a string")
    subtasks = raw.get("subtasks", [])
    if not isinstance(subtasks, list):
        raise PlanningError(f"{tid}: subtasks must be an array")
    return Task(
        id=tid,
        description=raw["description"].strip(),
        verification=verification,
        subtasks=[_parse_task(s) for s in subtasks],
        kind=kind,
        size_est=size_est,
        depends_on=tuple(raw.get("depends_on", [])),
        writes=tuple(raw.get("writes", [])),
        flags=tuple(raw.get("flags", [])),
    )


def _conjunction_chained(description: str) -> bool:
    """One concern per leaf, judged by proxy: semicolons, chain phrases,
    or repeated ' and ' read as a compound task. A single 'and' passes —
    'parse and validate the header' is one concern."""
    lowered = description.lower()
    return (";" in lowered or bool(_CHAIN_RE.search(lowered))
            or lowered.count(" and ") >= 2)


def validate_plan(tasks: tuple[Task, ...]) -> list[str]:
    """Every structure + size-proxy violation at once — the bounce list
    the planner AI gets back. Empty list = plan accepted."""
    violations: list[str] = []
    seen: dict[str, Task] = {}

    def walk(task: Task, parent: Task | None) -> None:
        tid = task.id
        if not _ID_RE.match(tid):
            violations.append(
                f"{tid}: id must be dotted integers (section.feature.task)")
        elif parent is None:
            if "." in tid:
                violations.append(
                    f"{tid}: top-level tasks must be sections "
                    "(single integer id)")
        elif not (tid.startswith(parent.id + ".")
                  and tid[len(parent.id) + 1:].isdigit()):
            violations.append(
                f"{tid}: id must extend parent {parent.id} by one "
                "integer segment")
        if tid in seen:
            violations.append(f"{tid}: duplicate id")
        seen[tid] = task
        for sub in task.subtasks:
            walk(sub, task)

    for task in tasks:
        walk(task, None)

    for tid, task in seen.items():
        if not task.is_leaf():
            if task.verification is not None:
                violations.append(
                    f"{tid}: internal node must not carry a verification")
            if task.depends_on:
                violations.append(f"{tid}: depends_on is allowed on "
                                  "leaves only")
            continue
        # Leaf size proxies — the enforceable shadow of the 20-30 minute
        # rule (design spec section 6).
        if task.kind not in TASK_KINDS:
            violations.append(
                f"{tid}: kind {task.kind!r} not one of {TASK_KINDS}")
        if (not isinstance(task.size_est, int)
                or not 1 <= task.size_est <= MAX_SIZE_EST):
            violations.append(f"{tid}: size_est must be 1..{MAX_SIZE_EST} "
                              "minutes — split this")
        if not 1 <= len(task.writes) <= MAX_WRITES:
            violations.append(f"{tid}: writes must list 1..{MAX_WRITES} "
                              "files/areas — split this")
        if task.verification is None or not task.verification.is_concrete():
            violations.append(
                f"{tid}: leaf needs exactly one concrete verification")
        if _conjunction_chained(task.description):
            violations.append(f"{tid}: description chains multiple concerns "
                              "— split this")
        bad_flags = [f for f in task.flags if f not in HARD_STOP_FLAGS]
        if bad_flags:
            violations.append(f"{tid}: unknown flags {bad_flags}; allowed: "
                              f"{list(HARD_STOP_FLAGS)}")
        for dep in task.depends_on:
            if dep not in seen:
                violations.append(f"{tid}: depends_on unknown task {dep!r}")
            elif dep == tid or tid.startswith(dep + "."):
                violations.append(f"{tid}: depends_on may not reference "
                                  "itself or an ancestor")
    return violations


def _id_key(task_id: str) -> tuple[int, ...]:
    """Numeric segment order: '1.10' after '1.2' — section order, then id
    (the spec section-6 tie-break)."""
    return tuple(int(part) for part in task_id.split("."))


def _leaves(tasks: tuple[Task, ...]) -> list[Task]:
    out: list[Task] = []
    for task in tasks:
        if task.is_leaf():
            out.append(task)
        else:
            out.extend(_leaves(tuple(task.subtasks)))
    return out


def order_tasks(tasks: tuple[Task, ...]) -> tuple[Task, ...]:
    """Deterministic topological order of the leaves: dependencies first,
    ties broken by numeric id. depends_on may target an internal node —
    that expands to every leaf under it. v1 flattens to a single linear
    order (one builder); `writes` stays on each task so wave planning
    can parallelize later."""
    index: dict[str, Task] = {}

    def register(task: Task) -> None:
        index[task.id] = task
        for sub in task.subtasks:
            register(sub)

    for task in tasks:
        register(task)
    leaves = _leaves(tasks)
    dep_sets: dict[str, set[str]] = {}
    for item in leaves:
        expanded: set[str] = set()
        for target in item.depends_on:
            if target not in index:
                raise PlanningError(
                    f"{item.id}: depends_on unknown task {target!r}")
            expanded.update(t.id for t in _leaves((index[target],)))
        dep_sets[item.id] = expanded
    ordered: list[Task] = []
    done: set[str] = set()
    remaining = {item.id: item for item in leaves}
    while remaining:
        ready = sorted((lid for lid in remaining if dep_sets[lid] <= done),
                       key=_id_key)
        if not ready:
            raise PlanningError("dependency cycle among: "
                                + ", ".join(sorted(remaining, key=_id_key)))
        for lid in ready:
            ordered.append(remaining.pop(lid))
            done.add(lid)
    return tuple(ordered)


def feature_nodes(tasks: tuple[Task, ...]) -> tuple[str, ...]:
    """Feature ids for Rule 3 turn counting: the first two id segments of
    each leaf (a section-level leaf counts as its own feature), unique,
    in the order given — pass order_tasks() output for execution order."""
    out: list[str] = []
    for item in _leaves(tasks):
        feature = ".".join(item.id.split(".")[:2])
        if feature not in out:
            out.append(feature)
    return tuple(out)
