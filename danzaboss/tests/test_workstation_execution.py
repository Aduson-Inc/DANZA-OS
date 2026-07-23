"""Phase 4.1 Task 5: production atomic-unit execution lifecycle."""
import json
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.kernel.state import StateManager
from danzaboss.workstation import execution, routing
from danzaboss.workstation.conductor import TEAM_STATE_RELPATH
from danzaboss.workstation.planner import PLAN_JSON_RELPATH
from danzaboss.workstation.runners import default_config, save_runners


def leaf(tid, *, kind="backend", depends_on=(), flags=(), verify="exit 0"):
    feature_id = int(tid.split("-")[0])
    return {
        "id": tid,
        "feature_id": feature_id,
        "description": f"implement {tid}",
        "kind": kind,
        "size_est": 10,
        "writes": ["src/x.py"],
        "depends_on": list(depends_on),
        "flags": list(flags),
        "verification": {"kind": "automated_test", "detail": verify},
    }


class ExecutionFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / ".danza" / "runtime").mkdir(parents=True)
        self.manager = StateManager(str(self.root / TEAM_STATE_RELPATH))
        self.manager.init(mode="relay", current_boss="claude",
                          max_features_per_turn=2)
        config = default_config({"claude": True, "codex": True})
        config["runners"]["claude"]["auth"] = "ok"
        config["runners"]["codex"]["auth"] = "ok"
        save_runners(self.root, config)
        # Sequential relay is the only routing model that ships (P T8a):
        # every specialist seat must equal the active boss, so seats stay
        # uniform here — route_turn selects by turn-number rotation, not
        # by seat.
        seats = {seat: "claude" for seat in routing.SEATS}
        seats["conductor"] = routing.BUILTIN_CONDUCTOR
        routing.save_routing(self.root, {
            "version": routing.SCHEMA_VERSION,
            "features_per_turn": 2,
            "lineup": ["claude", "codex"],
            "seats": seats,
        }, config)

    def write_plan(self, *units):
        order = [unit["id"] for unit in units]
        data = {
            "spec_ref": ".danza/features.json#revision-1",
            "tasks": list(units),
            "order": order,
            "execution": execution.initial_execution(order),
            "calibration": [],
        }
        path = self.root / PLAN_JSON_RELPATH
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def plan(self):
        return json.loads((self.root / PLAN_JSON_RELPATH).read_text(
            encoding="utf-8"))


class ProductionLifecycle(ExecutionFixture):
    def test_begin_unit_starts_only_the_dependency_ready_leaf(self):
        self.write_plan(leaf("71-A"), leaf("71-B", depends_on=("71-A",)))

        out = execution.begin_unit(
            self.root, self.manager, "claude", "71-A",
            started_at="2026-07-15T10:00:00+00:00")

        self.assertEqual(out["conclusion"], "continue")
        self.assertEqual(out["unit"]["status"], "in_progress")
        self.assertEqual(self.manager.load().status, "in_progress")
        with self.assertRaisesRegex(execution.ExecutionError,
                                    "next dependency-ready unit"):
            execution.begin_unit(self.root, self.manager, "claude", "71-B")

    def test_failed_verification_records_evidence_without_completion(self):
        self.write_plan(leaf("71-A", verify="exit 7"))
        execution.begin_unit(
            self.root, self.manager, "claude", "71-A",
            started_at="2026-07-15T10:00:00+00:00")

        out = execution.verify_unit(
            self.root, self.manager, "claude", "71-A",
            completed_at="2026-07-15T10:04:00+00:00")

        self.assertFalse(out["verification"]["passed"])
        self.assertEqual(out["verification"]["exit_code"], 7)
        self.assertEqual(out["unit"]["status"], "in_progress")
        self.assertEqual(out["unit"]["verification_attempts"], 1)
        self.assertEqual(self.manager.load().features_completed_this_turn, 0)
        self.assertEqual(self.manager.load().verified_unit_ids_this_turn, [])
        self.assertEqual(out["conclusion"], "continue")

    def test_passing_verification_records_evidence_timing_and_unit_id_once(self):
        self.write_plan(leaf("71-A"), leaf("71-B"), leaf("72-A", kind="test"))
        execution.begin_unit(
            self.root, self.manager, "claude", "71-A",
            started_at="2026-07-15T10:00:00+00:00")

        out = execution.verify_unit(
            self.root, self.manager, "claude", "71-A",
            completed_at="2026-07-15T10:14:30+00:00")

        self.assertTrue(out["verification"]["passed"])
        self.assertEqual(out["unit"]["status"], "completed")
        self.assertEqual(out["unit"]["actual_minutes"], 14.5)
        self.assertEqual(out["conclusion"], "continue")
        state = self.manager.load()
        self.assertEqual(state.features_completed_this_turn, 1)
        self.assertEqual(state.verified_unit_ids_this_turn, ["71-A"])
        plan = self.plan()
        self.assertEqual(plan["calibration"][0]["unit_id"], "71-A")
        self.assertEqual(plan["execution"]["71-A"]["verification_evidence"][0]
                         ["command"], "exit 0")

        record, state, counted = execution.record_verified_completion(
            self.root, self.manager, "claude", "71-A",
            actual_minutes=14.5,
            verification_evidence=out["verification"],
            completed_at="2026-07-15T10:14:30+00:00")
        self.assertFalse(counted)
        self.assertEqual(state.features_completed_this_turn, 1)
        self.assertEqual(len(record["verification_evidence"]), 1)

    def test_verify_retry_reconciles_completed_plan_before_conclusion(self):
        self.write_plan(leaf("71-A"))
        execution.begin_unit(
            self.root, self.manager, "claude", "71-A",
            started_at="2026-07-15T10:00:00+00:00")
        evidence = {
            "command": "exit 0", "passed": True, "exit_code": 0,
            "stdout_tail": "", "stderr_tail": "", "timed_out": False,
            "recorded_at": "2026-07-15T10:05:00+00:00",
        }
        data = self.plan()
        data["execution"]["71-A"].update({
            "status": "completed", "completed_at": evidence["recorded_at"],
            "actual_minutes": 5, "verification_attempts": 1,
            "verification_passed": True,
            "verification_evidence": [evidence], "completed_turn": 0,
        })
        data["calibration"].append({
            "unit_id": "71-A", "estimated_minutes": 10,
            "actual_minutes": 5, "variance_minutes": -5,
            "overrun": False, "recorded_at": evidence["recorded_at"],
        })
        (self.root / PLAN_JSON_RELPATH).write_text(json.dumps(data),
                                                   encoding="utf-8")

        out = execution.verify_unit(
            self.root, self.manager, "claude", "71-A")

        self.assertFalse(out["counted"])
        self.assertEqual(out["conclusion"], "no_work")
        self.assertEqual(self.manager.load().verified_unit_ids_this_turn,
                         ["71-A"])
        self.assertEqual(self.manager.load().status, "done")

    def test_blocking_active_unit_records_reason_and_explicit_conclusion(self):
        self.write_plan(leaf("71-A"))
        execution.begin_unit(self.root, self.manager, "claude", "71-A")

        out = execution.block_active_unit(
            self.root, self.manager, "claude", "71-A", "needs API key")

        self.assertEqual(out["conclusion"], "blocked")
        self.assertEqual(out["unit"]["blocker_reason"], "needs API key")
        self.assertEqual(self.manager.load().status, "blocked")


