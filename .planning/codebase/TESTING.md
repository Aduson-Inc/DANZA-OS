# Testing Patterns

**Analysis Date:** 2026-07-08

## Test Framework

**Runner:**
- Python stdlib `unittest`, discovered via `unittest discover` — no pytest, no third-party
  test framework. Confirmed: no `pytest.ini`, `conftest.py`, or `pytest` import anywhere
  under `danzaboss/`.
- Entry point: `danzaboss/run_tests.sh`:
  ```bash
  #!/usr/bin/env bash
  set -euo pipefail
  cd "$(dirname "$0")"                 # danza/
  ROOT="$(cd .. && pwd)"              # repo root (so `import danzaboss works)
  export PYTHONPATH="$ROOT:$(pwd)/tests"
  export DANZA_CORTEX_GLOBAL_DB="${DANZA_CORTEX_GLOBAL_DB:-$(mktemp -d)/global.db}"
  python3 -m unittest discover -s tests -p 'test_*.py' -v
  ```
- Scale: 65 `test_*.py` files, 105 `TestCase` classes, 681 individual `test_*` methods,
  ~7,475 lines of test code as of this analysis (CLAUDE.md's "694 tests" figure is a
  rounded/slightly stale headline count — treat the actual `run_tests.sh -v` output as
  ground truth, not the doc).

**Assertion Library:** stdlib `unittest.TestCase` assertions only
(`assertEqual`, `assertTrue`, `assertFalse`, `assertIsNone`, `assertIn`,
`assertRaises`, `assertGreaterEqual`, `assertIsInstance`).

**Run Commands:**
```bash
./danzaboss/run_tests.sh                                   # full suite, verbose
PYTHONPATH=. python3 -m unittest danzaboss.tests.test_state # single module (from repo root, adjust path)
cd danzaboss && PYTHONPATH="$(cd .. && pwd):$(pwd)/tests" python3 -m unittest discover -s tests -p 'test_profile.py' -v
```
There is no separate watch mode or coverage command configured (no `.coveragerc`,
no `coverage` invocation in `run_tests.sh` or `CLAUDE.md`).

## Test File Organization

**Location:** All tests live in the single flat directory `danzaboss/tests/`, not
co-located with source modules. This is a deliberate structural choice — `danzaboss/tests/`
is the promoted, canonical test suite (694-ish tests referenced by `CLAUDE.md`), separate
from source subpackages (`kernel/`, `cortex/`, `hooks/`, `security/`, `workstation/`, etc.)
which contain zero test files of their own.

**Naming:**
- `test_<module_or_feature>.py`, snake_case, mirroring the source module name where there's
  a 1:1 mapping (`kernel/state.py` → `tests/test_state.py`,
  `kernel/profile.py` → `tests/test_profile.py`,
  `kernel/scheduler.py` → `tests/test_scheduler.py`).
- CORTEX is the exception: it has ~25 test files under a `test_cortex_<feature>.py` prefix
  (`test_cortex_store.py`, `test_cortex_fts.py`, `test_cortex_mcp.py`,
  `test_cortex_backend_parity.py`, `test_cortex_federation.py`, `test_cortex_gate.py`, ...)
  because the `cortex/` package itself has many internal modules (store, ports, sqlite
  backend, neon backend, mcp_server, federate, extract, inject, compress, git_intel,
  repo_intel, graph, quality, identity...) that don't each need their own 1:1 test file —
  tests are grouped by user-facing feature/capability instead.
- `workstation/` similarly has ~15 `test_workstation_<feature>.py` files
  (`test_workstation_hosts.py`, `test_workstation_conductor.py`,
  `test_workstation_planner.py`, `test_workstation_wizard.py`, ...).

**Structure:**
```
danzaboss/tests/
├── _bootstrap.py                    # sys.path + hermeticity setup, imported first in every file
├── test_app_profile.py
├── test_capabilities.py
├── test_context.py
├── test_cortex_*.py                 # ~25 files, CORTEX subsystem
├── test_decompose.py
├── test_harness.py                  # selftest cold-start harness tests
├── test_hooks.py                    # guards + gates + dispatcher
├── test_memory.py
├── test_parallel.py
├── test_plan_record.py
├── test_profile.py                  # execution-profile governor (C4.5)
├── test_research.py
├── test_runtime.py
├── test_scheduler.py
├── test_state.py                    # team-state manager (Upgrade #2)
├── test_tiers.py
├── test_trace.py
├── test_workstation_*.py            # ~15 files, workstation subsystem
└── .danza/                          # fixture data used by some tests
```

## Bootstrap / Hermeticity Pattern

Every single test file starts with the same two lines:
```python
import _bootstrap  # noqa: F401     (or `# noqa` / `# noqa: F401`)
from danzaboss.kernel.state import StateManager, StateError, TeamState
```

`danzaboss/tests/_bootstrap.py` does two jobs and **must be imported first** in any new
test file:
1. Puts the repo root and the `tests/` dir on `sys.path` so `import danzaboss.<module>`
   and `import _bootstrap` resolve regardless of how/where the test is launched (IDE,
   `python3 -m unittest tests.test_x`, or `run_tests.sh`).
2. Sets `DANZA_CORTEX_GLOBAL_DB` (and blanks `DANZA_CORTEX_GLOBAL_DSN`) to a fresh
   `tempfile.mkdtemp()` path via `os.environ.setdefault(...)` — this is a C6 hermeticity
   guarantee: **tests must never touch the developer's real `~/.danza` global CORTEX
   store**, even when a test file is run directly instead of through `run_tests.sh`.

When adding a new test file, always start with `import _bootstrap  # noqa` before any
`danzaboss.*` import.

