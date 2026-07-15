"""Plan record/schema fields, including Phase 4.1 atomic product links."""
import json
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.planning.decompose import (HARD_STOP_FLAGS, TASK_KINDS, Task,
                                          Verification, VerificationKind)

SCHEMA = Path(__file__).resolve().parents[1] / "planning" / "plan_schema.json"


class SchemaExtension(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.task_def = self.schema["definitions"]["task"]
        self.props = self.task_def["properties"]

    def test_new_fields_declared(self):
        for name in ("feature_id", "kind", "size_est", "depends_on", "writes",
                     "flags"):
            self.assertIn(name, self.props)

    def test_kind_enum_matches_module_constant(self):
        self.assertEqual(tuple(self.props["kind"]["enum"]), TASK_KINDS)

    def test_atomic_size_est_capped_at_20(self):
        atomic_rule = next(
            rule for rule in self.task_def["allOf"]
            if rule["if"]["properties"]["id"].get("pattern") == "^\\d+-[A-Z]$"
        )
        self.assertEqual(
            atomic_rule["then"]["properties"]["size_est"]["maximum"], 20)
        self.assertIn("feature_id", atomic_rule["then"]["required"])

    def test_writes_capped_at_3_files(self):
        self.assertEqual(self.props["writes"]["maxItems"], 3)

    def test_flags_enum_matches_hard_stops(self):
        self.assertEqual(tuple(self.props["flags"]["items"]["enum"]),
                         HARD_STOP_FLAGS)

    def test_new_fields_stay_optional(self):
        self.assertEqual(self.task_def["required"], ["id", "description"])


class TaskRecordDefaults(unittest.TestCase):
    def test_legacy_construction_still_works(self):
        task = Task(id="t1", description="build the thing")
        self.assertIsNone(task.kind)
        self.assertIsNone(task.size_est)
        self.assertIsNone(task.feature_id)
        self.assertEqual(task.depends_on, ())
        self.assertEqual(task.writes, ())
        self.assertEqual(task.flags, ())

    def test_gate_ignores_new_fields(self):
        task = Task(id="t1", description="one thing", kind="backend",
                    size_est=20, writes=("a.py",),
                    verification=Verification(
                        VerificationKind.AUTOMATED_TEST, "pytest -k x"))
        self.assertTrue(task.ready_for_dispatch())


if __name__ == "__main__":
    unittest.main()
