# Phase 3 — Onboarding That Grills: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the dashboard's read-only ONBOARD tab into the real onboarding surface: wizard forms over the existing engine, an adaptive AI interview ("the grill") with a deterministic clarity gate, inline reality-check/checkpoint actions, and a finish flow that compiles `spec.md` + validated `plan.json`.

**Architecture:** One new pure library module (`workstation/interview.py`, mirrors `checkpoints.py`) plus extensions to `workstation/server.py` (enriched read API + first POST routes) and the Phase 2 front-end (`static/app.js`/`app.css`). `wizard.submit()` is unchanged (spec §7); the clarity gate is deterministic control logic in `interview.py` — AI output is data, never control flow. All AI calls ride the existing `checkpoints.run_headless` injectable-argv seam, so every test is hermetic via stub Python scripts registered as the boss in `runners.json`.

**Tech Stack:** Python 3.10+ stdlib only; vanilla JS/CSS (no build step); `unittest` discovered by `danzaboss/run_tests.sh`.

**Spec:** `docs/superpowers/specs/2026-07-11-danza-os-product-completion-design.md` §7 (+ §11 cross-cutting rules). Decisions D5, D6, D9 bind.

## Global Constraints

- **Stdlib only** in all OS code; no pip installs to run tests (spec §11).
- **Fail closed:** invalid state raises; degraded AI calls are flagged, never silent (spec §11).
- **Determinism:** clarity gate, round cap, and route gating are pure and unit-testable; AI output is validated data (spec §11, D6).
- **No drift:** interview follow-ups clarify the user's stated idea; they never introduce features; escalation puts the decision back with the user, whose answer is final (spec §7, §11).
- **Interview hard cap: 3 rounds per phase** (D6).
- **Style is law:** `interview.py` mirrors `checkpoints.py`; server code mirrors the Phase 2 handler; JS mirrors existing `app.js` idioms (`esc()`, `panel()`, `row()`), origin-relative URLs only (no leading `/` in fetch paths).
- **`wizard.submit()` unchanged** (spec §7). Rules 34–36: `answers.json` merge discipline is owned by `state.py`; generated artifacts (spec.md, plan.json, interview.json) are whole-file atomic writes.
- **PEP 8, type hints on public functions, docstrings that state why.** Tests via `python3 -m unittest` from `danzaboss/` with `PYTHONPATH` per `run_tests.sh`; every task ends green.
- Commit after every task; message prefix `feat(workstation):` / `test:` / `docs:` as appropriate. Layer 0 (OS_DEV) — constitution runtime ceremony does not apply; Rule 16 (no deletions) does.

## Design decisions (locked during planning)

