"""W1-P4 T5 CLI wiring: `danza runners` and `danza conduct` subcommands.

Invokes cli.main() in-process so the full dispatch path is exercised.
All I/O is captured via redirect_stdout/stderr; no network, no real tmux
or claude binary is needed.
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.cli import main
from danzaboss.kernel.state import StateManager
from danzaboss.workstation import execution, routing
from danzaboss.workstation.planner import PLAN_JSON_RELPATH
from danzaboss.workstation import runners as runners_mod
import danzaboss.workstation.conductor as conductor_mod
from danzaboss.workstation.conductor import (
    PIDFILE_RELPATH,
    TEAM_STATE_RELPATH,
    acquire_pidfile,
)


class RunnersCmd(unittest.TestCase):
    """Tests for `danza runners <root>`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_creates_registry_on_empty_root(self):
        """First run: detect runners, build default config, save, and print
        one human line per runner plus the chosen boss and the path written.
        Does NOT assert on which runners are detected (shutil.which varies)."""
        out = io.StringIO()
        with redirect_stdout(out):
            rc = main(["runners", str(self.root)])
        self.assertEqual(rc, 0)
        registry_path = self.root / runners_mod.RUNNERS_RELPATH
        self.assertTrue(registry_path.exists(), "registry must be written on first run")
        config = runners_mod.load_runners(self.root)
        self.assertIn("runners", config)
        self.assertIn("boss", config)
        output = out.getvalue()
        # Both known runner names appear in the output (detected or not found)
        self.assertIn("claude", output)
        self.assertIn("codex", output)

    def test_does_not_clobber_existing_registry(self):
        """Second run must pretty-print the existing config and NOT overwrite it.
        The /models screen is the only entity that writes runners.json after
        initial detection."""
        # First run creates the registry
        main(["runners", str(self.root)])
        # Hand-edit session_host to verify it survives
        config = runners_mod.load_runners(self.root)
        config["session_host"] = "headless"
        runners_mod.save_runners(self.root, config)
        # Second run
        out = io.StringIO()
        with redirect_stdout(out):
            rc = main(["runners", str(self.root)])
        self.assertEqual(rc, 0)
        config_after = runners_mod.load_runners(self.root)
        self.assertEqual(
            config_after["session_host"],
            "headless",
            "hand-edited session_host must survive the second runners run",
        )


