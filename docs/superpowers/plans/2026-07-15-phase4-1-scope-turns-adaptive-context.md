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
7. **PROJECT UI.** Rename ONBOARD, present Create New/Continue Existing, audit progress/results/gaps, interview continuation, concise draft scope, expandable acceptance details, and exact-revision approval.
8. **BUILD backend.** Add live scope/unit payloads, transactional progress updates, feature status derivation, immutable completed work, draft additions, approval/replanning of pending work, and next-handoff queueing.
9. **BUILD UI.** Add compact live crossed-off features, expandable criteria and A/B/C units, quota progress, approval states, additions, blocks, and hard stops without adding a FEATURES tab.
10. **Adaptive CORTEX.** Implement base/ceiling policy, one-time qualified expansion, explicit-budget bypass, acceptance comparison, 6000 dispatch guard, and additive context-read telemetry migration.
11. **Compatibility and documentation.** Update active prompts/scaffolds/docs, generated artifact contracts, top-level status/test counts, and historical supersession banners. Remove active dial references; retain historical text only behind banners.
12. **Whole-product verification.** Run focused suites, full unit/integration suite, lint/static/package/install checks, and full Playwright. Diagnose and fix regressions test-first. Perform final active-reference and repository-status audits.

## Acceptance

All focused and full verification commands pass from clean invocations. No active runtime, UI, test, prompt, scaffold, or current documentation depends on the removed dial. New and takeover projects cannot build before exact-revision scope approval. Turns count verified atomic leaves and use the configured 2–5 quota. CORTEX telemetry proves when and why adaptive expansion occurred.
