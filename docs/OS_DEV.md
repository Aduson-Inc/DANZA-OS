# OS_DEV — The Development Constitution (Layer 0 Contributor Guidelines)

> Mission C4.5 deliverable. This document governs sessions that IMPROVE DANZABOSS
> (Layer 0). The runtime Constitution (`.claude/rules/constitution.md`) governs
> sessions that RUN DANZABOSS (Layers 2–3). Different layers, different rules.
>
> Litmus test before acting: **"Am I changing the factory, or running the factory?"**

## The layer model

| Layer | What it is | Which rules bind |
|---|---|---|
| 0 | Fable/Claude improving DANZABOSS itself | this document |
| 1 | This repo — the source/boot image, not a running OS | none (it's data) |
| 2 | Activated DANZABOSS after "Who's the Boss?" in a target repo | runtime Constitution |
| 3 | The agent workforce (Tony D, Jonathan, Samantha…) | runtime Constitution |
| 4 | The user's app being built | app standards via Jonathan |

## Execution profiles

The profile decides which rules bind, which hooks run, what memory is recorded,
and how much ceremony is allowed. Source of truth: `danzaboss/kernel/profile.py`.

| | OS_DEV | OS_BOOT_TEST | APP_BUILD |
|---|---|---|---|
| Purpose | improve the OS | validate the boot image in a disposable repo | build the user app |
| Constitution binding | no (source material) | yes | yes |
| Ceremony | minimal | full | full |
| `.claude/` writes (Rule 37) | pre-approved | user approval | user approval |
| Auth/payment/schema asks (Rules 13–15) | off | on | on |
| Destructive-command deny (Rule 16) | **on** | **on** | **on** |
| Turn gates (anti-theatre/verify/regression) | off | on | on |
| Handoff/self-audit reports | not required | required | required |
| Memory level | lightweight | normal | normal |
| Distillation noise floor | 3 significant events | every session | every session |
| Agent roster may spawn | no (subagents only when the task clearly benefits) | yes | yes |
| External research (Tavily etc.) | **explicit user approval** | **explicit user approval** | **explicit user approval** |

**Resolution order** (deterministic, first hit wins):
1. `DANZABOSS_PROFILE` environment variable
2. `.danza/runtime/profile.json` — `{"profile": "OS_DEV"}` (local-only, gitignored)
3. Heuristic: `.danza/runtime/team-state.json` exists (created at activation, Rule 45)
   → `APP_BUILD`; otherwise → `OS_DEV`

`OS_BOOT_TEST` is **never inferred** — boot tests opt in via 1 or 2, in a
separate disposable worktree/repo, never in the source tree.

Inspect the active profile any time: `PYTHONPATH=. python3 -m danzaboss.cli profile`

## Hook audit (which hooks run where)

| Hook / guard | OS_DEV | OS_BOOT_TEST | APP_BUILD | Classification |
|---|---|---|---|---|
| Destructive-command deny (`hard_stop_guard`, Rule 16) | on | on | on | always needed |
| Auth/payment/schema escalation (Rules 13–15) | off | on | on | runtime only — the patterns protect app code, and misfire on OS source (e.g. "session" in `sqlite_backend.py`) |
| Template read-only (Rule 34) | on | on | on | always needed (cheap, prevents accidents) |
| `.claude/` immutability (Rule 37) | pre-approved | on | on | runtime only — Layer 0 edits `.claude/` as source |
| Log overwrite deny (Rule 36) | on | on | on | always needed (cheap) |
| Capability / turn-lock / scope / context-budget guards (`HookDispatcher`) | not wired (no agents) | on | on | runtime only |
| Turn gates: anti-theatre, verify-before-done, regression (Rules 5, 42–43) | off | on | on | runtime only — OS_DEV honesty is enforced by test tiers at commit instead |
| CORTEX SessionStart inject | on | on | on | always needed (read-only, token-budgeted) |
| CORTEX PostToolUse capture | significant events only | everything (redacted) | everything (redacted) | profile-tuned |
| CORTEX Stop distillation gate | blocks only at ≥ 3 pending significant events | every session | every session | profile-tuned |

## Memory policy (CORTEX diet)

Memory event levels: `none` · `lightweight` · `normal` · `critical`.
OS_DEV defaults to **lightweight**: only file mutations and state-changing
commands (`git commit/push/merge/revert/rebase`, test runs, `danzaboss.cli`
invocations) are captured; reads and trivial shell never become memory pressure.

Distill an observation only for: architectural decisions, bugs found/fixed,
verified milestones, user preferences, conventions, regressions, accepted
research results, or implementation facts a future session genuinely needs.
Never for: file reads, tiny tweaks, repeated test runs, obvious commands,
temporary debugging steps, or subagent status updates.

Write observations in plain language a non-engineer can skim — title says what
happened, summary says why it matters. No invented jargon.

## Test tiers (cheapest safe verification)

Source of truth: `danzaboss/kernel/tiers.py`. Ask the CLI:
`PYTHONPATH=. python3 -m danzaboss.cli tier <paths...> [--commit]`

| Tier | Name | When | Verification |
|---|---|---|---|
| 0 | none | docs/comments only | read the diff |
| 1 | smoke | UI/CSS/static | lint + browser/render check |
| 2 | targeted | one plain module | that module's test file |
| 3 | subsystem | hooks / CORTEX / CLI / kernel / runtime | the subsystem's tests |
| 4 | full | security, state, broad sweeps, **any commit** | `./danzaboss/run_tests.sh` |
| 5 | boot | boot-image behavior (`.claude/` skills/agents/rules) | activate in a disposable OS_BOOT_TEST repo |

The recommendation is the lowest safe tier; commits always demand at least
Tier 4 (never-regress line), and boot-surface changes demand Tier 5.

## Token budget policy

**Use the cheapest process that safely proves the claim.** Before any major
task, weigh: expected value, needed verification tier, expected token cost,
whether subagents genuinely help (parallel independent work, context isolation),
and whether external research is justified. Heavyweight governance for
lightweight tasks is a bug, not diligence. In OS_DEV, prefer direct work over
orchestration; spawn a subagent only when it beats doing it inline.

## Research policy (Tavily and friends)

External research **never runs automatically in any profile** (enforced:
`ResearchSquad.run_cycle` fails closed without `user_approved=True`). Before
asking, present: what research is needed · why repo evidence is insufficient ·
expected cost · expected benefit · what decision it supports. After approved
research, report: key findings · sources · buildable ideas · recommendation ·
whether stored in CORTEX · freshness date.

## What OS_DEV must NOT do

- Do not delete or weaken runtime safety to save tokens — separate modes instead.
- Do not delete the Constitution, hooks, agent files, or templates (they are the product).
- Do not run "Who's the Boss?" / `/danza` in the source tree — boot-test in a disposable repo.
- Do not treat empty runtime state (`.danza/handoff.md`, logs, team-state) as bugs outside boot tests.
- Do not become Tony D while editing Tony D.
