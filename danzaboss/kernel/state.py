"""Team-state manager — DANZABOSS Upgrade #2.

Implements the machine-checkable source of truth for turn ownership and
execution mode that Constitution Rule 45 references but which never existed.

Design goals (per project mandate):
  * Deterministic, validated state transitions (no prose-only turn lock).
  * Zero external dependencies (stdlib json only) so it runs in any environment.
  * Fail-closed: an invalid transition raises rather than silently corrupting state.

The manager owns exactly one file (``team-state.json``). All mutation goes through
``transition`` so every change is validated against the schema and the transition
rules before it is persisted.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass, asdict, field
from typing import Any, Optional

_ALLOWED_MODES = {"continuous", "relay"}
_ALLOWED_STATUS = {"ready", "in_progress", "blocked", "awaiting_handoff", "done"}
SCHEMA_VERSION = 1
_MIN_FEATURES_PER_TURN = 2
_MAX_FEATURES_PER_TURN = 5
_UNSET = object()


class StateError(Exception):
    """Raised when a state document or transition is invalid. Fail closed."""


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


@dataclass
class TeamState:
    """Typed view of ``team-state.json``.

    ``max_features_per_turn`` is ``None`` in continuous mode (no cap) and an
    integer (default 2) in relay mode — the concrete knob that replaces the
    hard-coded "2 features per turn" rule.
    """
    mode: str = "relay"
    current_boss: str = "claude"
    previous_boss: Optional[str] = None
    turn_number: int = 0
    features_completed_this_turn: int = 0
    verified_unit_ids_this_turn: list[str] = field(default_factory=list)
    max_features_per_turn: Optional[int] = 2
    handoff_required: bool = False
    status: str = "ready"
    goal: Optional[str] = None
    updated_at: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        """Structural validation. Raises StateError on any violation."""
        if self.schema_version != SCHEMA_VERSION:
            raise StateError(f"unsupported schema_version {self.schema_version}")
        if self.mode not in _ALLOWED_MODES:
            raise StateError(f"invalid mode {self.mode!r}")
        if self.status not in _ALLOWED_STATUS:
            raise StateError(f"invalid status {self.status!r}")
        if not isinstance(self.current_boss, str) or not self.current_boss:
            raise StateError("current_boss must be a non-empty string")
        for name in ("turn_number", "features_completed_this_turn"):
            if not isinstance(getattr(self, name), int) or getattr(self, name) < 0:
                raise StateError(f"{name} must be a non-negative int")
        if (not isinstance(self.verified_unit_ids_this_turn, list)
                or not all(isinstance(unit_id, str) and unit_id
                           for unit_id in self.verified_unit_ids_this_turn)
                or len(set(self.verified_unit_ids_this_turn))
                   != len(self.verified_unit_ids_this_turn)):
            raise StateError(
                "verified_unit_ids_this_turn must contain unique non-empty ids")
        if self.mode == "relay":
            if (type(self.max_features_per_turn) is not int
                    or not _MIN_FEATURES_PER_TURN <= self.max_features_per_turn <= _MAX_FEATURES_PER_TURN):
                raise StateError(
                    "relay mode requires integer max_features_per_turn "
                    f"from {_MIN_FEATURES_PER_TURN} to {_MAX_FEATURES_PER_TURN}")
        if self.mode == "continuous" and self.max_features_per_turn is not None:
            raise StateError("continuous mode must have max_features_per_turn = null")

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


# valid status transitions (deterministic state machine)
_TRANSITIONS: dict[str, set[str]] = {
    "ready": {"in_progress", "blocked"},
    "in_progress": {"in_progress", "blocked", "awaiting_handoff", "done"},
    "blocked": {"in_progress", "ready", "awaiting_handoff"},
    "awaiting_handoff": {"ready", "in_progress"},
    "done": {"ready"},
}


class StateManager:
    """Owns the single ``team-state.json`` file and guards every transition."""

    # ownership fields — mutating any of these ALWAYS requires the caller to
    # prove it is the current boss (fail-closed; W1 regression).
    _PROTECTED_FIELDS = frozenset({
        "current_boss", "previous_boss", "mode", "turn_number", "schema_version"})

    def __init__(self, path: str):
        self.path = path

    # -- persistence ----------------------------------------------------------
    def load(self) -> TeamState:
        if not os.path.exists(self.path):
            raise StateError(f"no state file at {self.path}; call init() first")
        with open(self.path, encoding="utf-8") as fh:
            raw = json.load(fh)
        state = TeamState(**raw)
        state.validate()
        return state

    def _atomic_write(self, state: TeamState) -> None:
        state.updated_at = _utcnow()
        state.validate()
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state.to_json(), fh, indent=2)
        os.replace(tmp, self.path)  # atomic on POSIX

    def init(self, *, mode: str = "relay", current_boss: str = "claude",
             goal: Optional[str] = None,
             max_features_per_turn: int = 2) -> TeamState:
        state = TeamState(mode=mode, current_boss=current_boss, goal=goal,
                          max_features_per_turn=(
                              None if mode == "continuous"
                              else max_features_per_turn))
        self._atomic_write(state)
        return state

    # -- guarded mutation -----------------------------------------------------
    def transition(self, *, to_status: Optional[str] = None,
                   actor: Optional[str] = None, **updates: Any) -> TeamState:
        """Apply a validated mutation.

        Turn lock (fail-closed):
          * If ``actor`` is given, it must equal ``current_boss``.
          * Mutating any ownership field (``_PROTECTED_FIELDS``) ALWAYS requires
            ``actor`` supplied AND equal to ``current_boss`` — you cannot
            reassign the boss by simply omitting ``actor`` (closes W1 fail-open).
        Also rejects a status change not permitted by ``_TRANSITIONS``.
        """
        state = self.load()

        touched = self._PROTECTED_FIELDS & set(updates)
        if touched and actor is None:
            raise StateError(
                f"turn lock: mutating ownership fields {sorted(touched)} "
                "requires an explicit actor (fail-closed)")
        if actor is not None and actor != state.current_boss:
            raise StateError(
                f"turn lock: {actor!r} may not mutate state owned by "
                f"{state.current_boss!r}")

        if to_status is not None:
            allowed = _TRANSITIONS.get(state.status, set())
            if to_status not in allowed:
                raise StateError(
                    f"illegal transition {state.status!r} -> {to_status!r} "
                    f"(allowed: {sorted(allowed)})")
            state.status = to_status

        for key, value in updates.items():
            if not hasattr(state, key):
                raise StateError(f"unknown state field {key!r}")
            setattr(state, key, value)

        self._atomic_write(state)
        return state

    # -- convenience: relay handoff ------------------------------------------
    def handoff(self, next_boss: str, actor: Optional[str] = None,
                max_features_per_turn: Any = _UNSET) -> TeamState:
        """Perform a relay handoff: increment turn, swap boss, reset counters.

        Only the current boss may hand off. ``actor`` defaults to the current
        boss and is passed through so the ownership guard is enforced, not bypassed.
        """
        state = self.load()
        if state.mode != "relay":
            raise StateError("handoff() only valid in relay mode")
        actor = actor if actor is not None else state.current_boss
        next_max = (state.max_features_per_turn
                    if max_features_per_turn is _UNSET
                    else max_features_per_turn)
        return self.transition(
            actor=actor,
            to_status="awaiting_handoff",
            previous_boss=state.current_boss,
            current_boss=next_boss,
            turn_number=state.turn_number + 1,
            features_completed_this_turn=0,
            verified_unit_ids_this_turn=[],
            max_features_per_turn=next_max,
            handoff_required=False,
        )

    # -- convenience: record a completed feature ------------------------------
    def record_feature(self, actor: str) -> TeamState:
        """Increment the completed-feature counter and, in relay mode, flag a
        required handoff once the cap is reached."""
        state = self.load()
        done = state.features_completed_this_turn + 1
        handoff_required = bool(
            state.mode == "relay" and state.max_features_per_turn is not None
            and done >= state.max_features_per_turn)
        return self.transition(
            actor=actor,
            features_completed_this_turn=done,
            handoff_required=handoff_required,
        )

    def record_unit(self, actor: str, unit_id: str) -> TeamState:
        """Count a verified atomic unit once for the active turn.

        The legacy numeric counter remains for compatibility and display, while
        the durable id set makes retries idempotent.
        """
        if not isinstance(unit_id, str) or not unit_id:
            raise StateError("unit_id must be a non-empty string")
        state = self.load()
        if unit_id in state.verified_unit_ids_this_turn:
            return state
        ids = [*state.verified_unit_ids_this_turn, unit_id]
        done = state.features_completed_this_turn + 1
        handoff_required = bool(
            state.mode == "relay" and state.max_features_per_turn is not None
            and done >= state.max_features_per_turn)
        return self.transition(
            actor=actor,
            features_completed_this_turn=done,
            verified_unit_ids_this_turn=ids,
            handoff_required=handoff_required,
        )
