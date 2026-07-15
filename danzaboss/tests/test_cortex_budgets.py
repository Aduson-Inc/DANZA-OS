"""Tests for the authoritative adaptive per-driver CORTEX budget policy.

Covers the Phase 4.1 Task 10 base/ceiling policy while retaining the dial-free
one-argument resolution and re-export compatibility established in Phase 4.
"""
import _bootstrap  # noqa
import inspect
import unittest

from danzaboss.cortex.budgets import (
    DEFAULT_CEILING,
    DEFAULT_BUDGET,
    DRIVER_BUDGETS,
    DRIVER_CEILINGS,
    DRIVER_CORTEX,
    DRIVER_FLOORS,
    resolve_budget,
    resolve_policy,
)

# The retrieval profile remains byte-identical to its pre-policy source. The
# budget tables below pin the binding Phase 4.1 Task 10 bases and ceilings.
_EXPECTED_DRIVER_CORTEX = {
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

_EXPECTED_DRIVER_BUDGETS = {
    "tony-d-orchestrator": 2400,
    "jonathan-builder": 2400,
    "samantha-mapper": 2400,
    "angela-auditor": 2400,
    "bonnie-qa": 2000,
    "billy-security": 2000,
    "hank-designer": 2000,
    "carmella-researcher": 2000,
}

_EXPECTED_DRIVER_CEILINGS = {
    "tony-d-orchestrator": 4000,
    "jonathan-builder": 4000,
    "samantha-mapper": 4000,
    "angela-auditor": 4000,
    "bonnie-qa": 3500,
    "billy-security": 3500,
    "hank-designer": 3500,
    "carmella-researcher": 3500,
}


class TestPolicyTables(unittest.TestCase):
    """Retrieval profiles stay stable while role budget policy is adaptive."""

    def test_driver_cortex_moved_verbatim(self):
        self.assertEqual(DRIVER_CORTEX, _EXPECTED_DRIVER_CORTEX)

    def test_driver_budgets_moved_verbatim(self):
        self.assertEqual(DRIVER_BUDGETS, _EXPECTED_DRIVER_BUDGETS)

    def test_default_budget_constant(self):
        self.assertEqual(DEFAULT_BUDGET, 2400)
        self.assertEqual(DEFAULT_CEILING, 4000)

    def test_driver_ceilings_match_binding_policy(self):
        self.assertEqual(DRIVER_CEILINGS, _EXPECTED_DRIVER_CEILINGS)

    def test_floors_jonathan_600_others_400(self):
        self.assertEqual(set(DRIVER_FLOORS), set(DRIVER_BUDGETS))
        self.assertEqual(DRIVER_FLOORS["jonathan-builder"], 600)
        for driver, floor in DRIVER_FLOORS.items():
            if driver != "jonathan-builder":
                self.assertEqual(floor, 400, driver)

    def test_dial_surface_is_gone(self):
        # the Normal/Full-Power dial and budgets.json persistence were
        # removed 2026-07-14 — CORTEX self-budgets from the tables above
        import danzaboss.cortex.budgets as budgets_mod
        for name in ("DIALS", "FULL_POWER_BUDGETS", "load_budgets",
                     "save_budgets", "validate_budgets", "BudgetError",
                     "BUDGETS_RELPATH"):
            self.assertFalse(hasattr(budgets_mod, name), name)


class TestResolveBudget(unittest.TestCase):
    """max(floor, DRIVER_BUDGETS[driver]) — the never-starve rule."""

    def test_known_drivers_resolve_to_their_table_value(self):
        for driver, value in DRIVER_BUDGETS.items():
            self.assertEqual(resolve_budget(driver), value)

    def test_unknown_driver_gets_default_budget(self):
        self.assertEqual(resolve_budget("nobody"), DEFAULT_BUDGET)

    def test_signature_is_one_arg(self):
        # dial/override params left with the dial — a stale keyword call
        # must fail loudly, not silently run at Normal
        params = inspect.signature(resolve_budget).parameters
        self.assertEqual(list(params), ["driver"])

    def test_policy_resolves_exact_role_pairs_and_unknown_fallback(self):
        for driver, base in _EXPECTED_DRIVER_BUDGETS.items():
            policy = resolve_policy(driver)
            self.assertEqual((policy.base, policy.ceiling),
                             (base, _EXPECTED_DRIVER_CEILINGS[driver]))
        unknown = resolve_policy("nobody")
        self.assertEqual((unknown.base, unknown.ceiling), (2400, 4000))


class TestReExportCompat(unittest.TestCase):
    """The previous table homes keep working for existing importers."""

    def test_driver_context_reexports(self):
        from danzaboss.cortex.driver_context import (
            DRIVER_BUDGETS as dc_budgets, DRIVER_CORTEX as dc_cortex)
        self.assertIs(dc_budgets, DRIVER_BUDGETS)
        self.assertIs(dc_cortex, DRIVER_CORTEX)

    def test_default_budget_delegates_to_resolve(self):
        from danzaboss.cortex.driver_context import default_budget
        self.assertEqual(default_budget("jonathan-builder"), 2400)
        self.assertEqual(default_budget("nobody"), DEFAULT_BUDGET)

    def test_pipeline_imports_shared_table(self):
        from danzaboss.context.pipeline import DRIVER_CORTEX as pl_cortex
        self.assertIs(pl_cortex, DRIVER_CORTEX)


if __name__ == "__main__":
    unittest.main()
