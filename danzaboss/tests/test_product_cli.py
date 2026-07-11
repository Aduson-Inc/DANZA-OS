"""Phase-1 T7 CLI wiring: `danza init` and `danza doctor` through the real
dispatch path (cli.main in-process), stdout captured. `which` cannot be
injected through the CLI, so assertions avoid claims about which runners the
host has - same policy as test_workstation_cli.py.
"""
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.cli import main


class InitCmd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / ".git").mkdir()   # keeps the doctor tail green

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_init_scaffolds_reports_and_health_checks(self):
        rc, out, _ = self._run("init", str(self.root))
        self.assertEqual(rc, 0, out)
        self.assertIn("created", out)
        self.assertIn(".claude/rules/constitution.md", out)
        self.assertIn("[PASS] scaffold", out)
        self.assertIn("Next steps", out)
        self.assertIn("Who's the Boss?", out)
        self.assertTrue((self.root / ".danza" / "handoff.md").is_file())

    def test_rerun_reports_all_skipped(self):
        self._run("init", str(self.root))
        rc, out, _ = self._run("init", str(self.root))
        self.assertEqual(rc, 0)
        file_lines = [l for l in out.splitlines()
                      if l.startswith(("created", "merged", "skipped"))]
        self.assertTrue(file_lines, "no file-result lines printed")
        self.assertTrue(all(l.startswith("skipped") for l in file_lines),
                        f"second init must create/merge nothing:\n{out}")
        self.assertIn("up-to-date", out)

    def test_bad_target_exits_2(self):
        rc, _, err = self._run("init", "/nonexistent/nope")
        self.assertEqual(rc, 2)
        self.assertIn("not a directory", err)


class DoctorCmd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _run(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = main(list(argv))
        return rc, out.getvalue()

    def test_red_on_non_git_dir(self):
        rc, out = self._run("doctor", str(self.root))
        self.assertEqual(rc, 1)
        self.assertIn("[FAIL] git_repo", out)

    def test_green_on_scaffolded_git_repo(self):
        (self.root / ".git").mkdir()
        main(["init", str(self.root)])
        rc, out = self._run("doctor", str(self.root))
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] python_version", out)
        self.assertIn("[PASS] cortex", out)
        self.assertIn("doctor: green", out)


class UsageLine(unittest.TestCase):
    def test_unknown_command_usage_mentions_init_and_doctor(self):
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["bogus"])
        self.assertEqual(rc, 2)
        self.assertIn("init", err.getvalue())
        self.assertIn("doctor", err.getvalue())
