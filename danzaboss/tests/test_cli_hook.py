"""Live Claude Code hook decision path (danzaboss.cli._hook_decision).

The live PreToolUse hook enforces the actor-independent guards. These tests pin
the wired behavior — including the context-budget guard, which caps sub-agent
dispatch payloads so drivers get budgeted context instead of the whole repo.

The CC PreToolUse payload carries no acting-agent id (actor=""), so only the
actor-independent guards can be enforced here: file_protection, hard_stop, and
context_budget. The budget guard binds only where runtime law binds
(constitution_binding: OS_BOOT_TEST / APP_BUILD), never in OS_DEV (Layer 0).
"""
import json
import os
import tempfile
import unittest

from danzaboss.cli import _hook_decision, _dispatch_tokens
from danzaboss.hooks.guards import GuardConfig


def _app_build_root() -> str:
    """A repo root the profile resolver reads as APP_BUILD (runtime law binds):
    activation writes .danza/runtime/team-state.json (Rule 45)."""
    root = tempfile.mkdtemp()
    rt = os.path.join(root, ".danza", "runtime")
    os.makedirs(rt)
    with open(os.path.join(rt, "team-state.json"), "w") as fh:
        json.dump({"current_boss": "claude"}, fh)
    return root


def _os_dev_root() -> str:
    """A fresh repo with no team-state.json -> OS_DEV (Layer 0)."""
    return tempfile.mkdtemp()


def _task_payload(prompt: str) -> dict:
    return {"tool_name": "Task",
            "tool_input": {"description": "spawn driver",
                           "subagent_type": "jonathan-builder",
                           "prompt": prompt}}


def _task_payload_at_tokens(tokens: int) -> dict:
    payload = _task_payload("")
    tool_input = payload["tool_input"]
    overhead = len(json.dumps(tool_input))
    tool_input["prompt"] = "x" * (tokens * 4 - overhead)
    assert _dispatch_tokens("Task", tool_input) == tokens
    return payload


class TestDispatchTokenEstimate(unittest.TestCase):
    def test_non_dispatch_tools_are_zero(self):
        self.assertEqual(_dispatch_tokens("Edit", {"file_path": "a.py"}), 0)
        self.assertEqual(_dispatch_tokens("Bash", {"command": "ls"}), 0)

    def test_dispatch_payload_estimated_by_size(self):
        small = _dispatch_tokens("Task", {"prompt": "x" * 40})
        big = _dispatch_tokens("Agent", {"prompt": "x" * 40000})
        self.assertGreater(big, small)
        self.assertGreater(big, 4000)          # ~10k tokens
        self.assertLessEqual(small, 40)        # tiny


class TestContextBudgetWiring(unittest.TestCase):
    """The context-budget guard is live on the CC hook in runtime profiles."""

    def test_app_build_denies_oversized_dispatch(self):
        root = _app_build_root()
        over = "x" * (GuardConfig().max_dispatch_tokens * 4 + 4000)  # > budget
        decision, reason = _hook_decision(_task_payload(over), root)
        self.assertEqual(decision, "deny")
        self.assertIn("budget", reason)

    def test_app_build_allows_budgeted_dispatch(self):
        root = _app_build_root()
        decision, _ = _hook_decision(_task_payload("build feature X"), root)
        self.assertEqual(decision, "allow")

    def test_app_build_allows_6000_and_denies_6001(self):
        root = _app_build_root()
        allowed, _ = _hook_decision(_task_payload_at_tokens(6000), root)
        denied, reason = _hook_decision(_task_payload_at_tokens(6001), root)
        self.assertEqual(allowed, "allow")
        self.assertEqual(denied, "deny")
        self.assertIn("6000", reason)

    def test_os_dev_never_blocks_dispatch(self):
        # Layer 0 edits the factory; token discipline is a build-flow concern.
        root = _os_dev_root()
        over = "x" * (GuardConfig().max_dispatch_tokens * 4 + 4000)
        decision, _ = _hook_decision(_task_payload(over), root)
        self.assertEqual(decision, "allow")

    def test_ordinary_edit_untouched_by_budget_guard(self):
        root = _app_build_root()
        decision, _ = _hook_decision(
            {"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}}, root)
        self.assertEqual(decision, "allow")


class TestExistingGuardsPreserved(unittest.TestCase):
    """Wiring the budget guard must not change the two guards already live."""

    def test_template_write_still_denied(self):
        root = _app_build_root()
        decision, reason = _hook_decision(
            {"tool_name": "Write",
             "tool_input": {"file_path": ".danza/handoff-template.md"}}, root)
        self.assertEqual(decision, "deny")
        self.assertIn("template", reason.lower())

    def test_destructive_command_still_denied(self):
        root = _app_build_root()
        decision, reason = _hook_decision(
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}, root)
        self.assertEqual(decision, "deny")
        self.assertIn("destructive", reason)

    def test_ordinary_read_allowed(self):
        root = _app_build_root()
        decision, _ = _hook_decision(
            {"tool_name": "Read", "tool_input": {"file_path": "README.md"}}, root)
        self.assertEqual(decision, "allow")


if __name__ == "__main__":
    unittest.main()