class ConductCmd(unittest.TestCase):
    """Tests for `danza conduct <root> [--poll N] [--max-ticks N]`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _make_headless_registry(self):
        """Write a valid runners.json with session_host='headless' so no tmux
        is needed — the HeadlessHost is a plain subprocess seam."""
        (self.root / ".danza" / "runtime").mkdir(parents=True, exist_ok=True)
        config = runners_mod.default_config({"claude": True, "codex": False})
        config["session_host"] = "headless"
        config["runners"]["claude"]["auth"] = "ok"
        runners_mod.save_runners(self.root, config)

    def _init_state(self):
        """Bootstrap team-state.json so the Conductor can load() it."""
        StateManager(
            str(self.root / ".danza" / "runtime" / "team-state.json")
        ).init()
        config = runners_mod.load_runners(self.root)
        seats = {seat: "claude" for seat in routing.SEATS}
        seats["conductor"] = routing.BUILTIN_CONDUCTOR
        routing.save_routing(self.root, {
            "version": routing.SCHEMA_VERSION, "features_per_turn": 2,
            "lineup": ["claude"], "seats": seats,
        }, config)
        unit = {
            "id": "71-A", "feature_id": 71,
            "description": "implement the unit", "kind": "backend",
            "size_est": 10, "writes": ["src/x.py"],
            "verification": {"kind": "automated_test", "detail": "exit 0"},
        }
        data = {"spec_ref": "features#1", "tasks": [unit],
                "order": ["71-A"],
                "execution": execution.initial_execution(["71-A"]),
                "calibration": []}
        (self.root / PLAN_JSON_RELPATH).write_text(json.dumps(data),
                                                   encoding="utf-8")

    def test_no_registry_exits_2(self):
        """`conduct` with no runners.json must exit 2 and emit a helpful
        stderr message (RunnerError from load_runners mentions /models)."""
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["conduct", str(self.root)])
        self.assertEqual(rc, 2)
        self.assertTrue(err.getvalue().strip(), "stderr must be non-empty")

    def test_pidfile_conflict_exits_2(self):
        """A pre-existing live pidfile raises ConductorError inside run();
        the CLI must catch it, emit one stderr line, and exit 2."""
        self._make_headless_registry()
        self._init_state()
        # Occupy the pidfile with our own PID (always alive in this process)
        acquire_pidfile(self.root, pid=os.getpid(), alive=lambda p: True)
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["conduct", str(self.root)])
        self.assertEqual(rc, 2)
        self.assertTrue(err.getvalue().strip(), "stderr must be non-empty")

    def test_host_error_exits_2_one_line(self):
        """HostError from ignite (e.g. the boss binary vanished after the
        registry was written) must exit 2 with one stderr line, not a
        traceback (review finding, W1-P4 final)."""
        self._make_headless_registry()
        config = runners_mod.load_runners(self.root)
        config["runners"]["claude"]["headless"] = [
            "/nonexistent-danza-boss-xyz", "-p"]
        runners_mod.save_runners(self.root, config)
        self._init_state()  # status ready -> first tick ignites
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["conduct", str(self.root), "--max-ticks", "1"])
        self.assertEqual(rc, 2)
        self.assertIn("ignite", err.getvalue())
        pidfile = self.root / conductor_mod.PIDFILE_RELPATH
        self.assertFalse(pidfile.exists(), "pidfile released on HostError")

    def test_max_ticks_0_exits_0_and_releases_pidfile(self):
        """Zero-tick run: the loop body never executes, action stays WAIT
        (non-terminal), exit 0; the finally block in run() must release the
        pidfile even on this minimal path."""
        self._make_headless_registry()
        self._init_state()
        rc = main(["conduct", str(self.root), "--max-ticks", "0"])
        self.assertEqual(rc, 0)
        pidfile = self.root / conductor_mod.PIDFILE_RELPATH
        self.assertFalse(pidfile.exists(), "pidfile must be released after run()")


class UnitCmd(unittest.TestCase):
    """The installed CLI is the production caller for Task 5 mutations."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        runtime = self.root / ".danza" / "runtime"
        runtime.mkdir(parents=True)
        self.manager = StateManager(str(runtime / "team-state.json"))
        self.manager.init(current_boss="claude")

    def write_plan(self, *, verify="exit 0", flags=()):
        unit = {
            "id": "71-A", "feature_id": 71,
            "description": "implement the unit", "kind": "backend",
            "size_est": 10, "writes": ["src/x.py"],
            "flags": list(flags),
            "verification": {"kind": "automated_test", "detail": verify},
        }
        data = {
            "spec_ref": "features#1", "tasks": [unit], "order": ["71-A"],
            "execution": execution.initial_execution(["71-A"]),
            "calibration": [],
        }
        (self.root / PLAN_JSON_RELPATH).write_text(json.dumps(data),
                                                   encoding="utf-8")

    def run_unit(self, *args):
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(["unit", *args])
        payload = json.loads(out.getvalue()) if out.getvalue().strip() else None
        return rc, payload, err.getvalue()

    def test_start_and_verify_success_call_the_real_lifecycle(self):
        self.write_plan()
        rc, started, _ = self.run_unit(
            "start", str(self.root), "71-A", "--actor", "claude")
        self.assertEqual(rc, 0)
        self.assertEqual(started["unit"]["status"], "in_progress")

        rc, verified, _ = self.run_unit(
            "verify", str(self.root), "71-A", "--actor", "claude")
        self.assertEqual(rc, 0)
        self.assertTrue(verified["verification"]["passed"])
        self.assertEqual(verified["unit"]["status"], "completed")
        self.assertEqual(verified["conclusion"], "no_work")

    def test_verify_failure_returns_one_and_does_not_count(self):
        self.write_plan(verify="exit 9")
        self.run_unit("start", str(self.root), "71-A",
                      "--actor", "claude")

        rc, verified, _ = self.run_unit(
            "verify", str(self.root), "71-A", "--actor", "claude")

        self.assertEqual(rc, 1)
        self.assertFalse(verified["verification"]["passed"])
        self.assertEqual(self.manager.load().features_completed_this_turn, 0)

    def test_block_and_conclude_have_explicit_results(self):
        self.write_plan()
        self.run_unit("start", str(self.root), "71-A",
                      "--actor", "claude")

        rc, blocked, _ = self.run_unit(
            "block", str(self.root), "71-A", "--actor", "claude",
            "--reason", "missing API key")

        self.assertEqual(rc, 0)
        self.assertEqual(blocked["conclusion"], "blocked")
        rc, concluded, _ = self.run_unit(
            "conclude", str(self.root), "--actor", "claude")
        self.assertEqual(rc, 0)
        self.assertEqual(concluded["conclusion"], "blocked")

    def test_bad_unit_usage_exits_two_without_traceback(self):
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["unit", "verify", str(self.root)])
        self.assertEqual(rc, 2)
        self.assertNotIn("Traceback", err.getvalue())


if __name__ == "__main__":
    unittest.main()
