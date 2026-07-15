import json
import os
import tempfile
import unittest
from pathlib import Path

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

    def test_relay_cap_accepts_only_integer_two_through_five(self):
        for value in range(2, 6):
            with self.subTest(value=value):
                TeamState(max_features_per_turn=value).validate()
        for value in (True, False, 1, 6, 2.5, "2", None):
            with self.subTest(value=value):
                with self.assertRaises(StateError):
                    TeamState(max_features_per_turn=value).validate()

    def test_schema_pins_relay_cap_range(self):
        path = Path(__file__).parents[1] / "kernel" / "team_state.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        cap = schema["properties"]["max_features_per_turn"]
        self.assertEqual(cap["minimum"], 2)
        self.assertEqual(cap["maximum"], 5)

    def test_init_relay_accepts_cap_override(self):
        s = self.mgr.init(mode="relay", current_boss="claude",
                          max_features_per_turn=5)
        self.assertEqual(s.max_features_per_turn, 5)

    def test_turn_lock_blocks_wrong_actor(self):
        self.mgr.init(current_boss="claude")
        with self.assertRaises(StateError):
            self.mgr.transition(actor="codex", to_status="in_progress")

    def test_illegal_status_transition_rejected(self):
        self.mgr.init(current_boss="claude")  # status = ready
        with self.assertRaises(StateError):
            self.mgr.transition(to_status="awaiting_handoff")

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

    def test_handoff_omitted_cap_retains_active_turn_snapshot(self):
        self.mgr.init(mode="relay", current_boss="claude",
                      max_features_per_turn=4)
        self.mgr.transition(to_status="in_progress")
        s = self.mgr.handoff("codex")
        self.assertEqual(s.max_features_per_turn, 4)

    def test_handoff_supplied_cap_updates_snapshot_and_resets_counter(self):
        self.mgr.init(mode="relay", current_boss="claude",
                      max_features_per_turn=4)
        self.mgr.transition(to_status="in_progress")
        self.mgr.record_feature(actor="claude")
        s = self.mgr.handoff("codex", max_features_per_turn=3)
        self.assertEqual(s.max_features_per_turn, 3)
        self.assertEqual(s.features_completed_this_turn, 0)

    def test_invalid_handoff_cap_leaves_state_unchanged(self):
        self.mgr.init(mode="relay", current_boss="claude",
                      max_features_per_turn=4)
        self.mgr.transition(to_status="in_progress")
        before = self.mgr.load().to_json()
        with self.assertRaises(StateError):
            self.mgr.handoff("codex", max_features_per_turn=True)
        self.assertEqual(self.mgr.load().to_json(), before)

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
