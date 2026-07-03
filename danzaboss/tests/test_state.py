import os
import tempfile
import unittest

import _bootstrap  # noqa: F401
from danzaboss.kernel.state import StateManager, StateError, TeamState


class TestTeamState(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "team-state.json")
        self.mgr = StateManager(self.path)

    def test_init_relay_defaults(self):
        s = self.mgr.init(mode="relay", current_boss="claude")
        self.assertEqual(s.mode, "relay")
        self.assertEqual(s.max_features_per_turn, 2)
        self.assertTrue(os.path.exists(self.path))

    def test_continuous_has_no_cap(self):
        s = self.mgr.init(mode="continuous", current_boss="claude")
        self.assertIsNone(s.max_features_per_turn)

    def test_continuous_with_cap_is_invalid(self):
        s = TeamState(mode="continuous", max_features_per_turn=2)
        with self.assertRaises(StateError):
            s.validate()

    def test_turn_lock_blocks_wrong_actor(self):
        self.mgr.init(current_boss="claude")
        with self.assertRaises(StateError):
            self.mgr.transition(actor="codex", to_status="in_progress")

    def test_illegal_status_transition_rejected(self):
        self.mgr.init(current_boss="claude")  # status = ready
        with self.assertRaises(StateError):
            self.mgr.transition(to_status="done")  # ready -> done not allowed

    def test_legal_status_transition(self):
        self.mgr.init(current_boss="claude")
        s = self.mgr.transition(to_status="in_progress")
        self.assertEqual(s.status, "in_progress")

    def test_record_feature_flags_handoff_at_cap(self):
        self.mgr.init(mode="relay", current_boss="claude")
        self.mgr.transition(to_status="in_progress")
        s = self.mgr.record_feature(actor="claude")
        self.assertEqual(s.features_completed_this_turn, 1)
        self.assertFalse(s.handoff_required)
        s = self.mgr.record_feature(actor="claude")
        self.assertEqual(s.features_completed_this_turn, 2)
        self.assertTrue(s.handoff_required)  # cap reached

    def test_handoff_swaps_boss_and_increments_turn(self):
        self.mgr.init(mode="relay", current_boss="claude")
        self.mgr.transition(to_status="in_progress")
        s = self.mgr.handoff("codex")
        self.assertEqual(s.current_boss, "codex")
        self.assertEqual(s.previous_boss, "claude")
        self.assertEqual(s.turn_number, 1)
        self.assertEqual(s.features_completed_this_turn, 0)

    def test_unknown_field_rejected(self):
        self.mgr.init(current_boss="claude")
        with self.assertRaises(StateError):
            self.mgr.transition(nonsense=True)

    def test_atomic_write_leaves_no_tmp(self):
        self.mgr.init(current_boss="claude")
        self.assertFalse(os.path.exists(self.path + ".tmp"))


if __name__ == "__main__":
    unittest.main()


class TestTurnLockFailClosed(unittest.TestCase):
    """Regression for W1: fail-open turn lock allowed arbitrary boss reassignment."""

    def setUp(self):
        import tempfile as _t, os as _o
        self.mgr = StateManager(_o.path.join(_t.mkdtemp(), "s.json"))
        self.mgr.init(mode="relay", current_boss="claude")
        self.mgr.transition(to_status="in_progress")

    def test_cannot_reassign_boss_without_actor(self):
        with self.assertRaises(StateError):
            self.mgr.transition(current_boss="attacker")  # actor omitted -> must fail now

    def test_cannot_reassign_boss_as_wrong_actor(self):
        with self.assertRaises(StateError):
            self.mgr.transition(actor="attacker", current_boss="attacker")

    def test_current_boss_can_reassign(self):
        s = self.mgr.transition(actor="claude", current_boss="codex")
        self.assertEqual(s.current_boss, "codex")

    def test_nonprotected_field_still_ok_without_actor(self):
        s = self.mgr.transition(goal="new goal")  # non-ownership field, still allowed
        self.assertEqual(s.goal, "new goal")

    def test_handoff_requires_current_boss(self):
        with self.assertRaises(StateError):
            self.mgr.handoff("codex", actor="attacker")

    def test_handoff_by_current_boss_ok(self):
        s = self.mgr.handoff("codex", actor="claude")
        self.assertEqual(s.current_boss, "codex")
