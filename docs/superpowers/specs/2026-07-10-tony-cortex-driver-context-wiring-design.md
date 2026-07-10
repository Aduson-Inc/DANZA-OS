# Spec — Wire Tony D handoffs to CORTEX driver context

- **Date:** 2026-07-10
- **Status:** Approved design, ready to execute (fresh session)
- **Layer:** OS_DEV (building DANZA-OS itself)
- **Branch:** `danza/os-selfimprove`
- **Builds on:** commit `ef1ed11` (`feat(cortex): add driver-scoped context compiler`)
- **Commit message when done:** `feat(agents): wire Tony handoffs to CORTEX driver context`

> Execute this spec directly, TDD (tests first). It is self-contained: exact
> file edits, exact string replacements, and the full test plan are below. Do
> NOT re-derive the design — it is settled.

---

## 1. Goal

When Tony D delegates work to a specialist, he first compiles **role-scoped,
budgeted CORTEX context** with the new compiler and pastes it into the
specialist's spawn prompt as a `## CORTEX Context` block. Specialists consume
that block as primary task memory and only fall back to `cortex search` if it is
insufficient. Tony spawns only the specialists a task needs — never the full
roster by reflex.

This is an **upgrade of an existing protocol**, not a greenfield add: Tony and
all 7 specialists already carry a `## CORTEX memory protocol` section built
around the old `danza cortex search` flow. We swap Tony's to the new compiler
and flip specialists to "consume the supplied block first."

## 2. Layer model & safety (must hold)

1. **OS_DEV** (this repo, building DANZA-OS) — stays **CORTEX-silent**. Do NOT
   flip it hot. Do NOT edit `danzaboss/kernel/profile.py`.
2. **APP_BUILD** (DANZA building a user app) — CORTEX runs **hot**; this is where
   Tony + specialists depend on CORTEX. Scoped project DB
   (`<repo>/.danza/cortex/cortex.db`).
3. **User app** — receives scoped project memory through the drivers.

Why OS_DEV stays silent even after this change: `compile_driver_context` is an
**explicit, on-demand call** (like `danza cortex retrieve`) that reads no
execution profile and injects nothing. Tony only runs it when *he* delegates,
which only happens in an activated APP_BUILD repo. Nothing here auto-injects into
an OS_DEV session. (Already proven by `test_compiler_is_profile_agnostic`.)

`.claude/` edits are permitted: the sentinel `.danza/runtime/claude-approval`
exists ("User-approved .claude/ edit grant for the CORTEX build"), so Rule 37 is
unlocked and OS_DEV's `claude_write_approval=True`.

## 3. Default budgets (real agent IDs)

The mission listed `angela-architect`/`hank-devops`, which **do not exist**.
Real IDs (matching the `DRIVER_CORTEX` map already in `driver_context.py`):

| Driver id | Budget |
|---|---|
| `jonathan-builder` | 900 |
| `samantha-mapper` | 900 |
| `angela-auditor` | 900 |
| `bonnie-qa` | 800 |
| `billy-security` | 800 |
| `hank-designer` | 800 |
| `carmella-researcher` | 800 |
| (unknown / `tony-d-orchestrator`) | 1200 fallback |

**Decision (user-approved): code anchor.** Budgets live in `driver_context.py`
as the single source of truth; the CLI applies the role default when `--budget`
is omitted. Tony's prompt does NOT carry a budget table.

## 4. Files to touch (10 source/prompt + 2 test files + this spec)

| # | File | Change |
|---|---|---|
| 1 | `danzaboss/cortex/driver_context.py` | Add `DRIVER_BUDGETS` + `default_budget()`; `compile_driver_context(budget=None)` resolves to role default. |
| 2 | `danzaboss/cortex/commands.py` | `_cmd_driver_context`: omit `--budget` → pass `None` (role default). |
| 3 | `.claude/agents/tony-d-orchestrator.md` | 2 surgical edits (below). |
| 4–10 | `.claude/agents/{jonathan-builder,samantha-mapper,angela-auditor,bonnie-qa,carmella-researcher,hank-designer,billy-security}.md` | 1 uniform edit each. |
| — | `danzaboss/tests/test_cortex_driver_context.py` | Extend: budget-default tests. |
| — | `danzaboss/tests/test_agents_cortex_wiring.py` | **New**: prompt-content asserts + APP_BUILD flow harness. |

