"""W1-P1 wizard engine: validation, routing, resume, and the revision rule
(editing an approved phase stales everything after it — design section 4)."""
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.workstation.wizard import Wizard, WizardError

P1_ANSWERS = {
    "project_name": "TestApp",
    "concept_what": "It tracks practice sessions for drummers.",
    "concept_who": "Working drummers",
    "concept_problem": "No log of what was practiced",
    "features_must": ["log a session", "weekly summary"],
    "non_goals": ["social feed"],
}


class WizardBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.wiz = Wizard(self.root)


class FlowAndRouting(WizardBase):
    def test_fresh_wizard_starts_at_p0(self):
        self.assertEqual(self.wiz.current_step().id, "p0")

    def test_seed_type_routes_to_seed_phase_only(self):
        self.wiz.submit("p0", {"project_type": "design_ideas"})
        self.assertEqual([s.id for s in self.wiz.flow()], ["p0", "p_seed"])
        self.assertEqual(self.wiz.current_step().id, "p_seed")

    def test_app_type_routes_to_full_interview(self):
        self.wiz.submit("p0", {"project_type": "saas"})
        self.assertEqual(self.wiz.current_step().id, "p1")
        self.assertNotIn("p_seed", [s.id for s in self.wiz.flow()])


class Validation(WizardBase):
    def setUp(self):
        super().setUp()
        self.wiz.submit("p0", {"project_type": "saas"})

    def test_missing_required_raises(self):
        with self.assertRaises(WizardError):
            self.wiz.submit("p1", {"project_name": "X"})

    def test_unknown_question_raises(self):
        with self.assertRaises(WizardError):
            self.wiz.submit("p1", dict(P1_ANSWERS, bogus="nope"))

    def test_bad_choice_raises(self):
        with self.assertRaises(WizardError):
            self.wiz.submit("p0", {"project_type": "spaceship"})

    def test_multi_values_must_be_in_options(self):
        self.wiz.submit("p1", P1_ANSWERS)
        with self.assertRaises(WizardError):
            self.wiz.submit("p2", {"capabilities": ["telepathy"]})

    def test_hidden_question_not_required(self):
        self.wiz.submit("p1", P1_ANSWERS)
        self.wiz.record_result("r_reality", {"skipped": True})
        self.wiz.record_result("cp_concept", {"verdict": "ok"}, approved=True)
        self.wiz.submit("p2", {})
        # stack_template/stack_custom are hidden for no_preference
        self.wiz.submit("p3", {"stack_choice": "no_preference"})
        self.assertEqual(self.wiz.status("p3"), "complete")

    def test_same_payload_visibility(self):
        self.wiz.submit("p1", P1_ANSWERS)
        self.wiz.record_result("r_reality", {"skipped": True})
        self.wiz.record_result("cp_concept", {"verdict": "ok"}, approved=True)
        self.wiz.submit("p2", {})
        # choosing template + naming it in ONE payload must work
        self.wiz.submit("p3", {"stack_choice": "template",
                               "stack_template": "saas-ts"})
        self.assertEqual(self.wiz.answers["stack_template"], "saas-ts")

    def test_default_fills_required_choice(self):
        self.wiz.submit("p1", P1_ANSWERS)
        self.wiz.record_result("r_reality", {"skipped": True})
        self.wiz.record_result("cp_concept", {"verdict": "ok"}, approved=True)
        self.wiz.submit("p2", {})
        self.wiz.submit("p3", {"stack_choice": "no_preference"})
        self.wiz.submit("p4", {})  # color_direction defaults to "propose"
        self.assertEqual(self.wiz.answers["color_direction"], "propose")

    def test_submit_to_checkpoint_step_raises(self):
        with self.assertRaises(WizardError):
            self.wiz.submit("cp_concept", {})

    def test_step_not_in_active_flow_raises(self):
        with self.assertRaises(WizardError):
            self.wiz.submit("p_seed", {"seed_name": "x", "seed_intent": "y"})


