"""Phase 3 write-side acceptance: dashboard onboarding POST routes."""
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.workstation.routing import (ROUTING_RELPATH,
                                           SCHEMA_VERSION as ROUTING_SCHEMA_VERSION,
                                           SEAT_WORK_TYPES)
from danzaboss.workstation.runners import RUNNERS_RELPATH, SCHEMA_VERSION
from danzaboss.workstation.server import serve_in_thread
from danzaboss.workstation.wizard import Wizard


def install_stub_boss(root: Path, body: str, headless: bool = True) -> Path:
    """Register a stub python script as the repo's headless boss runner and
    confirm it as the whole team (routing.json) so the Phase 4 setup-first
    gate lets onboarding POSTs through.

    validate_config accepts arbitrary runner names, so tests point the
    'boss' at a local script — the same injectable-argv seam
    checkpoints.run_headless was designed around. headless=False registers
    the stub with no headless argv: setup is complete but every AI call
    degrades honestly (boss_available False)."""
    script = root / "stub_boss.py"
    script.write_text(body, encoding="utf-8")
    config = {
        "version": SCHEMA_VERSION, "boss": "stub", "session_host": "headless",
        "permission_mode": None,
        "runners": {"stub": {"kind": "cli", "binary": sys.executable,
                             "display_name": "Stub",
                             "strengths": "",
                             "suggested_seats": [],
                             "activation": "argv",
                             "full_power_extra_argv": [],
                             "interactive": [sys.executable, str(script)],
                             "headless": ([sys.executable, str(script)]
                                          if headless else []),
                             "detected": True}}}
    path = root / RUNNERS_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config), encoding="utf-8")
    routing = {"version": ROUTING_SCHEMA_VERSION, "features_per_turn": 2,
               "lineup": ["stub"],
               "seats": {"conductor": "builtin",
                         **{wt: "stub" for wt in SEAT_WORK_TYPES}}}
    (root / ROUTING_RELPATH).write_text(json.dumps(routing), encoding="utf-8")
    return script


SWITCHING_STUB = r'''
import json, sys
from pathlib import Path
prompt = sys.argv[1]
if "DANZA planner" in prompt:
    print(json.dumps({"spec_ref": ".danza/spec.md", "tasks": [
        {"id": "1-A", "feature_id": 1,
         "description": "Health endpoint returns ok",
         "kind": "backend", "size_est": 12, "writes": ["app.py"],
         "verification": {"kind": "automated_test",
                          "detail": "pytest -k health"}}]}))
elif "onboarding reviewer" in prompt:
    print(json.dumps({"summary": "looks buildable", "concerns": [],
                      "follow_up_questions": [], "recommendation": "proceed",
                      "verdict": "approve"}))
elif "Reality Check analyst" in prompt:
    print(json.dumps({"verdict": "crowded_but_viable",
                      "summary": "market exists",
                      "competitors": [{"name": "Rover", "url": "", "note": ""}],
                      "differentiation": "local focus"}))
else:  # the grill ("You are the DANZA onboarding interviewer")
    marker = Path(__file__).with_name("grilled.txt")
    first = not marker.exists()
    marker.write_text("y")
    if first:
        print(json.dumps({"ambiguities": ["Which currency for payments?"],
                          "follow_up_questions": ["Which currency?"],
                          "clear": False}))
    else:
        print(json.dumps({"ambiguities": [], "follow_up_questions": [],
                          "clear": True}))
'''

UNCLEAR_BODY = ("import json\n"
                "print(json.dumps({'ambiguities': ['which currency?'],"
                " 'follow_up_questions': ['USD or EUR?'], 'clear': False}))\n")
CLEAR_BODY = ("import json\n"
              "print(json.dumps({'ambiguities': [],"
              " 'follow_up_questions': [], 'clear': True}))\n")

P1_ANSWERS = {"project_name": "Dogly", "concept_what": "a dog-walking app",
              "concept_who": "dog owners", "concept_problem": "no time",
              "features_must": ["book a walker"], "non_goals": ["social feed"]}


