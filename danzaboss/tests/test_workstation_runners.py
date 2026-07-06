"""Tests for danzaboss.workstation.runners — runner registry.

Covers all 8 contract test cases from the W1-P4 T1 spec.
"""
import _bootstrap  # noqa
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from danzaboss.workstation.runners import (
    KNOWN_RUNNERS,
    RUNNERS_RELPATH,
    SCHEMA_VERSION,
    RunnerError,
    boss_runner,
    default_config,
    detect_runners,
    headless_argv,
    interactive_argv,
    load_runners,
    save_runners,
    validate_config,
)


class TestDetectRunners(unittest.TestCase):
    """Test 1 — detect_runners with injectable which."""

    def test_detect_only_claude(self):
        def stub_which(binary):
            return "/usr/bin/claude" if binary == "claude" else None

        result = detect_runners(which=stub_which)
        self.assertEqual(result, {"claude": True, "codex": False})

    def test_detect_none(self):
        result = detect_runners(which=lambda _: None)
        self.assertEqual(result, {"claude": False, "codex": False})

    def test_detect_all(self):
        result = detect_runners(which=lambda _: "/usr/bin/x")
        self.assertEqual(result, {"claude": True, "codex": True})


class TestDefaultConfig(unittest.TestCase):
    """Test 2 & 3 — default_config shape and boss selection."""

    def test_boss_is_first_detected(self):
        detected = {"claude": True, "codex": False}
        cfg = default_config(detected)
        self.assertEqual(cfg["boss"], "claude")
        self.assertEqual(cfg["session_host"], "tmux")
        self.assertIsNone(cfg["permission_mode"])
        self.assertIn("claude", cfg["runners"])
        self.assertIn("codex", cfg["runners"])
        self.assertTrue(cfg["runners"]["claude"]["detected"])
        self.assertFalse(cfg["runners"]["codex"]["detected"])

    def test_validate_accepts_default(self):
        detected = {"claude": True, "codex": False}
        cfg = default_config(detected)
        result = validate_config(cfg)
        self.assertEqual(result, cfg)

    def test_boss_none_when_nothing_detected(self):
        """Test 3 — nothing detected → boss None, boss_runner raises."""
        cfg = default_config({"claude": False, "codex": False})
        self.assertIsNone(cfg["boss"])
        with self.assertRaises(RunnerError):
            boss_runner(cfg)

    def test_version_in_default(self):
        cfg = default_config({"claude": True, "codex": False})
        self.assertEqual(cfg["version"], SCHEMA_VERSION)

    def test_deep_copy_isolation(self):
        """Mutating a runner entry returned by default_config must not
        corrupt KNOWN_RUNNERS."""
        cfg = default_config({"claude": True, "codex": False})
        cfg["runners"]["claude"]["injected"] = True
        self.assertNotIn("injected", KNOWN_RUNNERS["claude"])


