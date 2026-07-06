"""W1-P4 conductor decisions: pure table over TeamState + Watch — the
postman's brain (design spec section 7). Valve and stall are the two
deterministic safety rails testable without any process machinery."""
import unittest

import _bootstrap  # noqa
from danzaboss.kernel.state import TeamState
from danzaboss.workstation.conductor import (DEAD_SESSION_VALVE,
                                             STALL_MINUTES, Action, Watch,
                                             decide, is_stalled,
                                             observe_session_end)


def state(**over):
    return TeamState(**{"mode": "relay", "current_boss": "claude",
                        "turn_number": 3, "status": "ready", **over})


def watch(**over):
    base = {"session_alive": False, "turn_at_ignite": None,
            "dead_sessions": 0, "last_change_monotonic": 0.0,
            "last_tail": ""}
    base.update(over)
    return Watch(**base)


class Decide(unittest.TestCase):
    def test_blocked_halts_regardless_of_session(self):
        for alive in (False, True):
            self.assertIs(decide(state(status="blocked"),
                                 watch(session_alive=alive)),
                          Action.HALT_BLOCKED)

    def test_done_stops(self):
        self.assertIs(decide(state(status="done"), watch()),
                      Action.STOP_DONE)

    def test_valve_trips_before_ignition(self):
        self.assertIs(decide(state(status="ready"),
                             watch(dead_sessions=DEAD_SESSION_VALVE)),
                      Action.STOP_VALVE)

    def test_ready_without_session_ignites(self):
        self.assertIs(decide(state(status="ready"), watch()), Action.IGNITE)

    def test_ready_with_live_session_waits(self):
        self.assertIs(decide(state(status="ready"),
                             watch(session_alive=True)), Action.WAIT)

    def test_in_progress_and_awaiting_handoff_wait_while_session_lives(self):
        for status in ("in_progress", "awaiting_handoff"):
            self.assertIs(decide(state(status=status),
                                 watch(session_alive=True)), Action.WAIT)

    def test_awaiting_handoff_with_dead_session_ignites_next_boss(self):
        # kernel handoff() leaves status awaiting_handoff as the departing
        # boss's final act; waiting here would deadlock the relay forever.
        self.assertIs(decide(state(status="awaiting_handoff"), watch()),
                      Action.IGNITE)

    def test_in_progress_with_dead_session_still_waits(self):
        # An orphaned turn is surfaced via the session_end log, not by
        # igniting over a turn someone may still own.
        self.assertIs(decide(state(status="in_progress"), watch()),
                      Action.WAIT)


class Valve(unittest.TestCase):
    def test_death_without_turn_advance_counts(self):
        w = watch(session_alive=True, turn_at_ignite=3)
        w = observe_session_end(state(turn_number=3), w)
        self.assertFalse(w.session_alive)
        self.assertEqual(w.dead_sessions, 1)

    def test_two_dead_sessions_trip_the_valve(self):
        w = watch(session_alive=True, turn_at_ignite=3, dead_sessions=1)
        w = observe_session_end(state(turn_number=3), w)
        self.assertEqual(w.dead_sessions, 2)
        self.assertIs(decide(state(status="ready"), w), Action.STOP_VALVE)

    def test_turn_advance_resets_the_counter(self):
        w = watch(session_alive=True, turn_at_ignite=3, dead_sessions=1)
        w = observe_session_end(state(turn_number=4), w)
        self.assertEqual(w.dead_sessions, 0)
        self.assertIs(decide(state(status="ready"), w), Action.IGNITE)


class Stall(unittest.TestCase):
    def test_below_threshold_is_not_a_stall(self):
        w = watch(session_alive=True, last_change_monotonic=100.0)
        self.assertFalse(is_stalled(w, 100.0 + STALL_MINUTES * 60 - 1))

    def test_at_threshold_is_a_stall(self):
        w = watch(session_alive=True, last_change_monotonic=100.0)
        self.assertTrue(is_stalled(w, 100.0 + STALL_MINUTES * 60))

    def test_dead_session_never_stalls(self):
        w = watch(session_alive=False, last_change_monotonic=0.0)
        self.assertFalse(is_stalled(w, 10_000_000.0))

    def test_custom_threshold(self):
        w = watch(session_alive=True, last_change_monotonic=0.0)
        self.assertTrue(is_stalled(w, 120.0, stall_minutes=2))
        self.assertFalse(is_stalled(w, 119.0, stall_minutes=2))


if __name__ == "__main__":
    unittest.main()
