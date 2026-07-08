# CORTEX App-Layer Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove, in an isolated sandbox, that DANZA agents onboard a fresh app correctly, use CORTEX per their instructions, and keep app memory scoped — via one live agent run plus a deterministic harness — without changing the OS layer.

**Architecture:** All test code lives OUTSIDE the DANZA-OS repo, in a throwaway sandbox git repo at `/home/tre/dev/danza-cortex-app-test/`. `danzaboss` is imported read-only via `PYTHONPATH`. Both CORTEX tiers are redirected into the sandbox (project DB is CWD-scoped; global DB via `DANZA_CORTEX_GLOBAL_DB`). A snapshot guard proves the OS's real memory is byte-identical before/after. Phase 2 is a deterministic Python driver that replays the prescribed `search → get → observe` protocol and asserts three checks; Phase 1 is a live `tony-d-orchestrator` run following the same shape, captured for comparison.

**Tech Stack:** Python 3.10+, standard library only (`unittest`, `subprocess`, `sqlite3`, `hashlib`, `json`, `pathlib`). Consumes `danzaboss.cortex` + `danzaboss.cli` from the OS repo by import/subprocess — never modified.

## Global Constraints

- **Stdlib only.** No pip installs. Import `danzaboss` via `PYTHONPATH`; add no dependencies. (CLAUDE.md coding standards.)
- **Never modify the OS repo working tree** except the already-committed `docs/superpowers/specs/` and `docs/superpowers/plans/` files. No writes under `/home/tre/dev/DANZA-OS/danzaboss/`, `.claude/`, or the OS's `.danza/`.
- **Never touch real memory.** The real global store `~/.danza/cortex/global.db` and the OS's `/home/tre/dev/DANZA-OS/.danza/cortex/` must be byte-identical after the run. Every `danza cortex` invocation MUST run with all three env vars set (below); the snapshot guard enforces this.
- **Env for every CORTEX call (subprocess or in-process):**
  - `PYTHONPATH=/home/tre/dev/DANZA-OS`
  - `DANZABOSS_PROFILE=APP_BUILD`
  - `DANZA_CORTEX_GLOBAL_DB=/home/tre/dev/danza-cortex-app-test/global.db`
- **Sandbox root:** `/home/tre/dev/danza-cortex-app-test` (its own git repo; overridable in tests via the `Paths` dataclass so unit tests use `tmp`).
- **Project identity of the mock app:** `mockapp` (dir basename + pinned marker).
- **CORTEX facts this plan relies on (verified in source):**
  - `Observation(title, summary, type, project, ...)` — `layer` defaults to `2`; `layer>=4` routes to the global store on `upsert` (`federate.py:117-119`, `GLOBAL_LAYER=4`).
  - Federated reads surface a global obs only if `layer>=4` and not shadowed by a same-type project obs with title/link Jaccard ≥ 0.5 (`federate.py:27-56, 79-91`).
  - `distillation_gate(pending, observations_written, already_blocked, min_events=1)` denies only when `pending>=max(1,min_events) and observations_written==0 and not already_blocked` (`gates.py:55-72`). Under `APP_BUILD`, `distill_min_events=1`, `session_inject=True`, `distill_gate_active=True`.
  - `active_profile(root)` reads `DANZABOSS_PROFILE` first (`profile.py:20-25`), so the env var deterministically forces `APP_BUILD`.
  - CLI entry: `python3 -m danzaboss.cli cortex <sub> ...`; `root` defaults to `os.getcwd()` (`commands.py:385-393`), so subprocess `cwd` must be the mock-app dir. `observe` reads a JSON object/array from stdin.

---

## File Structure

Everything below is created under the sandbox root `S = /home/tre/dev/danza-cortex-app-test/`:

- `S/harness/__init__.py` — package marker (empty).
- `S/harness/paths.py` — `Paths` dataclass; env builders (`build_env`, `apply_env`). One responsibility: where things live + how to invoke the OS toolkit safely.
- `S/harness/snapshot_guard.py` — hash real-memory paths; assert unchanged. One responsibility: OS-untouched proof.
- `S/harness/init_app.py` — create the fresh mock-app fixtures (NEW-mode `handoff.md`, canned onboarding answers, pinned `project.json`).
- `S/harness/seed_global.py` — insert one L4 build-order template into the sandbox global store; return its id.
- `S/harness/cortex_cli.py` — subprocess wrapper for `danza cortex ...` (env + cwd + stdin); returns a small `CortexResult`.
- `S/harness/dump_cortex.py` — read project + global observations and usage logs into a plain dict for reporting/asserts.
- `S/harness/checks.py` — `check_onboarding`, `check_cortex_usage`, `check_scoping`; each returns a `CheckResult`.
- `S/harness/harness.py` — Phase 2 deterministic driver `run(paths) -> dict`; also CLI `python -m harness.harness`.
- `S/harness/report.py` — render `RESULTS.md` from a results dict.
- `S/tests/test_harness.py` — stdlib `unittest` covering paths, guard, init, seed, checks, and a full harness run in a tmp sandbox.
- `S/run_live.md` — Phase 1 runbook: exact env, the `tony-d-orchestrator` spawn prompt, and what to capture.
- `S/.gitignore` — ignores `mockapp/`, `*.db`, `artifacts/`.

---

### Task 1: Sandbox scaffold + paths/env module

**Files:**
- Create: `S/.gitignore`, `S/harness/__init__.py`, `S/harness/paths.py`
- Test: `S/tests/test_harness.py`

**Interfaces:**
- Produces: `Paths(sandbox: str)` with properties `.app_dir -> str` (`<sandbox>/mockapp`), `.global_db -> str` (`<sandbox>/global.db`), `.artifacts -> str` (`<sandbox>/artifacts`), constant `OS_REPO = "/home/tre/dev/DANZA-OS"`. Functions `build_env(paths) -> dict[str,str]` (copy of `os.environ` + the three vars), `apply_env(paths) -> None` (sets those three into `os.environ`).

- [ ] **Step 1: Create the sandbox git repo and directories**

```bash
mkdir -p /home/tre/dev/danza-cortex-app-test/harness /home/tre/dev/danza-cortex-app-test/tests
cd /home/tre/dev/danza-cortex-app-test
git init -q
printf 'mockapp/\n*.db\nartifacts/\n__pycache__/\n' > .gitignore
touch harness/__init__.py
```

- [ ] **Step 2: Write the failing test for paths/env**

Add to `S/tests/test_harness.py`:

```python
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make `harness` importable

from harness.paths import Paths, build_env, apply_env


class TestPaths(unittest.TestCase):
    def test_derived_paths(self):
        p = Paths(sandbox="/tmp/sb")
        self.assertEqual(p.app_dir, "/tmp/sb/mockapp")
        self.assertEqual(p.global_db, "/tmp/sb/global.db")
        self.assertEqual(p.artifacts, "/tmp/sb/artifacts")
        self.assertEqual(p.OS_REPO, "/home/tre/dev/DANZA-OS")

    def test_build_env_sets_three_vars(self):
        p = Paths(sandbox="/tmp/sb")
        env = build_env(p)
        self.assertEqual(env["PYTHONPATH"], "/home/tre/dev/DANZA-OS")
        self.assertEqual(env["DANZABOSS_PROFILE"], "APP_BUILD")
        self.assertEqual(env["DANZA_CORTEX_GLOBAL_DB"], "/tmp/sb/global.db")

    def test_apply_env_mutates_environ(self):
        p = Paths(sandbox="/tmp/sb")
        apply_env(p)
        self.assertEqual(os.environ["DANZABOSS_PROFILE"], "APP_BUILD")
        self.assertEqual(os.environ["DANZA_CORTEX_GLOBAL_DB"], "/tmp/sb/global.db")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /home/tre/dev/danza-cortex-app-test && python3 -m unittest tests.test_harness -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.paths'`.

- [ ] **Step 4: Write minimal implementation**

Create `S/harness/paths.py`:

```python
"""Where the CORTEX app-layer test lives, and how to invoke the OS toolkit
without ever touching real memory. Every derived path hangs off one sandbox
root so unit tests can point it at a tmp dir."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Paths:
    sandbox: str
    OS_REPO: str = "/home/tre/dev/DANZA-OS"

    @property
    def app_dir(self) -> str:
        return os.path.join(self.sandbox, "mockapp")

    @property
    def global_db(self) -> str:
        return os.path.join(self.sandbox, "global.db")

    @property
    def artifacts(self) -> str:
        return os.path.join(self.sandbox, "artifacts")


def build_env(paths: Paths) -> dict:
    """A subprocess env that scopes CORTEX entirely inside the sandbox."""
    env = dict(os.environ)
    env["PYTHONPATH"] = paths.OS_REPO
    env["DANZABOSS_PROFILE"] = "APP_BUILD"
    env["DANZA_CORTEX_GLOBAL_DB"] = paths.global_db
    return env


def apply_env(paths: Paths) -> None:
    """Same redirection for in-process use of danzaboss APIs."""
    os.environ["PYTHONPATH"] = paths.OS_REPO
    os.environ["DANZABOSS_PROFILE"] = "APP_BUILD"
    os.environ["DANZA_CORTEX_GLOBAL_DB"] = paths.global_db
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/tre/dev/danza-cortex-app-test && python3 -m unittest tests.test_harness -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
cd /home/tre/dev/danza-cortex-app-test
git add -A && git commit -q -m "test: sandbox scaffold + paths/env module"
```

---

### Task 2: Snapshot guard (OS-untouched proof)

**Files:**
- Create: `S/harness/snapshot_guard.py`
- Test: `S/tests/test_harness.py`

**Interfaces:**
- Consumes: nothing from prior tasks.
- Produces: `snapshot(paths_list: list[str]) -> dict[str,str]` mapping each path → `sha256` of its bytes (or the literal `"ABSENT"` if it does not exist; directories are walked and each contained file hashed under `dir/relpath` keys). `real_memory_targets() -> list[str]` returns `["/home/tre/dev/DANZA-OS/.danza/cortex", os.path.expanduser("~/.danza/cortex/global.db")]`. `assert_unchanged(before: dict, after: dict) -> list[str]` returns the list of changed keys (empty == unchanged).

- [ ] **Step 1: Write the failing test**

Add to `S/tests/test_harness.py`:

```python
import tempfile
from harness import snapshot_guard


class TestSnapshotGuard(unittest.TestCase):
    def test_detects_change_and_absence(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "a.db")
            with open(f, "w") as fh:
                fh.write("one")
            before = snapshot_guard.snapshot([f, os.path.join(d, "missing")])
            self.assertEqual(before[os.path.join(d, "missing")], "ABSENT")
            # unchanged
            self.assertEqual(snapshot_guard.assert_unchanged(before,
                             snapshot_guard.snapshot([f, os.path.join(d, "missing")])), [])
            # changed
            with open(f, "w") as fh:
                fh.write("two")
            after = snapshot_guard.snapshot([f, os.path.join(d, "missing")])
            self.assertIn(f, snapshot_guard.assert_unchanged(before, after))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tre/dev/danza-cortex-app-test && python3 -m unittest tests.test_harness.TestSnapshotGuard -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.snapshot_guard'`.

- [ ] **Step 3: Write minimal implementation**

Create `S/harness/snapshot_guard.py`:

```python
"""Fail-loud proof that the test never wrote real CORTEX memory. Hash the OS
repo's .danza/cortex and the user's global DB before and after; any diff is a
test failure, not a warning."""
from __future__ import annotations

import hashlib
import os


def _hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(paths_list: list[str]) -> dict:
    out: dict[str, str] = {}
    for p in paths_list:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for name in sorted(files):
                    fp = os.path.join(root, name)
                    out[fp] = _hash_file(fp)
        elif os.path.isfile(p):
            out[p] = _hash_file(p)
        else:
            out[p] = "ABSENT"
    return out


def real_memory_targets() -> list[str]:
    return ["/home/tre/dev/DANZA-OS/.danza/cortex",
            os.path.expanduser("~/.danza/cortex/global.db")]


def assert_unchanged(before: dict, after: dict) -> list[str]:
    changed = []
    for key in set(before) | set(after):
        if before.get(key) != after.get(key):
            changed.append(key)
    return sorted(changed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/tre/dev/danza-cortex-app-test && python3 -m unittest tests.test_harness.TestSnapshotGuard -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/tre/dev/danza-cortex-app-test
git add -A && git commit -q -m "test: OS real-memory snapshot guard"
```

---

### Task 3: Fresh mock-app initializer

**Files:**
- Create: `S/harness/init_app.py`
- Test: `S/tests/test_harness.py`

**Interfaces:**
- Consumes: `Paths` (Task 1).
- Produces: `init_app(paths: Paths) -> None` — deletes any existing `paths.app_dir`, then writes a fresh mock app: `.danza/handoff.md` containing exactly `"No handoff yet."`, `.danza/onboarding-answers.md` (canned), `.danza/cortex/project.json` == `{"project": "mockapp"}`, and a `README.md` describing the app idea. `APP_CONCEPT: str` module constant (the one-line idea used by both phases).

- [ ] **Step 1: Write the failing test**

Add to `S/tests/test_harness.py`:

