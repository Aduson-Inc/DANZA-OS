"""Tests for danzaboss.cortex.budgets — single home for driver budgets.

Covers the P4 T4 contract: tables byte-identical to their previous homes
(cortex/driver_context.py, context/pipeline.py), floor-clamped resolution,
Normal/Full-Power dial presets, fail-closed budgets.json validation,
absent-file defaults, save/load round-trip, and re-export compatibility for
the two modules that previously owned the tables.
"""
import _bootstrap  # noqa
import json
import tempfile
import unittest
from pathlib import Path

from danzaboss.cortex.budgets import (
    BUDGETS_RELPATH,
    DEFAULT_BUDGET,
    DIALS,
    DRIVER_BUDGETS,
    DRIVER_CORTEX,
    DRIVER_FLOORS,
    FULL_POWER_BUDGETS,
    MAX_BUDGET,
    BudgetError,
    load_budgets,
    resolve_budget,
    save_budgets,
    validate_budgets,
)

# Literal copies of the tables as they lived in cortex/driver_context.py
# (DRIVER_CORTEX, DRIVER_BUDGETS, _DEFAULT_BUDGET) before this module became
# their single home. The move must be byte-identical — any drift here changes
# retrieval or budget behavior silently.
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
    "jonathan-builder": 900,
    "samantha-mapper": 900,
    "angela-auditor": 900,
    "bonnie-qa": 800,
    "billy-security": 800,
    "hank-designer": 800,
    "carmella-researcher": 800,
}


def _config(dial: str = "normal", overrides: dict | None = None) -> dict:
    return {"version": 1, "dial": dial, "overrides": overrides or {}}


class TestTablesVerbatim(unittest.TestCase):
    """The moved tables are byte-identical to their previous homes."""

    def test_driver_cortex_moved_verbatim(self):
        self.assertEqual(DRIVER_CORTEX, _EXPECTED_DRIVER_CORTEX)

    def test_driver_budgets_moved_verbatim(self):
        self.assertEqual(DRIVER_BUDGETS, _EXPECTED_DRIVER_BUDGETS)

    def test_default_budget_constant(self):
        self.assertEqual(DEFAULT_BUDGET, 1200)

    def test_max_budget_constant(self):
        self.assertEqual(MAX_BUDGET, 50_000)

    def test_dials(self):
        self.assertEqual(DIALS, ("normal", "full_power"))

    def test_full_power_doubles_every_driver(self):
        self.assertEqual(
            FULL_POWER_BUDGETS,
            {driver: 2 * value for driver, value in DRIVER_BUDGETS.items()})

    def test_floors_jonathan_600_others_400(self):
        self.assertEqual(set(DRIVER_FLOORS), set(DRIVER_BUDGETS))
        self.assertEqual(DRIVER_FLOORS["jonathan-builder"], 600)
        for driver, floor in DRIVER_FLOORS.items():
            if driver != "jonathan-builder":
                self.assertEqual(floor, 400, driver)


class TestResolveBudget(unittest.TestCase):
    """max(floor, override or preset[dial][driver]) — the never-starve rule."""

    def test_normal_preset_is_driver_budgets(self):
        for driver, value in DRIVER_BUDGETS.items():
            self.assertEqual(resolve_budget(driver), value)

    def test_full_power_doubles(self):
        self.assertEqual(resolve_budget("bonnie-qa", dial="full_power"), 1600)
        self.assertEqual(
            resolve_budget("jonathan-builder", dial="full_power"), 1800)

    def test_unknown_driver_gets_default_budget(self):
        self.assertEqual(resolve_budget("nobody"), DEFAULT_BUDGET)

    def test_override_wins_over_preset(self):
        self.assertEqual(resolve_budget("bonnie-qa", override=2000), 2000)

    def test_floor_clamps_sub_floor_override(self):
        self.assertEqual(resolve_budget("bonnie-qa", override=100), 400)

    def test_floor_clamps_jonathan_at_600(self):
        self.assertEqual(
            resolve_budget("jonathan-builder", override=100), 600)

    def test_unknown_dial_raises(self):
        with self.assertRaises(BudgetError):
            resolve_budget("bonnie-qa", dial="economy")


