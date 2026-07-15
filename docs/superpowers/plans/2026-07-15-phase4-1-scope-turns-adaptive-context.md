# Phase 4.1 — Scope, Turn Size, and Adaptive Context

## Binding decisions

- Remove every active Normal/Full Power dial and `budgets.json` dependency. Ignore stale files without deleting them; preserve historical plans with supersession banners.
- Setup persists `features_per_turn` in routing configuration: integer 2–5, default 2. A change applies at the next handoff.
- One counted feature is one verified atomic plan leaf such as `71-A`. Product feature `71` may have A/B/C units. Count leaves directly; never group dotted ID prefixes or advance by `turn_number * quota`.
- Atomic units estimate 1–20 minutes, target 10–15; estimates below 3 warn but remain valid. Require one concern, 1–3 write areas, one verification, valid acyclic dependencies, and existing hard-stop flags. Never kill an overrunning unit; record actual time and a calibration observation.
- `.danza/features.json` is authoritative approved product scope. `.danza/plan.json` is authoritative internal execution work. `.danza/feature-list.md` and `plan.md` are generated views. Completed scope and units are immutable.
- Users approve concise product features, never A/B/C decomposition. Approved additions are planned for the next handoff without interrupting the active turn.
- Keep dashboard tabs. Rename ONBOARD to PROJECT. PROJECT offers Create New and Continue Existing. BUILD owns feature approval, live progress, expandable units, and additions.
- Continue Existing audits repository/Git state, manifests, source graph, tests/config/docs, Git history, existing DANZA artifacts, and analyzer coverage before asking for desired work. Material coverage gaps require explicit acknowledgement. Cache by HEAD plus tracked-worktree fingerprint.
- The conductor only reacts after the kernel concludes a turn and ignites the next connected runner as Tony D. Scheduling, verification, counting, and stopping decisions remain outside the conductor.
- Adaptive CORTEX budgets: Tony/Jonathan/Samantha/Angela 2400→4000; Bonnie/Billy/Hank/Carmella 2000→3500; unknown 2400→4000. Expand once only at >=85% base consumption plus dropped relevant observations or missing required category despite candidates. Accept expansion only without relevance loss and with improved coverage/high-ranked context. Explicit `--budget N` is exact and disables expansion. Dispatch guard becomes 6000.

## Tasks

1. **Complete dial removal.** Repair dashboard/server/tests around the existing two-file handoff. Setup writes runners and routing only; stale budgets files are ignored. Test first, then verify budget and dashboard focused suites.
2. **Features-per-turn configuration.** Upgrade routing schema/load/save compatibility, Setup UI, summaries, server validation, and team-state handoff snapshot. Test 2–5, default/migration, invalid values, and mid-turn behavior.
3. **Product-scope artifacts.** Add validated revisioned `features.json`, stable product IDs, approval state, immutable completions, concise summaries, acceptance criteria, and generated `feature-list.md`. Test round trips, stale approvals, status derivation, and corruption.
4. **Atomic plan units.** Add product references and new `71-A` leaf IDs while retaining legacy dotted IDs. Enforce 1–20 sizing, sub-3 warnings, 1–3 write areas, one concern, verification, dependencies, and flags. Replace feature-prefix rendering/counting with ordered leaves.
5. **Verified completion and routing.** Persist unit status/timing, route the first dependency-ready incomplete leaf, count successful verification once, conclude at quota/no work/block/hard stop, and record overruns. Remove arithmetic cursors. Keep conductor postman-only.

   **Completion evidence — corrected 2026-07-15:** The installed `danza unit
   start|verify|block|conclude` boundary now drives the execution ledger;
   verification runs the concrete atomic-unit command and persists its result,
   timing, calibration, and idempotent unit count. BUILD start initializes and
   concludes kernel state before spawning the conductor. The conductor no
   longer selects a fallback boss when routing has no ready work. Verification:
   8 Task 5 lifecycle tests, 123 execution/routing/conductor tests, 8 BUILD
   integration tests, 279 bounded call-graph regressions, 84 dashboard/onboarding
   HTTP regressions, and the 8/8 cold-start self-test all passed.
6. **PROJECT backend.** Split finish flow into discovery → draft scope → approval → decomposition. Add new/existing modes, deterministic takeover audit, coverage/gap acknowledgement, fingerprint caching, and server endpoints with revision conflicts.

   **Completion evidence — 2026-07-15:** PROJECT now persists explicit new or
   existing discovery state. Existing-project discovery deterministically audits
   repository/Git state, manifests, source dependencies, tests, config, docs,
   Git history, DANZA artifacts, and analyzer coverage; material analyzer gaps
   require exact acknowledgement, and audit results cache by HEAD plus tracked
   worktree content. Separate discover, scope-draft, exact-revision approval,
   and decomposition endpoints return revision conflicts as HTTP 409. Planning
   consumes and covers only the exact approved `features.json` revision, while
   BUILD rejects missing, draft, stale, or mismatched scope/plan revisions.
   Verification: 23 focused PROJECT/planning tests and 268 cumulative Task 3–6
   backend/regression tests passed; changed production Python files compiled.
