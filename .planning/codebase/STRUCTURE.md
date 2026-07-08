# Codebase Structure

**Analysis Date:** 2026-07-08

## Directory Layout

```
DANZA-OS/
├── .claude/                     # System configuration — IMMUTABLE at runtime without user approval (Rule 37)
│   ├── agents/                  # 8 role-tagged agent prompt definitions
│   ├── rules/constitution.md    # 45 unbreakable rules, loaded every turn
│   ├── skills/danza/SKILL.md    # Ignition: "Who's the Boss?" -> spawns orchestrator
│   ├── settings.json            # Live Claude Code hook wiring
│   ├── settings.local.json      # Local hook overrides (not committed policy)
│   └── settings.example.json    # Reference hook config
├── .danza/                      # Runtime shared-brain state (survives turns & AI environments)
│   ├── handoff.md                # Turn baton (state, merge-only)
│   ├── system-map.md             # Samantha's living blueprint (state, merge-only)
│   ├── feature-list.md           # Work queue (being superseded by workstation spec/plan)
│   ├── decision-log.md           # Angela's decisions (append-only)
│   ├── turn-log.md               # Turn history (append-only)
│   ├── build-history.md          # Append-only build record
│   ├── patterns.md               # Append-only prevention rules
│   ├── onboarding-answers.md     # User's onboarding responses (state)
│   ├── onboarding-misses.md      # Append-only gap log
│   ├── self-assessment-log.md    # Append-only self-audit log
│   ├── stack-philosophy.md       # Target-app stack decision guide (free/lightweight/local-first)
│   ├── design-tokens.json        # Hank's design system state
│   ├── checkpoints.json          # Workstation checkpoint state
│   ├── rankings.json             # Research/decision rankings state
│   ├── *-template.md             # READ-ONLY templates (Rule 34) — never edited, only read
│   ├── logs/NNN.md               # Per-run records (append-only, historical, sequential)
│   ├── memory/                   # Legacy prose memory docs (architecture, lexicon, overview)
│   ├── onboarding/README.md      # Onboarding process notes
│   ├── design/README.md          # Design process notes
│   ├── cortex/                   # This repo's local CORTEX SQLite state
│   │   ├── cortex.db              # Observations, sessions, events, graph, usage logs
│   │   ├── project.json           # Resolved project identity for CORTEX
│   │   └── ui-settings.json       # CORTEX dashboard settings
│   └── runtime/                  # Machine-checkable runtime state (created by kernel)
│       ├── team-state.json        # Turn ownership source of truth (Rule 45)
│       ├── profile.json           # Explicit execution-profile override
│       └── claude-approval        # Sentinel file unlocking .claude/ writes (gitignored)
├── danzaboss/                    # THE BRAIN — Python, stdlib-only, 694 tests
│   ├── cli.py                     # `danza` command entry point — the only executable seam
│   ├── kernel/                    # profile.py, scheduler.py, state.py, tiers.py
│   ├── hooks/                     # dispatcher.py, guards.py, gates.py, events.py
│   ├── security/                  # capabilities.py — least-privilege + audit trail
│   ├── cortex/                    # Cognitive memory subsystem (25 modules) + ui/ dashboard
│   ├── workstation/               # Onboarding, planner, conductor, hosts, runners
│   ├── planning/                  # decompose.py — verifiable-task gate
│   ├── orchestration/             # parallel.py — dependency-aware dispatch waves
│   ├── memory/                    # store.py — legacy JSONL memory (overlaps CORTEX)
│   ├── context/                   # pipeline.py — legacy context engineering pipeline
│   ├── observability/             # trace.py — structured JSONL spans
│   ├── selftest/                  # harness.py — cold-start self-test
│   ├── runtime/                   # scan.py, verify.py, runner.py — app-agnostic adapters
│   ├── tests/                     # 62 test_*.py files + _bootstrap.py, mirrors package layout
│   └── run_tests.sh               # Test runner (sets PYTHONPATH, isolates CORTEX global DB)
├── docs/                         # Design docs, ADRs, research, lexicon
│   └── superpowers/
│       ├── specs/                 # Dated design specs (e.g. cortex-design.md)
│       └── plans/                 # Dated DONE-*.md phase completion plans
├── tools/research-pipeline/      # YouTube -> NotebookLM research helper (external senses)
│   ├── SKILL.md
│   └── yt_search.py
├── .agents/                      # Empty at present (reserved)
├── .codex/skills/                # Codex-environment skill mirror (danza-forensic-auditor)
├── .superpowers/sdd/             # Spec-driven-development working artifacts (task briefs/reports/diffs)
├── .planning/codebase/           # THIS document set (codebase maps)
├── CLAUDE.md                     # Root entry document — read first by any AI environment
├── README.md, STATUS.md, ARCHITECTURE.md, ROADMAP.md, RUNBOOK.md, CORTEX.md, INSTALL.md
│                                  # Top-level truth docs (repo root; separate from generated .planning/codebase docs)
└── DONE-CHANGELOG-REPORT.md      # Changelog/audit report
```