```python
import json as _json
from harness.init_app import init_app, APP_CONCEPT


class TestInitApp(unittest.TestCase):
    def test_fresh_new_mode_fixtures(self):
        with tempfile.TemporaryDirectory() as d:
            p = Paths(sandbox=d)
            init_app(p)
            handoff = Path(p.app_dir, ".danza", "handoff.md").read_text()
            self.assertEqual(handoff.strip(), "No handoff yet.")
            self.assertTrue(Path(p.app_dir, ".danza", "onboarding-answers.md").read_text().strip())
            marker = _json.loads(Path(p.app_dir, ".danza", "cortex", "project.json").read_text())
            self.assertEqual(marker["project"], "mockapp")
            self.assertIn(APP_CONCEPT, Path(p.app_dir, "README.md").read_text())

    def test_idempotent_reset(self):
        with tempfile.TemporaryDirectory() as d:
            p = Paths(sandbox=d)
            init_app(p)
            Path(p.app_dir, "stray.txt").write_text("leftover")
            init_app(p)  # must wipe stray
            self.assertFalse(Path(p.app_dir, "stray.txt").exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tre/dev/danza-cortex-app-test && python3 -m unittest tests.test_harness.TestInitApp -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.init_app'`.

- [ ] **Step 3: Write minimal implementation**

Create `S/harness/init_app.py`:

```python
"""Create a brand-new mock app that forces NEW-PROJECT mode (Rule 39) and pins
CORTEX identity to 'mockapp'. Deterministic and disposable: re-running wipes the
prior app so every test starts cold."""
from __future__ import annotations

import json
import os
import shutil

from .paths import Paths

APP_CONCEPT = "Quote of the Day CLI: prints one inspirational quote per day."

_ONBOARDING = """\
# Onboarding Answers (canned, for CORTEX app-layer test)

- App name: Quote of the Day
- Concept: {concept}
- Target user: a developer who wants a daily quote in their terminal
- Platform: Python CLI
- Stack preference: no preference — let DANZA suggest a stack that works well
- Scope for this turn: 2 features (fetch-or-store quotes, print today's quote)
""".format(concept=APP_CONCEPT)


def init_app(paths: Paths) -> None:
    app = paths.app_dir
    if os.path.isdir(app):
        shutil.rmtree(app)
    danza = os.path.join(app, ".danza")
    cortex = os.path.join(danza, "cortex")
    os.makedirs(cortex, exist_ok=True)
    os.makedirs(os.path.join(danza, "logs"), exist_ok=True)
    with open(os.path.join(danza, "handoff.md"), "w") as fh:
        fh.write("No handoff yet.\n")
    with open(os.path.join(danza, "onboarding-answers.md"), "w") as fh:
        fh.write(_ONBOARDING)
    with open(os.path.join(cortex, "project.json"), "w") as fh:
        json.dump({"project": "mockapp"}, fh)
    with open(os.path.join(app, "README.md"), "w") as fh:
        fh.write("# Mock App\n\n" + APP_CONCEPT + "\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/tre/dev/danza-cortex-app-test && python3 -m unittest tests.test_harness.TestInitApp -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/tre/dev/danza-cortex-app-test
git add -A && git commit -q -m "test: fresh mock-app initializer (NEW mode + pinned identity)"
```

---

### Task 4: Seed one global build-order template

**Files:**
- Create: `S/harness/seed_global.py`
- Test: `S/tests/test_harness.py`

**Interfaces:**
- Consumes: `Paths` (Task 1), `apply_env` (Task 1), `init_app` (Task 3).
- Produces: `seed_build_order(paths: Paths) -> str` — writes one `layer=4` build-order `Observation` into the sandbox global store via `danzaboss.cortex.factory.open_global_store()` and returns its `id`. `TEMPLATE_TITLE: str` constant. Requires `apply_env(paths)` to have been called (so `open_global_store` targets the sandbox global DB).

- [ ] **Step 1: Write the failing test**

Add to `S/tests/test_harness.py`:

```python
from harness import seed_global


class TestSeedGlobal(unittest.TestCase):
    def test_seed_lands_in_global_and_federates_to_app(self):
        with tempfile.TemporaryDirectory() as d:
            p = Paths(sandbox=d)
            apply_env(p)
            init_app(p)
            tid = seed_global.seed_build_order(p)
            self.assertTrue(tid.startswith("obs_"))
            # imported here so PYTHONPATH/env are already applied
            from danzaboss.cortex.factory import open_global_store, open_project_store
            globs = open_global_store().backend.all()
            self.assertTrue(any(o.id == tid and o.layer >= 4 for o in globs))
            # project store is still empty (fresh app)
            self.assertEqual(open_project_store(p.app_dir).backend.all("mockapp"), [])
            # federated search from the app finds the global template (HIT)
            from danzaboss.cortex.factory import open_store
            hits = open_store(p.app_dir).backend.search("build order cli", project="mockapp")
            self.assertTrue(any(o.id == tid for o in hits))
```

> Note: this test requires the OS repo importable. The `apply_env` call sets `PYTHONPATH`, but Python resolves imports from `sys.path` at process start; add the OS repo to `sys.path` at the top of the test file (Step 2) so `import danzaboss...` works in-process.

- [ ] **Step 2: Make danzaboss importable in-process (test header)**

At the top of `S/tests/test_harness.py`, below the existing `sys.path.insert` line, add:

```python
sys.path.insert(0, "/home/tre/dev/DANZA-OS")  # import danzaboss.* in-process
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /home/tre/dev/danza-cortex-app-test && python3 -m unittest tests.test_harness.TestSeedGlobal -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.seed_global'`.

- [ ] **Step 4: Write minimal implementation**

Create `S/harness/seed_global.py`:

```python
"""Seed the shared L4/L5 global store with ONE build-order template — the
minimal placeholder for the future tech-stack/template library. Layer 4 makes
it cross-project (federate.py GLOBAL_LAYER), so a fresh app federates it in
without any local copy. apply_env() must have run first so open_global_store()
targets the sandbox global DB, never ~/.danza/cortex/global.db."""
from __future__ import annotations

from danzaboss.cortex.factory import open_global_store
from danzaboss.cortex.observation import Observation

from .paths import Paths

TEMPLATE_TITLE = "Build order for a Python CLI tool"


def seed_build_order(paths: Paths) -> str:
    obs = Observation(
        title=TEMPLATE_TITLE,
        summary=("Recommended build order for a small Python CLI: "
                 "1) scaffold package + entry point, 2) core logic module, "
                 "3) unit tests, 4) CLI arg wiring, 5) README/usage docs."),
        type="convention",
        project="_global_templates",
        layer=4,
        importance="high",
        confidence=90,
        confidence_source="repo_verified",
        tags=["build-order", "cli", "python", "template"],
        concepts=["build order", "cli tool", "scaffold"],
        reasoning=("New CLI apps that wire the interface before the core logic "
                   "repeatedly stall; core-first with tests keeps features verifiable."),
        when_relevant=["planning a new cli app", "build order", "feature sequencing"],
        when_not_relevant=["web frontend", "database schema design"],
    )
    return open_global_store().upsert(obs).id
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/tre/dev/danza-cortex-app-test && python3 -m unittest tests.test_harness.TestSeedGlobal -v`
Expected: PASS. (Confirms: template in global at layer≥4, app project store empty, federated search HIT.)

- [ ] **Step 6: Commit**

```bash
cd /home/tre/dev/danza-cortex-app-test
git add -A && git commit -q -m "test: seed one L4 build-order template into sandbox global store"
```

