"""Phase 4.1 Task 4: product-linked atomic plan leaves."""
import unittest

import _bootstrap  # noqa
from danzaboss.workstation.planner import (
    PlanningError,
    build_planning_prompt,
    feature_nodes,
    order_tasks,
    parse_plan,
    plan_payload,
    plan_warnings,
    render_plan_md,
    validate_plan,
)


def atomic(tid="71-A", *, feature_id=71, **over):
    leaf = {
        "id": tid,
        "feature_id": feature_id,
        "description": "implement one focused change",
        "kind": "backend",
        "size_est": 12,
        "writes": ["src/x.py"],
        "verification": {
            "kind": "automated_test",
            "detail": "pytest tests/test_x.py",
        },
    }
    leaf.update(over)
    return leaf


def plan(*leaves):
    return {"spec_ref": ".danza/features.json#revision-3",
            "tasks": list(leaves)}


class AtomicIdentity(unittest.TestCase):
    def test_atomic_leaf_parses_with_numeric_product_reference(self):
        task = parse_plan(plan(atomic()))[0]
        self.assertEqual((task.id, task.feature_id), ("71-A", 71))

    def test_live_planning_requires_atomic_ids(self):
        legacy = parse_plan({"spec_ref": "legacy", "tasks": [{
            "id": "1.1", "description": "legacy leaf", "kind": "backend",
            "size_est": 20, "writes": ["src/x.py"],
            "verification": {"kind": "automated_test",
                             "detail": "pytest tests/test_x.py"},
        }]})
        found = validate_plan(legacy, require_atomic=True)
        self.assertTrue(any("atomic id" in item for item in found), found)

    def test_atomic_feature_id_is_required_and_matches_id(self):
        missing = atomic()
        missing.pop("feature_id")
        for candidate in (missing, atomic(feature_id=72)):
            with self.subTest(candidate=candidate):
                found = validate_plan(parse_plan(plan(candidate)))
                self.assertTrue(any("feature_id" in item for item in found),
                                found)
        with self.assertRaisesRegex(PlanningError, "feature_id"):
            parse_plan(plan(atomic(feature_id=True)))

    def test_legacy_dotted_plan_retains_identity_and_old_size(self):
        raw = {"spec_ref": "legacy", "tasks": [{
            "id": "1", "description": "area", "subtasks": [{
                "id": "1.2", "description": "legacy leaf",
                "kind": "backend", "size_est": 25,
                "writes": ["src/x.py"],
                "verification": {"kind": "automated_test",
                                 "detail": "pytest tests/test_x.py"},
            }],
        }]}
        tasks = parse_plan(raw)
        self.assertEqual(order_tasks(tasks)[0].id, "1.2")
        self.assertEqual(validate_plan(tasks), [])


class AtomicPolicy(unittest.TestCase):
    def check(self, leaf):
        return validate_plan(parse_plan(plan(leaf)))

    def test_estimates_one_through_twenty_are_valid(self):
        self.assertEqual(self.check(atomic(size_est=1)), [])
        self.assertEqual(self.check(atomic(size_est=20)), [])
        found = self.check(atomic(size_est=21))
        self.assertTrue(any("1..20" in item for item in found), found)

    def test_sub_three_estimate_warns_without_invalidating(self):
        tasks = parse_plan(plan(atomic(size_est=2)))
        self.assertEqual(validate_plan(tasks), [])
        self.assertEqual(plan_warnings(tasks),
                         ["71-A: size_est 2 minutes is below the 3-minute "
                          "calibration floor"])
        self.assertEqual(plan_warnings(parse_plan(plan(atomic(size_est=3)))),
                         [])

    def test_write_areas_must_be_non_empty(self):
        for writes in ([], [""], ["   "], ["a", "b", "c", "d"]):
            with self.subTest(writes=writes):
                found = self.check(atomic(writes=writes))
                self.assertTrue(any("writes" in item for item in found), found)

    def test_one_concern_and_one_verification_remain_required(self):
        with self.assertRaisesRegex(PlanningError, "description"):
            parse_plan(plan(atomic(description="   ")))
        chained = self.check(atomic(
            description="add the model and then wire the route"))
        self.assertTrue(any("multiple concerns" in item for item in chained),
                        chained)
        missing = self.check(atomic(verification=None))
        self.assertTrue(any("exactly one concrete verification" in item
                            for item in missing), missing)

    def test_dependencies_are_validated_and_cycles_rejected(self):
        tasks = parse_plan(plan(
            atomic("71-A"),
            atomic("71-B", depends_on=["71-A"]),
        ))
        self.assertEqual([task.id for task in order_tasks(tasks)],
                         ["71-A", "71-B"])
        cycle = parse_plan(plan(
            atomic("71-A", depends_on=["71-B"]),
            atomic("71-B", depends_on=["71-A"]),
        ))
        with self.assertRaisesRegex(PlanningError, "dependency cycle"):
            order_tasks(cycle)

    def test_hard_stop_flags_survive_payload(self):
        tasks = parse_plan(plan(atomic(flags=["payment"])))
        payload = plan_payload(".danza/features.json#revision-3", tasks,
                               order_tasks(tasks))
        self.assertEqual(payload["tasks"][0]["flags"], ["payment"])


class AtomicCountingAndRendering(unittest.TestCase):
    def setUp(self):
        self.tasks = parse_plan(plan(
            atomic("71-C", depends_on=["71-B"]),
            atomic("71-A"),
            atomic("71-B", depends_on=["71-A"], size_est=2),
        ))
        self.ordered = order_tasks(self.tasks)

    def test_each_ordered_leaf_counts_independently(self):
        self.assertEqual(feature_nodes(self.ordered),
                         ("71-A", "71-B", "71-C"))

    def test_payload_is_authoritative_canonical_leaf_order(self):
        payload = plan_payload(".danza/features.json#revision-3", self.tasks,
                               self.ordered)
        self.assertEqual(payload["order"], ["71-A", "71-B", "71-C"])
        self.assertEqual([leaf["feature_id"] for leaf in payload["tasks"]],
                         [71, 71, 71])

    def test_markdown_counts_leaves_without_prefix_grouping(self):
        text = render_plan_md(".danza/features.json#revision-3", self.ordered)
        self.assertIn("3 atomic units", text)
        self.assertNotIn("across 1 features", text)
        self.assertIn("product feature 71", text)
        self.assertIn("WARNING", text)

    def test_prompt_targets_ten_to_fifteen_minute_atomic_leaves(self):
        prompt = build_planning_prompt("approved scope")
        self.assertIn("10-15 minute", prompt)
        self.assertIn("1-20", prompt)
        self.assertIn('"71-A"', prompt)
        self.assertIn('"feature_id"', prompt)
        self.assertNotIn("20-30 minutes", prompt)


if __name__ == "__main__":
    unittest.main()