## Directory Purposes

**`.claude/`:**
- Purpose: Defines how any AI environment behaves in this repo — agent roles, rules, hook wiring
- Contains: Markdown agent prompts, the constitution, the ignition skill, Claude Code settings JSON
- Key files: `.claude/rules/constitution.md`, `.claude/skills/danza/SKILL.md`, `.claude/agents/tony-d-orchestrator.md`

**`.danza/`:**
- Purpose: The shared "blackboard" — durable state every agent/AI environment reads and merges into across turns
- Contains: State files (merge-only), append-only logs, read-only templates, machine-checkable JSON, CORTEX SQLite DB
- Key files: `.danza/handoff.md`, `.danza/runtime/team-state.json`, `.danza/system-map.md`, `.danza/cortex/cortex.db`

**`danzaboss/`:**
- Purpose: The only executable enforcement/state/memory engine — "THE BRAIN"
- Contains: Python stdlib-only modules organized by responsibility (kernel, hooks, security,
  cortex, workstation, planning, orchestration, memory, context, observability, selftest, runtime)
- Key files: `danzaboss/cli.py` (entry point), `danzaboss/run_tests.sh` (694 tests)

**`danzaboss/cortex/`:**
- Purpose: Cognitive memory subsystem — the strongest implemented part of the OS
- Contains: Persistence (`store.py`, `sqlite_backend.py`, `neon_backend.py`), retrieval
  (`retrieve.py`, `intent.py`, `explain.py`, `quality.py`), context assembly (`inject.py`,
  `assemble.py`, `compress.py`), graph (`graph.py`), CLI surface (`commands.py`), MCP server
  (`mcp_server.py`), federation (`federate.py`, `factory.py`), local dashboard (`ui/server.py`)
- Key files: `danzaboss/cortex/commands.py` (393 lines, largest module), `danzaboss/cortex/store.py`

**`danzaboss/workstation/`:**
- Purpose: The operational build loop — onboarding through unattended relay execution
- Contains: `wizard.py` (onboarding questions), `planner.py`/`compiler.py` (spec -> plan),
  `conductor.py` (relay postman), `hosts.py` (tmux/headless session backends),
  `runners.py` (AI-CLI detection registry), `checkpoints.py`, `tree.py`, `research.py`, `state.py`
- Key files: `danzaboss/workstation/conductor.py`, `danzaboss/workstation/hosts.py`

**`danzaboss/tests/`:**
- Purpose: Unit test suite mirroring the package layout, one `test_*.py` per module
- Contains: 62 test files (`test_cortex_*.py` is the largest cluster — ~20 files;
  `test_workstation_*.py` is next largest — ~15 files)
- Generated: No (hand-written); `danzaboss/tests/.danza/cortex/` is a sandboxed test fixture DB

**`docs/`:**
- Purpose: Design notes, ADRs, dated specs and phase-completion plans
- Contains: `docs/superpowers/specs/` (design specs, e.g. `2026-07-03-cortex-design.md`),
  `docs/superpowers/plans/` (dated `DONE-*.md` phase reports)
- Key files: `docs/OS_DEV.md` (Layer-0 development constitution), `docs/danza-lexicon.md`

**`tools/research-pipeline/`:**
- Purpose: External research ingestion tool, separate from the stdlib-only `danzaboss/` package
- Contains: `yt_search.py` (YouTube search), `SKILL.md` (skill wiring)
- Generated: No; Committed: Yes

**`.superpowers/sdd/`:**
- Purpose: Spec-driven-development working artifacts (task briefs, reports, review diffs)
  from a superpowers-style planning workflow
- Contains: Dated brief/report/diff files per task
- Generated: Partially (diffs are captured output); Committed: Yes (has its own `.gitignore`)

**`.planning/codebase/`:**
- Purpose: Generated codebase maps consumed by `/gsd:plan-phase` and `/gsd:execute-phase`
- Contains: `ARCHITECTURE.md`, `STRUCTURE.md` (this file), and other focus-area docs as generated
- Generated: Yes (by the `gsd-codebase-mapper` agent); Committed: Yes

## Key File Locations

**Entry Points:**
- `danzaboss/cli.py`: `danza` CLI — dispatches all subcommands (`scan`, `verify`, `selftest`, `hook`, `cortex`, `profile`, `tier`, `runners`, `conduct`)
- `.claude/skills/danza/SKILL.md`: "Who's the Boss?" trigger — spawns the orchestrator agent
- `danzaboss/cortex/mcp_server.py`: `danza cortex mcp` stdio JSON-RPC entry point

