"""Phase-1 T3 scaffold engine: idempotent copy of the bundled payload into a
target repo. Rules 34-35 encoded: a user-edited file is never overwritten;
re-runs report skipped, not re-created.
"""
import json
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
import danzaboss
from danzaboss.product.scaffold import (ScaffoldError, FileResult, scaffold,
                                        SCAFFOLD_VERSION_RELPATH)


class ScaffoldFreshTarget(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.results = scaffold(self.root)
        self.by_path = {r.path: r for r in self.results}

    def test_all_payload_files_created(self):
        payload = [r for r in self.results if r.path != "CLAUDE.md"]
        self.assertTrue(payload)
        for r in payload:
            self.assertEqual((r.status, r.reason), ("created", ""),
                             f"{r.path} not created on fresh target")

    def test_key_files_land_in_dotted_dirs(self):
        for rel in (".claude/rules/constitution.md",
                    ".claude/agents/tony-d-orchestrator.md",
                    ".claude/settings.json",
                    ".danza/handoff.md"):
            self.assertTrue((self.root / rel).is_file(), rel)

    def test_empty_runtime_dirs_created_with_gitkeep(self):
        self.assertTrue((self.root / ".danza" / "logs" / ".gitkeep").is_file())
        self.assertTrue((self.root / ".danza" / "runtime" / ".gitkeep").is_file())
        self.assertEqual(self.by_path[".danza/logs/.gitkeep"].status, "created")

    def test_manifest_stamped(self):
        manifest = json.loads(
            (self.root / SCAFFOLD_VERSION_RELPATH).read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], danzaboss.__version__)
        self.assertIn(".claude/rules/constitution.md", manifest["files"])
        for digest in manifest["files"].values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_results_are_deterministically_sorted(self):
        paths = [r.path for r in self.results if r.path != "CLAUDE.md"]
        self.assertEqual(paths, sorted(paths))


class ScaffoldRerun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        scaffold(self.root)

    def test_rerun_skips_everything_up_to_date(self):
        for r in scaffold(self.root):
            if r.path == "CLAUDE.md":
                continue
            self.assertEqual((r.status, r.reason), ("skipped", "up-to-date"),
                             f"{r.path} must skip on identical re-run")

    def test_user_edit_is_never_overwritten(self):
        handoff = self.root / ".danza" / "handoff.md"
        user_text = "# Handoff\n\nTurn 3: codex -> claude. Build features 5+6.\n"
        handoff.write_text(user_text, encoding="utf-8")
        results = {r.path: r for r in scaffold(self.root)}
        self.assertEqual(results[".danza/handoff.md"].status, "skipped")
        self.assertEqual(results[".danza/handoff.md"].reason, "user-modified")
        self.assertEqual(handoff.read_text(encoding="utf-8"), user_text,
                         "Rule 35 violation: user edit was clobbered")


class ScaffoldErrors(unittest.TestCase):
    def test_missing_target_raises(self):
        with self.assertRaises(ScaffoldError):
            scaffold("/nonexistent/definitely/not/a/dir")

    def test_target_is_file_raises(self):
        with tempfile.NamedTemporaryFile() as fh:
            with self.assertRaises(ScaffoldError):
                scaffold(fh.name)
