# W1-P1: Workstation Engine Foundations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure-library heart of the DANZA Workstation — question tree, wizard state machine, persistence, stack template library, and the answers→spec compiler — fully tested, no HTTP, no AI calls.

**Architecture:** New `danzaboss/workstation/` package. The onboarding flow is declared as data (`tree.py`); a small engine (`wizard.py`) walks it, validates/merges answers into `.danza/onboarding/answers.json` of a *target* repo, and enforces downstream-stale invalidation. Stack templates are JSON data files loaded/ranked by `templates.py`. `compiler.py` renders approved answers into the existing `planning/spec_template.md` format. Everything is importable, deterministic, and hermetic.

**Tech Stack:** Python 3.10+ stdlib only. `unittest` (auto-discovered by `danzaboss/run_tests.sh`).

**Spec:** `docs/superpowers/specs/2026-07-05-workstation-onboarding-design.md` §3 (modules), §4 (flow), §5 (templates). Implementers do NOT need to read the spec — every task below is self-contained.

## W1 Phase Map (this plan = P1 only)

Each later phase gets its own plan doc at phase start (repo precedent: CORTEX C1/C4/C6), because plans written far ahead rot.

| Phase | Delivers | Depends on | Default model |
|---|---|---|---|
| **P1 (this plan)** | tree, wizard engine, state, templates, compiler | — | mixed (per task below) |
| P2 | `checkpoints.py` + `research.py` (injectable-command AI seams, Tavily provider, degraded modes) | P1 | fable: contracts/parsing · sonnet: providers |
| P3 | decomposition bridge: plan-schema extension, size-proxy validator, topo ordering, headless planning call | P1 | fable: validator · sonnet: schema/fixtures |
| P4 | `runners.py` registry, session-host interface (tmux + headless impls), `conductor.py` + rails | P1 | fable: conductor loop · sonnet: registry, shims |
| P5 | `server.py` shell, wizard UI, `/models`, dashboard button states, live strip, CORTEX mount, SSE | P1–P4 | sonnet: routes/HTML · fable: mount + button state machine |
| P6 | constitutional amendment texts (user sign-off gate), selftest check, CLAUDE.md/RUNBOOK docs | P1–P5 | fable: amendment text · haiku/sonnet: docs |

## Model Assignment & Token Discipline

- **Model per task** is declared in each task header. `fable (inline)` = the orchestrator implements it directly in the main session (user directive: "write the important files yourself"). `sonnet` = dispatch to a sonnet subagent; quality is guarded by (a) complete code provided in this plan, (b) tests that must pass, (c) orchestrator review between tasks.
- **Batch consecutive sonnet tasks into ONE subagent** when they touch adjacent modules (Task 2 alone; Tasks 4+5 together) — a warm session reuses its cache instead of re-reading the tree/engine from disk.
- **Subagents must not read** the design spec, `CLAUDE.md`, the constitution, or any module not listed in their task's Files block. This plan is the single source; re-reads are the waste we're avoiding.
- **Prompt caching note:** Claude Code caches the session prefix automatically (5-min TTL). The savings lever we control is context minimization (self-contained tasks, tight file lists) and not letting a subagent idle past the TTL between steps — run steps back-to-back.

## Global Constraints

- Python 3.10+, **stdlib only** — no pip installs anywhere in `danzaboss/` (CLAUDE.md standard).
- PEP 8, 4-space indent, `snake_case`, type hints on all public functions, docstrings that state *why*.
- **Fail closed:** validation raises `WizardError` / `ValueError`; never continue past bad state.
- **Deterministic:** no randomness, no wall-clock reads in logic; same inputs → same outputs.
- **Hermetic tests:** operate only on `tempfile` fixture roots; never touch this repo's real `.danza/`, never network. Tests begin with `import _bootstrap  # noqa` (matches every existing test).
- Test run incantation (from repo root): `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.<module> -v`; full suite: `./danzaboss/run_tests.sh` (auto-discovers `test_*.py`).
- Commit after every task; message style `feat(workstation): ...` matching repo history.

---

### Task 1: Package scaffold + question tree (`tree.py`)

**Model:** fable (inline)

**Files:**
- Create: `danzaboss/workstation/__init__.py`
- Create: `danzaboss/workstation/tree.py`
- Create: `.danza/onboarding/README.md`, `.danza/design/README.md` (boot-image scaffold stubs)
- Test: `danzaboss/tests/test_workstation_tree.py`

**Interfaces:**
- Consumes: nothing (foundation task).
- Produces: `Question(id, prompt, kind, options, required, default, show_if)`, `Step(id, kind, title, questions)`, `FLOW: tuple[Step, ...]`, `step_applies(step: Step, project_type: str | None) -> bool`, constants `APP_PROJECT_TYPES`, `SEED_PROJECT_TYPES`. Step kinds: `"phase" | "research" | "checkpoint"`. Question kinds: `"choice" | "text" | "longtext" | "list" | "multi" | "uploads"`.

- [ ] **Step 1: Write the failing test**

`danzaboss/tests/test_workstation_tree.py`:

```python
"""W1-P1 question tree: the onboarding flow is data (design D3/D9);
these tests pin its structural invariants so the engine can trust them."""
import unittest

import _bootstrap  # noqa
from danzaboss.workstation.tree import (APP_PROJECT_TYPES, FLOW,
                                        SEED_PROJECT_TYPES, Step,
                                        step_applies)


class TreeInvariants(unittest.TestCase):
    def test_first_step_is_project_type_phase(self):
        self.assertEqual(FLOW[0].id, "p0")
        self.assertEqual(FLOW[0].kind, "phase")
        self.assertEqual(FLOW[0].questions[0].id, "project_type")

    def test_question_ids_unique_across_flow(self):
        ids = [q.id for step in FLOW for q in step.questions]
        self.assertEqual(len(ids), len(set(ids)), f"duplicate ids: {ids}")

    def test_step_ids_unique_and_kinds_valid(self):
        ids = [s.id for s in FLOW]
        self.assertEqual(len(ids), len(set(ids)))
        for step in FLOW:
            self.assertIn(step.kind, ("phase", "research", "checkpoint"))

    def test_choice_and_multi_questions_have_options(self):
        for step in FLOW:
            for q in step.questions:
                if q.kind in ("choice", "multi"):
                    self.assertTrue(q.options, f"{q.id} has no options")

    def test_project_types_cover_all_p0_options(self):
        p0_options = set(FLOW[0].questions[0].options)
        self.assertEqual(p0_options, APP_PROJECT_TYPES | SEED_PROJECT_TYPES)

    def test_show_if_references_existing_questions(self):
        ids = {q.id for step in FLOW for q in step.questions}
        for step in FLOW:
            for q in step.questions:
                for ref, _accepted in q.show_if:
                    self.assertIn(ref, ids, f"{q.id} show_if references {ref}")

    def test_expected_flow_order_for_app_projects(self):
        app_ids = [s.id for s in FLOW if step_applies(s, "saas")]
        self.assertEqual(app_ids, ["p0", "p1", "r_reality", "cp_concept",
                                   "p2", "p3", "cp_stack", "p4", "p5",
                                   "cp_final"])


class SeedRouting(unittest.TestCase):
    def test_only_p0_before_project_type_known(self):
        applicable = [s.id for s in FLOW if step_applies(s, None)]
        self.assertEqual(applicable, ["p0"])

    def test_seed_types_get_only_seed_phase(self):
        for ptype in sorted(SEED_PROJECT_TYPES):
            ids = [s.id for s in FLOW if step_applies(s, ptype)]
            self.assertEqual(ids, ["p0", "p_seed"], ptype)

    def test_app_types_skip_seed_phase(self):
        for ptype in sorted(APP_PROJECT_TYPES):
            ids = [s.id for s in FLOW if step_applies(s, ptype)]
            self.assertNotIn("p_seed", ids)
            self.assertIn("cp_final", ids)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_tree -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'danzaboss.workstation'`

