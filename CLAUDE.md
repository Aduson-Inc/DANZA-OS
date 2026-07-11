# CLAUDE.md — DANZABOSS OS

> Root entry document. Any AI environment (Claude Code, Codex, Gemini, Grok…) reads
> this first on session start. It is the map; the detail lives in the files it points to.
> This file fixes the Phase-1 gap where `CLAUDE.md` was referenced by startup but never existed.

## What DANZABOSS is

DANZABOSS is a **multi-AI development operating system**: a framework of prompts + state
files that lets one or more AI environments build a *target application* under a fixed
constitution. It is not an application itself. The only executable code that ships with the
OS is the research pipeline (`tools/research-pipeline/`) and the promoted brain
(`danzaboss/` — kernel, CORTEX, hooks, research, runtime, workstation; 819 tests).

The **local repository is the single source of truth.** Never compare against GitHub or
assume an online version is newer. Local files are authoritative.

## Required reading order (every session)

1. `CLAUDE.md` (this file)
2. `.claude/rules/constitution.md` — the 45 unbreakable rules (the kernel ruleset)
3. `.danza/handoff.md` — mode detection: "No handoff yet." = NEW PROJECT; real data = CONTINUE
4. `.danza/runtime/team-state.json` — machine-checkable turn ownership (Constitution Rule 45)
5. The active `.danza/` state: `system-map.md`, `feature-list.md`, `decision-log.md`, latest `logs/NNN.md`

## Project layout

```
.claude/                     System configuration — IMMUTABLE without user approval (Rule 37)
  agents/                    8 role-tagged agent definitions (see roster below)
  rules/constitution.md      45 rules; loaded every turn
  skills/danza/SKILL.md      Ignition: "Who's the Boss?" -> spawns the orchestrator
.danza/                      Runtime state — the shared brain (survives turns & environments)
  handoff.md                 Turn baton (state)
  system-map.md              Samantha's living blueprint (state)
  feature-list.md            Work queue (state) — being superseded by spec.md/plan.md (Upgrade #3)
  decision-log.md            Angela's decisions (append-only)
  turn-log.md                Turn history (append-only)
  logs/NNN.md                Per-run records (append-only, historical)
  *-template.md              Read-only templates (Rule 34)
  runtime/team-state.json    Machine-checkable turn state (Upgrade #2; created by kernel)
danzaboss/                  THE BRAIN (promoted, authoritative) — Python, stdlib only, 819 tests
  kernel/ planning/ memory/ context/ security/ observability/ orchestration/ selftest/
  cortex/                    CORTEX cognitive memory (capture, store, FTS5, inject, extract, CLI)
  hooks/                     Governance guards + gates (capability, anti-theatre, verify, regression)
  research/                  Research squad: multisource collector, throttle, proposals, messaging
  runtime/                   scan (learn any repo) · verify (real tests) · runner
  workstation/               Onboarding + conductor relay + product dashboard: runner registry, session hosts, event loop, danza ui server ('danza runners' / 'danza conduct' / 'danza ui')
  product/                   Packaging & lifecycle: `danza init` scaffold, `danza doctor`, bundled install payload
  cli.py                     `danza` command the agents + hooks call
  tests/  run_tests.sh       819 unit tests + cold-start harness
docs/                        Design docs (architecture, ADRs, research, lexicon)
tools/research-pipeline/     YouTube -> NotebookLM research (the external senses)
RUNBOOK.md                   How to try DANZA on a real app
pyproject.toml               Package metadata — pipx install => `danza` CLI
install.sh                   Hardened curl|bash installer (pipx wrapper)
```

## Agent roster (role-tagged names)

| Name (`id`) | Layer | Writes code? | Spawns? |
|---|---|:--:|:--:|
| Tony D — Orchestrator (`tony-d-orchestrator`) | kernel | no | yes (all drivers) |
| Jonathan — Builder (`jonathan-builder`) | driver | **yes (only one)** | no |
| Samantha — Mapper (`samantha-mapper`) | driver | no | no |
| Angela — Auditor (`angela-auditor`) | driver | no | no |
| Bonnie — QA (`bonnie-qa`) | driver | no | no |
| Carmella — Researcher (`carmella-researcher`) | driver | no | no |
| Hank — Designer (`hank-designer`) | driver | no | no |
| Billy — Security (`billy-security`) | driver | no | no |

Topology is a **star**: only the orchestrator spawns drivers; drivers never call each other.
They coordinate through the orchestrator and the shared `.danza/` files (a blackboard).

## Coding standards

These apply to all executable code in the OS (`tools/`, `danzaboss/`) and to code Jonathan
writes into target projects.

- **Language/runtime:** Python 3.10+, **standard library only** in OS-level code (no pip
  installs required to run tests). Target-app stacks follow `.danza/stack-philosophy.md`
  (free-first, lightweight-first, local-first).
- **Style:** PEP 8, 4-space indent, `snake_case` functions/vars, `PascalCase` classes,
  type hints on all public functions, module + function docstrings that state *why*.
- **Fail closed:** validation and authorization raise on violation; never silently
  continue past a bad state (see `kernel/state.py`, `security/capabilities.py`).
- **Determinism:** control logic (scheduler decisions, wave planning, memory scoring) must
  be deterministic and unit-testable — no hidden randomness in decisions.
- **Tests are mandatory:** every module ships with a `tests/test_*.py`. A change is not
  "done" until `danzaboss/run_tests.sh` is green. Show test output, not a narrative (Rule 5, 43).
