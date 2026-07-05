"""W1-P1 question tree: the onboarding flow is data (design D3/D9);
these tests pin its structural invariants so the engine can trust them."""
import unittest

import _bootstrap  # noqa
from danzaboss.workstation.tree import (APP_PROJECT_TYPES, FLOW,
                                        SEED_PROJECT_TYPES, Step,
                                        step_applies)


class TreeInvariants(unittest.TestCase):
    def test_first_step_is_project_type_phase(self):
        self.assertEqual(FLOW[0].id, "p0")
        self.assertEqual(FLOW[0].kind, "phase")
        self.assertEqual(FLOW[0].questions[0].id, "project_type")

    def test_question_ids_unique_across_flow(self):
        ids = [q.id for step in FLOW for q in step.questions]
        self.assertEqual(len(ids), len(set(ids)), f"duplicate ids: {ids}")

    def test_step_ids_unique_and_kinds_valid(self):
        ids = [s.id for s in FLOW]
        self.assertEqual(len(ids), len(set(ids)))
        for step in FLOW:
            self.assertIn(step.kind, ("phase", "research", "checkpoint"))

    def test_choice_and_multi_questions_have_options(self):
        for step in FLOW:
            for q in step.questions:
                if q.kind in ("choice", "multi"):
                    self.assertTrue(q.options, f"{q.id} has no options")

    def test_project_types_cover_all_p0_options(self):
        p0_options = set(FLOW[0].questions[0].options)
        self.assertEqual(p0_options, APP_PROJECT_TYPES | SEED_PROJECT_TYPES)

    def test_show_if_references_existing_questions(self):
        ids = {q.id for step in FLOW for q in step.questions}
        for step in FLOW:
            for q in step.questions:
                for ref, _accepted in q.show_if:
                    self.assertIn(ref, ids, f"{q.id} show_if references {ref}")

    def test_expected_flow_order_for_app_projects(self):
        app_ids = [s.id for s in FLOW if step_applies(s, "saas")]
        self.assertEqual(app_ids, ["p0", "p1", "r_reality", "cp_concept",
                                   "p2", "p3", "cp_stack", "p4", "p5",
                                   "cp_final"])


class SeedRouting(unittest.TestCase):
    def test_only_p0_before_project_type_known(self):
        applicable = [s.id for s in FLOW if step_applies(s, None)]
        self.assertEqual(applicable, ["p0"])

    def test_seed_types_get_only_seed_phase(self):
        for ptype in sorted(SEED_PROJECT_TYPES):
            ids = [s.id for s in FLOW if step_applies(s, ptype)]
            self.assertEqual(ids, ["p0", "p_seed"], ptype)

    def test_app_types_skip_seed_phase(self):
        for ptype in sorted(APP_PROJECT_TYPES):
            ids = [s.id for s in FLOW if step_applies(s, ptype)]
            self.assertNotIn("p_seed", ids)
            self.assertIn("cp_final", ids)


if __name__ == "__main__":
    unittest.main()


class FailClosedGuards(unittest.TestCase):
    """Deferred P1 minors: declaration-time kind validation and unknown
    project_type rejection (corrupt-state guard)."""

    def test_unknown_question_kind_raises(self):
        from danzaboss.workstation.tree import Question
        with self.assertRaises(ValueError):
            Question("q", "prompt", "vibes")

    def test_unknown_step_kind_raises(self):
        with self.assertRaises(ValueError):
            Step("s", "party", "title")

    def test_unknown_project_type_raises(self):
        with self.assertRaises(ValueError):
            step_applies(FLOW[1], "spaceship")
