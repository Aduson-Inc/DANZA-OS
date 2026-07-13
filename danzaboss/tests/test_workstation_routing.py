"""Tests for danzaboss.workstation.routing — deterministic seat router.

Covers the P4 T3 contract: strengths-based seat suggestion, fail-closed
routing.json validation, save/load round-trip, and the pure next_boss
decision (kind table hit, rotation fallback, cursor clamp, unknown kind).
"""
import _bootstrap  # noqa
import json
import tempfile
import unittest
from pathlib import Path

from danzaboss.kernel.state import TeamState
from danzaboss.workstation.routing import (
    BUILTIN_CONDUCTOR,
    KIND_TO_WORK_TYPE,
    ROUTING_RELPATH,
    SEAT_WORK_TYPES,
    SEATS,
    RoutingError,
    load_routing,
    next_boss,
    save_routing,
    suggest_seats,
    validate_routing,
)
from danzaboss.workstation.runners import default_config, save_runners


def _config(auth_by_name: dict[str, str]) -> dict:
    """Runner config with exactly the named runners detected, each stamped
    with the given auth status; everything else stays undetected."""
    detected = {name: True for name in auth_by_name}
    cfg = default_config(detected)
    for name, auth in auth_by_name.items():
        cfg["runners"][name]["auth"] = auth
    return cfg


def _routing(lineup: list[str], seats: dict) -> dict:
    return {"version": 1, "lineup": lineup, "seats": seats}


def _full_seats(runner: str, **overrides: str) -> dict:
    seats = {seat: runner for seat in SEATS}
    seats["conductor"] = BUILTIN_CONDUCTOR
    seats.update(overrides)
    return seats


# Minimal valid plan.json payload (planner.plan_payload shape). Features
# (first two id segments) in execution order: 1.1, 1.2, 2.1.
def _plan(first_kind: str = "backend") -> dict:
    def leaf(tid: str, kind: str) -> dict:
        return {"id": tid, "description": f"do {tid}", "kind": kind,
                "size_est": 10, "writes": ["x"],
                "verification": {"kind": "automated_test",
                                 "detail": "pytest tests/x.py"}}

    return {
        "spec_ref": "spec.md",
        "tasks": [
            {"id": "1", "description": "section one",
             "subtasks": [leaf("1.1", first_kind), leaf("1.2", "design")]},
            {"id": "2", "description": "section two",
             "subtasks": [leaf("2.1", "test")]},
        ],
        "order": ["1.1", "1.2", "2.1"],
    }


class TestSuggestSeats(unittest.TestCase):
    """Strengths-based suggestion: all 9 seats, deterministic, fail-closed."""

    def test_fills_all_nine_seats_from_strengths(self):
        cfg = _config({"claude": "ok", "codex": "ok", "gemini": "ok"})
        seats = suggest_seats(cfg)
        self.assertEqual(set(seats), set(SEATS))
        self.assertEqual(seats["conductor"], BUILTIN_CONDUCTOR)
        self.assertEqual(seats["plan"], "claude")     # lists "plan"
        self.assertEqual(seats["build"], "claude")    # first lister wins
        self.assertEqual(seats["map"], "gemini")      # only lister
        self.assertEqual(seats["qa"], "codex")        # first lister
        self.assertEqual(seats["research"], "gemini")
        # nobody connected lists "design" -> first connected runner
        self.assertEqual(seats["design"], "claude")

    def test_deterministic(self):
        cfg = _config({"claude": "ok", "codex": "unprobed"})
        self.assertEqual(suggest_seats(cfg), suggest_seats(cfg))

    def test_unauthenticated_runner_never_seated(self):
        cfg = _config({"claude": "unauthenticated", "codex": "ok"})
        seats = suggest_seats(cfg)
        for work_type in SEAT_WORK_TYPES:
            self.assertEqual(seats[work_type], "codex")

    def test_nothing_connected_raises(self):
        with self.assertRaises(RoutingError):
            suggest_seats(_config({}))
        with self.assertRaises(RoutingError):
            suggest_seats(_config({"claude": "unauthenticated"}))


class TestValidateRouting(unittest.TestCase):
    """Fail-closed validation against the live runner config."""

    def setUp(self):
        self.cfg = _config({"claude": "ok", "codex": "ok"})

    def test_accepts_valid_routing(self):
        routing = _routing(["claude", "codex"], _full_seats("claude"))
        self.assertEqual(validate_routing(routing, self.cfg), routing)

    def test_rejects_wrong_version(self):
        routing = _routing(["claude"], _full_seats("claude"))
        routing["version"] = 2
        with self.assertRaises(RoutingError):
            validate_routing(routing, self.cfg)

    def test_rejects_six_runner_lineup(self):
        lineup = ["claude", "codex", "gemini", "grok", "opencode", "generic"]
        routing = _routing(lineup, _full_seats("claude"))
        with self.assertRaises(RoutingError):
            validate_routing(routing, self.cfg)

    def test_rejects_duplicate_lineup_names(self):
        routing = _routing(["claude", "claude"], _full_seats("claude"))
        with self.assertRaises(RoutingError):
            validate_routing(routing, self.cfg)

    def test_rejects_unauthenticated_lineup_member(self):
        cfg = _config({"claude": "ok", "codex": "unauthenticated"})
        routing = _routing(["claude", "codex"], _full_seats("claude"))
        with self.assertRaises(RoutingError):
            validate_routing(routing, cfg)

    def test_rejects_undetected_lineup_member(self):
        routing = _routing(["claude", "gemini"], _full_seats("claude"))
        with self.assertRaises(RoutingError):
            validate_routing(routing, self.cfg)

    def test_rejects_missing_seat_key(self):
        seats = _full_seats("claude")
        del seats["design"]
        routing = _routing(["claude"], seats)
        with self.assertRaises(RoutingError):
            validate_routing(routing, self.cfg)

    def test_rejects_non_lineup_seat_value(self):
        routing = _routing(["claude"], _full_seats("claude", qa="codex"))
        with self.assertRaises(RoutingError):
            validate_routing(routing, self.cfg)

    def test_rejects_builtin_on_non_conductor_seat(self):
        routing = _routing(
            ["claude"], _full_seats("claude", build=BUILTIN_CONDUCTOR))
        with self.assertRaises(RoutingError):
            validate_routing(routing, self.cfg)

    def test_conductor_may_be_lineup_member(self):
        routing = _routing(
            ["claude"], _full_seats("claude", conductor="claude"))
        self.assertEqual(validate_routing(routing, self.cfg), routing)


