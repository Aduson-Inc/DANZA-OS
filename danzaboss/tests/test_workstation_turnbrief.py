"""P4.1 T4 — turn-brief compiler: informs the incoming boss before ignition.

Every ignited boss used to start blind and re-explore the repo by hand. The
conductor now compiles ``.danza/runtime/turn-brief.md`` before ignite: 1) your
turn (quota/stop rule), 2) assigned units (dependency-ready, up to quota),
3) last turn (what the previous boss finished), 4) a role-budgeted CORTEX
package. Section 4 must NEVER be able to block a turn: any cortex exception
degrades to a one-line fallback, sections 1-3 stay intact regardless.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _bootstrap  # noqa
from danzaboss.kernel.state import TeamState
from danzaboss.cortex.events import CaptureLog
from danzaboss.cortex.factory import db_path, open_store
from danzaboss.cortex.identity import resolve_project
from danzaboss.cortex.observation import Observation
from danzaboss.workstation import execution as execution_mod
from danzaboss.workstation.turnbrief import (
    TURN_BRIEF_RELPATH, compile_turn_brief, write_turn_brief)


def _leaf(tid: str, kind: str = "backend", depends_on=()) -> dict:
    return {"id": tid, "description": f"implement {tid}", "kind": kind,
            "size_est": 10, "writes": ["x"], "depends_on": list(depends_on),
            "verification": {"kind": "automated_test",
                             "detail": f"pytest tests/{tid}.py"}}


def _plan(order, leaves_by_id) -> dict:
    return {"spec_ref": "spec.md",
            "tasks": [{"id": "1", "description": "section",
                      "subtasks": list(leaves_by_id.values())}],
            "order": order}


def _independent_plan(n: int) -> dict:
    """n independent leaves (no deps on each other) — all ready at once."""
    leaves = {f"1.{i}": _leaf(f"1.{i}") for i in range(1, n + 1)}
    return _plan(list(leaves), leaves)


def state(**over):
    base = {"mode": "relay", "current_boss": "claude", "turn_number": 0,
            "status": "ready", "max_features_per_turn": 2}
    base.update(over)
    return TeamState(**base)


class TurnBriefFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / ".danza" / "runtime").mkdir(parents=True)


class AssignedUnitsQuota(TurnBriefFixture):
    def test_quota_cap_respected(self):
        plan = _independent_plan(5)
        text = compile_turn_brief(self.root, state(max_features_per_turn=2),
                                  plan, "claude", "build")
        self.assertEqual(text.count("implement 1."), 2)

    def test_larger_quota_lists_more_units(self):
        plan = _independent_plan(5)
        text = compile_turn_brief(self.root, state(max_features_per_turn=4),
                                  plan, "claude", "build")
        self.assertEqual(text.count("implement 1."), 4)

    def test_no_ready_units_states_so_explicitly(self):
        plan = _independent_plan(1)
        plan["execution"] = execution_mod.initial_execution(plan["order"])
        plan["execution"]["1.1"].update({
            "status": "completed", "started_at": "s", "completed_at": "c",
            "actual_minutes": 1, "verification_attempts": 1,
            "verification_passed": True,
            "verification_evidence": [{"passed": True}], "completed_turn": 0})
        text = compile_turn_brief(self.root, state(), plan, "claude", "build")
        self.assertIn("No dependency-ready units", text)

    def test_lists_id_description_and_verification(self):
        plan = _independent_plan(2)
        text = compile_turn_brief(self.root, state(max_features_per_turn=1),
                                  plan, "claude", "build")
        self.assertIn("1.1", text)
        self.assertIn("implement 1.1", text)
        self.assertIn("pytest tests/1.1.py", text)


class SectionsWithoutCortex(TurnBriefFixture):
    def test_sections_one_two_three_present_regardless_of_cortex_health(self):
        plan = _independent_plan(2)
        with patch("danzaboss.cortex.factory.open_store",
                   side_effect=RuntimeError("db locked")):
            text = compile_turn_brief(self.root, state(), plan, "claude", "build")
        self.assertIn("## Your turn", text)
        self.assertIn("## Assigned units", text)
        self.assertIn("## Last turn", text)

    def test_cortex_failure_yields_one_line_fallback_without_section(self):
        plan = _independent_plan(1)
        with patch("danzaboss.cortex.factory.open_store",
                   side_effect=RuntimeError("db locked")):
            text = compile_turn_brief(self.root, state(), plan, "claude", "build")
        self.assertNotIn("## What the team already knows", text)
        self.assertIn("Memory unavailable (db locked)", text)
        self.assertIn("proceed with the plan above", text)

    def test_footer_present_even_on_cortex_failure(self):
        plan = _independent_plan(1)
        with patch("danzaboss.cortex.driver_context.compile_driver_context",
                   side_effect=RuntimeError("boom")):
            text = compile_turn_brief(self.root, state(), plan, "claude", "build")
        self.assertIn("danza cortex search", text)
        self.assertIn("danza cortex get", text)


class HappyPathCortex(TurnBriefFixture):
    def _seed(self):
        project = resolve_project(str(self.root))
        store = open_store(str(self.root))
        store.upsert(Observation(
            title="Auth uses bcrypt cost 12", summary="cost factor 12 chosen",
            type="impl_detail", project=project, concepts=["auth"],
            tags=["auth"]))
        return project

    def test_happy_path_includes_rendered_observation(self):
        self._seed()
        plan = _independent_plan(1)
        text = compile_turn_brief(self.root, state(), plan, "claude", "build")
        self.assertIn("## What the team already knows", text)
        self.assertIn("Auth uses bcrypt cost 12", text)
        self.assertIn("cost factor 12 chosen", text)

    def test_telemetry_records_context_read(self):
        project = self._seed()
        plan = _independent_plan(1)
        compile_turn_brief(self.root, state(), plan, "claude", "build")
        log = CaptureLog(db_path(str(self.root)))
        stats = log.context_read_stats(project)
        self.assertIn("tony-d-orchestrator", stats)
        self.assertEqual(stats["tony-d-orchestrator"]["reads"], 1)


class LastTurnSection(TurnBriefFixture):
    def test_no_prior_turn_says_so(self):
        plan = _independent_plan(1)
        text = compile_turn_brief(self.root, state(turn_number=0), plan,
                                  "claude", "build")
        self.assertIn("No prior turn recorded", text)

    def test_reports_previous_boss_and_units(self):
        leaves = {"1.1": _leaf("1.1")}
        plan = _plan(["1.1"], leaves)
        plan["execution"] = execution_mod.initial_execution(plan["order"])
        plan["execution"]["1.1"].update({
            "status": "completed", "started_at": "s", "completed_at": "c",
            "actual_minutes": 1, "verification_attempts": 1,
            "verification_passed": True,
            "verification_evidence": [{"passed": True}], "completed_turn": 0})
        text = compile_turn_brief(
            self.root,
            state(turn_number=1, current_boss="codex", previous_boss="claude"),
            plan, "codex", "build")
        self.assertIn("claude", text.split("## Last turn")[1].split("##")[0])
        self.assertIn("1.1", text.split("## Last turn")[1].split("##")[0])


class YourTurnSection(TurnBriefFixture):
    def test_names_boss_turn_and_quota(self):
        plan = _independent_plan(1)
        text = compile_turn_brief(
            self.root, state(turn_number=3, max_features_per_turn=5), plan,
            "claude", "build")
        self.assertIn("claude", text)
        self.assertIn("3", text)
        self.assertIn("5", text)
        self.assertIn("danza unit conclude", text)

    def test_continuous_mode_reports_no_cap(self):
        plan = _independent_plan(1)
        text = compile_turn_brief(
            self.root, state(mode="continuous", max_features_per_turn=None),
            plan, "claude", "build")
        self.assertIn("no cap", text.lower())


class AtomicWrite(TurnBriefFixture):
    def test_write_creates_relpath_with_no_leftover_tmp(self):
        plan = _independent_plan(1)
        path = write_turn_brief(self.root, state(), plan, "claude", "build")
        self.assertEqual(path, self.root / TURN_BRIEF_RELPATH)
        self.assertTrue(path.exists())
        self.assertFalse(path.with_name(path.name + ".tmp").exists())
        self.assertIn("## Your turn", path.read_text(encoding="utf-8"))

    def test_write_overwrites_prior_brief(self):
        plan = _independent_plan(1)
        write_turn_brief(self.root, state(max_features_per_turn=2), plan,
                         "claude", "build")
        first = (self.root / TURN_BRIEF_RELPATH).read_text(encoding="utf-8")
        write_turn_brief(self.root, state(max_features_per_turn=5), plan,
                         "claude", "build")
        second = (self.root / TURN_BRIEF_RELPATH).read_text(encoding="utf-8")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
