"""Checkpoint runner tests: AI without AI (design spec section 8).

The boss CLI is an injectable argv prefix; every test substitutes a
Python stub script, so the suite proves parse/retry/degraded behavior
with zero network and zero real CLI.
"""
import _bootstrap  # noqa: F401
import json
import sys
import tempfile
import unittest
from pathlib import Path

from danzaboss.workstation import checkpoints

VALID_VERDICT = {
    "summary": "Building a dog-walking SaaS for urban owners.",
    "concerns": ["no pricing model stated"],
    "follow_up_questions": ["Is this mobile-first?"],
    "recommendation": "Clarify pricing before the stack phase.",
    "verdict": "revise",
}


def make_stub(tmp: Path, body: str) -> list[str]:
    """A stub boss CLI: a python script receiving the prompt as argv[1]."""
    stub = tmp / "stub_boss.py"
    stub.write_text(body, encoding="utf-8")
    return [sys.executable, str(stub)]


class ParseTests(unittest.TestCase):
    def test_parse_verdict_accepts_bare_object(self):
        verdict = checkpoints.parse_verdict(json.dumps(VALID_VERDICT))
        self.assertEqual(verdict["verdict"], "revise")
        self.assertEqual(verdict["concerns"], ["no pricing model stated"])

    def test_parse_verdict_accepts_envelope_with_fenced_json(self):
        inner = "```json\n" + json.dumps(VALID_VERDICT) + "\n```"
        text = json.dumps({"type": "result", "result": inner})
        self.assertEqual(checkpoints.parse_verdict(text)["verdict"], "revise")

    def test_parse_verdict_rejects_missing_key(self):
        bad = {k: v for k, v in VALID_VERDICT.items() if k != "summary"}
        with self.assertRaises(checkpoints.CheckpointError):
            checkpoints.parse_verdict(json.dumps(bad))

    def test_parse_verdict_rejects_unknown_verdict_value(self):
        bad = dict(VALID_VERDICT, verdict="maybe")
        with self.assertRaises(checkpoints.CheckpointError):
            checkpoints.parse_verdict(json.dumps(bad))

    def test_parse_verdict_rejects_non_list_concerns(self):
        bad = dict(VALID_VERDICT, concerns="none")
        with self.assertRaises(checkpoints.CheckpointError):
            checkpoints.parse_verdict(json.dumps(bad))


class CallTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_call_returns_valid_verdict(self):
        command = make_stub(self.tmp, (
            "import json\n"
            f"print(json.dumps({VALID_VERDICT!r}))\n"))
        verdict = checkpoints.call_checkpoint(command, "review this")
        self.assertEqual(verdict["verdict"], "revise")

    def test_call_retries_once_on_garbage_then_succeeds(self):
        marker = self.tmp / "called_once"
        command = make_stub(self.tmp, (
            "import json, pathlib\n"
            f"marker = pathlib.Path({str(marker)!r})\n"
            "if marker.exists():\n"
            f"    print(json.dumps({VALID_VERDICT!r}))\n"
            "else:\n"
            "    marker.touch()\n"
            "    print('sorry, here are my thoughts...')\n"))
        verdict = checkpoints.call_checkpoint(command, "review this")
        self.assertEqual(verdict["summary"], VALID_VERDICT["summary"])
        self.assertTrue(marker.exists())

    def test_call_raises_checkpoint_error_on_garbage_twice(self):
        command = make_stub(self.tmp, "print('still not json')\n")
        with self.assertRaises(checkpoints.CheckpointError):
            checkpoints.call_checkpoint(command, "review this")

    def test_nonzero_exit_raises_unavailable(self):
        command = make_stub(self.tmp, "import sys; sys.exit(3)\n")
        with self.assertRaises(checkpoints.CheckpointUnavailable):
            checkpoints.call_checkpoint(command, "review this")

    def test_missing_binary_raises_unavailable(self):
        with self.assertRaises(checkpoints.CheckpointUnavailable):
            checkpoints.run_headless(
                [str(self.tmp / "no_such_binary")], "hi", timeout=5)

    def test_timeout_raises_unavailable(self):
        command = make_stub(self.tmp, "import time; time.sleep(5)\n")
        with self.assertRaises(checkpoints.CheckpointUnavailable):
            checkpoints.run_headless(command, "hi", timeout=1)


if __name__ == "__main__":
    unittest.main()