---

### Task 5: CORTEX CLI wrapper + store dump

**Files:**
- Create: `S/harness/cortex_cli.py`, `S/harness/dump_cortex.py`
- Test: `S/tests/test_harness.py`

**Interfaces:**
- Consumes: `Paths`, `build_env`, `apply_env` (Task 1), `init_app` (Task 3).
- Produces:
  - `cortex_cli.run(paths, args, stdin=None) -> CortexResult` where `CortexResult` is a dataclass `(rc: int, out: str, err: str)`. Runs `python3 -m danzaboss.cli cortex <args...>` with `cwd=paths.app_dir` and `env=build_env(paths)`; `stdin` is passed to the process stdin.
  - `dump_cortex.dump(paths) -> dict` with keys `project` (list of obs rows from `open_project_store(app_dir).backend.all("mockapp")`), `global_` (list from `open_global_store().backend.all()`), `usage` (from `open_store(app_dir).backend.usage_log()`), each obs reduced to `{id,title,type,layer,project,usage_count}`. Requires `apply_env` first.

- [ ] **Step 1: Write the failing test**

Add to `S/tests/test_harness.py`:

```python
from harness import cortex_cli, dump_cortex, seed_global as _seed


class TestCliAndDump(unittest.TestCase):
    def test_cli_stats_runs_and_dump_reports_seed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Paths(sandbox=d)
            apply_env(p)
            init_app(p)
            tid = _seed.seed_build_order(p)
            res = cortex_cli.run(p, ["stats"])
            self.assertEqual(res.rc, 0, res.err)
            _json.loads(res.out)  # stats prints JSON
            snap = dump_cortex.dump(p)
            self.assertTrue(any(o["id"] == tid for o in snap["global_"]))
            self.assertEqual(snap["project"], [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tre/dev/danza-cortex-app-test && python3 -m unittest tests.test_harness.TestCliAndDump -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.cortex_cli'`.

- [ ] **Step 3: Write minimal implementation**

Create `S/harness/cortex_cli.py`:

```python
"""Thin wrapper around `danza cortex ...` that always runs in the mock-app dir
with the sandbox env. Mirrors exactly how agents invoke CORTEX."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .paths import Paths, build_env


@dataclass
class CortexResult:
    rc: int
    out: str
    err: str


def run(paths: Paths, args: list[str], stdin: str | None = None) -> CortexResult:
    proc = subprocess.run(
        ["python3", "-m", "danzaboss.cli", "cortex", *args],
        cwd=paths.app_dir, env=build_env(paths),
        input=stdin, capture_output=True, text=True)
    return CortexResult(rc=proc.returncode, out=proc.stdout, err=proc.stderr)
```

Create `S/harness/dump_cortex.py`:

```python
"""Read the two CORTEX stores into a plain dict for asserts and the report.
apply_env() must have run so open_* target the sandbox DBs."""
from __future__ import annotations

from danzaboss.cortex.factory import open_global_store, open_project_store, open_store

from .paths import Paths


def _row(o) -> dict:
    return {"id": o.id, "title": o.title, "type": o.type, "layer": o.layer,
            "project": o.project, "usage_count": o.usage_count}


def dump(paths: Paths) -> dict:
    project = [_row(o) for o in open_project_store(paths.app_dir).backend.all("mockapp")]
    global_ = [_row(o) for o in open_global_store().backend.all()]
    usage = open_store(paths.app_dir).backend.usage_log()
    return {"project": project, "global_": global_, "usage": usage}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/tre/dev/danza-cortex-app-test && python3 -m unittest tests.test_harness.TestCliAndDump -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/tre/dev/danza-cortex-app-test
git add -A && git commit -q -m "test: cortex CLI wrapper + two-store dump"
```

---

### Task 6: The three checks (A/B/C)

**Files:**
- Create: `S/harness/checks.py`
- Test: `S/tests/test_harness.py`

**Interfaces:**
- Consumes: `Paths` (Task 1).
- Produces: dataclass `CheckResult(name: str, passed: bool, evidence: list[str], failures: list[str])` and three functions:
  - `check_onboarding(paths, require_products: bool) -> CheckResult` — verifies NEW-mode fixtures (handoff == "No handoff yet.", onboarding answers non-empty, marker == mockapp); when `require_products=True` also requires `.danza/logs/001.md` and `.danza/feature-list.md` to exist (live run only).
  - `check_cortex_usage(ops: list[dict], template_id: str) -> CheckResult` — over an ordered op log (each `{"cmd": str, "args": list, "hit_ids": list, "obs": dict|None}`) asserts: (1) a `search` or `retrieve` occurs before any `observe`; (2) the build-order `template_id` appears in some op's `hit_ids` (a real retrieval HIT); (3) at least one `observe` op whose `obs` has non-empty `reasoning`, `when_relevant`, and `when_not_relevant`.
  - `check_scoping(dump: dict, template_id: str, changed_os_paths: list[str]) -> CheckResult` — asserts: every `project` obs has `layer <= 3` and `project == "mockapp"`; `template_id` is present in `global_` with `layer >= 4`; no `project` obs id appears in `global_` (no leak up); `changed_os_paths` is empty (OS untouched).

- [ ] **Step 1: Write the failing test**

Add to `S/tests/test_harness.py`:

```python
from harness import checks


class TestChecks(unittest.TestCase):
    def test_onboarding_pass(self):
        with tempfile.TemporaryDirectory() as d:
            p = Paths(sandbox=d)
            init_app(p)
            r = checks.check_onboarding(p, require_products=False)
            self.assertTrue(r.passed, r.failures)

    def test_onboarding_requires_products_when_asked(self):
        with tempfile.TemporaryDirectory() as d:
            p = Paths(sandbox=d)
            init_app(p)
            r = checks.check_onboarding(p, require_products=True)
            self.assertFalse(r.passed)  # no logs/001.md yet

    def test_cortex_usage_pass(self):
        ops = [
            {"cmd": "search", "args": ["build order"], "hit_ids": ["obs_T"], "obs": None},
            {"cmd": "get", "args": ["obs_T"], "hit_ids": ["obs_T"], "obs": None},
            {"cmd": "observe", "args": [], "hit_ids": [],
             "obs": {"reasoning": "why", "when_relevant": ["x"], "when_not_relevant": ["y"]}},
        ]
        r = checks.check_cortex_usage(ops, "obs_T")
        self.assertTrue(r.passed, r.failures)

    def test_cortex_usage_fails_without_search_before_observe(self):
        ops = [{"cmd": "observe", "args": [], "hit_ids": [],
                "obs": {"reasoning": "why", "when_relevant": ["x"], "when_not_relevant": ["y"]}}]
        self.assertFalse(checks.check_cortex_usage(ops, "obs_T").passed)

    def test_scoping_detects_leak_and_os_change(self):
        good = {"project": [{"id": "obs_A", "layer": 2, "project": "mockapp"}],
                "global_": [{"id": "obs_T", "layer": 4, "project": "_global_templates"}]}
        self.assertTrue(checks.check_scoping(good, "obs_T", []).passed)
        leak = {"project": [{"id": "obs_A", "layer": 2, "project": "mockapp"}],
                "global_": [{"id": "obs_T", "layer": 4, "project": "_g"},
                            {"id": "obs_A", "layer": 4, "project": "mockapp"}]}
        self.assertFalse(checks.check_scoping(leak, "obs_T", []).passed)
        self.assertFalse(checks.check_scoping(good, "obs_T", ["/some/os/path.db"]).passed)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tre/dev/danza-cortex-app-test && python3 -m unittest tests.test_harness.TestChecks -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.checks'`.