- [ ] **Step 3: Write the implementation**

`danzaboss/workstation/__init__.py`:

```python
"""DANZA Workstation (W1): onboarding dashboard engine libraries.

Design: docs/superpowers/specs/2026-07-05-workstation-onboarding-design.md.
Factory equipment — operates on a TARGET repo's .danza/, never this repo's.
"""
```

`danzaboss/workstation/tree.py`:

```python
"""Question tree for the W1 onboarding wizard (design spec section 4).

The tree is DATA, not control flow: evolving onboarding (Constitution
Rule 21) means editing these declarations. The engine (wizard.py) walks
whatever FLOW declares and never hard-codes step order.
"""
from __future__ import annotations

from dataclasses import dataclass

APP_PROJECT_TYPES = frozenset({"website", "saas"})
SEED_PROJECT_TYPES = frozenset({"design_ideas", "workflow", "other", "not_sure"})


@dataclass(frozen=True)
class Question:
    """One wizard prompt.

    show_if: ((question_id, (accepted, values...)), ...) — every clause must
    match current answers for this question to be shown. Hidden questions
    are never required. `default` satisfies `required` when unanswered.
    """
    id: str
    prompt: str
    kind: str  # "choice" | "text" | "longtext" | "list" | "multi" | "uploads"
    options: tuple[str, ...] = ()
    required: bool = True
    default: str | None = None
    show_if: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class Step:
    """One flow step: a question phase, a research pass, or an AI checkpoint."""
    id: str
    kind: str  # "phase" | "research" | "checkpoint"
    title: str
    questions: tuple[Question, ...] = ()


FLOW: tuple[Step, ...] = (
    Step("p0", "phase", "Project type", (
        Question("project_type", "What do you want to build?", "choice",
                 options=("website", "saas", "design_ideas", "workflow",
                          "other", "not_sure")),
    )),
    Step("p_seed", "phase", "Project seed", (
        Question("seed_name", "Name this idea", "text"),
        Question("seed_intent", "Describe it in a paragraph", "longtext"),
        Question("seed_links", "Any links or references?", "list",
                 required=False),
    )),
    Step("p1", "phase", "Concept", (
        Question("project_name", "Name the project", "text"),
        Question("concept_what", "What does the app do?", "longtext"),
        Question("concept_who", "Who is it for?", "longtext"),
        Question("concept_problem", "What problem does it solve?", "longtext"),
        Question("concept_similar", "Similar products you like", "list",
                 required=False),
        Question("features_must", "Must-have features", "list"),
        Question("features_nice", "Nice-to-have features", "list",
                 required=False),
        Question("non_goals", "What should this app NOT try to do?", "list"),
    )),
    Step("r_reality", "research", "Reality check"),
    Step("cp_concept", "checkpoint", "Concept review"),
    Step("p2", "phase", "Features", (
        Question("capabilities", "Which capabilities does it need?", "multi",
                 options=("accounts_auth", "payments", "admin_panel",
                          "notifications", "file_uploads", "search",
                          "realtime"),
                 required=False),
        Question("feature_notes", "Notes on any feature", "longtext",
                 required=False),
    )),
    Step("p3", "phase", "Stack", (
        Question("stack_choice", "Do you have a stack in mind?", "choice",
                 options=("template", "custom", "no_preference")),
        Question("stack_template", "Which template?", "text",
                 show_if=(("stack_choice", ("template",)),)),
        Question("stack_custom", "Describe your stack", "longtext",
                 show_if=(("stack_choice", ("custom",)),)),
    )),
    Step("cp_stack", "checkpoint", "Stack review"),
    Step("p4", "phase", "Design", (
        Question("design_urls", "Reference URLs", "list", required=False),
        Question("design_uploads", "Upload images", "uploads",
                 required=False),
        Question("color_direction", "Color direction", "choice",
                 options=("pick", "upload", "propose"), default="propose"),
        Question("style_words", "Style words (minimal, playful, ...)",
                 "list", required=False),
        Question("design_notes", "Design notes", "longtext", required=False),
    )),
    Step("p5", "phase", "Practicalities", (
        Question("repo_mode", "Fresh repo or existing?", "choice",
                 options=("fresh", "existing")),
        Question("deploy_intent", "Where will it run?", "choice",
                 options=("local", "vps", "platform"), default="local"),
        Question("cadence", "Build cadence", "choice",
                 options=("relay", "continuous", "supervised"),
                 default="continuous"),
        Question("cadence_n", "Pause for approval every N features", "text",
                 default="4", required=False),
    )),
    Step("cp_final", "checkpoint", "Final rundown"),
)


def step_applies(step: Step, project_type: str | None) -> bool:
    """Route by project type: seed types skip the full interview (D9)."""
    if step.id == "p0":
        return True
    if project_type is None:
        return False
    if project_type in APP_PROJECT_TYPES:
        return step.id != "p_seed"
    return step.id == "p_seed"
```

`.danza/onboarding/README.md`:

```markdown
# .danza/onboarding/ — wizard state (W1)

Runtime state of the workstation onboarding wizard for THIS project.
`answers.json` is Rule 35 merge-only state; `research/` holds cached
Reality Check digests; `seeds/` holds captured project seeds.
This stub ships with the boot image (Rule 34: stub is read-only).
```

`.danza/design/README.md`:

```markdown
# .danza/design/ — design inputs (W1)

User-provided design assets from onboarding Phase 4: uploaded images,
reference URLs, palettes, design.md notes. Inputs for Hank at build time.
Uploads are user content — Rule 35 state, never regenerated or pruned
by agents. This stub ships with the boot image (Rule 34).
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_tree -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/ danzaboss/tests/test_workstation_tree.py .danza/onboarding/README.md .danza/design/README.md
git commit -m "feat(workstation): W1-P1 T1 package scaffold + question tree as data"
```

---

### Task 2: Wizard state persistence (`state.py`)

**Model:** sonnet

**Files:**
- Create: `danzaboss/workstation/state.py`
- Test: `danzaboss/tests/test_workstation_state.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `STATE_RELPATH: Path` (== `.danza/onboarding/answers.json`), `state_path(root) -> Path`, `load_state(root) -> dict` (always has `"answers": dict` and `"steps": dict` keys), `save_state(root, state) -> None` (atomic, merge-preserving). Task 3's `Wizard` calls exactly these.

- [ ] **Step 1: Write the failing test**

`danzaboss/tests/test_workstation_state.py`:

```python
"""W1-P1 wizard persistence: Rule 35 discipline in code — read-then-merge,
atomic replace, unknown keys on disk survive a save."""
import json
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.workstation.state import load_state, save_state, state_path


