# DANZA-OS Self-Improve — Running Improvements Log

Branch: `danza/os-selfimprove` · Baseline: main `6bf9457` · Suite baseline: 694 tests green

Mission: land a stack of measurable, verified improvements to the app-building agentic flow.
Evidence-before-claims; suite green every step.

---

## Phase 0 — Read-only baseline audit (in progress)

Goal: confirm exact live-wiring of hooks + which flow modules are wired vs test-only
(file:line precision), and measure current per-driver context payload (theme-1 token baseline).

### Baseline (verified 2026-07-08)
- Suite: **694 tests, OK (14 skipped), 11.9s** (`./danzaboss/run_tests.sh`).

### Hook wiring — live CC path `cli.py:_cmd_hook` (83-133)
- Enforces **2 of 6** PreToolUse guards: `file_protection_guard` (cli.py:116),
  `hard_stop_guard` (cli.py:120). Charter claim CONFIRMED.
- The other 4 live only inside `HookDispatcher` (dispatcher.py:29-41), which is
  **TEST-ONLY** (reachable in prod only via `DanzaSession.dispatcher`, and
  `DanzaSession` has no cli entry point).
- **KEY NUANCE (reframes charter theme-3):** 3 of the 4 unwired guards *cannot*
  be correctly wired to the live CC hook, because the CC PreToolUse payload does
  not carry the identity they need — the live event is built with `actor=""`
  (cli.py:100):
  - `capability_guard(ev, registry)` needs `ev.actor`.
  - `turn_lock_guard(ev, cfg, current_boss)` needs actor+boss; with `actor=""`
    it would **deny every state-file write** (regression).
  - `scope_guard(ev, approved_task_ids)` needs `ev.task_id`; CC has none, so it
    would **deny every code write** (regression).
  - `context_budget_guard(ev, cfg)` — fires only on `Task`/`Agent` dispatch and
    needs only `payload_tokens`. **Actor-independent → the one cleanly wirable guard.**

### End-of-turn gates (`hooks/gates.py`)
- `anti_theatre`, `verify_before_done`, `regression` → TEST-ONLY (only via
  `run_all_gates`→`HookDispatcher.stop`, unreachable from cli; the live Stop path
  cli.py:90-94 deliberately bypasses them — CC Stop lacks turn data).
- `distillation_gate` → WIRED via `danza cortex` (commands.py:96).

### Flow modules — wired vs test-only
- `context/pipeline.py`, `orchestration/parallel.py`, `observability/trace.py`,
  `memory/store.py` → **TEST-ONLY** (no non-test importer).
- `kernel/scheduler.py`, `planning/decompose.py` → WIRED only via `danza selftest` harness.
- `kernel/tiers.py` → WIRED (`danza tier`). `workstation/conductor.py` → WIRED (`danza conduct`);
  it holds a parallel decision table to `scheduler.decide` (different purpose: relay vs build-loop).
- `runtime/verify.py:27` → `subprocess.run(command, shell=True)` on free-text argv[0]; WIRED via `danza verify`. Real injection surface (borderline: intended as the app's own test cmd).

### Per-driver context payload baseline (theme-1)
- Raw per-driver floor **≈6,150 est-tokens**, of which **≈6,016 (98%) is fixed
  governance** (`constitution.md` 3,788 + `CLAUDE.md` 2,227), paid every turn.
  Live `.danza/` state = 133 tok today (fresh NEW-PROJECT repo; grows unbounded mid-build).
- `context/pipeline.py` compiles a per-driver context hard-capped at
  `token_budget=1200` (pipeline.py:116) + ~50 task + optional 600 CORTEX → **~1,250–1,850 tok**.
- **Honesty caveat:** the pipeline draws only from MemoryStore/CORTEX; it has **no
  path to replace the 6,016-tok governance load**. On a fresh repo it shrinks
  nothing (state 133 < budget 1,200). Its win is on accumulated state mid-build
  (raw unbounded → capped 1,200). So theme-1's token win is *modeled*, not
  demonstrable-now without a populated fixture.

---

## Increment #1 — Wire `context_budget_guard` into the live hook (theme-3 + theme-1)

**Why this one first:** it is the single unwired guard that (a) is actor-independent
so it can be *correctly* wired to the CC hook (the other 3 would regress), (b) serves
integrity (a dormant guard goes live) AND token efficiency (caps sub-agent dispatch to
budgeted context, not whole-repo — the enforcement teeth behind theme-1), and (c) has a
concrete before/after demonstrable NOW via unit tests, unlike the modeled pipeline win.

**Scope:** enforce only where `prof.constitution_binding` is True (OS_BOOT_TEST/APP_BUILD
= the app-build flow the constitution governs). OS_DEV (Layer 0) dispatches freely.
Budget = `GuardConfig.max_dispatch_tokens = 4000`. Fail-open preserved.

**Implementation:** extracted pure `_hook_decision(payload, cwd) -> (decision, reason)`
from `_cmd_hook` (cli.py) + added `_dispatch_tokens(tool, tool_input)` (≈4 chars/tok over
serialized Task/Agent input). `context_budget_guard` now runs when `prof.constitution_binding`.
`_cmd_hook` is now a thin stdin/stdout adapter over the pure helper.

**Verified before/after (real `danza hook pretooluse` output, identical 10k-tok Task payload):**

| Scenario | BEFORE (baseline cli.py) | AFTER |
|---|---|---|
| APP_BUILD, oversized dispatch (10,020 tok) | `allow` (guard dormant) | **`deny`** — "payload 10020 tok exceeds budget 4000; use compiled/budgeted context, not the whole repo" |
| APP_BUILD, budgeted dispatch | allow | allow |
| OS_DEV (Layer 0), oversized dispatch | allow | allow (Layer 0 dispatches freely) |

- Live-path PreToolUse guards enforced: **2 → 3** (`file_protection`, `hard_stop`, **+`context_budget`**).
- Tests: **+9** new (`tests/test_cli_hook.py`); full suite **694 → 703, OK (14 skipped)**, no regressions.
- Reversible; behavior of the two pre-existing guards unchanged (pinned by tests).

_Status: DONE — verified._

---

## Increment #2 — Remove retired `mona-historian` from driver rosters (theme-5 hygiene)

`mona-historian` was retired (agent def is `mona-historian-RETIRED`, not in the
CLAUDE.md 8-agent roster) but three tables still carried it as an active driver:
- `security/capabilities.py:50` — a capability grant (`{Capability.READ}`)
- `context/pipeline.py:98` — a `DRIVER_PROFILES` context-routing entry
- `observability/trace.py:5` — docstring naming "Mona" as the consumer

**Fix:** removed both driver-table entries (now match the real 8-agent roster) and
generalized the trace docstring to "the memory layer (CORTEX)". No test asserted on
`mona-historian` (grep clean), and both tables are read via `.get()`/membership so no
lookup can KeyError.

**Verified:** `grep -rin mona danzaboss/**/*.py` → **CLEAN, 0 refs**. Suite **703, OK
(14 skipped)**, no regressions. This removes a dead capability grant to a
non-existent agent (a small least-privilege correctness win, not just cosmetics).

_Status: DONE — verified._


