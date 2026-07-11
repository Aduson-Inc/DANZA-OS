"""Phase-1 T5 auto-resume hook (D8): a fresh session in an activated repo
with a real handoff gets a CONTINUE MODE context block; everything else
stays silent. The hook is read-only and fails open.
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.cli import main
from danzaboss.product.resume import session_start_context


class SessionStartContext(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _write_handoff(self, text):
        d = self.root / ".danza"
        d.mkdir(exist_ok=True)
        (d / "handoff.md").write_text(text, encoding="utf-8")

    def test_no_danza_dir_is_silent(self):
        self.assertIsNone(session_start_context(self.root))

    def test_bootstrap_handoff_is_silent(self):
        self._write_handoff("# Handoff\n\nNo handoff yet.\n")
        self.assertIsNone(session_start_context(self.root))

    def test_blank_handoff_is_silent(self):
        self._write_handoff("   \n\n")
        self.assertIsNone(session_start_context(self.root))

    def test_real_handoff_emits_continue_block(self):
        self._write_handoff("# Handoff\n\nTurn 4: claude -> codex. "
                            "Features 7+8 next.\n")
        block = session_start_context(self.root)
        self.assertIsNotNone(block)
        self.assertIn("CONTINUE MODE", block)
        self.assertIn("Who's the Boss?", block)
        self.assertIn(".danza/handoff.md", block)


class SessionStartCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self._old_cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self._old_cwd)

    def test_activated_repo_prints_session_start_json(self):
        d = self.root / ".danza"
        d.mkdir()
        (d / "handoff.md").write_text("# Handoff\n\nTurn 2: resume.\n",
                                      encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            rc = main(["hook", "session-start"])
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        hso = payload["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "SessionStart")
        self.assertIn("CONTINUE MODE", hso["additionalContext"])

    def test_unactivated_repo_prints_nothing_and_exits_zero(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = main(["hook", "session-start"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.getvalue(), "")