class TestValidateBudgets(unittest.TestCase):
    """Fail-closed: bad shape, dial, keys, or ranges never pass silently."""

    def test_valid_config_returned(self):
        cfg = _config(overrides={"bonnie-qa": 900})
        self.assertIs(validate_budgets(cfg), cfg)

    def test_non_dict_rejected(self):
        with self.assertRaises(BudgetError):
            validate_budgets(["not", "a", "dict"])

    def test_wrong_version_rejected(self):
        with self.assertRaises(BudgetError):
            validate_budgets({"version": 99, "dial": "normal",
                              "overrides": {}})

    def test_unknown_dial_rejected(self):
        with self.assertRaises(BudgetError):
            validate_budgets(_config(dial="economy"))

    def test_unknown_override_key_rejected(self):
        with self.assertRaises(BudgetError):
            validate_budgets(_config(overrides={"nobody": 900}))

    def test_non_int_override_rejected(self):
        with self.assertRaises(BudgetError):
            validate_budgets(_config(overrides={"bonnie-qa": "900"}))

    def test_bool_override_rejected(self):
        with self.assertRaises(BudgetError):
            validate_budgets(_config(overrides={"bonnie-qa": True}))

    def test_sub_floor_override_rejected(self):
        with self.assertRaises(BudgetError):
            validate_budgets(_config(overrides={"bonnie-qa": 399}))

    def test_over_max_override_rejected(self):
        with self.assertRaises(BudgetError):
            validate_budgets(_config(overrides={"bonnie-qa": MAX_BUDGET + 1}))

    def test_overrides_must_be_dict(self):
        with self.assertRaises(BudgetError):
            validate_budgets({"version": 1, "dial": "normal",
                              "overrides": ["bonnie-qa"]})


class TestPersistence(unittest.TestCase):
    """budgets.json: absent-file defaults, round-trip, corrupt fails closed."""

    def test_load_missing_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(
                load_budgets(root),
                {"version": 1, "dial": "normal", "overrides": {}})

    def test_round_trip(self):
        cfg = _config(dial="full_power", overrides={"bonnie-qa": 900})
        with tempfile.TemporaryDirectory() as root:
            path = save_budgets(root, cfg)
            self.assertEqual(path, Path(root) / BUDGETS_RELPATH)
            self.assertEqual(load_budgets(root), cfg)

    def test_save_rejects_invalid_config(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(BudgetError):
                save_budgets(root, _config(dial="economy"))
            self.assertFalse((Path(root) / BUDGETS_RELPATH).exists())

    def test_load_corrupt_json_raises(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / BUDGETS_RELPATH
            path.parent.mkdir(parents=True)
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(BudgetError):
                load_budgets(root)

    def test_load_invalid_config_raises(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / BUDGETS_RELPATH
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(_config(dial="economy")),
                            encoding="utf-8")
            with self.assertRaises(BudgetError):
                load_budgets(root)


class TestReExportCompat(unittest.TestCase):
    """The previous table homes keep working for existing importers."""

    def test_driver_context_reexports(self):
        from danzaboss.cortex.driver_context import (
            DRIVER_BUDGETS as dc_budgets, DRIVER_CORTEX as dc_cortex)
        self.assertIs(dc_budgets, DRIVER_BUDGETS)
        self.assertIs(dc_cortex, DRIVER_CORTEX)

    def test_default_budget_delegates_to_resolve(self):
        from danzaboss.cortex.driver_context import default_budget
        self.assertEqual(default_budget("jonathan-builder"), 900)
        self.assertEqual(default_budget("nobody"), DEFAULT_BUDGET)

    def test_pipeline_imports_shared_table(self):
        from danzaboss.context.pipeline import DRIVER_CORTEX as pl_cortex
        self.assertIs(pl_cortex, DRIVER_CORTEX)


if __name__ == "__main__":
    unittest.main()
