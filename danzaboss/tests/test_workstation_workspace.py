"""Project-local AI workspace state contract."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from danzaboss.workstation.workspace import (
    load_workspace,
    save_workspace,
    session_name,
    workspace_summary,
)


class WorkspaceContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "demo.app"
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_session_name_is_shared_and_safe(self):
        self.assertEqual(session_name(self.root), "danza-demo_app")

    def test_workspace_round_trips_stable_pane_ids(self):
        save_workspace(self.root, {
            "schema_version": 1,
            "session": session_name(self.root),
            "host": "tmux",
            "order": ["claude", "codex"],
            "panes": {"claude": "%1", "codex": "%2"},
            "active_runner": "claude",
            "terminal_opened": True,
        })
        loaded = load_workspace(self.root)
        self.assertEqual(loaded["panes"], {"claude": "%1", "codex": "%2"})
        self.assertEqual(workspace_summary(self.root)["attach_command"],
                         "tmux attach -t danza-demo_app")

    def test_invalid_workspace_fails_closed(self):
        path = self.root / ".danza" / "runtime" / "workspace.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({}), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_workspace(self.root)

    def test_missing_workspace_has_unconfigured_summary(self):
        summary = workspace_summary(self.root)
        self.assertEqual(summary["host"], "unconfigured")
        self.assertEqual(summary["session"], "danza-demo_app")
        self.assertEqual(summary["order"], [])
        self.assertIsNone(summary["attach_command"])


if __name__ == "__main__":
    unittest.main()
