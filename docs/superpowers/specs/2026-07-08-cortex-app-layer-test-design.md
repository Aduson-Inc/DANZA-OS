# CORTEX App-Layer Test — Design Spec

**Date:** 2026-07-08
**Status:** Approved (design) — pending implementation plan
**Author:** Claude (Opus 4.8), with Tre

## Problem

DANZA-OS has two layers of interest here:

- **OS layer (`OS_DEV`, Layer 0)** — an AI session improving DANZABOSS itself. CORTEX runs
  *dormant*: `memory_level=none` (captures nothing — claude-mem holds build memory),
  `session_inject=False`, `distill_gate_active=False` (`danzaboss/kernel/profile.py:72-82`).
- **User-app layer (`APP_BUILD`, Layer 2)** — activated DANZABOSS building a user's app. CORTEX
  runs *hot*: `memory_level=normal`, `session_inject=True`, `distill_gate_active=True`,
  `distill_min_events=1` (`danzaboss/kernel/profile.py:94-104`).

Agents are already *instructed* to depend on CORTEX (search-before-work, `get` for evidence,
cite IDs per Rule 43, `observe` durable learnings with `reasoning` + relevance gates; Tony D
consults CORTEX for build-order templates per Rule 29). What is **UNVERIFIED** (per `RUNBOOK.md`)
is whether real agents actually follow those instructions, and whether app memory stays scoped.

We must earn confidence in the safe `APP_BUILD` sandbox *before* enabling CORTEX injection/gating
in the `OS_DEV` layer. This spec defines a test that does exactly that. **It makes no changes to
the OS layer.**

## Goal & Success Criteria

Prove three things about DANZA agents on a **fresh** app, then report results for a human
go/no-go decision:

| Check | Pass evidence |
|---|---|
| **A. Onboard correctly** | NEW-PROJECT mode detected (Rule 39); canned onboarding answers consumed; `feature-list` + per-run log produced (Rule 40) |
| **B. Use CORTEX as intended** | `search`/`retrieve` logged *before* build work; `get` used for evidence; build-order retrieval returns a **HIT**; `observe` writes carry `reasoning` + `when_relevant`/`when_not_relevant` |
| **C. Keep memory scoped** | App learnings land in the app's `cortex.db` (project id `"mockapp"`); the seeded global template stays in the global DB; **zero leakage** in either direction; the OS repo's real `.danza/cortex/` and `~/.danza/cortex/global.db` are **byte-identical before and after** |

**Deliverable:** a `RESULTS.md` with a PASS/FAIL verdict per check and a recommendation on
whether it is safe to move toward OS-layer enablement. Shown to the user; no OS changes applied.

## Non-Goals

- Building a real/usable app (the mock app is a stub; we test the *loop*, not the software).
- Researching or shipping the future tech-stack/template library (the seeded template is a
  single minimal placeholder — see *Future Work*).
- Enabling CORTEX in `OS_DEV`. That is a separate, later decision made after seeing results.
- Fixing the broader UNVERIFIED multi-agent loop or the unwired hook guards
  (`.planning/codebase/CONCERNS.md`). Out of scope; noted as risk.

## Isolation Model (keeps the OS untouched)

- **Sandbox app dir:** a brand-new sibling directory outside the repo:
  `/home/tre/dev/danza-cortex-app-test/mockapp/`. Disposable (`rm -rf` to reset).
- **`danzaboss` imported read-only** via `PYTHONPATH=/home/tre/dev/DANZA-OS`. Running the toolkit
  never mutates OS source; the only writes go to the sandbox's `.danza/`.
- **Both CORTEX tiers redirected into the sandbox** so real memory cannot be polluted:
  - project DB → `mockapp/.danza/cortex/cortex.db` (automatic, CWD/root-scoped via `factory.db_path`)
  - global DB → `DANZA_CORTEX_GLOBAL_DB=<sandbox>/global.db` (env override per
    `danzaboss/cortex/factory.py`; **must be set on every command in the test**)
- **Fail-loud guardrail:** snapshot (sha256 + mtime) of the OS's `.danza/cortex/` **and**
  `~/.danza/cortex/global.db` is taken before and after the run and asserted identical. Any change
  to real memory fails the test.
- **Worktree:** intentionally *not* used. A worktree of DANZA-OS would inherit the OS's committed
  `.danza/` state (real `handoff.md`, existing `team-state.json`), forcing CONTINUE mode +
  `APP_BUILD`-already + CORTEX scoped to `"DANZA-OS"` — defeating the fresh-onboarding and
  app-scoping goals. The PYTHONPATH + snapshot guard already fully protect the OS source.

## The Mock App & Fresh Onboarding

- **App concept:** a tiny, stack-light "Quote of the Day" CLI (one idea, ~2 features). Chosen so
  onboarding + build-order have something concrete to reason about without real engineering.
