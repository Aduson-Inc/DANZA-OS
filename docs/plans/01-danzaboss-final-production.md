# Plan 01 — DANZABOSS Final Production Version

**Date:** 2026-07-23
**Status:** APPROVED — ready to implement
**Repo:** danza-takeover clone, branch `codex/production-danzaboss-install-flow`

## Purpose

Finish DANZABOSS as a provable, production-ready product: a model-neutral
"mission control" that connects the AI CLIs a user already has (claude, codex,
gemini, grok, opencode, …), relays them through turn-based boss shifts of 2–5
verified atomic build units, briefs every turn from CORTEX memory so models
stop re-reading the repo (the token saver), and presents the whole journey in
one simple linear UI. Proven by a live two-model build, not by claims.

## Scope

**IN:**
- Sequential relay execution model, polished to production quality
- Dead-code purge + fail-closed hook hardening
- CORTEX wired into the live loop: ignition turn briefs (boss + specialists),
  pull-on-demand mid-turn, calibrated token estimation, SessionStart dedup
- One-flow mission-control UI replacing the 4-tab SPA
- Stack/template recommender (curated catalog) in onboarding
- Token-savings meter on the build screen
- Weekly "frontier scout" (Tavily-backed, canonical repo only, approval-gated)
- Proof package: full suite + live 2-model E2E + Playwright walkthrough + docs
  rewritten to match reality

**OUT (explicitly not this version):**
- Parallel lanes / git-worktree fleet execution (v2 backlog)
- Wiring the `agents/runtime.py` authorization engine (deleted instead)
- Any second memory system or fixed token dial (CORTEX stays canonical)
- Frontier scout running in customer installs (canonical repo only)
- New visual identity / motion design beyond the one-flow simplification

## Decisions made during grilling

| # | Question | Decision | Why |
|---|---|---|---|
| 1 | Core execution model | Sequential relay: one boss at a time, 2–5 verified units/turn, handoff through lineup; parallel lanes deferred to v2 | Differentiated vs crowded parallel-fleet market; already 90% built and testable |
| 2 | Fate of dead code (~25% of package) | Delete all unwired modules; harden the 3 live hook guards to fail closed; make Stop hook enforce the `danza cortex observe` distillation gate | Codebase must be honest about what it enforces; kernel + unit gates already own turn safety |
| 3 | How memory reaches models | Push a compiled role-budgeted CORTEX brief at ignition + pull-on-demand (`danza cortex` / MCP) mid-turn | Deterministic for all six CLIs; research shows pull-only gets skipped |
| 3a | Specialists | Each spawned specialist gets its own role-budgeted brief; boss dispatches only the specialists a unit needs, not the full cast | User requirement — compounds the token savings |
| 4 | UI shape | One-flow mission control: single page, linear journey (Connect → Describe → Approve → Build), done stages collapse, advanced behind one menu; vanilla JS, no build step | "A lot more simple"; kills dead widgets, duplicate editors, jargon panels |
| 5 | Proof of done | Live 2-model build: install → onboard → relay with ≥2 real CLIs, ≥2 handoffs, all units verified, demo app tests pass, CORTEX savings evidence, Playwright walkthrough, full suite green | Only honest basis for a "production-ready" claim |
| 6 | Feature additions | Stack/template recommender + token-savings meter + weekly frontier scout | User-approved scope adds |
| 7 | Scout mechanics | Opportunistic trigger (≥7 days since last run, `TAVILY_API_KEY` present, canonical repo only); Tavily research pass + code-health pass; writes `.danza/frontier/proposals.md`; FRONTIER dashboard panel with per-item Approve/Dismiss; approved items → backlog, nothing auto-builds | No daemon/cron; human approval is the gate |

**Architect calls (flag if you disagree):**
- Token estimation: calibrated heuristic (per-content-type divisors) with an
  optional real tokenizer if one is importable; never a hard dependency.
- Stack recommender consults a curated built-in catalog (vetted stacks +
  build-order templates), refreshed over time by the frontier scout in the
  canonical repo — customer installs never need API keys for it.
- Live proof pair: claude + codex (both verified installed here, with tmux).

## Files to create

- `danzaboss/frontier/` — scout package: Tavily client, 7-day throttle,
  research pass, code-health pass, proposal store (`.danza/frontier/`),
  approval state. Reuses salvageable ideas from the old stub `research/`
  package, then that package is deleted.
- `danzaboss/product/stacks.py` (+ `stacks.json` catalog) — curated
  stack/template catalog + recommender consulted by onboarding.
- `docs/plans/01-danzaboss-final-production.md` — this plan.
- Proof artifacts under `docs/proof/` (E2E transcript, token comparison,
  Playwright results).

## Files to modify

- `danzaboss/cli.py` — hook guards fail closed; Stop hook enforces
  distillation gate; remove dead-module imports.