- **Existing style is law:** match the surrounding file before introducing any new pattern
  (Constitution Rule 4). No new frameworks without explicit user approval.
- **Append-only logs / read-only templates / merged state** — respect Rules 34–37 at all times.

## Module descriptions (v2 upgrades)

Each maps to one approved upgrade; all are unit-tested (`danzaboss/tests/`). Paths are under `danzaboss/`.

| Module | Upgrade | Responsibility |
|---|---|---|
| `kernel/state.py` | #2 | Machine-checkable `team-state.json`: schema validation, turn lock, deterministic transitions |
| `kernel/scheduler.py` | #1 | Dual-mode execution kernel: `continuous` loop vs `relay` handoff; loop safety valve |
| `planning/decompose.py` | #4 | Verifiable-task gate: a task is dispatchable only if every leaf has a concrete verification |
| `planning/spec_template.md` + `plan_schema.json` | #3 | Spec-driven development: spec → plan → atomic verifiable tasks |
| `memory/store.py` | #7 | Layered memory (semantic/episodic/procedural) with token-budgeted retrieval |
| `context/pipeline.py` | #8 | Context engineering: select → compress → isolate → compiled per-driver context |
| `security/capabilities.py` | #10 | Capability least-privilege + elevation tokens + audit trail (enforces hard stops 13–16) |
| `observability/trace.py` | #5 | Structured JSONL spans replacing prose logs; anti-theatre evidence for Rules 42–43 |
| `orchestration/parallel.py` | #9 | Parallel dispatch planner: dependency + write-conflict aware execution waves |
| `selftest/harness.py` | #6 | Cold-start self-test: validates the OS itself before any promotion |
| `kernel/profile.py` | C4.5 | Execution profiles (OS_DEV / OS_BOOT_TEST / APP_BUILD): layer-aware governance + memory diet (`docs/OS_DEV.md`) |
| `kernel/tiers.py` | C4.5 | Verification tiers 0–5: cheapest safe verification per change set (`danza tier <paths>`) |
| `cortex/mcp_server.py` + `neon_backend.py` + `factory.py` + `federate.py` | C6 | VPS-readiness: MCP stdio server (`danza cortex mcp`), Neon/Postgres adapter (parity-tested), L4/L5 global store with L2-wins federation |
| `workstation/` (`conductor.py`, `runners.py`, `hosts.py`, `planner.py`, …) | W1 | Onboarding + conductor relay engine: runner registry, tmux/headless session hosts, conductor decision loop; powers `danza runners` / `danza conduct`; product dashboard server (danza ui, Phase 2) |

## How to run the OS

- **Start / take a turn:** trigger phrase **"Who's the Boss?"** → `SKILL.md` spawns
  `tony-d-orchestrator`, which runs the mandatory startup (mode detection, run log,
  turn lock, load constitution).
- **Run the test suite:** `./danzaboss/run_tests.sh` (819 tests)
- **CORTEX memory:** `PYTHONPATH=. python3 -m danzaboss.cli cortex <search|get|observe|retrieve|context|age|learn|stats|index|graph|ui|mcp>` —
  repo-scoped cognitive memory at `.danza/cortex/cortex.db`, federated with the
  L4/L5 global store (`~/.danza/cortex/global.db`, or Neon via
  `DANZA_CORTEX_GLOBAL_DSN`); `danza cortex mcp` serves it to external MCP clients.
  On driver handoff Tony compiles role-scoped, budgeted memory with
  `cortex context --driver <agent-id> --task "…"` and pastes the returned
  `## CORTEX Context` block into each specialist's spawn prompt
  (design: `docs/superpowers/specs/2026-07-03-cortex-design.md`)
- **Product dashboard:** `PYTHONPATH=. python3 -m danzaboss.cli ui [dir] [--port N] [--no-open]` — DANZA-OS dashboard on 127.0.0.1:33100 with the CORTEX UI mounted at `/cortex/` (D4).
- **Health-check:** `PYTHONPATH=. python3 -m danzaboss.cli selftest`
- **Install as a product:** `pipx install git+https://github.com/Aduson-Inc/DANZA-OS` (or `./install.sh`);
  then `danza init <dir>` scaffolds an app repo and `danza doctor` health-checks it.
- **Execution profile:** `PYTHONPATH=. python3 -m danzaboss.cli profile` — which mode is active
  (OS_DEV = Layer 0, ceremony off; OS_BOOT_TEST / APP_BUILD = runtime law binds). See `docs/OS_DEV.md`.
- **Verification tier:** `PYTHONPATH=. python3 -m danzaboss.cli tier <paths...> [--commit]` —
  cheapest safe test level for a change set
- **Learn a target app:** `PYTHONPATH=. python3 -m danzaboss.cli scan <dir> --domain "..."`
- **Verify a change:** `PYTHONPATH=. python3 -m danzaboss.cli verify "<test cmd>" <dir>`
- **Workstation relay:** `PYTHONPATH=. python3 -m danzaboss.cli runners <dir>` (detect the runner registry) · `… conduct <dir>` (run the conductor relay loop)
- **Full runbook:** see `RUNBOOK.md`

## Guardrails recap (do not violate)

No assumptions (verify from files) · No workarounds (stop means stop) · Hard stops on
auth/payment/DB-schema/delete · Verify before "done" · Append-only logs · Immutable `.claude/`
without user approval · One turn owner at a time.