- **Fresh-start fixtures** written into the sandbox before the run:
  - `.danza/handoff.md` = `"No handoff yet."` → forces NEW-PROJECT mode (Rule 39).
  - canned `.danza/onboarding-answers.md` (app name, concept, target user, stack preference =
    "let DANZA suggest") so onboarding runs **non-interactively**.
- **Force the profile:** `DANZABOSS_PROFILE=APP_BUILD` for the entire run. A brand-new dir with no
  `team-state.json` would otherwise resolve to `OS_DEV` (silent CORTEX) via the profile heuristic
  (`profile.py:20-25`) — the opposite of what we need to observe. Env var is the highest-priority,
  most deterministic override.

## Phase 1 — Live Agent Run

1. **Seed** one global build-order template (layer 4) into the sandbox global DB — a generic build
   order for a CLI tool (e.g. scaffold → core logic → tests → CLI wiring → docs). Minimal
   placeholder for the future template library.
2. **Spawn** the real `tony-d-orchestrator` subagent with the "Who's the Boss?" trigger + the app
   concept, explicitly pointed at the sandbox root and instructed to run every `cortex` command
   with the sandboxed env (`PYTHONPATH`, `DANZABOSS_PROFILE=APP_BUILD`,
   `DANZA_CORTEX_GLOBAL_DB`, CWD = sandbox).
3. **Observe the loop:** Tony D detects NEW mode → onboards → consults CORTEX for build order
   (Rule 29 = the *build-order lookup*) → spawns one driver (Jonathan) for one feature, which
   performs `search → get → …work… → observe`.
4. **Capture everything:** the agents' bash `cortex` invocations are recorded in the subagent
   transcript; after the run, both DBs are dumped (`observations`, `usage_log`) to reconstruct
   exactly what was read and written, and by whom.

**Fidelity risk (reported honestly):** reliably scoping a real subagent's CWD/root to the sandbox
is the shakiest part, and the multi-agent loop is UNVERIFIED. If the live agent strays, the report
states exactly what it did — no massaging. Phase 2 still yields the clean deterministic answer.

## Phase 2 — Scripted Harness (repeatable)

A deterministic script (stdlib + `danzaboss`, **no LLM**) that replays the prescribed protocol:

1. init a fresh sandbox → seed the global template
2. simulate one build turn: `search → get → observe` using the real CLI/store APIs
3. drive the real hook entry points: `cortex hook session-start | post-tool-use | stop`
4. assert checks A/B/C programmatically

Purpose: confirm consistent behavior independent of live-run nondeterminism, and leave a
**regression test** at the app-scenario level — a superset of `danzaboss/tests/test_cortex_cold_start.py`
that adds global-federation and scoping-boundary assertions. Runs fast; re-runnable as CORTEX evolves.

## Data Flow

```
seed: build-order template ─► sandbox global.db (L4)
                                     │ federates down (federate.py L2-wins)
                                     ▼
Tony D "Who's the Boss?" ─► NEW mode ─► onboarding (canned answers)
        │                                    │
        │ Rule 29: consult CORTEX build order│  ── retrieve ──► HIT (seeded template)
        ▼                                    ▼
   spawn Jonathan ─► search ─► get ─► build feature ─► observe (reasoning + gates)
                                                          │ layer ≤3
                                                          ▼
                                              sandbox mockapp/.danza/cortex/cortex.db
                                              (project = "mockapp"; NOT global)
verify: app rows scoped to "mockapp"; template stays in global; no leak;
        OS .danza/cortex + ~/.danza/cortex/global.db byte-identical (snapshot guard)
```

## Error Handling

- **CORTEX failure during the test** → per project policy: stop and report; do not silently
  continue. (The test's job is to observe, not to repair.)
- **Onboarding blocks on a missing answer** → canned fixture should prevent it; if it still blocks,
  record as a check-A failure rather than improvising answers.
- **Snapshot guard trips** (real memory changed) → hard fail, abort, report which path changed.
- **Live subagent unavailable / strays** → record partial live result; rely on Phase 2 for verdict.

## Testing

- Phase 2 harness *is* the automated test; it exits non-zero on any failed assertion.
- The harness is added under `danzaboss/tests/` (or a clearly-marked sandbox test module) so it can
  run under `run_tests.sh` without requiring the live agent or network. It must not touch real
  memory (uses the same env-redirection + snapshot guard).

## Outputs

- `RESULTS.md` (in the sandbox + a copy shown to the user): onboarding evidence, full CORTEX
  read/write log, two-DB scoping proof, live-vs-harness comparison, PASS/FAIL per check, and an
  OS-layer-enablement recommendation.
- No modifications to the OS layer (`OS_DEV` profile, `.claude/`, OS `.danza/cortex/`).

## Future Work (out of scope here)

- Research and build the tech-stack/template recommendation library — vetted stacks/templates per
  app-idea scenario, user-choose-or-accept-suggestion model. This is the real L4/L5 global
  procedural-memory payload behind Rule 29; this test validates the plumbing it will ride on.
- Decide and (separately) implement CORTEX enablement in the `OS_DEV` layer, informed by results.
```
