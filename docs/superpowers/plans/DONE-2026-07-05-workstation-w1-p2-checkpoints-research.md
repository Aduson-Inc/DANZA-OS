# W1-P2: Checkpoints + Reality Check Research — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the two AI seams of the workstation — `checkpoints.py` (headless boss-CLI checkpoint runner with structured verdicts, Rule-32 memory reading, retry + degraded modes) and `research.py` (Reality Check provider interface with Tavily + headless-boss-with-web providers, digest cache, CORTEX observation distill) — fully tested with stub binaries, zero network in the suite.

**Architecture:** Both modules are pure libraries in `danzaboss/workstation/` that operate on a TARGET repo root, exactly like P1. They integrate with P1 through one seam: `Wizard.record_result(step_id, result, approved=False)` — checkpoints write verdicts to `cp_concept`/`cp_stack`/`cp_final` (status stays `pending`; approval is the *user's* click in P5), research writes the digest to `r_reality` (status `complete`; informational, not gating). All subprocess calls go through ONE injectable-command runner (argv-prefix list + prompt as final arg), so tests substitute a Python stub script for the `claude` CLI. Tavily is stdlib `urllib` with an injectable `urlopen`. JSON parsing is shared: `checkpoints.parse_json_reply` handles the bare object, the `claude --output-format json` envelope, and code fences; research reuses it.

**Tech Stack:** Python 3.10+ stdlib only. `unittest` (auto-discovered by `danzaboss/run_tests.sh`).

**Spec:** `docs/superpowers/specs/2026-07-05-workstation-onboarding-design.md` §3 (checkpoints.py, research.py), §4 (Phase 1.5 + checkpoint contract), §8 (AI-without-AI testing). Implementers do NOT need to read the spec — every task below is self-contained.

## Review Policy (user directive, validated by P1)

**No per-task reviews.** P1 proved the trade: per-task reviews found only minors; the single whole-branch final review caught all three real bugs. P2 runs the same way from the start:

- Implementers note any concerns inline in `.superpowers/sdd/progress.md` as deferred minors — nothing blocks on them.
- **Task 5 is the ONLY review gate:** one whole-branch code review over the full P2 diff, Important findings fixed inline with one regression test each, minors triaged into the deferred backlog.

## Model Assignment & Token Discipline

- **Task 1, 2, 5: fable (inline)** — contracts, parsing, wizard integration, final review (per the P1 phase map: "fable: contracts/parsing").
- **Tasks 3+4: ONE sonnet subagent, batched** — providers + cache are adjacent code in one file; a warm session reuses its cache instead of re-reading checkpoints.py from disk.
- **Subagents must not read** the design spec, `CLAUDE.md`, the constitution, or any module not listed in their task's Files block. This plan is the single source; re-reads are the waste we're avoiding.
- **Prompt caching note:** Claude Code caches the session prefix automatically (5-min TTL). The savings lever we control is context minimization (self-contained tasks, tight file lists) and not letting a subagent idle past the TTL between steps — run steps back-to-back.

## Global Constraints

- Python 3.10+, **stdlib only** — no pip installs anywhere in `danzaboss/` (CLAUDE.md standard).
- PEP 8, 4-space indent, `snake_case`, type hints on all public functions, docstrings that state *why*.
- **Fail closed:** validation raises `CheckpointError` / `ResearchError` (both `ValueError`); never continue past bad state. The ONE deliberate exception is checkpoint degraded mode, which is a spec'd design decision (§4): an unreachable boss CLI records a `degraded: true` verdict instead of raising, so onboarding can continue wizard-only with the flag carried into `spec.md`.
- **Deterministic:** no randomness, no wall-clock reads in logic; same inputs → same outputs.
- **Hermetic tests:** operate only on `tempfile` fixture roots; never touch this repo's real `.danza/`; **no network** (Tavily's `urlopen` is injected; the boss CLI is a stub script); no real API keys. Tests begin with `import _bootstrap  # noqa` (matches every existing test).
- Test run incantation (from repo root): `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.<module> -v`; full suite: `./danzaboss/run_tests.sh` (auto-discovers `test_*.py`). Baseline entering P2: **459 OK**.
- Commit after every task; message style `feat(workstation): W1-P2 T<n> ...` matching repo history.

## P1 Seam Reference (read-only contracts every task relies on)

- `Wizard(root)` — facade over one target repo. `wizard.answers -> dict` (copy), `wizard.result(step_id) -> dict | None`, `wizard.status(step_id) -> str`.
- `Wizard.record_result(step_id, result: dict, *, approved: bool = False)` — raises `WizardError` for phase steps, for steps not in the active flow, and for `approved=True` with any earlier non-terminal step. `checkpoint` steps → status `"approved"`/`"pending"`; `research` steps → `"complete"`. **P2 never passes `approved=True`.**
- Editing an approved/complete earlier phase stales downstream terminal steps automatically (`_stale_after` walks the full tree) — P2 inherits stale-on-edit for free and must NOT re-implement it.
- Checkpoint step ids in `tree.FLOW`: `cp_concept`, `cp_stack`, `cp_final`. Research step id: `r_reality`. These exist only in the app flow (`website`/`saas`); seed flows have none, and `record_result` correctly raises there.
- `templates.load_templates(dir=DEFAULT_DIR) -> tuple[StackTemplate, ...]` (7 ship; raises on empty/bad) and `templates.select_templates(templates, project_type, capabilities) -> list[StackTemplate]` (deterministic fit ranking, top of list = recommended). `StackTemplate` fields used here: `key, name, tagline, why, tradeoffs`.
- `compiler.compile_spec(..., research=digest, ...)` reads `digest["verdict"]`, `digest["summary"]`, `digest.get("skipped")` — the digest contract below feeds it unchanged.
- Subprocess house pattern (`runtime/verify.py`): `subprocess.run(..., capture_output=True, text=True, timeout=...)`, tail long output to ~2000 chars.

---

### Task 1: Checkpoint contract — headless runner + fail-closed verdict parsing (`checkpoints.py` part 1)

**Model:** fable (inline)

**Files:**
- Create: `danzaboss/workstation/checkpoints.py`
- Test: `danzaboss/tests/test_workstation_checkpoints.py`