## Test Structure

**Suite organization** — one `TestCase` subclass per logical grouping of behavior, not
one per public method. Example from `danzaboss/tests/test_profile.py`:
```python
class TestProfileResolution(unittest.TestCase):
    def test_env_var_wins(self): ...
    def test_env_var_is_case_insensitive(self): ...
    def test_unknown_name_fails_closed(self): ...

class TestPolicyInvariants(unittest.TestCase):
    def test_destructive_deny_active_in_every_profile(self):
        for p in PROFILES.values():
            self.assertTrue(p.destructive_deny_active, p.name)

class TestMemoryDiet(unittest.TestCase): ...
class TestDistillationNoiseFloor(unittest.TestCase): ...
class TestProfileAwareCortexHooks(unittest.TestCase):
    """The live hook handlers must honor the profile of the repo they run in."""
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._saved = os.environ.pop(PROFILE_ENV_VAR, None)
    def tearDown(self):
        if self._saved is not None:
            os.environ[PROFILE_ENV_VAR] = self._saved
```
Groupings map to a concept (`TestProfileResolution`, `TestPolicyInvariants`,
`TestMemoryDiet`) rather than to a single function — this makes intent readable straight
from `-v` test output.

**Regression tests get their own class named after the incident**, appended at the bottom
of the relevant file with a docstring explaining what broke:
```python
class TestTurnLockFailClosed(unittest.TestCase):
    """Regression for W1: fail-open turn lock allowed arbitrary boss reassignment."""
    def setUp(self):
        import tempfile as _t, os as _o
        self.mgr = StateManager(_o.path.join(_t.mkdtemp(), "s.json"))
        self.mgr.init(mode="relay", current_boss="claude")
        self.mgr.transition(to_status="in_progress")

    def test_cannot_reassign_boss_without_actor(self):
        with self.assertRaises(StateError):
            self.mgr.transition(current_boss="attacker")
```
(`danzaboss/tests/test_state.py:78-109`.) When fixing a bug found in review/production,
add a dedicated `Test<Incident>` class rather than folding assertions into an existing
class — this preserves the "why does this test exist" narrative for future readers.

**Setup pattern:** `setUp()` builds fresh isolated state per test — almost always a
`tempfile.mkdtemp()`-backed manager/registry, never a shared module-level fixture:
```python
def setUp(self):
    self.dir = tempfile.mkdtemp()
    self.path = os.path.join(self.dir, "team-state.json")
    self.mgr = StateManager(self.path)
```
(`danzaboss/tests/test_state.py:10-13`.) In-memory SQLite is used the same way for
CORTEX store tests: `ObservationStore(SqliteBackend(":memory:"))`
(`danzaboss/tests/test_cortex_store.py:14-15`).

**Teardown** is used only when a test mutates process-global state (env vars) that must
be restored, e.g. `TestProfileAwareCortexHooks.tearDown` above, and
`TestProfileAwareCortexHooks.test_app_build_capture_keeps_everything` wraps its own
`os.environ[...] = "APP_BUILD"` / `del os.environ[...]` in a `try/finally` inline when the
mutation is local to one test (`danzaboss/tests/test_profile.py:151-159`).

## Mocking

**Framework:** stdlib `unittest.mock` (`MagicMock`, `call`, `patch` where needed) — used
sparingly, only where a real subprocess/external boundary must not run during tests.
Confirmed mock usage in 5 of 65 test files: `test_workstation_hosts.py`, `test_hooks.py`,
`test_cortex_federation.py`, `test_decompose.py`, `test_plan_record.py`. The overwhelming
majority of tests (60/65 files) use **no mocking at all** — they exercise real objects
(`StateManager`, `CapabilityRegistry`, `ObservationStore`) against real temp files / real
in-memory SQLite, because those objects have no external dependencies to isolate.

