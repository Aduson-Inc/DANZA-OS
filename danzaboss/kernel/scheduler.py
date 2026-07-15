"""Dual-mode execution kernel — DANZABOSS Upgrade #1.

Replaces the hard-coded "2 features per turn, then hand off" loop with a
configurable scheduler that supports two modes:

  * ``continuous`` : run state -> decide -> build -> verify -> repeat until the
    goal is met or a real blocker is hit (loop engineering).
  * ``relay``      : preserve the multi-AI handoff; stop and hand off after
    ``max_features_per_turn`` verified features.

The scheduler is pure control logic. It does not itself call an LLM or write
code — it decides *what should happen next* given the current state and the
outcome of the last step. That keeps it deterministic and unit-testable, and
lets any AI environment drive it. Actual building is delegated to a callable
``executor`` the caller supplies (in production, that dispatches Jonathan etc.).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Protocol

from .state import StateManager, TeamState, StateError


class Decision(str, Enum):
    BUILD_NEXT = "build_next"      # dispatch the next task
    VERIFY = "verify"             # send last build to QA
    HANDOFF = "handoff"           # relay: cap reached, pass the baton
    STOP_DONE = "stop_done"       # goal met, nothing left
    STOP_BLOCKED = "stop_blocked"  # real blocker -> escalate to user


@dataclass
class StepOutcome:
    """What the executor reports back after doing one unit of work."""
    built: bool = False        # a feature was produced this step
    verified: bool = False     # QA (Bonnie) passed it
    blocked: bool = False      # a genuine blocker (hard stop / missing dep)
    blocker_reason: str = ""
    unit_id: str = ""            # concrete atomic identity when verified


class Executor(Protocol):
    """Anything that can perform one unit of work and report an outcome.
    In production this dispatches the driver agents; in tests it is a stub."""
    def __call__(self, state: TeamState, tasks_remaining: int) -> StepOutcome: ...


class Scheduler:
    """Drives the build loop for either mode."""

    def __init__(self, manager: StateManager, *, max_steps: int = 10_000):
        self.manager = manager
        self.max_steps = max_steps  # safety valve against runaway loops (Rule 18)

    def decide(self, state: TeamState, tasks_remaining: int,
               last: Optional[StepOutcome]) -> Decision:
        """Pure decision function — the heart of the kernel.

        Deterministic: same (state, tasks_remaining, last) always yields the
        same decision. This is what makes the loop auditable.
        """
        if last is not None and last.blocked:
            return Decision.STOP_BLOCKED
        if last is not None and last.built and not last.verified:
            return Decision.VERIFY
        if tasks_remaining <= 0:
            return Decision.STOP_DONE
        if state.mode == "relay":
            cap = state.max_features_per_turn or 0
            if state.features_completed_this_turn >= cap:
                return Decision.HANDOFF
        return Decision.BUILD_NEXT

    def run(self, *, tasks_remaining: int, executor: Executor,
            actor: str, next_boss: Optional[str] = None) -> dict:
        """Run the loop until a terminal decision.

        Returns a summary dict with the terminal decision, steps taken, and
        features completed. Enforces ``max_steps`` as a loop-detector safety
        valve (Constitution Rule 18).
        """
        state = self.manager.load()
        if state.status == "ready":
            state = self.manager.transition(actor=actor, to_status="in_progress")

        steps = 0
        last: Optional[StepOutcome] = None
        features = 0

        while True:
            if steps >= self.max_steps:
                self.manager.transition(actor=actor, to_status="blocked")
                return {"decision": Decision.STOP_BLOCKED.value,
                        "reason": "max_steps exceeded (loop safety valve)",
                        "steps": steps, "features_completed": features}

            decision = self.decide(state, tasks_remaining, last)

            if decision == Decision.STOP_DONE:
                self.manager.transition(actor=actor, to_status="done")
                return {"decision": decision.value, "steps": steps,
                        "features_completed": features}

            if decision == Decision.STOP_BLOCKED:
                self.manager.transition(actor=actor, to_status="blocked")
                return {"decision": decision.value,
                        "reason": last.blocker_reason if last else "",
                        "steps": steps, "features_completed": features}

            if decision == Decision.HANDOFF:
                if not next_boss:
                    raise StateError("relay handoff requires next_boss")
                self.manager.handoff(next_boss)
                return {"decision": decision.value, "steps": steps,
                        "features_completed": features, "next_boss": next_boss}

            if decision == Decision.VERIFY:
                # re-dispatch the same unit for verification
                outcome = executor(state, tasks_remaining)
                if outcome.verified:
                    if not outcome.unit_id:
                        raise StateError(
                            "verified scheduler outcome requires unit_id")
                    state = self.manager.record_unit(actor, outcome.unit_id)
                    features += 1
                    tasks_remaining -= 1
                    last = None  # unit fully done
                else:
                    last = outcome  # still needs work / may block
                steps += 1
                state = self.manager.load()
                continue

            # BUILD_NEXT
            outcome = executor(state, tasks_remaining)
            last = outcome
            steps += 1
            state = self.manager.load()