**Do NOT touch:** `danzaboss/kernel/profile.py`, `danzaboss/context/pipeline.py`,
`danzaboss/memory/store.py`, any CORTEX `.db` file, live `.danza/` state (only
temp test sandboxes). No GSD, no new planning system, no unrelated docs.

## 5. Exact edits

### 5.1 `driver_context.py` (code anchor)

Add after the `_FALLBACK` definition:

```python
# Per-driver default context token budgets (mission default). Applied when the
# caller/CLI passes no explicit budget. Unknown drivers get the generic cap.
DRIVER_BUDGETS: dict[str, int] = {
    "jonathan-builder": 900,
    "samantha-mapper": 900,
    "angela-auditor": 900,
    "bonnie-qa": 800,
    "billy-security": 800,
    "hank-designer": 800,
    "carmella-researcher": 800,
}
_DEFAULT_BUDGET = 1200


def default_budget(driver: str) -> int:
    """The role's default context budget; unknown drivers -> generic cap."""
    return DRIVER_BUDGETS.get(driver, _DEFAULT_BUDGET)
```

Change `compile_driver_context` signature `budget: int = 1200` →
`budget: Optional[int] = None`, and as the first line of the body:

```python
    if budget is None:
        budget = default_budget(driver)
```

(`Optional` is already imported.) Existing callers that pass an explicit budget
are unaffected. Update the docstring line to note the None→role-default behavior.

### 5.2 `commands.py` — `_cmd_driver_context`

Replace:

```python
    budget = int(take_opt("--budget") or 1200)
```

with:

```python
    budget_opt = take_opt("--budget")
    budget = int(budget_opt) if budget_opt else None   # None -> role default
```

`compile_driver_context(...)` already receives `budget=budget`; when `None` the
compiler resolves the role default, and `DriverContext.budget`/`used` in the JSON
then reflect the real role cap.

### 5.3 `tony-d-orchestrator.md` — edit A (orchestrator CORTEX duties)

In `## CORTEX memory protocol (orchestrator duties)`, replace item **(1)**:

> (1) when spawning a driver, run `danza cortex search` for their task and paste
> the relevant observation IDs + titles into their spawn prompt;

with:

> (1) when spawning a driver, compile role-scoped memory with
> `danza cortex context --driver <agent-id> --task "<specific task>"` (the role
> budget auto-applies; override with `--budget N`) and paste the returned block
> verbatim into the driver's spawn prompt under a `## CORTEX Context` heading —
> this is the driver's primary task memory, not a `search` dump;

Items (2)–(4) unchanged.

### 5.4 `tony-d-orchestrator.md` — edit B (spawn discipline)

At the end of `## Sub-Agent Spawning` (after the `Agent(...)` code block), add:

> Spawn only the specialists a task actually needs — never the full roster by
> reflex (Billy near end-of-build only; Carmella only for research/external
> APIs; Hank only for design work). Every driver spawn prompt MUST include its
> `## CORTEX Context` block, compiled per the CORTEX protocol below.

### 5.5 All 7 specialist `.md` files — uniform edit

Each specialist's `## CORTEX memory protocol` currently opens:

> Before starting work: run `danza cortex search "<your task keywords>"` and
> fetch relevant hits with `danza cortex get <id>`.

Replace that opening with:

> Before starting work: first use the `## CORTEX Context` block Tony D supplied
> in your spawn prompt as your primary task memory — it is already scoped to your
> role and task. Only if that block is missing or insufficient, run
> `danza cortex search "<your task keywords>"` and fetch relevant hits with
> `danza cortex get <id>`.

The remainder of each block (cite IDs as evidence, `cortex observe` on durable
learnings, `PYTHONPATH=...` note) is unchanged. All 7 blocks are byte-identical
today, so the same replacement applies to each file.

## 6. Test plan (TDD — write first, watch fail, then implement)

### 6.1 Extend `test_cortex_driver_context.py`
- `default_budget("jonathan-builder") == 900`, `"bonnie-qa" == 800`,
  `"nobody" == 1200`.
- `compile_driver_context(store, "jonathan-builder", task, project)` with **no**
  budget → `ctx.budget == 900` and `ctx.used <= 900`.
- Same for `bonnie-qa` → `ctx.budget == 800`, `ctx.used <= 800`.
- CLI: `context --driver bonnie-qa --task "..." --json` with **no** `--budget`
  → JSON `budget == 800`, `used <= 800`.

