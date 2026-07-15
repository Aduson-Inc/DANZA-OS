"""W1 decomposition bridge (design spec section 6).

approved features.json -> headless planning call -> plan.json/plan.md -> machine
validation -> deterministic order -> button armed. New plans are flat,
product-linked atomic leaves; legacy dotted task trees remain readable.
The AI proposes and this module refuses invalid breakdowns.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from danzaboss.planning.decompose import (HARD_STOP_FLAGS, TASK_KINDS, Task,
                                          Verification, VerificationKind)
from danzaboss.workstation import checkpoints
from danzaboss.workstation import project as project_mod
from danzaboss.workstation import product_scope as product_scope_mod
from danzaboss.workstation import templates as templates_mod
from danzaboss.workstation.wizard import Wizard


class PlanningError(ValueError):
    """Unusable or invalid plan. Fail closed (CLAUDE.md standard)."""


class PlanningUnavailable(PlanningError):
    """The boss CLI could not be run at all. Unlike checkpoints there is
    no degraded continuation: nothing downstream can proceed unplanned."""


MAX_WRITES = 3
MAX_SIZE_EST = 20
LEGACY_MAX_SIZE_EST = 30
_LEGACY_ID_RE = re.compile(r"^\d+(\.\d+){0,2}$")
_ATOMIC_ID_RE = re.compile(r"^([1-9]\d*)-([A-Z])$")
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
    feature_id = raw.get("feature_id")
    if feature_id is not None and (isinstance(feature_id, bool)
                                   or not isinstance(feature_id, int)):
        raise PlanningError(f"{tid}: feature_id must be an integer")
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
        feature_id=feature_id,
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


def validate_plan(tasks: tuple[Task, ...], *,
                  require_atomic: bool = False) -> list[str]:
    """Every structure + size-proxy violation at once — the bounce list
    the planner AI gets back. Empty list = plan accepted."""
    violations: list[str] = []
    seen: dict[str, Task] = {}

    def walk(task: Task, parent: Task | None) -> None:
        tid = task.id
        atomic_match = _ATOMIC_ID_RE.match(tid)
        legacy_match = _LEGACY_ID_RE.match(tid)
        if atomic_match:
            if parent is not None or task.subtasks:
                violations.append(
                    f"{tid}: atomic ids must identify top-level leaves")
            expected_feature_id = int(atomic_match.group(1))
            if (type(task.feature_id) is not int
                    or task.feature_id != expected_feature_id):
                violations.append(
                    f"{tid}: feature_id must be numeric {expected_feature_id}")
        elif not legacy_match:
            violations.append(
                f"{tid}: id must be atomic (71-A) or legacy dotted integers")
        else:
            if require_atomic and task.is_leaf():
                violations.append(
                    f"{tid}: new plans require a product-linked atomic id "
                    "such as 71-A")
            if parent is None and "." in tid:
                violations.append(
                    f"{tid}: top-level tasks must be sections "
                    "(single integer id)")
            elif (parent is not None
                  and not (tid.startswith(parent.id + ".")
                           and tid[len(parent.id) + 1:].isdigit())):
                violations.append(
                    f"{tid}: id must extend parent {parent.id} by one "
                    "integer segment")
        if (task.feature_id is not None
                and (type(task.feature_id) is not int
                     or task.feature_id < 1)):
            violations.append(
                f"{tid}: feature_id must be a positive integer")
        if tid in seen:
            violations.append(f"{tid}: duplicate id")
        seen[tid] = task
        for sub in task.subtasks:
            walk(sub, task)

    for task in tasks:
        walk(task, None)

    for tid, task in seen.items():
        if not task.is_leaf():
            if task.feature_id is not None:
                violations.append(
                    f"{tid}: feature_id is allowed on leaves only")
            if task.verification is not None:
                violations.append(
                    f"{tid}: internal node must not carry a verification")
            if task.depends_on:
                violations.append(f"{tid}: depends_on is allowed on "
                                  "leaves only")
            continue
        # Atomic leaves are deliberately short; old dotted plan records keep
        # their historical 30-minute ceiling for read/validation compatibility.
        if task.kind not in TASK_KINDS:
            violations.append(
                f"{tid}: kind {task.kind!r} not one of {TASK_KINDS}")
        size_cap = (MAX_SIZE_EST if _ATOMIC_ID_RE.match(tid)
                    else LEGACY_MAX_SIZE_EST)
        if (isinstance(task.size_est, bool)
                or not isinstance(task.size_est, int)
                or not 1 <= task.size_est <= size_cap):
            violations.append(f"{tid}: size_est must be 1..{size_cap} "
                              "minutes — split this")
        if (not 1 <= len(task.writes) <= MAX_WRITES
                or any(not item.strip() for item in task.writes)):
            violations.append(f"{tid}: writes must list 1..{MAX_WRITES} "
                              "non-empty files/areas — split this")
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


def plan_warnings(tasks: tuple[Task, ...]) -> list[str]:
    """Return accepted calibration warnings, never validation failures."""
    return [f"{task.id}: size_est {task.size_est} minutes is below the "
            "3-minute calibration floor"
            for task in _leaves(tasks)
            if isinstance(task.size_est, int) and task.size_est < 3]


def validate_scope_coverage(tasks: tuple[Task, ...], scope: dict) -> list[str]:
    """Require decomposition to cover each incomplete approved feature only."""
    approved_ids = {
        feature["id"] for feature in scope["features"]
        if feature["status"] != "completed"
    }
    planned_ids = {task.feature_id for task in _leaves(tasks)}
    violations = []
    unknown = sorted(planned_ids - approved_ids, key=lambda value: (value is None,
                                                                    value or 0))
    missing = sorted(approved_ids - planned_ids)
    if unknown:
        violations.append(
            f"atomic units reference product features outside the approved "
            f"product scope: {unknown!r}"
        )
    if missing:
        violations.append(
            f"approved product scope features have no atomic units: {missing!r}"
        )
    return violations


def _id_key(task_id: str) -> tuple[int, ...]:
    """Stable natural order for atomic and legacy dotted identities."""
    atomic = _ATOMIC_ID_RE.match(task_id)
    if atomic:
        return (int(atomic.group(1)), 1, ord(atomic.group(2)) - ord("A"))
    parts = tuple(int(part) for part in task_id.split("."))
    return (parts[0], 0, *parts[1:])


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
    can parallelize later.

    Call after validate_plan: ids are assumed well-formed. Duplicate
    leaf ids still fail closed here (never silently dropped) because
    this function is also usable standalone (P3-M2)."""
    index: dict[str, Task] = {}

    def register(task: Task) -> None:
        index[task.id] = task
        for sub in task.subtasks:
            register(sub)

    for task in tasks:
        register(task)
    leaves = _leaves(tasks)
    dupes = sorted({item.id for n, item in enumerate(leaves)
                    if any(item.id == other.id for other in leaves[:n])},
                   key=_id_key)
    if dupes:
        raise PlanningError("duplicate leaf ids: " + ", ".join(dupes))
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
    """Counted work identities: exactly one entry per ordered leaf.

    The legacy public name remains for callers until Task 5 replaces routing;
    its old dotted-prefix grouping semantics intentionally do not.
    """
    return tuple(item.id for item in _leaves(tasks))