class TurnConclusions(ExecutionFixture):
    def test_no_work_concludes_done_from_ready(self):
        self.write_plan(leaf("71-A"))
        data = self.plan()
        data["execution"]["71-A"].update({
            "status": "completed",
            "started_at": "2026-07-15T10:00:00+00:00",
            "completed_at": "2026-07-15T10:05:00+00:00",
            "actual_minutes": 5,
            "verification_attempts": 1,
            "verification_passed": True,
            "verification_evidence": [{"passed": True}],
            "completed_turn": 0,
        })
        (self.root / PLAN_JSON_RELPATH).write_text(json.dumps(data),
                                                   encoding="utf-8")

        out = execution.apply_turn_conclusion(
            self.root, self.manager, "claude")

        self.assertEqual(out["conclusion"], "no_work")
        self.assertEqual(out["state"].status, "done")

    def test_quota_routes_next_ready_unit_and_hands_off(self):
        self.write_plan(leaf("71-A"), leaf("71-B"), leaf("72-A", kind="test"))
        self.manager.transition(
            actor="claude", to_status="in_progress",
            features_completed_this_turn=2,
            verified_unit_ids_this_turn=["71-A", "71-B"],
            handoff_required=True)
        data = self.plan()
        for unit_id in ("71-A", "71-B"):
            data["execution"][unit_id].update({
                "status": "completed", "started_at": "start",
                "completed_at": "done", "actual_minutes": 10,
                "verification_attempts": 1, "verification_passed": True,
                "verification_evidence": [{"passed": True}],
                "completed_turn": 0,
            })
        (self.root / PLAN_JSON_RELPATH).write_text(json.dumps(data),
                                                   encoding="utf-8")

        out = execution.apply_turn_conclusion(
            self.root, self.manager, "claude")

        self.assertEqual(out["conclusion"], "quota")
        self.assertEqual(out["state"].current_boss, "codex")
        self.assertEqual(out["state"].status, "awaiting_handoff")

    def test_dependency_dead_end_and_hard_stop_are_distinct(self):
        for expected, units in (
            ("blocked", (leaf("71-A", depends_on=("71-B",)),
                         leaf("71-B", depends_on=("71-A",)))),
            ("hard_stop", (leaf("71-A", flags=("auth",)),)),
        ):
            with self.subTest(expected=expected):
                # Cyclic plans are invalid at planning time, so model a
                # dependency dead-end with a blocked prerequisite instead.
                if expected == "blocked":
                    units = (leaf("71-A"), leaf("71-B", depends_on=("71-A",)))
                self.write_plan(*units)
                if expected == "blocked":
                    data = self.plan()
                    data["execution"]["71-A"]["status"] = "blocked"
                    data["execution"]["71-A"]["blocker_reason"] = "external"
                    (self.root / PLAN_JSON_RELPATH).write_text(
                        json.dumps(data), encoding="utf-8")
                out = execution.apply_turn_conclusion(
                    self.root, self.manager, "claude")
                self.assertEqual(out["conclusion"], expected)
                self.assertEqual(out["state"].status, "blocked")
                self.manager.transition(actor="claude", to_status="ready")


if __name__ == "__main__":
    unittest.main()
