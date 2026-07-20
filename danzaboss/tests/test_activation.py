"""Installation activation creates a usable project before onboarding."""
from __future__ import annotations

import json
import os
import signal
import tempfile
import time
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from danzaboss.product.activation import activate_project, verify_installation
from danzaboss.product.connection import launch_runner, verify_runner
from danzaboss.cortex.tasks import start_task


class ActivationContract(unittest.TestCase):
    def test_launch_runner_uses_project_scoped_tmux_session(self):
        calls = []

        class Result:
            def __init__(self, returncode):
                self.returncode = returncode
                self.stderr = ""

        def run(argv, **kwargs):
            calls.append(argv)
            return Result(1 if argv[1] == "has-session" else 0)

        proof = launch_runner(
            "/tmp/demo-project", "codex",
            {"runners": {"codex": {
                "detected": True, "auth": "unprobed",
                "interactive": ["codex"], "kind": "cli"}}},
            run=run, which=lambda name: "/usr/bin/tmux")
        self.assertEqual(proof["status"], "launched")
        self.assertEqual(proof["runner"], "codex")
        self.assertEqual(calls[0][0:3], ["tmux", "has-session", "-t"])
        self.assertEqual(calls[1][0:2], ["tmux", "new-session"])
        self.assertIn("codex", calls[1])

    def test_activation_scaffolds_cortex_and_runtime_without_ui_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            result = activate_project(root, start_ui_process=False)
            self.assertTrue(result["cortex"])
            self.assertTrue((root / ".danza" / "cortex" / "cortex.db").is_file())
            self.assertTrue((root / ".danza" / "runtime" / "team-state.json").is_file())
            installation = json.loads(
                (root / ".danza" / "runtime" / "installation.json")
                .read_text(encoding="utf-8"))
            self.assertEqual(installation["status"], "active")
            report = verify_installation(root)
            self.assertEqual(report["status"], "awaiting_ai_connection")
            self.assertFalse(report["ui"])
            self.assertFalse(report["ai_connection"])

    def test_end_to_end_activation_connection_and_verified_project_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            activate_project(root, start_ui_process=True, open_browser=False)
            pid = int((root / ".danza" / "runtime" / "ui.pid")
                      .read_text(encoding="utf-8"))
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    report = verify_installation(root)
                    if report["ui"]:
                        break
                    time.sleep(0.05)
                self.assertTrue(report["ui"], report)
                proof = verify_runner(root, "test-client", {
                    "runners": {"test-client": {
                        "detected": True, "auth": "ok", "kind": "provider",
                        "model": "test-model"}}})
                self.assertEqual(proof["status"], "verified")
                final = verify_installation(root, require_connection=True)
                self.assertEqual(final["status"], "verified", final)
                first = start_task(
                    root, "idea-1", "tony-d-orchestrator",
                    "turn the user idea into a working project",
                    seed={"type": "decision", "title": "User idea",
                          "summary": "A verified project idea to implement."})
                self.assertTrue(first.seeded)
                second = start_task(
                    root, "idea-2", "jonathan-builder",
                    "implement the verified project idea")
                self.assertIn("User idea", second.context)
            finally:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                for _ in range(20):
                    try:
                        waited, _ = os.waitpid(pid, os.WNOHANG)
                    except ChildProcessError:
                        break
                    if waited:
                        break
                    time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
