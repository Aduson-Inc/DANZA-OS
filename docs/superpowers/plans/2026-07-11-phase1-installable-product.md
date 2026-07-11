# Phase 1 — Installable Product Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-07-11-danza-os-product-completion-design.md` §5 (Phase 1), §11 (cross-cutting rules).

**Goal:** Make DANZA-OS pip-installable (`pipx install git+https://github.com/Aduson-Inc/DANZA-OS`) with a `danza` console script, a `danza init` scaffolder that activates any repo, a `danza doctor` health check, and a hardened `install.sh` — proven on this machine with a fresh temp repo.

**Architecture:** A new `danzaboss/product/` package holds packaging-and-lifecycle code: `scaffold.py` (idempotent copy/merge of a bundled `.claude/` + `.danza/` payload via `importlib.resources`), `doctor.py` (env + profile + CORTEX + runner checks, reusing the selftest `Report` type), and `resume.py` (the D8 auto-resume SessionStart hook). `pyproject.toml` packages everything with zero runtime deps; `cli.py` gains `init` and `doctor` commands plus a `hook session-start` event.

**Tech Stack:** Python 3.10+ stdlib only. setuptools build backend. unittest (NOT pytest — the suite runs via `danzaboss/run_tests.sh` → `python3 -m unittest discover`).

## Global Constraints

- **Stdlib only** in all OS code; the optional extra `neon` (`psycopg[binary]`) is never required for tests (spec §11).
- **Package identity (D1/D2, spec §5):** `[project] name = "danza-os"`, zero runtime deps, `[project.scripts] danza = "danzaboss.cli:main"`, install source `git+https://github.com/Aduson-Inc/DANZA-OS`.
- **Fail closed:** invalid scaffold state raises; degraded paths are flagged, never silent (spec §11). Hook entry points fail OPEN (a hook bug must never brick a session — existing `cli.py` contract).
- **Rules 34–35 encoded in scaffold logic:** never overwrite user-edited files; state is merged, not clobbered; per-file result `created / merged / skipped(user-modified)`.
- **Rule 16:** never delete existing repo files. (This plan only adds files.)
- **Style is law:** new modules mirror the closest existing module — `workstation/runners.py` for validation/persistence idiom, `selftest/harness.py` for the Report/Check idiom, `cortex/commands.py` for hook handlers. Module docstrings state *why*.
- **Tests mandatory:** every task lands with its unittest file; `./danzaboss/run_tests.sh` must be green at the phase boundary (733 existing tests + new ones).
- **Test invocation (single task):**
  ```bash
  cd /home/tre/dev/DANZA-OS && PYTHONPATH="$PWD:$PWD/danzaboss/tests" \
    DANZA_CORTEX_GLOBAL_DB="$(mktemp -d)/global.db" \
    python3 -m unittest discover -s danzaboss/tests -p 'test_product_<name>.py' -v
  ```
- **Version source of truth:** `danzaboss/__init__.py` `__version__ = "0.1.0"`; pyproject reads it via `[tool.setuptools.dynamic]`.

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` (create) | Package metadata, console script, package data (product templates, cortex UI static, planning schemas, workstation stacks) |
| `danzaboss/__init__.py` (modify — currently empty) | `__version__` |
| `danzaboss/product/__init__.py` (create) | Package marker |
| `danzaboss/product/templates/` (create) | Bundled scaffold payload: `scaffold/claude/**` → target `.claude/`, `scaffold/danza/**` → target `.danza/`, plus `claude-md-managed-block.md` |
| `danzaboss/product/scaffold.py` (create) | `scaffold(target)` — idempotent copy/merge engine, CLAUDE.md managed block, `.danza/.scaffold-version` stamp |
| `danzaboss/product/resume.py` (create) | `session_start_context(root)` — D8 auto-resume CONTINUE-MODE block |
| `danzaboss/product/doctor.py` (create) | `run_doctor(root)` — env/git/scaffold/profile/runners/CORTEX/selftest checks |
| `danzaboss/cli.py` (modify) | `init`, `doctor` commands; `hook session-start` event; usage strings |
| `install.sh` (create) | Hardened curl\|bash wrapper around pipx |
| `danzaboss/tests/test_product_*.py` (create ×7) | Unit tests per module |

Payload dir names deliberately avoid leading dots (`claude/`, not `.claude/`): packaging globs and resource traversal skip dotfiles unreliably. `scaffold.py` maps `claude → .claude`, `danza → .danza` at copy time. The payload contains **no dotfiles**; `.gitkeep` and `.scaffold-version` are generated programmatically.

---

### Task 1: Package metadata (`pyproject.toml` + version)

**Files:**
- Create: `pyproject.toml`
- Modify: `danzaboss/__init__.py` (empty today)
- Test: `danzaboss/tests/test_product_packaging.py`

**Interfaces:**
- Produces: `danzaboss.__version__: str` (consumed by Task 3's manifest stamp); console script `danza = danzaboss.cli:main`; package data covering `danzaboss/product/templates/**` (consumed by Tasks 2–3 via `importlib.resources`).

- [ ] **Step 1: Write the failing test**

```python
"""Phase-1 T1 packaging: pyproject metadata matches D1/D2 and the version has
a single source of truth in danzaboss.__version__.

tomllib is 3.11+; the assertions are skipped (not failed) on 3.10 — the
package still builds there because setuptools does its own TOML parsing.
"""
import re
import sys
import unittest
from pathlib import Path

import _bootstrap  # noqa
import danzaboss

REPO = Path(__file__).resolve().parents[2]


class VersionAttr(unittest.TestCase):
    def test_version_is_semver_string(self):
        self.assertTrue(re.fullmatch(r"\d+\.\d+\.\d+", danzaboss.__version__),
                        f"bad __version__: {danzaboss.__version__!r}")


@unittest.skipUnless(sys.version_info >= (3, 11), "tomllib requires 3.11+")
class PyprojectMetadata(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tomllib
        with open(REPO / "pyproject.toml", "rb") as fh:
            cls.data = tomllib.load(fh)

    def test_identity_and_zero_deps(self):
        proj = self.data["project"]
        self.assertEqual(proj["name"], "danza-os")
        self.assertEqual(proj["dependencies"], [])
        self.assertEqual(proj["requires-python"], ">=3.10")

    def test_console_script(self):
        self.assertEqual(self.data["project"]["scripts"]["danza"],
                         "danzaboss.cli:main")

    def test_neon_extra_is_optional(self):
        self.assertEqual(self.data["project"]["optional-dependencies"]["neon"],
                         ["psycopg[binary]"])

    def test_version_is_dynamic_from_package(self):
        self.assertIn("version", self.data["project"]["dynamic"])
        self.assertEqual(
            self.data["tool"]["setuptools"]["dynamic"]["version"]["attr"],
            "danzaboss.__version__")

    def test_package_data_ships_all_runtime_assets(self):
        pkg_data = self.data["tool"]["setuptools"]["package-data"]
        self.assertIn("templates/**/*", pkg_data["danzaboss.product"])
        self.assertIn("static/*", pkg_data["danzaboss.cortex.ui"])
        self.assertIn("plan_schema.json", pkg_data["danzaboss.planning"])
        self.assertIn("spec_template.md", pkg_data["danzaboss.planning"])
        self.assertIn("templates/stacks/*.json", pkg_data["danzaboss.workstation"])
        self.assertIn("team_state.schema.json", pkg_data["danzaboss.kernel"])

    def test_tests_excluded_from_wheel(self):
        find = self.data["tool"]["setuptools"]["packages"]["find"]
        self.assertIn("danzaboss.tests*", find["exclude"])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/tre/dev/DANZA-OS && PYTHONPATH="$PWD:$PWD/danzaboss/tests" \
  DANZA_CORTEX_GLOBAL_DB="$(mktemp -d)/global.db" \
  python3 -m unittest discover -s danzaboss/tests -p 'test_product_packaging.py' -v
