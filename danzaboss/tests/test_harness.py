import unittest
import _bootstrap  # noqa
from danzaboss.selftest.harness import run_cold_start


class TestHarness(unittest.TestCase):
    def test_cold_start_all_pass(self):
        rep = run_cold_start()
        failed = [c.name for c in rep.checks if not c.passed]
        self.assertTrue(rep.ok, f"cold-start checks failed: {failed}")

    def test_has_expected_checks(self):
        rep = run_cold_start()
        names = {c.name for c in rep.checks}
        for expected in ("turn_lock_enforced", "unverifiable_task_blocked",
                         "hard_stop_enforced", "relay_cycle_hands_off",
                         "continue_mode_ownership"):
            self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main()
