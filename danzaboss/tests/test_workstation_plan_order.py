"""W1-P3 deterministic ordering: topological over depends_on, tie-break
section order then id; cycles rejected (design spec section 6)."""
import unittest

import _bootstrap  # noqa
from danzaboss.workstation.planner import (PlanningError, feature_nodes,
                                           order_tasks, parse_plan)


def leaf(tid, **over):
    base = {"id": tid, "description": "one focused change",
            "kind": "backend", "size_est": 15, "writes": ["src/x.py"],
            "verification": {"kind": "automated_test",
                             "detail": "pytest tests/test_x.py"}}
    base.update(over)
    return base


def tree(*tasks):
    return parse_plan({"spec_ref": "spec", "tasks": list(tasks)})


class Ordering(unittest.TestCase):
    def test_independent_leaves_in_id_order(self):
        tasks = tree({"id": "1", "description": "a",
                      "subtasks": [leaf("1.2"), leaf("1.1")]})
        self.assertEqual([t.id for t in order_tasks(tasks)], ["1.1", "1.2"])

    def test_dependency_beats_id_order(self):
        tasks = tree(
            {"id": "1", "description": "a",
             "subtasks": [leaf("1.1", depends_on=["2.1"])]},
            {"id": "2", "description": "b", "subtasks": [leaf("2.1")]})
        self.assertEqual([t.id for t in order_tasks(tasks)], ["2.1", "1.1"])

    def test_internal_target_expands_to_leaves(self):
        tasks = tree(
            {"id": "1", "description": "a",
             "subtasks": [leaf("1.1"), leaf("1.2")]},
            {"id": "2", "description": "b",
             "subtasks": [leaf("2.1", depends_on=["1"])]})
        order = [t.id for t in order_tasks(tasks)]
        self.assertLess(order.index("1.2"), order.index("2.1"))

    def test_cycle_rejected(self):
        tasks = tree(
            {"id": "1", "description": "a", "subtasks": [
                leaf("1.1", depends_on=["1.2"]),
                leaf("1.2", depends_on=["1.1"])]})
        with self.assertRaises(PlanningError) as ctx:
            order_tasks(tasks)
        self.assertIn("1.1", str(ctx.exception))

    def test_unknown_target_fails_closed(self):
        tasks = tree({"id": "1", "description": "a",
                      "subtasks": [leaf("1.1", depends_on=["9.9"])]})
        with self.assertRaises(PlanningError):
            order_tasks(tasks)

    def test_duplicate_leaf_ids_fail_closed(self):
        # validate_plan catches this too, but order_tasks must not
        # silently drop a duplicate when called standalone (P3-M2).
        tasks = tree({"id": "1", "description": "a",
                      "subtasks": [leaf("1.1"), leaf("1.1")]})
        with self.assertRaisesRegex(PlanningError, "duplicate"):
            order_tasks(tasks)

    def test_deterministic(self):
        tasks = tree(
            {"id": "1", "description": "a", "subtasks": [
                leaf("1.1"), leaf("1.2", depends_on=["2.1"])]},
            {"id": "2", "description": "b", "subtasks": [leaf("2.1")]})
        self.assertEqual([t.id for t in order_tasks(tasks)],
                         [t.id for t in order_tasks(tasks)])


class FeatureNodes(unittest.TestCase):
    def test_every_ordered_legacy_leaf_counts_independently(self):
        tasks = tree(
            {"id": "1", "description": "a", "subtasks": [
                {"id": "1.1", "description": "f", "subtasks": [
                    leaf("1.1.1"), leaf("1.1.2")]},
                leaf("1.2")]},
            {"id": "2", "description": "b", "subtasks": [leaf("2.1")]})
        self.assertEqual(feature_nodes(order_tasks(tasks)),
                         ("1.1.1", "1.1.2", "1.2", "2.1"))

    def test_section_level_leaf_counts_as_own_feature(self):
        tasks = tree(leaf("1"))
        self.assertEqual(feature_nodes(tasks), ("1",))


if __name__ == "__main__":
    unittest.main()
