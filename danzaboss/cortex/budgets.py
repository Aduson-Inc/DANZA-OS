"""Single home for per-driver budgets and retrieval profiles (P4 T4).

Why this module exists: the per-driver tables lived in two places —
``DRIVER_CORTEX`` was duplicated in both ``cortex/driver_context.py`` and
``context/pipeline.py``, and ``DRIVER_BUDGETS`` sat next to one copy — so a
budget or profile change had to be made twice or it silently diverged. This
module is the one authoritative table; both previous homes import from here
and the values moved verbatim.

Budgets are internal constants, not user settings: CORTEX self-budgets each
driver's context from these tested defaults, and the floors are the
never-starve guarantee (context quality is never compromised to save tokens).
The Phase 4 Normal/Full-Power dial and per-role overrides that briefly lived
here were removed 2026-07-14 — they persisted a budgets.json that no runtime
path ever read, and the user-facing knob that matters (how much each turn
builds) lives in routing.json ``features_per_turn`` instead.

Stdlib only.
"""
from __future__ import annotations

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

# Per-driver default context token budgets. Moved verbatim from
# cortex/driver_context.py. Unknown drivers get DEFAULT_BUDGET.
DRIVER_BUDGETS: dict[str, int] = {
    "jonathan-builder": 900,
    "samantha-mapper": 900,
    "angela-auditor": 900,
    "bonnie-qa": 800,
    "billy-security": 800,
    "hank-designer": 800,
    "carmella-researcher": 800,
}

# Floors — the minimum context a driver can ever be handed. The builder
# writes the code, so its floor is highest; every other specialist still
# gets enough to stay grounded.
DRIVER_FLOORS: dict[str, int] = {
    driver: 600 if driver == "jonathan-builder" else 400
    for driver in DRIVER_BUDGETS
}
_UNKNOWN_FLOOR = 400

DEFAULT_BUDGET = 1200  # unknown drivers (was driver_context._DEFAULT_BUDGET)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve_budget(driver: str) -> int:
    """max(floor, DRIVER_BUDGETS[driver]); floors are the never-starve
    guarantee. Unknown drivers resolve to DEFAULT_BUDGET — there is no role
    table entry to consult."""
    value = DRIVER_BUDGETS.get(driver, DEFAULT_BUDGET)
    return max(DRIVER_FLOORS.get(driver, _UNKNOWN_FLOOR), value)