- [ ] **Step 3: Write minimal implementation**

Create `S/harness/checks.py`:

```python
"""The three pass/fail checks the test exists to answer:
A onboard correctly, B use CORTEX as intended, C keep memory scoped."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .paths import Paths


@dataclass
class CheckResult:
    name: str
    passed: bool
    evidence: list = field(default_factory=list)
    failures: list = field(default_factory=list)


def check_onboarding(paths: Paths, require_products: bool) -> CheckResult:
    ev, fail = [], []
    danza = os.path.join(paths.app_dir, ".danza")

    def _read(rel):
        try:
            with open(os.path.join(danza, rel)) as fh:
                return fh.read()
        except OSError:
            return None

    handoff = _read("handoff.md")
    if handoff is not None and handoff.strip() == "No handoff yet.":
        ev.append("handoff.md signals NEW-PROJECT mode (Rule 39)")
    else:
        fail.append("handoff.md missing or not in NEW-PROJECT state")

    answers = _read("onboarding-answers.md")
    if answers and answers.strip():
        ev.append("onboarding-answers.md present and non-empty")
    else:
        fail.append("onboarding-answers.md missing/empty")

    try:
        marker = json.loads(_read("cortex/project.json") or "{}")
    except ValueError:
        marker = {}
    if marker.get("project") == "mockapp":
        ev.append("CORTEX identity pinned to 'mockapp'")
    else:
        fail.append("project.json identity is not 'mockapp'")

    if require_products:
        if os.path.exists(os.path.join(danza, "logs", "001.md")):
            ev.append("run log .danza/logs/001.md created (Rule 40)")
        else:
            fail.append("no run log .danza/logs/001.md produced")
        if os.path.exists(os.path.join(danza, "feature-list.md")):
            ev.append("feature-list.md produced")
        else:
            fail.append("no feature-list.md produced")

    return CheckResult("A. Onboard correctly", not fail, ev, fail)


def check_cortex_usage(ops: list, template_id: str) -> CheckResult:
    ev, fail = [], []
    first_observe = next((i for i, o in enumerate(ops) if o["cmd"] == "observe"), None)
    first_read = next((i for i, o in enumerate(ops)
                       if o["cmd"] in ("search", "retrieve")), None)
    if first_read is not None and (first_observe is None or first_read < first_observe):
        ev.append("agent searched/retrieved CORTEX before writing (search-before-work)")
    else:
        fail.append("no search/retrieve before observe")

    if any(template_id in o.get("hit_ids", []) for o in ops):
        ev.append(f"build-order template retrieved (HIT on {template_id})")
    else:
        fail.append(f"build-order template {template_id} was never retrieved")

    good_obs = [o for o in ops if o["cmd"] == "observe" and o.get("obs")
                and o["obs"].get("reasoning")
                and o["obs"].get("when_relevant")
                and o["obs"].get("when_not_relevant")]
    if good_obs:
        ev.append("observation stored with reasoning + relevance gates (Rule 43 shape)")
    else:
        fail.append("no observation with reasoning + when_relevant/when_not_relevant")

    return CheckResult("B. Use CORTEX as intended", not fail, ev, fail)


def check_scoping(dump: dict, template_id: str, changed_os_paths: list) -> CheckResult:
    ev, fail = [], []
    proj_ids = {o["id"] for o in dump["project"]}
    for o in dump["project"]:
        if o["layer"] > 3:
            fail.append(f"project obs {o['id']} has global layer {o['layer']}")
        if o["project"] != "mockapp":
            fail.append(f"project obs {o['id']} scoped to {o['project']!r}, not mockapp")
    if not fail:
        ev.append(f"all {len(dump['project'])} app observations are layer<=3 and scoped to mockapp")

    tmpl = next((g for g in dump["global_"] if g["id"] == template_id), None)
    if tmpl and tmpl["layer"] >= 4:
        ev.append("build-order template resides in the global store (layer>=4)")
    else:
        fail.append("build-order template missing from global store")

    leaked = proj_ids & {g["id"] for g in dump["global_"]}
    if leaked:
        fail.append(f"app observations leaked into global store: {sorted(leaked)}")
    else:
        ev.append("no app observation leaked up into the global store")

    if changed_os_paths:
        fail.append(f"OS real memory CHANGED: {changed_os_paths}")
    else:
        ev.append("OS .danza/cortex and ~/.danza/cortex/global.db byte-identical")

    return CheckResult("C. Keep memory scoped", not fail, ev, fail)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/tre/dev/danza-cortex-app-test && python3 -m unittest tests.test_harness.TestChecks -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/tre/dev/danza-cortex-app-test
git add -A && git commit -q -m "test: onboarding/usage/scoping checks"
```

---

### Task 7: Phase 2 deterministic harness driver

**Files:**
- Create: `S/harness/harness.py`
- Test: `S/tests/test_harness.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: `run(paths: Paths) -> dict` returning `{"phase": "harness", "template_id": str, "ops": list, "dump": dict, "checks": [CheckResult...], "os_changed": list, "passed": bool}`. Also a `__main__` block: `python -m harness.harness [sandbox]` runs against the real sandbox and prints the results JSON. The driver: snapshots OS memory → `init_app` → `seed_build_order` → simulates one build turn through the real CLI (`search` → `get` → PostToolUse event → first `stop` [expect BLOCK] → `observe` with reasoning+gates → second `stop` [expect OK]) → re-snapshots OS memory → runs the three checks (usage uses `require_products=False`).

The build turn's CLI calls, in order, all via `cortex_cli.run`:
1. `session-start` hook (`hook session-start`, stdin `{"session_id":"s1"}`)
2. `search build order cli` → record `hit_ids` = ids parsed from JSON out
3. `get <template_id>`
4. `hook post-tool-use` stdin `{"session_id":"s1","tool_name":"Write","tool_input":{"file_path":"quote.py"},"tool_response":{"success":true}}`
5. `hook stop` stdin `{"session_id":"s1"}` → expect stdout JSON `{"decision":"block",...}`
6. `observe --session s1` stdin = the learning JSON (below) → record `obs`
7. `hook stop` stdin `{"session_id":"s1"}` → expect clean (no block)

The observe payload:
```json
{"title":"Quote CLI stores quotes in a local JSON file",
 "summary":"Chose a bundled quotes.json over a network fetch for offline-first simplicity.",
 "type":"decision","reasoning":"Offline-first avoids a network dependency for a daily-quote CLI.",
 "when_relevant":["quote storage","offline cli"],"when_not_relevant":["web app"]}