class StateRoundTrip(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_load_missing_file_returns_empty_shape(self):
        state = load_state(self.root)
        self.assertEqual(state["answers"], {})
        self.assertEqual(state["steps"], {})

    def test_save_then_load_round_trips(self):
        save_state(self.root, {"answers": {"project_type": "saas"},
                               "steps": {"p0": {"status": "complete"}}})
        state = load_state(self.root)
        self.assertEqual(state["answers"]["project_type"], "saas")
        self.assertEqual(state["steps"]["p0"]["status"], "complete")

    def test_save_preserves_unknown_top_level_keys(self):
        path = state_path(self.root)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"answers": {}, "steps": {},
                                    "other_writer": {"keep": True}}))
        save_state(self.root, {"answers": {"a": "b"}, "steps": {}})
        on_disk = json.loads(path.read_text())
        self.assertEqual(on_disk["other_writer"], {"keep": True})
        self.assertEqual(on_disk["answers"], {"a": "b"})

    def test_no_tmp_file_left_behind(self):
        save_state(self.root, {"answers": {}, "steps": {}})
        leftovers = list(state_path(self.root).parent.glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_corrupt_non_object_state_raises(self):
        path = state_path(self.root)
        path.parent.mkdir(parents=True)
        path.write_text("[1, 2, 3]")
        with self.assertRaises(ValueError):
            load_state(self.root)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_state -v`
Expected: FAIL — `ModuleNotFoundError` (no `state` module)

- [ ] **Step 3: Write the implementation**

`danzaboss/workstation/state.py`:

```python
"""Wizard state persistence into a TARGET repo's .danza/onboarding/.

Rule 35 discipline in code: read-then-merge and atomic replace, so a save
never blind-overwrites what another writer put on disk, and a crash never
leaves a torn file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

STATE_RELPATH = Path(".danza") / "onboarding" / "answers.json"


def state_path(root: str | os.PathLike) -> Path:
    """Where this target repo's wizard state lives."""
    return Path(root) / STATE_RELPATH


def load_state(root: str | os.PathLike) -> dict:
    """Current wizard state, or an empty shape. Fails closed on a file
    that exists but is not a JSON object."""
    raw: dict = {}
    path = state_path(root)
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"corrupt wizard state (not an object): {path}")
    raw.setdefault("answers", {})
    raw.setdefault("steps", {})
    return raw


