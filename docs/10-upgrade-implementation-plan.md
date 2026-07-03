# DANZABOSS — 10-Upgrade Implementation Plan

Each upgrade is broken into small, ordered steps with an **acceptance criterion** per step and
a **findings / next-round** section documenting what was left open for the next iteration.

Status legend: ✅ built & tested this round · ◑ scaffolded (interface + tests, production wiring pending) · ⬜ next round.

Test evidence lives in `danzaboss/tests/`; run `./run_tests.sh` (56 tests) and
`python3 -m danzaboss_v2.selftest.harness` (8 checks). All green as of this round.

---

## Upgrade #2 — Machine-checkable team-state ✅ (foundation, built first)
**Why first:** every other upgrade needs a trustworthy turn/mode state.
Steps:
1. ✅ Define `team_state.schema.json` (mode, boss, turn, cap, status). *Accept: schema present, documented.*
2. ✅ `TeamState` dataclass + `validate()` fail-closed. *Accept: invalid docs raise `StateError`.*
3. ✅ Deterministic status state machine `_TRANSITIONS`. *Accept: illegal transition rejected (`test_illegal_status_transition_rejected`).*
4. ✅ Turn lock: only `current_boss` may mutate. *Accept: wrong actor raises (`test_turn_lock_blocks_wrong_actor`).*
5. ✅ Atomic write (tmp + `os.replace`). *Accept: no `.tmp` left (`test_atomic_write_leaves_no_tmp`).*
6. ✅ `handoff()` / `record_feature()` helpers. *Accept: cap flips handoff flag (`test_record_feature_flags_handoff_at_cap`).*
**Findings / next round:** file locking is process-atomic but not cross-host; if two environments
ever share a filesystem concurrently, add an OS-level advisory lock. Add a `history` array for full
turn provenance instead of only `previous_boss`.

## Upgrade #1 — Dual-mode execution kernel ✅
Steps:
1. ✅ `Decision` enum (build/verify/handoff/stop-done/stop-blocked). *Accept: enumerated.*
2. ✅ Pure `decide()` function. *Accept: deterministic (`test_decide_is_deterministic`).*
3. ✅ Continuous loop to completion. *Accept: builds N features then STOP_DONE (`test_continuous_builds_until_done`).*
4. ✅ Relay mode stops at cap → handoff. *Accept: `test_relay_hands_off_at_cap`.*
5. ✅ Blocker → escalate. *Accept: `test_blocker_stops_and_escalates`.*
6. ✅ `max_steps` loop safety valve (Rule 18). *Accept: `test_max_steps_safety_valve`.*
**Findings / next round:** the `executor` is a stub Protocol; production must wire it to actual
driver dispatch (Jonathan→Bonnie). Add adaptive control — escalate from single-agent to
multi-agent only when a task exceeds one context/role (research-backed "minimum control per failure mode").

## Upgrade #4 — Verifiable task decomposition ✅
Steps:
1. ✅ `VerificationKind` + `Verification.is_concrete()`. *Accept: empty detail is not concrete (`test_empty_verification_detail_rejected`).*
2. ✅ `Task` tree; `is_verifiable()` recursion. *Accept: parent verifiable iff all leaves are (`test_parent_verifiable_iff_all_children_verifiable`).*
3. ✅ `unverifiable_leaves()` diagnostic. *Accept: names the offending leaves.*
4. ✅ `assert_dispatchable()` fail-closed gate. *Accept: raises on vague task (`test_assert_dispatchable_raises_on_unverifiable`).*
**Findings / next round:** verification *kind* is declared but not executed here; wire each kind to
a runner (pytest, curl, schema-validate) so the gate can also *run* the check, not just require it.

## Upgrade #3 — Spec-driven planning ◑
Steps:
1. ✅ `spec_template.md` (intent, FRs w/ acceptance, NFRs, data, non-goals, verification strategy).
2. ✅ `plan_schema.json` (task tree, every leaf carries verification).
3. ⬜ Spec→plan generator that emits a `Task` tree consumable by #4. *Accept: generated plan passes `assert_dispatchable`.*
4. ⬜ Onboarding writes `spec.md` instead of `feature-list.md`. *Accept: feature-list deprecated.*
**Findings / next round:** steps 3–4 are the wiring into onboarding; kept as templates this round so
they can be reviewed before touching the live onboarding flow.

## Upgrade #7 — Layered memory subsystem ✅
Steps:
1. ✅ Three scopes (semantic/episodic/procedural), append-only JSONL. *Accept: `test_remember_and_stats`.*
2. ✅ Deterministic relevance scorer (overlap + tag + recency). *Accept: ranks bcrypt fact first (`test_retrieve_ranks_by_relevance`).*
3. ✅ Token budget + record cap on retrieval. *Accept: `test_token_budget_bounds_results`, `test_max_records_bounds_results`.*
4. ✅ Persist across instances. *Accept: `test_append_only_persists_across_instances`.*
**Findings / next round:** scorer is lexical; a vector/embedding backend behind the same
`retrieve()` interface would improve recall. Add contradiction resolution (bitemporal) so newer
facts supersede stale ones explicitly (addresses "hallucination amplification").

