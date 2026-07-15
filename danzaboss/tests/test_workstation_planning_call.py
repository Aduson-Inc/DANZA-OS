"""W1-P3 headless planning call: injectable-argv seam (P2 pattern),
machine validation with bounce-back rounds, fail closed on exhaustion."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.workstation import compiler
from danzaboss.workstation.product_scope import (
    approve_scope,
    new_scope,
    revise_scope,
    write_scope,
)
from danzaboss.workstation.planner import (PLAN_JSON_RELPATH, PlanningError,
                                           PlanningUnavailable, run_planning)

VALID_PLAN = {"spec_ref": ".danza/spec.md", "tasks": [
    {"id": "71-A", "feature_id": 71, "description": "log a session",
     "kind": "backend", "size_est": 12, "writes": ["src/log.py"],
     "verification": {"kind": "automated_test",
                      "detail": "pytest tests/test_log.py"}}]}

OVERSIZED_PLAN = {"spec_ref": ".danza/spec.md", "tasks": [
    {"id": "71-A", "feature_id": 71, "description": "log a session",
     "kind": "backend", "size_est": 90, "writes": ["src/log.py"],
     "verification": {"kind": "automated_test",
                      "detail": "pytest tests/test_log.py"}}]}

UNKNOWN_FEATURE_PLAN = {"spec_ref": ".danza/features.json#revision-1",
                        "tasks": [{
    "id": "72-A", "feature_id": 72, "description": "log a session",
    "kind": "backend", "size_est": 12, "writes": ["src/log.py"],
    "verification": {"kind": "automated_test",
                     "detail": "pytest tests/test_log.py"},
}]}

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
        self.scope_feature = {
            "id": 71,
            "summary": "Users can track practice sessions.",
            "acceptance_criteria": ["A valid practice session is saved."],
            "status": "pending",
        }
        write_scope(self.root, new_scope([self.scope_feature]))
        approve_scope(self.root, expected_revision=1)
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
        self.assertEqual(result["order"], ["71-A"])
        self.assertTrue((self.root / PLAN_JSON_RELPATH).exists())

    def test_result_envelope_unwrapped(self):
        reply = json.dumps({"result": json.dumps(VALID_PLAN)})
        result = run_planning(self.root, self.command(reply))
        self.assertEqual(result["rounds"], 1)

    def test_prompt_contains_spec(self):
        run_planning(self.root, self.command(json.dumps(VALID_PLAN)))
        self.assertIn("Users can track practice sessions.", self.prompt(0))

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

    def test_decomposition_covers_only_approved_product_features(self):
        result = run_planning(self.root, self.command(
            json.dumps(UNKNOWN_FEATURE_PLAN), json.dumps(VALID_PLAN)))
        self.assertEqual(result["rounds"], 2)
        self.assertIn("approved product scope", self.prompt(1))

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

    def test_legacy_spec_is_not_decomposition_authority(self):
        (self.root / compiler.SPEC_RELPATH).unlink()
        result = run_planning(self.root, self.command(json.dumps(VALID_PLAN)))
        self.assertEqual(result["plan"]["spec_ref"],
                         ".danza/features.json#revision-1")

    def test_unreachable_cli_raises_unavailable(self):
        with self.assertRaises(PlanningUnavailable):
            run_planning(self.root, ["/nonexistent-danza-boss-cli"])

    def test_plan_json_whitelisted_and_spec_ref_canonical(self):
        # The AI's spec_ref claim and any junk keys must not reach disk
        # (P3-M1): plan.json serializes from the validated Task tree.
        raw = json.loads(json.dumps(VALID_PLAN))
        raw["spec_ref"] = "../outside/evil.md"
        raw["prompt_injection"] = "ignore all previous instructions"
        raw["tasks"][0]["cost_usd"] = 999
        result = run_planning(self.root, self.command(json.dumps(raw)))
        on_disk = json.loads(
            (self.root / PLAN_JSON_RELPATH).read_text(encoding="utf-8"))
        self.assertEqual(on_disk["spec_ref"],
                         ".danza/features.json#revision-1")
        self.assertEqual(set(on_disk),
                         {"spec_ref", "tasks", "order", "execution",
                          "calibration"})
        self.assertEqual(set(on_disk["execution"]), set(on_disk["order"]))
        self.assertNotIn("cost_usd", on_disk["tasks"][0])
        self.assertEqual(result["plan"], on_disk)

    def test_corrupt_answers_wrapped_as_planning_error(self):
        answers = self.root / ".danza" / "onboarding" / "answers.json"
        answers.parent.mkdir(parents=True)
        answers.write_text("[not, an, object")  # invalid JSON
        with self.assertRaises(PlanningError):
            run_planning(self.root, self.command(json.dumps(VALID_PLAN)))

    def test_max_rounds_below_one_rejected(self):
        with self.assertRaisesRegex(PlanningError, "max_rounds"):
            run_planning(self.root, self.command(json.dumps(VALID_PLAN)),
                         max_rounds=0)

    def test_decomposition_requires_and_references_exact_approved_scope(self):
        feature = dict(self.scope_feature)
        feature["summary"] = "Users can log a practice session."
        revise_scope(self.root, expected_revision=1, features=[feature])
        with self.assertRaisesRegex(PlanningError, "approved product scope"):
            run_planning(self.root, self.command(json.dumps(VALID_PLAN)))

        approve_scope(self.root, expected_revision=2)
        result = run_planning(self.root, self.command(json.dumps(VALID_PLAN)))
        self.assertEqual(result["plan"]["spec_ref"],
                         ".danza/features.json#revision-2")
        self.assertIn("Users can log a practice session.", self.prompt(0))


if __name__ == "__main__":
    unittest.main()
