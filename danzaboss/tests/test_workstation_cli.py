"""W1-P4 T5 CLI wiring: `danza runners` and `danza conduct` subcommands.

Invokes cli.main() in-process so the full dispatch path is exercised.
All I/O is captured via redirect_stdout/stderr; no network, no real tmux
or claude binary is needed.
"""
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.cli import main
from danzaboss.kernel.state import StateManager
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
        runners_mod.save_runners(self.root, config)

    def _init_state(self):
        """Bootstrap team-state.json so the Conductor can load() it."""
        StateManager(
            str(self.root / ".danza" / "runtime" / "team-state.json")
        ).init()

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


if __name__ == "__main__":
    unittest.main()