**Interfaces:**
- Consumes: nothing from P1 yet (pure subprocess + parsing layer).
- Produces (Tasks 2–4 rely on these exact names):
  - `CheckpointError(ValueError)`, `CheckpointUnavailable(CheckpointError)`
  - `run_headless(command: list[str], prompt: str, *, timeout: int = 180) -> str` — raises `CheckpointUnavailable` on OSError/timeout/nonzero exit
  - `parse_json_reply(text: str) -> object` — lenient decode (bare JSON, `--output-format json` envelope, ``` fences); raises `CheckpointError`
  - `parse_verdict(text: str) -> dict` — validated `{summary, concerns, follow_up_questions, recommendation, verdict}`
  - `call_checkpoint(command: list[str], prompt: str, *, timeout: int = 180) -> dict` — one retry on garbage
  - `VERDICT_KEYS`, `VERDICTS = ("approve", "revise")`, `JSON_CONTRACT` (str)

- [ ] **Step 1: Write the failing tests**

`danzaboss/tests/test_workstation_checkpoints.py`:

```python
"""Checkpoint runner tests: AI without AI (design spec section 8).

The boss CLI is an injectable argv prefix; every test substitutes a
Python stub script, so the suite proves parse/retry/degraded behavior
with zero network and zero real CLI.
"""
import _bootstrap  # noqa: F401
import json
import sys
import tempfile
import unittest
from pathlib import Path

from danzaboss.workstation import checkpoints

VALID_VERDICT = {
    "summary": "Building a dog-walking SaaS for urban owners.",
    "concerns": ["no pricing model stated"],
    "follow_up_questions": ["Is this mobile-first?"],
    "recommendation": "Clarify pricing before the stack phase.",
    "verdict": "revise",
}


def make_stub(tmp: Path, body: str) -> list[str]:
    """A stub boss CLI: a python script receiving the prompt as argv[1]."""
    stub = tmp / "stub_boss.py"
    stub.write_text(body, encoding="utf-8")
    return [sys.executable, str(stub)]


class ParseTests(unittest.TestCase):
    def test_parse_verdict_accepts_bare_object(self):
        verdict = checkpoints.parse_verdict(json.dumps(VALID_VERDICT))
        self.assertEqual(verdict["verdict"], "revise")
        self.assertEqual(verdict["concerns"], ["no pricing model stated"])

    def test_parse_verdict_accepts_envelope_with_fenced_json(self):
        inner = "```json\n" + json.dumps(VALID_VERDICT) + "\n```"
        text = json.dumps({"type": "result", "result": inner})
        self.assertEqual(checkpoints.parse_verdict(text)["verdict"], "revise")

    def test_parse_verdict_rejects_missing_key(self):
        bad = {k: v for k, v in VALID_VERDICT.items() if k != "summary"}
        with self.assertRaises(checkpoints.CheckpointError):
            checkpoints.parse_verdict(json.dumps(bad))

    def test_parse_verdict_rejects_unknown_verdict_value(self):
        bad = dict(VALID_VERDICT, verdict="maybe")
        with self.assertRaises(checkpoints.CheckpointError):
            checkpoints.parse_verdict(json.dumps(bad))

    def test_parse_verdict_rejects_non_list_concerns(self):
        bad = dict(VALID_VERDICT, concerns="none")
        with self.assertRaises(checkpoints.CheckpointError):
            checkpoints.parse_verdict(json.dumps(bad))


class CallTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_call_returns_valid_verdict(self):
        command = make_stub(self.tmp, (
            "import json\n"
            f"print(json.dumps({VALID_VERDICT!r}))\n"))
        verdict = checkpoints.call_checkpoint(command, "review this")
        self.assertEqual(verdict["verdict"], "revise")

    def test_call_retries_once_on_garbage_then_succeeds(self):
        marker = self.tmp / "called_once"
        command = make_stub(self.tmp, (
            "import json, pathlib\n"
            f"marker = pathlib.Path({str(marker)!r})\n"
            "if marker.exists():\n"
            f"    print(json.dumps({VALID_VERDICT!r}))\n"
            "else:\n"
            "    marker.touch()\n"
            "    print('sorry, here are my thoughts...')\n"))
        verdict = checkpoints.call_checkpoint(command, "review this")
        self.assertEqual(verdict["summary"], VALID_VERDICT["summary"])
        self.assertTrue(marker.exists())

    def test_call_raises_checkpoint_error_on_garbage_twice(self):
        command = make_stub(self.tmp, "print('still not json')\n")
        with self.assertRaises(checkpoints.CheckpointError):
            checkpoints.call_checkpoint(command, "review this")

    def test_nonzero_exit_raises_unavailable(self):
        command = make_stub(self.tmp, "import sys; sys.exit(3)\n")
        with self.assertRaises(checkpoints.CheckpointUnavailable):
            checkpoints.call_checkpoint(command, "review this")

    def test_missing_binary_raises_unavailable(self):
        with self.assertRaises(checkpoints.CheckpointUnavailable):
            checkpoints.run_headless(
                [str(self.tmp / "no_such_binary")], "hi", timeout=5)

    def test_timeout_raises_unavailable(self):
        command = make_stub(self.tmp, "import time; time.sleep(5)\n")
        with self.assertRaises(checkpoints.CheckpointUnavailable):
            checkpoints.run_headless(command, "hi", timeout=1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_checkpoints -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'danzaboss.workstation.checkpoints'`

- [ ] **Step 3: Write the implementation**

`danzaboss/workstation/checkpoints.py`:

```python
"""AI checkpoint runner (design spec sections 3-4).

Builds a review prompt from answers-so-far plus the target repo's user
memory files (Constitution Rule 32), calls the boss CLI headless through
an INJECTABLE argv prefix, and parses a structured verdict. The AI only
proposes: this module never passes approved=True — approval stays a user
act (P5 server). Degraded wizard-only continuation on an unreachable CLI
is the spec'd fallback, not a silent failure: the recorded result carries
degraded=True and the compiler flags it in spec.md.
"""
from __future__ import annotations

import json
import subprocess

VERDICT_KEYS = ("summary", "concerns", "follow_up_questions",
                "recommendation", "verdict")
VERDICTS = ("approve", "revise")

JSON_CONTRACT = (
    "Respond with ONLY a JSON object, no prose around it, shaped exactly:\n"
    '{"summary": str, "concerns": [str], "follow_up_questions": [str], '
    '"recommendation": str, "verdict": "approve"|"revise"}'
)


class CheckpointError(ValueError):
    """The CLI answered, but not with a usable verdict (after one retry)."""


class CheckpointUnavailable(CheckpointError):
    """The CLI could not be run at all (missing, crashed, timed out)."""


def run_headless(command: list[str], prompt: str, *,
                 timeout: int = 180) -> str:
    """One boss-CLI call. `command` is an argv prefix (e.g. ["claude",
    "-p", "--output-format", "json"]); the prompt rides as the final
    argument, which is what lets tests substitute a stub interpreter."""
    try:
        proc = subprocess.run(list(command) + [prompt], capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CheckpointUnavailable(f"boss CLI failed to run: {exc}") from exc
    if proc.returncode != 0:
        raise CheckpointUnavailable(
            f"boss CLI exit {proc.returncode}: {(proc.stderr or '')[-2000:]}")
    return proc.stdout


def parse_json_reply(text: str) -> object:
    """Decode a JSON payload from the shapes real CLIs emit: the bare
    object, the `--output-format json` envelope ({"result": <text>}),
    and a ```json fence. Shared with research.py — one lenient decoder
    beats two divergent ones."""
    data = _loads(text)
    if isinstance(data, dict) and "result" in data and not all(
            k in data for k in VERDICT_KEYS):
        data = _loads(str(data["result"]))
    return data


def parse_verdict(text: str) -> dict:
    """Fail-closed validation of the checkpoint contract (spec section 4)."""
    data = parse_json_reply(text)
    if not isinstance(data, dict):
        raise CheckpointError(f"verdict is not an object: {text[:200]!r}")
    missing = [k for k in VERDICT_KEYS if k not in data]
    if missing:
        raise CheckpointError(f"verdict missing keys {missing}")
    if not isinstance(data["summary"], str) or not data["summary"].strip():
        raise CheckpointError("verdict.summary must be non-empty text")
    for key in ("concerns", "follow_up_questions"):
        value = data[key]
        if (not isinstance(value, list)
                or not all(isinstance(v, str) for v in value)):
            raise CheckpointError(f"verdict.{key} must be a list of strings")
    if not isinstance(data["recommendation"], str):
        raise CheckpointError("verdict.recommendation must be text")
    if data["verdict"] not in VERDICTS:
        raise CheckpointError(f"verdict.verdict must be one of {VERDICTS}")
    return {key: data[key] for key in VERDICT_KEYS}


def call_checkpoint(command: list[str], prompt: str, *,
                    timeout: int = 180) -> dict:
    """Call once; ONE retry on garbage with a harder instruction (spec
    section 4). Unavailability propagates — the caller decides whether
    to degrade (run_checkpoint does) or surface (research does)."""
    try:
        return parse_verdict(run_headless(command, prompt, timeout=timeout))
    except CheckpointUnavailable:
        raise
    except CheckpointError:
        retry = (prompt + "\n\nYour previous reply was not valid JSON. "
                 + JSON_CONTRACT)
        return parse_verdict(run_headless(command, retry, timeout=timeout))


def _loads(text: str) -> object:
    """json.loads that tolerates surrounding prose and code fences by
    slicing the outermost object — models decorate, contracts don't."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise CheckpointError(f"no JSON object in reply: {text[:200]!r}")
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise CheckpointError(
                f"unparseable JSON in reply: {text[:200]!r}") from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_checkpoints -v`
Expected: all PASS (the timeout test takes ~1s by design)

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/checkpoints.py danzaboss/tests/test_workstation_checkpoints.py
git commit -m "feat(workstation): W1-P2 T1 checkpoint contract — headless runner, fail-closed verdict parse, one-retry"
```

---

### Task 2: Prompt builders, Rule-32 memory, wizard integration (`checkpoints.py` part 2)

**Model:** fable (inline)

**Files:**
- Modify: `danzaboss/workstation/checkpoints.py` (append; Task 1 content unchanged)
- Modify: `danzaboss/tests/test_workstation_checkpoints.py` (append test classes)

**Interfaces:**
- Consumes: Task 1's `call_checkpoint`, `CheckpointError`, `JSON_CONTRACT`; P1's `Wizard`, `templates.load_templates` / `select_templates`.
- Produces (P5 server + tests rely on):
  - `CHECKPOINT_IDS = ("cp_concept", "cp_stack", "cp_final")`
  - `read_memory(root, *, cap: int = 8000) -> str`
  - `build_prompt(step_id, answers: dict, *, research: dict | None = None, stack_options: tuple = (), memory: str = "", concerns: tuple[str, ...] = ()) -> str`
  - `run_checkpoint(root, step_id: str, command: list[str], *, timeout: int = 180, template_dir=templates.DEFAULT_DIR) -> dict` — records via `wizard.record_result(step_id, verdict)`, returns the verdict dict; result always carries `degraded: bool` (+ `degraded_reason` when True)

- [ ] **Step 1: Write the failing tests**

Append to `danzaboss/tests/test_workstation_checkpoints.py` (add `from danzaboss.workstation.wizard import Wizard` to the imports):

```python
P1_ANSWERS = {
    "project_name": "WalkWise",
    "concept_what": "Dog walking marketplace",
    "concept_who": "Urban dog owners",
    "concept_problem": "Finding trusted walkers is slow",
    "features_must": ["book a walk", "walker profiles"],
    "non_goals": ["pet supplies store"],
}


def make_app_wizard(root: Path) -> Wizard:
    """A target repo mid-onboarding: p0+p1 done, cp_concept is next."""
    wizard = Wizard(root)
    wizard.submit("p0", {"project_type": "saas"})
    wizard.submit("p1", P1_ANSWERS)
    return wizard


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_no_memory_dir_reads_empty(self):
        self.assertEqual(checkpoints.read_memory(self.tmp), "")

    def test_memory_files_concatenated_sorted_and_capped(self):
        mem = self.tmp / ".danza" / "memory"
        mem.mkdir(parents=True)
        (mem / "b-style.md").write_text("likes HTMX", encoding="utf-8")
        (mem / "a-user.md").write_text("no dark mode", encoding="utf-8")
        text = checkpoints.read_memory(self.tmp)
        self.assertLess(text.index("a-user.md"), text.index("b-style.md"))
        self.assertIn("no dark mode", text)
        self.assertLessEqual(
            len(checkpoints.read_memory(self.tmp, cap=10)), 10)


class PromptTests(unittest.TestCase):
    def test_prompt_includes_answers_memory_and_contract(self):
        prompt = checkpoints.build_prompt(
            "cp_concept", {"concept_what": "walk dogs"},
            memory="prefers Python")
        self.assertIn("walk dogs", prompt)
        self.assertIn("prefers Python", prompt)
        self.assertIn('"verdict": "approve"|"revise"', prompt)

    def test_prompt_is_deterministic(self):
        args = ("cp_final", {"a": "1", "b": "2"})
        self.assertEqual(checkpoints.build_prompt(*args),
                         checkpoints.build_prompt(*args))

    def test_prompt_rejects_non_checkpoint_step(self):
        with self.assertRaises(checkpoints.CheckpointError):
            checkpoints.build_prompt("p1", {})

    def test_skipped_research_is_not_injected(self):
        prompt = checkpoints.build_prompt(
            "cp_concept", {}, research={"skipped": True, "summary": "x"})
        self.assertNotIn("Reality digest", prompt)


class RunCheckpointTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        make_app_wizard(self.tmp)

    def test_valid_run_records_pending_verdict(self):
        command = make_stub(self.tmp, (
            "import json\n"
            f"print(json.dumps({VALID_VERDICT!r}))\n"))
        verdict = checkpoints.run_checkpoint(self.tmp, "cp_concept", command)
        self.assertFalse(verdict["degraded"])
        wizard = Wizard(self.tmp)
        self.assertEqual(wizard.status("cp_concept"), "pending")
        self.assertEqual(wizard.result("cp_concept")["summary"],
                         VALID_VERDICT["summary"])

    def test_unreachable_cli_records_degraded_verdict(self):
        command = make_stub(self.tmp, "import sys; sys.exit(9)\n")
        verdict = checkpoints.run_checkpoint(self.tmp, "cp_concept", command)
        self.assertTrue(verdict["degraded"])
        self.assertEqual(verdict["verdict"], "revise")
        self.assertTrue(Wizard(self.tmp).result("cp_concept")["degraded"])

    def test_cp_stack_prompt_carries_template_grounding_and_bad_key_concern(self):
        wizard = Wizard(self.tmp)
        wizard.submit("p2", {"capabilities": ["accounts_auth", "payments"]})
        wizard.submit("p3", {"stack_choice": "template",
                             "stack_template": "no-such-template"})
        prompt_file = self.tmp / "prompt.txt"
        command = make_stub(self.tmp, (
            "import json, pathlib, sys\n"
            f"pathlib.Path({str(prompt_file)!r}).write_text(sys.argv[1])\n"
            f"print(json.dumps({VALID_VERDICT!r}))\n"))
        checkpoints.run_checkpoint(self.tmp, "cp_stack", command)
        prompt = prompt_file.read_text(encoding="utf-8")
        self.assertIn("Fitting stack templates:", prompt)
        self.assertIn("'no-such-template' is not in the template library",
                      prompt)

    def test_phase_step_is_rejected_by_wizard_seam(self):
        command = make_stub(self.tmp, "print('unused')\n")
        with self.assertRaises(ValueError):
            checkpoints.run_checkpoint(self.tmp, "p1", command)
```

- [ ] **Step 2: Run tests to verify the new classes fail**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_checkpoints -v`
Expected: Task 1 classes PASS; new classes FAIL with `AttributeError: ... no attribute 'read_memory'` (etc.)

- [ ] **Step 3: Write the implementation**

Append to `danzaboss/workstation/checkpoints.py` (extend the imports at the top of the file to):

```python
import json
import subprocess
from pathlib import Path

from danzaboss.workstation import templates as templates_mod
from danzaboss.workstation.wizard import Wizard
```

then append after `_loads`:

```python
CHECKPOINT_IDS = ("cp_concept", "cp_stack", "cp_final")
MEMORY_RELDIR = Path(".danza") / "memory"

_FOCUS = {
    "cp_concept": (
        "Concept review: reflect back what the user is building in plain "
        "words, flag contradictions and unstated assumptions, and ask the "
        "follow-up questions a senior product engineer would ask. Ground "
        "the review in the reality digest when one is present."),
    "cp_stack": (
        "Stack review: judge the chosen stack against the fitting templates "
        "listed. For a custom stack give reasoned pushback plus the nearest "
        "template; for no-preference recommend one option WITH trade-offs, "
        "never a bare pick (Rule 30); the user may still insist."),
    "cp_final": (
        "Final rundown: narrate the whole build back to the user — concept, "
        "features with priorities, stack, design, cadence — and list every "
        "gap that would surprise them mid-build."),
}


def read_memory(root, *, cap: int = 8000) -> str:
    """Rule 32: user memory files must inform checkpoint review when they
    exist. Reads the TARGET repo's .danza/memory/*.md, sorted for
    determinism, capped so memory informs the prompt without drowning
    the answers."""
    directory = Path(root) / MEMORY_RELDIR
    if not directory.is_dir():
        return ""
    parts = [f"--- {path.name} ---\n{path.read_text(encoding='utf-8')}"
             for path in sorted(directory.glob("*.md"))]
    return "\n".join(parts)[:cap]


def build_prompt(step_id: str, answers: dict, *,
                 research: dict | None = None, stack_options: tuple = (),
                 memory: str = "", concerns: tuple[str, ...] = ()) -> str:
    """Deterministic review prompt. All variable context (answers, digest,
    templates, memory) is inlined so the headless call needs no repo
    access — the prompt IS the context."""
    if step_id not in CHECKPOINT_IDS:
        raise CheckpointError(f"not a checkpoint step: {step_id}")
    lines = ["You are the DANZA onboarding reviewer.", _FOCUS[step_id], ""]
    if memory:
        lines += ["User memory (honor these preferences — Rule 32):",
                  memory, ""]
    lines += ["Answers so far (JSON):",
              json.dumps(answers, indent=2, sort_keys=True), ""]
    if research and not research.get("skipped"):
        lines += ["Reality digest (JSON):",
                  json.dumps(research, indent=2, sort_keys=True), ""]
    if stack_options:
        lines.append("Fitting stack templates:")
        lines += [f"- {t.key}: {t.name} — {t.tagline} (why: {t.why}; "
                  f"tradeoffs: {t.tradeoffs})" for t in stack_options]
        lines.append("")
    for concern in concerns:
        lines.append(f"KNOWN ISSUE to address in your review: {concern}")
    lines += ["", JSON_CONTRACT]
    return "\n".join(lines)


def run_checkpoint(root, step_id: str, command: list[str], *,
                   timeout: int = 180,
                   template_dir=templates_mod.DEFAULT_DIR) -> dict:
    """Build context from the target repo, call the boss CLI, record the
    verdict on the wizard. Never passes approved=True — approval is the
    user's click (P5). An unreachable CLI records a degraded verdict so
    onboarding can continue wizard-only, flagged (spec section 4)."""
    wizard = Wizard(root)
    answers = wizard.answers
    concerns: list[str] = []
    stack_options: tuple = ()
    if step_id == "cp_stack":
        library = templates_mod.load_templates(template_dir)
        stack_options = tuple(templates_mod.select_templates(
            library, answers.get("project_type", ""),
            answers.get("capabilities", [])))
        chosen = answers.get("stack_template")
        if (answers.get("stack_choice") == "template" and chosen is not None
                and chosen not in {t.key for t in library}):
            concerns.append(
                f"{chosen!r} is not in the template library")
    prompt = build_prompt(step_id, answers,
                          research=wizard.result("r_reality"),
                          stack_options=stack_options,
                          memory=read_memory(root),
                          concerns=tuple(concerns))
    try:
        verdict = dict(call_checkpoint(command, prompt, timeout=timeout))
        verdict["degraded"] = False
    except CheckpointError as exc:
        verdict = {
            "summary": ("checkpoint degraded: boss CLI unreachable or "
                        "returned unusable output"),
            "concerns": list(concerns),
            "follow_up_questions": [],
            "recommendation": ("wizard-only continuation; re-run this "
                               "checkpoint when the CLI is available"),
            "verdict": "revise",
            "degraded": True,
            "degraded_reason": str(exc),
        }
    wizard.record_result(step_id, verdict)
    return verdict
```

- [ ] **Step 4: Run the module tests, then the full suite**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_checkpoints -v`
Expected: all PASS
Run: `./danzaboss/run_tests.sh`
Expected: 459 + new tests, all OK

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/checkpoints.py danzaboss/tests/test_workstation_checkpoints.py
git commit -m "feat(workstation): W1-P2 T2 checkpoint prompts, Rule-32 memory read, run_checkpoint wizard seam + degraded mode"
```

---

### Task 3: Reality Check providers — digest contract, Tavily, boss-with-web (`research.py` part 1)

**Model:** sonnet subagent (batch with Task 4 in ONE dispatch)

**Files:**
- Create: `danzaboss/workstation/research.py`
- Test: `danzaboss/tests/test_workstation_research.py`

**Interfaces:**
- Consumes: Task 1's `checkpoints.run_headless`, `checkpoints.parse_json_reply`, `checkpoints.CheckpointError`.
- Produces (Task 4 + P5 rely on):
  - `ResearchError(ValueError)`
  - `DIGEST_VERDICTS = ("saturated", "crowded_but_viable", "novel")`, `DIGEST_KEYS = ("verdict", "summary", "competitors", "differentiation")`
  - `validate_digest(digest: dict) -> dict`
  - `build_query(answers: dict) -> str`
  - `tavily_search(query: str, api_key: str, *, urlopen=urllib.request.urlopen, timeout: int = 30) -> list[dict]` — each `{title, url, content}`
  - `build_digest_prompt(answers: dict, evidence: list[dict] | None) -> str`
  - `TavilyProvider(api_key, command, *, urlopen=...)` / `BossWebProvider(command)` — both expose `run(answers: dict, *, timeout: int) -> dict`
  - `tavily_from_env(command, env=os.environ) -> TavilyProvider | None` — reads `TAVILY_API_KEY`; None when unset (feeds the no-provider path)

- [ ] **Step 1: Write the failing tests**

`danzaboss/tests/test_workstation_research.py`:

```python
"""Reality Check tests: providers stubbed, digest contract fail-closed,
wizard integration stale-on-edit (design spec sections 4 and 8). Zero
network: urlopen is injected, the boss CLI is a stub script."""
import _bootstrap  # noqa: F401
import json
import sys
import tempfile
import unittest
from pathlib import Path

from danzaboss.workstation import research
from danzaboss.workstation.wizard import Wizard

VALID_DIGEST = {
    "verdict": "crowded_but_viable",
    "summary": "Rover and Wag dominate; the trust-first wedge is open.",
    "competitors": [
        {"name": "Rover", "url": "https://rover.com", "note": "marketplace"},
        {"name": "Wag", "url": "https://wag.co", "note": "on-demand"},
    ],
    "differentiation": "Verified-walker trust layer for one metro area.",
}

CONCEPT_ANSWERS = {
    "project_name": "WalkWise",
    "concept_what": "Dog walking marketplace",
    "concept_who": "Urban dog owners",
    "concept_problem": "Finding trusted walkers is slow",
    "features_must": ["book a walk"],
    "non_goals": ["pet supplies"],
}


def make_stub(tmp: Path, body: str) -> list[str]:
    stub = tmp / "stub_boss.py"
    stub.write_text(body, encoding="utf-8")
    return [sys.executable, str(stub)]


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_urlopen(body: dict):
    def urlopen(request, timeout=0):
        return _FakeResponse(body)
    return urlopen


class DigestContractTests(unittest.TestCase):
    def test_valid_digest_passes(self):
        self.assertEqual(research.validate_digest(dict(VALID_DIGEST)),
                         dict(VALID_DIGEST))

    def test_unknown_verdict_rejected(self):
        with self.assertRaises(research.ResearchError):
            research.validate_digest(dict(VALID_DIGEST, verdict="meh"))

    def test_missing_key_rejected(self):
        bad = {k: v for k, v in VALID_DIGEST.items() if k != "competitors"}
        with self.assertRaises(research.ResearchError):
            research.validate_digest(bad)

    def test_competitor_without_name_rejected(self):
        bad = dict(VALID_DIGEST, competitors=[{"url": "https://x.io"}])
        with self.assertRaises(research.ResearchError):
            research.validate_digest(bad)


class QueryTests(unittest.TestCase):
    def test_query_built_from_concept_answers(self):
        query = research.build_query(CONCEPT_ANSWERS)
        self.assertIn("Dog walking marketplace", query)
        self.assertIn("Urban dog owners", query)

    def test_empty_concept_rejected(self):
        with self.assertRaises(research.ResearchError):
            research.build_query({})


class TavilySearchTests(unittest.TestCase):
    def test_results_mapped_to_title_url_content(self):
        body = {"results": [{"title": "Rover", "url": "https://rover.com",
                             "content": "walkers", "score": 0.9}]}
        results = research.tavily_search("dogs", "key",
                                         urlopen=fake_urlopen(body))
        self.assertEqual(results, [{"title": "Rover",
                                    "url": "https://rover.com",
                                    "content": "walkers"}])

    def test_missing_results_field_raises(self):
        with self.assertRaises(research.ResearchError):
            research.tavily_search("dogs", "key",
                                   urlopen=fake_urlopen({"error": "nope"}))

    def test_network_failure_raises_research_error(self):
        def broken(request, timeout=0):
            raise OSError("connection refused")
        with self.assertRaises(research.ResearchError):
            research.tavily_search("dogs", "key", urlopen=broken)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_tavily_provider_searches_then_synthesizes(self):
        body = {"results": [{"title": "Rover", "url": "https://rover.com",
                             "content": "walkers"}]}
        command = make_stub(self.tmp, (
            "import json\n"
            f"print(json.dumps({VALID_DIGEST!r}))\n"))
        provider = research.TavilyProvider("key", command,
                                           urlopen=fake_urlopen(body))
        digest = provider.run(CONCEPT_ANSWERS, timeout=30)
        self.assertEqual(digest["verdict"], "crowded_but_viable")
        self.assertEqual(digest["sources"], ["https://rover.com"])

    def test_boss_web_provider_single_call(self):
        command = make_stub(self.tmp, (
            "import json\n"
            f"print(json.dumps({VALID_DIGEST!r}))\n"))
        digest = research.BossWebProvider(command).run(
            CONCEPT_ANSWERS, timeout=30)
        self.assertEqual(digest["summary"], VALID_DIGEST["summary"])

    def test_provider_garbage_output_raises(self):
        command = make_stub(self.tmp, "print('not json at all')\n")
        with self.assertRaises(research.ResearchError):
            research.BossWebProvider(command).run(CONCEPT_ANSWERS, timeout=30)

    def test_tavily_from_env(self):
        self.assertIsNone(research.tavily_from_env(["claude"], env={}))
        provider = research.tavily_from_env(
            ["claude"], env={"TAVILY_API_KEY": "tk"})
        self.assertIsInstance(provider, research.TavilyProvider)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_research -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'danzaboss.workstation.research'`

- [ ] **Step 3: Write the implementation**

`danzaboss/workstation/research.py`:

```python
"""Reality Check research (design spec section 4, Phase 1.5).

Provider interface with two v1 implementations: Tavily (direct API over
stdlib urllib, urlopen injectable) and headless-boss-with-web fallback.
Research is NEVER automatic — run_reality_check (Task 4) is only invoked
from an explicit user click, which is the user approval external research
requires in every profile. Digest synthesis reuses the checkpoint
runner's subprocess + lenient JSON parse: one CLI seam, not two.
"""
from __future__ import annotations

import json
import os
import urllib.request

from danzaboss.workstation import checkpoints as checkpoints_mod

DIGEST_VERDICTS = ("saturated", "crowded_but_viable", "novel")
DIGEST_KEYS = ("verdict", "summary", "competitors", "differentiation")
TAVILY_URL = "https://api.tavily.com/search"
TAVILY_ENV = "TAVILY_API_KEY"

DIGEST_CONTRACT = (
    "Respond with ONLY a JSON object, no prose around it, shaped exactly:\n"
    '{"verdict": "saturated"|"crowded_but_viable"|"novel", "summary": str, '
    '"competitors": [{"name": str, "url": str, "note": str}], '
    '"differentiation": str}'
)


class ResearchError(ValueError):
    """Bad digest, bad provider response, or misuse. Fail closed."""


def validate_digest(digest: dict) -> dict:
    """The digest contract feeds compile_spec and Checkpoint 1 — a torn
    digest must die here, not render as a half-empty card."""
    if not isinstance(digest, dict):
        raise ResearchError("digest must be an object")
    missing = [k for k in DIGEST_KEYS if k not in digest]
    if missing:
        raise ResearchError(f"digest missing keys {missing}")
    if digest["verdict"] not in DIGEST_VERDICTS:
        raise ResearchError(
            f"digest.verdict must be one of {DIGEST_VERDICTS}")
    if not isinstance(digest["summary"], str) or not digest["summary"].strip():
        raise ResearchError("digest.summary must be non-empty text")
    competitors = digest["competitors"]
    if (not isinstance(competitors, list)
            or not all(isinstance(c, dict)
                       and isinstance(c.get("name"), str) and c["name"]
                       for c in competitors)):
        raise ResearchError(
            "digest.competitors must be objects with at least a name")
    if not isinstance(digest["differentiation"], str):
        raise ResearchError("digest.differentiation must be text")
    return digest


def build_query(answers: dict) -> str:
    """Deterministic search query from the concept phase answers."""
    parts = [answers.get("concept_what", ""), answers.get("concept_who", "")]
    similar = answers.get("concept_similar") or []
    if similar:
        parts.append("similar to " + ", ".join(similar))
    query = " ".join(p.strip() for p in parts if p and p.strip())
    if not query:
        raise ResearchError(
            "cannot research an empty concept (finish phase 1 first)")
    return query[:400]


def tavily_search(query: str, api_key: str, *,
                  urlopen=urllib.request.urlopen,
                  timeout: int = 30) -> list[dict]:
    """One Tavily call over stdlib urllib. urlopen is injectable so the
    suite proves the mapping without a network or a key."""
    payload = json.dumps({"api_key": api_key, "query": query,
                          "search_depth": "basic",
                          "max_results": 8}).encode("utf-8")
    request = urllib.request.Request(
        TAVILY_URL, data=payload,
        headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise ResearchError(f"tavily search failed: {exc}") from exc
    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list):
        raise ResearchError(
            f"tavily response missing results: {str(body)[:200]}")
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "content": r.get("content", "")} for r in results]


def build_digest_prompt(answers: dict, evidence: list[dict] | None) -> str:
    """Synthesis prompt. evidence=None tells a web-capable boss to gather
    its own; inline evidence means no web tools are needed at all."""
    lines = [
        "You are the DANZA Reality Check analyst. Assess this product idea "
        "against the real market: direct competitors and near-substitutes, "
        "pricing, user complaints, recent entrants or shutdowns, and "
        "whether the described angle already exists.",
        "Verdict rules: 'saturated' needs evidence-backed pushback; "
        "'crowded_but_viable' must name the wedge; 'novel' must still list "
        "the closest adjacents so the claim is falsifiable.", "",
        "Concept (JSON):",
        json.dumps(answers, indent=2, sort_keys=True), "",
    ]
    if evidence is None:
        lines.append("Use your web search tools to gather evidence first.")
    else:
        lines += ["Search evidence (JSON):",
                  json.dumps(evidence, indent=2, sort_keys=True)]
    lines += ["", DIGEST_CONTRACT]
    return "\n".join(lines)


def _synthesize(command: list[str], prompt: str, *, timeout: int) -> dict:
    """Headless synthesis call -> validated digest. Checkpoint errors
    become research errors at this boundary so callers handle ONE type."""
    try:
        raw = checkpoints_mod.run_headless(command, prompt, timeout=timeout)
        reply = checkpoints_mod.parse_json_reply(raw)
    except checkpoints_mod.CheckpointError as exc:
        raise ResearchError(f"digest synthesis failed: {exc}") from exc
    if not isinstance(reply, dict):
        raise ResearchError(f"digest is not an object: {str(reply)[:200]}")
    return validate_digest(reply)


class TavilyProvider:
    """Gather evidence via Tavily, then synthesize the digest with one
    headless boss call — the evidence rides inline, so the boss needs
    no web tools of its own."""

    def __init__(self, api_key: str, command: list[str], *,
                 urlopen=urllib.request.urlopen) -> None:
        self._api_key = api_key
        self._command = list(command)
        self._urlopen = urlopen

    def run(self, answers: dict, *, timeout: int = 180) -> dict:
        evidence = tavily_search(build_query(answers), self._api_key,
                                 urlopen=self._urlopen)
        digest = _synthesize(self._command,
                             build_digest_prompt(answers, evidence),
                             timeout=timeout)
        digest["sources"] = [e["url"] for e in evidence if e.get("url")]
        return digest


class BossWebProvider:
    """Fallback: one headless boss-with-web call does search + synthesis."""

    def __init__(self, command: list[str]) -> None:
        self._command = list(command)

    def run(self, answers: dict, *, timeout: int = 300) -> dict:
        return _synthesize(self._command,
                           build_digest_prompt(answers, None),
                           timeout=timeout)


def tavily_from_env(command: list[str],
                    env=os.environ) -> TavilyProvider | None:
    """Provider when a key is configured, None otherwise — None routes
    run_reality_check into the honest no-provider path."""
    api_key = env.get(TAVILY_ENV, "").strip()
    return TavilyProvider(api_key, command) if api_key else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_research -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/research.py danzaboss/tests/test_workstation_research.py
git commit -m "feat(workstation): W1-P2 T3 reality-check providers — digest contract, Tavily over urllib, boss-with-web fallback"
```

---

### Task 4: Digest cache, wizard integration, CORTEX observation distill (`research.py` part 2)

**Model:** sonnet subagent (same dispatch as Task 3, run back-to-back)

**Files:**
- Modify: `danzaboss/workstation/research.py` (append; Task 3 content unchanged)
- Modify: `danzaboss/tests/test_workstation_research.py` (append test classes)

**Interfaces:**
- Consumes: Task 3's `validate_digest`, providers; P1's `Wizard.record_result` / `Wizard.answers` / stale-on-edit.
- Produces (P5 server + compiler wiring rely on):
  - `RESEARCH_RELDIR = Path(".danza") / "onboarding" / "research"`
  - `digest_path(root) -> Path`, `save_digest(root, digest) -> Path`, `load_digest(root) -> dict | None`
  - `digest_to_observation(digest: dict, answers: dict) -> dict`
  - `run_reality_check(root, provider, *, timeout: int = 300) -> dict` — records on `r_reality`; `provider=None` records the honest skipped digest

- [ ] **Step 1: Write the failing tests**

Append to `danzaboss/tests/test_workstation_research.py`:

```python
class _FixtureProvider:
    """Provider double: fixture digest, records the answers it was given."""

    def __init__(self, digest: dict):
        self.digest = digest
        self.seen: dict | None = None

    def run(self, answers: dict, *, timeout: int = 300) -> dict:
        self.seen = answers
        return dict(self.digest)


def make_app_wizard(root: Path) -> Wizard:
    wizard = Wizard(root)
    wizard.submit("p0", {"project_type": "saas"})
    wizard.submit("p1", CONCEPT_ANSWERS)
    return wizard


class CacheTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_load_missing_returns_none(self):
        self.assertIsNone(research.load_digest(self.tmp))

    def test_save_load_roundtrip(self):
        path = research.save_digest(self.tmp, dict(VALID_DIGEST))
        self.assertTrue(str(path).endswith("reality-digest.json"))
        self.assertEqual(research.load_digest(self.tmp)["verdict"],
                         "crowded_but_viable")

    def test_corrupt_digest_fails_closed(self):
        path = research.digest_path(self.tmp)
        path.parent.mkdir(parents=True)
        path.write_text('["not", "an", "object"]', encoding="utf-8")
        with self.assertRaises(research.ResearchError):
            research.load_digest(self.tmp)


class ObservationTests(unittest.TestCase):
    def test_observation_shape_is_deterministic(self):
        obs = research.digest_to_observation(VALID_DIGEST, CONCEPT_ANSWERS)
        self.assertEqual(obs["type"], "research")
        self.assertIn("WalkWise", obs["title"])
        self.assertIn("crowded_but_viable", obs["title"])
        self.assertEqual(obs["concepts"], ["Rover", "Wag"])
        self.assertEqual(
            obs, research.digest_to_observation(VALID_DIGEST,
                                                CONCEPT_ANSWERS))


class RunRealityCheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        make_app_wizard(self.tmp)

    def test_run_records_caches_and_distills(self):
        provider = _FixtureProvider(VALID_DIGEST)
        digest = research.run_reality_check(self.tmp, provider)
        self.assertEqual(provider.seen["project_name"], "WalkWise")
        wizard = Wizard(self.tmp)
        self.assertEqual(wizard.status("r_reality"), "complete")
        self.assertEqual(wizard.result("r_reality")["verdict"],
                         "crowded_but_viable")
        self.assertEqual(research.load_digest(self.tmp)["summary"],
                         digest["summary"])
        obs_path = self.tmp / ".danza" / "onboarding" / "research" \
            / "observation.json"
        self.assertIn("WalkWise",
                      json.loads(obs_path.read_text())["title"])

    def test_no_provider_records_honest_skip(self):
        digest = research.run_reality_check(self.tmp, None)
        self.assertTrue(digest["skipped"])
        wizard = Wizard(self.tmp)
        self.assertEqual(wizard.status("r_reality"), "complete")
        self.assertTrue(wizard.result("r_reality")["skipped"])
        self.assertIsNone(research.load_digest(self.tmp))

    def test_invalid_provider_digest_fails_closed(self):
        provider = _FixtureProvider({"verdict": "meh"})
        with self.assertRaises(research.ResearchError):
            research.run_reality_check(self.tmp, provider)
        self.assertEqual(Wizard(self.tmp).status("r_reality"), "pending")

    def test_concept_edit_stales_digest_but_keeps_cache(self):
        research.run_reality_check(self.tmp, _FixtureProvider(VALID_DIGEST))
        wizard = Wizard(self.tmp)
        wizard.submit("p1", dict(CONCEPT_ANSWERS,
                                 concept_what="Cat sitting marketplace"))
        wizard = Wizard(self.tmp)
        self.assertEqual(wizard.status("r_reality"), "stale")
        self.assertIsNotNone(research.load_digest(self.tmp))
```

- [ ] **Step 2: Run tests to verify the new classes fail**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_research -v`
Expected: Task 3 classes PASS; new classes FAIL with `AttributeError: ... no attribute 'load_digest'` (etc.)

- [ ] **Step 3: Write the implementation**

Append to `danzaboss/workstation/research.py` (extend the imports at the top of the file to):

```python
import json
import os
import urllib.request
from pathlib import Path

from danzaboss.workstation import checkpoints as checkpoints_mod
from danzaboss.workstation.wizard import Wizard
```

then append at the end of the file:

```python
RESEARCH_RELDIR = Path(".danza") / "onboarding" / "research"
DIGEST_FILENAME = "reality-digest.json"
OBSERVATION_FILENAME = "observation.json"


def digest_path(root) -> Path:
    return Path(root) / RESEARCH_RELDIR / DIGEST_FILENAME


def save_digest(root, digest: dict) -> Path:
    """Whole-file overwrite is correct here: the digest is a generated,
    re-runnable artifact (like spec.md), not merged user state — the
    Rule 35 merge discipline protects answers.json, not caches."""
    path = digest_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(digest, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_digest(root) -> dict | None:
    """Cached digest, or None. Persisting across a stale r_reality step
    is deliberate: the wizard's status says 're-approve me', the cache
    says 'here is what the last run cost' — never a silent re-spend."""
    path = digest_path(root)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ResearchError(f"corrupt digest (not an object): {path}")
    return data


def digest_to_observation(digest: dict, answers: dict) -> dict:
    """Deterministic CORTEX-shaped record so build-time Carmella inherits
    the research instead of re-spending it (spec section 4)."""
    name = answers.get("project_name") or answers.get("seed_name", "project")
    return {
        "type": "research",
        "title": f"Reality check: {name} — {digest['verdict']}",
        "summary": digest["summary"],
        "tags": ["reality-check", "onboarding", digest["verdict"]],
        "concepts": [c["name"] for c in digest["competitors"]],
    }


def run_reality_check(root, provider, *, timeout: int = 300) -> dict:
    """One explicit research pass against the target repo's answers. The
    caller's click IS the user approval external research requires in
    every profile — nothing in the OS calls this automatically.
    provider=None records the skipped path honestly so the wizard can
    proceed and spec.md says 'not run' instead of pretending."""
    wizard = Wizard(root)
    if provider is None:
        digest = {"skipped": True, "reason": "no_provider",
                  "summary": ("reality check unavailable: no research "
                              "provider configured")}
        wizard.record_result("r_reality", digest)
        return digest
    digest = validate_digest(provider.run(wizard.answers, timeout=timeout))
    save_digest(root, digest)
    observation = digest_to_observation(digest, wizard.answers)
    obs_path = digest_path(root).with_name(OBSERVATION_FILENAME)
    obs_tmp = obs_path.with_name(obs_path.name + ".tmp")
    obs_tmp.write_text(json.dumps(observation, indent=2, sort_keys=True),
                       encoding="utf-8")
    os.replace(obs_tmp, obs_path)
    wizard.record_result("r_reality", digest)
    return digest
```

- [ ] **Step 4: Run the module tests, then the full suite**

Run: `PYTHONPATH=".:danzaboss/tests" python3 -m unittest danzaboss.tests.test_workstation_research -v`
Expected: all PASS
Run: `./danzaboss/run_tests.sh`
Expected: all OK (T1–T4 additions on top of the 459 baseline)

- [ ] **Step 5: Commit**

```bash
git add danzaboss/workstation/research.py danzaboss/tests/test_workstation_research.py
git commit -m "feat(workstation): W1-P2 T4 digest cache, run_reality_check wizard seam, CORTEX observation distill"
```

---

### Task 5: Integration check + THE final whole-branch review

**Model:** fable (inline; review via one code-reviewer subagent over the full P2 diff)

**Files:**
- Modify: only what review findings require (+ one regression test per Important finding)
- Modify: `.superpowers/sdd/progress.md` (append P2 section — append-only discipline)

**Interfaces:**
- Consumes: everything T1–T4 produced.
- Produces: P2-complete state — the seam P3 (decomposition bridge) and P5 (server) build on.

- [ ] **Step 1: Hermeticity + integration sweep**

Run and verify each:

```bash
# full suite green
./danzaboss/run_tests.sh
# workstation stays stdlib-only (no third-party imports)
grep -rn "^import \|^from " danzaboss/workstation/checkpoints.py danzaboss/workstation/research.py | grep -v "danzaboss\.\|from __future__\|import json\|import os\|import subprocess\|import urllib" && echo "NON-STDLIB IMPORT FOUND" || echo "stdlib-only OK"
# this repo's real .danza/ untouched by the suite
git status --porcelain .danza/ | head; echo "---"; git diff --stat .danza/
```

Expected: suite all OK · "stdlib-only OK" · no `.danza/` modifications.

- [ ] **Step 2: Dispatch ONE whole-branch review**

Dispatch a single `code-reviewer`-style subagent over the full P2 diff (`git diff <P1-final-commit>..HEAD`), with the deferred-minors list from `.superpowers/sdd/progress.md` as triage input. Review focus (the P1 lesson — seam bugs live *between* tasks): the checkpoints↔wizard seam (`record_result` ordering, degraded verdicts surviving staling), the research↔checkpoints reuse boundary (`parse_json_reply` error types crossing modules), cache-vs-state semantics (digest file survives stale; `answers.json` never overwritten), and prompt-injection surface (memory files and Tavily content are untrusted text flowing into boss prompts — confirm they're inert data in the prompt, with the contract line last).

- [ ] **Step 3: Fix Important findings inline, one regression test each**

Every Important finding gets its fix plus a regression test in the matching `test_workstation_*.py`. Minor findings append to the deferred backlog in `.superpowers/sdd/progress.md` — do not fix them now.

- [ ] **Step 4: Re-run the full suite**

Run: `./danzaboss/run_tests.sh`
Expected: all OK, count recorded in progress.md.

- [ ] **Step 5: Close out P2 + commit**

Append to `.superpowers/sdd/progress.md`: a `## W1-P2 checkpoints + research` section with per-task commit ranges, the review outcome, deferred minors, and `W1-P2 COMPLETE at this commit.`

```bash
git add -A
git commit -m "fix(workstation): W1-P2 final-review fixes + progress log"
```

(If the review found nothing Important, the commit is just the progress.md close-out: `docs(workstation): W1-P2 progress close-out`.)

---

## Deferred / explicitly out of P2 scope

- **P5 wires approval:** `record_result(step_id, result, approved=True)` on the user's click; the informed-override recording (`proceeding past saturated`) uses `compile_spec(overrides=...)` — both server concerns.
- **Re-run offer on stale digest** is UI behavior (P5); the engine already exposes everything needed (`status("r_reality") == "stale"` + `load_digest`).
- **Tavily key entry via /models screen** (P5); P2 ships `tavily_from_env` only.
- **CORTEX store write** of the distilled observation happens at activation (Layer 2), not in the factory; P2 persists `observation.json` for pickup.
- P1 deferred backlog items not touched by P2 code remain in the backlog (state.py annotations, `_set_status` docstring, UI-test ResourceWarning, SPEC_RELPATH constant → P3).