### 6.2 New `test_agents_cortex_wiring.py`

**Prompt-content assertions** (read the `.md` files):
1. (req 1,2) Tony's md contains `cortex context --driver` and `## CORTEX Context`.
2. (req 4) Tony's md contains the "only the specialists a task actually needs /
   never the full roster" instruction.
3. (req 3) Each of the 7 specialist mds instructs using the supplied
   `## CORTEX Context` block **before** `cortex search` (assert both the
   `## CORTEX Context` mention and that it precedes the `cortex search` fallback).

**APP_BUILD flow harness** (isolated mock sandbox; `tempfile.TemporaryDirectory`):
4. (req 7) Build a mock APP_BUILD repo: create `.danza/runtime/team-state.json`
   so `active_profile(root)` resolves **APP_BUILD** (assert req 6). Seed a scoped
   `.danza/cortex/cortex.db` (via `ObservationStore(SqliteBackend(db_path(root)))`)
   with a handful of observations of varied types — the "simulated
   post-onboarding project memory."
5. Simulate Tony delegating to a **subset** — e.g. `{"jonathan-builder",
   "bonnie-qa"}` — NOT all 7. For each, run the CLI `context --driver <id>
   --task "<task>" --json` against the sandbox root.
6. (req 8) Assert each returned package `used <= role budget` and the block is
   non-empty (≥1 observation) → "at least one specialist receives driver-scoped
   context." Record total tokens (`sum(used)`) and assert it is measured/positive.
7. (not-all-agents) Assert the called set ⊊ full roster (`len(called) < 7`).
8. (req 5, OS_DEV unchanged) Separate OS_DEV sandbox (no `team-state.json`,
   `DANZABOSS_PROFILE=OS_DEV`) → `active_profile` is OS_DEV and
   `session_inject is False`.
9. (req 9, no legacy dep) Assert the wiring module source and
   `driver_context.py` contain neither `memory.store`/`MemoryStore` nor
   `context.pipeline`.

**Hermeticity:** rely on `_bootstrap` (already isolates the global store to a
temp DB). Save/restore `DANZABOSS_PROFILE` in `setUp`/`tearDown` like
`test_cortex_commands.py`.

## 7. Work order (for the executing session)

1. Confirm branch `danza/os-selfimprove` and clean status.
2. Restate the layer model (OS_DEV silent, APP_BUILD hot).
3. Show the intended file list (§4).
4. **Tests first** (§6): write, run, watch them fail for the right reason (RED).
5. Implement the smallest edits (§5) → GREEN.
6. Run targeted tests: `test_cortex_driver_context` + `test_agents_cortex_wiring`.
7. Run the full suite: `./danzaboss/run_tests.sh` — must be green.
8. Show `git diff --stat` and confirm no forbidden paths (profile.py,
   context/pipeline.py, memory/store.py, CORTEX .db, live .danza state).
9. Commit: `feat(agents): wire Tony handoffs to CORTEX driver context`.
10. Final report (see §9). Stop after the commit.

## 8. Success criteria

- All new tests pass; full suite green (currently 721 → grows by the new tests).
- Tony's prompt requires `cortex context --driver` + a `## CORTEX Context` block
  and the minimum-roster discipline.
- All 7 specialists instruct "use supplied block first."
- Budgets resolve from `DRIVER_BUDGETS`; CLI respects them.
- OS_DEV behavior unchanged; no `profile.py`, `context/pipeline.py`,
  `memory/store.py`, or CORTEX `.db` change. Additive and reversible.

## 9. Final report must include
files changed · exact prompt/instruction changes · tests added/updated · proof
Tony uses driver context in handoff · proof specialists receive/use it · proof
not all agents are called · proof OS_DEV stayed unchanged · test results · what
remains next.

## 10. What remains unproven (honesty)

The flow harness **simulates** Tony's delegation — unit tests cannot spawn a live
LLM Tony or real sub-agents. It proves: (a) the CLI/compiler produce scoped,
budgeted, non-empty blocks for a chosen subset; (b) the prompts *instruct* the
flow; (c) budgets and profiles behave. It does **not** prove a live Tony obeys
the instruction end-to-end in an activated repo. That live end-to-end validation
(in `/home/tre/dev/danza-cortex-app-test` or a fresh APP_BUILD sandbox) is the
next increment after this one.
```
