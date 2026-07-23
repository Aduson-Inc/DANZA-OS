"""Installation activation creates a usable project before onboarding."""
from __future__ import annotations

import json
import os
import signal
import io
import shutil
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import _bootstrap  # noqa: F401

from danzaboss.product.activation import (activate_project, clear_ui_port,
                                          verify_installation, wait_for_ui)
from danzaboss.product.connection import (launch_runner, prepare_workspace,
                                           verify_runner)
from danzaboss.cortex.tasks import start_task
from danzaboss import cli


class ActivationContract(unittest.TestCase):
    def test_clear_ui_port_stops_an_existing_danza_ui(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "new-project"
            other = Path(tmp) / "old-project"
            pid_path = other / ".danza" / "runtime" / "ui.pid"
            pid_path.parent.mkdir(parents=True)
            pid_path.write_text("4242\n", encoding="utf-8")
            with patch("danzaboss.product.activation._port_available",
                       side_effect=[False, True]), \
                    patch("danzaboss.product.activation._ui_overview",
                          return_value={"root": str(other)}), \
                    patch("danzaboss.product.activation._terminate_pid") as stop:
                clear_ui_port(root)
            stop.assert_called_once_with(4242)

    def test_clear_ui_port_refuses_an_unknown_process(self):
        with patch("danzaboss.product.activation._port_available",
                   return_value=False), \
                patch("danzaboss.product.activation._ui_overview",
                      return_value=None):
            with self.assertRaisesRegex(OSError, "another application"):
                clear_ui_port("/tmp/new-project")

    def test_wait_for_ui_rejects_a_different_project_on_same_port(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"root": "/tmp/other-project"}).encode()

        with patch("danzaboss.product.activation.urllib.request.urlopen",
                   return_value=Response()):
            self.assertFalse(wait_for_ui(expected_root="/tmp/this-project",
                                         timeout=0.01))

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
                patch("danzaboss.product.activation.wait_for_ui", return_value=True) as wait, \
                patch("danzaboss.product.activation.verify_installation",
                      return_value=report), \
                patch("danzaboss.cli.webbrowser.open", return_value=True) as open_browser, \
                redirect_stdout(output):
            result = cli._cmd_activate(["/tmp/project"])

        self.assertEqual(result, 0)
        self.assertIn("http://localhost:33000", output.getvalue())
        activate.assert_called_once_with("/tmp/project", start_ui_process=True,
                                         open_browser=False)
        wait.assert_called_once_with(expected_root="/tmp/project")
        open_browser.assert_called_once_with("http://localhost:33000")

    def test_launch_runner_uses_one_project_session_and_opens_terminal(self):
        root = tempfile.mkdtemp(prefix="danzaboss-launch-")
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
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
            root, "codex",
            {"runners": {"codex": {
                "detected": True, "auth": "unprobed",
                "interactive": ["codex"], "kind": "cli"}}},
            run=run, popen=popen,
            which=lambda name: "/usr/bin/tmux" if name == "tmux" else
            ("/usr/bin/x-terminal-emulator" if name == "x-terminal-emulator"
             else None))
        self.assertEqual(proof["status"], "launched")
        self.assertEqual(proof["runner"], "codex")
        self.assertTrue(proof["session"].startswith("danza-"))
        self.assertTrue(proof["terminal"]["opened"])
        self.assertEqual(len(terminal_calls), 1)
        self.assertEqual(calls[0][0:3], ["tmux", "has-session", "-t"])
        self.assertEqual(calls[1][0:2], ["tmux", "new-session"])
        self.assertIn("codex", calls[1])
        self.assertEqual(calls[2][0:2], ["tmux", "has-session"])

    def test_second_runner_gets_a_pane_in_the_same_project_session(self):
        root = tempfile.mkdtemp(prefix="danzaboss-launch-")
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        calls = []

        class Result:
            returncode = 0
            stderr = ""
            stdout = "%1\n"

        def run(argv, **kwargs):
            calls.append(argv)
            if argv[1] == "has-session" and len(
                    [call for call in calls if call[1] == "has-session"]) == 1:
                return type("Result", (), {"returncode": 1,
                                            "stderr": "", "stdout": ""})()
            return Result()

        config = {"runners": {
            "codex": {"detected": True, "auth": "unprobed",
                      "interactive": ["codex"], "kind": "cli"},
            "claude": {"detected": True, "auth": "unprobed",
                       "interactive": ["claude"], "kind": "cli"}}}
        launch_runner(root, "codex", config, run=run,
                      popen=lambda *args, **kwargs: None,
                      which=lambda name: "/usr/bin/tmux"
                      if name == "tmux" else None)
        proof = launch_runner(
            root, "claude", config, run=run,
            popen=lambda *args, **kwargs: None,
            which=lambda name: "/usr/bin/tmux" if name == "tmux" else None)
        self.assertEqual(proof["status"], "already_running")
        self.assertTrue(proof["session"].startswith("danza-"))
        self.assertFalse(proof["terminal"]["opened"])
        self.assertEqual(calls[0][0:3], ["tmux", "has-session", "-t"])
        self.assertEqual(calls[1][0:2], ["tmux", "new-session"])
        self.assertEqual(calls[4][0:2], ["tmux", "split-window"])
        self.assertIn("=" + proof["session"], calls[4])

    def test_launch_runner_falls_back_to_native_terminal_without_tmux(self):
        root = tempfile.mkdtemp(prefix="danzaboss-launch-")
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        terminal_calls = []

        def popen(argv, **kwargs):
            terminal_calls.append(argv)

        proof = launch_runner(
            root, "gemini",
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

    def test_prepare_workspace_returns_requested_order_and_active_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "demo-project"
            calls = []

            class Result:
                returncode = 0
                stderr = ""
                stdout = "%0\n"

            def run(argv, **kwargs):
                calls.append(argv)
                if argv[1] == "has-session" and len(
                        [call for call in calls if call[1] == "has-session"]) == 1:
                    return type("Result", (), {"returncode": 1,
                                                "stderr": "", "stdout": ""})()
                return Result()

            config = {"runners": {
                "codex": {"detected": True, "auth": "ok",
                          "interactive": ["codex"], "kind": "cli"},
                "claude": {"detected": True, "auth": "ok",
                           "interactive": ["claude"], "kind": "cli"}}}
            launch_runner(root, "codex", config, run=run,
                          popen=lambda *a, **k: None,
                          which=lambda name: "/usr/bin/tmux"
                          if name == "tmux" else None)
            launch_runner(root, "claude", config, run=run,
                          popen=lambda *a, **k: None,
                          which=lambda name: "/usr/bin/tmux"
                          if name == "tmux" else None)
            out = prepare_workspace(root, ["claude", "codex"], config,
                                    run=run, popen=lambda *a, **k: None,
                                    which=lambda name: "/usr/bin/tmux"
                                    if name == "tmux" else None)
            self.assertEqual(out["order"], ["claude", "codex"])
            self.assertEqual(out["active_runner"], "claude")
            self.assertEqual(out["host"], "tmux")
            self.assertTrue(any(call[1] == "swap-pane" for call in calls))

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