```

Expected: FAIL — `AttributeError: module 'danzaboss' has no attribute '__version__'` and `FileNotFoundError: pyproject.toml`.

- [ ] **Step 3: Write `danzaboss/__init__.py`**

```python
"""DANZABOSS — the promoted brain of DANZA-OS.

Single source of truth for the package version: pyproject.toml reads this
attribute via [tool.setuptools.dynamic], and scaffold.py stamps it into
.danza/.scaffold-version so `danza init --upgrade` (future) can diff.
"""
__version__ = "0.1.0"
```

- [ ] **Step 4: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "danza-os"
description = "DANZA-OS: a multi-AI development operating system - AI agents build your app under a fixed constitution."
requires-python = ">=3.10"
dependencies = []
dynamic = ["version"]

[project.urls]
Repository = "https://github.com/Aduson-Inc/DANZA-OS"

[project.optional-dependencies]
neon = ["psycopg[binary]"]

[project.scripts]
danza = "danzaboss.cli:main"

[tool.setuptools.dynamic]
version = { attr = "danzaboss.__version__" }

[tool.setuptools.packages.find]
include = ["danzaboss*"]
exclude = ["danzaboss.tests*"]

[tool.setuptools.package-data]
"danzaboss.product" = ["templates/**/*"]
"danzaboss.cortex.ui" = ["static/*"]
"danzaboss.planning" = ["plan_schema.json", "spec_template.md"]
"danzaboss.workstation" = ["templates/stacks/*.json"]
"danzaboss.kernel" = ["team_state.schema.json"]
```

(No `readme =` key: the repo has no `README.md` yet — Phase 6 adds it; referencing a missing file breaks the build.)

- [ ] **Step 5: Run test to verify it passes**

Same command as Step 2. Expected: PASS (all tests OK; skipped on 3.10).

- [ ] **Step 6: Smoke-check the build backend accepts the config**

```bash
cd /home/tre/dev/DANZA-OS && python3 -c "
from setuptools.config.pyprojecttoml import read_configuration
cfg = read_configuration('pyproject.toml')
print(cfg['project']['name'])"
```

Expected output: `danza-os` (no exception). If setuptools is too old to expose that module, `pip install --dry-run .` in a venv is the fallback check — the real install is proven in Task 9.

- [ ] **Step 7: Commit**