PLAN_JSON_RELPATH = Path(".danza") / "plan.json"
PLAN_MD_RELPATH = Path(".danza") / "plan.md"


def _task_to_dict(task: Task) -> dict:
    """Whitelist serialization of one validated Task. plan.json carries
    only fields the validator guarantees — junk keys from the AI reply
    never reach disk (P3-M1). Empty optionals are omitted."""
    out: dict = {"id": task.id, "description": task.description}
    if task.subtasks:
        out["subtasks"] = [_task_to_dict(sub) for sub in task.subtasks]
        return out
    if task.feature_id is not None:
        out["feature_id"] = task.feature_id
    out["kind"] = task.kind
    out["size_est"] = task.size_est
    out["writes"] = list(task.writes)
    out["verification"] = {"kind": task.verification.kind.value,
                           "detail": task.verification.detail}
    if task.depends_on:
        out["depends_on"] = list(task.depends_on)
    if task.flags:
        out["flags"] = list(task.flags)
    return out


def plan_payload(spec_ref: str, tasks: tuple[Task, ...],
                 ordered: tuple[Task, ...]) -> dict:
    """The persistable plan: whitelist-serialized from the VALIDATED
    task tree with the canonical spec_ref and the computed order — never
    from the raw AI reply (P3-M1). Call after validate_plan: leaves are
    assumed complete (kind, size_est, writes, concrete verification)."""
    order = [task.id for task in ordered]
    # Imported lazily to keep the planner/execution ownership boundary clear:
    # planner defines immutable work; execution owns mutable unit progress.
    from danzaboss.workstation.execution import initial_execution
    return {"spec_ref": spec_ref,
            "tasks": [_task_to_dict(task) for task in tasks],
            "order": order,
            "execution": initial_execution(order),
            "calibration": []}


