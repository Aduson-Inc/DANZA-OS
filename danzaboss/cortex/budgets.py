"""Single home for per-driver budgets and retrieval profiles (P4 T4).

Why this module exists: the per-driver tables lived in two places —
``DRIVER_CORTEX`` was duplicated in both ``cortex/driver_context.py`` and
``context/pipeline.py``, and ``DRIVER_BUDGETS`` sat next to one copy — so a
budget or profile change had to be made twice or it silently diverged. This
module is the one authoritative table; both previous homes import from here.

Budgets are internal constants, not user settings: CORTEX self-budgets each
driver's context from tested role bases and one qualified expansion ceiling.
The floors retain the older compatibility contract but do not affect the
larger Phase 4.1 bases.
The Phase 4 Normal/Full-Power dial and per-role overrides that briefly lived
here were removed 2026-07-14 — they persisted a budgets.json that no runtime
path ever read, and the user-facing knob that matters (how much each turn
builds) lives in routing.json ``features_per_turn`` instead.

Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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

# Per-driver adaptive context policy. DRIVER_BUDGETS retains its historical
# import contract and represents the base values; DRIVER_CEILINGS supplies the
# single qualified expansion cap. Unknown drivers use the default pair.
DRIVER_BUDGETS: dict[str, int] = {
    "tony-d-orchestrator": 2400,
    "jonathan-builder": 2400,
    "samantha-mapper": 2400,
    "angela-auditor": 2400,
    "bonnie-qa": 2000,
    "billy-security": 2000,
    "hank-designer": 2000,
    "carmella-researcher": 2000,
}

DRIVER_CEILINGS: dict[str, int] = {
    "tony-d-orchestrator": 4000,
    "jonathan-builder": 4000,
    "samantha-mapper": 4000,
    "angela-auditor": 4000,
    "bonnie-qa": 3500,
    "billy-security": 3500,
    "hank-designer": 3500,
    "carmella-researcher": 3500,
}

# Floors — the minimum context a driver can ever be handed. The builder
# writes the code, so its floor is highest; every other specialist still
# gets enough to stay grounded.
DRIVER_FLOORS: dict[str, int] = {
    driver: 600 if driver == "jonathan-builder" else 400
    for driver in DRIVER_BUDGETS
}
_UNKNOWN_FLOOR = 400

DEFAULT_BUDGET = 2400
DEFAULT_CEILING = 4000


@dataclass(frozen=True)
class BudgetPolicy:
    base: int
    ceiling: int


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve_budget(driver: str) -> int:
    """max(floor, DRIVER_BUDGETS[driver]); floors are the never-starve
    guarantee. Unknown drivers resolve to DEFAULT_BUDGET — there is no role
    table entry to consult."""
    value = DRIVER_BUDGETS.get(driver, DEFAULT_BUDGET)
    return max(DRIVER_FLOORS.get(driver, _UNKNOWN_FLOOR), value)


def resolve_policy(driver: str) -> BudgetPolicy:
    """Resolve the deterministic base/ceiling pair for one driver."""
    return BudgetPolicy(
        base=resolve_budget(driver),
        ceiling=DRIVER_CEILINGS.get(driver, DEFAULT_CEILING),
    )
