"""W1-P3 headless planning call: injectable-argv seam (P2 pattern),
machine validation with bounce-back rounds, fail closed on exhaustion."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.workstation import compiler
from danzaboss.workstation.planner import (PLAN_JSON_RELPATH, PlanningError,
                                           PlanningUnavailable, run_planning)

VALID_PLAN = {"spec_ref": ".danza/spec.md", "tasks": [
    {"id": "1", "description": "core area", "subtasks": [
        {"id": "1.1", "description": "log a session", "kind": "backend",
         "size_est": 25, "writes": ["src/log.py"],
         "verification": {"kind": "automated_test",
                          "detail": "pytest tests/test_log.py"}}]}]}

OVERSIZED_PLAN = {"spec_ref": ".danza/spec.md", "tasks": [
    {"id": "1", "description": "core area", "subtasks": [
        {"id": "1.1", "description": "log a session", "kind": "backend",
         "size_est": 90, "writes": ["src/log.py"],
         "verification": {"kind": "automated_test",
                          "detail": "pytest tests/test_log.py"}}]}]}

# Stub boss CLI: replies from replies.json in call order, records each
# prompt so tests can assert on bounce-back content.
STUB = """\
import json, sys
from pathlib import Path
here = Path(__file__).parent
state = here / "calls.txt"
n = int(state.read_text()) if state.exists() else 0
state.write_text(str(n + 1))
(here / f"prompt{n}.txt").write_text(sys.argv[-1])
replies = json.loads((here / "replies.json").read_text())
print(replies[min(n, len(replies) - 1)])
"""


class PlanningCall(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        spec = self.root / compiler.SPEC_RELPATH
        spec.parent.mkdir(parents=True)
        spec.write_text("# Spec — DrumLog\n\n## 1. Intent\nTrack practice.\n")
        self.stub_dir = self.root / "stub"
        self.stub_dir.mkdir()
        self.stub = self.stub_dir / "stub.py"
        self.stub.write_text(STUB)

    def command(self, *replies):
        (self.stub_dir / "replies.json").write_text(json.dumps(list(replies)))
        return [sys.executable, str(self.stub)]

    def prompt(self, n):
        return (self.stub_dir / f"prompt{n}.txt").read_text()

    def test_valid_first_round(self):
        result = run_planning(self.root, self.command(json.dumps(VALID_PLAN)))
        self.assertEqual(result["rounds"], 1)
        self.assertEqual(result["order"], ["1.1"])
        self.assertTrue((self.root / PLAN_JSON_RELPATH).exists())

    def test_result_envelope_unwrapped(self):
        reply = json.dumps({"result": json.dumps(VALID_PLAN)})
        result = run_planning(self.root, self.command(reply))
        self.assertEqual(result["rounds"], 1)

    def test_prompt_contains_spec(self):
        run_planning(self.root, self.command(json.dumps(VALID_PLAN)))
        self.assertIn("Track practice.", self.prompt(0))

    def test_stack_testing_defaults_in_prompt(self):
        answers = self.root / ".danza" / "onboarding" / "answers.json"
        answers.parent.mkdir(parents=True)
        answers.write_text(json.dumps(
            {"answers": {"stack_template": "saas-ts"}, "steps": {}}))
        run_planning(self.root, self.command(json.dumps(VALID_PLAN)))
        self.assertIn("vitest", self.prompt(0))

    def test_violations_bounced_back(self):
        result = run_planning(self.root, self.command(
            json.dumps(OVERSIZED_PLAN), json.dumps(VALID_PLAN)))
        self.assertEqual(result["rounds"], 2)
        self.assertIn("size_est", self.prompt(1))
        self.assertIn("REJECTED", self.prompt(1))

    def test_garbage_reply_costs_a_round(self):
        result = run_planning(self.root, self.command(
            "not json at all", json.dumps(VALID_PLAN)))
        self.assertEqual(result["rounds"], 2)

    def test_exhaustion_fails_closed(self):
        with self.assertRaises(PlanningError) as ctx:
            run_planning(self.root, self.command(json.dumps(OVERSIZED_PLAN)),
                         max_rounds=2)
        self.assertIn("2 rounds", str(ctx.exception))
        self.assertFalse((self.root / PLAN_JSON_RELPATH).exists())

    def test_missing_spec_fails_closed(self):
        (self.root / compiler.SPEC_RELPATH).unlink()
        with self.assertRaises(PlanningError):
            run_planning(self.root, self.command(json.dumps(VALID_PLAN)))

    def test_unreachable_cli_raises_unavailable(self):
        with self.assertRaises(PlanningUnavailable):
            run_planning(self.root, ["/nonexistent-danza-boss-cli"])


if __name__ == "__main__":
    unittest.main()