```

- [ ] **Step 1: Write the failing test**

Add to `S/tests/test_harness.py`:

```python
from harness import harness as harness_mod


class TestHarnessRun(unittest.TestCase):
    def test_full_run_all_checks_pass(self):
        with tempfile.TemporaryDirectory() as d:
            p = Paths(sandbox=d)
            result = harness_mod.run(p)
            self.assertTrue(result["passed"],
                            [(c.name, c.failures) for c in result["checks"]])
            # the distill gate must have blocked on the first stop
            self.assertTrue(any(o["cmd"] == "stop" and o.get("blocked") for o in result["ops"]))
            # exactly one app observation, scoped, and OS memory untouched
            self.assertEqual(len(result["dump"]["project"]), 1)
            self.assertEqual(result["os_changed"], [])
```

> This test hits the real OS `danzaboss` via subprocess and the real OS snapshot targets. It writes only inside the tmp sandbox; the snapshot guard asserts the OS is untouched. It needs `python3` and the OS repo on disk (both present in this environment).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tre/dev/danza-cortex-app-test && python3 -m unittest tests.test_harness.TestHarnessRun -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.harness'`.

- [ ] **Step 3: Write minimal implementation**

Create `S/harness/harness.py`:

```python
"""Phase 2: deterministic replay of the prescribed agent CORTEX protocol against
a fresh mock app — no LLM. Answers checks A/B/C repeatably and doubles as a
regression test. Never touches real memory (snapshot-guarded)."""
from __future__ import annotations

import json
import sys

from .paths import Paths, apply_env
from . import checks, cortex_cli, dump_cortex, init_app, seed_global, snapshot_guard

_OBSERVE_PAYLOAD = {
    "title": "Quote CLI stores quotes in a local JSON file",
    "summary": "Chose a bundled quotes.json over a network fetch for offline-first simplicity.",
    "type": "decision",
    "reasoning": "Offline-first avoids a network dependency for a daily-quote CLI.",
    "when_relevant": ["quote storage", "offline cli"],
    "when_not_relevant": ["web app"],
}


def _ids_from_search(out: str) -> list:
    try:
        return [r["id"] for r in json.loads(out)]
    except (ValueError, TypeError, KeyError):
        return []


def run(paths: Paths) -> dict:
    apply_env(paths)
    targets = snapshot_guard.real_memory_targets()
    before = snapshot_guard.snapshot(targets)

    init_app.init_app(paths)
    template_id = seed_global.seed_build_order(paths)

    ops: list = []
    cortex_cli.run(paths, ["hook", "session-start"], stdin='{"session_id":"s1"}')

    r_search = cortex_cli.run(paths, ["search", "build", "order", "cli"])
    ops.append({"cmd": "search", "args": ["build order cli"],
                "hit_ids": _ids_from_search(r_search.out), "obs": None})

    cortex_cli.run(paths, ["get", template_id])
    ops.append({"cmd": "get", "args": [template_id], "hit_ids": [template_id], "obs": None})

    cortex_cli.run(paths, ["hook", "post-tool-use"], stdin=json.dumps(
        {"session_id": "s1", "tool_name": "Write",
         "tool_input": {"file_path": "quote.py"}, "tool_response": {"success": True}}))

    r_stop1 = cortex_cli.run(paths, ["hook", "stop"], stdin='{"session_id":"s1"}')
    blocked = '"decision": "block"' in r_stop1.out or '"decision":"block"' in r_stop1.out
    ops.append({"cmd": "stop", "args": [], "hit_ids": [], "obs": None, "blocked": blocked})

    cortex_cli.run(paths, ["observe", "--session", "s1"],
                   stdin=json.dumps(_OBSERVE_PAYLOAD))
    ops.append({"cmd": "observe", "args": [], "hit_ids": [], "obs": _OBSERVE_PAYLOAD})

    cortex_cli.run(paths, ["hook", "stop"], stdin='{"session_id":"s1"}')
    ops.append({"cmd": "stop", "args": [], "hit_ids": [], "obs": None, "blocked": False})

    dump = dump_cortex.dump(paths)
    after = snapshot_guard.snapshot(targets)
    os_changed = snapshot_guard.assert_unchanged(before, after)

    results = [
        checks.check_onboarding(paths, require_products=False),
        checks.check_cortex_usage(ops, template_id),
        checks.check_scoping(dump, template_id, os_changed),
    ]
    return {"phase": "harness", "template_id": template_id, "ops": ops,
            "dump": dump, "checks": results, "os_changed": os_changed,
            "passed": all(c.passed for c in results)}


if __name__ == "__main__":
    sandbox = sys.argv[1] if len(sys.argv) > 1 else "/home/tre/dev/danza-cortex-app-test"
    res = run(Paths(sandbox=sandbox))
    printable = {**res, "checks": [vars(c) for c in res["checks"]]}
    print(json.dumps(printable, indent=2))
    sys.exit(0 if res["passed"] else 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/tre/dev/danza-cortex-app-test && python3 -m unittest tests.test_harness.TestHarnessRun -v`
Expected: PASS. If the first `stop` did not block, re-read `gates.py:55-72` — under `APP_BUILD` with one pending event and zero observations it MUST block.

- [ ] **Step 5: Run the whole suite once green**

Run: `cd /home/tre/dev/danza-cortex-app-test && python3 -m unittest discover -s tests -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/tre/dev/danza-cortex-app-test
git add -A && git commit -q -m "test: Phase 2 deterministic CORTEX app-layer harness"
```

---

### Task 8: Results report renderer

**Files:**
- Create: `S/harness/report.py`
- Test: `S/tests/test_harness.py`

**Interfaces:**
- Consumes: `CheckResult` shape (Task 6), the `run()` result dict (Task 7).
- Produces: `render(harness_result: dict, live_notes: str = "") -> str` — a Markdown `RESULTS.md` body with: a header, a per-check table (name, PASS/FAIL, evidence count), an expanded evidence/failures list per check, the two-store contents summary (counts + the template + the app observation), the `os_changed` line, an optional live-run notes section, and a final overall verdict + recommendation line. `write(paths, harness_result, live_notes="") -> str` writes it to `<sandbox>/RESULTS.md` and returns the path.

- [ ] **Step 1: Write the failing test**

Add to `S/tests/test_harness.py`:

