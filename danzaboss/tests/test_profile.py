"""Tests for the execution-profile governor (C4.5) — resolution, policy
invariants, memory-capture diet, and profile-aware hook behavior."""
import dataclasses
import json
import os
import tempfile
import unittest

import _bootstrap  # noqa

from danzaboss.kernel.profile import (
    PROFILE_ENV_VAR, PROFILES, active_profile, capture_event, event_significant)
from danzaboss.cortex import commands as cortex_commands
from danzaboss.cortex.events import CaptureLog
from danzaboss.hooks.gates import distillation_gate


class TestProfileResolution(unittest.TestCase):
    def test_env_var_wins(self):
        self.assertEqual(
            active_profile(".", env={PROFILE_ENV_VAR: "APP_BUILD"}).name, "APP_BUILD")

    def test_env_var_is_case_insensitive(self):
        self.assertEqual(
            active_profile(".", env={PROFILE_ENV_VAR: "os_boot_test"}).name,
            "OS_BOOT_TEST")

    def test_unknown_name_fails_closed(self):
        with self.assertRaises(ValueError):
            active_profile(".", env={PROFILE_ENV_VAR: "YOLO"})

    def test_config_file_used_when_no_env(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, ".danza", "runtime"))
        with open(os.path.join(root, ".danza", "runtime", "profile.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"profile": "OS_BOOT_TEST"}, fh)
        self.assertEqual(active_profile(root, env={}).name, "OS_BOOT_TEST")

    def test_unactivated_repo_defaults_to_os_dev(self):
        self.assertEqual(active_profile(tempfile.mkdtemp(), env={}).name, "OS_DEV")

    def test_team_state_presence_means_app_build(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, ".danza", "runtime"))
        with open(os.path.join(root, ".danza", "runtime", "team-state.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("{}")
        self.assertEqual(active_profile(root, env={}).name, "APP_BUILD")

    def test_boot_test_is_never_inferred(self):
        # only env/config can select OS_BOOT_TEST; heuristics never do
        for root in (".", tempfile.mkdtemp()):
            self.assertNotEqual(active_profile(root, env={}).name, "OS_BOOT_TEST")


class TestPolicyInvariants(unittest.TestCase):
    def test_destructive_deny_active_in_every_profile(self):
        for p in PROFILES.values():
            self.assertTrue(p.destructive_deny_active, p.name)

    def test_research_requires_approval_in_every_profile(self):
        for p in PROFILES.values():
            self.assertTrue(p.research_requires_approval, p.name)

    def test_os_dev_is_minimal_ceremony_layer_zero(self):
        p = PROFILES["OS_DEV"]
        self.assertEqual(p.layer, 0)
        self.assertFalse(p.constitution_binding)
        self.assertFalse(p.turn_gates_active)
        self.assertFalse(p.domain_ask_active)
        self.assertTrue(p.claude_write_approval)
        self.assertEqual(p.memory_level, "none")   # CORTEX dormant during OS builds
        self.assertFalse(p.agents_may_spawn)
        self.assertFalse(p.session_inject)        # CORTEX stays silent in Layer 0
        self.assertFalse(p.distill_gate_active)   # no distillation nagging in dev

    def test_runtime_profiles_keep_full_governance(self):
        for name in ("OS_BOOT_TEST", "APP_BUILD"):
            p = PROFILES[name]
            self.assertTrue(p.constitution_binding, name)
            self.assertTrue(p.turn_gates_active, name)
            self.assertTrue(p.domain_ask_active, name)
            self.assertFalse(p.claude_write_approval, name)
            self.assertTrue(p.agents_may_spawn, name)
            self.assertEqual(p.distill_min_events, 1, name)
            self.assertTrue(p.session_inject, name)        # runtime injects memory
            self.assertTrue(p.distill_gate_active, name)   # runtime enforces distill


class TestMemoryDiet(unittest.TestCase):
    def test_mutations_and_state_commands_are_significant(self):
        self.assertTrue(event_significant("Write"))
        self.assertTrue(event_significant("Edit"))
        self.assertTrue(event_significant("Bash", "git commit -m 'x'"))
        self.assertTrue(event_significant("Bash", "./danzaboss/run_tests.sh"))
        self.assertTrue(event_significant("Bash", "python3 -m danzaboss.cli selftest"))

    def test_reads_and_trivial_shell_are_noise(self):
        self.assertFalse(event_significant("Read"))
        self.assertFalse(event_significant("Bash", "ls -la"))
        self.assertFalse(event_significant("Bash", "cat foo.py"))
        self.assertFalse(event_significant("Glob"))

    def test_capture_levels(self):
        os_dev, app = PROFILES["OS_DEV"], PROFILES["APP_BUILD"]
        # OS_DEV is dormant (memory_level="none"): CORTEX captures nothing during
        # OS builds so claude-mem is the sole build-time memory system.
        self.assertFalse(capture_event(os_dev, "Bash", "ls"))       # none -> nothing
        self.assertFalse(capture_event(os_dev, "Edit"))             # not even mutations
        self.assertTrue(capture_event(app, "Bash", "ls"))           # normal keeps all
        # the "lightweight" level still drops noise but keeps mutations
        light = dataclasses.replace(os_dev, memory_level="lightweight")
        self.assertFalse(capture_event(light, "Bash", "ls"))
        self.assertTrue(capture_event(light, "Edit"))


class TestDistillationNoiseFloor(unittest.TestCase):
    def test_blocks_at_or_above_min_events(self):
        self.assertFalse(distillation_gate(3, 0, False, min_events=3).allow)

    def test_passes_below_min_events(self):
        self.assertTrue(distillation_gate(2, 0, False, min_events=3).allow)

    def test_default_min_is_one_backward_compatible(self):
        self.assertFalse(distillation_gate(1, 0, False).allow)
        self.assertTrue(distillation_gate(0, 0, False).allow)


class TestProfileAwareCortexHooks(unittest.TestCase):
    """The live hook handlers must honor the profile of the repo they run in."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._saved = os.environ.pop(PROFILE_ENV_VAR, None)

    def tearDown(self):
        if self._saved is not None:
            os.environ[PROFILE_ENV_VAR] = self._saved

    def _events(self, sid):
        log = CaptureLog(cortex_commands.db_path(self.root))
        return log.pending(sid)

    def test_os_dev_capture_drops_trivial_bash(self):
        # fresh tmp repo has no team-state.json -> OS_DEV -> memory_level="none"
        cortex_commands._hook_post_tool_use(self.root, {
            "session_id": "s1", "tool_name": "Bash",
            "tool_input": {"command": "ls -la"}})
        self.assertEqual(self._events("s1"), [])

    def test_os_dev_capture_records_nothing(self):
        # OS_DEV is dormant: even a mutation is NOT captured — claude-mem holds
        # build memory so only one memory system runs during OS builds.
        cortex_commands._hook_post_tool_use(self.root, {
            "session_id": "s1", "tool_name": "Edit",
            "tool_input": {"file_path": "danzaboss/cli.py"}})
        self.assertEqual(self._events("s1"), [])

    def test_app_build_capture_keeps_everything(self):
        os.environ[PROFILE_ENV_VAR] = "APP_BUILD"
        try:
            cortex_commands._hook_post_tool_use(self.root, {
                "session_id": "s2", "tool_name": "Bash",
                "tool_input": {"command": "ls -la"}})
            self.assertEqual(len(self._events("s2")), 1)
        finally:
            del os.environ[PROFILE_ENV_VAR]

    def test_os_dev_stop_does_not_nag_tiny_sessions(self):
        log = CaptureLog(cortex_commands.db_path(self.root))
        log.open_session("s3", "proj")
        log.record_event("s3", "Edit", file_path="a.py")  # 1 event < floor of 3
        rc = cortex_commands._hook_stop(self.root, {"session_id": "s3"})
        self.assertEqual(rc, 0)
        sess = log.session("s3")
        self.assertEqual(sess["gate_blocked"], 0)          # no block issued
        self.assertEqual(sess["status"], "completed")      # session closed clean
        self.assertEqual(self._events("s3"), [])           # processed, not drafted

    def test_os_dev_session_start_injects_nothing(self):
        # Layer 0: the session-start hook must NOT print a CORTEX context block.
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cortex_commands._hook_session_start(self.root, {"session_id": "sX"})
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), "")       # nothing injected in OS_DEV

    def test_os_dev_stop_does_not_block_above_floor(self):
        # 4 events (>= floor of 3) but OS_DEV's gate is inactive -> no block.
        log = CaptureLog(cortex_commands.db_path(self.root))
        log.open_session("s4", "proj")
        for i in range(4):
            log.record_event("s4", "Edit", file_path=f"f{i}.py")
        rc = cortex_commands._hook_stop(self.root, {"session_id": "s4"})
        self.assertEqual(rc, 0)
        sess = log.session("s4")
        self.assertEqual(sess["gate_blocked"], 0)          # OS_DEV never blocks
        self.assertEqual(sess["status"], "completed")

    def test_app_build_stop_blocks_above_floor(self):
        # runtime profile keeps the distillation gate active.
        import contextlib
        import io
        os.environ[PROFILE_ENV_VAR] = "APP_BUILD"
        try:
            log = CaptureLog(cortex_commands.db_path(self.root))
            log.open_session("s5", "proj")
            for i in range(2):
                log.record_event("s5", "Edit", file_path=f"g{i}.py")
            with contextlib.redirect_stdout(io.StringIO()):
                rc = cortex_commands._hook_stop(self.root, {"session_id": "s5"})
            self.assertEqual(rc, 0)
            self.assertEqual(log.session("s5")["gate_blocked"], 1)
        finally:
            del os.environ[PROFILE_ENV_VAR]


if __name__ == "__main__":
    unittest.main()