**Subprocess seam pattern** (`danzaboss/tests/test_workstation_hosts.py:1-53`) — this is
the canonical example of mocking in this codebase, for a module (`workstation/hosts.py`)
that shells out to `tmux`:
```python
"""SessionHost tests: TmuxHost, HeadlessHost, pick_host — all hermetic.

Every test substitutes the subprocess seam so no real tmux or real claude
is invoked. One env-gated live smoke test exercises the full ignite→tail→kill
cycle against a real tmux process; it is skipped by default.
"""
from unittest.mock import MagicMock, call

def _ok_proc(stdout: str = "", stderr: str = "") -> MagicMock:
    """Fake subprocess.run result with returncode=0."""
    p = MagicMock()
    p.returncode = 0
    p.stdout = stdout
    p.stderr = stderr
    return p

def _err_proc(rc: int = 1, stderr: str = "tmux error") -> MagicMock:
    """Fake subprocess.run result with nonzero returncode."""
    ...

def _fake_popen(poll_result: int | None = None) -> MagicMock:
    """Fake subprocess.Popen handle."""
    h = MagicMock()
    h.poll.return_value = poll_result
    return h
```
Pattern: define small module-level factory helpers (`_ok_proc`, `_err_proc`,
`_fake_popen`) that build a `MagicMock` shaped like the real return value
(`subprocess.CompletedProcess` / `subprocess.Popen` handle), then inject them via
`unittest.mock.patch` on the specific `subprocess.run`/`subprocess.Popen` call site.
Real external processes are never invoked in the default test run.

**Live/env-gated tests:** one real-process smoke test exists and is skipped unless an
explicit env var opts in:
```python
@unittest.skipUnless(os.environ.get("DANZA_LIVE_TMUX") == "1", "...")
```
(`danzaboss/tests/test_workstation_hosts.py:435`). The same `skipUnless` pattern gates
tests on optional external tooling:
```python
@unittest.skipUnless(shutil.which("git"), "git not installed")           # test_cortex_git_intel.py:91
@unittest.skipUnless(NeonBackend and _PG_DSN and driver_available(), ...) # test_cortex_backend_parity.py:173
```
Use `@unittest.skipUnless(...)` with a clear reason string for any test that depends on
an optional binary, live network resource, or optional backend driver — never silently
`pass` or comment out such a test.

**What to mock:** only true external-process/IO boundaries (subprocess calls to `tmux`,
optional Postgres driver). Never mock the modules under test themselves.

**What NOT to mock:** internal DANZA objects (`StateManager`, `CapabilityRegistry`,
`ObservationStore`, `Scheduler`) — these are constructed for real against temp
files/in-memory SQLite because they're cheap, deterministic, and stdlib-only. Mocking
them would hide the exact invariant-violation bugs this codebase's tests are built to
catch (fail-closed behavior, schema validation, transition legality).

## Fixtures and Factories

**Factory functions** (not fixture files) build test data inline, module-level, just
above the `TestCase` classes that use them:
```python
def obs(title, summary, typ=ObsType.DECISION.value, project="p", **kw):
    return Observation(title=title, summary=summary, type=typ, project=project, **kw)
```
(`danzaboss/tests/test_cortex_store.py:9-10`.) Similarly, `danzaboss/tests/test_hooks.py:13-14`
defines `def reg(): return CapabilityRegistry(os.path.join(tempfile.mkdtemp(), "audit.jsonl"))`
as a shared constructor for a fresh registry.

**No pytest fixtures, no factory_boy/faker.** All test data is constructed by hand with
plain dataclass/constructor calls and small local helper functions — consistent with the
stdlib-only policy.

**Fixture data directory:** `danzaboss/tests/.danza/` holds on-disk fixture state
consumed by some tests (state-file shaped test inputs), separate from the real project's
`.danza/` runtime directory.

## Coverage

**Requirements:** None enforced by tooling — no `.coveragerc`, no CI coverage gate
detected. Coverage is enforced by process instead: CLAUDE.md states "every module ships
with a `tests/test_*.py`. A change is not 'done' until `danzaboss/run_tests.sh` is green,"
and Constitution Rule 5 requires Bonnie (QA) to verify every feature — "It should work" is
explicitly rejected as insufficient.

**View coverage:** not configured. If needed, run manually:
```bash
python3 -m coverage run -m unittest discover -s danzaboss/tests -p 'test_*.py'
python3 -m coverage report
```
(requires installing `coverage`, which would deviate from the stdlib-only-for-tests
posture unless treated as a dev-only tool.)

## Test Types