```python
from harness import report


class TestReport(unittest.TestCase):
    def test_render_contains_verdict_and_checks(self):
        with tempfile.TemporaryDirectory() as d:
            p = Paths(sandbox=d)
            res = harness_mod.run(p)
            md = report.render(res, live_notes="(live run pending)")
            self.assertIn("# CORTEX App-Layer Test — Results", md)
            self.assertIn("A. Onboard correctly", md)
            self.assertIn("B. Use CORTEX as intended", md)
            self.assertIn("C. Keep memory scoped", md)
            self.assertIn("OVERALL", md)
            path = report.write(p, res, live_notes="(live run pending)")
            self.assertTrue(os.path.exists(path))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tre/dev/danza-cortex-app-test && python3 -m unittest tests.test_harness.TestReport -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.report'`.

- [ ] **Step 3: Write minimal implementation**

Create `S/harness/report.py`:

```python
"""Render RESULTS.md from a harness run (+ optional live-run notes)."""
from __future__ import annotations

import os

from .paths import Paths


def render(harness_result: dict, live_notes: str = "") -> str:
    checks = harness_result["checks"]
    lines = ["# CORTEX App-Layer Test — Results", ""]
    lines.append("## Summary")
    lines.append("")
    lines.append("| Check | Verdict | Evidence |")
    lines.append("|---|---|---|")
    for c in checks:
        verdict = "✅ PASS" if c.passed else "❌ FAIL"
        lines.append(f"| {c.name} | {verdict} | {len(c.evidence)} item(s) |")
    lines.append("")

    for c in checks:
        lines.append(f"### {c.name} — {'PASS' if c.passed else 'FAIL'}")
        for e in c.evidence:
            lines.append(f"- ✅ {e}")
        for f in c.failures:
            lines.append(f"- ❌ {f}")
        lines.append("")

    dump = harness_result["dump"]
    lines.append("## CORTEX store contents (Phase 2)")
    lines.append(f"- App project store (`mockapp`): {len(dump['project'])} observation(s)")
    for o in dump["project"]:
        lines.append(f"  - `{o['id']}` L{o['layer']} [{o['project']}] — {o['title']}")
    lines.append(f"- Global store: {len(dump['global_'])} observation(s)")
    for o in dump["global_"]:
        lines.append(f"  - `{o['id']}` L{o['layer']} [{o['project']}] — {o['title']}")
    lines.append(f"- OS real memory changed: {harness_result['os_changed'] or 'none (untouched)'}")
    lines.append("")

    if live_notes:
        lines.append("## Phase 1 — Live agent run")
        lines.append(live_notes)
        lines.append("")

    overall = all(c.passed for c in checks)
    lines.append("## OVERALL")
    lines.append("")
    if overall:
        lines.append("**PASS.** Agents onboard a fresh app, use CORTEX per protocol, and app "
                     "memory stays scoped. The plumbing the future template library will ride "
                     "on is verified. Recommendation: proceed to evaluate OS-layer enablement "
                     "as a separate, explicit change.")
    else:
        lines.append("**FAIL.** One or more checks did not pass (see above). Do NOT enable "
                     "CORTEX in the OS layer until resolved.")
    return "\n".join(lines) + "\n"


def write(paths: Paths, harness_result: dict, live_notes: str = "") -> str:
    os.makedirs(paths.sandbox, exist_ok=True)
    out = os.path.join(paths.sandbox, "RESULTS.md")
    with open(out, "w") as fh:
        fh.write(render(harness_result, live_notes))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/tre/dev/danza-cortex-app-test && python3 -m unittest tests.test_harness.TestReport -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/tre/dev/danza-cortex-app-test
git add -A && git commit -q -m "test: RESULTS.md report renderer"
```

---

### Task 9: Phase 1 live agent run

**Files:**
- Create: `S/run_live.md` (runbook), `S/artifacts/live/` (captured outputs)

**Interfaces:**
- Consumes: the sandbox from Tasks 1–8 (harness modules for re-dumping the store after the live run).
- Produces: captured artifacts under `S/artifacts/live/` and a `live_notes` markdown string fed into `report.write` in Task 10.

This task is a procedure, not TDD — it observes real agent behavior. Execute it exactly.

- [ ] **Step 1: Reset a fresh app + seed the template for the live run**

```bash
cd /home/tre/dev/danza-cortex-app-test
mkdir -p artifacts/live
PYTHONPATH=/home/tre/dev/DANZA-OS DANZABOSS_PROFILE=APP_BUILD \
  DANZA_CORTEX_GLOBAL_DB=/home/tre/dev/danza-cortex-app-test/global.db \
  python3 -c "import sys; sys.path.insert(0,'harness'); \
from harness.paths import Paths, apply_env; from harness import init_app, seed_global; \
p=Paths('/home/tre/dev/danza-cortex-app-test'); apply_env(p); init_app.init_app(p); \
print('template_id', seed_global.seed_build_order(p))" | tee artifacts/live/00-seed.txt
```
Expected: prints `template_id obs_...`. Record that id.

- [ ] **Step 2: Snapshot OS real memory (before)**

```bash
cd /home/tre/dev/danza-cortex-app-test
python3 -c "import sys; sys.path.insert(0,'.'); import json; \
from harness import snapshot_guard as g; \
json.dump(g.snapshot(g.real_memory_targets()), open('artifacts/live/os-before.json','w'))"
echo "snapshot saved"
```

- [ ] **Step 3: Write the live runbook**

Create `S/run_live.md` documenting, for the human/agent operator, the exact spawn. Content:

```markdown
# Phase 1 — Live Agent Run

Goal: spawn the real `tony-d-orchestrator` on the fresh mock app and observe
its CORTEX use, without touching real memory.

## Environment (every command the agent runs must carry these)
- PYTHONPATH=/home/tre/dev/DANZA-OS
- DANZABOSS_PROFILE=APP_BUILD
- DANZA_CORTEX_GLOBAL_DB=/home/tre/dev/danza-cortex-app-test/global.db
- Working dir: /home/tre/dev/danza-cortex-app-test/mockapp

## Spawn prompt (Agent tool, subagent_type="tony-d-orchestrator")
> Who's the Boss? You are activating on a NEW target app located at
> `/home/tre/dev/danza-cortex-app-test/mockapp`. Its concept: "Quote of the Day
> CLI: prints one inspirational quote per day." Onboarding answers are in
> `.danza/onboarding-answers.md` — use them; do NOT ask the user. Run every
> `danza cortex` command from that directory with:
> `PYTHONPATH=/home/tre/dev/DANZA-OS DANZABOSS_PROFILE=APP_BUILD
> DANZA_CORTEX_GLOBAL_DB=/home/tre/dev/danza-cortex-app-test/global.db
> python3 -m danzaboss.cli cortex ...`.
> Do exactly this and stop: (1) detect NEW-PROJECT mode from
> `.danza/handoff.md`; (2) consult CORTEX for a build order via
> `cortex retrieve "build order for a new python cli app"`; (3) plan the 2
> features from the onboarding answers into `.danza/feature-list.md`; (4) write
> a run log `.danza/logs/001.md`; (5) store one durable decision via
> `cortex observe` (JSON on stdin with title, summary, type, reasoning,
> when_relevant, when_not_relevant). Report the observation IDs you read and
> wrote. Do NOT modify anything outside that directory.

## Capture
Save the agent's full final transcript to `artifacts/live/agent-transcript.md`
and note which cortex commands it actually ran (search/retrieve/get/observe).
```

