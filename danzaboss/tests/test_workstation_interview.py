"""Adaptive-interview contract tests (product spec section 7, D6)."""
import sys
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.workstation import checkpoints, interview


def make_stub(tmp: Path, body: str) -> list[str]:
    stub = tmp / "stub_boss.py"
    stub.write_text(body, encoding="utf-8")
    return [sys.executable, str(stub)]


UNCLEAR = {"ambiguities": ["which currency?"],
           "follow_up_questions": ["USD or EUR?"], "clear": False}


class ParseReplyTests(unittest.TestCase):
    def test_valid_unclear_reply_normalizes(self):
        out = interview.parse_reply(
            '{"ambiguities": [" which currency? "], '
            '"follow_up_questions": ["USD or EUR?"], "clear": false}')
        self.assertEqual(out["ambiguities"], ["which currency?"])
        self.assertFalse(out["clear"])

    def test_clear_flag_is_data_not_control(self):
        # AI says clear but still lists an ambiguity -> deterministically unclear
        out = interview.parse_reply(
            '{"ambiguities": ["x"], "follow_up_questions": [], "clear": true}')
        self.assertFalse(out["clear"])

    def test_truly_clear_reply(self):
        out = interview.parse_reply(
            '{"ambiguities": [], "follow_up_questions": [], "clear": true}')
        self.assertTrue(out["clear"])

    def test_unclear_with_nothing_to_ask_is_unusable(self):
        with self.assertRaises(interview.InterviewError):
            interview.parse_reply(
                '{"ambiguities": [], "follow_up_questions": [], "clear": false}')

    def test_missing_keys_fail_closed(self):
        with self.assertRaises(interview.InterviewError):
            interview.parse_reply('{"clear": true}')

    def test_non_string_items_fail_closed(self):
        with self.assertRaises(interview.InterviewError):
            interview.parse_reply(
                '{"ambiguities": [1], "follow_up_questions": [], "clear": false}')

    def test_result_envelope_is_unwrapped(self):
        # the `--output-format json` envelope shape real CLIs emit
        out = interview.parse_reply(
            '{"result": "{\\"ambiguities\\": [], '
            '\\"follow_up_questions\\": [], \\"clear\\": true}"}')
        self.assertTrue(out["clear"])


class PromptTests(unittest.TestCase):
    def test_prompt_carries_phase_and_accumulated_context(self):
        prompt = interview.build_interview_prompt(
            "Concept", {"concept_what": "a dog app"},
            {"project_type": "saas", "concept_what": "a dog app"},
            [], memory="prefers python")
        self.assertIn("DANZA onboarding interviewer", prompt)
        self.assertIn("a dog app", prompt)
        self.assertIn('"project_type": "saas"', prompt)
        self.assertIn("prefers python", prompt)
        self.assertIn(interview.INTERVIEW_CONTRACT, prompt)

    def test_prompt_forbids_drift(self):
        prompt = interview.build_interview_prompt("Concept", {}, {}, [])
        self.assertIn("never introduce features", prompt.lower())

    def test_prior_rounds_ride_inline(self):
        rounds = [{"ambiguities": ["a"], "follow_up_questions": ["q1?"],
                   "clear": False, "answers": {"q1?": "answer one"}}]
        prompt = interview.build_interview_prompt("Concept", {}, {}, rounds)
        self.assertIn("q1?", prompt)
        self.assertIn("answer one", prompt)


class CallTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_call_returns_normalized_reply(self):
        import json as _json
        command = make_stub(self.tmp,
                            f"import json\nprint(json.dumps({UNCLEAR!r}))\n")
        out = interview.call_interview(command, "grill this")
        self.assertEqual(out["follow_up_questions"], ["USD or EUR?"])

    def test_one_retry_on_garbage_then_success(self):
        # first call prints prose; retry (prompt contains the harder
        # instruction) prints valid JSON — same pattern as call_checkpoint
        body = (
            "import json, sys\n"
            "prompt = sys.argv[1]\n"
            "if 'not valid JSON' in prompt:\n"
            f"    print(json.dumps({UNCLEAR!r}))\n"
            "else:\n"
            "    print('no json here')\n")
        out = interview.call_interview(make_stub(self.tmp, body), "grill")
        self.assertFalse(out["clear"])

    def test_unavailable_cli_propagates(self):
        with self.assertRaises(checkpoints.CheckpointUnavailable):
            interview.call_interview(["/nonexistent/boss-cli"], "grill")


if __name__ == "__main__":
    unittest.main()