```bash
cd /home/tre/dev/DANZA-OS && git add pyproject.toml danzaboss/__init__.py danzaboss/tests/test_product_packaging.py
git commit -m "feat(product): pyproject packaging - danza-os with danza console script, zero deps

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Bundled scaffold payload

**Files:**
- Create: `danzaboss/product/__init__.py`
- Create: `danzaboss/product/templates/scaffold/claude/**` (agents ×8, constitution, skill, settings.json)
- Create: `danzaboss/product/templates/scaffold/danza/**` (19 bootstrap files)
- Create: `danzaboss/product/templates/claude-md-managed-block.md`
- Test: `danzaboss/tests/test_product_payload.py`

**Interfaces:**
- Produces: resource tree at `files("danzaboss.product") / "templates" / "scaffold"` with top-level dirs `claude/` and `danza/` (consumed by Task 3), and `templates/claude-md-managed-block.md` (consumed by Task 4).

- [ ] **Step 1: Write the failing test**

```python
"""Phase-1 T2 scaffold payload: the bundled .claude/.danza templates exist,
are reachable via importlib.resources, and stay byte-identical to the live
repo sources they were copied from.

Parity matters: the constitution/agents evolve in .claude/ (the authoritative
source); this test forces every such edit to consciously re-sync the shipped
payload instead of silently drifting. settings.json is intentionally NOT
parity-checked - the shipped one invokes the installed `danza` console script,
while the OS repo's uses PYTHONPATH module invocation.
"""
import json
import unittest
from importlib.resources import files
from pathlib import Path

import _bootstrap  # noqa

REPO = Path(__file__).resolve().parents[2]
PAYLOAD = files("danzaboss.product") / "templates" / "scaffold"

AGENTS = ["tony-d-orchestrator", "jonathan-builder", "samantha-mapper",
          "angela-auditor", "bonnie-qa", "carmella-researcher",
          "hank-designer", "billy-security"]

CLAUDE_PARITY = ([f"agents/{a}.md" for a in AGENTS]
                 + ["rules/constitution.md", "skills/danza/SKILL.md"])

DANZA_PARITY = ["audit-report-template.md", "build-history.md",
                "build-orders.md", "decision-log.md", "feature-list.md",
                "handoff.md", "onboarding-answers.md", "onboarding-misses.md",
                "onboarding-template.md", "patterns.md",
                "self-assessment-log.md", "stack-philosophy.md",
                "system-map.md", "turn-log.md", "checkpoints.json",
                "design-tokens.json", "rankings.json",
                "design/README.md", "onboarding/README.md"]


@unittest.skipUnless((REPO / ".claude").is_dir(),
                     "parity checks need the source repo")
class PayloadParity(unittest.TestCase):
    def test_claude_payload_matches_repo_source(self):
        for rel in CLAUDE_PARITY:
            with self.subTest(rel=rel):
                bundled = (PAYLOAD / "claude" / rel).read_bytes()
                source = (REPO / ".claude" / rel).read_bytes()
                self.assertEqual(bundled, source,
                                 f"payload drifted from .claude/{rel} - re-sync it")

    def test_danza_payload_matches_repo_source(self):
        for rel in DANZA_PARITY:
            with self.subTest(rel=rel):
                bundled = (PAYLOAD / "danza" / rel).read_bytes()
                source = (REPO / ".danza" / rel).read_bytes()
                self.assertEqual(bundled, source,
                                 f"payload drifted from .danza/{rel} - re-sync it")


class PayloadStructure(unittest.TestCase):
    def test_retired_agent_not_shipped(self):
        self.assertFalse(
            (PAYLOAD / "claude" / "agents" / "mona-historian.md").is_file(),
            "mona-historian is RETIRED and must not ship to new repos")

    def test_handoff_is_bootstrap(self):
        text = (PAYLOAD / "danza" / "handoff.md").read_text(encoding="utf-8")
        self.assertIn("No handoff yet.", text)

    def test_no_dotfiles_in_payload(self):
        def walk(node, rel=""):
            for child in node.iterdir():
                path = f"{rel}/{child.name}"
                self.assertFalse(child.name.startswith("."),
                                 f"dotfile in payload: {path}")
                if child.is_dir():
                    walk(child, path)
        walk(PAYLOAD)

    def test_settings_use_installed_console_script(self):
        raw = (PAYLOAD / "claude" / "settings.json").read_text(encoding="utf-8")
        settings = json.loads(raw)
        commands = [h["command"]
                    for group in settings["hooks"].values()
                    for entry in group
                    for h in entry["hooks"]]
        self.assertTrue(commands, "scaffolded settings.json wires no hooks")
        for cmd in commands:
            self.assertTrue(cmd.startswith("danza "),
                            f"scaffolded hook must call the danza console script: {cmd}")
        session_start = [c for c in commands if "session-start" in c]
        self.assertIn("danza hook session-start", session_start,
                      "D8 auto-resume hook missing from SessionStart")
        self.assertIn("danza cortex hook session-start", session_start,
                      "CORTEX injection hook missing from SessionStart")

    def test_managed_block_template_exists(self):
        body = (files("danzaboss.product") / "templates"
                / "claude-md-managed-block.md").read_text(encoding="utf-8")
        self.assertIn("Who's the Boss?", body)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/tre/dev/DANZA-OS && PYTHONPATH="$PWD:$PWD/danzaboss/tests" \
  DANZA_CORTEX_GLOBAL_DB="$(mktemp -d)/global.db" \
  python3 -m unittest discover -s danzaboss/tests -p 'test_product_payload.py' -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'danzaboss.product'`.

- [ ] **Step 3: Create the package marker and copy the payload**

`danzaboss/product/__init__.py`:

```python
"""Product layer - packaging & lifecycle (danza init / danza doctor).

Everything that turns the tested danzaboss libraries into an installable
product lives here: the bundled scaffold payload, the idempotent scaffolder,
the doctor health check, and the auto-resume session hook.
"""
```

Copy commands (run from repo root; explicit file lists — nothing is deleted, retired files are simply not copied):

```bash
cd /home/tre/dev/DANZA-OS
P=danzaboss/product/templates/scaffold
mkdir -p $P/claude/agents $P/claude/rules $P/claude/skills/danza \
         $P/danza/design $P/danza/onboarding
for a in tony-d-orchestrator jonathan-builder samantha-mapper angela-auditor \
         bonnie-qa carmella-researcher hank-designer billy-security; do
  cp .claude/agents/$a.md $P/claude/agents/
done
cp .claude/rules/constitution.md $P/claude/rules/
cp .claude/skills/danza/SKILL.md $P/claude/skills/danza/
for f in audit-report-template.md build-history.md build-orders.md \
         decision-log.md feature-list.md handoff.md onboarding-answers.md \
         onboarding-misses.md onboarding-template.md patterns.md \
         self-assessment-log.md stack-philosophy.md system-map.md \
         turn-log.md checkpoints.json design-tokens.json rankings.json; do
  cp .danza/$f $P/danza/
done
cp .danza/design/README.md $P/danza/design/
cp .danza/onboarding/README.md $P/danza/onboarding/
```

- [ ] **Step 4: Write `danzaboss/product/templates/scaffold/claude/settings.json`**

This is the one intentional divergence from the OS repo's `.claude/settings.json`: an activated repo has `danza` on PATH (pipx), so hooks call the console script, and SessionStart additionally wires the D8 auto-resume hook (implemented in Task 5).

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|Bash",
        "hooks": [
          { "type": "command", "command": "danza hook pretooluse" }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          { "type": "command", "command": "danza hook session-start" },
          { "type": "command", "command": "danza cortex hook session-start" }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit|Bash",
        "hooks": [
          { "type": "command", "command": "danza cortex hook post-tool-use" }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "danza cortex hook stop" }
        ]
      }
    ]
  }
}
```

- [ ] **Step 5: Write `danzaboss/product/templates/claude-md-managed-block.md`**

The block body appended to the target repo's `CLAUDE.md` (markers are added by `scaffold.py`, not stored here):

```markdown
## DANZA-OS

This repo is DANZA-activated: a multi-AI development operating system builds
this app under a fixed constitution.

- **Activate / take a turn:** say **"Who's the Boss?"**
- **Unbreakable rules:** `.claude/rules/constitution.md` (read every session)
- **Turn baton / mode detection:** `.danza/handoff.md` ("No handoff yet." = new project)
- **Machine turn state:** `.danza/runtime/team-state.json`
- **Health check:** `danza doctor`
```

- [ ] **Step 6: Run test to verify it passes**

Same command as Step 2. Expected: PASS (all subTests green, no dotfiles, retired agent absent).

- [ ] **Step 7: Commit**

```bash
cd /home/tre/dev/DANZA-OS && git add danzaboss/product/ danzaboss/tests/test_product_payload.py
git commit -m "feat(product): bundled scaffold payload (.claude + .danza templates) with parity tests

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Scaffold engine (`scaffold.py`)

**Files:**
- Create: `danzaboss/product/scaffold.py`
- Test: `danzaboss/tests/test_product_scaffold.py`

**Interfaces:**
- Consumes: payload tree from Task 2; `danzaboss.__version__` from Task 1.
- Produces: `scaffold(target: str | os.PathLike) -> list[FileResult]`; `FileResult(path: str, status: str, reason: str = "")` with `status ∈ {"created", "merged", "skipped"}` and `reason ∈ {"", "up-to-date", "user-modified"}`; `ScaffoldError(ValueError)`; constants `SCAFFOLD_VERSION_RELPATH`, `CLAUDE_MD_BEGIN`, `CLAUDE_MD_END`. (CLI Task 7 and doctor Task 6 import these.)

CLAUDE.md merging is deferred to Task 4 — in this task `scaffold()` handles only the payload copy, generated `.gitkeep` files, and the manifest stamp.

- [ ] **Step 1: Write the failing test**

```python
"""Phase-1 T3 scaffold engine: idempotent copy of the bundled payload into a
target repo. Rules 34-35 encoded: a user-edited file is never overwritten;
re-runs report skipped, not re-created.
"""
import json
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
import danzaboss
from danzaboss.product.scaffold import (ScaffoldError, FileResult, scaffold,
                                        SCAFFOLD_VERSION_RELPATH)


class ScaffoldFreshTarget(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.results = scaffold(self.root)
        self.by_path = {r.path: r for r in self.results}

    def test_all_payload_files_created(self):
        payload = [r for r in self.results if r.path != "CLAUDE.md"]
        self.assertTrue(payload)
        for r in payload:
            self.assertEqual((r.status, r.reason), ("created", ""),
                             f"{r.path} not created on fresh target")

    def test_key_files_land_in_dotted_dirs(self):
        for rel in (".claude/rules/constitution.md",
                    ".claude/agents/tony-d-orchestrator.md",
                    ".claude/settings.json",
                    ".danza/handoff.md"):
            self.assertTrue((self.root / rel).is_file(), rel)

    def test_empty_runtime_dirs_created_with_gitkeep(self):
        self.assertTrue((self.root / ".danza" / "logs" / ".gitkeep").is_file())
        self.assertTrue((self.root / ".danza" / "runtime" / ".gitkeep").is_file())
        self.assertEqual(self.by_path[".danza/logs/.gitkeep"].status, "created")

    def test_manifest_stamped(self):
        manifest = json.loads(
            (self.root / SCAFFOLD_VERSION_RELPATH).read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], danzaboss.__version__)
        self.assertIn(".claude/rules/constitution.md", manifest["files"])
        for digest in manifest["files"].values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_results_are_deterministically_sorted(self):
        paths = [r.path for r in self.results if r.path != "CLAUDE.md"]
        self.assertEqual(paths, sorted(paths))


class ScaffoldRerun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        scaffold(self.root)

    def test_rerun_skips_everything_up_to_date(self):
        for r in scaffold(self.root):
            if r.path == "CLAUDE.md":
                continue
            self.assertEqual((r.status, r.reason), ("skipped", "up-to-date"),
                             f"{r.path} must skip on identical re-run")

    def test_user_edit_is_never_overwritten(self):
        handoff = self.root / ".danza" / "handoff.md"
        user_text = "# Handoff\n\nTurn 3: codex -> claude. Build features 5+6.\n"
        handoff.write_text(user_text, encoding="utf-8")
        results = {r.path: r for r in scaffold(self.root)}
        self.assertEqual(results[".danza/handoff.md"].status, "skipped")
        self.assertEqual(results[".danza/handoff.md"].reason, "user-modified")
        self.assertEqual(handoff.read_text(encoding="utf-8"), user_text,
                         "Rule 35 violation: user edit was clobbered")


class ScaffoldErrors(unittest.TestCase):
    def test_missing_target_raises(self):
        with self.assertRaises(ScaffoldError):
            scaffold("/nonexistent/definitely/not/a/dir")

    def test_target_is_file_raises(self):
        with tempfile.NamedTemporaryFile() as fh:
            with self.assertRaises(ScaffoldError):
                scaffold(fh.name)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/tre/dev/DANZA-OS && PYTHONPATH="$PWD:$PWD/danzaboss/tests" \
  DANZA_CORTEX_GLOBAL_DB="$(mktemp -d)/global.db" \
  python3 -m unittest discover -s danzaboss/tests -p 'test_product_scaffold.py' -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'danzaboss.product.scaffold'`.

- [ ] **Step 3: Write `danzaboss/product/scaffold.py`**

```python
"""danza init - idempotent scaffold of .claude/ + .danza/ into a target repo.

An activated repo gets its own COPIES of the DANZA system files (agents,
constitution, skills, hook settings) and bootstrap state - copies, not
symlinks, so activated repos survive OS upgrades (spec D1). The scaffold is
idempotent and encodes Rules 34-35: templates and state are never blind-
overwritten; every file lands as created, merged, or skipped with a reason,
and a user-edited file is never touched.

.danza/.scaffold-version records the package version and the sha256 of every
bundled file at scaffold time, so a future `danza init --upgrade` can diff
what the user changed against what the OS changed.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import danzaboss

SCAFFOLD_VERSION_RELPATH = Path(".danza") / ".scaffold-version"
CLAUDE_MD_BEGIN = ("<!-- DANZA:BEGIN managed by `danza init` "
                   "- do not edit inside this block -->")
CLAUDE_MD_END = "<!-- DANZA:END -->"

# payload dir name -> target dir name. Dotted names never appear inside the
# bundled payload (packaging globs and resource walkers skip dotfiles
# unreliably), so the mapping happens here at copy time.
_PAYLOAD_DIRS = {"claude": ".claude", "danza": ".danza"}

# runtime dirs the product needs but that ship empty: represented by generated
# .gitkeep entries rather than payload files (no dotfiles in package data).
_KEEP_FILES = (Path(".danza") / "logs" / ".gitkeep",
               Path(".danza") / "runtime" / ".gitkeep")


class ScaffoldError(ValueError):
    """Unusable target directory or missing/corrupt bundled payload."""


@dataclass(frozen=True)
class FileResult:
    """Outcome for one scaffolded file (repo-relative POSIX path)."""
    path: str
    status: str        # "created" | "merged" | "skipped"
    reason: str = ""   # "" | "up-to-date" | "user-modified"


def _payload_root():
    root = files("danzaboss.product") / "templates" / "scaffold"
    if not root.is_dir():
        raise ScaffoldError(
            "bundled scaffold payload missing - broken installation; "
            "reinstall danza-os")
    return root


def _walk(node, rel: Path):
    """Yield (relative Path, bytes) for every file under a Traversable."""
    for child in node.iterdir():
        if child.is_dir():
            yield from _walk(child, rel / child.name)
        else:
            yield rel / child.name, child.read_bytes()


def _iter_payload():
    """Every file the scaffold owns: (target-relative Path, content bytes),
    deterministically sorted. Includes the generated .gitkeep entries."""
    entries: list[tuple[Path, bytes]] = []
    root = _payload_root()
    for src_name, dst_name in _PAYLOAD_DIRS.items():
        base = root / src_name
        if not base.is_dir():
            raise ScaffoldError(f"payload dir {src_name!r} missing - broken install")
        entries.extend((Path(dst_name) / rel, content)
                       for rel, content in _walk(base, Path()))
    entries.extend((keep, b"") for keep in _KEEP_FILES)
    return sorted(entries, key=lambda e: e[0].as_posix())


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_manifest(target: Path, entries) -> None:
    """Atomic write (tmp -> os.replace), same idiom as runners.save_runners."""
    manifest = {"version": danzaboss.__version__,
                "files": {rel.as_posix(): _sha256(content)
                          for rel, content in entries}}
    path = target / SCAFFOLD_VERSION_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, path)


def scaffold(target: str | os.PathLike) -> list[FileResult]:
    """Copy/merge the bundled payload into *target*. Returns one FileResult
    per file. Never overwrites a file that differs from the bundle (Rule 35);
    identical files skip as up-to-date, so re-runs are no-ops."""
    root = Path(target)
    if not root.is_dir():
        raise ScaffoldError(f"target is not a directory: {root}")

    entries = _iter_payload()
    results: list[FileResult] = []
    for rel, content in entries:
        dst = root / rel
        posix = rel.as_posix()
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(content)
            results.append(FileResult(posix, "created"))
        elif dst.read_bytes() == content:
            results.append(FileResult(posix, "skipped", "up-to-date"))
        else:
            results.append(FileResult(posix, "skipped", "user-modified"))

    results.append(_merge_claude_md(root))
    _write_manifest(root, entries)
    return results


def _merge_claude_md(root: Path) -> FileResult:
    """Placeholder until Task 4: report CLAUDE.md untouched."""
    return FileResult("CLAUDE.md", "skipped", "up-to-date")
```

- [ ] **Step 4: Run test to verify it passes**

Same command as Step 2. Expected: PASS (10 tests OK).

- [ ] **Step 5: Commit**

```bash
cd /home/tre/dev/DANZA-OS && git add danzaboss/product/scaffold.py danzaboss/tests/test_product_scaffold.py
git commit -m "feat(product): idempotent scaffold engine with created/merged/skipped reporting

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: CLAUDE.md managed block

**Files:**
- Modify: `danzaboss/product/scaffold.py` (replace the `_merge_claude_md` placeholder)
- Test: extend `danzaboss/tests/test_product_scaffold.py`

**Interfaces:**
- Consumes: `templates/claude-md-managed-block.md` (Task 2); `CLAUDE_MD_BEGIN`/`CLAUDE_MD_END` constants (Task 3).
- Produces: `scaffold()` results now include a real `CLAUDE.md` entry: `created` (file absent), `merged` (block appended or refreshed), `skipped/up-to-date` (block current). Corrupt markers → `ScaffoldError`.

- [ ] **Step 1: Add failing tests to `test_product_scaffold.py`**

```python
from danzaboss.product.scaffold import CLAUDE_MD_BEGIN, CLAUDE_MD_END


class ClaudeMdManagedBlock(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.claude_md = self.root / "CLAUDE.md"

    def _result(self):
        return {r.path: r for r in scaffold(self.root)}["CLAUDE.md"]

    def test_absent_file_is_created_with_block(self):
        res = self._result()
        self.assertEqual(res.status, "created")
        text = self.claude_md.read_text(encoding="utf-8")
        self.assertIn(CLAUDE_MD_BEGIN, text)
        self.assertIn(CLAUDE_MD_END, text)
        self.assertIn("Who's the Boss?", text)

    def test_existing_file_gets_block_appended_user_text_preserved(self):
        self.claude_md.write_text("# My App\n\nUser notes.\n", encoding="utf-8")
        res = self._result()
        self.assertEqual(res.status, "merged")
        text = self.claude_md.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# My App"),
                        "user content must stay first and intact")
        self.assertIn("User notes.", text)
        self.assertIn(CLAUDE_MD_BEGIN, text)

    def test_rerun_with_current_block_skips(self):
        scaffold(self.root)
        self.assertEqual((self._result().status, self._result().reason),
                         ("skipped", "up-to-date"))

    def test_stale_block_is_refreshed_in_place(self):
        scaffold(self.root)
        text = self.claude_md.read_text(encoding="utf-8")
        pre, rest = text.split(CLAUDE_MD_BEGIN, 1)
        _, post = rest.split(CLAUDE_MD_END, 1)
        stale = (pre + CLAUDE_MD_BEGIN + "\nold contents\n"
                 + CLAUDE_MD_END + post)
        self.claude_md.write_text("USER HEADER\n" + stale, encoding="utf-8")
        res = self._result()
        self.assertEqual(res.status, "merged")
        refreshed = self.claude_md.read_text(encoding="utf-8")
        self.assertTrue(refreshed.startswith("USER HEADER"))
        self.assertNotIn("old contents", refreshed)
        self.assertIn("Who's the Boss?", refreshed)
        self.assertEqual(refreshed.count(CLAUDE_MD_BEGIN), 1,
                         "block must be replaced, not duplicated")

    def test_corrupt_markers_fail_closed(self):
        self.claude_md.write_text(f"# App\n{CLAUDE_MD_BEGIN}\nno end marker\n",
                                  encoding="utf-8")
        with self.assertRaises(ScaffoldError):
            scaffold(self.root)
```

- [ ] **Step 2: Run tests to verify the new ones fail**

```bash
cd /home/tre/dev/DANZA-OS && PYTHONPATH="$PWD:$PWD/danzaboss/tests" \
  DANZA_CORTEX_GLOBAL_DB="$(mktemp -d)/global.db" \
  python3 -m unittest discover -s danzaboss/tests -p 'test_product_scaffold.py' -v
```

Expected: 4 FAIL / ERROR (`test_absent_file_is_created_with_block` etc. — placeholder always reports skipped), existing tests still PASS.

- [ ] **Step 3: Replace `_merge_claude_md` in `scaffold.py`**

```python
def _managed_block() -> str:
    body = (files("danzaboss.product") / "templates"
            / "claude-md-managed-block.md").read_text(encoding="utf-8").strip()
    return f"{CLAUDE_MD_BEGIN}\n{body}\n{CLAUDE_MD_END}"


def _merge_claude_md(root: Path) -> FileResult:
    """Create CLAUDE.md or maintain the DANZA managed block inside it.

    Only the text between the BEGIN/END markers is ever rewritten - the
    user's own CLAUDE.md content is untouchable (Rule 35). One marker
    without the other means a hand-mangled block: fail closed rather than
    guess where the user's content ends."""
    path = root / "CLAUDE.md"
    block = _managed_block()
    if not path.exists():
        path.write_text(block + "\n", encoding="utf-8")
        return FileResult("CLAUDE.md", "created")

    text = path.read_text(encoding="utf-8")
    has_begin, has_end = CLAUDE_MD_BEGIN in text, CLAUDE_MD_END in text
    if has_begin != has_end:
        raise ScaffoldError(
            "CLAUDE.md managed block markers are corrupt (found one of "
            "BEGIN/END but not the other) - repair the block by hand, "
            "then re-run danza init")
    if has_begin:
        pre, rest = text.split(CLAUDE_MD_BEGIN, 1)
        inner, post = rest.split(CLAUDE_MD_END, 1)
        del inner  # replaced wholesale - it is machine-owned text
        merged = pre + block + post
        if merged == text:
            return FileResult("CLAUDE.md", "skipped", "up-to-date")
        path.write_text(merged, encoding="utf-8")
        return FileResult("CLAUDE.md", "merged")

    appended = text.rstrip("\n") + "\n\n" + block + "\n"
    path.write_text(appended, encoding="utf-8")
    return FileResult("CLAUDE.md", "merged")
```

- [ ] **Step 4: Run tests to verify all pass**

Same command as Step 2. Expected: PASS (15 tests OK).

- [ ] **Step 5: Commit**

```bash
cd /home/tre/dev/DANZA-OS && git add danzaboss/product/scaffold.py danzaboss/tests/test_product_scaffold.py
git commit -m "feat(product): CLAUDE.md managed block merge (create/append/refresh, fail-closed markers)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Auto-resume SessionStart hook (D8)

**Files:**
- Create: `danzaboss/product/resume.py`
- Modify: `danzaboss/cli.py` (`_cmd_hook`: handle `session-start`; docstring)
- Test: `danzaboss/tests/test_product_resume.py`

**Interfaces:**
- Produces: `session_start_context(root: str | os.PathLike = ".") -> str | None` — CONTINUE-MODE context block, or `None` when there is nothing to resume. CLI event `danza hook session-start` emits the Claude Code `SessionStart` `additionalContext` JSON (exactly the shape `cortex/commands.py::_hook_session_start` uses) and always exits 0.

- [ ] **Step 1: Write the failing test**

```python
"""Phase-1 T5 auto-resume hook (D8): a fresh session in an activated repo
with a real handoff gets a CONTINUE MODE context block; everything else
stays silent. The hook is read-only and fails open.
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.cli import main
from danzaboss.product.resume import session_start_context


class SessionStartContext(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _write_handoff(self, text):
        d = self.root / ".danza"
        d.mkdir(exist_ok=True)
        (d / "handoff.md").write_text(text, encoding="utf-8")

    def test_no_danza_dir_is_silent(self):
        self.assertIsNone(session_start_context(self.root))

    def test_bootstrap_handoff_is_silent(self):
        self._write_handoff("# Handoff\n\nNo handoff yet.\n")
        self.assertIsNone(session_start_context(self.root))

    def test_blank_handoff_is_silent(self):
        self._write_handoff("   \n\n")
        self.assertIsNone(session_start_context(self.root))

    def test_real_handoff_emits_continue_block(self):
        self._write_handoff("# Handoff\n\nTurn 4: claude -> codex. "
                            "Features 7+8 next.\n")
        block = session_start_context(self.root)
        self.assertIsNotNone(block)
        self.assertIn("CONTINUE MODE", block)
        self.assertIn("Who's the Boss?", block)
        self.assertIn(".danza/handoff.md", block)


class SessionStartCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self._old_cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self._old_cwd)

    def test_activated_repo_prints_session_start_json(self):
        d = self.root / ".danza"
        d.mkdir()
        (d / "handoff.md").write_text("# Handoff\n\nTurn 2: resume.\n",
                                      encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            rc = main(["hook", "session-start"])
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        hso = payload["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "SessionStart")
        self.assertIn("CONTINUE MODE", hso["additionalContext"])

    def test_unactivated_repo_prints_nothing_and_exits_zero(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = main(["hook", "session-start"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.getvalue(), "")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/tre/dev/DANZA-OS && PYTHONPATH="$PWD:$PWD/danzaboss/tests" \
  DANZA_CORTEX_GLOBAL_DB="$(mktemp -d)/global.db" \
  python3 -m unittest discover -s danzaboss/tests -p 'test_product_resume.py' -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'danzaboss.product.resume'`.

- [ ] **Step 3: Write `danzaboss/product/resume.py`**

```python
"""Auto-resume SessionStart hook (spec D8, borrowed from GSD's session-start
pattern).

Why: in an activated repo a relay may be mid-flight. A fresh AI session that
does not know this will treat the repo as new work and violate the turn lock.
If .danza/handoff.md holds real handoff data (anything beyond the bootstrap
"No handoff yet."), we hand the session a CONTINUE MODE pointer at the
required reading (Rule 44: pointers, not briefings). Read-only: this hook
never mutates state, and its CLI wrapper fails open.
"""
from __future__ import annotations

import os
from pathlib import Path

HANDOFF_RELPATH = Path(".danza") / "handoff.md"
_BOOTSTRAP_MARKER = "No handoff yet."

_CONTINUE_BLOCK = (
    "CONTINUE MODE - a DANZA relay is in flight in this repo.\n"
    "Resume via the trigger phrase: \"Who's the Boss?\"\n"
    "Required reading before any work: .danza/handoff.md, "
    ".danza/runtime/team-state.json, .claude/rules/constitution.md."
)


def session_start_context(root: str | os.PathLike = ".") -> str | None:
    """CONTINUE-MODE context block, or None when there is nothing to resume
    (missing/unreadable handoff, blank file, or the bootstrap marker)."""
    try:
        text = (Path(root) / HANDOFF_RELPATH).read_text(encoding="utf-8")
    except OSError:
        return None  # not an activated repo -> stay silent
    if not text.strip() or _BOOTSTRAP_MARKER in text:
        return None
    return _CONTINUE_BLOCK
```

- [ ] **Step 4: Wire the event in `danzaboss/cli.py`**

Add the import near the other workstation imports (after the `from .workstation.conductor import ...` line):

```python
from .product.resume import session_start_context
```

In `_cmd_hook`, insert the new branch as the FIRST statement of the function — **before** the `payload = json.load(sys.stdin)...` line. Placement is load-bearing: the existing stdin parse fails open by emitting a PreToolUse "allow" JSON, so if session-start were handled after it, an empty non-tty stdin would print that allow JSON and never reach this branch (and session-start needs no payload anyway):

```python
def _cmd_hook(argv: list[str]) -> int:
    event = argv[0] if argv else "pretooluse"

    if event in ("session-start", "SessionStart"):
        # D8 auto-resume: read-only pointer at the in-flight relay. Needs no
        # stdin payload, so it dispatches before the payload parse (whose
        # fail-open path emits PreToolUse JSON that would corrupt this event).
        # Fail open - a resume-hook bug must never block a session start.
        try:
            block = session_start_context(os.getcwd())
        except Exception:
            return 0
        if block:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "SessionStart", "additionalContext": block}}))
        return 0

    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        return _emit("allow")  # unreadable input -> fail open
    # ... rest of the existing function body unchanged (stop branch, PreToolUse)
```

Update the module docstring's hook line from
`danzaboss.cli hook stop  Claude Code Stop hook` style to include:

```
  danzaboss.cli hook session-start             D8 auto-resume: CONTINUE-MODE context block
```

- [ ] **Step 5: Run test to verify it passes**

Same command as Step 2. Expected: PASS (6 tests OK). Also run the existing hook tests to prove no regression:

```bash
cd /home/tre/dev/DANZA-OS && PYTHONPATH="$PWD:$PWD/danzaboss/tests" \
  DANZA_CORTEX_GLOBAL_DB="$(mktemp -d)/global.db" \
  python3 -m unittest discover -s danzaboss/tests -p 'test_cli_hook.py' -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/tre/dev/DANZA-OS && git add danzaboss/product/resume.py danzaboss/cli.py danzaboss/tests/test_product_resume.py
git commit -m "feat(product): D8 auto-resume SessionStart hook (danza hook session-start)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Doctor (`doctor.py`)

**Files:**
- Create: `danzaboss/product/doctor.py`
- Test: `danzaboss/tests/test_product_doctor.py`

**Interfaces:**
- Consumes: `Report` from `danzaboss.selftest.harness` (has `.add(name, passed, detail)`, `.ok`, `.checks`, `.to_dict()`); `run_cold_start()`; `active_profile(root, env)` from `kernel.profile`; `detect_runners(which)` from `workstation.runners`; `db_path(root)` from `cortex.factory`; `SCAFFOLD_VERSION_RELPATH` from Task 3.
- Produces: `run_doctor(root=".", which=shutil.which, env=None) -> Report` with checks named `python_version`, `git_repo`, `scaffold`, `profile`, `runners`, `cortex`, `selftest`. (CLI Task 7 renders it.)

Check semantics (D9 decoded):
- *Activated* means `.danza/runtime/team-state.json` exists — the kernel writes it at activation (Rule 45). The scaffold stamp alone means "installed, awaiting first activation": profile legitimately resolves OS_DEV there, so CORTEX dormancy is only a FAILURE when team-state exists **and** the resolved profile's `memory_level == "none"` (someone forced OS_DEV in a live repo).
- When the profile is a runtime one (`OS_BOOT_TEST`/`APP_BUILD`), the CORTEX store must be writable: probe by connecting sqlite to `db_path(root)` (creating parent dirs). Any `OSError`/`sqlite3.Error` → FAIL.
- `scaffold` check: no stamp + no team-state → PASS "not an activated repo"; stamp present → every manifest file must exist; stamp unreadable → FAIL (fail closed); team-state present without stamp → PASS with "pre-product activation" detail (informational — legacy activations predate `danza init`).
- `runners` is informational (never fails): detection summary string; conduct-time code fails loudly on its own.

- [ ] **Step 1: Write the failing test**

```python
"""Phase-1 T6 doctor: env + activation health checks. Injected `which` and
`env` keep every test hermetic - no real runner binaries or global profile
state leak in.
"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.product.doctor import run_doctor
from danzaboss.product.scaffold import scaffold, SCAFFOLD_VERSION_RELPATH

_NO_ENV = {}          # blocks DANZABOSS_PROFILE leaking from the real env
_WHICH_NONE = lambda name: None
_WHICH_CLAUDE = lambda name: "/usr/bin/claude" if name == "claude" else None


def _check(report, name):
    return next(c for c in report.checks if c.name == name)


class DoctorFreshDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_non_git_dir_fails_git_check(self):
        rep = run_doctor(self.root, which=_WHICH_NONE, env=_NO_ENV)
        self.assertFalse(_check(rep, "git_repo").passed)
        self.assertFalse(rep.ok)

    def test_unscaffolded_source_tree_passes_scaffold_check(self):
        rep = run_doctor(self.root, which=_WHICH_NONE, env=_NO_ENV)
        self.assertTrue(_check(rep, "scaffold").passed)


class DoctorScaffoldedRepo(unittest.TestCase):
    """The `danza init` acceptance state: scaffolded + git, not yet activated."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / ".git").mkdir()          # doctor checks presence, not validity
        scaffold(self.root)

    def test_green_end_to_end(self):
        rep = run_doctor(self.root, which=_WHICH_CLAUDE, env=_NO_ENV)
        self.assertTrue(rep.ok, json.dumps(rep.to_dict(), indent=2))

    def test_runners_summary_is_informational(self):
        rep = run_doctor(self.root, which=_WHICH_NONE, env=_NO_ENV)
        runners = _check(rep, "runners")
        self.assertTrue(runners.passed)
        self.assertIn("claude: not found", runners.detail)

    def test_missing_scaffold_file_fails_integrity(self):
        (self.root / ".danza" / "handoff.md").unlink()
        rep = run_doctor(self.root, which=_WHICH_CLAUDE, env=_NO_ENV)
        check = _check(rep, "scaffold")
        self.assertFalse(check.passed)
        self.assertIn("handoff.md", check.detail)

    def test_corrupt_manifest_fails_closed(self):
        (self.root / SCAFFOLD_VERSION_RELPATH).write_text("{not json",
                                                          encoding="utf-8")
        rep = run_doctor(self.root, which=_WHICH_CLAUDE, env=_NO_ENV)
        self.assertFalse(_check(rep, "scaffold").passed)


class DoctorCortexD9(unittest.TestCase):
    """CORTEX is load-bearing: dormant-in-activated-repo and unwritable-store
    are failures, not warnings."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / ".git").mkdir()
        scaffold(self.root)
        runtime = self.root / ".danza" / "runtime"
        (runtime / "team-state.json").write_text("{}", encoding="utf-8")

    def test_activated_repo_with_runtime_profile_probes_store_writable(self):
        rep = run_doctor(self.root, which=_WHICH_CLAUDE, env=_NO_ENV)
        cortex = _check(rep, "cortex")
        self.assertTrue(cortex.passed, cortex.detail)

    def test_dormant_profile_in_activated_repo_fails(self):
        rep = run_doctor(self.root, which=_WHICH_CLAUDE,
                         env={"DANZABOSS_PROFILE": "OS_DEV"})
        cortex = _check(rep, "cortex")
        self.assertFalse(cortex.passed)
        self.assertIn("dormant", cortex.detail)

    def test_unwritable_store_fails(self):
        # a FILE where the cortex dir must go makes mkdir/connect raise
        (self.root / ".danza" / "cortex").write_text("", encoding="utf-8")
        rep = run_doctor(self.root, which=_WHICH_CLAUDE, env=_NO_ENV)
        self.assertFalse(_check(rep, "cortex").passed)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/tre/dev/DANZA-OS && PYTHONPATH="$PWD:$PWD/danzaboss/tests" \
  DANZA_CORTEX_GLOBAL_DB="$(mktemp -d)/global.db" \
  python3 -m unittest discover -s danzaboss/tests -p 'test_product_doctor.py' -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'danzaboss.product.doctor'`.

- [ ] **Step 3: Write `danzaboss/product/doctor.py`**

```python
"""danza doctor - environment + activation health checks (spec section 5).

Wraps the cold-start selftest and adds the product-level checks a fresh
install needs: interpreter floor, git repo, scaffold integrity, active
profile, runner detection, and CORTEX state. D9 makes CORTEX load-bearing:
in an activated repo (team-state.json present, Rule 45) a dormant CORTEX or
an unwritable store is a FAILURE, never a warning.

Reuses the selftest Report/Check shape so callers render both the same way.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

from danzaboss.cortex.factory import db_path
from danzaboss.kernel.profile import active_profile
from danzaboss.product.scaffold import SCAFFOLD_VERSION_RELPATH
from danzaboss.selftest.harness import Report, run_cold_start
from danzaboss.workstation.runners import detect_runners

_TEAM_STATE_RELPATH = Path(".danza") / "runtime" / "team-state.json"
_RUNTIME_PROFILES = ("OS_BOOT_TEST", "APP_BUILD")


def run_doctor(root: str | os.PathLike = ".",
               which=shutil.which, env: dict | None = None) -> Report:
    """Health-check *root*. `which` and `env` are injectable so tests never
    depend on the host's real binaries or environment variables."""
    r = Report()
    root = Path(root)

    ver = sys.version_info
    r.add("python_version", ver >= (3, 10),
          f"{ver.major}.{ver.minor}.{ver.micro} (need >= 3.10)")

    r.add("git_repo", (root / ".git").exists(),
          f"{root} {'is' if (root / '.git').exists() else 'is NOT'} a git repo")

    _check_scaffold(r, root)

    try:
        prof = active_profile(str(root), env=env)
    except ValueError as e:
        r.add("profile", False, str(e))
        return r  # profile-dependent checks below cannot run
    r.add("profile", True, prof.name)

    detected = detect_runners(which)
    summary = ", ".join(f"{n}: {'detected' if ok else 'not found'}"
                        for n, ok in detected.items())
    r.add("runners", True, summary)  # informational: conduct fails loudly itself

    _check_cortex(r, root, prof)

    cold = run_cold_start()
    d = cold.to_dict()
    r.add("selftest", cold.ok, f"cold-start {d['passed']}/{d['total']} checks")
    return r


def _check_scaffold(r: Report, root: Path) -> None:
    manifest_path = root / SCAFFOLD_VERSION_RELPATH
    activated = (root / _TEAM_STATE_RELPATH).exists()
    if not manifest_path.exists():
        if activated:
            r.add("scaffold", True,
                  "activated without scaffold stamp (pre-product activation)")
        else:
            r.add("scaffold", True, "not an activated repo (no scaffold stamp)")
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        recorded = manifest["files"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
        r.add("scaffold", False, f"unreadable .scaffold-version: {e}")
        return
    missing = [rel for rel in recorded if not (root / rel).exists()]
    if missing:
        r.add("scaffold", False,
              f"missing scaffold files: {', '.join(sorted(missing)[:5])}"
              + (" ..." if len(missing) > 5 else ""))
    else:
        r.add("scaffold", True,
              f"v{manifest.get('version', '?')}, {len(recorded)} files present")


def _check_cortex(r: Report, root: Path, prof) -> None:
    activated = (root / _TEAM_STATE_RELPATH).exists()
    if activated and prof.memory_level == "none":
        r.add("cortex", False,
              f"CORTEX dormant (memory_level=none) in an ACTIVATED repo - "
              f"profile {prof.name} is a Layer-0 profile; remove the override "
              f"(D9: CORTEX is load-bearing at runtime)")
        return
    if prof.name in _RUNTIME_PROFILES:
        db = Path(db_path(str(root)))
        try:
            db.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(db)
            try:
                con.execute("PRAGMA user_version")
            finally:
                con.close()
            r.add("cortex", True, f"store writable at {db}")
        except (OSError, sqlite3.Error) as e:
            r.add("cortex", False, f"CORTEX store unwritable at {db}: {e}")
        return
    r.add("cortex", True, f"dormant by design in {prof.name} (repo not activated)")
```

- [ ] **Step 4: Run test to verify it passes**

Same command as Step 2. Expected: PASS (9 tests OK).

- [ ] **Step 5: Commit**

```bash
cd /home/tre/dev/DANZA-OS && git add danzaboss/product/doctor.py danzaboss/tests/test_product_doctor.py
git commit -m "feat(product): danza doctor checks - env, git, scaffold integrity, profile, runners, CORTEX (D9), selftest

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: CLI wiring — `danza init` / `danza doctor`

**Files:**
- Modify: `danzaboss/cli.py` (new commands + `_COMMANDS` + usage strings)
- Test: `danzaboss/tests/test_product_cli.py`

**Interfaces:**
- Consumes: `scaffold`, `ScaffoldError` (Task 3/4); `run_doctor` (Task 6).
- Produces: `danza init [dir]` — prints one aligned line per FileResult, blank line, doctor report, next steps; exit = doctor's (0 green / 1 red), 2 on `ScaffoldError`. `danza doctor [dir]` — prints the report; exit 0/1.

- [ ] **Step 1: Write the failing test**

```python
"""Phase-1 T7 CLI wiring: `danza init` and `danza doctor` through the real
dispatch path (cli.main in-process), stdout captured. `which` cannot be
injected through the CLI, so assertions avoid claims about which runners the
host has - same policy as test_workstation_cli.py.
"""
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.cli import main


class InitCmd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / ".git").mkdir()   # keeps the doctor tail green

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_init_scaffolds_reports_and_health_checks(self):
        rc, out, _ = self._run("init", str(self.root))
        self.assertEqual(rc, 0, out)
        self.assertIn("created", out)
        self.assertIn(".claude/rules/constitution.md", out)
        self.assertIn("[PASS] scaffold", out)
        self.assertIn("Next steps", out)
        self.assertIn("Who's the Boss?", out)
        self.assertTrue((self.root / ".danza" / "handoff.md").is_file())

    def test_rerun_reports_all_skipped(self):
        self._run("init", str(self.root))
        rc, out, _ = self._run("init", str(self.root))
        self.assertEqual(rc, 0)
        file_lines = [l for l in out.splitlines()
                      if l.startswith(("created", "merged", "skipped"))]
        self.assertTrue(file_lines, "no file-result lines printed")
        self.assertTrue(all(l.startswith("skipped") for l in file_lines),
                        f"second init must create/merge nothing:\n{out}")
        self.assertIn("up-to-date", out)

    def test_bad_target_exits_2(self):
        rc, _, err = self._run("init", "/nonexistent/nope")
        self.assertEqual(rc, 2)
        self.assertIn("not a directory", err)


class DoctorCmd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _run(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = main(list(argv))
        return rc, out.getvalue()

    def test_red_on_non_git_dir(self):
        rc, out = self._run("doctor", str(self.root))
        self.assertEqual(rc, 1)
        self.assertIn("[FAIL] git_repo", out)

    def test_green_on_scaffolded_git_repo(self):
        (self.root / ".git").mkdir()
        main(["init", str(self.root)])
        rc, out = self._run("doctor", str(self.root))
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] python_version", out)
        self.assertIn("[PASS] cortex", out)
        self.assertIn("doctor: green", out)


class UsageLine(unittest.TestCase):
    def test_unknown_command_usage_mentions_init_and_doctor(self):
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["bogus"])
        self.assertEqual(rc, 2)
        self.assertIn("init", err.getvalue())
        self.assertIn("doctor", err.getvalue())
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/tre/dev/DANZA-OS && PYTHONPATH="$PWD:$PWD/danzaboss/tests" \
  DANZA_CORTEX_GLOBAL_DB="$(mktemp -d)/global.db" \
  python3 -m unittest discover -s danzaboss/tests -p 'test_product_cli.py' -v
```

Expected: FAIL — rc 2 / "usage" for every test (`init`/`doctor` unknown commands).

- [ ] **Step 3: Wire the commands in `danzaboss/cli.py`**

Imports (with the other package imports):

```python
from .product.doctor import run_doctor
from .product.scaffold import ScaffoldError, scaffold
```

New command functions (place after `_cmd_conduct`):

```python
def _print_doctor(root: str) -> int:
    """Render a doctor Report as [PASS]/[FAIL] lines + verdict. 0 green, 1 red."""
    rep = run_doctor(root)
    for c in rep.checks:
        mark = "PASS" if c.passed else "FAIL"
        print(f"[{mark}] {c.name}: {c.detail}")
    d = rep.to_dict()
    print(f"doctor: {'green' if rep.ok else 'RED'} "
          f"({d['passed']}/{d['total']} checks)")
    return 0 if rep.ok else 1


def _cmd_doctor(argv: list[str]) -> int:
    """danza doctor [dir] - env + activation health checks."""
    return _print_doctor(argv[0] if argv else ".")


def _cmd_init(argv: list[str]) -> int:
    """danza init [dir] - scaffold .claude/ + .danza/, then health-check.

    Exit code: 2 on scaffold failure, otherwise the doctor's verdict - the
    scaffold may be fine while the environment is not (e.g. no git repo),
    and the user should see that immediately, not at first build."""
    target = argv[0] if argv else "."
    try:
        results = scaffold(target)
    except ScaffoldError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for res in results:
        suffix = f" ({res.reason})" if res.reason else ""
        print(f"{res.status:<8} {res.path}{suffix}")
    print()
    rc = _print_doctor(target)
    print()
    print("Next steps:")
    print("  1. cd into the repo and open your AI CLI (claude, codex, ...)")
    print("  2. Say \"Who's the Boss?\" to activate the orchestrator")
    print("  3. Re-check health any time with: danza doctor")
    return rc
```

Register them:

```python
_COMMANDS = {"scan": _cmd_scan, "verify": _cmd_verify,
             "selftest": _cmd_selftest, "hook": _cmd_hook,
             "cortex": _cmd_cortex, "profile": _cmd_profile,
             "tier": _cmd_tier, "runners": _cmd_runners,
             "conduct": _cmd_conduct, "init": _cmd_init,
             "doctor": _cmd_doctor}
```

Update the `main()` usage line to
`"danzaboss.cli <scan|verify|selftest|hook|cortex|profile|tier|runners|conduct|init|doctor> ..."`
and add to the module docstring:

```
  danzaboss.cli init [dir]                      scaffold .claude/ + .danza/ into a repo (danza init)
  danzaboss.cli doctor [dir]                    env + activation health checks (danza doctor)
```

- [ ] **Step 4: Run test to verify it passes**

Same command as Step 2. Expected: PASS (6 tests OK).

- [ ] **Step 5: Run the full suite (tier: package-wide CLI change)**

```bash
cd /home/tre/dev/DANZA-OS && ./danzaboss/run_tests.sh 2>&1 | tail -5
```

Expected: `OK` with 733 + new tests, 0 failures.

- [ ] **Step 6: Commit**

```bash
cd /home/tre/dev/DANZA-OS && git add danzaboss/cli.py danzaboss/tests/test_product_cli.py
git commit -m "feat(product): wire danza init + danza doctor CLI commands

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: `install.sh`

**Files:**
- Create: `install.sh` (repo root)
- Test: `danzaboss/tests/test_product_install_sh.py`

**Interfaces:**
- Produces: `install.sh` honoring `DANZA_VERSION` (default: latest GitHub release tag, falling back to `main`), `DANZA_BIN_DIR` (exported as `PIPX_BIN_DIR`), `CONFIGURE=false` (skip PATH configuration for CI). Not executed by tests (it targets GitHub); tests verify structure. The live path is exercised by users; the local-install path is Task 9.

- [ ] **Step 1: Write the failing test**

```python
"""Phase-1 T8 install.sh hardening: structural assertions + bash syntax
check. The script is never EXECUTED here - it installs from GitHub, and unit
tests must not touch the network. Each assertion maps to a spec section 5
requirement.
"""
import subprocess
import unittest
from pathlib import Path

import _bootstrap  # noqa

SCRIPT = Path(__file__).resolve().parents[2] / "install.sh"


class InstallShStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")
        cls.lines = [l for l in cls.text.splitlines() if l.strip()]

    def test_bash_syntax_valid(self):
        proc = subprocess.run(["bash", "-n", str(SCRIPT)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_strict_mode(self):
        self.assertIn("set -euo pipefail", self.text)

    def test_body_in_main_invoked_on_last_line(self):
        # curl|bash safety: a truncated download must not execute a partial
        # body - everything runs only if main's closing invocation arrived.
        self.assertEqual(self.lines[-1].strip(), 'main "$@"')
        self.assertIn("main() {", self.text)

    def test_https_only(self):
        self.assertNotIn("http://", self.text)

    def test_curl_hardened(self):
        self.assertIn("curl -fsSL", self.text)

    def test_env_knobs_present(self):
        for knob in ("DANZA_VERSION", "DANZA_BIN_DIR", "CONFIGURE"):
            self.assertIn(knob, self.text, f"missing env knob {knob}")

    def test_installs_from_github_via_pipx(self):
        self.assertIn("pipx install", self.text)
        self.assertIn("git+https://github.com/Aduson-Inc/DANZA-OS", self.text)

    def test_executable_bit(self):
        self.assertTrue(SCRIPT.stat().st_mode & 0o111,
                        "install.sh must be executable")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/tre/dev/DANZA-OS && PYTHONPATH="$PWD:$PWD/danzaboss/tests" \
  DANZA_CORTEX_GLOBAL_DB="$(mktemp -d)/global.db" \
  python3 -m unittest discover -s danzaboss/tests -p 'test_product_install_sh.py' -v
```

Expected: ERROR — `FileNotFoundError: install.sh`.

- [ ] **Step 3: Write `install.sh`**

```bash
#!/usr/bin/env bash
# DANZA-OS installer - hardened curl|bash wrapper around pipx.
#
#   curl -fsSL https://raw.githubusercontent.com/Aduson-Inc/DANZA-OS/main/install.sh | bash
#
# Env knobs:
#   DANZA_VERSION   git ref to install (default: latest release tag, else main)
#   DANZA_BIN_DIR   where pipx links the danza binary (default: pipx's default)
#   CONFIGURE       "false" skips PATH configuration - CI mode (default: true)
#
# The whole body lives inside main(), invoked only on the last line, so a
# truncated download can never execute a partial script.
set -euo pipefail

REPO_URL="https://github.com/Aduson-Inc/DANZA-OS"
API_LATEST="https://api.github.com/repos/Aduson-Inc/DANZA-OS/releases/latest"

log() { printf 'danza-install: %s\n' "$*"; }
die() { printf 'danza-install: ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1; }

resolve_version() {
  if [ -n "${DANZA_VERSION:-}" ]; then
    printf '%s' "$DANZA_VERSION"
    return
  fi
  local tag
  tag="$(curl -fsSL "$API_LATEST" 2>/dev/null \
        | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
        | head -n1 || true)"
  printf '%s' "${tag:-main}"
}

ensure_pipx() {
  if need pipx; then return; fi
  log "pipx not found - installing with python3 -m pip --user"
  need python3 || die "python3 is required (>= 3.10)"
  python3 -m pip install --user pipx \
    || die "could not install pipx; install it manually, then re-run"
  export PATH="$HOME/.local/bin:$PATH"
  need pipx || die "pipx installed but not on PATH; open a new shell and re-run"
}

main() {
  need curl || die "curl is required"
  local version
  version="$(resolve_version)"
  log "installing danza-os@${version}"
  ensure_pipx
  if [ -n "${DANZA_BIN_DIR:-}" ]; then
    export PIPX_BIN_DIR="$DANZA_BIN_DIR"
  fi
  if pipx list 2>/dev/null | grep -q "danza-os"; then
    log "existing install detected - reinstalling at ${version}"
    pipx install --force "git+${REPO_URL}@${version}"
  else
    pipx install "git+${REPO_URL}@${version}"
  fi
  if [ "${CONFIGURE:-true}" != "false" ]; then
    pipx ensurepath >/dev/null 2>&1 || true
  fi
  log "done. verify with: danza doctor"
}

main "$@"
```

Then:

```bash
chmod +x /home/tre/dev/DANZA-OS/install.sh
```

- [ ] **Step 4: Run test to verify it passes**

Same command as Step 2. Expected: PASS (8 tests OK).

- [ ] **Step 5: Commit**

```bash
cd /home/tre/dev/DANZA-OS && git add install.sh danzaboss/tests/test_product_install_sh.py
git commit -m "feat(product): hardened install.sh (pipx wrapper, version pin, CI mode)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: End-to-end acceptance + docs sync

**Files:**
- Modify: `CLAUDE.md` (project layout + "How to run the OS" + test count)
- No new source files — this task proves spec §5 acceptance on this machine.

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Full suite green**

```bash
cd /home/tre/dev/DANZA-OS && ./danzaboss/run_tests.sh 2>&1 | tail -3
```

Expected: `OK`, 0 failures. Note the exact test count for Step 5.

- [ ] **Step 2: Real install from the local clone (spec §5 acceptance)**

```bash
command -v pipx || python3 -m pip install --user pipx
pipx install /home/tre/dev/DANZA-OS
danza doctor /home/tre/dev/DANZA-OS || true   # source tree: scaffold check passes as "not activated"
```

Expected: `pipx install` succeeds; `danza` is on PATH; doctor prints all seven checks (the source tree itself may be red only on non-scaffold grounds — that's fine, the product target is the fresh repo below).

- [ ] **Step 3: Fresh temp repo — init, doctor green, re-init all-skip**

```bash
TMP="$(mktemp -d)/myapp" && mkdir -p "$TMP" && git -C "$(dirname "$TMP")" --version >/dev/null
git init -q "$TMP"
danza init "$TMP"
```

Expected: `created` lines for every payload file + `CLAUDE.md`, then `[PASS]` ×7 and `doctor: green`, then Next steps. Exit 0.

```bash
danza doctor "$TMP"; echo "rc=$?"
danza init "$TMP" | grep -c "up-to-date"
```

Expected: `doctor: green`, `rc=0`; second command prints a count equal to the payload file count + CLAUDE.md (every line `skipped ... (up-to-date)`), and crucially the word `created` appears nowhere:

```bash
danza init "$TMP" | grep -c "^created" || echo "no created lines - PASS"
```

Expected: `no created lines - PASS`.

- [ ] **Step 4: Verify the D8 hook fires in the temp repo**

```bash
cd "$TMP" && printf '# Handoff\n\nTurn 1: claude built features 1+2; codex next.\n' > .danza/handoff.md
danza hook session-start
```

Expected: one JSON line whose `additionalContext` contains `CONTINUE MODE`. Then clean up the install:

```bash
pipx uninstall danza-os
```

- [ ] **Step 5: Sync `CLAUDE.md` (root) to reality**

Three edits, preserving surrounding text exactly:
1. Project layout tree: under `danzaboss/`, extend the module list line to include `product/` — change `kernel/ planning/ memory/ context/ security/ observability/ orchestration/ selftest/` to include `product/`, and add below the `workstation/` line:
   ```
     product/                   Packaging & lifecycle: danza init scaffold, danza doctor, install payload
   ```
   Also add after the `RUNBOOK.md` line:
   ```
   pyproject.toml               Package metadata — pipx install => `danza` CLI
   install.sh                   Hardened curl|bash installer (pipx wrapper)
   ```
2. "How to run the OS" section, add after the health-check bullet:
   ```
   - **Install as a product:** `pipx install git+https://github.com/Aduson-Inc/DANZA-OS` (or `./install.sh`);
     then `danza init <dir>` scaffolds an app repo and `danza doctor` health-checks it.
   ```
3. Replace every occurrence of the test count `733` with the count observed in Step 1 (there are several — grep for `733`).

- [ ] **Step 6: Final suite run + commit**

```bash
cd /home/tre/dev/DANZA-OS && ./danzaboss/run_tests.sh 2>&1 | tail -3
git add CLAUDE.md
git commit -m "docs: sync CLAUDE.md to Phase 1 (product package, danza init/doctor, test count)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Expected: suite `OK`; clean commit.

---

## Spec §5 coverage map

| Spec requirement | Task |
|---|---|
| pyproject: name danza-os, zero deps, `neon` extra, console script, package data | 1 |
| `danza init`: copy `.claude/` + `.danza/` from bundled data (copy, not symlink) | 2, 3 |
| Idempotent per-file `created/merged/skipped(user-modified)`; Rules 34–35 | 3 |
| CLAUDE.md managed block (begin/end markers, create if absent) | 4 |
| `.danza/.scaffold-version` stamp for future `--upgrade` | 3 |
| Auto-resume SessionStart hook (D8) installed + implemented | 2 (wiring), 5 (logic) |
| init ends with doctor + next steps | 7 |
| `danza doctor`: selftest wrap, Python ≥ 3.10, git, scaffold integrity, runners, profile, CORTEX D9 | 6 |
| `install.sh` hardening (strict mode, main-on-last-line, HTTPS, env knobs, pipx) | 8 |
| Acceptance: fresh temp repo, pipx from local clone, init, doctor green, re-init all-skip, suite green | 9 |
