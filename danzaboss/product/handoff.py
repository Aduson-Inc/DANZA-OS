"""Human handoff compatibility plus machine-validation sidecar."""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


HANDOFF_RELPATH = Path(".danza") / "handoff.md"
HANDOFF_STATE_RELPATH = Path(".danza") / "runtime" / "handoff-state.json"
BOOTSTRAP_MARKER = "No handoff yet."


class HandoffMode(str, Enum):
    NEW = "new"
    CONTINUE = "continue"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class HandoffResult:
    mode: HandoffMode
    valid: bool
    reason: str = ""
    state: Optional[dict] = None


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def write_handoff_state(root: str | Path, *, turn_number: int,
                        current_boss: str, next_boss: str,
                        verified_unit_ids: list[str],
                        features_completed_this_turn: int = 0,
                        max_features_per_turn: int | None = 2,
                        blocker: str | None = None,
                        required_reading: list[str] | None = None) -> Path:
    if turn_number < 0 or not current_boss or not next_boss:
        raise ValueError("handoff state requires valid turn ownership")
    if max_features_per_turn is not None and not 2 <= max_features_per_turn <= 5:
        raise ValueError("max_features_per_turn must be 2-5 or null")
    data = {
        "schema_version": 1,
        "turn_number": turn_number,
        "current_boss": current_boss,
        "next_boss": next_boss,
        "features_completed_this_turn": features_completed_this_turn,
        "max_features_per_turn": max_features_per_turn,
        "verified_unit_ids": list(verified_unit_ids),
        "blocker": blocker,
        "required_reading": list(required_reading or []),
        "updated_at": _now(),
    }
    path = Path(root) / HANDOFF_STATE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path


def _validate_state(raw: object) -> tuple[bool, str]:
    if not isinstance(raw, dict):
        return False, "handoff-state.json must be an object"
    required = ("schema_version", "turn_number", "current_boss", "next_boss",
                "verified_unit_ids", "max_features_per_turn")
    if any(key not in raw for key in required):
        return False, "handoff-state.json is missing required fields"
    if raw["schema_version"] != 1 or not isinstance(raw["turn_number"], int):
        return False, "handoff-state.json has an unsupported schema"
    if not isinstance(raw["current_boss"], str) or not raw["current_boss"]:
        return False, "handoff current_boss is invalid"
    if not isinstance(raw["next_boss"], str) or not raw["next_boss"]:
        return False, "handoff next_boss is invalid"
    if not isinstance(raw["verified_unit_ids"], list):
        return False, "handoff verified_unit_ids must be a list"
    cap = raw["max_features_per_turn"]
    if cap is not None and (type(cap) is not int or not 2 <= cap <= 5):
        return False, "handoff max_features_per_turn must be 2-5 or null"
    return True, ""


def classify_handoff(root: str | Path) -> HandoffResult:
    root = Path(root)
    try:
        text = (root / HANDOFF_RELPATH).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return HandoffResult(HandoffMode.BLOCKED, False,
                             "handoff.md is missing or unreadable")
    if not text.strip():
        return HandoffResult(HandoffMode.BLOCKED, False,
                             "handoff.md is empty")
    if BOOTSTRAP_MARKER in text:
        return HandoffResult(HandoffMode.NEW, True)
    try:
        state = json.loads((root / HANDOFF_STATE_RELPATH).read_text(
            encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return HandoffResult(HandoffMode.BLOCKED, False,
                             "runtime handoff sidecar is missing or corrupt")
    valid, reason = _validate_state(state)
    if not valid:
        return HandoffResult(HandoffMode.BLOCKED, False, reason, state)
    return HandoffResult(HandoffMode.CONTINUE, True, state=state)
