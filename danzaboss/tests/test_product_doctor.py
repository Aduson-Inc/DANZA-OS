"""Phase-1 T6 doctor: env + activation health checks. Injected `which` and
`env` keep every test hermetic - no real runner binaries or global profile
state leak in.
"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.product.doctor import run_doctor
from danzaboss.product.scaffold import scaffold, SCAFFOLD_VERSION_RELPATH

_NO_ENV = {}          # blocks DANZABOSS_PROFILE leaking from the real env


def _which_none(name):
    return None


def _which_claude(name):
    return "/usr/bin/claude" if name == "claude" else None


def _check(report, name):
    return next(c for c in report.checks if c.name == name)


class DoctorFreshDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_non_git_dir_fails_git_check(self):
        rep = run_doctor(self.root, which=_which_none, env=_NO_ENV)
        self.assertFalse(_check(rep, "git_repo").passed)
        self.assertFalse(rep.ok)

    def test_unscaffolded_source_tree_passes_scaffold_check(self):
        rep = run_doctor(self.root, which=_which_none, env=_NO_ENV)
        self.assertTrue(_check(rep, "scaffold").passed)


class DoctorScaffoldedRepo(unittest.TestCase):
    """The `danza init` acceptance state: scaffolded + git, not yet activated."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / ".git").mkdir()          # doctor checks presence, not validity
        scaffold(self.root)

    def test_green_end_to_end(self):
        rep = run_doctor(self.root, which=_which_claude, env=_NO_ENV)
        self.assertTrue(rep.ok, json.dumps(rep.to_dict(), indent=2))

    def test_runners_summary_is_informational(self):
        rep = run_doctor(self.root, which=_which_none, env=_NO_ENV)
        runners = _check(rep, "runners")
        self.assertTrue(runners.passed)
        self.assertIn("claude: not found", runners.detail)

    def test_missing_scaffold_file_fails_integrity(self):
        (self.root / ".danza" / "handoff.md").unlink()
        rep = run_doctor(self.root, which=_which_claude, env=_NO_ENV)
        check = _check(rep, "scaffold")
        self.assertFalse(check.passed)
        self.assertIn("handoff.md", check.detail)

    def test_corrupt_manifest_fails_closed(self):
        (self.root / SCAFFOLD_VERSION_RELPATH).write_text("{not json",
                                                          encoding="utf-8")
        rep = run_doctor(self.root, which=_which_claude, env=_NO_ENV)
        self.assertFalse(_check(rep, "scaffold").passed)


class DoctorCortexD9(unittest.TestCase):
    """CORTEX is load-bearing: dormant-in-activated-repo and unwritable-store
    are failures, not warnings."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / ".git").mkdir()
        scaffold(self.root)
        runtime = self.root / ".danza" / "runtime"
        (runtime / "team-state.json").write_text("{}", encoding="utf-8")

    def test_activated_repo_with_runtime_profile_probes_store_writable(self):
        rep = run_doctor(self.root, which=_which_claude, env=_NO_ENV)
        cortex = _check(rep, "cortex")
        self.assertTrue(cortex.passed, cortex.detail)

    def test_dormant_profile_in_activated_repo_fails(self):
        rep = run_doctor(self.root, which=_which_claude,
                         env={"DANZABOSS_PROFILE": "OS_DEV"})
        cortex = _check(rep, "cortex")
        self.assertFalse(cortex.passed)
        self.assertIn("dormant", cortex.detail)

    def test_unwritable_store_fails(self):
        # a FILE where the cortex dir must go makes mkdir/connect raise
        (self.root / ".danza" / "cortex").write_text("", encoding="utf-8")
        rep = run_doctor(self.root, which=_which_claude, env=_NO_ENV)
        self.assertFalse(_check(rep, "cortex").passed)