- [ ] **Step 4: Execute the live spawn and capture the transcript**

Spawn the agent via the Agent tool using `subagent_type="tony-d-orchestrator"` and the prompt in `run_live.md`. When it completes, save its final message to `artifacts/live/agent-transcript.md`, and record the cortex ops it ran (from the transcript) as a JSON op-log at `artifacts/live/ops.json` in the same shape `check_cortex_usage` consumes: a list of `{"cmd","args","hit_ids","obs"}`.

> Honest-fidelity note: if the agent strays (wrong dir, skips a step, forgets env), record exactly what happened — do NOT edit the artifacts to look clean. The verdict for Phase 1 reflects reality; Phase 2 remains the deterministic answer.

- [ ] **Step 5: Snapshot OS real memory (after) and dump the store**

```bash
cd /home/tre/dev/danza-cortex-app-test
python3 -c "import sys; sys.path.insert(0,'.'); import json; \
from harness import snapshot_guard as g, dump_cortex, paths; \
p=paths.Paths('/home/tre/dev/danza-cortex-app-test'); paths.apply_env(p); \
before=json.load(open('artifacts/live/os-before.json')); \
after=g.snapshot(g.real_memory_targets()); \
json.dump({'os_changed': g.assert_unchanged(before, after), \
'dump': dump_cortex.dump(p)}, open('artifacts/live/after.json','w'), indent=2); \
print('os_changed:', g.assert_unchanged(before, after))"
```
Expected: `os_changed: []` (OS untouched). If not empty, STOP — the live run wrote real memory; investigate before proceeding.

- [ ] **Step 6: Commit live artifacts**

```bash
cd /home/tre/dev/danza-cortex-app-test
git add -f run_live.md artifacts/live/agent-transcript.md artifacts/live/ops.json artifacts/live/after.json artifacts/live/00-seed.txt
git commit -q -m "test: Phase 1 live agent run artifacts"
```

---

### Task 10: Assemble RESULTS.md and present

**Files:**
- Create: `S/RESULTS.md`; copy to `docs/superpowers/plans/` sibling for the user.

**Interfaces:**
- Consumes: Task 7 `run()`, Task 8 `report`, Task 9 live artifacts.

- [ ] **Step 1: Re-run the deterministic harness against the real sandbox**

```bash
cd /home/tre/dev/danza-cortex-app-test
python3 -m harness.harness /home/tre/dev/danza-cortex-app-test | tee artifacts/harness-run.json
echo "exit: $?"
```
Expected: JSON with `"passed": true`, exit 0.

- [ ] **Step 2: Build a live-notes string from the live artifacts**

Read `artifacts/live/agent-transcript.md`, `artifacts/live/ops.json`, and `artifacts/live/after.json`. Run `check_onboarding(paths, require_products=True)`, `check_cortex_usage(<ops.json>, <template_id>)`, and `check_scoping(<after.dump>, <template_id>, <after.os_changed>)` for the LIVE data, and summarize each as PASS/FAIL with its evidence/failures into a `live_notes` markdown string. Include the exact cortex commands the agent ran.

- [ ] **Step 3: Render and write RESULTS.md**

```bash
cd /home/tre/dev/danza-cortex-app-test
python3 -c "import sys, json; sys.path.insert(0,'.'); \
from harness import harness, report, paths; \
p=paths.Paths('/home/tre/dev/danza-cortex-app-test'); \
res=harness.run(p); \
live=open('artifacts/live/live_notes.md').read() if __import__('os').path.exists('artifacts/live/live_notes.md') else '(live run notes pending)'; \
print(report.write(p, res, live_notes=live))"
```
(Write the `live_notes` markdown from Step 2 to `artifacts/live/live_notes.md` first.)
Expected: prints the path to `RESULTS.md`.

- [ ] **Step 4: Verify RESULTS.md and full suite are green, present to user**

```bash
cd /home/tre/dev/danza-cortex-app-test
python3 -m unittest discover -s tests -v
sed -n '1,80p' RESULTS.md
```
Expected: suite PASS; `RESULTS.md` shows the per-check verdicts and an OVERALL line.

- [ ] **Step 5: Commit results**

```bash
cd /home/tre/dev/danza-cortex-app-test
git add -A && git commit -q -m "test: assemble CORTEX app-layer RESULTS.md (live + harness)"
```

- [ ] **Step 6: Present the verdict**

Show the user the `RESULTS.md` contents and the per-check PASS/FAIL table for BOTH phases. Explicitly state: no OS-layer files were modified, and OS real memory was byte-identical throughout. Recommend the go/no-go on OS-layer CORTEX enablement as a separate change. Do not modify the OS layer.

---

## Self-Review

**1. Spec coverage:**
- Goal/checks A/B/C → Tasks 6, 7, 9, 10. ✓
- Isolation (sandbox dir, PYTHONPATH read-only, both DBs redirected, snapshot guard, no worktree) → Tasks 1, 2, 5, 7. ✓
- Fresh onboarding (handoff NEW, canned answers, forced APP_BUILD) → Tasks 1 (env), 3 (fixtures), 9 (live). ✓
- Phase 1 live run (seed template, spawn Tony D, build-order lookup, capture) → Task 9. ✓
- Phase 2 harness (deterministic replay, hook entry points, regression test) → Task 7. ✓
- Outputs (RESULTS.md, PASS/FAIL, recommendation, OS untouched) → Tasks 8, 10. ✓
- Global-store pollution guard (`DANZA_CORTEX_GLOBAL_DB` + snapshot of `~/.danza/cortex/global.db`) → Tasks 1, 2, 7. ✓
- Future work (template library) → captured in spec + memory; not implemented here (correct — out of scope). ✓

**2. Placeholder scan:** No "TBD"/"handle appropriately"/"similar to Task N". Every code step shows complete code; every command shows expected output. Task 9 is intentionally a procedure (live observation) with an exact spawn prompt and capture steps, not vague. ✓

**3. Type consistency:** `Paths` properties (`app_dir`, `global_db`, `artifacts`, `OS_REPO`) used identically across Tasks 1/3/4/5/7/9/10. `CortexResult(rc,out,err)` consistent (Task 5→7). `CheckResult(name,passed,evidence,failures)` consistent (Task 6→8). Op-log shape `{"cmd","args","hit_ids","obs"[, "blocked"]}` consistent (Task 6 check ↔ Task 7 producer ↔ Task 9 live). `run()` result keys (`phase,template_id,ops,dump,checks,os_changed,passed`) consistent (Task 7→8→10). CORTEX APIs match verified source signatures (`Observation`, `open_global_store/open_project_store/open_store`, `.backend.all/search/usage_log`, `distillation_gate`). ✓
