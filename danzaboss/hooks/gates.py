"""End-of-turn gates — DANZA governance (fire on Stop/SubagentStop).

These are the anti-regression / anti-theatre spine. They run once at turn end and
block the handoff if the turn's claims aren't backed by evidence. They are the
hooks that make it safe to let DANZA run unattended.
"""
from __future__ import annotations

from .events import TurnRecord, Decision


# -- anti-theatre gate (Rules 42-43) -----------------------------------------
def anti_theatre_gate(rec: TurnRecord) -> Decision:
    """Every claimed sub-agent must have real evidence it ran (trace/SubagentStop).
    Blocks Tony D from narrating work that was never dispatched."""
    hook = "anti_theatre_gate"
    evidence = set(rec.evidence_actors)
    missing = [a for a in rec.claimed_subagents if a not in evidence]
    if missing:
        return Decision.deny(hook, f"claimed sub-agent work with NO evidence: {missing}. "
                                   "Each claim needs a trace span / SubagentStop record "
                                   "(Rules 42-43). Handoff blocked.")
    return Decision.ok(hook)


# -- verify-before-done gate (Rule 5) ----------------------------------------
def verify_before_done_gate(rec: TurnRecord) -> Decision:
    """A feature counts as done only if it has a passing verification on record."""
    hook = "verify_before_done_gate"
    unverified = [f for f in rec.completed_features
                  if rec.verifications.get(f) is not True]
    if unverified:
        return Decision.deny(hook, f"features marked done without a PASS: {unverified}. "
                                   "Bonnie must verify (Rule 5). Handoff blocked.")
    return Decision.ok(hook)


# -- regression gate ("never regress") ---------------------------------------
def regression_gate(rec: TurnRecord) -> Decision:
    """The test suite / cold-start harness must be green before promotion."""
    hook = "regression_gate"
    if rec.tests_green is None:
        return Decision.deny(hook, "regression suite was not run; run tests before handoff")
    if not rec.tests_green:
        return Decision.deny(hook, "regression suite is RED; fix before handoff (never regress)")
    return Decision.ok(hook)


def run_all_gates(rec: TurnRecord) -> list[Decision]:
    """Run every end-of-turn gate; caller blocks handoff if any denied."""
    return [anti_theatre_gate(rec), verify_before_done_gate(rec), regression_gate(rec)]


# -- CORTEX distillation gate (spec 2026-07-03, section 4.2) ------------------
def distillation_gate(pending_events: int, observations_written: int,
                      already_blocked: bool) -> Decision:
    """Turn knowledge must be distilled before the session may stop. Blocks at
    most once per session: after one block (or any distillation) it passes, and
    the caller runs the deterministic floor extractor instead (Tier 2). Fed
    from CaptureLog counts by the cortex CLI, not from TurnRecord."""
    hook = "distillation_gate"
    if pending_events == 0 or observations_written > 0 or already_blocked:
        return Decision.ok(hook)
    return Decision.deny(
        hook,
        f"{pending_events} captured events not distilled. Write what this session "
        "learned via `danza cortex observe` (JSON on stdin: title, summary, type, "
        "reasoning, when_relevant/when_not_relevant), or run "
        "`danza cortex observe --nothing-meaningful` if nothing durable happened. "
        "Then stop again.")
