import unittest
import _bootstrap  # noqa
from danzaboss.orchestration.parallel import (
    PTask, plan_waves, token_multiplier, DependencyError)


class TestParallel(unittest.TestCase):
    def test_independent_tasks_one_wave(self):
        waves = plan_waves([PTask("a"), PTask("b"), PTask("c")])
        self.assertEqual(len(waves), 1)
        self.assertEqual(set(waves[0]), {"a", "b", "c"})

    def test_dependencies_serialize(self):
        waves = plan_waves([PTask("a"), PTask("b", depends_on=["a"])])
        self.assertEqual(waves, [["a"], ["b"]])

    def test_write_conflict_splits_waves(self):
        waves = plan_waves([PTask("a", writes=frozenset({"db"})),
                            PTask("b", writes=frozenset({"db"}))])
        # both write db -> cannot share a wave
        self.assertEqual(len(waves), 2)

    def test_max_parallel_cap(self):
        waves = plan_waves([PTask(str(i)) for i in range(10)], max_parallel=3)
        self.assertTrue(all(len(w) <= 3 for w in waves))

    def test_unknown_dependency_raises(self):
        with self.assertRaises(DependencyError):
            plan_waves([PTask("a", depends_on=["ghost"])])

    def test_cycle_detected(self):
        with self.assertRaises(DependencyError):
            plan_waves([PTask("a", depends_on=["b"]), PTask("b", depends_on=["a"])])

    def test_unverifiable_task_rejected(self):
        with self.assertRaises(DependencyError):
            plan_waves([PTask("a", verifiable=False)])

    def test_token_multiplier(self):
        waves = [["a", "b"], ["c"]]
        self.assertEqual(token_multiplier(waves), 1.5)


if __name__ == "__main__":
    unittest.main()
