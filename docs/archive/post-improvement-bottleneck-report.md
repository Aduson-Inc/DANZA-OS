# Post-Improvement Bottleneck Report — DANZABOSS

Three sub-agents independently analyzed the upgraded DANZABOSS OS, each with a different lens
(execution kernel · token/context · reliability/security). This aggregates their findings,
de-duplicates convergent points, and ranks them. One finding (W1) was a real defect in the new
code and has already been **fixed and regression-tested** this round.

**Verification baseline at time of review:** 56 tests green → after W1 fix, **62 tests green**;
cold-start harness 8/8.

---

## The one theme all three agents converged on
> **The upgrades built correct *mechanisms* but left them *enforcement-optional* — guards that
> must be voluntarily invoked rather than being unavoidable at the action boundary, and modules
> that are not yet wired into the live dispatch path.**

This is expected for this round (the plan explicitly scoped production wiring as "next round"),
but all three reviewers independently ranked it the dominant limiter. It is the headline for
round 2.

---

## Ranked aggregate bottlenecks

### P0 — Turn lock was fail-OPEN (RELIABILITY) — ✅ FIXED THIS ROUND
`kernel/state.py`. `transition()` skipped the ownership check when `actor` was omitted, and
`handoff()` never passed one, so `current_boss` could be reassigned to an arbitrary value.
**Fix applied:** ownership fields are now protected — mutating them requires an explicit
`actor` equal to `current_boss` (fail-closed); `handoff()` passes the caller identity through.
**Evidence:** direct repro now raises; 6 new regression tests in `test_state.py::TestTurnLockFailClosed`.

### P1 — New modules are not wired into live dispatch (all three agents)
The scheduler never calls the parallel planner; the orchestrator prompt still hand-pastes
`prompt="[task + context]"` instead of using `ContextPipeline.compile()`; `CapabilityRegistry.check()`
and `Tracer.span()` are invoked only by the harness/tests. **Impact:** throughput stays serial,
token savings stay theoretical, hard stops and anti-theatre evidence stay honor-system.
**Where:** `kernel/scheduler.py`, `context/pipeline.py`, `security/capabilities.py`,
`observability/trace.py`, `tony-d-orchestrator.md` (~lines 134, 174–175). **Severity: High.**
*This is the round-2 headline.*

### P2 — Serial execution / single-orchestrator star (kernel + reliability agents)
`plan_waves()` is computed then discarded; the loop runs one `executor` call per iteration and
every driver result funnels back through Tony D, whose own context window becomes the ceiling.
**Severity: High.** *Fix path: wire waves into `Scheduler.run`; measure with `token_multiplier`
before enabling by default (Anthropic caveat).* 

### P3 — Enforcement guards are opt-in, not structural (reliability agent)
Capabilities (W2), tracer evidence (W4), and the doc-level overlap remedies O2–O5/W7 all depend
on voluntary invocation. Even Bonnie-as-sole-gate (Rule 5) has no code teeth yet. **Severity: High.**
*Fix path: call `reg.check()` at every action boundary; make the self-audit fail when
`evidence_for(actor)` is empty.*

### P4 — Retrieval quality & token flow (token agent)
Lexical set-overlap scorer misses synonyms/stemming (`store.py::_score`); recency term is
mis-normalized and summed raw against unbounded overlap; full-scan `_load` reads every record per
query; `compress()` is exact-prefix only; dropped records are silent (no "N elided" marker).
**Severity: High→Med.** *Fix path: pluggable vector backend behind `retrieve()`, weighted scoring,
an index, and drop-annotations in `CompiledContext`.*

### P5 — Duplicated memory surfaces persist (token + reliability agents, overlap F2)
The legacy `.danza/*.md` logs still coexist with the unified episodic stream, and `.danza/memory/*.md`
is a third surface. Triple-counting is only half-remedied. **Severity: Med.** *Fix path: render the
`.md` logs as views over the stream so there is one source (overlap F2).*

### P6 — State I/O amplification + no cross-process lock (kernel + reliability agents)
Each step does multiple full load→validate→write cycles of the whole JSON; `record_feature`
double-loads; there is no `flock`/`fsync`, so concurrent writers on a shared FS can clobber
counters (W5). **Severity: Med.** *Fix path: single load per step, OS advisory lock, `fsync`.*

### P7 — VERIFY re-dispatch has no per-task attempt cap (kernel + reliability agents)
A build-but-never-verify task oscillates until the global `max_steps` valve trips, masking stuck-QA
as a loop and burning the whole budget on one feature (W8/B5). **Severity: Med.** *Fix path:
per-task attempt counter + distinct verify signal; state-repetition loop detection (true Rule 18).*

### P8 — Crash-durability of elevation tokens & continuous-mode progress (reliability + kernel)
Elevation single-use state is in-memory only (not rebuilt from `audit.jsonl`); continuous mode has
no mid-run checkpoint/resume cursor. **Severity: Med.** *Fix path: replay audit to reconstruct spent
tokens; periodic checkpoint emit in the loop.*

### P9 — Self-test coverage gaps (reliability agent)
Harness tested happy paths and (before this round) missed the `actor=None` bypass; it early-returns
after the first failure and doesn't exercise continuous-mode termination, concurrency, or token
durability. **Severity: Med.** *Partly addressed:* W1 now has regression tests; extend the harness
next round (and have it read the responsibility matrix — overlap F3).

---

## Single worst bottleneck (consensus)
**P1 — the upgrade mechanisms are not yet wired into the live path.** Two agents named it
outright as their #1; the third's worst finding (W1) was a defect *within* that unwired machinery
and is now fixed. Until `Scheduler.run` consumes `plan_waves`, the orchestrator pastes
`ContextPipeline.compile()` output, and `reg.check()`/`tracer.span()` gate real actions, the
system's measured throughput, token, and safety behavior is close to its pre-upgrade self plus
tested-but-dormant modules. **Round 2 = wiring, not new features.**

## Round-2 backlog (prioritized)
1. Wire waves → scheduler; context pipeline → orchestrator prompts; capabilities + tracer → action boundaries. (P1/P2/P3)
2. Pluggable vector retrieval + weighted scoring + drop-annotations. (P4)
3. Render `.danza/*.md` logs as views over the episodic stream. (P5)
4. Single load/step + advisory lock + fsync. (P6)
5. Per-task attempt cap + true state-repetition loop detection. (P7)
6. Audit-replay token durability + continuous-mode checkpoints. (P8)
7. Extend cold-start harness (continuity, concurrency, matrix check). (P9)

## Method note
Each reviewer ran read-only against the same tree, cited file/line evidence, and named its single
worst bottleneck. Convergence across three independent lenses on P1 raises confidence it is the
correct next priority. All findings are ✅ evidence-backed; none are speculative.
