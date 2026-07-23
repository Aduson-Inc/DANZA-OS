"""P4 Task 7 — mock-runner relay integration proof (no AI spend, CI-able).

One deterministic test proving the full relay contract end to end, the way
the live system runs it: the conductor ignites a boss, the boss works its
turn through the same public execution API `danza unit` subcommands use
(``begin_unit`` / ``verify_unit`` / ``apply_turn_conclusion`` via CLI-style
routing), and control returns to the conductor to route the next boss —
until the plan is done. No real AI CLI is launched; ``ScriptedHost`` plays
the boss synchronously inside ``ignite()`` instead of spawning a process.

Fixture: 4 atomic leaves across 2 plan sections ("features"), quota 2
verified units/turn, a 2-runner sequential lineup (claude, codex) so the
boss alternates strictly by turn number, and a CORTEX store seeded with a
few observations so the turn brief's knowledge section has content.

While building this fixture, a real defect surfaced and was fixed
separately in ``workstation/execution.py`` (see ``ExecutionFixture``
docstring below) — `apply_turn_conclusion`'s automatic ``next_boss`` lookup
used the *pre-handoff* turn number for turn-number-dependent routing
(sequential boss_mode, and the seat_routed builtin/missing-seat fallback),
which handed the turn right back to the departing boss instead of rotating
to the next lineup member. That mismatch is exactly what this end-to-end
test is designed to catch and did.
"""
import json
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.cortex.events import CaptureLog
from danzaboss.cortex.factory import db_path, open_store
from danzaboss.cortex.identity import resolve_project
from danzaboss.cortex.observation import Observation
from danzaboss.kernel.state import StateManager
from danzaboss.workstation import execution as execution_mod
from danzaboss.workstation import planner as planner_mod
from danzaboss.workstation import routing as routing_mod
from danzaboss.workstation import runners as runners_mod
from danzaboss.workstation import turnbrief as turnbrief_mod
from danzaboss.workstation.conductor import (Action, Conductor, LOG_RELPATH,
                                             TEAM_STATE_RELPATH)

VERIFY_CMD = 'python3 -c "pass"'


def _leaf(tid: str, kind: str) -> dict:
    return {"id": tid, "description": f"implement {tid}", "kind": kind,
            "size_est": 10, "writes": [f"src/{tid}.py"],
            "verification": {"kind": "automated_test", "detail": VERIFY_CMD}}


def _plan_payload() -> dict:
    """4 atomic leaves across 2 sections ("features"), all independently
    ready (no depends_on), so execution order alone decides the pick: turn
    0 gets 1.1/1.2, turn 1 gets 2.1/2.2 — exactly the quota-2 boundary."""
    return {
        "spec_ref": "spec.md",
        "tasks": [
            {"id": "1", "description": "feature one",
             "subtasks": [_leaf("1.1", "backend"), _leaf("1.2", "design")]},
            {"id": "2", "description": "feature two",
             "subtasks": [_leaf("2.1", "test"), _leaf("2.2", "backend")]},
        ],
        "order": ["1.1", "1.2", "2.1", "2.2"],
    }