def render_plan_md(spec_ref: str, ordered: tuple[Task, ...]) -> str:
    """Human-readable numbered build order (.danza/plan.md, the UI right
    panel). Hard-stop flags are called out so the user sees where the
    build will pause (Rules 13-15) — no surprise mid-build stops.

    Call after validate_plan: every ordered task must be a validated
    leaf (concrete verification, kind, size_est) or rendering derefs
    None (P3-M2)."""
    lines = [f"# Plan — {spec_ref}", "",
             f"{len(ordered)} atomic units "
             f"(each ordered leaf counts once: "
             f"{', '.join(feature_nodes(ordered))})", ""]
    for n, task in enumerate(ordered, start=1):
        lines.append(f"{n}. **{task.id}** ({task.kind}, ~{task.size_est}m) "
                     f"{task.description}")
        lines.append(f"   - verify [{task.verification.kind.value}]: "
                     f"{task.verification.detail}")
        lines.append(f"   - writes: {', '.join(task.writes)}")
        if task.feature_id is not None:
            lines.append(f"   - product feature {task.feature_id}")
        if task.depends_on:
            lines.append(f"   - after: {', '.join(task.depends_on)}")
        if task.flags:
            lines.append(f"   - HARD STOP flags: {', '.join(task.flags)} — "
                         "build pauses for user approval here")
        if isinstance(task.size_est, int) and task.size_est < 3:
            lines.append("   - WARNING: estimate is below 3 minutes; "
                         "accepted for calibration")
    return "\n".join(lines) + "\n"


def write_plan(root: str | os.PathLike, payload: dict,
               ordered: tuple[Task, ...]) -> tuple[Path, Path]:
    """Persist .danza/plan.json and .danza/plan.md atomically. `payload`
    comes from plan_payload() — whitelisted fields plus the computed
    `order` so the scheduler never re-derives it. Both are generated
    artifacts, regenerated whole on each planning run — plain overwrite
    is correct here (same reasoning as compiler.write_spec)."""
    json_path = Path(root) / PLAN_JSON_RELPATH
    md_path = Path(root) / PLAN_MD_RELPATH
    json_path.parent.mkdir(parents=True, exist_ok=True)
    for path, text in (
            (json_path, json.dumps(payload, indent=2, sort_keys=True) + "\n"),
            (md_path, render_plan_md(payload["spec_ref"], ordered))):
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    return json_path, md_path


MAX_ROUNDS = 3

PLAN_CONTRACT = (
    "Respond with ONLY a JSON object, no prose around it, shaped exactly:\n"
    '{"spec_ref": str, "tasks": [<task>, ...]}\n'
    'where every <task> is one atomic leaf: {"id": "71-A" form, '
    '"feature_id": matching positive integer product feature id, '
    '"description": non-empty str naming ONE concern (no \'and then\' '
    'chains), '
    '"kind": one of ' + str(list(TASK_KINDS)) + ', '
    '"size_est": estimated minutes (integer 1-' + str(MAX_SIZE_EST)
    + '; target 10-15; 1-2 accepted with warning), "writes": [1-'
    + str(MAX_WRITES) + ' non-empty files or areas], '
    '"depends_on": [task ids] (optional), '
    '"flags": subset of ' + str(list(HARD_STOP_FLAGS)) + ' (optional), '
    '"verification": {"kind": one of '
    + str([k.value for k in VerificationKind])
    + ', "detail": a concrete command or check}}'
)


