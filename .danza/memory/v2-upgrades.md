# DANZABOSS v2 — 10 Approved Upgrades

Approved by Tre 2026-07-01. Direction: configurable dual-mode; grounded in OS design + 2026
agentic systems. Implemented as tested Python in danzaboss (stdlib only).

1. Dual-mode execution kernel (kernel/scheduler.py) — BUILT+TESTED
2. Machine-checkable team-state (kernel/state.py) — BUILT+TESTED  [fixes missing Rule 45 file]
3. Spec-driven planning (planning/spec_template.md, plan_schema.json) — SCAFFOLDED
4. Verifiable task decomposition (planning/decompose.py) — BUILT+TESTED
5. Structured observability (observability/trace.py) — BUILT+TESTED
6. Cold-start self-test harness (selftest/harness.py) — BUILT+TESTED (8/8 checks)
7. Layered memory subsystem (memory/store.py) — BUILT+TESTED
8. Context-engineering pipeline (context/pipeline.py) — BUILT+TESTED
9. Parallel dispatch planner (orchestration/parallel.py) — BUILT+TESTED
10. Capability-based security (security/capabilities.py) — BUILT+TESTED

## Learnings
- 2026-07-01: 56 unit tests + harness all green. Modules are interfaces + logic; production
  wiring into live driver dispatch is the next round. See docs/10-upgrade-implementation-plan.md.
- 2026-07-01: Post-improvement review by 3 independent sub-agents found W1 — a fail-OPEN
  turn lock in kernel/state.py (actor omitted bypassed ownership; handoff never passed actor).
  FIXED same round: ownership fields now fail-closed; +6 regression tests. Suite now 62 tests
  green + harness 8/8. Consensus round-2 priority: WIRE modules into live dispatch (they are
  built+tested but not yet called by the orchestrator). See docs/post-improvement-bottleneck-report.md.
