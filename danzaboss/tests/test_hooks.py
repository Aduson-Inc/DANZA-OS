import os, tempfile, unittest
import _bootstrap  # noqa
from danzaboss.hooks.events import ToolEvent, TurnRecord
from danzaboss.hooks.guards import (
    GuardConfig, capability_guard, hard_stop_guard, turn_lock_guard,
    file_protection_guard, scope_guard, context_budget_guard)
from danzaboss.hooks.gates import (
    anti_theatre_gate, verify_before_done_gate, regression_gate)
from danzaboss.hooks.dispatcher import HookDispatcher
from danzaboss.security.capabilities import CapabilityRegistry, Capability


def reg():
    return CapabilityRegistry(os.path.join(tempfile.mkdtemp(), "audit.jsonl"))


class TestGuards(unittest.TestCase):
    def setUp(self):
        self.cfg = GuardConfig()
        self.reg = reg()

    def test_orchestrator_cannot_write_code(self):
        ev = ToolEvent(actor="tony-d-orchestrator", tool="Write", path="src/app.py")
        self.assertFalse(capability_guard(ev, self.reg).allow)

    def test_builder_can_write_code(self):
        ev = ToolEvent(actor="jonathan-builder", tool="Write", path="src/app.py")
        self.assertTrue(capability_guard(ev, self.reg).allow)

    def test_hard_stop_on_auth_file(self):
        ev = ToolEvent(actor="jonathan-builder", tool="Edit", path="src/auth/login.ts")
        self.assertFalse(hard_stop_guard(ev, self.cfg).allow)

    def test_hard_stop_cleared_with_elevation(self):
        ev = ToolEvent(actor="jonathan-builder", tool="Edit", path="src/auth/login.ts",
                       elevation_token="approved")
        self.assertTrue(hard_stop_guard(ev, self.cfg).allow)

    def test_hard_stop_on_rm_rf(self):
        ev = ToolEvent(actor="jonathan-builder", tool="Bash", command="rm -rf build/")
        self.assertFalse(hard_stop_guard(ev, self.cfg).allow)

    def test_ordinary_file_passes_hard_stop(self):
        ev = ToolEvent(actor="jonathan-builder", tool="Edit", path="src/widgets/button.tsx")
        self.assertTrue(hard_stop_guard(ev, self.cfg).allow)

    def test_turn_lock_blocks_non_boss_state_write(self):
        ev = ToolEvent(actor="codex", tool="Write", path=".danza/runtime/team-state.json")
        self.assertFalse(turn_lock_guard(ev, self.cfg, current_boss="claude").allow)

    def test_turn_lock_allows_boss(self):
        ev = ToolEvent(actor="claude", tool="Write", path=".danza/runtime/team-state.json")
        self.assertTrue(turn_lock_guard(ev, self.cfg, current_boss="claude").allow)

    def test_template_write_denied(self):
        ev = ToolEvent(actor="jonathan-builder", tool="Write", path=".danza/onboarding-template.md")
        self.assertFalse(file_protection_guard(ev, self.cfg).allow)

    def test_claude_dir_denied_without_approval(self):
        ev = ToolEvent(actor="jonathan-builder", tool="Edit", path=".claude/rules/constitution.md")
        self.assertFalse(file_protection_guard(ev, self.cfg, approval=False).allow)
        self.assertTrue(file_protection_guard(ev, self.cfg, approval=True).allow)

    def test_log_overwrite_denied(self):
        ev = ToolEvent(actor="angela-auditor", tool="Write", path=".danza/decision-log.md")
        self.assertFalse(file_protection_guard(ev, self.cfg).allow)

    def test_scope_guard_requires_approved_task(self):
        ev = ToolEvent(actor="jonathan-builder", tool="Write", path="src/x.py", task_id="T9")
        self.assertFalse(scope_guard(ev, approved_task_ids={"T1"}).allow)
        self.assertTrue(scope_guard(ev, approved_task_ids={"T9"}).allow)

    def test_scope_guard_denies_untagged_write(self):
        ev = ToolEvent(actor="jonathan-builder", tool="Write", path="src/x.py")
        self.assertFalse(scope_guard(ev, approved_task_ids={"T1"}).allow)

    def test_context_budget_blocks_oversized_dispatch(self):
        ev = ToolEvent(actor="tony-d-orchestrator", tool="Task", payload_tokens=9000)
        self.assertFalse(context_budget_guard(ev, self.cfg).allow)

    def test_context_budget_allows_within_budget(self):
        ev = ToolEvent(actor="tony-d-orchestrator", tool="Task", payload_tokens=1200)
        self.assertTrue(context_budget_guard(ev, self.cfg).allow)


class TestGates(unittest.TestCase):
    def test_anti_theatre_blocks_unbacked_claim(self):
        rec = TurnRecord(actor="claude", claimed_subagents=["bonnie-qa", "samantha-mapper"],
                         evidence_actors=["samantha-mapper"])
        self.assertFalse(anti_theatre_gate(rec).allow)

    def test_anti_theatre_passes_with_evidence(self):
        rec = TurnRecord(actor="claude", claimed_subagents=["bonnie-qa"],
                         evidence_actors=["bonnie-qa"])
        self.assertTrue(anti_theatre_gate(rec).allow)

    def test_verify_before_done_blocks_unverified(self):
        rec = TurnRecord(actor="claude", completed_features=["login"],
                         verifications={"login": False})
        self.assertFalse(verify_before_done_gate(rec).allow)

    def test_verify_before_done_passes(self):
        rec = TurnRecord(actor="claude", completed_features=["login"],
                         verifications={"login": True})
        self.assertTrue(verify_before_done_gate(rec).allow)

    def test_regression_gate_blocks_red_and_missing(self):
        self.assertFalse(regression_gate(TurnRecord(actor="c", tests_green=False)).allow)
        self.assertFalse(regression_gate(TurnRecord(actor="c", tests_green=None)).allow)
        self.assertTrue(regression_gate(TurnRecord(actor="c", tests_green=True)).allow)


class TestDispatcher(unittest.TestCase):
    def test_pre_tool_use_first_denial_wins(self):
        d = HookDispatcher(reg(), current_boss="claude", approved_task_ids={"T1"})
        # orchestrator writing code -> capability denies first
        ev = ToolEvent(actor="tony-d-orchestrator", tool="Write", path="src/a.py", task_id="T1")
        self.assertFalse(d.pre_tool_use(ev).allow)

    def test_pre_tool_use_allows_clean_action(self):
        d = HookDispatcher(reg(), current_boss="claude", approved_task_ids={"T1"})
        ev = ToolEvent(actor="jonathan-builder", tool="Write", path="src/widget.tsx", task_id="T1")
        self.assertTrue(d.pre_tool_use(ev).allow)

    def test_stop_blocks_on_regression(self):
        d = HookDispatcher(reg())
        rec = TurnRecord(actor="claude", tests_green=False)
        self.assertFalse(d.stop(rec).allow)


if __name__ == "__main__":
    unittest.main()
