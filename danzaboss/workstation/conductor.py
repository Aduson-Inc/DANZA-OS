"""W1 conductor — the deterministic relay postman (design spec section 7).

Watches team-state.json, ignites fresh boss sessions, and stops on the
states that need a human. It is a POSTMAN, not a boss: it reads turn
state through the kernel's StateManager and writes only its own JSONL
log and pidfile — it never holds a turn, so Rule 38 cannot be violated
from this seat. The decision core below is pure so every rail (valve,
stall, halt) is unit-testable without processes; the seat stays
swappable for an intelligent conductor (Hermes) later.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from danzaboss.kernel.state import TeamState


class ConductorError(RuntimeError):
    """Conductor cannot run safely (pidfile conflict, no registry)."""


class Action(str, Enum):
    IGNITE = "ignite"          # spawn a fresh boss session this tick
    WAIT = "wait"              # someone is (or should be) working
    HALT_BLOCKED = "halt_blocked"   # hard stop / Rule 18 loop — human needed
    STOP_DONE = "stop_done"    # goal met; relay over
    STOP_VALVE = "stop_valve"  # sessions dying without progress — stop relay


STALL_MINUTES = 10       # spec section 7 default T
DEAD_SESSION_VALVE = 2   # spec section 7 default K


@dataclass(frozen=True)
class Watch:
    """The conductor's between-tick bookkeeping. Deliberately the ONLY
    state it owns (beyond the log): a crashed conductor restarts with a
    fresh Watch, re-reads team-state, and resumes — statelessness IS the
    crash-recovery story (and what makes the seat swappable)."""
    session_alive: bool
    turn_at_ignite: int | None
    dead_sessions: int
    last_change_monotonic: float
    last_tail: str


def decide(state: TeamState, watch: Watch) -> Action:
    """Pure decision table — same discipline as kernel.scheduler.decide.

    Order matters: human-needed states outrank the valve, and the valve
    outranks ignition (a relay burning sessions must not get one more)."""
    if state.status == "blocked":
        return Action.HALT_BLOCKED
    if state.status == "done":
        return Action.STOP_DONE
    if watch.dead_sessions >= DEAD_SESSION_VALVE:
        return Action.STOP_VALVE
    if state.status == "ready" and not watch.session_alive:
        return Action.IGNITE
    return Action.WAIT


def observe_session_end(state: TeamState, watch: Watch) -> Watch:
    """Account for a session found dead. A death WITHOUT a turn_number
    advance counts toward the valve (the session did no relay work); an
    advancing death is normal relay churn and resets the count."""
    advanced = (watch.turn_at_ignite is None
                or state.turn_number != watch.turn_at_ignite)
    return replace(watch, session_alive=False,
                   dead_sessions=0 if advanced else watch.dead_sessions + 1)


def is_stalled(watch: Watch, now_monotonic: float, *,
               stall_minutes: int = STALL_MINUTES) -> bool:
    """Rule 33, machine side: a LIVE session with no observed change for
    the threshold. Stalls are surfaced, never auto-killed — the human
    decides whether it is thinking or wedged (spec section 7)."""
    if not watch.session_alive:
        return False
    return now_monotonic - watch.last_change_monotonic >= stall_minutes * 60
