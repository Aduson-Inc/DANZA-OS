# Coding Conventions

**Analysis Date:** 2026-07-08

## Scope

These conventions apply to all executable code shipped with DANZA-OS: `danzaboss/` (the
promoted brain — kernel, CORTEX, hooks, research, runtime, workstation, selftest) and
`tools/research-pipeline/`. This document was written by reading actual source files
(`danzaboss/kernel/`, `danzaboss/hooks/`, `danzaboss/security/`, `danzaboss/cortex/`,
`danzaboss/selftest/`, `danzaboss/cli.py`) and their tests, not just the stated rules in
`CLAUDE.md`. Per Constitution Rule 4 ("Existing Code Style"), **match these patterns
exactly** — no new frameworks, paradigms, or conventions without explicit user approval.

## Language & Runtime

- **Python 3.10+**, standard library only for all `danzaboss/` code. No pip installs are
  required to run the test suite. Confirmed: no `requests`, `flask`, `django`, `fastapi`,
  `numpy`, etc. imports anywhere in `danzaboss/`.
- `from __future__ import annotations` is the first import in every module that uses type
  hints (e.g. `danzaboss/kernel/profile.py:27`, `danzaboss/kernel/state.py:15`,
  `danzaboss/hooks/guards.py:7`, `danzaboss/cortex/store.py:12`). Add this to any new module.
