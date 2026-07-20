"""Contract tests for model-neutral DANZA runtime authority.

These tests deliberately exercise the runtime boundary rather than prompt
wording. A model response is never evidence of a spawn or a permitted action.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from danzaboss.agents.runtime import (
    AgentRuntime,
    AuthorizationError,
    load_agent_definitions,
)
from danzaboss.product.handoff import (
    HandoffMode,
    classify_handoff,
    write_handoff_state,
)
from danzaboss.runtime.events import DanzaEvent, EventKind, ProjectEventLog


class AgentDefinitionContract(unittest.TestCase):
    def test_definitions_are_vendor_neutral_and_role_bound(self):
        definitions = load_agent_definitions()
        self.assertEqual(set(definitions), {
            "tony-d-orchestrator", "jonathan-builder", "samantha-mapper",
            "angela-auditor", "bonnie-qa", "carmella-researcher",
            "hank-designer", "billy-security",
        })
        tony = definitions["tony-d-orchestrator"]
        self.assertIn("spawn_agent", tony.capabilities)
        self.assertNotIn("write_code", tony.capabilities)
        self.assertEqual(tony.spawn_allowlist, {
            "jonathan-builder", "samantha-mapper", "angela-auditor",
            "bonnie-qa", "carmella-researcher", "hank-designer",
            "billy-security",
        })


class DelegationContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runtime = AgentRuntime(self.root)

    def test_tony_cannot_do_a_builder_task(self):
        with self.assertRaises(AuthorizationError):
            self.runtime.authorize(
                actor="tony-d-orchestrator", action="write_code", task_id="T1"
            )

    def test_spawn_requires_real_receipt_before_child_can_act(self):
        assignment = self.runtime.assign(
            parent="tony-d-orchestrator",
            child="jonathan-builder",
            task_id="T1",
            scope=["src/app.py"],
            reason="the feature requires application code",
        )
        with self.assertRaises(AuthorizationError):
            self.runtime.authorize(
                actor="jonathan-builder", action="write_code", task_id="T1"
            )

        self.runtime.record_spawn(
            assignment.id, child_session_id="provider-session-1"
        )
        self.assertTrue(self.runtime.authorize(
            actor="jonathan-builder", action="write_code", task_id="T1",
            path="src/app.py",
        ))

    def test_claimed_spawn_without_receipt_is_not_evidence(self):
        assignment = self.runtime.assign(
            parent="tony-d-orchestrator",
            child="bonnie-qa",
            task_id="T2",
            scope=["."],
            reason="the feature has a verification criterion",
        )
        self.assertFalse(self.runtime.has_spawn_receipt(assignment.id))
        with self.assertRaises(AuthorizationError):
            self.runtime.authorize(
                actor="bonnie-qa", action="run_tests", task_id="T2"
            )

    def test_task_start_uses_runtime_receipt_and_cortex_gate(self):
        first = self.runtime.start_task(
            actor="tony-d-orchestrator", task_id="T0",
            task="seed the project brief",
            seed={"type": "decision", "title": "Project brief",
                  "summary": "The verified project brief."})
        self.assertTrue(first.seeded)
        assignment = self.runtime.assign(
            parent="tony-d-orchestrator", child="jonathan-builder",
            task_id="T1", scope=["src/app.py"],
            reason="the feature requires application code")
        with self.assertRaises(AuthorizationError):
            self.runtime.start_task(actor="jonathan-builder", task_id="T1",
                                    task="write the app")
        self.runtime.record_spawn(assignment.id,
                                  child_session_id="provider-session-2")
        second = self.runtime.start_task(
            actor="jonathan-builder", task_id="T1", task="write the app")
        self.assertFalse(second.seeded)
        self.assertIn("Project brief", second.context)

    def test_every_delegation_requires_a_specific_need(self):
        with self.assertRaisesRegex(AuthorizationError, "reason"):
            self.runtime.assign(parent="tony-d-orchestrator",
                                child="jonathan-builder", task_id="T3",
                                scope=["src"], reason="")

    def test_runtime_rejects_full_roster_and_limits_specialists_per_task(self):
        roster = [name for name in self.runtime.definitions
                  if name != "tony-d-orchestrator"]
        with self.assertRaisesRegex(AuthorizationError, "specialists"):
            self.runtime.plan_spawn(
                parent="tony-d-orchestrator", task_id="T4", scope=["."],
                specialists=roster,
                reasons={name: "not actually needed" for name in roster})

        assignments = self.runtime.plan_spawn(
            parent="tony-d-orchestrator", task_id="T5", scope=["."],
            specialists=["samantha-mapper", "jonathan-builder",
                         "bonnie-qa"],
            reasons={"samantha-mapper": "the feature changes an unknown area",
                     "jonathan-builder": "the feature requires code",
                     "bonnie-qa": "the acceptance test must pass"})
        self.assertEqual(len(assignments), 3)
        with self.assertRaisesRegex(AuthorizationError, "budget"):
            self.runtime.assign(parent="tony-d-orchestrator",
                                child="angela-auditor", task_id="T5",
                                scope=["."], reason="unnecessary extra review")


class EventContract(unittest.TestCase):
    def test_project_event_log_redacts_and_records_contract_kinds(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = ProjectEventLog(Path(tmp))
            receipt = log.append(DanzaEvent(
                kind=EventKind.COMMAND,
                actor="jonathan-builder",
                session_id="s1",
                task_id="T1",
                payload={"command": "curl https://x:secret@example.test"},
            ))
            self.assertEqual(receipt.kind, EventKind.COMMAND)
            raw = (Path(tmp) / ".danza" / "runtime" / "events.jsonl").read_text()
            self.assertNotIn("secret", raw)
            self.assertIn("command", raw)


class HandoffContract(unittest.TestCase):
    def test_bootstrap_handoff_is_new_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.mkdir(exist_ok=True)
            (root / ".danza").mkdir()
            (root / ".danza" / "handoff.md").write_text(
                "# Handoff\n\nNo handoff yet.\n"
            )
            self.assertEqual(classify_handoff(root).mode, HandoffMode.NEW)

    def test_valid_handoff_requires_consistent_machine_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".danza").mkdir()
            (root / ".danza" / "handoff.md").write_text(
                "# Handoff\n\nNext: claude.\n"
            )
            write_handoff_state(
                root,
                turn_number=3,
                current_boss="claude",
                next_boss="claude",
                verified_unit_ids=["T1"],
            )
            result = classify_handoff(root)
            self.assertEqual(result.mode, HandoffMode.CONTINUE)
            self.assertTrue(result.valid)

    def test_real_handoff_without_sidecar_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".danza").mkdir()
            (root / ".danza" / "handoff.md").write_text(
                "# Handoff\n\nNext: claude.\n"
            )
            result = classify_handoff(root)
            self.assertEqual(result.mode, HandoffMode.BLOCKED)
            self.assertFalse(result.valid)


if __name__ == "__main__":
    unittest.main()
