"""W1-P1 wizard persistence: Rule 35 discipline in code — read-then-merge,
atomic replace, unknown keys on disk survive a save."""
import json
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.workstation.state import load_state, save_state, state_path


class StateRoundTrip(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_load_missing_file_returns_empty_shape(self):
        state = load_state(self.root)
        self.assertEqual(state["answers"], {})
        self.assertEqual(state["steps"], {})

    def test_save_then_load_round_trips(self):
        save_state(self.root, {"answers": {"project_type": "saas"},
                               "steps": {"p0": {"status": "complete"}}})
        state = load_state(self.root)
        self.assertEqual(state["answers"]["project_type"], "saas")
        self.assertEqual(state["steps"]["p0"]["status"], "complete")

    def test_save_preserves_unknown_top_level_keys(self):
        path = state_path(self.root)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"answers": {}, "steps": {},
                                    "other_writer": {"keep": True}}))
        save_state(self.root, {"answers": {"a": "b"}, "steps": {}})
        on_disk = json.loads(path.read_text())
        self.assertEqual(on_disk["other_writer"], {"keep": True})
        self.assertEqual(on_disk["answers"], {"a": "b"})

    def test_no_tmp_file_left_behind(self):
        save_state(self.root, {"answers": {}, "steps": {}})
        leftovers = list(state_path(self.root).parent.glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_corrupt_non_object_state_raises(self):
        path = state_path(self.root)
        path.parent.mkdir(parents=True)
        path.write_text("[1, 2, 3]")
        with self.assertRaises(ValueError):
            load_state(self.root)


if __name__ == "__main__":
    unittest.main()