7. **PROJECT UI.** Rename ONBOARD, present Create New/Continue Existing, audit progress/results/gaps, interview continuation, concise draft scope, expandable acceptance details, and exact-revision approval.

   **Completion evidence — 2026-07-15:** The dashboard tab and active UI copy
   now use PROJECT. Create New continues the gated interview through brief
   creation; Continue Existing displays audit progress, evidence categories,
   and exact material-gap acknowledgement before scope drafting. Product
   features remain concise, acceptance criteria expand in place, unsaved edits
   disable approval, and approval posts the exact displayed saved revision
   before decomposition becomes available. Verification: 4 focused Task 7 UI
   tests, 73 dashboard integration tests, 64 PROJECT/onboarding/product-scope/
   planning tests, 104 Task 5 lifecycle regressions, and 407 cumulative
   workstation tests passed with 1 optional skip; JavaScript syntax and diff
   checks passed.
8. **BUILD backend.** Add live scope/unit payloads, transactional progress updates, feature status derivation, immutable completed work, draft additions, approval/replanning of pending work, and next-handoff queueing.

   **Completion evidence — 2026-07-15:** BUILD now returns the exact approved
   scope with derived product progress, linked atomic-unit execution evidence,
   turn quota, additions approval, and next-handoff state. Execution mutations
   journal `plan.json`, `plan.md`, `features.json`, and `feature-list.md` as one
   recoverable progress update; completed feature definitions and carried unit
   identity/evidence cannot regress. Additions use independent exact-revision
   drafts. Approval replans only pending units, preserves completed/active work,
   and leaves active artifacts untouched until the next safe handoff. Queue
   activation occurs before routing, fails closed on corruption, and preserves
   blocked and hard-stop conclusions without conductor scheduling. Verification:
   33 focused BUILD/replanning tests, 29 directly affected BUILD/API tests,
   64 PROJECT-to-BUILD tests, 104 Task 5 lifecycle regressions, 426 cumulative
   workstation tests with 1 optional skip, and 86 dashboard/onboarding HTTP
   tests passed; changed Python files compiled and diff checks passed.
9. **BUILD UI.** Add compact live crossed-off features, expandable criteria and A/B/C units, quota progress, approval states, additions, blocks, and hard stops without adding a FEATURES tab.

   **Completion evidence — 2026-07-15:** BUILD now presents the Task 8 product
   payload as compact live feature cards, crosses off completed outcomes, and
   expands acceptance criteria with linked atomic units. The same tab shows
   turn quota, exact active-scope approval, blocked reasons, hard-stop flags,
   isolated additions drafting and exact-revision approval, and queued
   next-handoff activation while preserving internal plan artifacts under an
   Advanced disclosure. Focused Task 9 tests failed first and then passed (2);
   18 BUILD backend/API tests, 52 PROJECT-to-BUILD tests, 116 Task 5 lifecycle
   regressions, 426 cumulative workstation tests with 1 optional skip, and 87
   dashboard/onboarding HTTP tests passed. JavaScript syntax and diff checks
   passed. No FEATURES tab or browser-level Playwright run was added.
10. **Adaptive CORTEX.** Implement base/ceiling policy, one-time qualified expansion, explicit-budget bypass, acceptance comparison, 6000 dispatch guard, and additive context-read telemetry migration.

   **Completion evidence — 2026-07-15:** Driver-default CORTEX context now
   resolves the binding `2400→4000` or `2000→3500` role policy, including
   Tony and the unknown-role fallback. A base package qualifies only at 85%
   consumption plus dropped relevant context or a missing top-three intent
   category with candidates; the selected retrieval ranking is reassembled at
   most once at the ceiling and accepted only without relevance loss plus
   improved coverage or a newly admitted fused top-five item. Explicit budgets
   remain exact and bypass adaptation. CLI JSON and the additive, idempotently
   migrated `context_reads.adaptation` JSON column record the requested,
   initial, candidate, acceptance, and final selection evidence while old rows
   and four-argument writers remain compatible. The live estimated Task/Agent
   dispatch boundary now allows 6000 and denies 6001 in runtime profiles.
   Verification: 59 focused policy/selection/driver tests, 29 telemetry/CLI
   tests, 34 guard/live-hook tests, 323 all-CORTEX tests with 13 optional skips,
   136 cumulative Tasks 3–8 backend/lifecycle regressions, and 74 dashboard/
   Task 9 regressions passed; changed production Python files compiled and diff
   checks passed. Existing dashboard socket warnings remained non-failing.
11. **Compatibility and documentation.** Update active prompts/scaffolds/docs, generated artifact contracts, top-level status/test counts, and historical supersession banners. Remove active dial references; retain historical text only behind banners.
12. **Whole-product verification.** Run focused suites, full unit/integration suite, lint/static/package/install checks, and full Playwright. Diagnose and fix regressions test-first. Perform final active-reference and repository-status audits.

## Acceptance

All focused and full verification commands pass from clean invocations. No active runtime, UI, test, prompt, scaffold, or current documentation depends on the removed dial. New and takeover projects cannot build before exact-revision scope approval. Turns count verified atomic leaves and use the configured 2–5 quota. CORTEX telemetry proves when and why adaptive expansion occurred.