class TestPersistence(unittest.TestCase):
    """save/load in the save_runners/load_runners idiom."""

    def test_round_trip(self):
        cfg = _config({"claude": "ok"})
        routing = _routing(["claude"], _full_seats("claude"))
        with tempfile.TemporaryDirectory() as root:
            save_runners(root, cfg)
            path = save_routing(root, routing, cfg)
            self.assertEqual(path, Path(root) / ROUTING_RELPATH)
            self.assertEqual(load_routing(root), routing)

    def test_save_validates_first(self):
        cfg = _config({"claude": "ok"})
        routing = _routing(["codex"], _full_seats("codex"))  # not detected
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(RoutingError):
                save_routing(root, routing, cfg)
            self.assertFalse((Path(root) / ROUTING_RELPATH).exists())

    def test_missing_file_message_points_at_setup(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(RoutingError) as ctx:
                load_routing(root)
            self.assertIn("SETUP", str(ctx.exception))

    def test_invalid_json_raises(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / ROUTING_RELPATH
            path.parent.mkdir(parents=True)
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(RoutingError):
                load_routing(root)


class TestNextBoss(unittest.TestCase):
    """Pure routing decision: cursor -> kind -> work type -> seat."""

    ROUTING = {"version": 1, "lineup": ["claude", "codex"],
               "seats": {**{s: "claude" for s in SEATS},
                         "conductor": BUILTIN_CONDUCTOR, "qa": "codex"}}

    def test_kind_table_hit(self):
        # turn 0, 2 features/turn -> cursor 0 -> feature 1.1, kind backend
        # -> work type build -> seat claude
        state = TeamState(turn_number=0)
        self.assertEqual(next_boss(self.ROUTING, _plan(), state), "claude")

    def test_second_turn_lands_on_qa_seat(self):
        # turn 1 -> cursor 2 -> feature 2.1, kind test -> qa -> codex
        state = TeamState(turn_number=1)
        self.assertEqual(next_boss(self.ROUTING, _plan(), state), "codex")

    def test_cursor_clamps_at_plan_end(self):
        # turn 9 -> cursor 18, clamped to last feature 2.1 -> qa -> codex
        state = TeamState(turn_number=9)
        self.assertEqual(next_boss(self.ROUTING, _plan(), state), "codex")

    def test_builtin_seat_falls_back_to_rotation(self):
        # Hand-edited file: qa seat says "builtin" -> rotation by turn.
        routing = {"version": 1, "lineup": ["claude", "codex"],
                   "seats": {**{s: "claude" for s in SEATS},
                             "qa": BUILTIN_CONDUCTOR}}
        state = TeamState(turn_number=1)  # feature 2.1 -> qa -> fallback
        self.assertEqual(next_boss(routing, _plan(), state),
                         routing["lineup"][1 % 2])

    def test_missing_seat_value_falls_back_to_rotation(self):
        routing = {"version": 1, "lineup": ["claude", "codex"],
                   "seats": {s: "claude" for s in SEATS if s != "qa"}}
        state = TeamState(turn_number=2)  # cursor clamps to 2.1 -> qa
        self.assertEqual(next_boss(routing, _plan(), state),
                         routing["lineup"][2 % 2])

    def test_unknown_kind_raises(self):
        state = TeamState(turn_number=0)
        with self.assertRaises(RoutingError):
            next_boss(self.ROUTING, _plan(first_kind="weird"), state)


class TestVocabulary(unittest.TestCase):
    """The pinned seat vocabulary and kind map are exactly as specced."""

    def test_seats(self):
        self.assertEqual(SEAT_WORK_TYPES,
                         ("plan", "build", "map", "qa", "review",
                          "research", "design", "security"))
        self.assertEqual(SEATS, ("conductor",) + SEAT_WORK_TYPES)
        self.assertEqual(BUILTIN_CONDUCTOR, "builtin")

    def test_kind_map_covers_all_task_kinds(self):
        from danzaboss.planning.decompose import TASK_KINDS
        self.assertEqual(set(KIND_TO_WORK_TYPE), set(TASK_KINDS))
        self.assertTrue(
            set(KIND_TO_WORK_TYPE.values()) <= set(SEAT_WORK_TYPES))


if __name__ == "__main__":
    unittest.main()