**Configuration:**
- `.danza/runtime/profile.json`: explicit execution-profile override (`{"profile": "OS_DEV"}`)
- `.danza/runtime/team-state.json`: turn ownership + execution mode (created by kernel at activation)
- `.claude/settings.json`: live Claude Code hook wiring (do not edit casually — see `RUNBOOK.md`)
- `DANZABOSS_PROFILE` env var: highest-priority profile override (see `danzaboss/kernel/profile.py`)
- `DANZA_CORTEX_GLOBAL_DSN` env var: opts CORTEX federation into Neon/Postgres

**Core Logic:**
- `danzaboss/kernel/profile.py`: execution profile resolution (layer-aware governance)
- `danzaboss/kernel/state.py`: team-state schema validation and transitions
- `danzaboss/hooks/guards.py` + `danzaboss/hooks/gates.py`: PreToolUse/Stop enforcement
- `danzaboss/cortex/store.py` + `danzaboss/cortex/retrieve.py`: memory persistence and ranking
- `danzaboss/workstation/conductor.py`: relay execution loop

**Testing:**
- `danzaboss/tests/`: all unit tests, run via `./danzaboss/run_tests.sh`
- `danzaboss/tests/_bootstrap.py`: shared test setup/path bootstrap
- `danzaboss/selftest/harness.py`: cold-start self-test (`danza selftest`), separate from unittest suite

## Naming Conventions

**Files:**
- Python modules: `snake_case.py` matching their primary responsibility noun (e.g. `store.py`, `guards.py`, `conductor.py`)
- Test files: `test_<module_or_feature>.py`, prefixed `test_cortex_*` or `test_workstation_*` for subsystem clusters
- `.danza/` state docs: `kebab-case.md` (e.g. `decision-log.md`, `self-assessment-log.md`)
- `.danza/` templates: `<name>-template.md` suffix — signals read-only (Rule 34)
- Run logs: zero-padded sequential `NNN.md` (e.g. `001.md`, `002.md`) under `.danza/logs/`
- Docs with lifecycle state: `DONE-<description>.md` prefix marks a completed plan/mission in `docs/superpowers/plans/`

**Directories:**
- Dotted config/state roots: `.claude/`, `.danza/`, `.codex/`, `.superpowers/`, `.planning/` — each owned by a distinct tool/workflow
- `danzaboss/<responsibility>/`: one directory per architectural concern (kernel, hooks, security, cortex, workstation, planning, orchestration, memory, context, observability, selftest, runtime), each with its own `__init__.py`

## Where to Add New Code

**New governance rule or guard:**
- Pattern/config: add regex or flag to `GuardConfig` in `danzaboss/hooks/guards.py`
- Enforcement: wire into `hooks/dispatcher.py` `pre_tool_use()` or `stop()`
- Tests: `danzaboss/tests/test_hooks.py`

**New execution-profile behavior:**
- Add/modify a field on the `Profile` dataclass and each named profile in `danzaboss/kernel/profile.py`
- Tests: `danzaboss/tests/test_profile.py`

**New CORTEX capability (retrieval, capture, etc.):**
- Implementation: new module under `danzaboss/cortex/`, wired through `danzaboss/cortex/commands.py`
- CLI surface: add subcommand handling in `commands.py` `main()`
- Tests: `danzaboss/tests/test_cortex_<feature>.py`

**New workstation capability (onboarding, planning, execution):**
- Implementation: new module under `danzaboss/workstation/`
- CLI surface: wire into `danzaboss/cli.py` if it needs a top-level command
- Tests: `danzaboss/tests/test_workstation_<feature>.py`

**New agent role:**
- Prompt: new `.claude/agents/<name>-<role>.md` file, following existing role-tagged naming (`<firstname>-<role>.md`)
- Update roster table in `CLAUDE.md` and `.claude/rules/constitution.md`
- Requires explicit user approval — `.claude/` is immutable at runtime (Rule 37)

**Utilities:**
- Shared pure helpers within a subsystem live alongside their consumers (no separate `utils/` directory pattern observed) — e.g. `danzaboss/hooks/events.py` holds `ToolEvent`/`Decision` shared by `guards.py` and `gates.py`

## Special Directories

**`danzaboss/tests/.danza/cortex/`:**
- Purpose: Sandboxed fixture CORTEX database used only during the test suite run
- Generated: Yes (by test setup); Committed: Check `.gitignore` before assuming — treat as disposable

**`.danza/logs/`:**
- Purpose: Append-only historical run records, one file per session activation
- Generated: Yes (by orchestrator per Rule 40); Committed: Yes (historical record, never modified after creation)

**`.danza/cortex/`:**
- Purpose: This repo's live CORTEX SQLite state (observations, sessions, graph)
- Generated: Yes (runtime data); Committed: Yes per current repo state, but is live mutable data, not source

**`__pycache__/` (throughout `danzaboss/`):**
- Purpose: Python bytecode cache
- Generated: Yes; Committed: No (should be gitignored)

**`.playwright-mcp/`:**
- Purpose: Playwright MCP tool working directory (browser automation artifacts)
- Generated: Yes; Committed: Check `.gitignore`

---

*Structure analysis: 2026-07-08*
