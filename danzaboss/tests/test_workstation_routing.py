"""Tests for danzaboss.workstation.routing — deterministic seat router.

Covers the P4 T3 contract plus Task 5 ledger routing: strengths-based seat
suggestion, fail-closed routing.json validation, save/load round-trip, and
the pure next_boss decision for the first dependency-ready unit.
"""
import _bootstrap  # noqa
import json
import tempfile
import unittest
from pathlib import Path

from danzaboss.kernel.state import TeamState
from danzaboss.workstation import execution
from danzaboss.workstation.routing import (
    BUILTIN_CONDUCTOR,
    DEFAULT_FEATURES_PER_TURN,
    KIND_TO_WORK_TYPE,
    MAX_FEATURES_PER_TURN,
    MIN_FEATURES_PER_TURN,
    ROUTING_RELPATH,
    SCHEMA_VERSION,
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
    return {"version": SCHEMA_VERSION, "features_per_turn": 2,
            "lineup": lineup, "seats": seats}


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

    data = {
        "spec_ref": "spec.md",
        "tasks": [
            {"id": "1", "description": "section one",
             "subtasks": [leaf("1.1", first_kind), leaf("1.2", "design")]},
            {"id": "2", "description": "section two",
             "subtasks": [leaf("2.1", "test")]},
        ],
        "order": ["1.1", "1.2", "2.1"],
    }
    data["execution"] = execution.initial_execution(data["order"])
    data["calibration"] = []
    return data


def _completed(plan: dict, *unit_ids: str) -> dict:
    for unit_id in unit_ids:
        plan["execution"][unit_id].update({
            "status": "completed", "started_at": "start",
            "completed_at": "done", "actual_minutes": 1,
            "verification_attempts": 1, "verification_passed": True,
            "verification_evidence": [{"passed": True}],
            "completed_turn": 0,
        })
    return plan


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

    def test_unprobed_runner_is_not_seated(self):
        cfg = _config({"claude": "unprobed"})
        with self.assertRaises(RoutingError):
            suggest_seats(cfg)

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
        for version in (True, 1, 2.0, 3):
            with self.subTest(version=version):
                routing = _routing(["claude"], _full_seats("claude"))
                routing["version"] = version
                with self.assertRaises(RoutingError):
                    validate_routing(routing, self.cfg)

    def test_features_per_turn_contract(self):
        self.assertEqual(SCHEMA_VERSION, 2)
        self.assertEqual(DEFAULT_FEATURES_PER_TURN, 2)
        self.assertEqual(MIN_FEATURES_PER_TURN, 2)
        self.assertEqual(MAX_FEATURES_PER_TURN, 5)
        for value in range(2, 6):
            routing = _routing(["claude"], _full_seats("claude"))
            routing["features_per_turn"] = value
            self.assertEqual(validate_routing(routing, self.cfg), routing)

    def test_rejects_missing_boolean_and_out_of_range_features_per_turn(self):
        for value in (None, True, False, 1, 6, 2.5, "2"):
            with self.subTest(value=value):
                routing = _routing(["claude"], _full_seats("claude"))
                if value is None:
                    del routing["features_per_turn"]
                else:
                    routing["features_per_turn"] = value
                with self.assertRaises(RoutingError):
                    validate_routing(routing, self.cfg)

    def test_rejects_six_runner_lineup(self):
        lineup = ["claude", "codex", "gemini", "grok", "opencode", "generic"]
        routing = _routing(lineup, _full_seats("claude"))
        with self.assertRaises(RoutingError):
            validate_routing(routing, self.cfg)

    def test_rejects_five_runner_lineup(self):
        lineup = ["claude", "codex", "gemini", "grok", "opencode"]
        cfg = _config(dict.fromkeys(lineup, "ok"))
        routing = _routing(lineup, _full_seats("claude"))
        with self.assertRaisesRegex(RoutingError, "1-4"):
            validate_routing(routing, cfg)

    def test_rejects_duplicate_lineup_names(self):
        routing = _routing(["claude", "claude"], _full_seats("claude"))
        with self.assertRaises(RoutingError):
            validate_routing(routing, self.cfg)

    def test_rejects_unauthenticated_lineup_member(self):
        cfg = _config({"claude": "ok", "codex": "unauthenticated"})
        routing = _routing(["claude", "codex"], _full_seats("claude"))
        with self.assertRaises(RoutingError):
            validate_routing(routing, cfg)

    def test_rejects_unprobed_lineup_member(self):
        cfg = _config({"claude": "ok", "codex": "unprobed"})
        routing = _routing(["claude", "codex"], _full_seats("claude"))
        with self.assertRaisesRegex(RoutingError, "not been verified"):
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

    def test_rejects_seat_routed_boss_mode(self):
        # Sequential relay is the only routing model that ships (P T8a).
        routing = _routing(["claude"], _full_seats("claude"))
        routing["boss_mode"] = "seat_routed"
        with self.assertRaises(RoutingError):
            validate_routing(routing, self.cfg)

    def test_missing_boss_mode_defaults_to_sequential_and_is_enforced(self):
        # No boss_mode key (legacy shape) still gets the sequential-only
        # rule: every specialist seat must equal the active boss.
        routing = _routing(["claude", "codex"],
                           _full_seats("claude", qa="codex"))
        with self.assertRaisesRegex(RoutingError, "sequential boss mode"):
            validate_routing(routing, self.cfg)


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

    def test_load_normalizes_exact_legacy_v1_without_rewriting(self):
        cfg = _config({"claude": "ok"})
        legacy = {"version": 1, "lineup": ["claude"],
                  "seats": _full_seats("claude")}
        with tempfile.TemporaryDirectory() as root:
            save_runners(root, cfg)
            path = Path(root) / ROUTING_RELPATH
            path.parent.mkdir(parents=True, exist_ok=True)
            original = json.dumps(legacy, separators=(",", ":"))
            path.write_text(original, encoding="utf-8")

            loaded = load_routing(root)

            self.assertEqual(loaded, {**legacy, "version": 2,
                                     "features_per_turn": 2})
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_load_rejects_non_exact_legacy_and_other_versions(self):
        cfg = _config({"claude": "ok"})
        base = {"lineup": ["claude"], "seats": _full_seats("claude")}
        for raw in ({"version": 0, **base},
                    {"version": True, **base},
                    {"version": 3, **base},
                    {"version": 1, "features_per_turn": 2, **base},
                    {"version": 1, "unexpected": True, **base}):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as root:
                save_runners(root, cfg)
                path = Path(root) / ROUTING_RELPATH
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(raw), encoding="utf-8")
                with self.assertRaises(RoutingError):
                    load_routing(root)

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
    """Pure routing decision: ready unit -> kind -> work type -> turn slot.

    Sequential relay is the only routing model that ships (P T8a): the
    runner is always ``lineup[turn_number % len(lineup)]``. The 'seats' map
    is shape-validated only — route_turn/next_boss never consult it."""

    ROUTING = {"version": SCHEMA_VERSION, "features_per_turn": 2,
               "lineup": ["claude", "codex"],
               "seats": _full_seats("claude")}

    def test_kind_table_hit(self):
        state = TeamState(turn_number=0)
        self.assertEqual(next_boss(self.ROUTING, _plan(), state), "claude")

    def test_rotates_to_next_lineup_member_on_next_turn(self):
        state = TeamState(turn_number=1)
        plan = _completed(_plan(), "1.1", "1.2")
        self.assertEqual(next_boss(self.ROUTING, plan, state), "codex")

    def test_completed_plan_has_no_route_instead_of_cursor_clamp(self):
        state = TeamState(turn_number=9)
        with self.assertRaisesRegex(RoutingError, "no dependency-ready"):
            next_boss(self.ROUTING,
                      _completed(_plan(), "1.1", "1.2", "2.1"), state)

    def test_seat_assignments_are_never_consulted(self):
        # A stale/hand-edited seat map claims "codex" owns qa work — proof
        # that route_turn ignores it and rotates by turn number instead.
        routing = {"version": SCHEMA_VERSION, "features_per_turn": 2,
                   "lineup": ["claude", "codex"],
                   "seats": {**{s: "claude" for s in SEATS}, "qa": "codex"}}
        state = TeamState(turn_number=0)
        self.assertEqual(
            next_boss(routing, _completed(_plan(), "1.1", "1.2"), state),
            "claude")  # lineup[0 % 2], NOT the seat's "codex"

    def test_sequential_boss_mode_ignores_specialist_seats(self):
        routing = {"version": SCHEMA_VERSION, "features_per_turn": 2,
                   "boss_mode": "sequential",
                   "lineup": ["claude", "codex"],
                   "seats": _full_seats("claude")}
        for turn, expected in ((0, "claude"), (1, "codex"), (2, "claude")):
            with self.subTest(turn=turn):
                self.assertEqual(
                    next_boss(routing, _plan(), TeamState(turn_number=turn)),
                    expected)

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