| # | Decision |
|---|---|
| P3-D1 | Interview state lives in `.danza/onboarding/interview.json`, NOT inside `answers.json` — `wizard.submit()` saves whole wizard state from an in-memory `Wizard`, so a second writer to the same file would race/clobber. Separate single-writer artifact, atomic replace. |
| P3-D2 | Deterministic clear: the AI's `clear: true` is honored only when `ambiguities` and `follow_up_questions` are both empty. An unclear reply with nothing to ask is unusable → `InterviewError` (triggers the one retry, then degraded). |
| P3-D3 | Gate semantics — `phase_clear(record)` is True when: no record exists (library/CLI onboarding never ran the interview — additive product surface, not a new wizard invariant), or `clear`, or `degraded` (spec: wizard continues, flagged in spec.md), or a user `resolution` exists (user's word is final). `blocking_phase(root)` = first flow phase that is terminal but not clear; it gates POST submit (of other steps), approve, and finish. |
| P3-D4 | Boss argv comes from `runners.headless_argv(load_runners(root))`; any `RunnerError` → `None` → degraded paths (interview degraded record; checkpoint degraded verdict via new `command=None` support; research skipped path). Tests register a stub Python script as a custom runner — `validate_config` accepts arbitrary runner names. |
| P3-D5 | Follow-up Q&A pairs are stored per-round in the interview record and inlined into subsequent round prompts ("merge into the phase record", spec §7). At finish, degraded grills and user-resolved ambiguities flow into `compile_spec(open_questions=…)` → spec.md "## 8. Open questions" — the appendix without changing the Rule-34 heading shape. |
| P3-D6 | Finish orchestration `finish_onboarding(root, command)` is a module-level function in `server.py` (no production caller of `compile_spec`/`run_planning` exists today). Seed project types (`design_ideas`/`workflow`/`other`/`not_sure`) cannot compile a build spec — 400. |
| P3-D7 | Phase 2 deferred minor lands here: `_team_state` validates through `kernel.state.TeamState.validate()` (Rule 45) and surfaces violations as `team_state_error` — warn-only, data still renders. |
| P3-D8 | A re-submission of a phase resets its interview record (`begin_phase`) — the grill re-runs against the changed answers; wizard's own stale-downstream rule is untouched and surfaces in the UI via status chips. |

## File structure

| File | Role |
|---|---|
| `danzaboss/workstation/interview.py` | NEW — reply contract, prompt builder, retry call, record store, round controller, clarity gate |
| `danzaboss/workstation/checkpoints.py` | EXTEND — `run_checkpoint(command=None)` records the degraded verdict without a subprocess |
| `danzaboss/workstation/server.py` | EXTEND — enriched `/api/onboarding`, `_headless_command`, Rule-45 team-state validation, `POST /api/onboard/*`, `finish_onboarding`, SSE token additions |
| `danzaboss/workstation/static/app.js` | EXTEND — ONBOARD tab: forms, grill panel, research/checkpoint/finish actions |
| `danzaboss/workstation/static/app.css` | EXTEND — form controls + warn-chip in ADUSON tokens |
| `danzaboss/tests/test_workstation_interview.py` | NEW — contract + controller + gate tests |
| `danzaboss/tests/test_workstation_checkpoints.py` | EXTEND — `command=None` tests |
| `danzaboss/tests/test_danza_ui.py` | EXTEND — read API, Rule-45, SSE token |
| `danzaboss/tests/test_danza_onboard_api.py` | NEW — POST routes + full hermetic onboarding acceptance run |

Interfaces used from existing code (verbatim, do not re-derive):
`Wizard(root)` / `.answers` / `.flow()` / `.status(id)` / `.result(id)` / `.current_step()` / `.is_complete()` / `.submit(step_id, answers)` / `.record_result(step_id, result, approved=…)`; `wizard.TERMINAL`; `tree.APP_PROJECT_TYPES`; `checkpoints.run_headless(command, prompt, timeout=…)`, `.parse_json_reply(text)`, `.read_memory(root)`, `.CheckpointError/CheckpointUnavailable`, `.CHECKPOINT_IDS`, `.run_checkpoint(root, step_id, command)`; `research.run_reality_check(root, provider)`, `.tavily_from_env(command)`, `.BossWebProvider(command)`, `.ResearchError`; `compiler.compile_spec(...)`, `.write_spec(root, text)`, `.SPEC_RELPATH`; `planner.run_planning(root, command, *, timeout=600, max_rounds=3, template_dir=…)` (raises `PlanningError`/`PlanningUnavailable`, both ValueError subclasses — verify at implementation), `.PLAN_JSON_RELPATH`; `templates.load_templates(directory=DEFAULT_DIR)`; `runners.load_runners(root)`, `.headless_argv(config)`, `.RunnerError`, `.RUNNERS_RELPATH`, `.SCHEMA_VERSION`; `kernel.state.TeamState` / `.StateError`; server helpers `_json`, `_static`, `serve_in_thread`, `snapshot_token`.

Test fixture for a stub boss (used across Tasks 4–7); put in `test_danza_onboard_api.py` and import where needed:

```python
import json, sys
from pathlib import Path
from danzaboss.workstation.runners import RUNNERS_RELPATH, SCHEMA_VERSION

def install_stub_boss(root: Path, body: str) -> Path:
    """Register a stub python script as the repo's headless boss runner.

    validate_config accepts arbitrary runner names, so tests point the
    'boss' at a local script — the same injectable-argv seam
    checkpoints.run_headless was designed around."""
    script = root / "stub_boss.py"
    script.write_text(body, encoding="utf-8")
    config = {
        "version": SCHEMA_VERSION, "boss": "stub", "session_host": "headless",
        "permission_mode": None,
        "runners": {"stub": {"kind": "cli", "binary": sys.executable,
                             "interactive": [sys.executable, str(script)],
                             "headless": [sys.executable, str(script)],
                             "detected": True}}}
    path = root / RUNNERS_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config), encoding="utf-8")
    return script
```

A **switching stub** body that answers all three prompt families (interview / checkpoint / planner) — the full-run acceptance test uses it; a counter file makes the first interview call unclear and later ones clear:

```python
SWITCHING_STUB = r'''
import json, sys
from pathlib import Path
prompt = sys.argv[1]
if "DANZA planner" in prompt:
    print(json.dumps({"spec_ref": ".danza/spec.md", "tasks": [
        {"id": "1", "description": "Walking skeleton", "subtasks": [
            {"id": "1.1", "description": "Health endpoint returns ok",
             "kind": "build", "size_est": 20, "writes": ["app.py"],
             "verification": {"kind": "automated_test",
                              "detail": "pytest -k health"}}]}]}))
elif "onboarding reviewer" in prompt:
    print(json.dumps({"summary": "looks buildable", "concerns": [],
                      "follow_up_questions": [], "recommendation": "proceed",
                      "verdict": "approve"}))
elif "Reality Check analyst" in prompt:
    print(json.dumps({"verdict": "crowded_but_viable",
                      "summary": "market exists",
                      "competitors": [{"name": "Rover", "url": "", "note": ""}],
                      "differentiation": "local focus"}))
else:  # the grill ("You are the DANZA onboarding interviewer")
    marker = Path(__file__).with_name("grilled.txt")
    first = not marker.exists()
    marker.write_text("y")
    if first:
        print(json.dumps({"ambiguities": ["Which currency for payments?"],
                          "follow_up_questions": ["Which currency?"],
                          "clear": False}))
    else:
        print(json.dumps({"ambiguities": [], "follow_up_questions": [],
                          "clear": True}))
'''
```

---

### Task 1: `interview.py` — reply contract, prompt, retry call

**Files:**
- Create: `danzaboss/workstation/interview.py`
- Test: `danzaboss/tests/test_workstation_interview.py`

**Interfaces:**
- Consumes: `checkpoints.parse_json_reply`, `checkpoints.run_headless`, `checkpoints.CheckpointError/CheckpointUnavailable`.
- Produces (later tasks rely on these exact names): `InterviewError(ValueError)`; `REPLY_KEYS`; `INTERVIEW_CONTRACT: str`; `parse_reply(text: str) -> dict`; `build_interview_prompt(step_title: str, phase_answers: dict, all_answers: dict, prior_rounds: list[dict], memory: str = "") -> str`; `call_interview(command: list[str], prompt: str, *, timeout: int = 180) -> dict`.

- [ ] **Step 1: Write the failing tests**

```python
"""Adaptive-interview contract tests (product spec section 7, D6)."""
import sys
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.workstation import checkpoints, interview


def make_stub(tmp: Path, body: str) -> list[str]:
    stub = tmp / "stub_boss.py"
    stub.write_text(body, encoding="utf-8")
    return [sys.executable, str(stub)]


UNCLEAR = {"ambiguities": ["which currency?"],
           "follow_up_questions": ["USD or EUR?"], "clear": False}


class ParseReplyTests(unittest.TestCase):
    def test_valid_unclear_reply_normalizes(self):
        out = interview.parse_reply(
            '{"ambiguities": [" which currency? "], '
            '"follow_up_questions": ["USD or EUR?"], "clear": false}')
        self.assertEqual(out["ambiguities"], ["which currency?"])
        self.assertFalse(out["clear"])

    def test_clear_flag_is_data_not_control(self):
        # AI says clear but still lists an ambiguity -> deterministically unclear
        out = interview.parse_reply(
            '{"ambiguities": ["x"], "follow_up_questions": [], "clear": true}')
        self.assertFalse(out["clear"])

    def test_truly_clear_reply(self):
        out = interview.parse_reply(
            '{"ambiguities": [], "follow_up_questions": [], "clear": true}')
        self.assertTrue(out["clear"])

    def test_unclear_with_nothing_to_ask_is_unusable(self):
        with self.assertRaises(interview.InterviewError):
            interview.parse_reply(
                '{"ambiguities": [], "follow_up_questions": [], "clear": false}')

    def test_missing_keys_fail_closed(self):
        with self.assertRaises(interview.InterviewError):
            interview.parse_reply('{"clear": true}')

    def test_non_string_items_fail_closed(self):
        with self.assertRaises(interview.InterviewError):
            interview.parse_reply(
                '{"ambiguities": [1], "follow_up_questions": [], "clear": false}')

    def test_result_envelope_is_unwrapped(self):
        # the `--output-format json` envelope shape real CLIs emit
        out = interview.parse_reply(
            '{"result": "{\\"ambiguities\\": [], '
            '\\"follow_up_questions\\": [], \\"clear\\": true}"}')
        self.assertTrue(out["clear"])


class PromptTests(unittest.TestCase):
    def test_prompt_carries_phase_and_accumulated_context(self):
        prompt = interview.build_interview_prompt(
            "Concept", {"concept_what": "a dog app"},
            {"project_type": "saas", "concept_what": "a dog app"},
            [], memory="prefers python")
        self.assertIn("DANZA onboarding interviewer", prompt)
        self.assertIn("a dog app", prompt)
        self.assertIn('"project_type": "saas"', prompt)
        self.assertIn("prefers python", prompt)
        self.assertIn(interview.INTERVIEW_CONTRACT, prompt)

    def test_prompt_forbids_drift(self):
        prompt = interview.build_interview_prompt("Concept", {}, {}, [])
        self.assertIn("never introduce features", prompt.lower())

    def test_prior_rounds_ride_inline(self):
        rounds = [{"ambiguities": ["a"], "follow_up_questions": ["q1?"],
                   "clear": False, "answers": {"q1?": "answer one"}}]
        prompt = interview.build_interview_prompt("Concept", {}, {}, rounds)
        self.assertIn("q1?", prompt)
        self.assertIn("answer one", prompt)


class CallTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_call_returns_normalized_reply(self):
        import json as _json
        command = make_stub(self.tmp,
                            f"import json\nprint(json.dumps({UNCLEAR!r}))\n")
        out = interview.call_interview(command, "grill this")
        self.assertEqual(out["follow_up_questions"], ["USD or EUR?"])

    def test_one_retry_on_garbage_then_success(self):
        # first call prints prose; retry (prompt contains the harder
        # instruction) prints valid JSON — same pattern as call_checkpoint
        body = (
            "import json, sys\n"
            "prompt = sys.argv[1]\n"
            "if 'not valid JSON' in prompt:\n"
            f"    print(json.dumps({UNCLEAR!r}))\n"
            "else:\n"
            "    print('no json here')\n")
        out = interview.call_interview(make_stub(self.tmp, body), "grill")
        self.assertFalse(out["clear"])

    def test_unavailable_cli_propagates(self):
        with self.assertRaises(checkpoints.CheckpointUnavailable):
            interview.call_interview(["/nonexistent/boss-cli"], "grill")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd danzaboss && PYTHONPATH="$(cd .. && pwd):$(pwd)/tests" python3 -m unittest tests.test_workstation_interview -v`
Expected: FAIL/ERROR with `ModuleNotFoundError`/`ImportError` (no `interview` module).

- [ ] **Step 3: Write the implementation**

```python
"""Adaptive AI interview for dashboard onboarding (product spec section 7).

After each phase submission the boss CLI is asked, headless, whether the
user's answers are buildable as stated: it returns ambiguities and
follow-up questions until the phase is clear. The AI only reports; every
decision that gates progress (round cap, clarity, escalation) is
deterministic control logic in this module (D6). Follow-ups clarify the
user's stated idea and never introduce features (spec section 11 —
no drift). Reuses the checkpoint runner's subprocess + lenient JSON
parse: one CLI seam, not two.
"""
from __future__ import annotations

import json

from danzaboss.workstation import checkpoints

REPLY_KEYS = ("ambiguities", "follow_up_questions", "clear")

INTERVIEW_CONTRACT = (
    "Respond with ONLY a JSON object, no prose around it, shaped exactly:\n"
    '{"ambiguities": [str], "follow_up_questions": [str], "clear": bool}')


class InterviewError(ValueError):
    """Invalid reply, record misuse, or gate violation. Fail closed."""


def parse_reply(text: str) -> dict:
    """Fail-closed validation + deterministic normalization of one grill
    reply. The AI's `clear` flag is honored only when it lists nothing
    left to ask — data never overrides the gate (spec section 11); and an
    unclear verdict must carry at least one ambiguity or question, or the
    round is unactionable."""
    try:
        data = checkpoints.parse_json_reply(text)
    except checkpoints.CheckpointError as exc:
        raise InterviewError(str(exc)) from exc
    if not isinstance(data, dict):
        raise InterviewError(f"reply is not an object: {text[:200]!r}")
    missing = [k for k in REPLY_KEYS if k not in data]
    if missing:
        raise InterviewError(f"reply missing keys {missing}")
    for key in ("ambiguities", "follow_up_questions"):
        value = data[key]
        if (not isinstance(value, list)
                or not all(isinstance(v, str) and v.strip() for v in value)):
            raise InterviewError(
                f"reply.{key} must be a list of non-empty strings")
    if not isinstance(data["clear"], bool):
        raise InterviewError("reply.clear must be a boolean")
    ambiguities = [v.strip() for v in data["ambiguities"]]
    follow_ups = [v.strip() for v in data["follow_up_questions"]]
    clear = data["clear"] and not ambiguities and not follow_ups
    if not clear and not ambiguities and not follow_ups:
        raise InterviewError(
            "unclear verdict with nothing to ask is unactionable")
    return {"ambiguities": ambiguities,
            "follow_up_questions": follow_ups, "clear": clear}


def build_interview_prompt(step_title: str, phase_answers: dict,
                           all_answers: dict, prior_rounds: list[dict],
                           memory: str = "") -> str:
    """Deterministic grill prompt: phase answers + accumulated spec context
    inline (spec section 7), so the headless call needs no repo access."""
    lines = [
        "You are the DANZA onboarding interviewer. A user just answered "
        f"the {step_title!r} phase of product onboarding. Grill the "
        "answers until they are crystal clear to build from: name every "
        "ambiguity, contradiction, or unstated assumption a builder "
        "would trip over, and ask the follow-up questions that resolve "
        "them.",
        "Do NOT invent or suggest features — never introduce features. "
        "Clarify only what the user already stated (their idea, their "
        "words). If everything is buildable as stated, say clear.", ""]
    if memory:
        lines += ["User memory (honor these preferences — Rule 32):",
                  memory, ""]
    lines += ["Answers for this phase (JSON):",
              json.dumps(phase_answers, indent=2, sort_keys=True), "",
              "All onboarding answers so far (JSON):",
              json.dumps(all_answers, indent=2, sort_keys=True), ""]
    for n, rnd in enumerate(prior_rounds, start=1):
        lines += [f"Round {n} follow-ups already asked and answered (JSON):",
                  json.dumps({"asked": rnd["follow_up_questions"],
                              "answers": rnd["answers"]},
                             indent=2, sort_keys=True), ""]
    lines += ["", INTERVIEW_CONTRACT]
    return "\n".join(lines)


def call_interview(command: list[str], prompt: str, *,
                   timeout: int = 180) -> dict:
    """Call once; ONE retry on garbage with a harder instruction (same
    policy as call_checkpoint). Unavailability propagates — the round
    controller decides how to degrade."""
    try:
        return parse_reply(
            checkpoints.run_headless(command, prompt, timeout=timeout))
    except checkpoints.CheckpointUnavailable:
        raise
    except InterviewError:
        retry = (prompt + "\n\nYour previous reply was not valid JSON. "
                 + INTERVIEW_CONTRACT)
        return parse_reply(
            checkpoints.run_headless(command, retry, timeout=timeout))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: same command as Step 2. Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/interview.py danzaboss/tests/test_workstation_interview.py
git commit -m "feat(workstation): interview reply contract, grill prompt, retry call (P3 T1)"
```

---

### Task 2: `interview.py` — record store, round controller, clarity gate

**Files:**
- Modify: `danzaboss/workstation/interview.py` (append)
- Test: `danzaboss/tests/test_workstation_interview.py` (append)

**Interfaces:**
- Consumes: Task 1 names; `Wizard`, `wizard.TERMINAL`, `checkpoints.read_memory`.
- Produces: `INTERVIEW_RELPATH = Path(".danza")/"onboarding"/"interview.json"`; `MAX_ROUNDS = 3`; `load_interview(root) -> dict` (shape `{"phases": {step_id: record}}`); `save_interview(root, data) -> None`; `begin_phase(root, step_id) -> dict`; `run_interview_round(root, step_id, command, *, timeout=180) -> dict`; `record_followup_answers(root, step_id, answers: dict) -> dict`; `resolve(root, step_id, decision: str) -> dict`; `phase_clear(record: dict | None) -> bool`; `blocking_phase(root, wizard=None) -> str | None`; `open_questions(root, wizard=None) -> tuple[str, ...]`. Record shape: `{"rounds": [{"ambiguities": [...], "follow_up_questions": [...], "clear": bool, "answers": {question: answer}}], "clear": bool, "degraded": bool, "degraded_reason": str (only when degraded), "needs_user_decision": bool, "resolution": str | None}`.

- [ ] **Step 1: Write the failing tests (append to test module)**

```python
CLEAR = {"ambiguities": [], "follow_up_questions": [], "clear": True}


def submit_p0_p1(root: Path) -> None:
    """Drive the real wizard to a grillable phase."""
    from danzaboss.workstation.wizard import Wizard
    wiz = Wizard(root)
    wiz.submit("p0", {"project_type": "saas"})
    Wizard(root).submit("p1", {
        "project_name": "Dogly", "concept_what": "a dog-walking app",
        "concept_who": "dog owners", "concept_problem": "no time to walk",
        "features_must": ["book a walker"], "non_goals": ["social feed"]})


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        submit_p0_p1(self.root)
        interview.begin_phase(self.root, "p1")

    def stub(self, payload) -> list[str]:
        import json as _json
        return make_stub(self.root,
                         f"import json\nprint(json.dumps({payload!r}))\n")

    def test_unclear_round_stores_followups(self):
        record = interview.run_interview_round(
            self.root, "p1", self.stub(UNCLEAR))
        self.assertEqual(len(record["rounds"]), 1)
        self.assertEqual(record["rounds"][0]["follow_up_questions"],
                         ["USD or EUR?"])
        self.assertFalse(record["clear"])
        self.assertFalse(record["needs_user_decision"])

    def test_followup_answers_merge_then_clear(self):
        interview.run_interview_round(self.root, "p1", self.stub(UNCLEAR))
        interview.record_followup_answers(
            self.root, "p1", {"USD or EUR?": "USD"})
        record = interview.run_interview_round(
            self.root, "p1", self.stub(CLEAR))
        self.assertTrue(record["clear"])
        self.assertEqual(record["rounds"][0]["answers"], {"USD or EUR?": "USD"})
        self.assertTrue(interview.phase_clear(record))

    def test_cap_escalates_to_user(self):
        for _ in range(interview.MAX_ROUNDS):
            record = interview.run_interview_round(
                self.root, "p1", self.stub(UNCLEAR))
            if not record["needs_user_decision"]:
                interview.record_followup_answers(
                    self.root, "p1", {"USD or EUR?": "still deciding"})
        self.assertEqual(len(record["rounds"]), interview.MAX_ROUNDS)
        self.assertTrue(record["needs_user_decision"])
        self.assertFalse(interview.phase_clear(record))
        # a 4th round is a no-op, not a 4th AI call
        again = interview.run_interview_round(
            self.root, "p1", self.stub(UNCLEAR))
        self.assertEqual(len(again["rounds"]), interview.MAX_ROUNDS)

    def test_resolution_is_final(self):
        for _ in range(interview.MAX_ROUNDS):
            interview.run_interview_round(self.root, "p1", self.stub(UNCLEAR))
        record = interview.resolve(self.root, "p1", "USD only, v1")
        self.assertEqual(record["resolution"], "USD only, v1")
        self.assertFalse(record["needs_user_decision"])
        self.assertTrue(interview.phase_clear(record))
        with self.assertRaises(interview.InterviewError):
            interview.record_followup_answers(self.root, "p1", {"q": "a"})

    def test_unreachable_boss_degrades_and_continues(self):
        record = interview.run_interview_round(
            self.root, "p1", ["/nonexistent/boss-cli"])
        self.assertTrue(record["degraded"])
        self.assertTrue(interview.phase_clear(record))

    def test_no_command_degrades(self):
        record = interview.run_interview_round(self.root, "p1", None)
        self.assertTrue(record["degraded"])
        self.assertIn("no headless boss", record["degraded_reason"])

    def test_begin_phase_resets_the_grill(self):
        interview.run_interview_round(self.root, "p1", self.stub(UNCLEAR))
        record = interview.begin_phase(self.root, "p1")
        self.assertEqual(record["rounds"], [])

    def test_non_phase_step_is_refused(self):
        with self.assertRaises(interview.InterviewError):
            interview.run_interview_round(
                self.root, "cp_concept", self.stub(CLEAR))


class GateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        submit_p0_p1(self.root)

    def test_no_record_means_clear(self):
        # library/CLI onboarding never ran the interview — additive surface
        self.assertIsNone(interview.blocking_phase(self.root))

    def test_open_grill_blocks(self):
        interview.begin_phase(self.root, "p1")
        stub = make_stub(self.root,
                         f"import json\nprint(json.dumps({UNCLEAR!r}))\n")
        interview.run_interview_round(self.root, "p1", stub)
        self.assertEqual(interview.blocking_phase(self.root), "p1")

    def test_open_questions_lines(self):
        interview.begin_phase(self.root, "p1")
        interview.run_interview_round(self.root, "p1", None)  # degraded
        lines = interview.open_questions(self.root)
        self.assertTrue(any("degraded" in line for line in lines))

    def test_resolution_line_carries_user_decision(self):
        interview.begin_phase(self.root, "p1")
        stub = make_stub(self.root,
                         f"import json\nprint(json.dumps({UNCLEAR!r}))\n")
        for _ in range(interview.MAX_ROUNDS):
            interview.run_interview_round(self.root, "p1", stub)
        interview.resolve(self.root, "p1", "USD only")
        lines = interview.open_questions(self.root)
        self.assertTrue(any("USD only" in line for line in lines))

    def test_corrupt_interview_file_fails_closed(self):
        path = self.root / interview.INTERVIEW_RELPATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[]", encoding="utf-8")
        with self.assertRaises(interview.InterviewError):
            interview.load_interview(self.root)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: same command as Task 1 Step 2. Expected: new tests ERROR with `AttributeError` (missing names).

- [ ] **Step 3: Write the implementation (append to `interview.py`)**

Add imports at top: `import os`, `from pathlib import Path`, `from danzaboss.workstation.wizard import TERMINAL, Wizard`.

```python
INTERVIEW_RELPATH = Path(".danza") / "onboarding" / "interview.json"
MAX_ROUNDS = 3  # hard cap per phase (design decision D6)


def _fresh_record() -> dict:
    return {"rounds": [], "clear": False, "degraded": False,
            "needs_user_decision": False, "resolution": None}


def load_interview(root) -> dict:
    """Interview state, or the empty shape. Fails closed on corruption —
    the reader must not act on garbage (same asymmetry as state.py)."""
    path = Path(root) / INTERVIEW_RELPATH
    if not path.exists():
        return {"phases": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InterviewError(f"corrupt interview state: {path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("phases"), dict):
        raise InterviewError(f"corrupt interview state (shape): {path}")
    return data


def save_interview(root, data: dict) -> None:
    """Atomic replace. Whole-file overwrite is correct here: this module is
    the file's only writer and every mutation goes load -> mutate -> save
    within one request (unlike answers.json, which has two writers and
    needs state.py's merge discipline)."""
    path = Path(root) / INTERVIEW_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, path)


def begin_phase(root, step_id: str) -> dict:
    """A (re)submission restarts the grill: prior rounds interrogated
    answers that may have just changed (P3-D8)."""
    data = load_interview(root)
    data["phases"][step_id] = _fresh_record()
    save_interview(root, data)
    return data["phases"][step_id]


def _require_phase(wizard: Wizard, step_id: str):
    for step in wizard.flow():
        if step.id == step_id:
            if step.kind != "phase":
                raise InterviewError(
                    f"{step_id} is a {step.kind}; only phases are grilled")
            return step
    raise InterviewError(f"step not in the active flow: {step_id}")


def run_interview_round(root, step_id: str, command: list[str] | None, *,
                        timeout: int = 180) -> dict:
    """One grill round, cap-guarded. Every gate here is deterministic:
    settled records no-op, the cap escalates instead of calling again,
    and an unreachable boss records degraded so the wizard continues
    flagged, never silently (spec section 7)."""
    wizard = Wizard(root)
    step = _require_phase(wizard, step_id)
    data = load_interview(root)
    record = data["phases"].setdefault(step_id, _fresh_record())
    if (record["clear"] or record["resolution"] is not None
            or record["needs_user_decision"] or record["degraded"]):
        return record
    if len(record["rounds"]) >= MAX_ROUNDS:
        record["needs_user_decision"] = True  # defensive; set below normally
        save_interview(root, data)
        return record
    if command is None:
        record["degraded"] = True
        record["degraded_reason"] = ("no headless boss runner configured "
                                     "(open MODELS or run 'danza runners')")
        save_interview(root, data)
        return record
    answers = wizard.answers
    phase_answers = {q.id: answers[q.id]
                     for q in step.questions if q.id in answers}
    prompt = build_interview_prompt(step.title, phase_answers, answers,
                                    record["rounds"],
                                    memory=checkpoints.read_memory(root))
    try:
        reply = call_interview(command, prompt, timeout=timeout)
    except checkpoints.CheckpointError as exc:
        record["degraded"] = True
        record["degraded_reason"] = str(exc)
        save_interview(root, data)
        return record
    record["rounds"].append({**reply, "answers": {}})
    record["clear"] = reply["clear"]
    if not record["clear"] and len(record["rounds"]) >= MAX_ROUNDS:
        record["needs_user_decision"] = True
    save_interview(root, data)
    return record


def record_followup_answers(root, step_id: str, answers: dict) -> dict:
    """Merge the user's follow-up answers into the open round — they ride
    into the next round's prompt ('merge into the phase record')."""
    if (not isinstance(answers, dict) or not answers
            or not all(isinstance(k, str) and isinstance(v, str) and v.strip()
                       for k, v in answers.items())):
        raise InterviewError(
            "follow-up answers must map question -> non-empty text")
    data = load_interview(root)
    record = data["phases"].get(step_id)
    if record is None or not record["rounds"]:
        raise InterviewError(f"no interview round open for {step_id}")
    if (record["clear"] or record["resolution"] is not None
            or record["degraded"]):
        raise InterviewError(f"{step_id} interview already settled")
    if record["needs_user_decision"]:
        raise InterviewError(f"{step_id} escalated: resolve it instead")
    record["rounds"][-1]["answers"].update(
        {k: v.strip() for k, v in answers.items()})
    save_interview(root, data)
    return record


def resolve(root, step_id: str, decision: str) -> dict:
    """The user's final word on escalated ambiguities. No drift beyond the
    user's stated intent — the decision is recorded verbatim and closes
    the grill (spec section 7)."""
    if not isinstance(decision, str) or not decision.strip():
        raise InterviewError("resolution must be non-empty text")
    data = load_interview(root)
    record = data["phases"].get(step_id)
    if record is None:
        raise InterviewError(f"no interview record for {step_id}")
    if record["clear"] or record["resolution"] is not None:
        raise InterviewError(f"{step_id} interview already settled")
    record["resolution"] = decision.strip()
    record["needs_user_decision"] = False
    save_interview(root, data)
    return record


def phase_clear(record: dict | None) -> bool:
    """THE clarity gate (D6), pure and deterministic. None = the phase was
    submitted outside the dashboard (library/CLI onboarding) — the
    interview is an additive product surface, not a new wizard
    invariant. Degraded passes flagged: spec.md carries the honesty."""
    if record is None:
        return True
    return bool(record["clear"] or record["degraded"]
                or record["resolution"] is not None)


def blocking_phase(root, wizard: Wizard | None = None) -> str | None:
    """First flow phase that is terminal but not clear — what the UI must
    grill and what approve/finish/other-submits wait on."""
    wizard = wizard or Wizard(root)
    records = load_interview(root)["phases"]
    for step in wizard.flow():
        if step.kind != "phase":
            continue
        if (wizard.status(step.id) in TERMINAL
                and not phase_clear(records.get(step.id))):
            return step.id
    return None


def open_questions(root, wizard: Wizard | None = None) -> tuple[str, ...]:
    """Spec section-8 lines: degraded grills and user-final decisions on
    ambiguities the AI could not clear — the honest appendix (P3-D5)."""
    wizard = wizard or Wizard(root)
    records = load_interview(root)["phases"]
    out: list[str] = []
    for step in wizard.flow():
        record = records.get(step.id)
        if record is None:
            continue
        if record["degraded"]:
            out.append(f"{step.id}: interview degraded — clarity not "
                       f"AI-verified ({record.get('degraded_reason', '')})")
        if record["resolution"] is not None:
            last = record["rounds"][-1] if record["rounds"] else {}
            listed = "; ".join(last.get("ambiguities", [])) or \
                "escalated ambiguities"
            out.append(f"{step.id}: {listed} — user decision (final): "
                       f"{record['resolution']}")
    return tuple(out)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: same command. Expected: all PASS. Also run the wizard/checkpoint modules to catch import cycles: `python3 -m unittest tests.test_workstation_wizard tests.test_workstation_checkpoints -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/interview.py danzaboss/tests/test_workstation_interview.py
git commit -m "feat(workstation): grill record store, round controller, deterministic clarity gate (P3 T2)"
```

---

### Task 3: `checkpoints.run_checkpoint` accepts `command=None`

**Files:**
- Modify: `danzaboss/workstation/checkpoints.py` (`run_checkpoint`, lines ~199–246)
- Test: `danzaboss/tests/test_workstation_checkpoints.py` (append)

**Interfaces:**
- Produces: `run_checkpoint(root, step_id, command: list[str] | None, *, timeout=180, template_dir=…) -> dict` — `command=None` records the degraded verdict (reason "no headless boss runner configured (open MODELS or run 'danza runners')") without spawning a subprocess. Existing behavior otherwise byte-identical.

- [ ] **Step 1: Write the failing test (append; reuse the module's existing fixtures/`make_stub`/wizard seeding helpers — read the file first and match its setup pattern)**

```python
class NoCommandTests(unittest.TestCase):
    def setUp(self):
        # mirror the module's existing run_checkpoint test setup: tmp repo,
        # wizard driven to cp_concept via real submits
        ...

    def test_none_command_records_degraded_verdict(self):
        verdict = checkpoints.run_checkpoint(self.root, "cp_concept", None)
        self.assertTrue(verdict["degraded"])
        self.assertIn("no headless boss", verdict["degraded_reason"])
        self.assertEqual(verdict["verdict"], "revise")
        wiz = Wizard(self.root)
        self.assertEqual(wiz.status("cp_concept"), "pending")
        self.assertTrue(wiz.result("cp_concept")["degraded"])
```

(Write the `setUp` by copying the existing degraded-CLI test's setup in that file verbatim — same submits, same tmp handling.)

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_workstation_checkpoints -v` (with the Task 1 PYTHONPATH). Expected: new test ERRORS (`TypeError`: None not iterable in `subprocess.run` path or similar).

- [ ] **Step 3: Implement**

In `run_checkpoint`, extract the existing degraded-verdict dict into a helper and branch on `command is None` before the `try`:

```python
def _degraded_verdict(concerns: list[str], reason: str) -> dict:
    """The wizard-only-continuation verdict (spec section 4): recorded,
    flagged, never silent."""
    return {
        "summary": ("checkpoint degraded: boss CLI unreachable or "
                    "returned unusable output"),
        "concerns": list(concerns),
        "follow_up_questions": [],
        "recommendation": ("wizard-only continuation; re-run this "
                           "checkpoint when the CLI is available"),
        "verdict": "revise",
        "degraded": True,
        "degraded_reason": reason,
    }
```

Change `run_checkpoint`'s signature to `command: list[str] | None` and replace its `try/except` tail:

```python
    if command is None:
        verdict = _degraded_verdict(
            concerns, "no headless boss runner configured "
                      "(open MODELS or run 'danza runners')")
    else:
        try:
            verdict = dict(call_checkpoint(command, prompt, timeout=timeout))
            verdict["degraded"] = False
        except CheckpointError as exc:
            verdict = _degraded_verdict(concerns, str(exc))
    wizard.record_result(step_id, verdict)
    return verdict
```

(Keep prompt building where it is — it is cheap and side-effect-free; only the subprocess is skipped.)

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_workstation_checkpoints -v`. Expected: ALL pass (old degraded tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/checkpoints.py danzaboss/tests/test_workstation_checkpoints.py
git commit -m "feat(workstation): run_checkpoint(command=None) records degraded verdict (P3 T3)"
```

---

### Task 4: Server read side — enriched `/api/onboarding`, boss availability, SSE token, Rule-45 team-state validation

**Files:**
- Modify: `danzaboss/workstation/server.py` (`onboarding_summary`, `_team_state`, `snapshot_token`, imports)
- Test: `danzaboss/tests/test_danza_ui.py` (extend)

**Interfaces:**
- Consumes: Task 2 (`interview` module), `runners.headless_argv/load_runners/RunnerError`, `kernel.state.TeamState/StateError`, `tree.APP_PROJECT_TYPES`, `compiler.SPEC_RELPATH`.
- Produces: `_headless_command(root) -> Optional[list]`; enriched `onboarding_summary(root)` payload — top-level gains `blocking_phase: str|None`, `boss_available: bool`, `app_project: bool`; each step gains `questions: [ {id, prompt, kind, options, required, default, value, show_if} ]` (list replaces the old int count) and, for research/checkpoint steps, `result`; phase steps with a grill record gain `interview: record`. `snapshot_token` additionally tracks `INTERVIEW_RELPATH` and `SPEC_RELPATH`.

- [ ] **Step 1: Write the failing tests (extend `test_danza_ui.py`; adjust the existing `test_onboarding_summary_reflects_wizard_state` if it asserts `questions` is an int)**

```python
class TestOnboardingDetail(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_questions_carry_render_contract(self):
        from danzaboss.workstation.server import onboarding_summary
        o = onboarding_summary(self.root)
        p0 = next(s for s in o["steps"] if s["id"] == "p0")
        q = p0["questions"][0]
        for key in ("id", "prompt", "kind", "options", "required",
                    "default", "value", "show_if"):
            self.assertIn(key, q)
        self.assertEqual(q["id"], "project_type")
        self.assertIn("saas", q["options"])

    def test_answers_show_as_values_and_interview_rides_along(self):
        from danzaboss.workstation import interview
        from danzaboss.workstation.server import onboarding_summary
        from danzaboss.workstation.wizard import Wizard
        Wizard(self.root).submit("p0", {"project_type": "saas"})
        interview.begin_phase(self.root, "p0")
        interview.run_interview_round(self.root, "p0", None)  # degraded
        o = onboarding_summary(self.root)
        p0 = next(s for s in o["steps"] if s["id"] == "p0")
        self.assertEqual(p0["questions"][0]["value"], "saas")
        self.assertTrue(p0["interview"]["degraded"])
        self.assertTrue(o["app_project"])
        self.assertFalse(o["boss_available"])
        self.assertIsNone(o["blocking_phase"])  # degraded passes the gate

    def test_snapshot_token_moves_on_interview_write(self):
        from danzaboss.workstation import interview
        from danzaboss.workstation.server import snapshot_token
        before = snapshot_token(self.root)
        interview.save_interview(self.root, {"phases": {}})
        self.assertNotEqual(before, snapshot_token(self.root))

    def test_team_state_rule45_violation_surfaces(self):
        from danzaboss.workstation.server import _team_state
        runtime = Path(self.root) / ".danza" / "runtime"
        runtime.mkdir(parents=True)
        bad = dict(TEAM_STATE, status="partying")
        (runtime / "team-state.json").write_text(json.dumps(bad))
        data, err = _team_state(self.root)
        self.assertEqual(data["status"], "partying")  # still rendered
        self.assertIn("Rule 45", err)

    def test_valid_team_state_has_no_error(self):
        from danzaboss.workstation.server import _team_state
        runtime = Path(self.root) / ".danza" / "runtime"
        runtime.mkdir(parents=True)
        (runtime / "team-state.json").write_text(json.dumps(TEAM_STATE))
        _, err = _team_state(self.root)
        self.assertEqual(err, "")
```

- [ ] **Step 2: Run to verify failures**

Run: `python3 -m unittest tests.test_danza_ui -v`. Expected: new tests FAIL (`KeyError`/`AssertionError`); existing suite otherwise green.

- [ ] **Step 3: Implement in `server.py`**

Imports to add: `from dataclasses import fields as dataclass_fields`, `from ..kernel.state import StateError, TeamState`, `from . import interview as interview_mod`, `from .compiler import SPEC_RELPATH`, `from .runners import headless_argv` (extend the existing `.runners` import line), `from .tree import APP_PROJECT_TYPES`.

```python
def _headless_command(root: str) -> Optional[list]:
    """Boss argv for dashboard-triggered AI calls, or None when no runner
    is configured/headless-capable — callers degrade honestly (P3-D4)."""
    try:
        return headless_argv(load_runners(root))
    except RunnerError:
        return None
```

Replace `_team_state` (Rule-45 surfacing, warn-only):

```python
def _team_state(root: str) -> tuple[Optional[dict], str]:
    data, err = _read_json(Path(root) / TEAM_STATE_RELPATH)
    if data is not None and not isinstance(data, dict):
        return None, "team-state.json is not a JSON object"
    if isinstance(data, dict) and not err:
        # Rule 45: the schema is machine-checkable — violations surface as
        # a warning while the raw document still renders (read-side honesty).
        known = {f.name for f in dataclass_fields(TeamState)}
        try:
            TeamState(**{k: v for k, v in data.items()
                         if k in known}).validate()
        except (StateError, TypeError) as e:
            err = f"team-state schema (Rule 45): {e}"
    return data, err
```

Replace `onboarding_summary`:

```python
def _question_dict(q, answers: dict) -> dict:
    """One Question as the form-render contract: declaration + current
    value + show_if clauses so the client can mirror branch visibility
    (the server re-validates on submit — wizard stays authoritative)."""
    return {"id": q.id, "prompt": q.prompt, "kind": q.kind,
            "options": list(q.options), "required": q.required,
            "default": q.default, "value": answers.get(q.id),
            "show_if": [[qid, list(accepted)] for qid, accepted in q.show_if]}


def onboarding_summary(root: str) -> dict:
    """Everything the ONBOARD tab needs to render forms, the grill, and
    inline research/checkpoint results (Phase 3)."""
    wiz = Wizard(root)
    answers = wiz.answers
    records = interview_mod.load_interview(root)["phases"]
    current = wiz.current_step()
    steps = []
    for s in wiz.flow():
        entry = {"id": s.id, "kind": s.kind, "title": s.title,
                 "status": wiz.status(s.id),
                 "questions": [_question_dict(q, answers)
                               for q in s.questions]}
        if s.kind != "phase":
            entry["result"] = wiz.result(s.id)
        record = records.get(s.id)
        if record is not None:
            entry["interview"] = record
        steps.append(entry)
    project_type = wiz.project_type()
    return {"project_type": project_type,
            "complete": wiz.is_complete(),
            "current_step": current.id if current else None,
            "answered": len(answers),
            "blocking_phase": interview_mod.blocking_phase(root, wiz),
            "boss_available": _headless_command(root) is not None,
            "app_project": project_type in APP_PROJECT_TYPES,
            "steps": steps}
```

Extend `snapshot_token`'s relpath tuple with `interview_mod.INTERVIEW_RELPATH, SPEC_RELPATH` (keeps the Phase 2 final-review lesson: every state file the UI renders must move the token).

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_danza_ui -v`. Expected: ALL pass (fix any Phase 2 assertion that treated `questions` as an int — the seeded `TEAM_STATE` fixture is kernel-valid: status `in_progress`, `max_features_per_turn` 2, defaults fill `mode`/`schema_version`).

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/server.py danzaboss/tests/test_danza_ui.py
git commit -m "feat(workstation): onboarding form contract API, boss probe, Rule-45 team-state check, SSE token (P3 T4)"
```

---

### Task 5: Server write side — `POST /api/onboard/*` routes

**Files:**
- Modify: `danzaboss/workstation/server.py` (`do_POST`, new module-level post functions, `GateConflict`, `_post_body`)
- Test: Create `danzaboss/tests/test_danza_onboard_api.py` (with the `install_stub_boss` fixture from the header)

**Interfaces:**
- Consumes: Tasks 2–4; `research_mod` (`from . import research as research_mod`), `checkpoints_mod` (`from . import checkpoints as checkpoints_mod`).
- Produces: `class GateConflict(Exception)`; `post_submit/post_followup/post_resolve/post_research/post_checkpoint/post_approve(root, body) -> dict` (all return `{"ok": True, ..., "onboarding": onboarding_summary(root)}`); `_POST_ROUTES` dict mapping the seven `/api/onboard/…` paths (finish added in Task 6 — register the route name now with a placeholder that raises `GateConflict("finish lands in Task 6")` OR simply add it in Task 6; choose: **add it in Task 6**, keep `_POST_ROUTES` with six entries here). HTTP: gate conflicts → 409; `ValueError` family (WizardError, InterviewError, CheckpointError, ResearchError, RunnerError, PlanningError) → 400; unknown POST route → 404; `/cortex/*` POST passthrough unchanged.

- [ ] **Step 1: Write the failing tests**

```python
"""Phase 3 write-side acceptance: dashboard onboarding POST routes."""
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.workstation.runners import RUNNERS_RELPATH, SCHEMA_VERSION
from danzaboss.workstation.server import serve_in_thread
from danzaboss.workstation.wizard import Wizard

# … install_stub_boss + stub bodies from the plan header …

UNCLEAR_BODY = ("import json\n"
                "print(json.dumps({'ambiguities': ['which currency?'],"
                " 'follow_up_questions': ['USD or EUR?'], 'clear': False}))\n")
CLEAR_BODY = ("import json\n"
              "print(json.dumps({'ambiguities': [],"
              " 'follow_up_questions': [], 'clear': True}))\n")

P1_ANSWERS = {"project_name": "Dogly", "concept_what": "a dog-walking app",
              "concept_who": "dog owners", "concept_problem": "no time",
              "features_must": ["book a walker"], "non_goals": ["social feed"]}


def post(port, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class OnboardPostTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.server, self.port = serve_in_thread(str(self.root))
        self.addCleanup(self.server.shutdown)

    def test_submit_validates_and_advances(self):
        install_stub_boss(self.root, CLEAR_BODY)
        status, out = post(self.port, "/api/onboard/submit",
                           {"step_id": "p0", "answers": {"project_type": "saas"}})
        self.assertEqual(status, 200)
        self.assertTrue(out["interview"]["clear"])
        self.assertEqual(out["onboarding"]["current_step"], "p1")

    def test_bad_answer_is_400_with_reason(self):
        install_stub_boss(self.root, CLEAR_BODY)
        status, out = post(self.port, "/api/onboard/submit",
                           {"step_id": "p0", "answers": {"project_type": "yacht"}})
        self.assertEqual(status, 400)
        self.assertIn("project_type", out["error"])

    def test_unclear_grill_blocks_other_submits_409(self):
        install_stub_boss(self.root, UNCLEAR_BODY)
        post(self.port, "/api/onboard/submit",
             {"step_id": "p0", "answers": {"project_type": "saas"}})
        # p0 grill is open -> submitting p1 is gated
        status, out = post(self.port, "/api/onboard/submit",
                           {"step_id": "p1", "answers": P1_ANSWERS})
        self.assertEqual(status, 409)
        self.assertIn("p0", out["error"])

    def test_followup_then_clear_unblocks(self):
        script = install_stub_boss(self.root, UNCLEAR_BODY)
        post(self.port, "/api/onboard/submit",
             {"step_id": "p0", "answers": {"project_type": "saas"}})
        script.write_text(CLEAR_BODY, encoding="utf-8")
        status, out = post(self.port, "/api/onboard/followup",
                           {"step_id": "p0", "answers": {"USD or EUR?": "USD"}})
        self.assertEqual(status, 200)
        self.assertIsNone(out["onboarding"]["blocking_phase"])

    def test_resolve_needs_escalation_flow(self):
        install_stub_boss(self.root, UNCLEAR_BODY)
        post(self.port, "/api/onboard/submit",
             {"step_id": "p0", "answers": {"project_type": "saas"}})
        for _ in range(2):
            post(self.port, "/api/onboard/followup",
                 {"step_id": "p0", "answers": {"USD or EUR?": "hmm"}})
        status, out = post(self.port, "/api/onboard/resolve",
                           {"step_id": "p0", "decision": "USD only"})
        self.assertEqual(status, 200)
        self.assertEqual(out["interview"]["resolution"], "USD only")
        self.assertIsNone(out["onboarding"]["blocking_phase"])

    def test_research_without_provider_records_skip(self):
        # NO runners.json and no TAVILY key: the grill degrades (gate
        # passes) and research honestly records the skipped digest
        saved = os.environ.pop("TAVILY_API_KEY", None)
        self.addCleanup(lambda: saved and os.environ.__setitem__(
            "TAVILY_API_KEY", saved))
        post(self.port, "/api/onboard/submit",
             {"step_id": "p0", "answers": {"project_type": "saas"}})
        post(self.port, "/api/onboard/submit",
             {"step_id": "p1", "answers": P1_ANSWERS})
        status, out = post(self.port, "/api/onboard/research", {})
        self.assertEqual(status, 200)
        self.assertTrue(out["digest"]["skipped"])

    def test_checkpoint_runs_and_approval_is_gated_by_grill(self):
        script = install_stub_boss(self.root, CLEAR_BODY)
        self._complete_through_p1()
        post(self.port, "/api/onboard/research", {})
        verdict_body = (
            "import json\n"
            "print(json.dumps({'summary': 'ok', 'concerns': [],"
            " 'follow_up_questions': [], 'recommendation': 'go',"
            " 'verdict': 'approve'}))\n")
        script.write_text(verdict_body, encoding="utf-8")
        status, out = post(self.port, "/api/onboard/checkpoint",
                           {"step_id": "cp_concept"})
        self.assertEqual(status, 200)
        self.assertEqual(out["verdict"]["verdict"], "approve")
        status, _ = post(self.port, "/api/onboard/approve",
                         {"step_id": "cp_concept"})
        self.assertEqual(status, 200)
        self.assertEqual(Wizard(str(self.root)).status("cp_concept"),
                         "approved")

    def test_approve_without_verdict_is_409(self):
        install_stub_boss(self.root, CLEAR_BODY)
        self._complete_through_p1()
        post(self.port, "/api/onboard/research", {})
        status, out = post(self.port, "/api/onboard/approve",
                           {"step_id": "cp_concept"})
        self.assertEqual(status, 409)
        self.assertIn("review", out["error"])

    def test_unknown_route_404_and_bad_body_400(self):
        status, _ = post(self.port, "/api/onboard/nope", {})
        self.assertEqual(status, 404)
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/onboard/submit",
            data=b"not json", method="POST")
        try:
            urllib.request.urlopen(req, timeout=10)
            self.fail("expected 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

    def _complete_through_p1(self):
        if not (self.root / RUNNERS_RELPATH).exists():
            install_stub_boss(self.root, CLEAR_BODY)
        post(self.port, "/api/onboard/submit",
             {"step_id": "p0", "answers": {"project_type": "saas"}})
        post(self.port, "/api/onboard/submit",
             {"step_id": "p1", "answers": P1_ANSWERS})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failures**

Run: `python3 -m unittest tests.test_danza_onboard_api -v`. Expected: FAIL — POST routes return 405 (Phase 2 read-only guard).

- [ ] **Step 3: Implement in `server.py`**

Add imports: `from . import checkpoints as checkpoints_mod`, `from . import research as research_mod`, `from .wizard import Wizard, WizardError` (extend existing).

```python
class GateConflict(Exception):
    """A write that must wait: open grill, missing verdict, wrong order."""


def _require(body: dict, key: str, kind: type):
    value = body.get(key)
    if not isinstance(value, kind):
        raise ValueError(f"body.{key} must be {kind.__name__}")
    return value


def post_submit(root: str, body: dict) -> dict:
    """Phase answers in, grill round out. The submit itself is the wizard's
    (validation + stale-downstream unchanged); the grill starts fresh on
    every (re)submission (P3-D8)."""
    step_id = _require(body, "step_id", str)
    answers = _require(body, "answers", dict)
    wiz = Wizard(root)
    blocking = interview_mod.blocking_phase(root, wiz)
    if blocking and blocking != step_id:
        raise GateConflict(
            f"phase {blocking} has open ambiguities — settle the grill first")
    wiz.submit(step_id, answers)
    interview_mod.begin_phase(root, step_id)
    record = interview_mod.run_interview_round(
        root, step_id, _headless_command(root))
    return {"ok": True, "interview": record,
            "onboarding": onboarding_summary(root)}


def post_followup(root: str, body: dict) -> dict:
    step_id = _require(body, "step_id", str)
    answers = _require(body, "answers", dict)
    interview_mod.record_followup_answers(root, step_id, answers)
    record = interview_mod.run_interview_round(
        root, step_id, _headless_command(root))
    return {"ok": True, "interview": record,
            "onboarding": onboarding_summary(root)}


def post_resolve(root: str, body: dict) -> dict:
    step_id = _require(body, "step_id", str)
    decision = _require(body, "decision", str)
    record = interview_mod.resolve(root, step_id, decision)
    return {"ok": True, "interview": record,
            "onboarding": onboarding_summary(root)}


def post_research(root: str, body: dict) -> dict:
    """The POST is the click, and the click IS the user approval external
    research requires in every profile (research.py contract)."""
    command = _headless_command(root)
    provider = None
    if command is not None:
        provider = (research_mod.tavily_from_env(command)
                    or research_mod.BossWebProvider(command))
    digest = research_mod.run_reality_check(root, provider)
    return {"ok": True, "digest": digest,
            "onboarding": onboarding_summary(root)}


def post_checkpoint(root: str, body: dict) -> dict:
    step_id = _require(body, "step_id", str)
    verdict = checkpoints_mod.run_checkpoint(
        root, step_id, _headless_command(root))
    return {"ok": True, "verdict": verdict,
            "onboarding": onboarding_summary(root)}


def post_approve(root: str, body: dict) -> dict:
    """Approval stays a user act (W1 law); the grill gate holds it until
    every submitted phase is clear (spec section 7 clarity gate)."""
    step_id = _require(body, "step_id", str)
    wiz = Wizard(root)
    blocking = interview_mod.blocking_phase(root, wiz)
    if blocking:
        raise GateConflict(
            f"cannot approve {step_id}: phase {blocking} has open ambiguities")
    result = wiz.result(step_id)
    if result is None:
        raise GateConflict(f"cannot approve {step_id}: run the review first")
    wiz.record_result(step_id, result, approved=True)
    return {"ok": True, "onboarding": onboarding_summary(root)}


_POST_ROUTES = {
    "/api/onboard/submit": post_submit,
    "/api/onboard/followup": post_followup,
    "/api/onboard/resolve": post_resolve,
    "/api/onboard/research": post_research,
    "/api/onboard/checkpoint": post_checkpoint,
    "/api/onboard/approve": post_approve,
}
```

In `DanzaUIHandler`, add `_post_body` and replace `do_POST`:

```python
    def _post_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"body is not valid JSON: {e}")
        if not isinstance(data, dict):
            raise ValueError("body must be a JSON object")
        return data

    def do_POST(self):
        route = urllib.parse.urlparse(self.path).path
        if route.startswith("/cortex/"):
            self.path = self.path[len("/cortex"):]
            CortexUIHandler.do_POST(self)
            return
        handler = _POST_ROUTES.get(route)
        if handler is None:
            self._json({"error": "not found"}, 404)
            return
        try:
            self._json(handler(self.root, self._post_body()))
        except GateConflict as e:
            self._json({"error": str(e)}, 409)
        except ValueError as e:
            # WizardError / InterviewError / CheckpointError / ResearchError
            # / RunnerError / PlanningError are ValueError subclasses — one
            # honest 400 with the reason.
            self._json({"error": str(e)}, 400)
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001 — surface as JSON, never crash
            try:
                self._json({"error": str(e)}, 500)
            except Exception:
                pass
```

Note the Phase 2 405 guard is replaced by the route table (unknown → 404). Update any Phase 2 test asserting 405 on POST (`test_danza_ui.py` "read-only" test) to assert 404 on an unknown route instead — the read-only *product-state* guarantee is now carried by the route allowlist.

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_danza_onboard_api tests.test_danza_ui -v`. Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/server.py danzaboss/tests/test_danza_onboard_api.py danzaboss/tests/test_danza_ui.py
git commit -m "feat(workstation): dashboard onboarding POST routes with grill gating (P3 T5)"
```

---

### Task 6: Finish flow — `finish_onboarding` + `POST /api/onboard/finish` + full hermetic acceptance run

**Files:**
- Modify: `danzaboss/workstation/server.py`
- Test: `danzaboss/tests/test_danza_onboard_api.py` (append)

**Interfaces:**
- Consumes: `compiler.compile_spec/write_spec/SPEC_RELPATH`, `planner.run_planning/PLAN_JSON_RELPATH/PlanningUnavailable`, `templates_mod.load_templates`, `checkpoints_mod.CHECKPOINT_IDS`, `interview_mod.open_questions/blocking_phase`, `tree.APP_PROJECT_TYPES`.
- Produces: `finish_onboarding(root, command: list[str] | None) -> dict` returning `run_planning`'s payload plus `{"spec": str(spec_path)}`; `post_finish(root, body)`; `_POST_ROUTES["/api/onboard/finish"]`.

- [ ] **Step 1: Write the failing tests (append)**

```python
class FinishTests(unittest.TestCase):
    """Spec section 7 acceptance: full hermetic run compiles spec + plan."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        # a real key in the environment would route research to Tavily's API
        saved = os.environ.pop("TAVILY_API_KEY", None)
        self.addCleanup(lambda: saved and os.environ.__setitem__(
            "TAVILY_API_KEY", saved))
        self.server, self.port = serve_in_thread(str(self.root))
        self.addCleanup(self.server.shutdown)
        self.script = install_stub_boss(self.root, SWITCHING_STUB)

    def _onboard_everything(self):
        """Drive the whole wizard over HTTP: p0 grill unclear once
        (follow-up answered), everything else clear; research; three
        checkpoints run + approved; p2..p5 submitted."""
        post(self.port, "/api/onboard/submit",
             {"step_id": "p0", "answers": {"project_type": "saas"}})
        # first interview call was unclear -> answer and clear it
        post(self.port, "/api/onboard/followup",
             {"step_id": "p0", "answers": {"Which currency?": "USD"}})
        post(self.port, "/api/onboard/submit",
             {"step_id": "p1", "answers": P1_ANSWERS})
        post(self.port, "/api/onboard/research", {})
        post(self.port, "/api/onboard/checkpoint", {"step_id": "cp_concept"})
        post(self.port, "/api/onboard/approve", {"step_id": "cp_concept"})
        post(self.port, "/api/onboard/submit",
             {"step_id": "p2", "answers": {"capabilities": ["payments"]}})
        post(self.port, "/api/onboard/submit",
             {"step_id": "p3", "answers": {"stack_choice": "no_preference"}})
        post(self.port, "/api/onboard/checkpoint", {"step_id": "cp_stack"})
        post(self.port, "/api/onboard/approve", {"step_id": "cp_stack"})
        post(self.port, "/api/onboard/submit", {"step_id": "p4", "answers": {}})
        post(self.port, "/api/onboard/submit",
             {"step_id": "p5", "answers": {"repo_mode": "fresh"}})
        post(self.port, "/api/onboard/checkpoint", {"step_id": "cp_final"})
        post(self.port, "/api/onboard/approve", {"step_id": "cp_final"})

    def test_full_run_compiles_spec_and_plan(self):
        self._onboard_everything()
        status, out = post(self.port, "/api/onboard/finish", {})
        self.assertEqual(status, 200, out)
        spec = (self.root / ".danza" / "spec.md").read_text(encoding="utf-8")
        self.assertIn("# Spec — Dogly", spec)
        self.assertTrue((self.root / ".danza" / "plan.json").exists())
        self.assertTrue((self.root / ".danza" / "plan.md").exists())
        status, _ = post(self.port, "/api/onboard/finish", {})
        self.assertEqual(status, 200)  # regeneration is idempotent

    def test_finish_before_complete_is_409(self):
        post(self.port, "/api/onboard/submit",
             {"step_id": "p0", "answers": {"project_type": "saas"}})
        status, out = post(self.port, "/api/onboard/finish", {})
        self.assertEqual(status, 409)

    def test_seed_project_cannot_finish(self):
        post(self.port, "/api/onboard/submit",
             {"step_id": "p0", "answers": {"project_type": "workflow"}})
        post(self.port, "/api/onboard/followup",
             {"step_id": "p0", "answers": {"Which currency?": "n/a"}})
        post(self.port, "/api/onboard/submit",
             {"step_id": "p_seed", "answers": {
                 "seed_name": "idea", "seed_intent": "a workflow thing"}})
        status, out = post(self.port, "/api/onboard/finish", {})
        self.assertEqual(status, 400)
        self.assertIn("seed", out["error"].lower())
```

Only degraded/resolution lines reach the spec's §8 appendix (answered follow-ups live in interview.json). Add one resolution-path test:

```python
    def test_escalated_resolution_reaches_spec_appendix(self):
        # force cap escalation on p1, resolve, then finish
        ...  # same drive as _onboard_everything but with an always-unclear
             # stub during p1, then resolve, then swap stub to SWITCHING_STUB
        spec = (self.root / ".danza" / "spec.md").read_text(encoding="utf-8")
        self.assertIn("user decision (final): USD only", spec)
```

(Implementer: write this test fully — swap the stub script's body between phases exactly as `test_followup_then_clear_unblocks` does; it's the same file-rewrite trick.)

- [ ] **Step 2: Run to verify failures**

Run: `python3 -m unittest tests.test_danza_onboard_api.FinishTests -v`. Expected: 404 on `/api/onboard/finish` (route missing).

- [ ] **Step 3: Implement in `server.py`**

Extend planner import: `from .planner import (PLAN_JSON_RELPATH, PLAN_MD_RELPATH, PlanningError, PlanningUnavailable, parse_plan, run_planning)`; add `from . import templates as templates_mod`; extend compiler import with `compile_spec, write_spec`.

```python
def finish_onboarding(root: str, command: Optional[list]) -> dict:
    """Compile spec.md from approved answers, then run validated planning
    (spec section 7 'Finish'). Deliberately gate-checked, fail-closed:
    planning has no degraded mode — nothing downstream can proceed
    without a valid plan."""
    wiz = Wizard(root)
    if wiz.project_type() not in APP_PROJECT_TYPES:
        raise WizardError("seed projects capture an idea; only app "
                          "projects (website/saas) compile a build spec")
    if not wiz.is_complete():
        raise GateConflict("onboarding is not complete — finish every "
                           "step (checkpoints need approval) first")
    blocking = interview_mod.blocking_phase(root, wiz)
    if blocking:
        raise GateConflict(
            f"phase {blocking} has open ambiguities — settle the grill first")
    if command is None:
        raise PlanningUnavailable(
            "no headless boss runner configured — planning needs one "
            "(open MODELS or run 'danza runners')")
    answers = wiz.answers
    template = None
    chosen = answers.get("stack_template")
    if chosen:
        library = {t.key: t for t in templates_mod.load_templates()}
        template = library.get(chosen)
    research_result = (wiz.result("r_reality")
                       if wiz.status("r_reality") == "complete" else None)
    verdicts = {}
    for cp_id in checkpoints_mod.CHECKPOINT_IDS:
        result = wiz.result(cp_id)
        if result:
            verdicts[cp_id] = result.get("summary", "")
    text = compile_spec(answers=answers, template=template,
                        research=research_result, checkpoints=verdicts,
                        open_questions=interview_mod.open_questions(root, wiz))
    spec_path = write_spec(root, text)
    out = run_planning(root, command)
    out["spec"] = str(spec_path)
    return out


def post_finish(root: str, body: dict) -> dict:
    out = finish_onboarding(root, _headless_command(root))
    out.update({"ok": True, "onboarding": onboarding_summary(root)})
    return out
```

Add `"/api/onboard/finish": post_finish` to `_POST_ROUTES`. `GateConflict` raised inside `finish_onboarding` maps to 409 via the existing `do_POST` handler; `WizardError`/`PlanningUnavailable`/`PlanningError` → 400.

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_danza_onboard_api -v` then the tier check `python3 -m unittest discover -s tests -p 'test_workstation*.py' -v`. Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/server.py danzaboss/tests/test_danza_onboard_api.py
git commit -m "feat(workstation): finish flow compiles spec + validated plan from the dashboard (P3 T6)"
```

---

### Task 7: Front-end — ONBOARD forms, the grill, inline actions

**Files:**
- Modify: `danzaboss/workstation/static/app.js` (replace `loadOnboard` + add helpers), `danzaboss/workstation/static/app.css` (append form styles)
- Test: `danzaboss/tests/test_danza_ui.py` (extend `TestDashboardStatic`)

**Interfaces:**
- Consumes: Task 4 payload (`o.steps[].questions[]` render contract, `o.blocking_phase`, `o.boss_available`, `o.app_project`, `step.interview`, `step.result`), Task 5/6 POST routes.
- Produces: form UX described below; all fetches origin-relative (`api/onboard/...`, no leading slash).

- [ ] **Step 1: Write the failing static tests**

```python
    def test_onboard_form_wiring_present(self):
        _, _, body = get(self.port, "/static/app.js")
        js = body.decode()
        for marker in ("api/onboard/submit", "api/onboard/followup",
                       "api/onboard/resolve", "api/onboard/research",
                       "api/onboard/checkpoint", "api/onboard/approve",
                       "api/onboard/finish", "showIfMet", "collectAnswers"):
            self.assertIn(marker, js)
        self.assertNotIn("Read-only view — dashboard onboarding forms", js)

    def test_onboard_css_form_tokens(self):
        _, _, body = get(self.port, "/static/app.css")
        self.assertIn(".field", body.decode())
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_danza_ui.TestDashboardStatic -v`. Expected: FAIL on missing markers.

- [ ] **Step 3: Implement**

In `app.js`, add a `post` helper after `api()`:

```javascript
async function post(path, body) {
  const res = await fetch(path, { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} on ${path}`);
  return data;
}
```

Replace the whole `/* ---------- onboard ---------- */` section:

```javascript
/* ---------- onboard (Phase 3: live forms + the grill) ---------- */
let onboardData = null;                       // last /api/onboarding payload
const onboard = { edit: null, error: "", busy: false };

function showIfMet(q, values) {
  return (q.show_if || []).every(([qid, ok]) => ok.includes(values[qid]));
}

function liveValues(step) {
  const values = {};
  for (const q of step.questions) if (q.value != null) values[q.id] = q.value;
  return values;
}

function fieldHTML(q) {
  const val = q.value ?? q.default ?? "";
  const opt = q.required ? "" : ' <span class="dim">(optional)</span>';
  let control;
  if (q.kind === "choice") {
    const opts = q.options.map((o) =>
      `<option value="${esc(o)}"${o === val ? " selected" : ""}>${esc(o)}</option>`).join("");
    control = `<select name="${esc(q.id)}">${val ? ""
      : '<option value="" selected disabled>choose…</option>'}${opts}</select>`;
  } else if (q.kind === "multi") {
    const set = Array.isArray(q.value) ? q.value : [];
    control = q.options.map((o) => `<label class="check">
      <input type="checkbox" name="${esc(q.id)}" value="${esc(o)}"
      ${set.includes(o) ? "checked" : ""}> ${esc(o)}</label>`).join("");
  } else if (q.kind === "longtext") {
    control = `<textarea name="${esc(q.id)}" rows="3">${esc(val)}</textarea>`;
  } else if (q.kind === "list" || q.kind === "uploads") {
    const text = Array.isArray(q.value) ? q.value.join("\n") : "";
    control = `<textarea name="${esc(q.id)}" rows="3"
      placeholder="one per line">${esc(text)}</textarea>`;
  } else {
    control = `<input type="text" name="${esc(q.id)}" value="${esc(val)}">`;
  }
  return `<div class="field"><label>${esc(q.prompt)}${opt}</label>${control}</div>`;
}

function collectAnswers(step) {
  const values = {};
  const form = $("#onboard-form");
  for (const q of step.questions) {
    const els = $$(`[name="${q.id}"]`, form);
    if (!els.length) continue;                 // hidden by show_if
    if (q.kind === "multi") {
      const picked = els.filter((e) => e.checked).map((e) => e.value);
      if (picked.length || q.required) values[q.id] = picked;
    } else if (q.kind === "list" || q.kind === "uploads") {
      const items = els[0].value.split("\n").map((s) => s.trim()).filter(Boolean);
      if (items.length) values[q.id] = items;
    } else if (els[0].value !== "") {
      values[q.id] = els[0].value;
    }
  }
  return values;
}

function formPanel(step) {
  const values = liveValues(step);
  const fields = step.questions.filter((q) => showIfMet(q, values))
    .map(fieldHTML).join("");
  return panel(step.title, `<form id="onboard-form" data-step="${esc(step.id)}">
    ${fields}<button type="submit" class="chip">Submit ${esc(step.id)}</button></form>`);
}

function grillChip(rec) {
  if (!rec) return "";
  const label = rec.resolution ? "user-decided" : rec.degraded ? "degraded"
    : rec.needs_user_decision ? "escalated" : rec.clear ? "clear"
    : `grill ${rec.rounds.length}/3`;
  const tone = rec.clear || rec.resolution ? "" : " warn-chip";
  return ` <span class="chip mono${tone}">${esc(label)}</span>`;
}

function interviewPanel(step) {
  const rec = step.interview;
  const last = rec.rounds[rec.rounds.length - 1]
    || { ambiguities: [], follow_up_questions: [] };
  const ambis = last.ambiguities.map((a) => `<li>${esc(a)}</li>`).join("");
  if (rec.needs_user_decision) {
    return panel(`The grill — ${step.title} needs your decision`, `
      <p class="warn">Still unclear after ${rec.rounds.length} rounds.
      Open ambiguities:</p><ul>${ambis}</ul>
      <form id="resolve-form" data-step="${esc(step.id)}">
        <div class="field"><label>Your decision (final — the build follows
        it verbatim)</label><textarea name="decision" rows="3"></textarea></div>
        <button type="submit" class="chip">Decide</button></form>`);
  }
  const qs = last.follow_up_questions.map((q) => `
    <div class="field"><label>${esc(q)}</label>
    <textarea data-fq="${esc(q)}" rows="2"></textarea></div>`).join("");
  return panel(`The grill — ${step.title} (round ${rec.rounds.length}/3)`, `
    ${ambis ? `<p class="dim">Ambiguities found:</p><ul>${ambis}</ul>` : ""}
    <form id="followup-form" data-step="${esc(step.id)}">${qs}
    <button type="submit" class="chip">Answer follow-ups</button></form>`);
}

function researchPanel(step) {
  const d = step.result;
  let body;
  if (d && d.skipped) {
    body = `<p class="warn">Skipped: ${esc(d.summary || d.reason)}</p>`;
  } else if (d) {
    const comp = (d.competitors || []).map((c) => `<li><b>${esc(c.name)}</b>
      <span class="dim">${esc(c.note || "")}</span></li>`).join("");
    body = `<table class="kv">
      ${row("verdict", `<span class="chip mono">${esc(d.verdict)}</span>`)}
      ${row("summary", esc(d.summary))}
      ${row("differentiation", esc(d.differentiation || ""))}</table>
      ${comp ? `<ul>${comp}</ul>` : ""}`;
  } else {
    body = `<p class="dim">Not run yet. Running searches the live market —
      your click is the approval.</p>`;
  }
  return panel(step.title,
    `${body}<button id="run-research" class="chip">Run reality check</button>`);
}

function checkpointPanel(step) {
  const v = step.result;
  let body = `<p class="dim">No review yet.</p>`;
  if (v) {
    const concerns = (v.concerns || []).map((c) => `<li>${esc(c)}</li>`).join("");
    const qs = (v.follow_up_questions || []).map((q) => `<li>${esc(q)}</li>`).join("");
    body = `<table class="kv">
      ${row("verdict", `<span class="chip mono">${esc(v.verdict)}</span>`)}
      ${row("summary", esc(v.summary))}
      ${row("recommendation", esc(v.recommendation))}</table>
      ${v.degraded ? `<p class="warn">Degraded:
        ${esc(v.degraded_reason || "boss CLI unreachable")}</p>` : ""}
      ${concerns ? `<p class="dim">Concerns</p><ul>${concerns}</ul>` : ""}
      ${qs ? `<p class="dim">Questions for you</p><ul>${qs}</ul>` : ""}`;
  }
  return panel(step.title, `${body}
    <button id="run-checkpoint" class="chip" data-step="${esc(step.id)}">Run AI review</button>
    ${v ? `<button id="approve-checkpoint" class="chip"
           data-step="${esc(step.id)}">Approve — proceed</button>` : ""}`);
}

function finishPanel(o) {
  if (!o.app_project) return panel("Finish",
    `<p class="dim">Seed idea captured — seed projects do not compile a
     build spec.</p>`);
  return panel("Finish — compile spec + plan", `
    <p>All steps complete. Compiling writes <span class="mono">.danza/spec.md</span>
    and asks the boss for a validated task plan (may take a few minutes).</p>
    <button id="finish-onboarding" class="chip">Compile spec + plan</button>`);
}

function activeStep(o) {
  if (onboard.edit) return o.steps.find((s) => s.id === onboard.edit);
  if (o.blocking_phase) return o.steps.find((s) => s.id === o.blocking_phase);
  return o.steps.find((s) => s.id === o.current_step);
}

function renderOnboard() {
  const o = onboardData;
  const step = activeStep(o);
  let main;
  if (o.blocking_phase && !onboard.edit) main = interviewPanel(step);
  else if (step && step.kind === "phase") main = formPanel(step);
  else if (step && step.kind === "research") main = researchPanel(step);
  else if (step && step.kind === "checkpoint") main = checkpointPanel(step);
  else if (o.complete) main = finishPanel(o);
  else main = `<p class="dim">Choose a project type to begin.</p>`;
  const steps = o.steps.map((s) => `<tr>
      <td class="mono dim">${esc(s.id)}</td><td>${esc(s.title)}</td>
      <td class="mono dim">${esc(s.kind)}</td>
      <td><span class="chip mono">${esc(s.status)}</span>${grillChip(s.interview)}
        ${s.kind === "phase" && s.status !== "pending"
          ? `<button class="chip edit-step" data-step="${esc(s.id)}">edit</button>`
          : ""}</td></tr>`).join("");
  const banner = [
    onboard.error ? `<p class="warn mono">${esc(onboard.error)}</p>` : "",
    onboard.busy ? `<p class="dim">working — the boss is thinking…</p>` : "",
    o.boss_available ? "" : `<p class="warn">No headless boss runner
      configured — AI review and the grill run degraded. Run
      <code>danza runners .</code></p>`].join("");
  $("#onboard-panel").innerHTML = `<table class="kv">
    ${row("project type", esc(o.project_type ?? "not chosen yet"))}
    ${row("answers stored", esc(o.answered))}
    ${row("complete", o.complete ? "yes" : "no")}
  </table>${banner}
  <table class="sessions-table"><thead>
    <tr><th>step</th><th>title</th><th>kind</th><th>status</th></tr></thead>
    <tbody>${steps}</tbody></table>${main}`;
  wireOnboard(step, o);
}

async function onboardAction(fn) {
  if (onboard.busy) return;
  onboard.busy = true;
  onboard.error = "";
  renderOnboard();
  try {
    const out = await fn();
    onboard.edit = null;
    onboardData = out.onboarding;
  } catch (e) {
    onboard.error = e.message;
  }
  onboard.busy = false;
  renderOnboard();
}

function wireOnboard(step, o) {
  $$(".edit-step").forEach((b) => b.addEventListener("click", () => {
    onboard.edit = b.dataset.step;
    renderOnboard();
  }));
  const form = $("#onboard-form");
  if (form) {
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      onboardAction(() => post("api/onboard/submit",
        { step_id: form.dataset.step, answers: collectAnswers(step) }));
    });
    // choice answers drive show_if branches — re-render with live values,
    // preserving everything typed so far
    $$("select", form).forEach((sel) => sel.addEventListener("change", () => {
      const live = collectAnswers(step);
      step.questions.forEach((q) => {
        if (live[q.id] !== undefined) q.value = live[q.id];
      });
      renderOnboard();
    }));
  }
  const followup = $("#followup-form");
  if (followup) followup.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const answers = {};
    $$("[data-fq]", followup).forEach((t) => {
      if (t.value.trim()) answers[t.dataset.fq] = t.value.trim();
    });
    if (!Object.keys(answers).length) {
      onboard.error = "answer at least one follow-up";
      renderOnboard();
      return;
    }
    onboardAction(() => post("api/onboard/followup",
      { step_id: followup.dataset.step, answers }));
  });
  const resolveForm = $("#resolve-form");
  if (resolveForm) resolveForm.addEventListener("submit", (ev) => {
    ev.preventDefault();
    onboardAction(() => post("api/onboard/resolve",
      { step_id: resolveForm.dataset.step,
        decision: resolveForm.decision.value }));
  });
  const research = $("#run-research");
  if (research) research.addEventListener("click", () =>
    onboardAction(() => post("api/onboard/research", {})));
  const cp = $("#run-checkpoint");
  if (cp) cp.addEventListener("click", () =>
    onboardAction(() => post("api/onboard/checkpoint",
      { step_id: cp.dataset.step })));
  const approve = $("#approve-checkpoint");
  if (approve) approve.addEventListener("click", () =>
    onboardAction(() => post("api/onboard/approve",
      { step_id: approve.dataset.step })));
  const finish = $("#finish-onboarding");
  if (finish) finish.addEventListener("click", () =>
    onboardAction(async () => {
      const out = await post("api/onboard/finish", {});
      $$(".tab[data-view]").find((b) => b.dataset.view === "build")?.click();
      return out;
    }));
}

async function loadOnboard() {
  onboardData = await api("api/onboarding");
  renderOnboard();
}
```

And guard SSE refreshes from nuking in-progress typing — in `refresh()`, change the onboard branch:

```javascript
    else if (state.view === "onboard") {
      const panelEl = $("#onboard-panel");
      // an SSE tick must never wipe a form mid-typing or mid-AI-call
      if (onboard.busy || (panelEl && panelEl.contains(document.activeElement))) return;
      await loadOnboard();
    }
```

Append to `app.css` (ADUSON tokens; match the file's variable names exactly — read the token block first):

```css
/* ---------- Phase 3: onboarding forms ---------- */
.field { margin: 12px 0; }
.field label {
  display: block; margin-bottom: 4px;
  font-family: "Chakra Petch", sans-serif;
  font-size: 12px; letter-spacing: .08em; text-transform: uppercase;
  color: var(--silver);
}
.field input[type="text"], .field textarea, .field select {
  width: 100%; padding: 8px 10px;
  background: var(--carbon); color: var(--text);
  border: 1px solid var(--gunmetal); border-radius: 2px;
  font-family: "IBM Plex Sans", sans-serif; font-size: 14px;
}
.field input[type="text"]:focus, .field textarea:focus, .field select:focus {
  outline: none; border-color: var(--crimson);
}
.field .check { display: inline-flex; align-items: center; gap: 6px;
  margin-right: 14px; color: var(--text); }
button.chip { cursor: pointer; }
.chip.warn-chip { border-color: var(--ember); color: var(--ember); }
```

- [ ] **Step 4: Run tests + eyeball**

Run: `python3 -m unittest tests.test_danza_ui -v`. Expected: PASS.
Then a live eyeball (controller step, Phase 2 precedent): in a temp repo with the switching stub installed, `PYTHONPATH=. python3 -m danzaboss.cli ui /tmp/<repo> --no-open --port 33199` and drive the p0→grill→followup flow in Playwright; 0 console errors; kill the server after.

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/static/app.js danzaboss/workstation/static/app.css danzaboss/tests/test_danza_ui.py
git commit -m "feat(workstation): ONBOARD tab forms, grill UI, inline research/checkpoint/finish (P3 T7)"
```

---

### Task 8: Docs + suite sync

**Files:**
- Modify: `docs/superpowers/specs/2026-07-11-danza-os-product-completion-design.md` (§7 STATUS block, mirroring §6's), `CLAUDE.md` (test count, workstation module row mentions onboarding forms + interview), `.superpowers/sdd/progress.md` (append Phase 3 section — append-only)

- [ ] **Step 1: Full suite**

Run: `./danzaboss/run_tests.sh`
Expected: OK (0 failures; count > 821 — record the exact number).

- [ ] **Step 2: Update docs**

- Spec §7: add `> **STATUS: COMPLETE <date> @<commit>** (plan: docs/superpowers/plans/2026-07-12-phase3-grilling-onboarding.md)` block after the heading, same format as §6.
- `CLAUDE.md`: replace both `821` occurrences with the new count; extend the `workstation/` row and the module-table W1 row with "adaptive interview + dashboard onboarding forms (Phase 3)".
- `.superpowers/sdd/progress.md`: append a `## Phase 3` section with per-task commits and any deferred minors.

- [ ] **Step 3: Commit**

```bash
git add docs/ CLAUDE.md .superpowers/sdd/progress.md
git commit -m "docs(specs): mark Phase 3 grilling onboarding COMPLETE; sync test count"
```

---

## Self-review (done during planning)

- **Spec §7 coverage:** forms over wizard flow → T4/T5/T7; `wizard.submit()` unchanged → nothing touches it; revision rule surfaces → stale chips + edit buttons (T7) + grill reset on resubmit (T2/T5); interview loop with `{ambiguities, follow_up_questions, clear}` → T1/T2; extra form step + merge + repeat → T5/T7 followup route; 3-round cap + `needs_user_decision` + user-final resolution → T2; deterministic gate outside the AI → `phase_clear`/`blocking_phase` (T2) enforced at submit/approve/finish (T5/T6); degraded-on-unreachable-CLI, wizard continues, spec.md appendix → T2/T3/T6 (`open_questions` → compile §8); reality-check + checkpoint verdicts inline → T5/T7; finish compiles spec + validated plan, BUILD tab shows tree → T6 (BUILD tab rendering already exists from Phase 2); hermetic acceptance tests with injected fake boss → T5/T6 (`install_stub_boss`).
- **Placeholder scan:** Task 3 Step 1 setUp and Task 6's escalated-resolution test intentionally direct the implementer to copy an existing fixture pattern from the same file (named exactly) — everything else is complete code.
- **Type consistency:** `record` shape identical across T2/T4/T5/T7; `_question_dict` keys match `fieldHTML`/`collectAnswers`/`showIfMet` consumption; route names identical in `_POST_ROUTES`, tests, and JS.
- **Known judgment calls:** listed as P3-D1…D8 above.
