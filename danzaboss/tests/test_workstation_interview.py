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

CLEAR = {"ambiguities": [], "follow_up_questions": [], "clear": True}


def submit_p0_p1(root: Path) -> None:
    """Drive the real wizard to a grillable phase."""
    from danzaboss.workstation.wizard import Wizard
    wiz = Wizard(root)
    wiz.submit("p0", {"project_type": "saas"})
    Wizard(root).submit("p1", {
        "project_name": "Dogly", "concept_what": "a dog-walking app",
        "concept_who": "dog owners", "concept_problem": "no time to walk",
        "features_must": ["book a walker"], "non_goals": ["social feed"]})


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


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        submit_p0_p1(self.root)
        interview.begin_phase(self.root, "p1")

    def stub(self, payload) -> list[str]:
        return make_stub(self.root,
                         f"import json\nprint(json.dumps({payload!r}))\n")

    def test_unclear_round_stores_followups(self):
        record = interview.run_interview_round(
            self.root, "p1", self.stub(UNCLEAR))
        self.assertEqual(len(record["rounds"]), 1)
        self.assertEqual(record["rounds"][0]["follow_up_questions"],
                         ["USD or EUR?"])
        self.assertFalse(record["clear"])
        self.assertFalse(record["needs_user_decision"])

    def test_followup_answers_merge_then_clear(self):
        interview.run_interview_round(self.root, "p1", self.stub(UNCLEAR))
        interview.record_followup_answers(
            self.root, "p1", {"USD or EUR?": "USD"})
        record = interview.run_interview_round(
            self.root, "p1", self.stub(CLEAR))
        self.assertTrue(record["clear"])
        self.assertEqual(record["rounds"][0]["answers"], {"USD or EUR?": "USD"})
        self.assertTrue(interview.phase_clear(record))

    def test_cap_escalates_to_user(self):
        for _ in range(interview.MAX_ROUNDS):
            record = interview.run_interview_round(
                self.root, "p1", self.stub(UNCLEAR))
            if not record["needs_user_decision"]:
                interview.record_followup_answers(
                    self.root, "p1", {"USD or EUR?": "still deciding"})
        self.assertEqual(len(record["rounds"]), interview.MAX_ROUNDS)
        self.assertTrue(record["needs_user_decision"])
        self.assertFalse(interview.phase_clear(record))
        # a 4th round is a no-op, not a 4th AI call
        again = interview.run_interview_round(
            self.root, "p1", self.stub(UNCLEAR))
        self.assertEqual(len(again["rounds"]), interview.MAX_ROUNDS)

    def test_resolution_is_final(self):
        for _ in range(interview.MAX_ROUNDS):
            interview.run_interview_round(self.root, "p1", self.stub(UNCLEAR))
        record = interview.resolve(self.root, "p1", "USD only, v1")
        self.assertEqual(record["resolution"], "USD only, v1")
        self.assertFalse(record["needs_user_decision"])
        self.assertTrue(interview.phase_clear(record))
        with self.assertRaises(interview.InterviewError):
            interview.record_followup_answers(self.root, "p1", {"q": "a"})

    def test_unreachable_boss_degrades_and_continues(self):
        record = interview.run_interview_round(
            self.root, "p1", ["/nonexistent/boss-cli"])
        self.assertTrue(record["degraded"])
        self.assertTrue(interview.phase_clear(record))

    def test_no_command_degrades(self):
        record = interview.run_interview_round(self.root, "p1", None)
        self.assertTrue(record["degraded"])
        self.assertIn("no AI agent is connected", record["degraded_reason"])

    def test_double_garbage_reply_degrades_and_continues(self):
        # boss returns unparseable prose on both the first call and the
        # retry -> call_interview's retry-path parse failure raises
        # InterviewError, not CheckpointError; the round must still
        # degrade instead of raising out (P3-D2: "one retry, then
        # degraded").
        always_garbage = make_stub(
            self.root, "print('no json here')\n")
        record = interview.run_interview_round(
            self.root, "p1", always_garbage)
        self.assertTrue(record["degraded"])
        self.assertTrue(interview.phase_clear(record))

    def test_begin_phase_resets_the_grill(self):
        interview.run_interview_round(self.root, "p1", self.stub(UNCLEAR))
        record = interview.begin_phase(self.root, "p1")
        self.assertEqual(record["rounds"], [])

    def test_non_phase_step_is_refused(self):
        with self.assertRaises(interview.InterviewError):
            interview.run_interview_round(
                self.root, "cp_concept", self.stub(CLEAR))


class GateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        submit_p0_p1(self.root)

    def test_no_record_means_clear(self):
        # library/CLI onboarding never ran the interview — additive surface
        self.assertIsNone(interview.blocking_phase(self.root))

    def test_open_grill_blocks(self):
        interview.begin_phase(self.root, "p1")
        stub = make_stub(self.root,
                         f"import json\nprint(json.dumps({UNCLEAR!r}))\n")
        interview.run_interview_round(self.root, "p1", stub)
        self.assertEqual(interview.blocking_phase(self.root), "p1")

    def test_open_questions_lines(self):
        interview.begin_phase(self.root, "p1")
        interview.run_interview_round(self.root, "p1", None)  # degraded
        lines = interview.open_questions(self.root)
        self.assertTrue(any("degraded" in line for line in lines))

    def test_resolution_line_carries_user_decision(self):
        interview.begin_phase(self.root, "p1")
        stub = make_stub(self.root,
                         f"import json\nprint(json.dumps({UNCLEAR!r}))\n")
        for _ in range(interview.MAX_ROUNDS):
            interview.run_interview_round(self.root, "p1", stub)
        interview.resolve(self.root, "p1", "USD only")
        lines = interview.open_questions(self.root)
        self.assertTrue(any("USD only" in line for line in lines))

    def test_corrupt_interview_file_fails_closed(self):
        path = self.root / interview.INTERVIEW_RELPATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[]", encoding="utf-8")
        with self.assertRaises(interview.InterviewError):
            interview.load_interview(self.root)


if __name__ == "__main__":
    unittest.main()
