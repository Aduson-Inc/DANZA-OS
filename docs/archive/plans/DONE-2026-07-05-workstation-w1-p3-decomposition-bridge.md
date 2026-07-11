# W1-P3: Decomposition Bridge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn an approved `spec.md` into a machine-validated, deterministically ordered task plan (`.danza/plan.json` + `.danza/plan.md`) via one headless planning call with a violation bounce-back loop — the AI proposes, deterministic code refuses bad breakdowns.

**Architecture:** Extend the existing task record (`danzaboss/planning/decompose.py` + `plan_schema.json`) with the W1 §6 fields (hierarchical id, kind, size_est, depends_on, writes, flags). A new `danzaboss/workstation/planner.py` holds the bridge: `parse_plan` (fail-closed shape), `validate_plan` (size proxies enforcing the 20–30-minute rule), `order_tasks` (deterministic topological order, cycles rejected), `render_plan_md`/`write_plan` (artifacts), and `run_planning` (headless call through the same injectable-argv seam as P2's checkpoints, max 3 rounds of violation bounce-back, fail closed on exhaustion). The Upgrade-#4 verification gate is reused unchanged.

**Tech Stack:** Python 3.10+ stdlib only. `unittest` (auto-discovered by `danzaboss/run_tests.sh`).

**Spec:** `docs/superpowers/specs/2026-07-05-workstation-onboarding-design.md` §6 (decomposition engine). Phase map: `docs/superpowers/plans/DONE-2026-07-05-workstation-w1-p1-engine-foundations.md` (this = P3). Implementers do NOT need to read either — every task below is self-contained.

**Placement decision:** spec §6 says "extended decompose.py"; that is satisfied by extending the `Task` record there (shared vocabulary, gate unchanged). W1-specific *policy* (id shape, proxies, ordering, headless call) lives in `danzaboss/workstation/planner.py`, matching the P1/P2 precedent that W1 modules live under `workstation/`.

**Resolves deferred item (P1 final review):** `SPEC_RELPATH` constant in `compiler.py` (Task 4).

## Model Assignment & Token Discipline

- **Per-task model in each header.** `fable (inline)` = orchestrator implements directly (validator, ordering, headless loop — the "important files"). `sonnet` = dispatch to a sonnet subagent (schema/record extension, rendering/artifacts — fully specified below).
- **No per-task reviews** (user decision, carried from P1/P2): single whole-branch review at Task 6, with prior deferred-minor lists as triage input.
- **Subagents must not read** the design spec, `CLAUDE.md`, the constitution, or any module not listed in their task's Files block. This plan is the single source.
- Run steps back-to-back; don't idle past the prompt-cache TTL.

## Global Constraints

- Python 3.10+, **stdlib only** — no pip installs anywhere in `danzaboss/`.
- PEP 8, 4-space indent, `snake_case`, type hints on all public functions, docstrings that state *why*.
- **Fail closed:** validation raises `PlanningError`; never continue past bad state.
- **Deterministic:** no randomness, no wall-clock reads in logic; same inputs → same outputs.
- **Hermetic tests:** operate only on `tempfile` fixture roots; never touch this repo's real `.danza/`, never network. Tests begin with `import _bootstrap  # noqa`.
- Test run incantation (from repo root): `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.<module> -v`; full suite: `./danzaboss/run_tests.sh` (currently 502 OK, skipped=13).
- Commit after every task; message style matches repo history.

---

### Task 1: Task record + schema extension

**Model:** sonnet

**Files:**
- Modify: `danzaboss/planning/decompose.py`
- Modify: `danzaboss/planning/plan_schema.json` (replace whole file — it is a contract doc, shown below)
- Test: `danzaboss/tests/test_plan_record.py`

**Interfaces:**
- Consumes: existing `Task`, `Verification`, `VerificationKind` in `decompose.py`.
- Produces: `Task` gains optional fields `kind: Optional[str]`, `size_est: Optional[int]`, `depends_on: tuple[str, ...]`, `writes: tuple[str, ...]`, `flags: tuple[str, ...]` (all defaulted — existing constructors keep working); module constants `TASK_KINDS: tuple[str, ...]` and `HARD_STOP_FLAGS: tuple[str, ...]`. Tasks 2–5 import all of these.

- [ ] **Step 1: Write the failing test**

`danzaboss/tests/test_plan_record.py`:

```python
"""W1-P3 task record extension: plan_schema.json and decompose.Task gain
the design-spec section-6 planning fields without disturbing the
Upgrade-#4 verifiable-task gate."""
import json
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.planning.decompose import (HARD_STOP_FLAGS, TASK_KINDS, Task,
                                          Verification, VerificationKind)

SCHEMA = Path(__file__).resolve().parents[1] / "planning" / "plan_schema.json"


class SchemaExtension(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.task_def = self.schema["definitions"]["task"]
        self.props = self.task_def["properties"]

    def test_new_fields_declared(self):
        for name in ("kind", "size_est", "depends_on", "writes", "flags"):
            self.assertIn(name, self.props)

    def test_kind_enum_matches_module_constant(self):
        self.assertEqual(tuple(self.props["kind"]["enum"]), TASK_KINDS)

    def test_size_est_capped_at_30(self):
        self.assertEqual(self.props["size_est"]["maximum"], 30)

    def test_writes_capped_at_3_files(self):
        self.assertEqual(self.props["writes"]["maxItems"], 3)

    def test_flags_enum_matches_hard_stops(self):
        self.assertEqual(tuple(self.props["flags"]["items"]["enum"]),
                         HARD_STOP_FLAGS)

    def test_new_fields_stay_optional(self):
        self.assertEqual(self.task_def["required"], ["id", "description"])


class TaskRecordDefaults(unittest.TestCase):
    def test_legacy_construction_still_works(self):
        task = Task(id="t1", description="build the thing")
        self.assertIsNone(task.kind)
        self.assertIsNone(task.size_est)
        self.assertEqual(task.depends_on, ())
        self.assertEqual(task.writes, ())
        self.assertEqual(task.flags, ())

    def test_gate_ignores_new_fields(self):
        task = Task(id="t1", description="one thing", kind="backend",
                    size_est=20, writes=("a.py",),
                    verification=Verification(
                        VerificationKind.AUTOMATED_TEST, "pytest -k x"))
        self.assertTrue(task.ready_for_dispatch())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_plan_record -v`
Expected: FAIL — `ImportError: cannot import name 'HARD_STOP_FLAGS'`

- [ ] **Step 3: Write the implementation**

In `danzaboss/planning/decompose.py`, add after the `VerificationKind` class:

```python
# W1 plan-record vocabulary (workstation design spec section 6). The
# workstation planner validates against these; the dispatch gate below
# stays verification-only.
TASK_KINDS = ("scaffold", "backend", "frontend", "db-migration",
              "integration", "config", "design", "test")
HARD_STOP_FLAGS = ("auth", "payment", "db-schema")
```

In the `Task` dataclass, add after the `subtasks` field (keep the existing fields untouched):

```python
    # W1 planning fields (design spec section 6) — optional so pre-W1
    # callers and tests construct Tasks exactly as before.
    kind: Optional[str] = None
    size_est: Optional[int] = None       # estimated minutes; policy cap 30
    depends_on: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()         # files/areas touched (wave planning)
    flags: tuple[str, ...] = ()          # hard-stop markers (Rules 13-15)
```

Replace `danzaboss/planning/plan_schema.json` wholesale with:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "DANZABOSS plan",
  "description": "Derived from spec.md. A tree of tasks; every leaf must carry a verification method (Upgrade #4). W1 (workstation design spec section 6) adds hierarchical ids, kind, size_est, depends_on, writes, flags.",
  "type": "object",
  "required": ["spec_ref", "tasks"],
  "properties": {
    "spec_ref": {"type": "string", "description": "path/hash of the spec this plan derives from"},
    "order": {"type": "array", "items": {"type": "string"}, "description": "leaf ids in validated execution order (written by the workstation planner)"},
    "tasks": {"type": "array", "items": {"$ref": "#/definitions/task"}}
  },
  "definitions": {
    "task": {
      "type": "object",
      "required": ["id", "description"],
      "properties": {
        "id": {"type": "string", "pattern": "^\\d+(\\.\\d+){0,2}$", "description": "hierarchical section.feature.task"},
        "description": {"type": "string", "description": "ONE concern; conjunction chains are rejected by the validator"},
        "kind": {"enum": ["scaffold", "backend", "frontend", "db-migration", "integration", "config", "design", "test"]},
        "size_est": {"type": "integer", "minimum": 1, "maximum": 30, "description": "estimated minutes; hard cap 30 (split larger tasks)"},
        "depends_on": {"type": "array", "items": {"type": "string"}, "description": "task ids that must complete first (leaves only)"},
        "writes": {"type": "array", "items": {"type": "string"}, "maxItems": 3, "description": "files/areas touched; kept for wave planning"},
        "flags": {"type": "array", "items": {"enum": ["auth", "payment", "db-schema"]}, "description": "hard-stop markers surfaced at planning time (Rules 13-15)"},
        "verification": {
          "type": ["object", "null"],
          "required": ["kind", "detail"],
          "properties": {
            "kind": {"enum": ["automated_test", "command_output", "http_check", "schema_check", "manual_gate"]},
            "detail": {"type": "string", "minLength": 1}
          }
        },
        "subtasks": {"type": "array", "items": {"$ref": "#/definitions/task"}}
      }
    }
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_plan_record -v`
Expected: PASS (8 tests)

Then confirm nothing broke: `./danzaboss/run_tests.sh`
Expected: 510 OK (skipped=13), zero failures.

- [ ] **Step 5: Commit**

```bash
git add danzaboss/planning/decompose.py danzaboss/planning/plan_schema.json danzaboss/tests/test_plan_record.py
git commit -m "feat(planning): W1-P3 T1 task record + plan schema extension — kind, size_est, deps, writes, flags"
```

---

### Task 2: Plan parsing + size-proxy validator (`planner.py`)

**Model:** fable (inline)

**Files:**
- Create: `danzaboss/workstation/planner.py`
- Test: `danzaboss/tests/test_workstation_planner.py`

**Interfaces:**
- Consumes: `Task`, `Verification`, `VerificationKind`, `TASK_KINDS`, `HARD_STOP_FLAGS` from `danzaboss.planning.decompose` (Task 1).
- Produces: `PlanningError(ValueError)`, `PlanningUnavailable(PlanningError)`, `MAX_WRITES = 3`, `MAX_SIZE_EST = 30`, `parse_plan(data: object) -> tuple[Task, ...]`, `validate_plan(tasks: tuple[Task, ...]) -> list[str]` (violation strings; empty = accepted). Tasks 3–5 extend this module.

**Design notes the implementer must honor:**
1. `parse_plan` rejects *shape* errors one at a time (raise); `validate_plan` collects *policy* violations all at once — the bounce list the planner AI gets back.
2. The 20–30-minute rule is enforced by PROXY (≤3 writes, one concern, exactly one concrete verification, `size_est ≤ 30`) because real minutes are unknowable at planning time.
3. `depends_on` is allowed on leaves only; it may target any existing id (internal targets expand at ordering time) but never the leaf itself or its own ancestor (that expansion would self-cycle).

- [ ] **Step 1: Write the failing test**

`danzaboss/tests/test_workstation_planner.py`:

```python
"""W1-P3 plan validation: the size proxies that enforce the 20-30 minute
rule (design spec section 6). The AI proposes; these checks refuse."""
import unittest

import _bootstrap  # noqa
from danzaboss.workstation.planner import (PlanningError, parse_plan,
                                           validate_plan)


def leaf(tid, desc="implement one focused change", **over):
    base = {"id": tid, "description": desc, "kind": "backend",
            "size_est": 20, "writes": ["src/x.py"],
            "verification": {"kind": "automated_test",
                             "detail": "pytest tests/test_x.py"}}
    base.update(over)
    return base


def plan(*tasks):
    return {"spec_ref": ".danza/spec.md", "tasks": list(tasks)}


VALID = plan(
    {"id": "1", "description": "accounts area", "subtasks": [
        {"id": "1.1", "description": "signup feature", "subtasks": [
            leaf("1.1.1"),
            leaf("1.1.2", depends_on=["1.1.1"]),
        ]},
        leaf("1.2"),
    ]},
    {"id": "2", "description": "billing area", "subtasks": [
        leaf("2.1", flags=["payment"], depends_on=["1"]),
    ]},
)


class ParsePlan(unittest.TestCase):
    def test_valid_plan_parses(self):
        tasks = parse_plan(VALID)
        self.assertEqual([t.id for t in tasks], ["1", "2"])
        self.assertEqual(tasks[0].subtasks[0].subtasks[1].depends_on,
                         ("1.1.1",))
        self.assertEqual(tasks[1].subtasks[0].flags, ("payment",))

    def test_non_object_rejected(self):
        with self.assertRaises(PlanningError):
            parse_plan([1, 2])

    def test_missing_spec_ref_rejected(self):
        with self.assertRaises(PlanningError):
            parse_plan({"tasks": [leaf("1")]})

    def test_empty_tasks_rejected(self):
        with self.assertRaises(PlanningError):
            parse_plan({"spec_ref": "s", "tasks": []})

    def test_unknown_verification_kind_rejected(self):
        with self.assertRaises(PlanningError):
            parse_plan(plan(leaf("1", verification={"kind": "vibes",
                                                    "detail": "trust me"})))

    def test_boolean_size_est_rejected(self):
        with self.assertRaises(PlanningError):
            parse_plan(plan(leaf("1", size_est=True)))

    def test_non_list_depends_on_rejected(self):
        with self.assertRaises(PlanningError):
            parse_plan(plan(leaf("1", depends_on="1.2")))


class ValidatePlan(unittest.TestCase):
    def check(self, plan_dict):
        return validate_plan(parse_plan(plan_dict))

    def test_valid_plan_has_no_violations(self):
        self.assertEqual(self.check(VALID), [])

    def test_non_numeric_id(self):
        found = self.check(plan(leaf("a")))
        self.assertTrue(any("dotted integers" in v for v in found), found)

    def test_top_level_must_be_section(self):
        found = self.check(plan(leaf("1.1")))
        self.assertTrue(any("top-level" in v for v in found), found)

    def test_child_must_extend_parent(self):
        found = self.check(plan({"id": "1", "description": "area",
                                 "subtasks": [leaf("2.1")]}))
        self.assertTrue(any("extend parent" in v for v in found), found)

    def test_duplicate_ids(self):
        found = self.check(plan(
            {"id": "1", "description": "area",
             "subtasks": [leaf("1.1"), leaf("1.1")]}))
        self.assertTrue(any("duplicate" in v for v in found), found)

    def test_internal_node_with_verification(self):
        found = self.check(plan(
            {"id": "1", "description": "area",
             "verification": {"kind": "manual_gate", "detail": "look"},
             "subtasks": [leaf("1.1")]}))
        self.assertTrue(any("internal node" in v for v in found), found)

    def test_internal_node_with_depends_on(self):
        found = self.check(plan(
            {"id": "1", "description": "area", "depends_on": ["2"],
             "subtasks": [leaf("1.1")]},
            {"id": "2", "description": "other", "subtasks": [leaf("2.1")]}))
        self.assertTrue(any("leaves only" in v for v in found), found)

    def test_unknown_kind(self):
        found = self.check(plan(leaf("1", kind="poetry")))
        self.assertTrue(any("kind" in v for v in found), found)

    def test_missing_kind(self):
        found = self.check(plan(leaf("1", kind=None)))
        self.assertTrue(any("kind" in v for v in found), found)

    def test_oversized_leaf_told_to_split(self):
        found = self.check(plan(leaf("1", size_est=90)))
        self.assertTrue(any("split this" in v for v in found), found)

    def test_too_many_writes(self):
        found = self.check(plan(leaf("1", writes=["a", "b", "c", "d"])))
        self.assertTrue(any("writes" in v for v in found), found)

    def test_empty_writes(self):
        found = self.check(plan(leaf("1", writes=[])))
        self.assertTrue(any("writes" in v for v in found), found)

    def test_missing_verification(self):
        found = self.check(plan(leaf("1", verification=None)))
        self.assertTrue(any("concrete verification" in v for v in found),
                        found)

    def test_conjunction_chain_rejected(self):
        found = self.check(plan(leaf(
            "1", desc="add the model and then wire the route and also test")))
        self.assertTrue(any("multiple concerns" in v for v in found), found)

    def test_semicolon_chain_rejected(self):
        found = self.check(plan(leaf("1", desc="add model; wire route")))
        self.assertTrue(any("multiple concerns" in v for v in found), found)

    def test_single_and_is_allowed(self):
        self.assertEqual(
            self.check(plan(leaf("1", desc="parse and validate the header"))),
            [])

    def test_unknown_flag(self):
        found = self.check(plan(leaf("1", flags=["gdpr"])))
        self.assertTrue(any("flags" in v for v in found), found)

    def test_unknown_dependency(self):
        found = self.check(plan(leaf("1", depends_on=["9.9"])))
        self.assertTrue(any("unknown task" in v for v in found), found)

    def test_ancestor_dependency_rejected(self):
        found = self.check(plan(
            {"id": "1", "description": "area",
             "subtasks": [leaf("1.1", depends_on=["1"])]}))
        self.assertTrue(any("ancestor" in v for v in found), found)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_planner -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'danzaboss.workstation.planner'`

- [ ] **Step 3: Write the implementation**

`danzaboss/workstation/planner.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_planner -v`
Expected: PASS (25 tests)

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/planner.py danzaboss/tests/test_workstation_planner.py
git commit -m "feat(workstation): W1-P3 T2 plan parsing + size-proxy validator"
```

---

### Task 3: Deterministic topological ordering + feature nodes

**Model:** fable (inline)

**Files:**
- Modify: `danzaboss/workstation/planner.py` (append)
- Test: `danzaboss/tests/test_workstation_plan_order.py`

**Interfaces:**
- Consumes: `Task`, `PlanningError`, `parse_plan` from Task 2.
- Produces: `order_tasks(tasks: tuple[Task, ...]) -> tuple[Task, ...]` (ordered leaves; raises `PlanningError` on cycles/unknown targets) and `feature_nodes(tasks: tuple[Task, ...]) -> tuple[str, ...]` (Rule 3 feature ids, unique, in the order given — pass `order_tasks(...)` output for execution order). Task 4's renderer and Task 5's loop call both.

- [ ] **Step 1: Write the failing test**

`danzaboss/tests/test_workstation_plan_order.py`:

```python
"""W1-P3 deterministic ordering: topological over depends_on, tie-break
section order then id; cycles rejected (design spec section 6)."""
import unittest

import _bootstrap  # noqa
from danzaboss.workstation.planner import (PlanningError, feature_nodes,
                                           order_tasks, parse_plan)


def leaf(tid, **over):
    base = {"id": tid, "description": "one focused change",
            "kind": "backend", "size_est": 15, "writes": ["src/x.py"],
            "verification": {"kind": "automated_test",
                             "detail": "pytest tests/test_x.py"}}
    base.update(over)
    return base


def tree(*tasks):
    return parse_plan({"spec_ref": "spec", "tasks": list(tasks)})


class Ordering(unittest.TestCase):
    def test_independent_leaves_in_id_order(self):
        tasks = tree({"id": "1", "description": "a",
                      "subtasks": [leaf("1.2"), leaf("1.1")]})
        self.assertEqual([t.id for t in order_tasks(tasks)], ["1.1", "1.2"])

    def test_dependency_beats_id_order(self):
        tasks = tree(
            {"id": "1", "description": "a",
             "subtasks": [leaf("1.1", depends_on=["2.1"])]},
            {"id": "2", "description": "b", "subtasks": [leaf("2.1")]})
        self.assertEqual([t.id for t in order_tasks(tasks)], ["2.1", "1.1"])

    def test_internal_target_expands_to_leaves(self):
        tasks = tree(
            {"id": "1", "description": "a",
             "subtasks": [leaf("1.1"), leaf("1.2")]},
            {"id": "2", "description": "b",
             "subtasks": [leaf("2.1", depends_on=["1"])]})
        order = [t.id for t in order_tasks(tasks)]
        self.assertLess(order.index("1.2"), order.index("2.1"))

    def test_cycle_rejected(self):
        tasks = tree(
            {"id": "1", "description": "a", "subtasks": [
                leaf("1.1", depends_on=["1.2"]),
                leaf("1.2", depends_on=["1.1"])]})
        with self.assertRaises(PlanningError) as ctx:
            order_tasks(tasks)
        self.assertIn("1.1", str(ctx.exception))

    def test_unknown_target_fails_closed(self):
        tasks = tree({"id": "1", "description": "a",
                      "subtasks": [leaf("1.1", depends_on=["9.9"])]})
        with self.assertRaises(PlanningError):
            order_tasks(tasks)

    def test_deterministic(self):
        tasks = tree(
            {"id": "1", "description": "a", "subtasks": [
                leaf("1.1"), leaf("1.2", depends_on=["2.1"])]},
            {"id": "2", "description": "b", "subtasks": [leaf("2.1")]})
        self.assertEqual([t.id for t in order_tasks(tasks)],
                         [t.id for t in order_tasks(tasks)])


class FeatureNodes(unittest.TestCase):
    def test_features_are_first_two_segments_in_order(self):
        tasks = tree(
            {"id": "1", "description": "a", "subtasks": [
                {"id": "1.1", "description": "f", "subtasks": [
                    leaf("1.1.1"), leaf("1.1.2")]},
                leaf("1.2")]},
            {"id": "2", "description": "b", "subtasks": [leaf("2.1")]})
        self.assertEqual(feature_nodes(order_tasks(tasks)),
                         ("1.1", "1.2", "2.1"))

    def test_section_level_leaf_counts_as_own_feature(self):
        tasks = tree(leaf("1"))
        self.assertEqual(feature_nodes(tasks), ("1",))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_plan_order -v`
Expected: FAIL — `ImportError: cannot import name 'feature_nodes'`

- [ ] **Step 3: Write the implementation**

Append to `danzaboss/workstation/planner.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_plan_order -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/planner.py danzaboss/tests/test_workstation_plan_order.py
git commit -m "feat(workstation): W1-P3 T3 deterministic topo ordering + Rule-3 feature nodes"
```

---

### Task 4: Plan artifacts (`plan.json` + `plan.md`) + `SPEC_RELPATH`

**Model:** sonnet

**Files:**
- Modify: `danzaboss/workstation/planner.py` (append; extend imports)
- Modify: `danzaboss/workstation/compiler.py` (add `SPEC_RELPATH`, use it in `write_spec`)
- Test: `danzaboss/tests/test_workstation_plan_artifacts.py`

**Interfaces:**
- Consumes: `Task`, `parse_plan`, `order_tasks`, `feature_nodes` from Tasks 2–3.
- Produces: `PLAN_JSON_RELPATH: Path` (`.danza/plan.json`), `PLAN_MD_RELPATH: Path` (`.danza/plan.md`), `render_plan_md(plan: dict, ordered: tuple[Task, ...]) -> str`, `write_plan(root, plan: dict, ordered: tuple[Task, ...]) -> tuple[Path, Path]`; `compiler.SPEC_RELPATH: Path` (`.danza/spec.md`). Task 5's `run_planning` calls `write_plan` and reads `compiler.SPEC_RELPATH`; P5 (server) renders both artifacts.

- [ ] **Step 1: Write the failing test**

`danzaboss/tests/test_workstation_plan_artifacts.py`:

```python
"""W1-P3 plan artifacts: .danza/plan.json + plan.md, atomic writes;
SPEC_RELPATH shared constant (P1 final-review deferred item)."""
import json
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.workstation import compiler
from danzaboss.workstation.planner import (PLAN_JSON_RELPATH, PLAN_MD_RELPATH,
                                           order_tasks, parse_plan,
                                           render_plan_md, write_plan)

PLAN = {"spec_ref": ".danza/spec.md", "tasks": [
    {"id": "1", "description": "core area", "subtasks": [
        {"id": "1.1", "description": "log a session", "kind": "backend",
         "size_est": 25, "writes": ["src/log.py"], "flags": ["auth"],
         "verification": {"kind": "automated_test",
                          "detail": "pytest tests/test_log.py"}},
        {"id": "1.2", "description": "weekly summary", "kind": "backend",
         "size_est": 20, "writes": ["src/summary.py"],
         "depends_on": ["1.1"],
         "verification": {"kind": "automated_test",
                          "detail": "pytest tests/test_summary.py"}}]}]}


class RenderPlanMd(unittest.TestCase):
    def setUp(self):
        self.ordered = order_tasks(parse_plan(PLAN))
        self.text = render_plan_md(PLAN, self.ordered)

    def test_numbered_in_execution_order(self):
        self.assertIn("1. **1.1**", self.text)
        self.assertIn("2. **1.2**", self.text)

    def test_verification_rendered(self):
        self.assertIn("verify [automated_test]: pytest tests/test_log.py",
                      self.text)

    def test_hard_stop_flag_called_out(self):
        self.assertIn("HARD STOP", self.text)

    def test_dependency_rendered(self):
        self.assertIn("after: 1.1", self.text)


class WritePlan(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.ordered = order_tasks(parse_plan(PLAN))

    def test_writes_both_artifacts(self):
        json_path, md_path = write_plan(self.root, PLAN, self.ordered)
        self.assertEqual(json_path, self.root / PLAN_JSON_RELPATH)
        self.assertEqual(md_path, self.root / PLAN_MD_RELPATH)
        self.assertTrue(json_path.exists())
        self.assertTrue(md_path.exists())

    def test_plan_json_carries_execution_order(self):
        json_path, _ = write_plan(self.root, PLAN, self.ordered)
        on_disk = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["order"], ["1.1", "1.2"])
        self.assertEqual(on_disk["spec_ref"], PLAN["spec_ref"])

    def test_no_tmp_files_left(self):
        write_plan(self.root, PLAN, self.ordered)
        self.assertEqual(list((self.root / ".danza").glob("*.tmp")), [])

    def test_rewrite_overwrites_clean(self):
        write_plan(self.root, PLAN, self.ordered)
        json_path, _ = write_plan(self.root, PLAN, self.ordered)
        on_disk = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["order"], ["1.1", "1.2"])


class SpecRelpath(unittest.TestCase):
    def test_write_spec_uses_shared_constant(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = compiler.write_spec(tmp, "# Spec — X\n")
            self.assertEqual(path, Path(tmp) / compiler.SPEC_RELPATH)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_plan_artifacts -v`
Expected: FAIL — `ImportError: cannot import name 'PLAN_JSON_RELPATH'`

- [ ] **Step 3: Write the implementation**

In `danzaboss/workstation/compiler.py`, add below the imports (before `CADENCE_LABELS`):

```python
SPEC_RELPATH = Path(".danza") / "spec.md"
```

and change `write_spec`'s first line from:

```python
    path = Path(root) / ".danza" / "spec.md"
```

to:

```python
    path = Path(root) / SPEC_RELPATH
```

In `danzaboss/workstation/planner.py`, extend the import block at the top to:

```python
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from danzaboss.planning.decompose import (HARD_STOP_FLAGS, TASK_KINDS, Task,
                                          Verification, VerificationKind)
```

and append:

```python
PLAN_JSON_RELPATH = Path(".danza") / "plan.json"
PLAN_MD_RELPATH = Path(".danza") / "plan.md"


def render_plan_md(plan: dict, ordered: tuple[Task, ...]) -> str:
    """Human-readable numbered build order (.danza/plan.md, the UI right
    panel). Hard-stop flags are called out so the user sees where the
    build will pause (Rules 13-15) — no surprise mid-build stops."""
    features = feature_nodes(ordered)
    lines = [f"# Plan — {plan['spec_ref']}", "",
             f"{len(ordered)} tasks across {len(features)} features "
             f"(Rule 3 counts feature nodes: {', '.join(features)})", ""]
    for n, task in enumerate(ordered, start=1):
        lines.append(f"{n}. **{task.id}** ({task.kind}, ~{task.size_est}m) "
                     f"{task.description}")
        lines.append(f"   - verify [{task.verification.kind.value}]: "
                     f"{task.verification.detail}")
        lines.append(f"   - writes: {', '.join(task.writes)}")
        if task.depends_on:
            lines.append(f"   - after: {', '.join(task.depends_on)}")
        if task.flags:
            lines.append(f"   - HARD STOP flags: {', '.join(task.flags)} — "
                         "build pauses for user approval here")
    return "\n".join(lines) + "\n"


def write_plan(root: str | os.PathLike, plan: dict,
               ordered: tuple[Task, ...]) -> tuple[Path, Path]:
    """Persist .danza/plan.json and .danza/plan.md atomically. plan.json
    carries the accepted plan plus the computed `order` so the scheduler
    never re-derives it. Both are generated artifacts, regenerated whole
    on each planning run — plain overwrite is correct here (same
    reasoning as compiler.write_spec)."""
    payload = dict(plan)
    payload["order"] = [task.id for task in ordered]
    json_path = Path(root) / PLAN_JSON_RELPATH
    md_path = Path(root) / PLAN_MD_RELPATH
    json_path.parent.mkdir(parents=True, exist_ok=True)
    for path, text in (
            (json_path, json.dumps(payload, indent=2, sort_keys=True) + "\n"),
            (md_path, render_plan_md(plan, ordered))):
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    return json_path, md_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_plan_artifacts -v`
Expected: PASS (9 tests)

Also re-run the compiler tests (write_spec changed): `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_compiler -v`
Expected: PASS, same count as before this task.

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/planner.py danzaboss/workstation/compiler.py danzaboss/tests/test_workstation_plan_artifacts.py
git commit -m "feat(workstation): W1-P3 T4 plan artifacts + shared SPEC_RELPATH"
```

---

### Task 5: Headless planning call with bounce-back rounds

**Model:** fable (inline)

**Files:**
- Modify: `danzaboss/workstation/planner.py` (append; extend imports)
- Test: `danzaboss/tests/test_workstation_planning_call.py`

**Interfaces:**
- Consumes: `checkpoints.run_headless`, `checkpoints.parse_json_reply`, `checkpoints.CheckpointError`, `checkpoints.CheckpointUnavailable` (P2); `compiler.SPEC_RELPATH` (Task 4); `templates_mod.load_templates`/`DEFAULT_DIR` (P1); `Wizard` (P1); everything from Tasks 2–4.
- Produces: `MAX_ROUNDS = 3`, `PLAN_CONTRACT: str`, `build_planning_prompt(spec_text: str, *, testing_defaults: dict | None = None, violations: tuple[str, ...] = (), prior_plan: dict | None = None) -> str`, `run_planning(root, command: list[str], *, timeout: int = 600, max_rounds: int = MAX_ROUNDS, template_dir=templates_mod.DEFAULT_DIR) -> dict` returning `{"plan", "order", "rounds", "plan_json", "plan_md"}`. P5 (server) calls `run_planning` at final approval to arm the button.

**Design notes the implementer must honor:**
1. Reuse P2's seam exactly: `command` is an injectable argv prefix, the prompt rides as the final argument (what lets tests substitute a stub interpreter). Unreachable CLI → `PlanningUnavailable`; **no degraded mode** — unlike checkpoints, nothing downstream can proceed without a valid plan.
2. Each round = one call. A garbage reply (unparseable / wrong shape) consumes a round and bounces back as a violation. Artifacts are written only on success; exhaustion raises with the last violation list (fail closed).
3. `parse_json_reply` already unwraps the `{"result": <text>}` CLI envelope; plan objects never carry a `result` key, so reuse is safe.

- [ ] **Step 1: Write the failing test**

`danzaboss/tests/test_workstation_planning_call.py`:

```python
"""W1-P3 headless planning call: injectable-argv seam (P2 pattern),
machine validation with bounce-back rounds, fail closed on exhaustion."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.workstation import compiler
from danzaboss.workstation.planner import (PLAN_JSON_RELPATH, PlanningError,
                                           PlanningUnavailable, run_planning)

VALID_PLAN = {"spec_ref": ".danza/spec.md", "tasks": [
    {"id": "1", "description": "core area", "subtasks": [
        {"id": "1.1", "description": "log a session", "kind": "backend",
         "size_est": 25, "writes": ["src/log.py"],
         "verification": {"kind": "automated_test",
                          "detail": "pytest tests/test_log.py"}}]}]}

OVERSIZED_PLAN = {"spec_ref": ".danza/spec.md", "tasks": [
    {"id": "1", "description": "core area", "subtasks": [
        {"id": "1.1", "description": "log a session", "kind": "backend",
         "size_est": 90, "writes": ["src/log.py"],
         "verification": {"kind": "automated_test",
                          "detail": "pytest tests/test_log.py"}}]}]}

# Stub boss CLI: replies from replies.json in call order, records each
# prompt so tests can assert on bounce-back content.
STUB = """\
import json, sys
from pathlib import Path
here = Path(__file__).parent
state = here / "calls.txt"
n = int(state.read_text()) if state.exists() else 0
state.write_text(str(n + 1))
(here / f"prompt{n}.txt").write_text(sys.argv[-1])
replies = json.loads((here / "replies.json").read_text())
print(replies[min(n, len(replies) - 1)])
"""


class PlanningCall(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        spec = self.root / compiler.SPEC_RELPATH
        spec.parent.mkdir(parents=True)
        spec.write_text("# Spec — DrumLog\n\n## 1. Intent\nTrack practice.\n")
        self.stub_dir = self.root / "stub"
        self.stub_dir.mkdir()
        self.stub = self.stub_dir / "stub.py"
        self.stub.write_text(STUB)

    def command(self, *replies):
        (self.stub_dir / "replies.json").write_text(json.dumps(list(replies)))
        return [sys.executable, str(self.stub)]

    def prompt(self, n):
        return (self.stub_dir / f"prompt{n}.txt").read_text()

    def test_valid_first_round(self):
        result = run_planning(self.root, self.command(json.dumps(VALID_PLAN)))
        self.assertEqual(result["rounds"], 1)
        self.assertEqual(result["order"], ["1.1"])
        self.assertTrue((self.root / PLAN_JSON_RELPATH).exists())

    def test_result_envelope_unwrapped(self):
        reply = json.dumps({"result": json.dumps(VALID_PLAN)})
        result = run_planning(self.root, self.command(reply))
        self.assertEqual(result["rounds"], 1)

    def test_prompt_contains_spec(self):
        run_planning(self.root, self.command(json.dumps(VALID_PLAN)))
        self.assertIn("Track practice.", self.prompt(0))

    def test_stack_testing_defaults_in_prompt(self):
        answers = self.root / ".danza" / "onboarding" / "answers.json"
        answers.parent.mkdir(parents=True)
        answers.write_text(json.dumps(
            {"answers": {"stack_template": "saas-ts"}, "steps": {}}))
        run_planning(self.root, self.command(json.dumps(VALID_PLAN)))
        self.assertIn("vitest", self.prompt(0))

    def test_violations_bounced_back(self):
        result = run_planning(self.root, self.command(
            json.dumps(OVERSIZED_PLAN), json.dumps(VALID_PLAN)))
        self.assertEqual(result["rounds"], 2)
        self.assertIn("size_est", self.prompt(1))
        self.assertIn("REJECTED", self.prompt(1))

    def test_garbage_reply_costs_a_round(self):
        result = run_planning(self.root, self.command(
            "not json at all", json.dumps(VALID_PLAN)))
        self.assertEqual(result["rounds"], 2)

    def test_exhaustion_fails_closed(self):
        with self.assertRaises(PlanningError) as ctx:
            run_planning(self.root, self.command(json.dumps(OVERSIZED_PLAN)),
                         max_rounds=2)
        self.assertIn("2 rounds", str(ctx.exception))
        self.assertFalse((self.root / PLAN_JSON_RELPATH).exists())

    def test_missing_spec_fails_closed(self):
        (self.root / compiler.SPEC_RELPATH).unlink()
        with self.assertRaises(PlanningError):
            run_planning(self.root, self.command(json.dumps(VALID_PLAN)))

    def test_unreachable_cli_raises_unavailable(self):
        with self.assertRaises(PlanningUnavailable):
            run_planning(self.root, ["/nonexistent-danza-boss-cli"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_planning_call -v`
Expected: FAIL — `ImportError: cannot import name 'run_planning'`

- [ ] **Step 3: Write the implementation**

In `danzaboss/workstation/planner.py`, add to the import block (after the `danzaboss.planning.decompose` import):

```python
from danzaboss.workstation import checkpoints
from danzaboss.workstation import compiler
from danzaboss.workstation import templates as templates_mod
from danzaboss.workstation.wizard import Wizard
```

and append:

```python
MAX_ROUNDS = 3

PLAN_CONTRACT = (
    "Respond with ONLY a JSON object, no prose around it, shaped exactly:\n"
    '{"spec_ref": str, "tasks": [<task>, ...]}\n'
    'where <task> = {"id": dotted integers — "1" section, "1.2" feature, '
    '"1.2.3" task, "description": str (ONE concern; no \'and then\' '
    'chains), "subtasks": [<task>, ...] on internal nodes} '
    "and every LEAF instead adds: "
    '"kind": one of ' + str(list(TASK_KINDS)) + ', '
    '"size_est": estimated minutes (integer, max ' + str(MAX_SIZE_EST)
    + '), "writes": [1-' + str(MAX_WRITES) + ' files or areas], '
    '"depends_on": [task ids] (optional), '
    '"flags": subset of ' + str(list(HARD_STOP_FLAGS)) + ' (optional), '
    '"verification": {"kind": one of '
    + str([k.value for k in VerificationKind])
    + ', "detail": a concrete command or check}'
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
        "ordered task tree: sections (app areas) -> features -> leaf",
        "tasks of 20-30 minutes each. Every leaf must be independently",
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
                 template_dir=templates_mod.DEFAULT_DIR) -> dict:
    """spec.md -> validated plan artifacts (design spec section 6).

    Calls the boss CLI headless (same injectable-argv seam as
    checkpoints.run_headless), machine-validates each proposal, bounces
    violations back up to max_rounds, then fails closed: a plan that
    never validates must not arm the button. There is deliberately no
    degraded mode — unlike checkpoints, nothing downstream can proceed
    without a valid plan."""
    spec_path = Path(root) / compiler.SPEC_RELPATH
    if not spec_path.exists():
        raise PlanningError(f"no approved spec at {spec_path}; planning "
                            "runs only after final approval")
    spec_text = spec_path.read_text(encoding="utf-8")
    answers = Wizard(root).answers
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
        found = validate_plan(tasks)
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
        json_path, md_path = write_plan(root, data, ordered)
        return {"plan": data, "order": [t.id for t in ordered],
                "rounds": round_num, "plan_json": str(json_path),
                "plan_md": str(md_path)}
    raise PlanningError(
        f"plan still invalid after {max_rounds} rounds; last violations: "
        + "; ".join(violations))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_planning_call -v`
Expected: PASS (9 tests)

Then the full suite: `./danzaboss/run_tests.sh`
Expected: 553 OK (skipped=13), zero failures.

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/planner.py danzaboss/tests/test_workstation_planning_call.py
git commit -m "feat(workstation): W1-P3 T5 headless planning call — bounce-back rounds, fail closed"
```

---

### Task 6: Final whole-branch review + ledger

**Model:** fable (inline). Process task — no new code unless the review finds Important issues.

**Files:**
- Modify (append): `.superpowers/sdd/progress.md`
- Possibly modify: any P3 file, per review findings

**Steps:**

- [ ] **Step 1:** Run the full suite: `./danzaboss/run_tests.sh` — must be green (expected 553 OK, skipped=13).
- [ ] **Step 2:** Single whole-branch review (superpowers:requesting-code-review) over `git diff 569967f..HEAD`, with the deferred-minor lists from `.superpowers/sdd/progress.md` (P1/P2 entries) as triage input.
- [ ] **Step 3:** Fix Important findings inline (own commit each, with regression tests); defer Minors to the ledger.
- [ ] **Step 4:** Append the P3 section to `.superpowers/sdd/progress.md` (append-only) recording per-task commits, review outcome, deferred minors, and "W1-P3 COMPLETE".
- [ ] **Step 5:** Commit: `git add .superpowers/sdd/progress.md && git commit -m "chore(workstation): W1-P3 ledger — decomposition bridge complete"`

---

## Self-Review Notes

- **Spec §6 coverage:** task record extension (T1) · size proxies ≤3 files / one concern / one verification / size_est ≤ 30 (T2) · deterministic topo + cycle rejection + tie-break (T3) · plan.md + plan.json artifacts (T4) · headless call + max-3-round bounce + Rule-3 feature nodes (T5, T3). CORTEX duration-observation calibration is build-time (W2+), out of P3 scope by design.
- **Type consistency:** `PlanningUnavailable` defined in T2, imported by T5 tests. `PLAN_JSON_RELPATH` defined in T4, imported by T5 tests. `order_tasks`/`feature_nodes` (T3) used by T4's renderer and T5's loop. `compiler.SPEC_RELPATH` (T4) read by T5. Verified consistent.
- **Import accumulation:** T2 creates `planner.py` with `re` + decompose imports; T4 adds `json`/`os`/`Path`; T5 adds workstation imports. No circular imports (`planner` → `checkpoints`/`compiler`/`templates`/`wizard`/`decompose`; none import `planner`).