- `danzaboss/workstation/conductor.py` + `hosts.py` — ignition compiles and
  injects the CORTEX turn brief (tmux + headless paths); record brief
  telemetry.
- `danzaboss/cortex/driver_context.py` / `budgets.py` / `inject.py` —
  specialist briefs, calibrated token estimator, SessionStart diffing (inject
  only new/changed observations per session).
- `danzaboss/workstation/server.py` — one-flow API adjustments, FRONTIER +
  savings-meter endpoints, remove dead payload fields (`seats`, etc.).
- `danzaboss/workstation/static/` — rebuild as one-flow SPA (index.html,
  app.js, app.css); merge scope/additions editors into one component; single
  active/waiting source of truth.
- `danzaboss/workstation/routing.py` — strip dead seat-routing machinery to
  the sequential model actually used.
- `danzaboss/product/templates/scaffold/` prompts — boss/specialist prompts
  updated for brief-first workflow + selective specialist dispatch.
- `README.md`, `ARCHITECTURE.md`, `RUNBOOK.md`, `INSTALL.md` — rewritten to
  match code reality (no claims about deleted subsystems).

## Files to delete (with their tests)

- `danzaboss/agents/runtime.py` (+ `definitions.json` if unreferenced after)
- `danzaboss/orchestration/parallel.py`
- `danzaboss/research/` (entire stub package; superseded by `frontier/`)
- `danzaboss/memory/` + `danzaboss/context/` (gen-1 system)
- `danzaboss/runtime/runner.py`
- `danzaboss/planning/decompose.py` (keep `plan_schema.json` — it is live)
- Dead workstation code: seat-routing tables, unused `setup_summary` fields,
  duplicate `RUNNER_NAMES` map in app.js

## Data / schema changes

- `.danza/frontier/` — `proposals.md` + `state.json` (last-run timestamp,
  per-proposal status: proposed/approved/dismissed).
- `handoff.md` / ignition payload — gains the compiled CORTEX brief section
  (turn goal, assigned units, ranked observations, last-boss delta).
- CORTEX capture gains brief-injection telemetry rows (for the savings meter).
- `plan.json`, `team-state.json`, `routing.json`, `workspace.json` schemas
  unchanged (compatibility preserved).

## Failure modes covered

- Hook guards fail CLOSED; hook errors block instead of silently allowing.
- Brief compilation failure → ignition proceeds with a minimal deterministic
  brief (turn goal + units) and logs the degradation; never blocks a build on
  memory.
- Tavily unreachable / no key → scout silently skips, retries next
  opportunity; never breaks the dashboard.
- Scout in a customer install → hard-gated off (canonical-repo check).
- Approval gates keep revision fingerprints (existing pattern) for scope,
  additions, and frontier proposals.

## Done definition

1. Full unittest suite green (post-purge).
2. Deterministic mock-runner relay test walks ignite → 2–5 verified units →
   quota handoff → done, with briefs injected (CI-able, no AI spend).
3. Live E2E: temp repo → install.sh → onboard → approve demo-app scope →
   relay build with claude + codex, ≥2 handoffs, every unit verified by real
   test runs → demo app's own tests pass.
4. CORTEX evidence: brief-injection telemetry + before/after token comparison
   recorded in `docs/proof/`.
5. Playwright walkthrough of the one-flow UI (connect → describe → approve →
   build states render correctly).
6. Docs match the shipped code; no claims about deleted subsystems.

## Task list (execution order)

1. Baseline: run full test suite in the clone; record pass/fail baseline.
2. Purge dead code (deletions above) + fix imports; suite green again.
3. Harden hooks: fail-closed guards + Stop-hook distillation gate (TDD).
4. Wire CORTEX turn brief into conductor ignition (tmux + headless), with
   minimal-brief fallback and telemetry (TDD).
5. Add specialist briefs + selective-dispatch prompt updates in scaffold
   payload; budgets per role (TDD).
6. Calibrate token estimator + SessionStart diff-injection (TDD).
7. Add mock-runner relay integration test proving briefs + quota + handoff.
8. Rebuild UI as one-flow mission control; merge duplicate editors; single
   active/waiting truth; advanced menu; update server payloads.
9. Add token-savings meter (server endpoint + UI readout).
10. Build stack/template recommender: catalog, onboarding step, plan seeding.
11. Build frontier scout package + FRONTIER panel + approval flow.
12. Rewrite README / ARCHITECTURE / RUNBOOK / INSTALL to match reality.
13. Proof run: suite + live claude+codex E2E in temp repo + Playwright
    walkthrough; collect artifacts into `docs/proof/`.
14. Final review pass (code-review skill) + fix findings; tag mission report.

## Open items deferred (v2 backlog)

- Parallel lanes over git worktrees (plan schema already carries `writes[]`
  + `depends_on` for it)
- Frontier scout auto-refreshing the stack catalog
- Neon/global CORTEX store activation
- PR-per-turn / CI-gated merge mode
