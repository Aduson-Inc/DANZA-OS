"""Single home for per-driver budgets and retrieval profiles (P4 T4).

Why this module exists: the per-driver tables lived in two places —
``DRIVER_CORTEX`` was duplicated in both ``cortex/driver_context.py`` and
``context/pipeline.py``, and ``DRIVER_BUDGETS`` sat next to one copy — so a
budget or profile change had to be made twice or it silently diverged. Phase 4
adds a Normal/Full-Power dial and floor-protected per-driver overrides
(Decision 4: floors are the never-starve guarantee — context quality is never
compromised to save tokens), which needs exactly one authoritative table.
Both previous homes now import from here; the values moved verbatim.

budgets.json (``.danza/runtime/budgets.json``) persists the app user's dial
and advanced overrides. Absent file means defaults — a fresh repo runs at
Normal with no overrides; a corrupt or out-of-range file fails closed.

Stdlib only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1

BUDGETS_RELPATH: Path = Path(".danza") / "runtime" / "budgets.json"

# The token-economy dial (Decision 4): Normal or Full Power, no Economy —
# starving a driver's context is never on the menu.
DIALS = ("normal", "full_power")

# Per-driver CORTEX retrieval profiles. `intent` is forced (intent_override);
# `types` narrows the candidate pool. Moved verbatim from
# cortex/driver_context.py (previously duplicated in context/pipeline.py).
DRIVER_CORTEX: dict[str, dict] = {
    "jonathan-builder":    {"intent": "write_code",
                            "types": ["convention", "decision",
                                      "impl_detail", "api_behavior"]},
    "samantha-mapper":     {"intent": "architecture",
                            "types": ["decision", "impl_detail",
                                      "milestone", "convention"]},
    "angela-auditor":      {"intent": "planning",
                            "types": ["decision", "milestone", "lesson"]},
    "bonnie-qa":           {"intent": "testing",
                            "types": ["bug_fix", "root_cause", "limitation"]},
    "carmella-researcher": {"intent": "learning",
                            "types": ["lesson", "api_behavior", "dependency"]},
    "hank-designer":       {"intent": "write_code",
                            "types": ["convention", "decision"]},
    "billy-security":      {"intent": "security",
                            "types": ["security", "dependency", "decision"]},
    "tony-d-orchestrator": {"intent": "planning", "types": None},
}

# Per-driver default context token budgets — the Normal preset. Moved
# verbatim from cortex/driver_context.py. Unknown drivers get DEFAULT_BUDGET.
DRIVER_BUDGETS: dict[str, int] = {
    "jonathan-builder": 900,
    "samantha-mapper": 900,
    "angela-auditor": 900,
    "bonnie-qa": 800,
    "billy-security": 800,
    "hank-designer": 800,
    "carmella-researcher": 800,
}

# Full Power doubles every driver's Normal budget: same shape of context,
# twice the room. Derived, so the presets can never drift apart.
FULL_POWER_BUDGETS: dict[str, int] = {
    driver: 2 * value for driver, value in DRIVER_BUDGETS.items()
}

_PRESETS: dict[str, dict[str, int]] = {
    "normal": DRIVER_BUDGETS,
    "full_power": FULL_POWER_BUDGETS,
}

# Floors — the minimum context a driver can ever be handed, whatever the dial
# or override says (Decision 4). The builder writes the code, so its floor is
# highest; every other specialist still gets enough to stay grounded.
DRIVER_FLOORS: dict[str, int] = {
    driver: 600 if driver == "jonathan-builder" else 400
    for driver in DRIVER_BUDGETS
}
_UNKNOWN_FLOOR = 400

DEFAULT_BUDGET = 1200  # unknown drivers (was driver_context._DEFAULT_BUDGET)
MAX_BUDGET = 50_000


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class BudgetError(ValueError):
    """Invalid dial, override, or budgets.json state."""


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve_budget(driver: str, *, dial: str = "normal",
                   override: int | None = None) -> int:
    """max(floor, override or preset[dial][driver]); floors are the
    never-starve guarantee (Decision 4).

    The override (advanced, per-driver) beats the dial preset; the floor
    beats both. Unknown drivers resolve to DEFAULT_BUDGET on either dial —
    there is no role table entry to double. An unknown dial raises: a typo
    must never quietly run at Normal."""
    if dial not in DIALS:
        raise BudgetError(f"unknown dial {dial!r}; expected one of {DIALS!r}")
    value = override if override is not None else \
        _PRESETS[dial].get(driver, DEFAULT_BUDGET)
    return max(DRIVER_FLOORS.get(driver, _UNKNOWN_FLOOR), value)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_budgets(config: object) -> dict:
    """Validate a budgets dict. Returns it on success; raises BudgetError
    describing the first violation.

    Fail-closed: version, dial in DIALS, overrides a dict keyed by known
    drivers with int values inside [floor, MAX_BUDGET] (Decision 4:
    out-of-range values are rejected at the door, not clamped in storage —
    resolve_budget's clamp is a runtime guarantee, not an excuse to persist
    bad data)."""
    if not isinstance(config, dict):
        raise BudgetError(
            f"budgets must be a dict, got {type(config).__name__!r}"
        )

    version = config.get("version")
    if version != SCHEMA_VERSION:
        raise BudgetError(
            f"budgets version {version!r} != expected {SCHEMA_VERSION} — "
            f"open the dashboard SETUP tab to reset your power settings"
        )

    dial = config.get("dial")
    if dial not in DIALS:
        raise BudgetError(
            f"unknown dial {dial!r}; expected one of {DIALS!r}"
        )

    overrides = config.get("overrides")
    if not isinstance(overrides, dict):
        raise BudgetError(
            f"'overrides' must be a dict, got {type(overrides).__name__!r}"
        )
    for driver, value in overrides.items():
        if driver not in DRIVER_BUDGETS:
            raise BudgetError(
                f"override for unknown driver {driver!r}; known drivers: "
                f"{sorted(DRIVER_BUDGETS)!r}"
            )
        if not isinstance(value, int) or isinstance(value, bool):
            raise BudgetError(
                f"override for {driver!r} must be an int, got {value!r}"
            )
        floor = DRIVER_FLOORS[driver]
        if not floor <= value <= MAX_BUDGET:
            raise BudgetError(
                f"override for {driver!r} is {value}; must be between the "
                f"role's floor ({floor}) and {MAX_BUDGET}"
            )

    return config


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_budgets(root: str | os.PathLike, config: dict) -> Path:
    """Validate *config* and atomically write it to BUDGETS_RELPATH under
    *root*.

    Atomic write (tmp -> os.replace) so a crash never leaves a torn file.
    Plain overwrite is correct: the SETUP tab writes the whole power
    configuration at once. Same reasoning as save_routing/save_runners."""
    validate_budgets(config)
    path = Path(root) / BUDGETS_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(config, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_budgets(root: str | os.PathLike) -> dict:
    """Read budgets from BUDGETS_RELPATH under *root*.

    Missing file -> the defaults (Normal dial, no overrides): budgets.json
    is optional by design (Decision 7 — setup is complete without it), so
    absence is a valid state, not an error. Corrupt JSON or an invalid
    config raises BudgetError — a file that EXISTS but can't be trusted must
    never silently fall back to defaults."""
    path = Path(root) / BUDGETS_RELPATH
    if not path.exists():
        return {"version": SCHEMA_VERSION, "dial": "normal", "overrides": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BudgetError(
            f"budgets file at {path} is not valid JSON: {exc}"
        ) from exc
    return validate_budgets(raw)