- Target-app stacks (code Jonathan writes into a *user's* project) follow
  `.danza/stack-philosophy.md` (free-first, lightweight-first, local-first) — a separate,
  looser policy than the OS's own stdlib-only rule.

## Naming Patterns

**Files:**
- `snake_case.py`, one clear noun/verb per module: `profile.py`, `state.py`,
  `capabilities.py`, `scheduler.py`, `decompose.py`, `harness.py`.
- Test files mirror the module under test: `danzaboss/kernel/state.py` →
  `danzaboss/tests/test_state.py`; `danzaboss/kernel/profile.py` →
  `danzaboss/tests/test_profile.py`. CORTEX submodules use a `test_cortex_<feature>.py`
  prefix (`test_cortex_store.py`, `test_cortex_fts.py`, `test_cortex_mcp.py`) rather than
  mirroring each internal `cortex/*.py` file 1:1.

**Functions:**
- `snake_case`, verb-first: `active_profile()`, `capture_event()`, `assert_dispatchable()`,
  `run_cold_start()`, `record_feature()`.
- Private/internal helpers prefixed with a single underscore: `_utcnow()`, `_atomic_write()`,
  `_emit()`, `_cmd_scan()`, `_hook_post_tool_use()`. CLI subcommand handlers in
  `danzaboss/cli.py` are consistently named `_cmd_<name>` (`_cmd_scan`, `_cmd_verify`,
  `_cmd_selftest`, `_cmd_hook`, `_cmd_profile`, `_cmd_tier`).
- Predicate/boolean-returning functions read as questions or assertions:
  `event_significant()`, `ready_for_dispatch()`.

**Variables:**
- `snake_case` throughout. Short, scoped names in tight loops/helpers (`p`, `s`, `fh`, `ev`);
  descriptive names at module/API boundaries (`current_boss`, `max_features_per_turn`,
  `distill_min_events`).
- Module-level constants are `UPPER_SNAKE_CASE`: `PROFILE_ENV_VAR`, `PROFILE_FILE`,
  `SCHEMA_VERSION`, `MEMORY_LEVELS`, `_ALLOWED_MODES`, `_TRANSITIONS`, `ELEVATED`,
  `DEFAULT_GRANTS`. Module-private constants get a leading underscore
  (`_MUTATING_TOOLS`, `_SIGNIFICANT_CMD`, `_TEAM_STATE_FILE`).

**Types:**
- `PascalCase` for classes and enums: `Profile`, `TeamState`, `StateManager`,
  `CapabilityRegistry`, `ElevationToken`, `Capability(str, Enum)`, `Task`, `Verification`.
- Exception classes are `PascalCase` ending in `Error`: `StateError`, `CapabilityError`,
  `DispatchError`, `HostError`, `RunnerError`, `ConductorError`. Every subsystem that needs
  fail-closed behavior defines its own `Exception` subclass rather than raising bare
  `Exception` or reusing `ValueError` broadly (an exception: `active_profile()` in
  `danzaboss/kernel/profile.py:109` intentionally raises stdlib `ValueError` for bad config,
  documented inline as "fail closed on bad config").

## Code Style

**Formatting:**
- No formatter config detected (no `.black`, `pyproject.toml [tool.black]`, or
  `.flake8`/`ruff.toml` in the repo root or `danzaboss/`). Style is enforced by human
  review and "match existing style" (Constitution Rule 4), not tooling.
- PEP 8 with 4-space indentation is followed throughout. Line length is not strictly
  capped at 79/88 — lines commonly run 90-100 chars where a docstring or an
  f-string reads more clearly unbroken (see `danzaboss/kernel/state.py:141-147`).
- Compact multi-statement lines are used deliberately for short guard clauses in CLI code,
  e.g. `danzaboss/cli.py:43`: `print("usage: ..."); return 2` on one line after an `if`.
  This is a `cli.py`-local idiom for argument validation, not used in kernel/security code.

**Docstrings:**
- Every module has a top docstring stating **why** it exists, not just what it does —
  see the "Why this exists" framing in `danzaboss/kernel/profile.py:1-26` and the design
  rationale in `danzaboss/kernel/scheduler.py:1-15`. This mirrors the CLAUDE.md
  requirement: "module + function docstrings that state *why*."
- Class docstrings describe the invariant they protect, e.g.
  `danzaboss/kernel/state.py:37-43` (`TeamState`) documents what `max_features_per_turn`
  means in each mode; `danzaboss/security/capabilities.py:75` documents that
  `CapabilityRegistry` is where the "human/user gate" happens.
- Public function docstrings state behavior contracts and failure modes explicitly, e.g.
  `active_profile()` (`danzaboss/kernel/profile.py:109-111`): "Resolve the active profile
  ... Raises ValueError on an explicitly configured but unknown name (fail closed on bad
  config)."

## Type Hints

- Type hints on all public functions and dataclass fields, per CLAUDE.md's stated rule —
  confirmed in practice: `def active_profile(root: str = ".", env: dict | None = None) -> Profile`
  (`danzaboss/kernel/profile.py:108`), `def check(self, agent: str, capability: Capability,
  elevation: Optional[ElevationToken] = None) -> None` (`danzaboss/security/capabilities.py:101`).
- Modern union syntax (`dict | None`, `int | None`) is used where `from __future__ import
  annotations` is present; `typing.Optional[...]` also appears in the same files
  (`danzaboss/kernel/state.py:21`, `danzaboss/security/capabilities.py:22`) — both styles
  coexist, prefer whichever the surrounding file already uses.
- Return types are annotated even for `None`-returning functions:
  `def validate(self) -> None:` (`danzaboss/kernel/state.py:56`).

## Dataclasses

- `@dataclass` (from stdlib `dataclasses`) is the standard way to model state and value
  objects — used 33+ times across non-test `danzaboss/` modules. Examples: `Profile`
  (`danzaboss/kernel/profile.py:41`, `frozen=True` because a profile is an immutable
  policy snapshot), `TeamState` (`danzaboss/kernel/state.py:36`, mutable — it's a document
  being transitioned), `ElevationToken` (`danzaboss/security/capabilities.py:64`, uses
  `field(default_factory=...)` for generated tokens/timestamps), `Check`/`Report`
  (`danzaboss/selftest/harness.py:23-45`).
- `frozen=True` is used specifically for value objects that must not be mutated after
  construction (policy/config objects like `Profile`). Mutable dataclasses are used for
  documents that get transitioned/updated in place (`TeamState`).
- Dataclasses expose `to_dict()`/`to_json()` methods (often wrapping `dataclasses.asdict`)
  for CLI/JSON output rather than ad hoc dict construction:
  `Profile.to_dict()` (`danzaboss/kernel/profile.py:67-68`),
  `TeamState.to_json()` (`danzaboss/kernel/state.py:75-76`),
  `Report.to_dict()` (`danzaboss/selftest/harness.py:41-45`).

## Error Handling — Fail Closed

This is the single most load-bearing convention in the codebase and is explicit in
CLAUDE.md ("Fail closed: validation and authorization raise on violation; never silently
continue past a bad state").

- **Security/state mutation paths fail closed (raise).** `StateManager.transition()`
  (`danzaboss/kernel/state.py:126-163`) raises `StateError` if an unrecognized field is
  set, if a status transition isn't in the `_TRANSITIONS` table, or if the actor doesn't
  match `current_boss`. `CapabilityRegistry.check()`
  (`danzaboss/security/capabilities.py:101-126`) raises `CapabilityError` for any
  ungranted or invalid elevated action, and audits the denial before raising.
  `active_profile()` raises `ValueError` on an unrecognized profile name rather than
  silently defaulting.
- **Ownership-field mutation is fail-closed by design, not by accident**: mutating any
  `_PROTECTED_FIELDS` entry (`current_boss`, `previous_boss`, `mode`, `turn_number`,
  `schema_version`) always requires an explicit `actor` argument that matches
  `current_boss` — omitting `actor` is treated as a hostile/buggy call and rejected
  (`danzaboss/kernel/state.py:139-147`, comment: "closes W1 fail-open"). See the
  regression suite `TestTurnLockFailClosed` in `danzaboss/tests/test_state.py:78-109`
  for the exact incident this guards against.
- **Claude Code hook integration fails OPEN by explicit, documented exception.**
  `danzaboss/cli.py:64-133` states the contract inline: "FAIL OPEN on any internal error
  (exit 0, allow) so a hook bug never bricks the session. FAIL CLOSED only on a real
  policy hit." Unreadable stdin JSON → `_emit("allow")`
  (`danzaboss/cli.py:86-88`); any uncaught internal exception in `_cmd_hook` is caught
  and also allows (`danzaboss/cli.py:131-133`), with the error printed to stderr for
  visibility. This is the one deliberate fail-open path in the codebase — used **only**
  for hook plumbing robustness, never for security/state logic itself. Do not generalize
  this pattern to new code outside the hook boundary.
- **Structural validation is centralized in a `validate()` method** that a caller invokes
  before persisting, rather than scattering checks across call sites: `TeamState.validate()`
  (`danzaboss/kernel/state.py:56-73`) is called both by `load()` and `_atomic_write()`
  so state can never be persisted in an invalid shape.
- **Exceptions carry a specific, actionable message**, usually including the offending
  value via `!r`: `f"invalid mode {self.mode!r}"`, `f"unknown DANZABOSS profile {name!r}; expected one of {sorted(PROFILES)}"`.
  Use `!r` (repr) for the offending value, not `str()`.
- **`raise ... from e`** is used when re-raising after catching a lower-level exception,
  to preserve the chain: `danzaboss/kernel/profile.py:120-121`
  (`except (OSError, json.JSONDecodeError) as e: raise ValueError(...) from e`).

## Determinism

- Control logic (scheduler decisions, wave planning, memory scoring, profile resolution)
  is deterministic and unit-testable — no hidden randomness. `active_profile()`'s
  resolution order is explicitly documented as "first hit wins; deterministic, no hidden
  state" (`danzaboss/kernel/profile.py:20-25`). `StateManager._TRANSITIONS`
  (`danzaboss/kernel/state.py:80-86`) is an explicit table of legal state transitions, not
  inferred logic.
- Where a token/ID must be unique but not predictable (elevation tokens, security-relevant
  identifiers), `secrets.token_hex(...)` is used
  (`danzaboss/security/capabilities.py:19,70`) — never `random`.

## Persistence Pattern — Atomic Writes

- Any module that persists JSON state to disk writes to a `.tmp` file first, then
  `os.replace()`s it into place (atomic on POSIX):
  `StateManager._atomic_write()` (`danzaboss/kernel/state.py:110-116`). Follow this
  pattern for any new state file to avoid partial-write corruption; there's an explicit
  regression test for it (`test_atomic_write_leaves_no_tmp`,
  `danzaboss/tests/test_state.py:69-71`).
- Append-only logs (audit trails, decision logs) are written with mode `"a"` and one JSON
  object per line (JSONL): `CapabilityRegistry._audit()`
  (`danzaboss/security/capabilities.py:83-86`).

## Imports

**Order:** stdlib imports first, one per group typically alphabetized within the group,
then a blank line, then local/relative imports. Example
(`danzaboss/security/capabilities.py:14-22`):
```python
from __future__ import annotations

import datetime as _dt
import json
import os
import secrets
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
```

**Relative imports** are used within `danzaboss/` for sibling/parent-package references:
`from .events import ToolEvent, Decision` and `from ..security.capabilities import (...)`
(`danzaboss/hooks/guards.py:9-11`). `danzaboss/cli.py` imports submodules via relative
dotted paths from the package root (`from .cortex import commands as cortex_commands`,
`from .kernel.profile import active_profile`).

**Aliasing:** common stdlib modules that would otherwise shadow local names are aliased
with a leading underscore: `import datetime as _dt`. Use this convention when a stdlib
name might collide with a local variable/param.

## CLI Design Pattern (`danzaboss/cli.py`)

- Every subcommand is a `_cmd_<name>(argv: list[str]) -> int` function returning a
  process exit code (`0` success, `1` failure, `2` usage error).
- Usage errors print `usage: ...` to `stderr` and return `2`, inline in the same
  guard clause (`danzaboss/cli.py:42-43`).
- Output is JSON via `json.dumps(..., indent=2)` for machine/agent consumption, since
  this CLI is called by hooks and other AI agents, not just humans.
- The Claude Code hook protocol (`_cmd_hook`, `danzaboss/cli.py:83-133`) is documented
  inline with its exact contract (stdin JSON, stdout JSON decision schema) directly above
  the implementation — follow this pattern of embedding protocol contracts as comments
  next to the code that implements them.

## Module Design

- **One concern per module**, named for that concern: `state.py` owns team-state
  persistence and transitions only; `profile.py` owns execution-profile resolution only;
  `capabilities.py` owns the capability/elevation model only. Cross-cutting orchestration
  (e.g. `danzaboss/cli.py`) imports from these narrow modules rather than reimplementing
  logic.
- **No barrel files / `__init__.py` re-export layers observed** — modules are imported by
  their full dotted path (`from danzaboss.kernel.state import StateManager`), not through
  a package-level convenience re-export.
- Public API surface per module is small and function/class based; internal helpers are
  underscore-prefixed and not intended for cross-module import.

## Comments

- Comments explain **why**, especially around non-obvious safety/security decisions —
  e.g. `danzaboss/cli.py:108-114` explains why `.claude/` write approval differs between
  OS_DEV and runtime profiles, referencing the Constitution rule number (Rule 37) inline.
- Rule references from `.claude/rules/constitution.md` are cited directly in code comments
  when a piece of logic exists specifically to enforce a rule, e.g. `# Rule 45`,
  `# Rules 13-15 hard stops`, `# closes W1 fail-open`. When adding governance-related code,
  follow this pattern — cite the constitution rule number in the comment.
- Section-divider comments (`# -- persistence ----...`) are used inside larger classes to
  separate logical groups of methods, e.g. `StateManager`
  (`danzaboss/kernel/state.py:100,125,165,186`).

---

*Convention analysis: 2026-07-08*