def build_planning_prompt(spec_text: str, *,
                          testing_defaults: dict | None = None,
                          violations: tuple[str, ...] = (),
                          prior_plan: dict | None = None) -> str:
    """Deterministic planning prompt: the spec IS the context (same
    principle as checkpoints.build_prompt — the headless call needs no
    repo access). Bounce rounds inline the machine's violation list plus
    the rejected plan for re-splitting."""
    lines = [
        "You are the DANZA planner. Decompose the spec below into an",
        "flat ordered list of product-linked atomic leaves. Target",
        "10-15 minute leaves; every estimate must be 1-20 minutes.",
        "Every leaf must be independently",
        "verifiable. Test-first where behavior is specified (business",
        "logic, endpoints, data rules); scaffold/config verify at tier",
        "0-1 (build passes, lint, boots).", ""]
    if testing_defaults:
        lines += ["Test policy from the approved stack template (JSON):",
                  json.dumps(testing_defaults, indent=2, sort_keys=True), ""]
    lines += ["Spec:", spec_text, ""]
    if violations:
        lines.append("Your previous reply was REJECTED by machine "
                     "validation.")
        if prior_plan is not None:
            lines += ["Previous plan (JSON):",
                      json.dumps(prior_plan, indent=2, sort_keys=True)]
        lines.append("Violations to fix (split oversized tasks; keep all "
                     "the work):")
        lines += [f"- {v}" for v in violations]
        lines.append("")
    lines.append(PLAN_CONTRACT)
    return "\n".join(lines)


def run_planning(root: str | os.PathLike, command: list[str], *,
                 timeout: int = 600, max_rounds: int = MAX_ROUNDS,
                 template_dir: str | Path = templates_mod.DEFAULT_DIR) -> dict:
    """Exact approved product scope -> validated plan artifacts.

    Calls the boss CLI headless (same injectable-argv seam as
    checkpoints.run_headless), machine-validates each proposal, bounces
    violations back up to max_rounds, then fails closed: a plan that
    never validates must not arm the button. There is deliberately no
    degraded mode — unlike checkpoints, nothing downstream can proceed
    without a valid plan."""
    if max_rounds < 1:
        raise PlanningError(f"max_rounds must be at least 1, got {max_rounds}")
    try:
        scope = project_mod.require_approved_scope(root)
    except project_mod.ProjectGateConflict as exc:
        raise PlanningError(f"approved product scope required: {exc}") from exc
    spec_text = product_scope_mod.render_feature_list_md(scope)
    spec_ref = project_mod.scope_ref(scope)
    try:
        answers = Wizard(root).answers
    except PlanningError:
        raise
    except ValueError as exc:
        # Corrupt answers.json (load_state) or wizard misuse surfaces as
        # this module's failure mode, not a bare ValueError (P3-M3).
        raise PlanningError(f"unusable onboarding state: {exc}") from exc
    testing_defaults = None
    chosen = answers.get("stack_template")
    if chosen:
        library = {t.key: t
                   for t in templates_mod.load_templates(template_dir)}
        if chosen in library:
            testing_defaults = library[chosen].testing_defaults
    violations: tuple[str, ...] = ()
    prior_plan: dict | None = None
    for round_num in range(1, max_rounds + 1):
        prompt = build_planning_prompt(spec_text,
                                       testing_defaults=testing_defaults,
                                       violations=violations,
                                       prior_plan=prior_plan)
        try:
            reply = checkpoints.run_headless(command, prompt,
                                             timeout=timeout)
        except checkpoints.CheckpointUnavailable as exc:
            raise PlanningUnavailable(str(exc)) from exc
        try:
            data = checkpoints.parse_json_reply(reply)
            tasks = parse_plan(data)
        except (checkpoints.CheckpointError, PlanningError) as exc:
            violations = (f"reply was not a valid plan object: {exc}",)
            prior_plan = None
            continue
        found = validate_plan(tasks, require_atomic=True)
        found.extend(validate_scope_coverage(tasks, scope))
        ordered: tuple[Task, ...] = ()
        if not found:
            try:
                ordered = order_tasks(tasks)
            except PlanningError as exc:
                found = [str(exc)]
        if found:
            violations = tuple(found)
            prior_plan = data
            continue
        payload = plan_payload(spec_ref, tasks, ordered)
        json_path, md_path = write_plan(root, payload, ordered)
        return {"plan": payload, "order": payload["order"],
                "warnings": plan_warnings(tasks),
                "rounds": round_num, "plan_json": str(json_path),
                "plan_md": str(md_path)}
    raise PlanningError(
        f"plan still invalid after {max_rounds} rounds; last violations: "
        + "; ".join(violations))