def save_state(root: str | os.PathLike, state: dict) -> None:
    """Merge answers/steps over what is on disk, then atomic-replace."""
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    on_disk: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                on_disk = loaded
        except (json.JSONDecodeError, OSError):
            on_disk = {}
    on_disk["answers"] = state["answers"]
    on_disk["steps"] = state["steps"]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(on_disk, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_state -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/state.py danzaboss/tests/test_workstation_state.py
git commit -m "feat(workstation): W1-P1 T2 answers.json persistence, Rule-35-safe"
```

---

### Task 3: Wizard engine (`wizard.py`)

**Model:** fable (inline)

**Files:**
- Create: `danzaboss/workstation/wizard.py`
- Test: `danzaboss/tests/test_workstation_wizard.py`

**Interfaces:**
- Consumes: `tree.FLOW`, `tree.step_applies`, `tree.Question`, `tree.Step`; `state.load_state`, `state.save_state` (Task 1/2 signatures).
- Produces: `WizardError(ValueError)`; `TERMINAL = frozenset({"complete", "approved"})`; class `Wizard(root)` with: `answers -> dict` (property), `project_type() -> str | None`, `flow() -> tuple[Step, ...]`, `status(step_id) -> str` (`"pending" | "complete" | "approved" | "stale"`), `result(step_id) -> dict | None`, `current_step() -> Step | None`, `is_complete() -> bool`, `visible_questions(step, incoming=None) -> tuple[Question, ...]`, `submit(step_id, answers: dict) -> None`, `record_result(step_id, result: dict, *, approved: bool = False) -> None`. P2 (checkpoints/research) will call `record_result`; P5 (server) calls everything.

**Design notes the implementer must honor:**
1. Visibility for validation is computed against **stored answers merged with the incoming payload** — otherwise submitting `stack_choice="template"` together with `stack_template="saas-ts"` in one payload would reject the second answer as hidden.
2. Downstream-stale fires only when a submit **changes** an answer on a step that was already terminal (`complete`/`approved`); re-submitting identical answers must not invalidate approvals.
3. `required` + `default` = auto-fill the default when unanswered. Required without default and without a stored answer = `WizardError`.

- [ ] **Step 1: Write the failing test**

`danzaboss/tests/test_workstation_wizard.py`:

```python
"""W1-P1 wizard engine: validation, routing, resume, and the revision rule
(editing an approved phase stales everything after it — design section 4)."""
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.workstation.wizard import Wizard, WizardError

P1_ANSWERS = {
    "project_name": "TestApp",
    "concept_what": "It tracks practice sessions for drummers.",
    "concept_who": "Working drummers",
    "concept_problem": "No log of what was practiced",
    "features_must": ["log a session", "weekly summary"],
    "non_goals": ["social feed"],
}


class WizardBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.wiz = Wizard(self.root)


class FlowAndRouting(WizardBase):
    def test_fresh_wizard_starts_at_p0(self):
        self.assertEqual(self.wiz.current_step().id, "p0")

    def test_seed_type_routes_to_seed_phase_only(self):
        self.wiz.submit("p0", {"project_type": "design_ideas"})
        self.assertEqual([s.id for s in self.wiz.flow()], ["p0", "p_seed"])
        self.assertEqual(self.wiz.current_step().id, "p_seed")

    def test_app_type_routes_to_full_interview(self):
        self.wiz.submit("p0", {"project_type": "saas"})
        self.assertEqual(self.wiz.current_step().id, "p1")
        self.assertNotIn("p_seed", [s.id for s in self.wiz.flow()])


class Validation(WizardBase):
    def setUp(self):
        super().setUp()
        self.wiz.submit("p0", {"project_type": "saas"})

    def test_missing_required_raises(self):
        with self.assertRaises(WizardError):
            self.wiz.submit("p1", {"project_name": "X"})

    def test_unknown_question_raises(self):
        with self.assertRaises(WizardError):
            self.wiz.submit("p1", dict(P1_ANSWERS, bogus="nope"))

    def test_bad_choice_raises(self):
        with self.assertRaises(WizardError):
            self.wiz.submit("p0", {"project_type": "spaceship"})

    def test_multi_values_must_be_in_options(self):
        self.wiz.submit("p1", P1_ANSWERS)
        with self.assertRaises(WizardError):
            self.wiz.submit("p2", {"capabilities": ["telepathy"]})

    def test_hidden_question_not_required(self):
        self.wiz.submit("p1", P1_ANSWERS)
        self.wiz.record_result("r_reality", {"skipped": True})
        self.wiz.record_result("cp_concept", {"verdict": "ok"}, approved=True)
        self.wiz.submit("p2", {})
        # stack_template/stack_custom are hidden for no_preference
        self.wiz.submit("p3", {"stack_choice": "no_preference"})
        self.assertEqual(self.wiz.status("p3"), "complete")

    def test_same_payload_visibility(self):
        self.wiz.submit("p1", P1_ANSWERS)
        self.wiz.record_result("r_reality", {"skipped": True})
        self.wiz.record_result("cp_concept", {"verdict": "ok"}, approved=True)
        self.wiz.submit("p2", {})
        # choosing template + naming it in ONE payload must work
        self.wiz.submit("p3", {"stack_choice": "template",
                               "stack_template": "saas-ts"})
        self.assertEqual(self.wiz.answers["stack_template"], "saas-ts")

    def test_default_fills_required_choice(self):
        self.wiz.submit("p1", P1_ANSWERS)
        self.wiz.record_result("r_reality", {"skipped": True})
        self.wiz.record_result("cp_concept", {"verdict": "ok"}, approved=True)
        self.wiz.submit("p2", {})
        self.wiz.submit("p3", {"stack_choice": "no_preference"})
        self.wiz.submit("p4", {})  # color_direction defaults to "propose"
        self.assertEqual(self.wiz.answers["color_direction"], "propose")

    def test_submit_to_checkpoint_step_raises(self):
        with self.assertRaises(WizardError):
            self.wiz.submit("cp_concept", {})

    def test_step_not_in_active_flow_raises(self):
        with self.assertRaises(WizardError):
            self.wiz.submit("p_seed", {"seed_name": "x", "seed_intent": "y"})


class RevisionRule(WizardBase):
    def _complete_through_stack(self):
        self.wiz.submit("p0", {"project_type": "saas"})
        self.wiz.submit("p1", P1_ANSWERS)
        self.wiz.record_result("r_reality", {"verdict": "viable"})
        self.wiz.record_result("cp_concept", {"verdict": "ok"}, approved=True)
        self.wiz.submit("p2", {"capabilities": ["accounts_auth"]})
        self.wiz.submit("p3", {"stack_choice": "no_preference"})
        self.wiz.record_result("cp_stack", {"pick": "saas-ts"}, approved=True)

    def test_editing_approved_phase_stales_downstream(self):
        self._complete_through_stack()
        self.wiz.submit("p1", dict(P1_ANSWERS, concept_what="Now it is a CRM."))
        self.assertEqual(self.wiz.status("p1"), "complete")
        for later in ("r_reality", "cp_concept", "p2", "p3", "cp_stack"):
            self.assertEqual(self.wiz.status(later), "stale", later)

    def test_identical_resubmit_does_not_stale(self):
        self._complete_through_stack()
        self.wiz.submit("p1", dict(P1_ANSWERS))
        self.assertEqual(self.wiz.status("cp_stack"), "approved")

    def test_stale_step_is_current_again(self):
        self._complete_through_stack()
        self.wiz.submit("p1", dict(P1_ANSWERS, concept_what="Changed."))
        self.assertEqual(self.wiz.current_step().id, "r_reality")


class ResumeAndResults(WizardBase):
    def test_resume_from_disk(self):
        self.wiz.submit("p0", {"project_type": "saas"})
        self.wiz.submit("p1", P1_ANSWERS)
        fresh = Wizard(self.root)
        self.assertEqual(fresh.answers["project_name"], "TestApp")
        self.assertEqual(fresh.status("p1"), "complete")
        self.assertEqual(fresh.current_step().id, "r_reality")

    def test_research_result_stored_and_step_complete(self):
        self.wiz.submit("p0", {"project_type": "saas"})
        self.wiz.submit("p1", P1_ANSWERS)
        digest = {"verdict": "crowded_but_viable", "competitors": ["X"]}
        self.wiz.record_result("r_reality", digest)
        self.assertEqual(self.wiz.result("r_reality"), digest)
        self.assertEqual(self.wiz.status("r_reality"), "complete")

    def test_checkpoint_without_approval_stays_pending(self):
        self.wiz.submit("p0", {"project_type": "saas"})
        self.wiz.submit("p1", P1_ANSWERS)
        self.wiz.record_result("r_reality", {"skipped": True})
        self.wiz.record_result("cp_concept", {"verdict": "concerns"})
        self.assertEqual(self.wiz.status("cp_concept"), "pending")
        self.assertEqual(self.wiz.current_step().id, "cp_concept")

    def test_is_complete_end_to_end(self):
        self.wiz.submit("p0", {"project_type": "saas"})
        self.wiz.submit("p1", P1_ANSWERS)
        self.wiz.record_result("r_reality", {"skipped": True})
        self.wiz.record_result("cp_concept", {"verdict": "ok"}, approved=True)
        self.wiz.submit("p2", {})
        self.wiz.submit("p3", {"stack_choice": "no_preference"})
        self.wiz.record_result("cp_stack", {"pick": "saas-ts"}, approved=True)
        self.wiz.submit("p4", {})
        self.wiz.submit("p5", {"repo_mode": "fresh"})
        self.assertFalse(self.wiz.is_complete())
        self.wiz.record_result("cp_final", {"rundown": "..."}, approved=True)
        self.assertTrue(self.wiz.is_complete())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_wizard -v`
Expected: FAIL — `ModuleNotFoundError` (no `wizard` module)

- [ ] **Step 3: Write the implementation**

`danzaboss/workstation/wizard.py`:

```python
"""W1 onboarding wizard engine (design spec section 4).

Pure library: no HTTP, no AI calls. Walks tree.FLOW, validates and merges
answers, and enforces the revision rule: CHANGING an already-terminal step
marks every later terminal step stale, so approvals must be re-earned.
That rule is the structural guarantee behind "never builds the wrong thing".
"""
from __future__ import annotations

import os

from danzaboss.workstation import state as state_mod
from danzaboss.workstation.tree import FLOW, Question, Step, step_applies

TERMINAL = frozenset({"complete", "approved"})


class WizardError(ValueError):
    """Invalid submission or flow misuse. Fail closed (CLAUDE.md standard)."""


def _validate(question: Question, value: object) -> object:
    """Normalize one answer or raise. Kind rules are the whole contract."""
    kind = question.kind
    if kind in ("text", "longtext"):
        if not isinstance(value, str) or not value.strip():
            raise WizardError(f"{question.id}: expected non-empty text")
        return value.strip()
    if kind == "choice":
        if value not in question.options:
            raise WizardError(
                f"{question.id}: {value!r} not one of {question.options}")
        return value
    if kind in ("list", "uploads"):
        if (not isinstance(value, list)
                or not all(isinstance(v, str) and v.strip() for v in value)):
            raise WizardError(
                f"{question.id}: expected a list of non-empty strings")
        return [v.strip() for v in value]
    if kind == "multi":
        if (not isinstance(value, list)
                or any(v not in question.options for v in value)):
            raise WizardError(
                f"{question.id}: values must be from {question.options}")
        return list(value)
    raise WizardError(f"{question.id}: unsupported kind {kind!r}")


class Wizard:
    """Stateful facade over ONE target repo's onboarding."""

    def __init__(self, root: str | os.PathLike) -> None:
        self._root = root
        self._state = state_mod.load_state(root)

    # ---- read side ----------------------------------------------------
    @property
    def answers(self) -> dict:
        return dict(self._state["answers"])

    def project_type(self) -> str | None:
        return self._state["answers"].get("project_type")

    def flow(self) -> tuple[Step, ...]:
        return tuple(s for s in FLOW if step_applies(s, self.project_type()))

    def status(self, step_id: str) -> str:
        return self._state["steps"].get(step_id, {}).get("status", "pending")

    def result(self, step_id: str) -> dict | None:
        return self._state["steps"].get(step_id, {}).get("result")

    def current_step(self) -> Step | None:
        for step in self.flow():
            if self.status(step.id) not in TERMINAL:
                return step
        return None

    def is_complete(self) -> bool:
        return self.project_type() is not None and self.current_step() is None

    def visible_questions(self, step: Step,
                          incoming: dict | None = None) -> tuple[Question, ...]:
        """Questions shown given stored answers overlaid with an incoming
        payload — the overlay is what lets one payload both pick a branch
        and answer inside it (e.g. stack_choice + stack_template)."""
        answers = dict(self._state["answers"])
        answers.update(incoming or {})
        return tuple(
            q for q in step.questions
            if all(answers.get(qid) in accepted for qid, accepted in q.show_if)
        )

    # ---- write side ---------------------------------------------------
    def submit(self, step_id: str, answers: dict) -> None:
        """Validate + merge one phase's answers; stale downstream on change."""
        step = self._require_step(step_id, kind="phase")
        visible = self.visible_questions(step, incoming=answers)
        by_id = {q.id: q for q in visible}
        for qid in answers:
            if qid not in by_id:
                raise WizardError(f"unknown or hidden question: {qid}")
        merged = dict(self._state["answers"])
        changed = False
        for q in visible:
            if q.id in answers:
                value = _validate(q, answers[q.id])
            elif q.id in merged:
                continue
            elif q.default is not None:
                value = q.default
            elif q.required:
                raise WizardError(f"missing required answer: {q.id}")
            else:
                continue
            if merged.get(q.id) != value:
                merged[q.id] = value
                changed = True
        was_terminal = self.status(step_id) in TERMINAL
        self._state["answers"] = merged
        self._set_status(step_id, "complete")
        if changed and was_terminal:
            self._stale_after(step_id)
        state_mod.save_state(self._root, self._state)

    def record_result(self, step_id: str, result: dict, *,
                      approved: bool = False) -> None:
        """Store a research digest or checkpoint verdict produced upstream
        (P2 seams / P5 server). Checkpoints stay pending until approved."""
        step = self._require_step(step_id, kind=None)
        if step.kind == "phase":
            raise WizardError(f"{step_id} is a phase; use submit()")
        if step.kind == "checkpoint":
            status = "approved" if approved else "pending"
        else:  # research
            status = "complete"
        entry = self._state["steps"].setdefault(step_id, {})
        entry["status"] = status
        entry["result"] = result
        state_mod.save_state(self._root, self._state)

    # ---- internals ------------------------------------------------------
    def _require_step(self, step_id: str, kind: str | None) -> Step:
        for step in self.flow():
            if step.id == step_id:
                if kind is not None and step.kind != kind:
                    raise WizardError(
                        f"{step_id} is a {step.kind}, not a {kind}")
                return step
        raise WizardError(f"step not in the active flow: {step_id}")

    def _set_status(self, step_id: str, status: str) -> None:
        self._state["steps"].setdefault(step_id, {})["status"] = status

    def _stale_after(self, step_id: str) -> None:
        """Everything terminal after an edited step must be re-earned."""
        seen = False
        for step in self.flow():
            if step.id == step_id:
                seen = True
                continue
            if seen and self.status(step.id) in TERMINAL:
                self._set_status(step.id, "stale")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_wizard -v`
Expected: PASS (17 tests)

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/wizard.py danzaboss/tests/test_workstation_wizard.py
git commit -m "feat(workstation): W1-P1 T3 wizard engine — validation, routing, revision staling"
```

---

### Task 4: Stack template library (`templates.py` + 7 JSON files)

**Model:** sonnet (batch with Task 5 in one subagent)

**Files:**
- Create: `danzaboss/workstation/templates.py`
- Create: `danzaboss/workstation/templates/stacks/{static-site,content-site,saas-ts,saas-python,lightweight-tool,realtime-app,cli-tool}.json`
- Test: `danzaboss/tests/test_workstation_templates.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `StackTemplate` dataclass (`key, name, tagline, best_for, components, why, tradeoffs, avoid_when, testing_defaults, philosophy_fit, rank`), `REQUIRED_FIELDS`, `DEFAULT_DIR`, `load_templates(directory=DEFAULT_DIR) -> tuple[StackTemplate, ...]`, `select_templates(templates, project_type: str, capabilities: list[str]) -> list[StackTemplate]`. Task 5's compiler takes a `StackTemplate | None`; P5's wizard UI calls `select_templates`.

- [ ] **Step 1: Write the failing test**

`danzaboss/tests/test_workstation_templates.py`:

```python
"""W1-P1 stack templates: data files under validation (design section 5).
Combinations, never pinned versions; selection is deterministic."""
import unittest

import _bootstrap  # noqa
from danzaboss.workstation.templates import (REQUIRED_FIELDS, StackTemplate,
                                             load_templates,
                                             select_templates)

EXPECTED_KEYS = {"static-site", "content-site", "saas-ts", "saas-python",
                 "lightweight-tool", "realtime-app", "cli-tool"}


class LibraryShape(unittest.TestCase):
    def setUp(self):
        self.templates = load_templates()

    def test_all_seven_load(self):
        self.assertEqual({t.key for t in self.templates}, EXPECTED_KEYS)

    def test_no_pinned_versions_in_components(self):
        for t in self.templates:
            for role, choice in t.components.items():
                for token in str(choice).split():
                    self.assertFalse(
                        token.strip("v").replace(".", "").isdigit()
                        and "." in token,
                        f"{t.key}.{role} pins a version: {choice}")

    def test_ranks_unique(self):
        ranks = [t.rank for t in self.templates]
        self.assertEqual(len(ranks), len(set(ranks)))


class Selection(unittest.TestCase):
    def setUp(self):
        self.templates = load_templates()

    def test_saas_with_auth_and_payments_recommends_ts_standard(self):
        picks = select_templates(self.templates, "saas",
                                 ["accounts_auth", "payments"])
        self.assertEqual(picks[0].key, "saas-ts")

    def test_plain_website_recommends_static(self):
        picks = select_templates(self.templates, "website", [])
        self.assertEqual(picks[0].key, "static-site")

    def test_workflow_recommends_cli_tool(self):
        picks = select_templates(self.templates, "workflow", [])
        self.assertEqual(picks[0].key, "cli-tool")

    def test_realtime_capability_surfaces_realtime_template(self):
        picks = select_templates(self.templates, "saas", ["realtime"])
        self.assertIn("realtime-app", [t.key for t in picks[:2]])

    def test_selection_is_deterministic(self):
        a = select_templates(self.templates, "saas", ["accounts_auth"])
        b = select_templates(self.templates, "saas", ["accounts_auth"])
        self.assertEqual([t.key for t in a], [t.key for t in b])


class Validation(unittest.TestCase):
    def test_missing_field_fails_closed(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            bad = dict.fromkeys(REQUIRED_FIELDS, "x")
            del bad["rank"]
            Path(tmp, "bad.json").write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                load_templates(tmp)

    def test_empty_directory_fails_closed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_templates(tmp)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_templates -v`
Expected: FAIL — `ModuleNotFoundError` (no `templates` module)

- [ ] **Step 3: Write the implementation**

`danzaboss/workstation/templates.py`:

```python
"""Stack template library (design spec section 5).

Templates are DATA files: proven combinations, never pinned versions (the
planner resolves versions at build time, so templates don't rot). The
library evolves by adding files — research or checkpoints propose, the
user approves (Constitution Rule 21).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DIR = Path(__file__).parent / "templates" / "stacks"

REQUIRED_FIELDS = ("name", "tagline", "best_for", "components", "why",
                   "tradeoffs", "avoid_when", "testing_defaults",
                   "philosophy_fit", "rank")


@dataclass(frozen=True)
class StackTemplate:
    """One proven combination. `key` is the filename stem — the stable id
    the wizard stores in answers (stack_template)."""
    key: str
    name: str
    tagline: str
    best_for: dict
    components: dict
    why: str
    tradeoffs: str
    avoid_when: str
    testing_defaults: dict
    philosophy_fit: str
    rank: int


def load_templates(directory: str | Path = DEFAULT_DIR
                   ) -> tuple[StackTemplate, ...]:
    """Load and validate every *.json template. Fail closed on a bad or
    empty library — a silent fallback would let onboarding recommend
    from nothing."""
    templates = []
    for path in sorted(Path(directory).glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = [f for f in REQUIRED_FIELDS if f not in data]
        if missing:
            raise ValueError(f"{path.name}: missing fields {missing}")
        templates.append(StackTemplate(
            key=path.stem, **{f: data[f] for f in REQUIRED_FIELDS}))
    if not templates:
        raise ValueError(f"no stack templates found in {directory}")
    return tuple(templates)


def select_templates(templates: tuple[StackTemplate, ...], project_type: str,
                     capabilities: list[str]) -> list[StackTemplate]:
    """Deterministic fit ranking: filter by project type, score by
    capability coverage, tie-break by declared rank then key. The wizard
    shows the top 2-3; Checkpoint 2 grounds its pushback in this list."""
    wanted = set(capabilities)
    fits = [t for t in templates
            if project_type in t.best_for.get("project_types", [])]

    def sort_key(t: StackTemplate) -> tuple:
        covered = len(wanted & set(t.best_for.get("capabilities", [])))
        return (-covered, t.rank, t.key)

    return sorted(fits, key=sort_key)
```

`danzaboss/workstation/templates/stacks/static-site.json`:

```json
{
  "name": "Static site",
  "tagline": "Plain HTML/CSS/JS or Astro — no backend, no database",
  "best_for": {"project_types": ["website"], "capabilities": []},
  "components": {"frontend": "HTML/CSS/JS or Astro", "backend": "none",
                 "database": "none", "auth": "none", "payments": "none",
                 "hosting": "any static host (free tiers)"},
  "why": "Zero moving parts. For landing pages and portfolios nothing beats a static site for cost, speed, and reliability.",
  "tradeoffs": "No user accounts, no server logic. Adding either later means moving to another template.",
  "avoid_when": "Any capability is checked — accounts, payments, or realtime need a backend.",
  "testing_defaults": {"framework": "none", "tiers": "tier 0-1: build passes, links resolve"},
  "philosophy_fit": "Maximal: free-first, lightweight-first, local-first.",
  "rank": 1
}
```

`danzaboss/workstation/templates/stacks/content-site.json`:

```json
{
  "name": "Content site / blog",
  "tagline": "Astro + Markdown content, SEO-first",
  "best_for": {"project_types": ["website"], "capabilities": ["search"]},
  "components": {"frontend": "Astro", "content": "Markdown files (optional CMS later)",
                 "backend": "none", "database": "none", "auth": "none",
                 "payments": "none", "hosting": "any static host (free tiers)"},
  "why": "Content-heavy sites need fast pages and clean markup for SEO; Astro renders Markdown to static HTML with near-zero JavaScript.",
  "tradeoffs": "Dynamic features require adding islands or a backend later.",
  "avoid_when": "Users need accounts or the content is user-generated.",
  "testing_defaults": {"framework": "none", "tiers": "tier 0-1: build passes, links resolve"},
  "philosophy_fit": "High: free-first, lightweight-first.",
  "rank": 2
}
```

`danzaboss/workstation/templates/stacks/saas-ts.json`:

```json
{
  "name": "SaaS Standard (TypeScript)",
  "tagline": "The boring, proven SaaS stack",
  "best_for": {"project_types": ["saas", "website"],
               "capabilities": ["accounts_auth", "payments", "admin_panel",
                                "notifications", "file_uploads", "search"]},
  "components": {"frontend": "Next.js", "backend": "Next.js API routes",
                 "database": "Postgres", "orm": "Prisma or Drizzle",
                 "auth": "Auth.js", "payments": "Stripe",
                 "hosting": "Vercel or any Node host"},
  "why": "One language front and back, shared types across the API boundary, and the largest ecosystem of reference material — AI builders make fewer wrong guesses on this path.",
  "tradeoffs": "Node toolchain weight; vendor gravity toward Vercel defaults.",
  "avoid_when": "The core is data/ML-heavy (pair with a Python service or use the Python standard).",
  "testing_defaults": {"framework": "vitest + playwright",
                       "tiers": "test-first business logic and API routes; smoke/integration for UI"},
  "philosophy_fit": "Moderate: free tiers exist end-to-end but the toolchain is not lightweight.",
  "rank": 3
}
```

`danzaboss/workstation/templates/stacks/saas-python.json`:

```json
{
  "name": "SaaS Standard (Python)",
  "tagline": "FastAPI backend, React front, Postgres",
  "best_for": {"project_types": ["saas", "website"],
               "capabilities": ["accounts_auth", "payments", "admin_panel",
                                "notifications", "file_uploads", "search"]},
  "components": {"frontend": "React + Vite", "backend": "FastAPI",
                 "database": "Postgres", "orm": "SQLAlchemy",
                 "auth": "fastapi-users or session auth", "payments": "Stripe",
                 "hosting": "any container host"},
  "why": "The same proven SaaS shape for Python-preferring teams, and the natural pick when the app's core involves data processing or ML.",
  "tradeoffs": "Two languages (Python back, TS front); API types must be kept in sync.",
  "avoid_when": "The team wants one language everywhere — use the TypeScript standard.",
  "testing_defaults": {"framework": "pytest + playwright",
                       "tiers": "test-first business logic and endpoints; smoke/integration for UI"},
  "philosophy_fit": "Moderate: free-first achievable; heavier than the lightweight tool stack.",
  "rank": 4
}
```

`danzaboss/workstation/templates/stacks/lightweight-tool.json`:

```json
{
  "name": "Lightweight app / internal tool",
  "tagline": "Flask or FastAPI + HTMX + SQLite — zero ops",
  "best_for": {"project_types": ["saas", "website"],
               "capabilities": ["accounts_auth", "admin_panel", "search"]},
  "components": {"frontend": "HTMX + server templates", "backend": "Flask or FastAPI",
                 "database": "SQLite", "auth": "session auth",
                 "payments": "none (add Stripe later if needed)",
                 "hosting": "single small VPS or local"},
  "why": "For modest-scale apps and internal tools, one process and one file database deliver everything with nothing to operate — the philosophy-purest choice.",
  "tradeoffs": "SQLite writes serialize; heavy concurrent traffic eventually forces the Postgres upgrade path (to the Python standard).",
  "avoid_when": "Payments at launch, high write concurrency, or a large realtime surface.",
  "testing_defaults": {"framework": "pytest",
                       "tiers": "test-first business logic; tier 0-1 for templates/config"},
  "philosophy_fit": "Maximal: free-first, lightweight-first, local-first.",
  "rank": 5
}
```

`danzaboss/workstation/templates/stacks/realtime-app.json`:

```json
{
  "name": "Realtime / collaborative app",
  "tagline": "Next.js + Supabase — live data on a free tier",
  "best_for": {"project_types": ["saas"],
               "capabilities": ["realtime", "accounts_auth", "notifications",
                                "file_uploads"]},
  "components": {"frontend": "Next.js", "backend": "Supabase (Postgres + realtime + auth)",
                 "database": "Postgres (Supabase)", "auth": "Supabase Auth",
                 "payments": "Stripe", "hosting": "Vercel + Supabase free tiers"},
  "why": "When features must update live across clients, Supabase bundles the database, subscriptions, and auth into one service with a generous free tier.",
  "tradeoffs": "Vendor coupling to Supabase; migrating off later is real work.",
  "avoid_when": "No realtime requirement — the plain SaaS standards are simpler.",
  "testing_defaults": {"framework": "vitest + playwright",
                       "tiers": "test-first business logic; integration tests for realtime flows"},
  "philosophy_fit": "Moderate: free-first yes, local-first no (cloud service at the core).",
  "rank": 6
}
```

`danzaboss/workstation/templates/stacks/cli-tool.json`:

```json
{
  "name": "CLI / automation tool",
  "tagline": "Python + Typer + SQLite, installed with pipx",
  "best_for": {"project_types": ["workflow"], "capabilities": ["search"]},
  "components": {"frontend": "terminal (Typer CLI)", "backend": "Python",
                 "database": "SQLite (or plain files)", "auth": "none",
                 "payments": "none", "hosting": "user's machine (pipx install)"},
  "why": "Workflow and automation ideas are usually best as a sharp command-line tool: instant startup, scriptable, no server to run.",
  "tradeoffs": "Terminal-only audience; a UI later means a separate template.",
  "avoid_when": "Non-technical end users need to operate it.",
  "testing_defaults": {"framework": "pytest",
                       "tiers": "test-first command logic; tier 0-1 for packaging"},
  "philosophy_fit": "Maximal: free-first, lightweight-first, local-first.",
  "rank": 7
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_templates -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/templates.py danzaboss/workstation/templates/ danzaboss/tests/test_workstation_templates.py
git commit -m "feat(workstation): W1-P1 T4 stack template library — 7 data files + deterministic selection"
```

---

### Task 5: Spec compiler (`compiler.py`)

**Model:** sonnet (same subagent as Task 4)

**Files:**
- Create: `danzaboss/workstation/compiler.py`
- Test: `danzaboss/tests/test_workstation_compiler.py`

**Interfaces:**
- Consumes: `StackTemplate` from Task 4 (fields `name`, `components`, `testing_defaults`).
- Produces: `compile_spec(*, answers: dict, template: StackTemplate | None, research: dict | None = None, checkpoints: dict[str, str] | None = None, overrides: tuple[str, ...] = (), open_questions: tuple[str, ...] = ()) -> str` and `write_spec(root, text) -> Path` (writes `.danza/spec.md`, atomic). P3 (planning bridge) and P5 (server) consume both.
- Headings MUST match `danzaboss/planning/spec_template.md` exactly (copied verbatim into the code below — do not re-derive them): `# Spec — <name>`, `## 1. Intent`, `## 2. Functional requirements`, `## 3. Non-functional requirements`, `## 4. Data model`, `## 5. External services / APIs`, `## 6. Explicit non-goals`, `## 7. Verification strategy`, `## 8. Open questions`.

- [ ] **Step 1: Write the failing test**

`danzaboss/tests/test_workstation_compiler.py`:

```python
"""W1-P1 spec compiler: approved answers render into the fixed
planning/spec_template.md shape — the document every plan derives from."""
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.workstation.compiler import compile_spec, write_spec
from danzaboss.workstation.templates import load_templates

ANSWERS = {
    "project_type": "saas",
    "project_name": "DrumLog",
    "concept_what": "Tracks practice sessions for drummers.",
    "concept_who": "Working drummers",
    "concept_problem": "No record of what was practiced",
    "features_must": ["log a session", "weekly summary email"],
    "features_nice": ["streak badges"],
    "non_goals": ["social feed"],
    "capabilities": ["accounts_auth", "payments"],
    "stack_choice": "template",
    "stack_template": "saas-ts",
    "color_direction": "propose",
    "repo_mode": "fresh",
    "deploy_intent": "vps",
    "cadence": "continuous",
    "cadence_n": "4",
}

HEADINGS = ["## 1. Intent", "## 2. Functional requirements",
            "## 3. Non-functional requirements", "## 4. Data model",
            "## 5. External services / APIs", "## 6. Explicit non-goals",
            "## 7. Verification strategy", "## 8. Open questions"]


def _template(key):
    return next(t for t in load_templates() if t.key == key)


class CompileSpec(unittest.TestCase):
    def setUp(self):
        self.text = compile_spec(
            answers=ANSWERS, template=_template("saas-ts"),
            research={"verdict": "crowded_but_viable",
                      "summary": "Three practice-log apps exist; none do drums."},
            checkpoints={"cp_concept": "Concept confirmed.",
                         "cp_final": "Rundown approved."},
        )

    def test_title_and_heading_order(self):
        self.assertTrue(self.text.startswith("# Spec — DrumLog"))
        positions = [self.text.index(h) for h in HEADINGS]
        self.assertEqual(positions, sorted(positions))

    def test_functional_requirements_numbered(self):
        self.assertIn("- FR-1: log a session", self.text)
        self.assertIn("- FR-2: weekly summary email", self.text)
        self.assertIn("(nice-to-have, post-MVP): streak badges", self.text)

    def test_hard_stop_flags_surfaced(self):
        self.assertIn("accounts_auth", self.text)
        self.assertIn("Rules 13-14", self.text)

    def test_stack_components_listed(self):
        self.assertIn("SaaS Standard (TypeScript)", self.text)
        self.assertIn("Stripe", self.text)

    def test_cadence_recorded(self):
        self.assertIn("continuous", self.text)
        self.assertIn("N=4", self.text)

    def test_research_verdict_in_intent(self):
        self.assertIn("crowded_but_viable", self.text)

    def test_non_goals_present(self):
        self.assertIn("- social feed", self.text)

    def test_open_questions_default_none(self):
        tail = self.text.split("## 8. Open questions")[1]
        self.assertIn("None.", tail)


class Overrides(unittest.TestCase):
    def test_custom_stack_and_override_notes(self):
        answers = dict(ANSWERS, stack_choice="custom",
                       stack_custom="Django + MongoDB")
        text = compile_spec(
            answers=answers, template=None,
            overrides=("User kept Django + MongoDB against recommendation "
                       "saas-python (checkpoint cp_stack).",))
        self.assertIn("Django + MongoDB", text)
        self.assertIn("OVERRIDE:", text)

    def test_skipped_research_is_honest(self):
        text = compile_spec(answers=ANSWERS, template=_template("saas-ts"),
                            research=None)
        self.assertIn("Reality check: not run", text)


class WriteSpec(unittest.TestCase):
    def test_writes_to_danza_spec_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_spec(tmp, "# Spec — X\n")
            self.assertEqual(path, Path(tmp) / ".danza" / "spec.md")
            self.assertEqual(path.read_text(), "# Spec — X\n")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_compiler -v`
Expected: FAIL — `ModuleNotFoundError` (no `compiler` module)

- [ ] **Step 3: Write the implementation**

`danzaboss/workstation/compiler.py`:

```python
"""Compile approved wizard answers into .danza/spec.md (Upgrade #3).

Headings mirror danzaboss/planning/spec_template.md EXACTLY — the plan and
all tasks derive from this document, so the shape is law (Rule 34: the
template defines the format). spec.md itself is a generated artifact:
regenerated whole from answers on each final approval, which is why plain
overwrite here is correct where answers.json must merge.
"""
from __future__ import annotations

import os
from pathlib import Path

from danzaboss.workstation.templates import StackTemplate

CADENCE_LABELS = {
    "relay": "relay — 2 features per turn, alternate environments",
    "continuous": ("continuous-checkpointed — fresh session per turn, "
                   "pause for user approval every N features"),
    "supervised": "supervised — 2 features per turn, explicit user continue",
}

HARD_STOP_CAPS = ("accounts_auth", "payments")


def compile_spec(*, answers: dict, template: StackTemplate | None,
                 research: dict | None = None,
                 checkpoints: dict[str, str] | None = None,
                 overrides: tuple[str, ...] = (),
                 open_questions: tuple[str, ...] = ()) -> str:
    """Render the spec markdown from approved onboarding state."""
    checkpoints = checkpoints or {}
    caps = answers.get("capabilities", [])
    lines: list[str] = [f"# Spec — {answers['project_name']}", ""]

    lines += ["## 1. Intent",
              answers["concept_what"],
              f"For: {answers['concept_who']}. "
              f"Problem: {answers['concept_problem']}"]
    if research and not research.get("skipped"):
        lines.append(f"Reality check: {research.get('verdict', 'unknown')} — "
                     f"{research.get('summary', '')}".rstrip(" —"))
    else:
        lines.append("Reality check: not run (user skipped or unavailable).")
    for cp_id, summary in sorted(checkpoints.items()):
        lines.append(f"> {cp_id}: {summary}")

    lines += ["", "## 2. Functional requirements"]
    for n, feat in enumerate(answers.get("features_must", []), start=1):
        lines.append(f"- FR-{n}: {feat} — Acceptance: concrete verification "
                     "assigned at decomposition (plan.json leaf)")
    for feat in answers.get("features_nice", []):
        lines.append(f"- (nice-to-have, post-MVP): {feat}")

    lines += ["", "## 3. Non-functional requirements",
              f"- Deployment intent: {answers.get('deploy_intent', 'local')}",
              f"- Build cadence: "
              f"{CADENCE_LABELS[answers.get('cadence', 'continuous')]} "
              f"(N={answers.get('cadence_n', '4')})",
              f"- Capabilities: {', '.join(caps) if caps else 'none checked'}"]
    hard = [c for c in HARD_STOP_CAPS if c in caps]
    if hard:
        lines.append(f"- Hard-stop flags (Rules 13-14): {', '.join(hard)} — "
                     "the build pauses for user approval on these areas")
    lines.append(f"- Design inputs: .danza/design/ "
                 f"(direction: {answers.get('color_direction', 'propose')})")

    lines += ["", "## 4. Data model",
              "Derived from the FR list at planning; Samantha's map is "
              "authoritative after the first scan."]
    if answers.get("feature_notes"):
        lines.append(f"Notes: {answers['feature_notes']}")

    lines += ["", "## 5. External services / APIs"]
    if template is not None:
        lines.append(f"Approved stack: {template.name}")
        for role, choice in template.components.items():
            lines.append(f"- {role}: {choice}")
    else:
        lines.append("Approved stack (user-specified): "
                     f"{answers.get('stack_custom', 'unspecified')}")
    for note in overrides:
        lines.append(f"- OVERRIDE: {note}")

    lines += ["", "## 6. Explicit non-goals"]
    lines += [f"- {goal}" for goal in answers.get("non_goals", [])]

    framework = (template.testing_defaults.get("framework", "unset")
                 if template else "chosen at planning from the user stack")
    lines += ["", "## 7. Verification strategy",
              f"- Test framework: {framework}",
              "- Every FR maps to at least one concrete verification at "
              "decomposition (planning/decompose.py kinds); no FR without "
              "a check",
              "- Test-first for business logic and endpoints; tier 0-1 "
              "checks for scaffold/config; the suite accumulates and runs "
              "at cadence checkpoints"]

    lines += ["", "## 8. Open questions"]
    lines += [f"- {q}" for q in open_questions] if open_questions else ["None."]

    return "\n".join(lines) + "\n"


def write_spec(root: str | os.PathLike, text: str) -> Path:
    """Write .danza/spec.md atomically; returns the path written."""
    path = Path(root) / ".danza" / "spec.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_compiler -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/compiler.py danzaboss/tests/test_workstation_compiler.py
git commit -m "feat(workstation): W1-P1 T5 answers-to-spec compiler in spec_template shape"
```

---

### Task 6: Full-suite integration & hermeticity check

**Model:** sonnet

**Files:**
- Modify: none expected — this task verifies; it may only fix breakage it finds.
- Test: the whole suite.

**Interfaces:**
- Consumes: everything above.
- Produces: green suite; the P1 exit gate.

- [ ] **Step 1: Run the complete suite**

Run: `./danzaboss/run_tests.sh 2>&1 | tail -15`
Expected: `OK` with **444+ tests** (401 existing + ~43 new). Zero failures, zero errors.

- [ ] **Step 2: Hermeticity spot-check**

Run: `git status --porcelain .danza/ | grep -v 'onboarding/README\|design/README' ; echo "clean=$?"`
Expected: `clean=1` (no test polluted this repo's `.danza/` beyond the two intended README stubs from Task 1).

- [ ] **Step 3: Verify no non-stdlib imports crept in**

Run: `grep -rEh '^(import|from) ' danzaboss/workstation/ | sort -u`
Expected: only `__future__`, `dataclasses`, `json`, `os`, `pathlib`, and `danzaboss.workstation.*` imports.

- [ ] **Step 4: Commit (only if fixes were needed) and report**

```bash
git add -A danzaboss/ && git commit -m "test(workstation): W1-P1 T6 suite integration fixes" || echo "nothing to fix"
```

Report the final test count for the CLAUDE.md doc update (done in P6, not now).

---

## Self-Review (planner)

1. **Spec coverage (P1 scope = design §3 modules tree/state/wizard/templates/compiler, §4 flow, §5 templates, D9 seeds, D10 scaffold dirs):** tree+routing → T1; persistence/Rule 35 → T2; engine+revision rule → T3; 7 templates+selection → T4; compiler+spec shape → T5; D10 scaffold READMEs → T1. Checkpoints/research *execution* is P2 by design — P1 only stores their results (`record_result`, tested). Seed listing UI is P5. No P1 gaps.
2. **Placeholder scan:** every code step contains complete code; no TBD/TODO/"similar to".
3. **Type consistency:** `Wizard.record_result(step_id, result, *, approved=False)` matches tests; `StackTemplate` field order matches JSON keys and `compile_spec` uses only `name/components/testing_defaults`; `load_templates()` default-dir usage in both test files matches `DEFAULT_DIR`. `visible_questions(step, incoming=None)` signature consistent between engine and tests.