## Upgrade #8 — Context-engineering pipeline ✅
Steps:
1. ✅ `CompiledContext` + per-driver `DRIVER_PROFILES`. *Accept: compiles for a driver (`test_compile_targets_driver_profile`).*
2. ✅ select→compress→isolate processors. *Accept: dedupe (`test_compress_dedupes`), trim (`test_isolate_trims_to_budget`).*
3. ✅ Hard budget enforcement. *Accept: `test_budget_is_enforced`.*
4. ✅ Unknown driver still compiles. *Accept: `test_unknown_driver_still_compiles`.*
**Findings / next round:** compression is dedupe-only; add extractive summarization for long
records. Wire `compile()` output into the actual sub-agent prompt so drivers stop receiving
hand-pasted context (closes the Phase-1 prompt-boundary risk end-to-end).

## Upgrade #10 — Capability-based security ✅
Steps:
1. ✅ `Capability` enum incl. elevated set (auth/payment/schema/delete). *Accept: enumerated per Rules 13–16.*
2. ✅ `DEFAULT_GRANTS` least-privilege per driver. *Accept: builder can `write_code`, mapper cannot (`test_missing_grant_denied`).*
3. ✅ Elevated actions require a minted token. *Accept: denied without token (`test_elevated_denied_without_token`).*
4. ✅ Single-use, agent-bound tokens. *Accept: `test_elevation_allows_once`, `test_elevation_bound_to_agent`.*
5. ✅ Append-only audit trail. *Accept: `test_audit_trail_written`.*
**Findings / next round:** tokens are in-memory; persist minted/spent tokens so enforcement
survives a crash. Add capability *attenuation* (a driver can pass a narrower subset to a helper).

## Upgrade #5 — Structured observability ✅
Steps:
1. ✅ `Span` dataclass (trace/parent ids, timing, status). *Accept: emitted with timing (`test_span_emitted_with_timing`).*
2. ✅ Context-manager span; error capture + re-raise. *Accept: `test_error_captured_and_reraised`.*
3. ✅ Nesting sets parent id. *Accept: `test_nesting_sets_parent`.*
4. ✅ `summary()` + `evidence_for()` (anti-theatre). *Accept: `test_summary_counts`, `test_evidence_for_actor`.*
**Findings / next round:** JSONL is local; add an exporter to an OTel-compatible sink for real
dashboards. Add in-loop evals (assert quality thresholds) that can fail a turn, not just record it.

## Upgrade #9 — Parallel dispatch planner ✅
Steps:
1. ✅ `PTask` (deps, writes, verifiable). *Accept: modeled.*
2. ✅ `plan_waves()` respects deps. *Accept: `test_dependencies_serialize`.*
3. ✅ Write-conflict isolation. *Accept: `test_write_conflict_splits_waves`.*
4. ✅ Fan-out cap + cycle/unknown-dep/unverifiable guards. *Accept: `test_max_parallel_cap`, `test_cycle_detected`, `test_unknown_dependency_raises`, `test_unverifiable_task_rejected`.*
5. ✅ `token_multiplier()` cost signal. *Accept: `test_token_multiplier`.*
**Findings / next round:** waves are planned but execution is still serial-per-wave in the
scheduler; wire real concurrent dispatch (parallel = more tokens — measure with the multiplier
before enabling by default, per the Anthropic caveat).

## Upgrade #6 — Cold-start self-test harness ✅
Steps:
1. ✅ State init + schema integrity check. *Accept: `state_init_and_schema` passes.*
2. ✅ Turn-lock, decomposition-gate, hard-stop, elevation-single-use checks. *Accept: all pass.*
3. ✅ Simulated relay build cycle → handoff. *Accept: `relay_cycle_hands_off`.*
4. ✅ Continue-mode ownership after handoff. *Accept: `continue_mode_ownership`.*
5. ✅ Returns a structured report; never raises (CI-safe). *Accept: `test_cold_start_all_pass`.*
**Findings / next round:** harness covers the kernel + security + planning; extend it to exercise
the memory/context pipeline and a *continuous*-mode full run. Make it read the responsibility
matrix (Overlap F3) so an out-of-lane agent fails cold-start.

---

## Cross-cutting next-round backlog
1. Promote doc-level overlap remedies (O2–O5) to capability-enforced.
2. Render the legacy `.danza/*.md` logs as views over the episodic stream (single source).
3. Wire `executor`, `compile()`, and verification runners into live driver dispatch.
4. Persist capability tokens + add OTel export.
5. Add a *continuous-mode* end-to-end harness scenario and a token-budget regression test.
