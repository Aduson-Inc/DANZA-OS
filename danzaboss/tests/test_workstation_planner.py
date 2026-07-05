"""W1-P3 plan validation: the size proxies that enforce the 20-30 minute
rule (design spec section 6). The AI proposes; these checks refuse."""
import unittest

import _bootstrap  # noqa
from danzaboss.workstation.planner import (PlanningError, parse_plan,
                                           validate_plan)


def leaf(tid, desc="implement one focused change", **over):
    base = {"id": tid, "description": desc, "kind": "backend",
            "size_est": 20, "writes": ["src/x.py"],
            "verification": {"kind": "automated_test",
                             "detail": "pytest tests/test_x.py"}}
    base.update(over)
    return base


def plan(*tasks):
    return {"spec_ref": ".danza/spec.md", "tasks": list(tasks)}


VALID = plan(
    {"id": "1", "description": "accounts area", "subtasks": [
        {"id": "1.1", "description": "signup feature", "subtasks": [
            leaf("1.1.1"),
            leaf("1.1.2", depends_on=["1.1.1"]),
        ]},
        leaf("1.2"),
    ]},
    {"id": "2", "description": "billing area", "subtasks": [
        leaf("2.1", flags=["payment"], depends_on=["1"]),
    ]},
)


class ParsePlan(unittest.TestCase):
    def test_valid_plan_parses(self):
        tasks = parse_plan(VALID)
        self.assertEqual([t.id for t in tasks], ["1", "2"])
        self.assertEqual(tasks[0].subtasks[0].subtasks[1].depends_on,
                         ("1.1.1",))
        self.assertEqual(tasks[1].subtasks[0].flags, ("payment",))

    def test_non_object_rejected(self):
        with self.assertRaises(PlanningError):
            parse_plan([1, 2])

    def test_missing_spec_ref_rejected(self):
        with self.assertRaises(PlanningError):
            parse_plan({"tasks": [leaf("1")]})

    def test_empty_tasks_rejected(self):
        with self.assertRaises(PlanningError):
            parse_plan({"spec_ref": "s", "tasks": []})

    def test_unknown_verification_kind_rejected(self):
        with self.assertRaises(PlanningError):
            parse_plan(plan(leaf("1", verification={"kind": "vibes",
                                                    "detail": "trust me"})))

    def test_boolean_size_est_rejected(self):
        with self.assertRaises(PlanningError):
            parse_plan(plan(leaf("1", size_est=True)))

    def test_non_list_depends_on_rejected(self):
        with self.assertRaises(PlanningError):
            parse_plan(plan(leaf("1", depends_on="1.2")))


class ValidatePlan(unittest.TestCase):
    def check(self, plan_dict):
        return validate_plan(parse_plan(plan_dict))

    def test_valid_plan_has_no_violations(self):
        self.assertEqual(self.check(VALID), [])

    def test_non_numeric_id(self):
        found = self.check(plan(leaf("a")))
        self.assertTrue(any("dotted integers" in v for v in found), found)

    def test_top_level_must_be_section(self):
        found = self.check(plan(leaf("1.1")))
        self.assertTrue(any("top-level" in v for v in found), found)

    def test_child_must_extend_parent(self):
        found = self.check(plan({"id": "1", "description": "area",
                                 "subtasks": [leaf("2.1")]}))
        self.assertTrue(any("extend parent" in v for v in found), found)

    def test_duplicate_ids(self):
        found = self.check(plan(
            {"id": "1", "description": "area",
             "subtasks": [leaf("1.1"), leaf("1.1")]}))
        self.assertTrue(any("duplicate" in v for v in found), found)

    def test_internal_node_with_verification(self):
        found = self.check(plan(
            {"id": "1", "description": "area",
             "verification": {"kind": "manual_gate", "detail": "look"},
             "subtasks": [leaf("1.1")]}))
        self.assertTrue(any("internal node" in v for v in found), found)

    def test_internal_node_with_depends_on(self):
        found = self.check(plan(
            {"id": "1", "description": "area", "depends_on": ["2"],
             "subtasks": [leaf("1.1")]},
            {"id": "2", "description": "other", "subtasks": [leaf("2.1")]}))
        self.assertTrue(any("leaves only" in v for v in found), found)

    def test_unknown_kind(self):
        found = self.check(plan(leaf("1", kind="poetry")))
        self.assertTrue(any("kind" in v for v in found), found)

    def test_missing_kind(self):
        found = self.check(plan(leaf("1", kind=None)))
        self.assertTrue(any("kind" in v for v in found), found)

    def test_oversized_leaf_told_to_split(self):
        found = self.check(plan(leaf("1", size_est=90)))
        self.assertTrue(any("split this" in v for v in found), found)

    def test_too_many_writes(self):
        found = self.check(plan(leaf("1", writes=["a", "b", "c", "d"])))
        self.assertTrue(any("writes" in v for v in found), found)

    def test_empty_writes(self):
        found = self.check(plan(leaf("1", writes=[])))
        self.assertTrue(any("writes" in v for v in found), found)

    def test_missing_verification(self):
        found = self.check(plan(leaf("1", verification=None)))
        self.assertTrue(any("concrete verification" in v for v in found),
                        found)

    def test_conjunction_chain_rejected(self):
        found = self.check(plan(leaf(
            "1", desc="add the model and then wire the route and also test")))
        self.assertTrue(any("multiple concerns" in v for v in found), found)

    def test_semicolon_chain_rejected(self):
        found = self.check(plan(leaf("1", desc="add model; wire route")))
        self.assertTrue(any("multiple concerns" in v for v in found), found)

    def test_single_and_is_allowed(self):
        self.assertEqual(
            self.check(plan(leaf("1", desc="parse and validate the header"))),
            [])

    def test_unknown_flag(self):
        found = self.check(plan(leaf("1", flags=["gdpr"])))
        self.assertTrue(any("flags" in v for v in found), found)

    def test_unknown_dependency(self):
        found = self.check(plan(leaf("1", depends_on=["9.9"])))
        self.assertTrue(any("unknown task" in v for v in found), found)

    def test_ancestor_dependency_rejected(self):
        found = self.check(plan(
            {"id": "1", "description": "area",
             "subtasks": [leaf("1.1", depends_on=["1"])]}))
        self.assertTrue(any("ancestor" in v for v in found), found)


if __name__ == "__main__":
    unittest.main()
