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
                                        SCAFFOLD_VERSION_RELPATH,
                                        CLAUDE_MD_BEGIN, CLAUDE_MD_END)


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


class ClaudeMdManagedBlock(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.claude_md = self.root / "CLAUDE.md"

    def _result(self):
        return {r.path: r for r in scaffold(self.root)}["CLAUDE.md"]

    def test_absent_file_is_created_with_block(self):
        res = self._result()
        self.assertEqual(res.status, "created")
        text = self.claude_md.read_text(encoding="utf-8")
        self.assertIn(CLAUDE_MD_BEGIN, text)
        self.assertIn(CLAUDE_MD_END, text)
        self.assertIn("Who's the Boss?", text)

    def test_existing_file_gets_block_appended_user_text_preserved(self):
        self.claude_md.write_text("# My App\n\nUser notes.\n", encoding="utf-8")
        res = self._result()
        self.assertEqual(res.status, "merged")
        text = self.claude_md.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# My App"),
                        "user content must stay first and intact")
        self.assertIn("User notes.", text)
        self.assertIn(CLAUDE_MD_BEGIN, text)

    def test_rerun_with_current_block_skips(self):
        scaffold(self.root)
        self.assertEqual((self._result().status, self._result().reason),
                         ("skipped", "up-to-date"))

    def test_stale_block_is_refreshed_in_place(self):
        scaffold(self.root)
        text = self.claude_md.read_text(encoding="utf-8")
        pre, rest = text.split(CLAUDE_MD_BEGIN, 1)
        _, post = rest.split(CLAUDE_MD_END, 1)
        stale = (pre + CLAUDE_MD_BEGIN + "\nold contents\n"
                 + CLAUDE_MD_END + post)
        self.claude_md.write_text("USER HEADER\n" + stale, encoding="utf-8")
        res = self._result()
        self.assertEqual(res.status, "merged")
        refreshed = self.claude_md.read_text(encoding="utf-8")
        self.assertTrue(refreshed.startswith("USER HEADER"))
        self.assertNotIn("old contents", refreshed)
        self.assertIn("Who's the Boss?", refreshed)
        self.assertEqual(refreshed.count(CLAUDE_MD_BEGIN), 1,
                         "block must be replaced, not duplicated")

    def test_corrupt_markers_fail_closed(self):
        self.claude_md.write_text(f"# App\n{CLAUDE_MD_BEGIN}\nno end marker\n",
                                  encoding="utf-8")
        with self.assertRaises(ScaffoldError):
            scaffold(self.root)

    def test_duplicated_block_fails_closed(self):
        scaffold(self.root)
        text = self.claude_md.read_text(encoding="utf-8")
        self.claude_md.write_text(text + "\n" + text, encoding="utf-8")
        with self.assertRaises(ScaffoldError):
            scaffold(self.root)
        self.assertEqual(self.claude_md.read_text(encoding="utf-8"),
                         text + "\n" + text,
                         "a mangled CLAUDE.md must be left untouched")


class ScaffoldErrors(unittest.TestCase):
    def test_missing_target_raises(self):
        with self.assertRaises(ScaffoldError):
            scaffold("/nonexistent/definitely/not/a/dir")

    def test_target_is_file_raises(self):
        with tempfile.NamedTemporaryFile() as fh:
            with self.assertRaises(ScaffoldError):
                scaffold(fh.name)
