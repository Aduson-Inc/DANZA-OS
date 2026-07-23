"""Live Claude Code hook decision path (danzaboss.cli._hook_decision).

The live PreToolUse hook enforces the actor-independent guards. These tests pin
the wired behavior — including the context-budget guard, which caps sub-agent
dispatch payloads so drivers get budgeted context instead of the whole repo.

The CC PreToolUse payload carries no acting-agent id (actor=""), so only the
actor-independent guards can be enforced here: file_protection, hard_stop, and
context_budget. The budget guard binds only where runtime law binds
(constitution_binding: OS_BOOT_TEST / APP_BUILD), never in OS_DEV (Layer 0).
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from danzaboss.cli import _hook_decision, _dispatch_tokens, main
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


def _corrupt_profile_root(with_installation: bool) -> str:
    """A repo whose .danza/runtime/profile.json is corrupt -> active_profile()
    raises. installation.json (product/activation.py's activation marker)
    present/absent decides whether profile_binds_law's evidence fallback
    treats this as a bound APP_BUILD repo or an unactivated OS_DEV tree."""
    root = tempfile.mkdtemp()
    rt = os.path.join(root, ".danza", "runtime")
    os.makedirs(rt)
    with open(os.path.join(rt, "profile.json"), "w", encoding="utf-8") as fh:
        fh.write("{not valid json")
    if with_installation:
        with open(os.path.join(rt, "installation.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("{}")
    return root


def _task_payload(prompt: str) -> dict:
    return {"tool_name": "Task",
            "tool_input": {"description": "spawn driver",
                           "subagent_type": "jonathan-builder",
                           "prompt": prompt}}


def _task_payload_at_tokens(tokens: int) -> dict:
    # _dispatch_tokens now estimates via cortex/tokens.py kind="json"
    # (~3.0 chars/token, not the old flat 4) — construct a payload whose
    # serialized length is exactly `tokens * 3` chars so the estimate lands
    # on `tokens` precisely, matching est_tokens' `len(text) // 3` math.
    payload = _task_payload("")
    tool_input = payload["tool_input"]
    overhead = len(json.dumps(tool_input))
    tool_input["prompt"] = "x" * (tokens * 3 - overhead)
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

    def test_app_build_allows_8000_and_denies_8001(self):
        root = _app_build_root()
        allowed, _ = _hook_decision(_task_payload_at_tokens(8000), root)
        denied, reason = _hook_decision(_task_payload_at_tokens(8001), root)
        self.assertEqual(allowed, "allow")
        self.assertEqual(denied, "deny")
        self.assertIn("8000", reason)

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


class TestFailClosedWhereRuntimeLawBinds(unittest.TestCase):
    """PreToolUse: an unreadable payload or an internal guard error must deny
    in profiles where runtime law binds (APP_BUILD/OS_BOOT_TEST). OS_DEV
    (Layer 0) keeps the historical fail-open behavior — its own hooks must
    never be able to brick it."""

    def setUp(self):
        self._old_cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._old_cwd)

    def _run_pretooluse(self, root, stdin_text):
        os.chdir(root)
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(stdin_text)):
            with redirect_stdout(out), redirect_stderr(err):
                rc = main(["hook", "pretooluse"])
        return rc, out.getvalue(), err.getvalue()

    def _run_hook(self, root, event, stdin_text):
        os.chdir(root)
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(stdin_text)):
            with redirect_stdout(out), redirect_stderr(err):
                rc = main(["hook", event])
        return rc, out.getvalue(), err.getvalue()

    def test_app_build_denies_unreadable_stdin(self):
        root = _app_build_root()
        rc, out, _ = self._run_pretooluse(root, "this is not json{{{")
        self.assertEqual(rc, 0)
        hso = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "deny")
        self.assertIn("hook payload unreadable",
                      hso["permissionDecisionReason"])

    def test_os_dev_allows_unreadable_stdin(self):
        root = _os_dev_root()
        rc, out, _ = self._run_pretooluse(root, "this is not json{{{")
        self.assertEqual(rc, 0)
        hso = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "allow")

    def test_app_build_denies_on_internal_guard_error(self):
        root = _app_build_root()
        payload = json.dumps({"tool_name": "Edit",
                              "tool_input": {"file_path": "a.py"}})
        with mock.patch("danzaboss.cli.file_protection_guard",
                        side_effect=RuntimeError("guard exploded")):
            rc, out, _ = self._run_pretooluse(root, payload)
        self.assertEqual(rc, 0)
        hso = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "deny")
        self.assertIn("guard exploded", hso["permissionDecisionReason"])

    def test_os_dev_allows_on_internal_guard_error(self):
        root = _os_dev_root()
        payload = json.dumps({"tool_name": "Edit",
                              "tool_input": {"file_path": "a.py"}})
        with mock.patch("danzaboss.cli.file_protection_guard",
                        side_effect=RuntimeError("guard exploded")):
            rc, out, err = self._run_pretooluse(root, payload)
        self.assertEqual(rc, 0)
        hso = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "allow")
        self.assertIn("failing open", err)

    def test_app_build_stop_with_unreadable_stdin_emits_stop_shape(self):
        # Finding 1: a Stop event must never emit the PreToolUse
        # permissionDecision shape, even when stdin is garbage in a binding
        # profile. Stop is an honest pass-through by design (the enforcement
        # point is `danza cortex hook stop`), so unreadable stdin here must
        # still produce the plain Stop shape and exit 0.
        root = _app_build_root()
        rc, out, _ = self._run_hook(root, "stop", "this is not json{{{")
        self.assertEqual(rc, 0)
        parsed = json.loads(out)
        hso = parsed["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "Stop")
        self.assertNotIn("permissionDecision", hso)

    def test_os_dev_stop_with_unreadable_stdin_emits_stop_shape(self):
        root = _os_dev_root()
        rc, out, _ = self._run_hook(root, "stop", "this is not json{{{")
        self.assertEqual(rc, 0)
        hso = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "Stop")
        self.assertNotIn("permissionDecision", hso)


class TestEvidenceBasedBindingFallback(unittest.TestCase):
    """Finding 2: a corrupt .danza/runtime/profile.json must not silently
    switch protection off. profile_binds_law falls back to evidence
    (installation.json presence) when active_profile() itself raises."""

    def setUp(self):
        self._old_cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._old_cwd)

    def _run_pretooluse(self, root, stdin_text):
        os.chdir(root)
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(stdin_text)):
            with redirect_stdout(out):
                rc = main(["hook", "pretooluse"])
        return rc, out.getvalue()

    def test_corrupt_profile_with_installation_evidence_denies_and_explains(self):
        root = _corrupt_profile_root(with_installation=True)
        rc, out = self._run_pretooluse(root, "this is not json{{{")
        self.assertEqual(rc, 0)
        hso = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "deny")
        reason = hso["permissionDecisionReason"].lower()
        self.assertIn("profile", reason)
        self.assertIn("unreadable", reason)
        self.assertIn("danza doctor", reason)

    def test_corrupt_profile_without_installation_evidence_fails_open(self):
        root = _corrupt_profile_root(with_installation=False)
        rc, out = self._run_pretooluse(root, "this is not json{{{")
        self.assertEqual(rc, 0)
        hso = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "allow")

    def test_corrupt_profile_with_installation_evidence_denies_on_guard_error(self):
        root = _corrupt_profile_root(with_installation=True)
        payload = json.dumps({"tool_name": "Edit",
                              "tool_input": {"file_path": "a.py"}})
        with mock.patch("danzaboss.cli.file_protection_guard",
                        side_effect=RuntimeError("guard exploded")):
            rc, out = self._run_pretooluse(root, payload)
        self.assertEqual(rc, 0)
        hso = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "deny")
        reason = hso["permissionDecisionReason"].lower()
        self.assertIn("profile", reason)
        self.assertIn("unreadable", reason)
        self.assertIn("danza doctor", reason)


if __name__ == "__main__":
    unittest.main()