class ScriptedHost:
    """Mock CLI host: ``ignite()`` plays the routed boss synchronously
    through the same public execution API a real ``danza unit`` CLI call
    uses (``begin_unit`` / ``verify_unit``), completing exactly the turn's
    quota, then exits (``alive_now`` flips False) — mirroring a real
    session's full lifecycle without spawning a process or spending AI.
    """

    def __init__(self, root: Path, manager: StateManager):
        self._root = root
        self._manager = manager
        self.ignites: list[tuple[str, str, list[str]]] = []
        self.runners: list[str | None] = []
        self.alive_now = False
        self.tail_now = ""
        self.killed: list[str] = []
        self.brief_snapshots: list[str] = []
        self.executed_units: list[list[str]] = []
        # Populated only on the first ignite (assertion 5): the refused
        # over-quota attempt's error, plus ledger/state snapshots taken
        # immediately afterward to prove it left no corruption.
        self.overquota_error: Exception | None = None
        self.post_overquota_execution: dict | None = None
        self.post_overquota_state = None

    def ignite(self, name, cwd, argv, runner=None):
        turn_index = len(self.ignites)
        self.ignites.append((name, str(cwd), list(argv)))
        self.runners.append(runner)

        brief_path = Path(self._root) / turnbrief_mod.TURN_BRIEF_RELPATH
        self.brief_snapshots.append(brief_path.read_text(encoding="utf-8"))

        actor = runner
        quota = self._manager.load().max_features_per_turn
        completed_ids: list[str] = []
        for i in range(quota):
            plan_data = execution_mod.load_execution_plan(self._root)
            selection = execution_mod.next_ready_unit(plan_data)
            assert selection is not None, "fixture ran out of ready work"
            unit_id = selection.id
            started_at = f"2026-07-15T10:{i:02d}:00+00:00"
            completed_at = f"2026-07-15T10:{i:02d}:30+00:00"
            execution_mod.begin_unit(self._root, self._manager, actor,
                                     unit_id, started_at=started_at)
            execution_mod.verify_unit(self._root, self._manager, actor,
                                      unit_id, completed_at=completed_at)
            completed_ids.append(unit_id)
        self.executed_units.append(completed_ids)

        if turn_index == 0:
            # verify_unit's LAST call above already ran the auto-conclude
            # (apply_turn_conclusion) synchronously and, on hitting quota,
            # atomically handed the turn to the next boss — so by the time
            # control returns here, `actor` (turn 0's boss) no longer owns
            # the turn. The execution layer refuses via its turn-lock guard
            # rather than a bare "quota" message; that is the real refusal
            # an over-eager boss hits in production (ownership is checked
            # before any per-turn unit count), and it is exactly as
            # fail-closed as a literal quota check would be.
            try:
                plan_data = execution_mod.load_execution_plan(self._root)
                selection = execution_mod.next_ready_unit(plan_data)
                execution_mod.begin_unit(self._root, self._manager, actor,
                                         selection.id)
            except execution_mod.ExecutionError as exc:
                self.overquota_error = exc
            self.post_overquota_execution = execution_mod.execution_records(
                execution_mod.load_execution_plan(self._root))
            self.post_overquota_state = self._manager.load()

        self.alive_now = False  # session exits once its scripted turn ends

    def alive(self, name):
        return self.alive_now

    def tail(self, name, lines=40):
        return self.tail_now

    def kill(self, name):
        self.killed.append(name)


