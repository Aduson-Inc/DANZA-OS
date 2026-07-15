# DANZA-OS Product Completion Design

**Status:** Active implementation specification

**Updated:** 2026-07-15

**Release state:** Unreleased; formal qualification remains future work

## Product definition

DANZA-OS is an installable Python application that turns a target repository
into a governed `APP_BUILD` project. Tony-D — The Boss orchestrates seven named
specialists, an approved executable plan, configured AI runners, verified
atomic units, and adaptive CORTEX memory.

The product must feel like DANZABOSS, not a generic agent framework. The active
cast is:

| Character | Authoritative role | Product responsibility |
|---|---|---|
| Tony-D | The Boss | Orchestrates, selects specialists, manages state and handoffs |
| Jonathan | Builder | Writes application code |
| Samantha | Mapper | Maps the codebase and maintains its blueprint |
| Angela | Auditor | Tracks decisions, evidence, risk, and loops |
| Bonnie | QA | Tests and verifies completed work |
| Carmella | Researcher | Resolves unknowns before commitments |
| Hank | Designer | Owns the approved visual system |
| Billy | Security | Reviews security and build risk |

Mona is retired. Persistent runtime automation is internal infrastructure,
not a character, boss, or visible team member.

## Three-layer architecture

### Layer 0 — OS_DEV

The DANZA-OS source repository contains package source, tests, current
documentation, contributor instructions, and development configuration. It
cannot activate itself as APP_BUILD and does not carry a root customer-agent
payload or duplicate bootstrap state.

### Layer 1 — packaged DANZA-OS

`pyproject.toml` builds the `danza-os` package and `danza` CLI. The package
contains kernel state, hooks, planning, runners, dashboard services, CORTEX,
schemas, assets, and the sole canonical APP_BUILD payload at:

`danzaboss/product/templates/scaffold/`

The payload contains the eight prompts, runtime constitution, activation
skill, installed Claude settings and hooks, managed target-project guide, and
bootstrap `.danza` files. `danza init` copies it deterministically, preserves
user modifications, and records a content-hash manifest.

### Layer 2 — APP_BUILD

A target application initialized by `danza init` owns its copied `.claude/`
runtime, project-scoped `.danza` state, PROJECT and BUILD state, project CORTEX
data, and application source. Activation and hook tests run only in real target
repositories or disposable fixtures.

## Dashboard contract

The local dashboard exposes four product views:

1. OVERVIEW reports profile, project, team state, plan state, CORTEX activity,
   and adaptive context usage.
2. SETUP detects supported AI CLIs, displays connection state, renders the
   canonical named cast under **Who Does What**, assigns runners to specialist
   work types, and configures 2–5 verified atomic units per AI turn.
3. PROJECT handles discovery, new-project interview, existing-project audit,
   gap acknowledgement, scope editing, explicit approval, and decomposition.
4. BUILD starts and stops execution, renders executable-plan progress, exposes
   active session output and runtime activity, and advances verified units.

Tony-D must appear as `Tony-D` with role `The Boss`. Generic work types are
routing keys, not replacement identities. Internal runtime mechanics are not
shown as cast members.

## Project and execution authority

`.danza/features.json` is the approved product-scope authority.
`.danza/plan.json` is the executable-plan authority. Markdown feature and plan
documents are generated views.

Each BUILD unit follows a durable lifecycle:

```text
pending → in_progress → verified → concluded
                       ↘ blocked
```

The CLI provides `danza unit start`, `danza unit verify`, `danza unit block`,
and `danza unit conclude`. The turn quota configures verified atomic units and
is independent of memory context size. PROJECT revisions use optimistic
concurrency and force reapproval/redecomposition when approved scope changes.

## CORTEX contract

CORTEX is the canonical product memory and context subsystem. SessionStart
restores runtime state and injects relevant context; PostToolUse captures
eligible evidence; Stop processes memory and runtime gates. Retrieval budgets
are adaptive: agent role, task complexity, project state, query evidence, and
available memories determine the context slice. There is no user-facing token
dial and no second product memory dependency.

## Safety and compatibility

- OS_DEV cannot trust or execute customer runtime hooks.
- Installed hooks use the `danza` console command and fail honestly.
- Scaffolding never overwrites a user-modified target file.
- State schemas remain validated, atomic writes remain atomic, and existing
  PROJECT, BUILD, runner, hook, and CORTEX behavior is preserved unless a
  narrowly tested compatibility fix is required.
- User approval remains mandatory for destructive or high-impact decisions and
  external research.

## Completion boundaries

Phase 4.1 Task 11 owns canonical payload consolidation, OS_DEV root isolation,
named-character identity repair, prompt/runtime alignment, current
documentation, and audited repository cleanup. It requires focused payload,
scaffold, isolation, dashboard, PROJECT, BUILD, CORTEX, packaging, and full
Python-suite verification.

Phase 4.1 Task 12 remains responsible for formal browser-level Playwright
qualification, install/upgrade qualification, release-readiness evidence, and
final ship/no-ship assessment. CI, licensing, release metadata, tags, pushes,
publication, and a public release are not complete or implied by Task 11.
