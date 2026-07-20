"""First-task seed and second-task CORTEX injection contract."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from danzaboss.cortex.events import CaptureLog
from danzaboss.cortex.factory import db_path
from danzaboss.cortex.tasks import start_task


class TaskMemoryContract(unittest.TestCase):
    def test_first_task_seeds_without_injection_second_receives_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = start_task(
                root, "task-1", "jonathan-builder",
                "build the authenticated request path",
                seed={"type": "decision", "title": "Auth boundary",
                      "summary": "The project keeps authentication local.",
                      "concepts": ["authentication"]})
            self.assertTrue(first.seeded)
            self.assertEqual(first.task_number, 1)
            self.assertEqual(first.context, "")

            second = start_task(
                root, "task-2", "jonathan-builder",
                "implement the authentication boundary")
            self.assertFalse(second.seeded)
            self.assertEqual(second.task_number, 2)
            self.assertIn("Auth boundary", second.context)
            self.assertGreaterEqual(second.context_tokens, 1)
            stats = CaptureLog(db_path(str(root))).context_read_stats(
                root.name)
            self.assertEqual(stats["jonathan-builder"]["reads"], 1)

    def test_first_task_cannot_skip_verified_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "requires a verified"):
                start_task(tmp, "task-1", "jonathan-builder", "build it")


if __name__ == "__main__":
    unittest.main()