class RelayIntegration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / ".danza" / "runtime").mkdir(parents=True)

        config = runners_mod.default_config({"claude": True, "codex": True})
        config["runners"]["claude"]["auth"] = "ok"
        config["runners"]["codex"]["auth"] = "ok"
        runners_mod.save_runners(self.root, config)
        seats = {seat: "claude" for seat in routing_mod.SEAT_WORK_TYPES}
        seats["conductor"] = routing_mod.BUILTIN_CONDUCTOR
        routing_mod.save_routing(
            self.root, {"version": routing_mod.SCHEMA_VERSION,
                        "features_per_turn": 2, "boss_mode": "sequential",
                        "lineup": ["claude", "codex"], "seats": seats},
            config)

        (self.root / planner_mod.PLAN_JSON_RELPATH).write_text(
            json.dumps(_plan_payload()), encoding="utf-8")

        self.manager = StateManager(str(self.root / TEAM_STATE_RELPATH))
        self.manager.init(mode="relay", current_boss="claude",
                          max_features_per_turn=2)

        self.project = resolve_project(str(self.root))
        store = open_store(str(self.root))
        for title, summary in [
            ("Auth uses bcrypt cost 12", "cost factor 12 chosen for hashing"),
            ("Relay runs sequential boss mode",
             "team confirmed strict claude/codex rotation"),
            ("Verification commands stay trivial",
             "unit verify commands must run in well under a second"),
        ]:
            store.upsert(Observation(title=title, summary=summary,
                                     type="impl_detail", project=self.project,
                                     concepts=["relay"], tags=["relay"]))

        self.host = ScriptedHost(self.root, self.manager)
        self.conductor = Conductor(self.root, self.host,
                                   clock=lambda: 1000.0,
                                   sleep=lambda s: None, poll_interval=0.0)

    def _log_events(self) -> list[dict]:
        path = self.root / LOG_RELPATH
        if not path.exists():
            return []
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines()]

    def test_full_relay_completes_end_to_end(self):
        action = self.conductor.run(max_ticks=6)

        # 1. Relay completes: final team-state done, conductor STOP_DONE.
        final_state = self.manager.load()
        self.assertEqual(final_state.status, "done")
        self.assertIs(action, Action.STOP_DONE)

        # 2. Two turns for 4 units at quota 2: boss order alternates per
        # the sequential lineup, turn_number advances 0 -> 1.
        ignite_events = [e for e in self._log_events()
                         if e["event"] == "ignite"]
        self.assertEqual(len(ignite_events), 2)
        self.assertEqual([e["runner"] for e in ignite_events],
                         ["claude", "codex"])
        self.assertEqual([e["turn_number"] for e in ignite_events], [0, 1])
        self.assertEqual(self.host.runners, ["claude", "codex"])

        # 3. Turn brief present at every ignite, listing exactly the units
        # that boss then executed, the "## Your turn" header, and the
        # rendered CORTEX knowledge section.
        self.assertEqual(len(self.host.brief_snapshots), 2)
        self.assertEqual(self.host.executed_units,
                         [["1.1", "1.2"], ["2.1", "2.2"]])
        for snapshot, unit_ids in zip(self.host.brief_snapshots,
                                      self.host.executed_units):
            self.assertIn("## Your turn", snapshot)
            self.assertIn("## What the team already knows", snapshot)
            for unit_id in unit_ids:
                self.assertIn(f"`{unit_id}`", snapshot)
            self.assertIn("Auth uses bcrypt cost 12", snapshot)

        # 4. Every completed unit has passing verification evidence
        # (command, exit_code 0, timing) in the plan.json ledger itself.
        records = execution_mod.execution_records(
            execution_mod.load_execution_plan(self.root))
        for unit_id in ("1.1", "1.2", "2.1", "2.2"):
            record = records[unit_id]
            self.assertEqual(record["status"], "completed")
            self.assertTrue(record["verification_passed"])
            evidence = record["verification_evidence"][-1]
            self.assertEqual(evidence["command"], VERIFY_CMD)
            self.assertEqual(evidence["exit_code"], 0)
            self.assertTrue(evidence["passed"])
            self.assertIsInstance(record["actual_minutes"], (int, float))
            self.assertGreaterEqual(record["actual_minutes"], 0)

        # 5. Exceeding quota mid-relay (one extra begin_unit scripted right
        # after turn 0's quota is met) is refused, and the refusal leaves
        # no corruption: the ledger still shows exactly 1.1/1.2 completed
        # and 2.1 untouched (still pending), and team-state cleanly reflects
        # the codex turn that already started (see ScriptedHost docstring
        # for why the refusal is a turn-lock error, not a bare "quota" one).
        self.assertIsInstance(self.host.overquota_error,
                              execution_mod.ExecutionError)
        snapshot = self.host.post_overquota_execution
        self.assertEqual(snapshot["1.1"]["status"], "completed")
        self.assertEqual(snapshot["1.2"]["status"], "completed")
        self.assertEqual(snapshot["2.1"]["status"], "pending")
        self.assertIsNone(snapshot["2.1"]["started_at"])
        state_after = self.host.post_overquota_state
        self.assertEqual(state_after.current_boss, "codex")
        self.assertEqual(state_after.turn_number, 1)
        self.assertEqual(state_after.features_completed_this_turn, 0)
        self.assertEqual(state_after.verified_unit_ids_this_turn, [])

        # 6. CaptureLog has one context-read telemetry row per turn for the
        # boss driver.
        log = CaptureLog(db_path(str(self.root)))
        stats = log.context_read_stats(self.project)
        self.assertIn(turnbrief_mod.BOSS_DRIVER, stats)
        self.assertEqual(stats[turnbrief_mod.BOSS_DRIVER]["reads"], 2)

        # 7. No stray .tmp leftovers under .danza/runtime.
        runtime_dir = self.root / ".danza" / "runtime"
        leftovers = list(runtime_dir.rglob("*.tmp"))
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
