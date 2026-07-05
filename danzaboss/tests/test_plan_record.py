"""W1-P3 task record extension: plan_schema.json and decompose.Task gain
the design-spec section-6 planning fields without disturbing the
Upgrade-#4 verifiable-task gate."""
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
        for name in ("kind", "size_est", "depends_on", "writes", "flags"):
            self.assertIn(name, self.props)

    def test_kind_enum_matches_module_constant(self):
        self.assertEqual(tuple(self.props["kind"]["enum"]), TASK_KINDS)

    def test_size_est_capped_at_30(self):
        self.assertEqual(self.props["size_est"]["maximum"], 30)

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