class TestSaveLoadRoundTrip(unittest.TestCase):
    """Test 4 — save → load round-trip."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="danza-runners-test-")

    def test_round_trip(self):
        cfg = default_config({"claude": True, "codex": False})
        returned_path = save_runners(self.root, cfg)
        expected_path = Path(self.root) / RUNNERS_RELPATH
        self.assertEqual(returned_path, expected_path)
        self.assertTrue(expected_path.exists())

        loaded = load_runners(self.root)
        self.assertEqual(loaded, cfg)

    def test_no_tmp_files_left(self):
        """Atomic write must not leave any *.tmp files."""
        cfg = default_config({"claude": True, "codex": False})
        save_runners(self.root, cfg)
        tmp_files = list(Path(self.root).rglob("*.tmp"))
        self.assertEqual(tmp_files, [])

    def test_lands_at_runners_relpath(self):
        cfg = default_config({"claude": True, "codex": False})
        save_runners(self.root, cfg)
        expected = Path(self.root) / RUNNERS_RELPATH
        self.assertTrue(expected.exists())


class TestLoadRunnersMissingFile(unittest.TestCase):
    """Test 5 — load_runners on empty root raises RunnerError mentioning /models."""

    def test_missing_file_error(self):
        with tempfile.TemporaryDirectory(prefix="danza-runners-test-") as root:
            with self.assertRaises(RunnerError) as ctx:
                load_runners(root)
            self.assertIn("/models", str(ctx.exception))

    def test_invalid_json_raises(self):
        with tempfile.TemporaryDirectory(prefix="danza-runners-test-") as root:
            target = Path(root) / RUNNERS_RELPATH
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("NOT JSON", encoding="utf-8")
            with self.assertRaises(RunnerError):
                load_runners(root)


class TestValidateConfig(unittest.TestCase):
    """Test 6 — validate_config rejects bad configs."""

    def _valid(self):
        return default_config({"claude": True, "codex": False})

    def test_rejects_non_dict(self):
        with self.assertRaises(RunnerError):
            validate_config("not a dict")

    def test_rejects_wrong_version(self):
        cfg = self._valid()
        cfg["version"] = 999
        with self.assertRaises(RunnerError):
            validate_config(cfg)

    def test_rejects_missing_version(self):
        cfg = self._valid()
        del cfg["version"]
        with self.assertRaises(RunnerError):
            validate_config(cfg)

    def test_rejects_boss_not_in_runners(self):
        cfg = self._valid()
        cfg["boss"] = "nonexistent"
        with self.assertRaises(RunnerError):
            validate_config(cfg)

    def test_rejects_bad_session_host(self):
        cfg = self._valid()
        cfg["session_host"] = "screen"
        with self.assertRaises(RunnerError):
            validate_config(cfg)

    def test_rejects_interactive_as_string(self):
        """Runner entry whose interactive is a string, not a list."""
        cfg = self._valid()
        cfg["runners"]["claude"]["interactive"] = "claude"
        with self.assertRaises(RunnerError):
            validate_config(cfg)

    def test_rejects_runners_not_dict(self):
        cfg = self._valid()
        cfg["runners"] = ["claude"]
        with self.assertRaises(RunnerError):
            validate_config(cfg)

    def test_rejects_runner_missing_kind(self):
        cfg = self._valid()
        del cfg["runners"]["claude"]["kind"]
        with self.assertRaises(RunnerError):
            validate_config(cfg)

    def test_rejects_headless_list_of_nonstrings(self):
        cfg = self._valid()
        cfg["runners"]["claude"]["headless"] = [1, 2, 3]
        with self.assertRaises(RunnerError):
            validate_config(cfg)

    def test_accepts_boss_none(self):
        cfg = self._valid()
        cfg["boss"] = None
        result = validate_config(cfg)
        self.assertIsNone(result["boss"])


class TestArgvHelpers(unittest.TestCase):
    """Test 7 & 8 — headless_argv, interactive_argv, mutation isolation."""

    def test_headless_argv_claude(self):
        cfg = default_config({"claude": True, "codex": False})
        argv = headless_argv(cfg)
        self.assertEqual(argv, ["claude", "-p", "--output-format", "json"])

    def test_interactive_argv_claude(self):
        cfg = default_config({"claude": True, "codex": False})
        argv = interactive_argv(cfg)
        self.assertEqual(argv, ["claude"])

    def test_headless_argv_codex_raises(self):
        """codex has empty headless list → headless_argv must raise RunnerError."""
        cfg = default_config({"claude": False, "codex": True})
        # Force boss to codex (nothing else detected first)
        self.assertEqual(cfg["boss"], "codex")
        with self.assertRaises(RunnerError):
            headless_argv(cfg)

    def test_interactive_argv_codex(self):
        cfg = default_config({"claude": False, "codex": True})
        argv = interactive_argv(cfg)
        self.assertEqual(argv, ["codex"])

    def test_mutation_isolation_headless(self):
        """Mutating the returned list must not mutate the stored config."""
        cfg = default_config({"claude": True, "codex": False})
        argv = headless_argv(cfg)
        original = list(argv)
        argv.append("POISONED")
        self.assertEqual(headless_argv(cfg), original)

    def test_mutation_isolation_interactive(self):
        """Same guarantee for interactive_argv."""
        cfg = default_config({"claude": True, "codex": False})
        argv = interactive_argv(cfg)
        argv.append("POISONED")
        self.assertEqual(interactive_argv(cfg), ["claude"])


class TestKnownRunners(unittest.TestCase):
    """Sanity-checks on the KNOWN_RUNNERS constant."""

    def test_claude_entry_present(self):
        self.assertIn("claude", KNOWN_RUNNERS)
        c = KNOWN_RUNNERS["claude"]
        self.assertEqual(c["binary"], "claude")
        self.assertEqual(c["interactive"], ["claude"])
        self.assertEqual(c["headless"], ["claude", "-p", "--output-format", "json"])

    def test_codex_entry_present(self):
        self.assertIn("codex", KNOWN_RUNNERS)
        c = KNOWN_RUNNERS["codex"]
        self.assertEqual(c["binary"], "codex")
        self.assertEqual(c["interactive"], ["codex"])
        self.assertEqual(c["headless"], [])

    def test_schema_version_is_1(self):
        self.assertEqual(SCHEMA_VERSION, 1)


if __name__ == "__main__":
    unittest.main()