**Unit tests:** the overwhelming majority. Each test exercises one function/method/class
in isolation using temp files or in-memory SQLite — no network, no real subprocess (except
the one gated live-tmux smoke test), no real filesystem outside `tempfile.mkdtemp()`.

**Integration tests:** exist within the same `unittest` suite, distinguished by scope, not
by a separate runner/marker. Examples: `TestProfileAwareCortexHooks`
(`danzaboss/tests/test_profile.py:123-209`) drives the actual `_hook_post_tool_use`,
`_hook_stop`, `_hook_session_start` entry points end-to-end against a real `CaptureLog`/
SQLite-backed store to prove profile-gated hook behavior, not just the pure `profile.py`
logic in isolation. `danzaboss/tests/test_cortex_c3_integration.py` and
`test_cortex_cold_start.py` similarly integrate multiple CORTEX submodules.

**Cold-start self-test (`danzaboss/selftest/harness.py`):** a distinct, non-`unittest`
health-check harness — a structured `run_cold_start() -> Report` that never raises,
runs a simulated New-Project → build → handoff → Continue cycle across `StateManager`,
`Scheduler`, `decompose.assert_dispatchable`, and `CapabilityRegistry`, and returns a
JSON-serializable pass/fail report:
```python
@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""

@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)
```
Run via `python3 -m danzaboss.cli selftest` (wired in `danzaboss/cli.py:58-61`,
`_cmd_selftest`). It is exercised by `danzaboss/tests/test_harness.py` inside the regular
`unittest` suite too, but its own internal structure is deliberately unittest-independent
so it can double as a CI/production health gate that returns a JSON report rather than
raising `AssertionError`s. Use this "Report of Checks, never raises" pattern for any new
self-diagnostic/health-check code — not `unittest`-only.

**E2E tests:** not used. No browser/UI automation framework; DANZA-OS is a CLI +
file-state system, not a UI application at the `danzaboss/` layer (the CORTEX UI under
`danzaboss/cortex/ui/` is a local web viewer but has no browser-driven E2E suite —
`test_cortex_ui.py` tests it at the HTTP/handler level, not via a browser).

## Common Patterns

**Table-driven invariant checks** — iterate over a dict/collection of related objects and
assert the same invariant on each, rather than writing N near-duplicate tests:
```python
def test_destructive_deny_active_in_every_profile(self):
    for p in PROFILES.values():
        self.assertTrue(p.destructive_deny_active, p.name)
```
(`danzaboss/tests/test_profile.py:57-59` — note the second `assertTrue` argument is the
profile name, used as the failure-message context so a failing iteration is identifiable.)

**Exception testing:**
```python
def test_unknown_name_fails_closed(self):
    with self.assertRaises(ValueError):
        active_profile(".", env={PROFILE_ENV_VAR: "YOLO"})
```
Always use `with self.assertRaises(SpecificExceptionType):`, never a bare `Exception`,
matching the fail-closed convention documented in `CONVENTIONS.md`.

**State-machine legality testing** — both the "allowed" and "illegal" transition paths get
explicit tests referencing the same transition table the implementation uses:
```python
def test_illegal_status_transition_rejected(self):
    self.mgr.init(current_boss="claude")  # status = ready
    with self.assertRaises(StateError):
        self.mgr.transition(to_status="done")  # ready -> done not allowed

def test_legal_status_transition(self):
    self.mgr.init(current_boss="claude")
    s = self.mgr.transition(to_status="in_progress")
    self.assertEqual(s.status, "in_progress")
```

**Security/authorization testing follows an allow/deny pair per rule** — for every guard,
there's a test proving the disallowed actor is blocked and the allowed actor passes:
```python
def test_orchestrator_cannot_write_code(self):
    ev = ToolEvent(actor="tony-d-orchestrator", tool="Write", path="src/app.py")
    self.assertFalse(capability_guard(ev, self.reg).allow)

def test_builder_can_write_code(self):
    ev = ToolEvent(actor="jonathan-builder", tool="Write", path="src/app.py")
    self.assertTrue(capability_guard(ev, self.reg).allow)
```
(`danzaboss/tests/test_hooks.py:22-28`.) Apply this pattern (positive + negative case) to
any new guard/gate/capability check.

**Comment-as-spec inside assertions** — inline comments explain *why* a specific value is
expected, especially for merge/scoring logic where the number itself isn't self-evident:
```python
self.assertIn("race", merged.concepts)              # unioned
self.assertEqual(merged.summary, "fuller reasoning")  # higher-confidence body kept
self.assertGreaterEqual(merged.confidence, 90)        # confidence climbed
```
(`danzaboss/tests/test_cortex_store.py:26-28`.)

---

*Testing analysis: 2026-07-08*
