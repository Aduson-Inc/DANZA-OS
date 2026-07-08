<!-- refreshed: 2026-07-08 -->
# Architecture

**Analysis Date:** 2026-07-08

## System Overview

DANZA-OS is a **multi-AI development operating system**: a framework of prompts (`.claude/`)
plus shared-brain state files (`.danza/`) plus a Python stdlib-only governance/memory engine
(`danzaboss/`) that lets one or more AI environments (Claude Code, Codex, Gemini, Grok…) build
a *target application* under a fixed constitution. DANZA-OS is not itself the target app.

```text
┌─────────────────────────────────────────────────────────────────────┐
│                     Prompt Layer (.claude/)                          │
│  8 role-tagged agents · rules/constitution.md (45 rules) ·           │
│  skills/danza/SKILL.md ("Who's the Boss?" ignition)                  │
│  `.claude/agents/*.md` `.claude/rules/constitution.md`               │
└───────────────────────────────┬────────────────────────────────────┘
                                 │ spawns (star topology, orchestrator only)
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│         Driver Agents (Jonathan, Samantha, Angela, Bonnie,           │
│         Carmella, Hank, Billy) — coordinate via the blackboard,      │
│         never call each other directly                               │
└───────────────────────────────┬────────────────────────────────────┘
                                 │ read/write
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Shared-Brain State / Blackboard (.danza/)               │
│  handoff.md · system-map.md · feature-list.md · decision-log.md ·    │
│  turn-log.md · logs/NNN.md · runtime/team-state.json ·                │
│  runtime/profile.json · cortex/cortex.db                              │
└───────────────────────────────┬────────────────────────────────────┘
                                 │ enforced/queried by
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│               THE BRAIN — danzaboss/ (Python, stdlib only)           │
│                        `danzaboss/cli.py` entry point                 │
├───────────────┬───────────────┬───────────────┬─────────────────────┤
│  kernel/       │  hooks/       │  cortex/      │  workstation/       │
│  profile,      │  dispatcher,  │  cognitive    │  onboarding,        │
│  scheduler,    │  guards,      │  memory       │  planner, conductor,│
│  state, tiers  │  gates,events │  (25 modules) │  hosts, runners     │
├───────────────┼───────────────┼───────────────┼─────────────────────┤
│  planning/     │  memory/      │  context/     │  security/          │
│  decompose     │  store (legacy)│ pipeline     │  capabilities       │
├───────────────┼───────────────┼───────────────┼─────────────────────┤
│  observability/│  orchestration/│ selftest/    │  runtime/           │
│  trace         │  parallel      │ harness      │  scan, verify,      │
│                │                │              │  runner             │
└───────────────┴───────────────┴───────────────┴─────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  External senses: tools/research-pipeline/ (YouTube -> NotebookLM)   │
│  Target application (the thing being built, outside this repo)      │
└─────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| Ignition skill | Detects trigger phrase, spawns orchestrator | `.claude/skills/danza/SKILL.md` |
| Orchestrator agent (Tony D) | Mode detection, turn lock, spawns drivers, writes handoff | `.claude/agents/tony-d-orchestrator.md` |
| Driver agents (7) | Role-scoped work (build/map/audit/QA/research/design/security) | `.claude/agents/*.md` |
| Constitution | 45 unbreakable rules; runtime law for Layers 2-3 | `.claude/rules/constitution.md` |
| CLI entry point | Dispatches `scan`, `verify`, `selftest`, `hook`, `cortex`, `profile`, `tier`, `runners`, `conduct` | `danzaboss/cli.py` |
| Execution profile resolver | Chooses OS_DEV / OS_BOOT_TEST / APP_BUILD; gates ceremony, memory, hooks | `danzaboss/kernel/profile.py` |
| Team-state manager | Machine-checkable turn ownership, deterministic state transitions | `danzaboss/kernel/state.py` |
| Scheduler | Dual-mode execution kernel (`continuous` vs `relay`) | `danzaboss/kernel/scheduler.py` |
| Verification tiers | Cheapest-safe-test recommendation for a change set | `danzaboss/kernel/tiers.py` |
| Hook dispatcher | Maps Claude Code lifecycle events to guards/gates | `danzaboss/hooks/dispatcher.py` |
| PreToolUse guards | Hard stops, file protection, turn lock, capability, scope, context-budget | `danzaboss/hooks/guards.py` |
| Stop gates | End-of-turn anti-theatre/verify/regression checks | `danzaboss/hooks/gates.py` |
| Capability registry | Least-privilege elevation tokens + audit trail | `danzaboss/security/capabilities.py` |
| CORTEX store/backend | SQLite (FTS5) + optional Neon/Postgres persistence of observations | `danzaboss/cortex/store.py`, `danzaboss/cortex/sqlite_backend.py`, `danzaboss/cortex/neon_backend.py` |
| CORTEX retrieval | Intent detection, ranking, budget assembly, explain traces | `danzaboss/cortex/retrieve.py`, `danzaboss/cortex/intent.py`, `danzaboss/cortex/explain.py` |
| CORTEX context injection | Builds the SessionStart `additionalContext` block | `danzaboss/cortex/inject.py`, `danzaboss/cortex/assemble.py` |
| CORTEX commands | CLI/hook surface (`danza cortex ...`) | `danzaboss/cortex/commands.py` |
| CORTEX MCP server | stdio JSON-RPC read surface for external MCP clients | `danzaboss/cortex/mcp_server.py` |
| CORTEX federation | L4/L5 global store merge (L2-wins) | `danzaboss/cortex/federate.py`, `danzaboss/cortex/factory.py` |
| Workstation conductor | Deterministic relay "postman": watches team-state, ignites boss sessions | `danzaboss/workstation/conductor.py` |
| Workstation hosts | tmux / headless session execution backends | `danzaboss/workstation/hosts.py` |
| Workstation planner/wizard | Onboarding questionnaire, spec/plan generation | `danzaboss/workstation/wizard.py`, `danzaboss/workstation/planner.py` |
| Workstation runners | Detects/persists which AI CLIs (claude/codex/etc.) are available | `danzaboss/workstation/runners.py` |
| Planning decomposition | Verifiable-task gate (leaf must have concrete verification) | `danzaboss/planning/decompose.py` |
| Runtime scan/verify | Learn an `AppProfile` from any repo; run a QA verification command | `danzaboss/runtime/scan.py`, `danzaboss/runtime/verify.py` |
| Selftest harness | Cold-start validation of the OS itself before promotion | `danzaboss/selftest/harness.py` |
| Research squad | Multisource collector, throttle, proposal/messaging abstractions | `danzaboss/research/squad.py`, `danzaboss/research/sources.py` |
| Research pipeline (external) | YouTube -> NotebookLM ingestion, outside `danzaboss/` | `tools/research-pipeline/yt_search.py` |

## Pattern Overview

**Overall:** Layered governance kernel + blackboard-coordinated multi-agent orchestration,
wrapped around a stdlib-only Python "brain" package. The prompt layer (`.claude/`) is
declarative policy read by whichever AI environment is active; the Python layer
(`danzaboss/`) is the only executable enforcement/state mechanism, invoked either by the
`danza` CLI directly or via Claude Code's hook protocol (stdin/stdout JSON).

**Key Characteristics:**
- **Star topology for agents.** Only `tony-d-orchestrator` spawns driver agents; drivers
  never call each other, coordinating exclusively through `.danza/` state files (a
  blackboard pattern) — see `.claude/skills/danza/SKILL.md` and `CLAUDE.md`.
- **Fail-open hooks, fail-closed state.** Claude Code PreToolUse/Stop hook handlers always
  `exit 0` and default to `allow` on internal error (`danzaboss/cli.py:_cmd_hook`,
  `danzaboss/cortex/commands.py` hook handlers) so a bug in DANZA never bricks a session;
  but state mutation (`kernel/state.py`, `security/capabilities.py`) raises (`StateError`,
  `CapabilityError`) on any invalid transition — validation never silently continues.
- **Execution profiles gate everything.** `danzaboss/kernel/profile.py` resolves one of
  `OS_DEV` (Layer 0, building the OS itself, ceremony off) / `OS_BOOT_TEST` (Layer 2 boot
  validation) / `APP_BUILD` (Layers 2-3, building a user app) via a deterministic 3-step
  resolution order (env var -> `.danza/runtime/profile.json` -> heuristic on
  `team-state.json` existence). Every guard, gate, and memory-capture decision consults the
  active profile rather than hardcoding runtime law.
- **Pure decision functions, impure shells.** Guards (`hooks/guards.py`), gates
  (`hooks/gates.py`), the scheduler (`kernel/scheduler.py`) and the conductor's `decide()`
  (`workstation/conductor.py`) are pure `(state, config) -> Decision` functions, unit-tested
  without I/O; the CLI/hook dispatcher shells around them handle stdin/stdout/filesystem.
- **Blackboard state, not message passing.** Agents/AI environments do not call each other's
  APIs. They read and merge into shared files (`.danza/handoff.md`,
  `.danza/runtime/team-state.json`, `.danza/system-map.md`) — Constitution Rule 45 makes
  `team-state.json` the machine-checkable source of truth for turn ownership.
- **Stdlib-only OS core.** `danzaboss/` has zero third-party runtime dependencies (Neon/
  Postgres support in `cortex/neon_backend.py` is optional and only used if a live DSN is
  configured); this is an explicit constraint stated in `CLAUDE.md` and enforced by
  `danzaboss/run_tests.sh` running via bare `python3 -m unittest`.

## Layers

**Prompt/Policy Layer (`.claude/`):**
- Purpose: Defines agent roles, the 45-rule constitution, and the ignition skill.
- Location: `.claude/agents/`, `.claude/rules/constitution.md`, `.claude/skills/danza/SKILL.md`
- Contains: Markdown agent prompts, rule text, hook wiring (`.claude/settings.json`)
- Depends on: Nothing (source of truth for behavior)
- Used by: Whichever AI environment is currently active; immutable without user approval (Rule 37)

**Shared-Brain State Layer (`.danza/`):**
- Purpose: Cross-turn, cross-environment blackboard — the only durable record of project state
- Location: `.danza/*.md`, `.danza/runtime/*.json`, `.danza/cortex/cortex.db`
- Contains: Turn baton (`handoff.md`), system map, feature list, append-only logs, machine
  state (`team-state.json`, `profile.json`), CORTEX SQLite store
- Depends on: `danzaboss/kernel/state.py` for schema validation and legal transitions
- Used by: All agents (read), orchestrator + kernel (write), CLI (`danza profile`, `danza cortex`)

**Brain / Governance Kernel (`danzaboss/kernel/`, `danzaboss/hooks/`, `danzaboss/security/`):**
- Purpose: Enforces the constitution mechanically — turn lock, hard stops, file protection,
  capability least-privilege, execution profile resolution, verification tiers
- Location: `danzaboss/kernel/*.py`, `danzaboss/hooks/*.py`, `danzaboss/security/capabilities.py`
- Contains: Pure decision functions + a thin dispatcher that maps Claude Code hook events
- Depends on: `.danza/runtime/*.json` for state; nothing external
- Used by: `danzaboss/cli.py` (`hook` subcommand), CORTEX hook handlers

**Cognitive Memory (`danzaboss/cortex/`):**
- Purpose: Observation capture, SQLite/Postgres persistence, retrieval ranking, context
  injection, knowledge graph, MCP read surface — the strongest implemented subsystem
- Location: `danzaboss/cortex/` (25 modules) + `danzaboss/cortex/ui/` (local dashboard)
- Contains: `store.py`/`sqlite_backend.py`/`neon_backend.py` (persistence),
  `retrieve.py`/`intent.py`/`explain.py` (ranking), `inject.py`/`assemble.py` (context build),
  `federate.py`/`factory.py` (L4/L5 global merge), `mcp_server.py` (stdio JSON-RPC)
- Depends on: `danzaboss/kernel/profile.py` (memory diet per profile), `danzaboss/hooks/gates.py`
- Used by: `danzaboss/cortex/commands.py` (CLI/hook surface), `danza cortex mcp` external clients

**Workstation (`danzaboss/workstation/`):**
- Purpose: Onboarding wizard, spec/plan compilation, relay conductor, session hosts
  (tmux/headless), runner registry — the operational execution loop for a target build
- Location: `danzaboss/workstation/*.py`
- Contains: `wizard.py`/`planner.py`/`compiler.py` (spec-to-plan), `conductor.py` (relay
  postman: watches `team-state.json`, ignites boss sessions), `hosts.py` (TmuxHost/
  HeadlessHost), `runners.py` (AI-CLI detection/registry), `checkpoints.py`, `tree.py`
- Depends on: `danzaboss/kernel/state.py` (StateManager, TeamState)
- Used by: `danzaboss/cli.py` (`runners`, `conduct` subcommands)

**Planning/Orchestration (`danzaboss/planning/`, `danzaboss/orchestration/`):**
- Purpose: Verifiable-task decomposition gate; dependency/write-conflict-aware parallel
  dispatch wave planning
- Location: `danzaboss/planning/decompose.py`, `danzaboss/orchestration/parallel.py`
- Depends on: Nothing external; deterministic pure logic
- Used by: Workstation planner, future multi-agent dispatch

**Legacy Memory/Context (`danzaboss/memory/`, `danzaboss/context/`):**
- Purpose: Older JSONL-based memory + context pipeline, predates CORTEX
- Location: `danzaboss/memory/store.py`, `danzaboss/context/pipeline.py`
- Status: overlapping with CORTEX per `ARCHITECTURE.md` (repo root) and `STATUS.md`; not
  yet consolidated — see `.planning/codebase/CONCERNS.md` if generated

**Runtime Adapters (`danzaboss/runtime/`):**
- Purpose: Generic, app-agnostic "learn any repo" and "run its real tests" primitives
- Location: `danzaboss/runtime/scan.py` (`profile_repo`), `danzaboss/runtime/verify.py`
  (`run_verification`), `danzaboss/runtime/runner.py`
- Used by: `danzaboss/cli.py` `scan`/`verify` subcommands, onboarding

**Observability/Selftest (`danzaboss/observability/`, `danzaboss/selftest/`):**
- Purpose: Structured JSONL span tracing (anti-theatre evidence); cold-start harness that
  validates the OS itself before any promotion
- Location: `danzaboss/observability/trace.py`, `danzaboss/selftest/harness.py`
- Used by: `danzaboss/cli.py` `selftest` subcommand, CI-style self-validation

**External Senses (`tools/research-pipeline/`):**
- Purpose: YouTube -> NotebookLM research helper, outside the stdlib-only `danzaboss/` package
- Location: `tools/research-pipeline/yt_search.py`, `tools/research-pipeline/SKILL.md`
- Depends on: External APIs (not stdlib-constrained)
- Used by: Carmella (Researcher) driver agent, gated by `research_requires_approval` in every profile

## Data Flow

### Turn/Session Activation ("Who's the Boss?")

1. User says trigger phrase; Claude Code loads `.claude/skills/danza/SKILL.md`, responds
   "TONY DANZA!" (`.claude/skills/danza/SKILL.md:19-21`)
2. Skill spawns `tony-d-orchestrator` agent, which reads `CLAUDE.md` and
   `.claude/rules/constitution.md` (`.claude/skills/danza/SKILL.md:36-37`)
3. Mode detection: read `.danza/handoff.md` — "No handoff yet." = NEW PROJECT;
   real turn data = CONTINUE (Constitution Rule 39)
4. Orchestrator reads `.danza/runtime/team-state.json` to confirm turn ownership
   (Constitution Rule 45; validated by `danzaboss/kernel/state.py`)
5. Run log created at `.danza/logs/NNN.md` (next sequential number; Constitution Rule 40)
6. Orchestrator spawns driver agents as needed (star topology); each driver reads/writes
   `.danza/` state files directly — no agent-to-agent calls
7. Self-audit before handoff (Rule 9/43): every checklist item requires a pasted tool-result
   or file diff as evidence
8. Orchestrator updates `.danza/handoff.md` and `.danza/runtime/team-state.json`
   (`current_boss`, `turn_number++`, `status`) — turn passes to next boss

### Claude Code Hook Path (PreToolUse)

1. Claude Code invokes `PYTHONPATH=. python3 -m danzaboss.cli hook pretooluse` with event
   JSON on stdin (`danzaboss/cli.py:_cmd_hook`, line 83)
2. Payload parsed into a `ToolEvent` (`danzaboss/hooks/events.py`)
3. Active profile resolved via `danzaboss.kernel.profile.active_profile()`
   (`danzaboss/cli.py:106`)
4. `file_protection_guard` runs first (templates/`.claude/`/logs), then `hard_stop_guard`
   (auth/payment/schema/destructive) (`danzaboss/cli.py:116-128`)
5. Decision emitted as `{"hookSpecificOutput": {...}}` JSON on stdout, exit 0 always
   (fail-open on internal error, fail-closed only on a real policy hit)

### CORTEX Session-Start Context Injection

1. `danza cortex hook session_start` invoked at session boot
   (`danzaboss/cortex/commands.py:_hook_session_start`, line 39)
2. `CaptureLog.open_session()` opens a session in the events log
3. Store housekeeping: `store.age()` then `learn(store)` run before context assembly
   (scheduler tick semantics)
4. Profile gate: if `active_profile(root).session_inject` is False (OS_DEV), no context is
   injected — store housekeeping still runs
5. `build_context()` assembles the retrieval package; if non-empty, printed as
   `additionalContext` in the `SessionStart` hook JSON

### Relay/Conductor Loop (Workstation)

1. `danza conduct <root>` loads `runners.json`, resolves `session_host` via `pick_host()`
   (`danzaboss/cli.py:_cmd_conduct`, lines 192-255)
2. `Conductor.run()` (`danzaboss/workstation/conductor.py`) polls `team-state.json` on a
   tick interval, reading state via `StateManager` (`danzaboss/kernel/state.py`) — never
   holding a turn itself (it is a "postman," not a boss, per file docstring)
3. Pure `decide(state, watch) -> Action` table: `HALT_BLOCKED` (status=blocked) outranks
   `STOP_VALVE` (dead-session threshold) outranks `IGNITE`/`WAIT`
   (`danzaboss/workstation/conductor.py:56-76`)
4. On `IGNITE`, spawns a fresh boss session through the resolved host (`TmuxHost` or
   `HeadlessHost`, `danzaboss/workstation/hosts.py`)
5. Statelessness is the crash-recovery story: a crashed conductor restarts with a fresh
   `Watch` and re-reads `team-state.json`

**State Management:**
- Turn ownership: single JSON file (`.danza/runtime/team-state.json`), validated schema,
  deterministic transition table in `danzaboss/kernel/state.py` (`_TRANSITIONS`)
- Execution profile: resolved fresh on every call, 3-step deterministic order, no caching
  across processes (`danzaboss/kernel/profile.py:active_profile`)
- CORTEX memory: SQLite file per repo (`.danza/cortex/cortex.db`), optional federated
  global store (`~/.danza/cortex/global.db` or Neon DSN)
- No in-process shared mutable state between CLI invocations — every `danza` command is a
  fresh process reading files from disk

## Key Abstractions

**Decision (guards/gates result type):**
- Purpose: Uniform pass/fail/reason result for every guard and gate
- Examples: `danzaboss/hooks/events.py` (`Decision`), consumed throughout `hooks/guards.py`, `hooks/gates.py`
- Pattern: `Decision.ok(...)` / deny with `.allow=False, .reason=str`

**Profile (execution mode):**
- Purpose: Single dataclass bundling every policy knob (ceremony, memory level, hook
  activation, spawn permission) keyed by layer/mode
- Examples: `danzaboss/kernel/profile.py` — `OS_DEV`, `OS_BOOT_TEST`, `APP_BUILD` frozen dataclasses in `PROFILES` dict
- Pattern: Resolve-once-per-call via `active_profile()`; every gate/guard/memory decision reads fields off the resolved `Profile`, never re-implements policy

**TeamState / StateManager:**
- Purpose: Typed, schema-validated view of turn ownership, mode (`continuous`/`relay`),
  feature-completion counters
- Examples: `danzaboss/kernel/state.py`
- Pattern: All mutation goes through `StateManager.transition()`; direct field writes bypass validation and are forbidden by convention

**Observation (CORTEX memory unit):**
- Purpose: The atomic unit of cognitive memory — confidence, relevance, lifecycle fields
- Examples: `danzaboss/cortex/observation.py`
- Pattern: Captured via `extract.py`/`events.py`, merged/upserted into `store.py`, ranked by `retrieve.py`, promoted by usage-count in `learn.py`

**Action (Conductor state machine):**
- Purpose: Enum of the conductor's only possible outputs per tick
- Examples: `danzaboss/workstation/conductor.py` — `IGNITE`, `WAIT`, `HALT_BLOCKED`, `STOP_DONE`, `STOP_VALVE`
- Pattern: Pure `decide()` function ordered by human-needed-state precedence

**GuardConfig:**
- Purpose: Externalizes all app-specific regex/paths so guards stay app-agnostic
- Examples: `danzaboss/hooks/guards.py` (`auth_patterns`, `payment_patterns`, `schema_patterns`, `destructive_cmds`, `template_glob`, `immutable_prefix`)
- Pattern: Dataclass with `field(default_factory=...)` lists; guards never hardcode a pattern inline

## Entry Points

**`danza` CLI (`danzaboss/cli.py`):**
- Location: `danzaboss/cli.py:main()`
- Triggers: `PYTHONPATH=. python3 -m danzaboss.cli <command> ...`
- Responsibilities: Dispatches to `scan`, `verify`, `selftest`, `hook`, `cortex`, `profile`,
  `tier`, `runners`, `conduct` — the only way any AI environment or hook talks to the brain

**Claude Code hooks (`.claude/settings.json` -> `danzaboss.cli hook`):**
- Location: `danzaboss/cli.py:_cmd_hook`, `danzaboss/hooks/dispatcher.py`
- Triggers: Claude Code's `PreToolUse` and `Stop` lifecycle events, JSON on stdin
- Responsibilities: Fail-open governance enforcement (hard stops, file protection)

**Ignition skill (`.claude/skills/danza/SKILL.md`):**
- Location: `.claude/skills/danza/SKILL.md`
- Triggers: User says "Who's the Boss?"
- Responsibilities: Spawns `tony-d-orchestrator`; hands off all further logic to it

**CORTEX MCP server (`danzaboss/cortex/mcp_server.py`):**
- Location: `danza cortex mcp` (invoked via `danzaboss/cli.py` -> `cortex_commands.main`)
- Triggers: External MCP client connecting over stdio JSON-RPC
- Responsibilities: Read-only surface for `search`/`get`/`retrieve`/`context`

**Conductor relay loop (`danzaboss/workstation/conductor.py`):**
- Location: `danza conduct <root>` (`danzaboss/cli.py:_cmd_conduct`)
- Triggers: Manual invocation to run unattended relay mode against a project root
- Responsibilities: Watches `team-state.json`, ignites boss sessions via tmux/headless hosts

## Architectural Constraints

- **Threading:** Single-threaded, process-per-invocation. No async runtime; the conductor
  loop (`danzaboss/workstation/conductor.py`) uses a synchronous `time`-based poll interval,
  not threads or asyncio.
- **Global state:** No module-level singletons in `danzaboss/`; every command re-reads state
  from disk (`.danza/runtime/*.json`, `.danza/cortex/cortex.db`) on each invocation. The
  closest thing to global state is the CORTEX SQLite file itself and the optional global
  federation DB at `~/.danza/cortex/global.db`.
- **Circular imports:** None observed; dependency direction is strictly
  `cli.py -> {kernel, hooks, cortex, workstation, runtime, selftest} -> {security, events}`.
  `hooks/dispatcher.py` imports `security/capabilities.py` one-way.
- **Stdlib-only in `danzaboss/`:** No pip installs required to run `danzaboss/run_tests.sh`;
  the only optional external dependency is a Postgres driver for `cortex/neon_backend.py`,
  used only if `DANZA_CORTEX_GLOBAL_DSN` is configured.
- **Fail-open vs fail-closed split:** Hook handlers (`cli.py:_cmd_hook`, CORTEX hook
  handlers in `commands.py`) always exit 0 and default to `allow`/silent-skip on internal
  error. State mutation and validation (`kernel/state.py`, `security/capabilities.py`)
  raise (`StateError`, `CapabilityError`) and never silently continue past a bad state —
  this split is deliberate and documented in module docstrings, not an inconsistency.
- **Immutable `.claude/` at runtime:** Constitution Rule 37 — files under `.claude/` are
  never written by agents during execution without explicit user approval; enforced
  mechanically by `file_protection_guard` in `danzaboss/hooks/guards.py`
  (`immutable_prefix = ".claude/"`), with an OS_DEV-only pre-approval bypass
  (`claude_write_approval` field on `Profile`).

## Anti-Patterns

### Theatre Orchestration

**What happens:** An orchestrating AI narrates or describes sub-agent work ("Samantha
mapped the system...") without actually dispatching a sub-agent tool call.
**Why it's wrong:** Constitution Rule 42 makes this an automatic self-audit failure; no
verifiable artifact exists to prove the work happened.
**Do this instead:** Every claimed sub-agent invocation must have a corresponding
tool-result block pasted into `.danza/decision-log.md` as evidence (Rule 43). See
`.claude/rules/constitution.md` Rules 42-43.

### Blind State Overwrite

**What happens:** Writing a new version of a `.danza/` state file (e.g. `system-map.md`,
`handoff.md`) that discards existing content instead of merging.
**Why it's wrong:** Constitution Rule 35 — state files must be read first, then merged;
blind overwrites destroy accumulated shared-brain context that other AI environments depend on.
**Do this instead:** Read the current file, merge new information into the existing
structure, write the merged result. Logs (Rule 36) go further — append-only, never edit
existing entries.

### Silent Assumption in the Builder

**What happens:** Jonathan (Builder) writes code assuming a file, dependency, or data
structure exists without confirming it first.
**Why it's wrong:** Constitution Rule 25 (Builder Verification Lock) — silent assumptions
are an explicit violation; Rule 1 (No Assumptions) makes files/state/onboarding answers the
only valid source of truth.
**Do this instead:** Confirm target file, dependencies, and data structures exist before
writing. If any are missing, STOP and notify Tony D.

## Error Handling

**Strategy:** Split by trust boundary. Anything reachable from an external environment event
(Claude Code hook stdin) fails open (never blocks the session on an internal bug). Anything
that is internal state mutation fails closed (raises on invalid data, e.g.
`danzaboss/kernel/state.py:StateError`, `danzaboss/security/capabilities.py:CapabilityError`).

**Patterns:**
- Hook handlers wrap all logic in `try/except Exception` and emit `allow` on any internal
  error, logging the error to stderr (`danzaboss/cli.py:131-133`)
- Domain-specific exceptions (`ConductorError`, `RunnerError`, `HostError`, `StateError`,
  `CapabilityError`) are raised for genuine policy/config violations and caught at the CLI
  boundary to print a one-line stderr message + nonzero exit, never a raw traceback
  (`danzaboss/cli.py:_cmd_conduct`, lines 232-251)
- `active_profile()` raises `ValueError` on an explicitly configured but unknown profile
  name (fail closed on bad config) even though its hook callers still wrap it in their
  fail-open handler (`danzaboss/kernel/profile.py:108-131`)

## Cross-Cutting Concerns

**Logging:** Two channels — append-only markdown logs in `.danza/` (`decision-log.md`,
`turn-log.md`, `logs/NNN.md`) written by agents per Constitution Rule 36, and structured
JSONL spans from `danzaboss/observability/trace.py` intended as anti-theatre evidence.

**Validation:** Schema validation is explicit and centralized per subsystem —
`TeamState.validate()` in `danzaboss/kernel/state.py`, `Profile` frozen dataclasses in
`danzaboss/kernel/profile.py`, capability checks in `danzaboss/security/capabilities.py`.
No implicit/duck-typed validation.

**Authentication/Authorization:** Not user-facing auth (DANZA-OS is a local dev toolkit).
"Authorization" here means capability-based least-privilege for agent actions
(`danzaboss/security/capabilities.py`) plus the hard-stop guards that block edits to
auth/payment/schema code in a *target* app (Constitution Rules 13-16).

---

*Architecture analysis: 2026-07-08*
