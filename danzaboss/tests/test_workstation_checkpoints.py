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
from danzaboss.workstation.wizard import Wizard

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

    def test_parse_verdict_accepts_envelope_with_object_result(self):
        # P2-M1: some CLIs decode for us — result arrives as an object,
        # not a string. str() would yield Python repr and fail to parse.
        text = json.dumps({"type": "result", "result": VALID_VERDICT})
        self.assertEqual(checkpoints.parse_verdict(text)["verdict"], "revise")

    def test_parse_json_reply_passes_object_result_through(self):
        plan = {"spec_ref": "spec", "tasks": [{"id": "1", "description": "x"}]}
        text = json.dumps({"result": plan})
        self.assertEqual(checkpoints.parse_json_reply(text), plan)

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


P1_ANSWERS = {
    "project_name": "WalkWise",
    "concept_what": "Dog walking marketplace",
    "concept_who": "Urban dog owners",
    "concept_problem": "Finding trusted walkers is slow",
    "features_must": ["book a walk", "walker profiles"],
    "non_goals": ["pet supplies store"],
}


def make_app_wizard(root: Path) -> Wizard:
    """A target repo mid-onboarding: p0+p1 done, cp_concept is next."""
    wizard = Wizard(root)
    wizard.submit("p0", {"project_type": "saas"})
    wizard.submit("p1", P1_ANSWERS)
    return wizard


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_no_memory_dir_reads_empty(self):
        self.assertEqual(checkpoints.read_memory(self.tmp), "")

    def test_memory_files_concatenated_sorted_and_capped(self):
        mem = self.tmp / ".danza" / "memory"
        mem.mkdir(parents=True)
        (mem / "b-style.md").write_text("likes HTMX", encoding="utf-8")
        (mem / "a-user.md").write_text("no dark mode", encoding="utf-8")
        text = checkpoints.read_memory(self.tmp)
        self.assertLess(text.index("a-user.md"), text.index("b-style.md"))
        self.assertIn("no dark mode", text)
        self.assertLessEqual(
            len(checkpoints.read_memory(self.tmp, cap=10)), 10)

    def test_cap_cuts_at_file_boundaries(self):
        mem = self.tmp / ".danza" / "memory"
        mem.mkdir(parents=True)
        (mem / "a.md").write_text("alpha", encoding="utf-8")
        (mem / "b.md").write_text("bravo " * 40, encoding="utf-8")
        (mem / "c.md").write_text("charlie", encoding="utf-8")
        first = f"--- a.md ---\nalpha"
        text = checkpoints.read_memory(self.tmp, cap=len(first) + 60)
        # b.md does not fit: omitted whole, never truncated mid-file.
        self.assertIn("alpha", text)
        self.assertNotIn("bravo", text)
        # later files that still fit are kept — omission is per file.
        self.assertIn("charlie", text)

    def test_oversized_first_file_hard_capped(self):
        mem = self.tmp / ".danza" / "memory"
        mem.mkdir(parents=True)
        (mem / "a.md").write_text("x" * 500, encoding="utf-8")
        text = checkpoints.read_memory(self.tmp, cap=50)
        self.assertEqual(len(text), 50)
        self.assertIn("x", text)


class PromptTests(unittest.TestCase):
    def test_prompt_includes_answers_memory_and_contract(self):
        prompt = checkpoints.build_prompt(
            "cp_concept", {"concept_what": "walk dogs"},
            memory="prefers Python")
        self.assertIn("walk dogs", prompt)
        self.assertIn("prefers Python", prompt)
        self.assertIn('"verdict": "approve"|"revise"', prompt)

    def test_prompt_is_deterministic(self):
        args = ("cp_final", {"a": "1", "b": "2"})
        self.assertEqual(checkpoints.build_prompt(*args),
                         checkpoints.build_prompt(*args))

    def test_prompt_rejects_non_checkpoint_step(self):
        with self.assertRaises(checkpoints.CheckpointError):
            checkpoints.build_prompt("p1", {})

    def test_skipped_research_is_not_injected(self):
        prompt = checkpoints.build_prompt(
            "cp_concept", {}, research={"skipped": True, "summary": "x"})
        self.assertNotIn("Reality digest", prompt)


class RunCheckpointTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        make_app_wizard(self.tmp)

    def test_valid_run_records_pending_verdict(self):
        command = make_stub(self.tmp, (
            "import json\n"
            f"print(json.dumps({VALID_VERDICT!r}))\n"))
        verdict = checkpoints.run_checkpoint(self.tmp, "cp_concept", command)
        self.assertFalse(verdict["degraded"])
        wizard = Wizard(self.tmp)
        self.assertEqual(wizard.status("cp_concept"), "pending")
        self.assertEqual(wizard.result("cp_concept")["summary"],
                         VALID_VERDICT["summary"])

    def test_unreachable_cli_records_degraded_verdict(self):
        command = make_stub(self.tmp, "import sys; sys.exit(9)\n")
        verdict = checkpoints.run_checkpoint(self.tmp, "cp_concept", command)
        self.assertTrue(verdict["degraded"])
        self.assertEqual(verdict["verdict"], "revise")
        self.assertTrue(Wizard(self.tmp).result("cp_concept")["degraded"])

    def test_cp_stack_prompt_carries_template_grounding_and_bad_key_concern(self):
        wizard = Wizard(self.tmp)
        wizard.submit("p2", {"capabilities": ["accounts_auth", "payments"]})
        wizard.submit("p3", {"stack_choice": "template",
                             "stack_template": "no-such-template"})
        prompt_file = self.tmp / "prompt.txt"
        command = make_stub(self.tmp, (
            "import json, pathlib, sys\n"
            f"pathlib.Path({str(prompt_file)!r}).write_text(sys.argv[1])\n"
            f"print(json.dumps({VALID_VERDICT!r}))\n"))
        checkpoints.run_checkpoint(self.tmp, "cp_stack", command)
        prompt = prompt_file.read_text(encoding="utf-8")
        self.assertIn("Fitting stack templates:", prompt)
        self.assertIn("'no-such-template' is not in the template library",
                      prompt)

    def test_stale_reality_digest_is_not_injected_into_prompt(self):
        """Final-review I1: editing p1 stales r_reality; a subsequent
        checkpoint run must not ground itself in the stale digest."""
        digest = {"verdict": "novel", "summary": "wide open market",
                  "competitors": [], "differentiation": "first mover"}
        Wizard(self.tmp).record_result("r_reality", digest)
        prompt_file = self.tmp / "prompt.txt"
        command = make_stub(self.tmp, (
            "import json, pathlib, sys\n"
            f"pathlib.Path({str(prompt_file)!r}).write_text(sys.argv[1])\n"
            f"print(json.dumps({VALID_VERDICT!r}))\n"))
        checkpoints.run_checkpoint(self.tmp, "cp_concept", command)
        self.assertIn("wide open market",
                      prompt_file.read_text(encoding="utf-8"))
        wizard = Wizard(self.tmp)
        wizard.submit("p1", dict(P1_ANSWERS,
                                 concept_what="Cat sitting marketplace"))
        checkpoints.run_checkpoint(self.tmp, "cp_concept", command)
        prompt = prompt_file.read_text(encoding="utf-8")
        self.assertNotIn("Reality digest", prompt)
        self.assertNotIn("wide open market", prompt)

    def test_phase_step_is_rejected_by_wizard_seam(self):
        command = make_stub(self.tmp, "print('unused')\n")
        with self.assertRaises(ValueError):
            checkpoints.run_checkpoint(self.tmp, "p1", command)


if __name__ == "__main__":
    unittest.main()
