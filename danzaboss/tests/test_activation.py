"""Installation activation creates a usable project before onboarding."""
from __future__ import annotations

import json
import os
import signal
import io
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import _bootstrap  # noqa: F401

from danzaboss.product.activation import activate_project, verify_installation
from danzaboss.product.connection import launch_runner, verify_runner
from danzaboss.cortex.tasks import start_task
from danzaboss import cli


class ActivationContract(unittest.TestCase):
    def test_activate_prints_dashboard_url_after_starting_ui(self):
        output = io.StringIO()
        report = {
            "status": "awaiting_ai_connection",
            "project_initialized": True,
            "cortex": True,
            "ui": True,
            "ai_connection": False,
            "missing": [],
        }
        with patch("danzaboss.product.activation.activate_project") as activate, \
                patch("danzaboss.product.activation.wait_for_ui", return_value=True), \
                patch("danzaboss.product.activation.verify_installation",
                      return_value=report), \
                patch("danzaboss.cli.webbrowser.open", return_value=True) as open_browser, \
                redirect_stdout(output):
            result = cli._cmd_activate(["/tmp/project"])

        self.assertEqual(result, 0)
        self.assertIn("http://localhost:33000", output.getvalue())
        activate.assert_called_once_with("/tmp/project", start_ui_process=True,
                                         open_browser=False)
        open_browser.assert_called_once_with("http://localhost:33000")

    def test_launch_runner_uses_one_project_session_and_opens_terminal(self):
        calls = []
        terminal_calls = []

        class Result:
            def __init__(self, returncode, stdout=""):
                self.returncode = returncode
                self.stderr = ""
                self.stdout = stdout

        def run(argv, **kwargs):
            calls.append(argv)
            # First health check says the shared project session is new; the
            # post-launch health check proves it stayed alive.
            if argv[1] == "has-session":
                return Result(1 if len([a for a in calls if a[1] == "has-session"]) == 1 else 0)
            return Result(0, "%0\n")

        def popen(argv, **kwargs):
            terminal_calls.append(argv)

        proof = launch_runner(
            "/tmp/demo-project", "codex",
            {"runners": {"codex": {
                "detected": True, "auth": "unprobed",
                "interactive": ["codex"], "kind": "cli"}}},
            run=run, popen=popen,
            which=lambda name: "/usr/bin/tmux" if name == "tmux" else
            ("/usr/bin/x-terminal-emulator" if name == "x-terminal-emulator"
             else None))
        self.assertEqual(proof["status"], "launched")
        self.assertEqual(proof["runner"], "codex")
        self.assertEqual(proof["session"], "danza-project-demo-project")
        self.assertTrue(proof["terminal"]["opened"])
        self.assertEqual(len(terminal_calls), 1)
        self.assertEqual(calls[0][0:3], ["tmux", "has-session", "-t"])
        self.assertEqual(calls[1][0:2], ["tmux", "new-session"])
        self.assertIn("codex", calls[1])
        self.assertEqual(calls[2][0:2], ["tmux", "has-session"])

    def test_second_runner_gets_a_pane_in_the_same_project_session(self):
        calls = []

        class Result:
            returncode = 0
            stderr = ""
            stdout = "%1\n"

        def run(argv, **kwargs):
            calls.append(argv)
            return Result()

        proof = launch_runner(
            "/tmp/demo-project", "claude",
            {"runners": {"claude": {
                "detected": True, "auth": "unprobed",
                "interactive": ["claude"], "kind": "cli"}}},
            run=run, popen=lambda *args, **kwargs: None,
            which=lambda name: "/usr/bin/tmux" if name == "tmux" else None)
        self.assertEqual(proof["status"], "already_running")
        self.assertEqual(proof["session"], "danza-project-demo-project")
        self.assertEqual(calls[0][0:3], ["tmux", "has-session", "-t"])
        self.assertEqual(calls[1][0:2], ["tmux", "split-window"])
        self.assertIn("=danza-project-demo-project", calls[1])

    def test_launch_runner_falls_back_to_native_terminal_without_tmux(self):
        terminal_calls = []

        def popen(argv, **kwargs):
            terminal_calls.append(argv)

        proof = launch_runner(
            "/tmp/demo-project", "gemini",
            {"runners": {"gemini": {
                "detected": True, "auth": "unprobed",
                "interactive": ["gemini"], "kind": "cli"}}},
            run=lambda *args, **kwargs: self.fail("tmux must not be used"),
            popen=popen,
            which=lambda name: "/usr/bin/x-terminal-emulator"
            if name == "x-terminal-emulator" else None)
        self.assertEqual(proof["status"], "launched")
        self.assertEqual(proof["host"], "native_terminal")
        self.assertTrue(proof["terminal"]["opened"])
        self.assertEqual(terminal_calls[0][0], "x-terminal-emulator")
        self.assertIn("gemini", terminal_calls[0])

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