def post(port, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class OnboardPostTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.server, self.port = serve_in_thread(str(self.root))
        self.addCleanup(self.server.shutdown)

    def test_submit_validates_and_advances(self):
        install_stub_boss(self.root, CLEAR_BODY)
        status, out = post(self.port, "/api/onboard/submit",
                           {"step_id": "p0", "answers": {"project_type": "saas"}})
        self.assertEqual(status, 200)
        self.assertTrue(out["interview"]["clear"])
        self.assertEqual(out["onboarding"]["current_step"], "p1")

    def test_bad_answer_is_400_with_reason(self):
        install_stub_boss(self.root, CLEAR_BODY)
        status, out = post(self.port, "/api/onboard/submit",
                           {"step_id": "p0", "answers": {"project_type": "yacht"}})
        self.assertEqual(status, 400)
        self.assertIn("project_type", out["error"])

    def test_unclear_grill_blocks_other_submits_409(self):
        install_stub_boss(self.root, UNCLEAR_BODY)
        post(self.port, "/api/onboard/submit",
             {"step_id": "p0", "answers": {"project_type": "saas"}})
        # p0 grill is open -> submitting p1 is gated
        status, out = post(self.port, "/api/onboard/submit",
                           {"step_id": "p1", "answers": P1_ANSWERS})
        self.assertEqual(status, 409)
        self.assertIn("p0", out["error"])

    def test_followup_then_clear_unblocks(self):
        script = install_stub_boss(self.root, UNCLEAR_BODY)
        post(self.port, "/api/onboard/submit",
             {"step_id": "p0", "answers": {"project_type": "saas"}})
        script.write_text(CLEAR_BODY, encoding="utf-8")
        status, out = post(self.port, "/api/onboard/followup",
                           {"step_id": "p0", "answers": {"USD or EUR?": "USD"}})
        self.assertEqual(status, 200)
        self.assertIsNone(out["onboarding"]["blocking_phase"])

    def test_resolve_needs_escalation_flow(self):
        install_stub_boss(self.root, UNCLEAR_BODY)
        post(self.port, "/api/onboard/submit",
             {"step_id": "p0", "answers": {"project_type": "saas"}})
        for _ in range(2):
            post(self.port, "/api/onboard/followup",
                 {"step_id": "p0", "answers": {"USD or EUR?": "hmm"}})
        status, out = post(self.port, "/api/onboard/resolve",
                           {"step_id": "p0", "decision": "USD only"})
        self.assertEqual(status, 200)
        self.assertEqual(out["interview"]["resolution"], "USD only")
        self.assertIsNone(out["onboarding"]["blocking_phase"])

    def test_research_without_provider_records_skip(self):
        # headless-less boss and no TAVILY key: setup is confirmed (the
        # Phase 4 gate passes) but the grill degrades and research honestly
        # records the skipped digest
        install_stub_boss(self.root, CLEAR_BODY, headless=False)
        saved = os.environ.pop("TAVILY_API_KEY", None)
        self.addCleanup(lambda: saved and os.environ.__setitem__(
            "TAVILY_API_KEY", saved))
        post(self.port, "/api/onboard/submit",
             {"step_id": "p0", "answers": {"project_type": "saas"}})
        post(self.port, "/api/onboard/submit",
             {"step_id": "p1", "answers": P1_ANSWERS})
        status, out = post(self.port, "/api/onboard/research", {})
        self.assertEqual(status, 200)
        self.assertTrue(out["digest"]["skipped"])

    def test_checkpoint_runs_and_approval_is_gated_by_grill(self):
        script = install_stub_boss(self.root, CLEAR_BODY)
        self._complete_through_p1()
        # r_reality precedes cp_concept in the flow, and record_result()
        # requires every earlier step to be terminal before an approval —
        # the research call needs a digest-shaped reply (not the grill's
        # clear/ambiguities shape) so r_reality actually completes.
        digest_body = (
            "import json\n"
            "print(json.dumps({'verdict': 'novel', 'summary': 'ok',"
            " 'competitors': [], 'differentiation': 'first mover'}))\n")
        script.write_text(digest_body, encoding="utf-8")
        post(self.port, "/api/onboard/research", {})
        script.write_text(CLEAR_BODY, encoding="utf-8")
        verdict_body = (
            "import json\n"
            "print(json.dumps({'summary': 'ok', 'concerns': [],"
            " 'follow_up_questions': [], 'recommendation': 'go',"
            " 'verdict': 'approve'}))\n")
        script.write_text(verdict_body, encoding="utf-8")
        status, out = post(self.port, "/api/onboard/checkpoint",
                           {"step_id": "cp_concept"})
        self.assertEqual(status, 200)
        self.assertEqual(out["verdict"]["verdict"], "approve")
        status, _ = post(self.port, "/api/onboard/approve",
                         {"step_id": "cp_concept"})
        self.assertEqual(status, 200)
        self.assertEqual(Wizard(str(self.root)).status("cp_concept"),
                         "approved")

    def test_approve_without_verdict_is_409(self):
        install_stub_boss(self.root, CLEAR_BODY)
        self._complete_through_p1()
        post(self.port, "/api/onboard/research", {})
        status, out = post(self.port, "/api/onboard/approve",
                           {"step_id": "cp_concept"})
        self.assertEqual(status, 409)
        self.assertIn("review", out["error"])

    def test_unknown_route_404_and_bad_body_400(self):
        status, _ = post(self.port, "/api/onboard/nope", {})
        self.assertEqual(status, 404)
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/onboard/submit",
            data=b"not json", method="POST")
        try:
            urllib.request.urlopen(req, timeout=10)
            self.fail("expected 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

    def _complete_through_p1(self):
        if not (self.root / RUNNERS_RELPATH).exists():
            install_stub_boss(self.root, CLEAR_BODY)
        post(self.port, "/api/onboard/submit",
             {"step_id": "p0", "answers": {"project_type": "saas"}})
        post(self.port, "/api/onboard/submit",
             {"step_id": "p1", "answers": P1_ANSWERS})


ALWAYS_UNCLEAR_STUB = (
    "import json\n"
    "print(json.dumps({'ambiguities': ['which currency?'],"
    " 'follow_up_questions': ['Which currency?'], 'clear': False}))\n")


class FinishTests(unittest.TestCase):
    """Task 6: onboarding finish stops after PROJECT discovery evidence."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        # a real key in the environment would route research to Tavily's API
        saved = os.environ.pop("TAVILY_API_KEY", None)
        self.addCleanup(lambda: saved and os.environ.__setitem__(
            "TAVILY_API_KEY", saved))
        self.server, self.port = serve_in_thread(str(self.root))
        self.addCleanup(self.server.shutdown)
        self.script = install_stub_boss(self.root, SWITCHING_STUB)

    def _onboard_everything(self):
        """Drive the whole wizard over HTTP: p0 grill unclear once
        (follow-up answered), everything else clear; research; three
        checkpoints run + approved; p2..p5 submitted."""
        post(self.port, "/api/onboard/submit",
             {"step_id": "p0", "answers": {"project_type": "saas"}})
        # first interview call was unclear -> answer and clear it
        post(self.port, "/api/onboard/followup",
             {"step_id": "p0", "answers": {"Which currency?": "USD"}})
        post(self.port, "/api/onboard/submit",
             {"step_id": "p1", "answers": P1_ANSWERS})
        post(self.port, "/api/onboard/research", {})
        post(self.port, "/api/onboard/checkpoint", {"step_id": "cp_concept"})
        post(self.port, "/api/onboard/approve", {"step_id": "cp_concept"})
        post(self.port, "/api/onboard/submit",
             {"step_id": "p2", "answers": {"capabilities": ["payments"]}})
        post(self.port, "/api/onboard/submit",
             {"step_id": "p3", "answers": {"stack_choice": "no_preference"}})
        post(self.port, "/api/onboard/checkpoint", {"step_id": "cp_stack"})
        post(self.port, "/api/onboard/approve", {"step_id": "cp_stack"})
        post(self.port, "/api/onboard/submit", {"step_id": "p4", "answers": {}})
        post(self.port, "/api/onboard/submit",
             {"step_id": "p5", "answers": {"repo_mode": "fresh"}})
        post(self.port, "/api/onboard/checkpoint", {"step_id": "cp_final"})
        post(self.port, "/api/onboard/approve", {"step_id": "cp_final"})

    def test_full_run_compiles_spec_and_stops_before_scope_and_plan(self):
        self._onboard_everything()
        status, out = post(self.port, "/api/onboard/finish", {})
        self.assertEqual(status, 200, out)
        spec = (self.root / ".danza" / "spec.md").read_text(encoding="utf-8")
        self.assertIn("# Spec — Dogly", spec)
        self.assertEqual(out["project"]["mode"], "new")
        self.assertFalse((self.root / ".danza" / "features.json").exists())
        self.assertFalse((self.root / ".danza" / "plan.json").exists())
        self.assertFalse((self.root / ".danza" / "plan.md").exists())
        status, _ = post(self.port, "/api/onboard/finish", {})
        self.assertEqual(status, 200)  # regeneration is idempotent

    def test_finish_before_complete_is_409(self):
        post(self.port, "/api/onboard/submit",
             {"step_id": "p0", "answers": {"project_type": "saas"}})
        status, out = post(self.port, "/api/onboard/finish", {})
        self.assertEqual(status, 409)

    def test_seed_project_cannot_finish(self):
        post(self.port, "/api/onboard/submit",
             {"step_id": "p0", "answers": {"project_type": "workflow"}})
        post(self.port, "/api/onboard/followup",
             {"step_id": "p0", "answers": {"Which currency?": "n/a"}})
        post(self.port, "/api/onboard/submit",
             {"step_id": "p_seed", "answers": {
                 "seed_name": "idea", "seed_intent": "a workflow thing"}})
        status, out = post(self.port, "/api/onboard/finish", {})
        self.assertEqual(status, 400)
        self.assertIn("idea", out["error"].lower())

    def test_escalated_resolution_reaches_spec_appendix(self):
        # p0 clears normally through the SWITCHING_STUB's grill (unclear
        # once, then clear after the follow-up is answered).
        post(self.port, "/api/onboard/submit",
             {"step_id": "p0", "answers": {"project_type": "saas"}})
        post(self.port, "/api/onboard/followup",
             {"step_id": "p0", "answers": {"Which currency?": "USD"}})
        # Force cap escalation on p1: swap in a stub that is NEVER clear,
        # so three rounds (submit + two follow-ups) exhaust MAX_ROUNDS and
        # the interview escalates to needs_user_decision.
        self.script.write_text(ALWAYS_UNCLEAR_STUB, encoding="utf-8")
        post(self.port, "/api/onboard/submit",
             {"step_id": "p1", "answers": P1_ANSWERS})
        for _ in range(2):
            post(self.port, "/api/onboard/followup",
                 {"step_id": "p1", "answers": {"Which currency?": "still unsure"}})
        status, out = post(self.port, "/api/onboard/resolve",
                           {"step_id": "p1", "decision": "USD only"})
        self.assertEqual(status, 200)
        self.assertEqual(out["interview"]["resolution"], "USD only")
        # Swap back to the well-behaved stub and complete the rest of the
        # run exactly as _onboard_everything does from p1 onward.
        self.script.write_text(SWITCHING_STUB, encoding="utf-8")
        post(self.port, "/api/onboard/research", {})
        post(self.port, "/api/onboard/checkpoint", {"step_id": "cp_concept"})
        post(self.port, "/api/onboard/approve", {"step_id": "cp_concept"})
        post(self.port, "/api/onboard/submit",
             {"step_id": "p2", "answers": {"capabilities": ["payments"]}})
        post(self.port, "/api/onboard/submit",
             {"step_id": "p3", "answers": {"stack_choice": "no_preference"}})
        post(self.port, "/api/onboard/checkpoint", {"step_id": "cp_stack"})
        post(self.port, "/api/onboard/approve", {"step_id": "cp_stack"})
        post(self.port, "/api/onboard/submit", {"step_id": "p4", "answers": {}})
        post(self.port, "/api/onboard/submit",
             {"step_id": "p5", "answers": {"repo_mode": "fresh"}})
        post(self.port, "/api/onboard/checkpoint", {"step_id": "cp_final"})
        post(self.port, "/api/onboard/approve", {"step_id": "cp_final"})
        status, out = post(self.port, "/api/onboard/finish", {})
        self.assertEqual(status, 200, out)
        spec = (self.root / ".danza" / "spec.md").read_text(encoding="utf-8")
        self.assertIn("user decision (final): USD only", spec)


if __name__ == "__main__":
    unittest.main()
