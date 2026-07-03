import unittest
import _bootstrap  # noqa
from danzaboss.hooks.gates import distillation_gate


class TestDistillationGate(unittest.TestCase):
    def test_blocks_when_events_pending_and_nothing_distilled(self):
        d = distillation_gate(pending_events=7, observations_written=0,
                              already_blocked=False)
        self.assertFalse(d.allow)
        self.assertIn("7", d.reason)
        self.assertIn("danza cortex observe", d.reason)

    def test_passes_when_observations_written(self):
        self.assertTrue(distillation_gate(7, 2, False).allow)

    def test_passes_when_no_pending_events(self):
        self.assertTrue(distillation_gate(0, 0, False).allow)

    def test_blocks_at_most_once(self):
        # second stop after a block must pass (loop safety, Rule 18 spirit)
        self.assertTrue(distillation_gate(7, 0, True).allow)


if __name__ == "__main__":
    unittest.main()