class RevisionRule(WizardBase):
    def _complete_through_stack(self):
        self.wiz.submit("p0", {"project_type": "saas"})
        self.wiz.submit("p1", P1_ANSWERS)
        self.wiz.record_result("r_reality", {"verdict": "viable"})
        self.wiz.record_result("cp_concept", {"verdict": "ok"}, approved=True)
        self.wiz.submit("p2", {"capabilities": ["accounts_auth"]})
        self.wiz.submit("p3", {"stack_choice": "no_preference"})
        self.wiz.record_result("cp_stack", {"pick": "saas-ts"}, approved=True)

    def test_editing_approved_phase_stales_downstream(self):
        self._complete_through_stack()
        self.wiz.submit("p1", dict(P1_ANSWERS, concept_what="Now it is a CRM."))
        self.assertEqual(self.wiz.status("p1"), "complete")
        for later in ("r_reality", "cp_concept", "p2", "p3", "cp_stack"):
            self.assertEqual(self.wiz.status(later), "stale", later)

    def test_identical_resubmit_does_not_stale(self):
        self._complete_through_stack()
        self.wiz.submit("p1", dict(P1_ANSWERS))
        self.assertEqual(self.wiz.status("cp_stack"), "approved")

    def test_stale_step_is_current_again(self):
        self._complete_through_stack()
        self.wiz.submit("p1", dict(P1_ANSWERS, concept_what="Changed."))
        self.assertEqual(self.wiz.current_step().id, "r_reality")

    def test_project_type_flip_flop_does_not_rehydrate_approvals(self):
        # Final-review fix: _stale_after must walk FLOW, not the active
        # flow, or switching away and back resurrects unearned approvals.
        self._complete_through_stack()
        self.wiz.submit("p0", {"project_type": "design_ideas"})
        self.wiz.submit("p0", {"project_type": "saas"})
        for later in ("p1", "r_reality", "cp_concept", "p2", "p3", "cp_stack"):
            self.assertEqual(self.wiz.status(later), "stale", later)
        self.assertFalse(self.wiz.is_complete())

    def test_premature_checkpoint_approval_raises(self):
        # Final-review fix: an approval must postdate everything it
        # approves — first-time submits never stale, so a premature
        # approval would survive answers it never saw.
        self.wiz.submit("p0", {"project_type": "saas"})
        with self.assertRaises(WizardError):
            self.wiz.record_result("cp_concept", {"verdict": "ok"},
                                   approved=True)


class ResumeAndResults(WizardBase):
    def test_resume_from_disk(self):
        self.wiz.submit("p0", {"project_type": "saas"})
        self.wiz.submit("p1", P1_ANSWERS)
        fresh = Wizard(self.root)
        self.assertEqual(fresh.answers["project_name"], "TestApp")
        self.assertEqual(fresh.status("p1"), "complete")
        self.assertEqual(fresh.current_step().id, "r_reality")

    def test_research_result_stored_and_step_complete(self):
        self.wiz.submit("p0", {"project_type": "saas"})
        self.wiz.submit("p1", P1_ANSWERS)
        digest = {"verdict": "crowded_but_viable", "competitors": ["X"]}
        self.wiz.record_result("r_reality", digest)
        self.assertEqual(self.wiz.result("r_reality"), digest)
        self.assertEqual(self.wiz.status("r_reality"), "complete")

    def test_checkpoint_without_approval_stays_pending(self):
        self.wiz.submit("p0", {"project_type": "saas"})
        self.wiz.submit("p1", P1_ANSWERS)
        self.wiz.record_result("r_reality", {"skipped": True})
        self.wiz.record_result("cp_concept", {"verdict": "concerns"})
        self.assertEqual(self.wiz.status("cp_concept"), "pending")
        self.assertEqual(self.wiz.current_step().id, "cp_concept")

    def test_is_complete_end_to_end(self):
        self.wiz.submit("p0", {"project_type": "saas"})
        self.wiz.submit("p1", P1_ANSWERS)
        self.wiz.record_result("r_reality", {"skipped": True})
        self.wiz.record_result("cp_concept", {"verdict": "ok"}, approved=True)
        self.wiz.submit("p2", {})
        self.wiz.submit("p3", {"stack_choice": "no_preference"})
        self.wiz.record_result("cp_stack", {"pick": "saas-ts"}, approved=True)
        self.wiz.submit("p4", {})
        self.wiz.submit("p5", {"repo_mode": "fresh"})
        self.assertFalse(self.wiz.is_complete())
        self.wiz.record_result("cp_final", {"rundown": "..."}, approved=True)
        self.assertTrue(self.wiz.is_complete())


if __name__ == "__main__":
    unittest.main()
