"""Tests for the Tier-3 LLM-worker ExtractorPort adapter (C5).

The adapter is OFF by default, fails open on every error class, and can
never mint confidence above llm_inferred.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from danzaboss.cortex.extract import (DeterministicExtractor,
                                      LLMWorkerExtractor,
                                      configured_extractor)

# A worker that echoes one draft observation for any input.
_FAKE_WORKER = (
    "python3 -c \"import json,sys; sys.stdin.read(); "
    "print(json.dumps([{'title': 't3 draft', 'summary': 's', "
    "'type': 'impl_detail', 'confidence': 99}]))\"")

_EVENTS = [{"id": 1, "tool": "Bash", "command": "git commit -m 'x'",
            "file_path": "", "outcome": ""}]


class TestConfiguredExtractor(unittest.TestCase):
    def test_off_by_default(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DANZABOSS_TIER3_CMD", None)
            self.assertIsNone(configured_extractor(root))

    def test_env_var_enables(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.dict(os.environ, {"DANZABOSS_TIER3_CMD": "worker"}):
            ext = configured_extractor(root)
            self.assertIsInstance(ext, LLMWorkerExtractor)
            self.assertEqual(ext.command, "worker")

    def test_config_file_enables(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DANZABOSS_TIER3_CMD", None)
            cfg_dir = os.path.join(root, ".danza", "cortex")
            os.makedirs(cfg_dir)
            with open(os.path.join(cfg_dir, "tier3.json"), "w") as fh:
                json.dump({"command": "my-worker --flag"}, fh)
            ext = configured_extractor(root)
            self.assertEqual(ext.command, "my-worker --flag")


class TestLLMWorkerExtractor(unittest.TestCase):
    def test_extracts_and_clamps_confidence(self):
        drafts = LLMWorkerExtractor(_FAKE_WORKER).extract(_EVENTS, "proj")
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].title, "t3 draft")
        self.assertEqual(drafts[0].project, "proj")
        self.assertLessEqual(drafts[0].confidence, 60)  # llm_inferred cap

    def test_broken_command_fails_open(self):
        self.assertEqual(
            LLMWorkerExtractor("no-such-binary-xyz").extract(_EVENTS, "p"), [])

    def test_garbage_output_fails_open(self):
        cmd = "python3 -c \"print('not json')\""
        self.assertEqual(LLMWorkerExtractor(cmd).extract(_EVENTS, "p"), [])

    def test_malformed_items_skipped(self):
        cmd = ("python3 -c \"import json; print(json.dumps("
               "[{'bogus_field_only': 1}, 'not-a-dict']))\"")
        self.assertEqual(LLMWorkerExtractor(cmd).extract(_EVENTS, "p"), [])


class TestDeterministicExtractorPort(unittest.TestCase):
    def test_tier2_floor_behind_the_port(self):
        drafts = DeterministicExtractor().extract(_EVENTS, "proj")
        self.assertEqual(len(drafts), 1)  # commit rule fires
        self.assertEqual(drafts[0].project, "proj")


if __name__ == "__main__":
    unittest.main()
