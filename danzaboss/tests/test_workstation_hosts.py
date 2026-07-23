"""SessionHost tests: TmuxHost, HeadlessHost, pick_host — all hermetic.

Every test substitutes the subprocess seam so no real tmux or real claude
is invoked. One env-gated live smoke test exercises the full ignite→tail→kill
cycle against a real tmux process; it is skipped by default.
"""
import _bootstrap  # noqa: F401
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call

from danzaboss.workstation import hosts
from danzaboss.workstation.hosts import (
    HostError,
    IGNITION_MESSAGE,
    TmuxHost,
    HeadlessHost,
    pick_host,
)
from danzaboss.workstation.workspace import (load_workspace, save_workspace,
                                              session_name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok_proc(stdout: str = "", stderr: str = "") -> MagicMock:
    """Fake subprocess.run result with returncode=0."""
    p = MagicMock()
    p.returncode = 0
    p.stdout = stdout
    p.stderr = stderr
    return p


def _err_proc(rc: int = 1, stderr: str = "tmux error") -> MagicMock:
    """Fake subprocess.run result with nonzero returncode."""
    p = MagicMock()
    p.returncode = rc
    p.stdout = ""
    p.stderr = stderr
    return p


def _fake_popen(poll_result: int | None = None) -> MagicMock:
    """Fake subprocess.Popen handle."""
    h = MagicMock()
    h.poll.return_value = poll_result
    return h


# ---------------------------------------------------------------------------
# IGNITION_MESSAGE constant
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    def test_ignition_message_is_nonempty_string(self):
        self.assertIsInstance(IGNITION_MESSAGE, str)
        self.assertTrue(IGNITION_MESSAGE)


# ---------------------------------------------------------------------------
# TmuxHost — ignite
# ---------------------------------------------------------------------------

class TestTmuxHostIgnite(unittest.TestCase):
    def test_workspace_ignite_targets_existing_runner_pane(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_workspace(root, {
                "schema_version": 1,
                "session": session_name(root),
                "host": "tmux",
                "order": ["claude", "codex"],
                "panes": {"claude": "%1", "codex": "%2"},
                "active_runner": "claude",
                "terminal_opened": True,
            })
            calls = []

            def run(cmd, **kwargs):
                calls.append(cmd)
                if "display-message" in cmd:
                    return _ok_proc(stdout=session_name(root) + "\n")
                return _ok_proc()

            TmuxHost(run=run).ignite(session_name(root), root, ["codex"],
                                     runner="codex")
            self.assertFalse(any("new-session" in call for call in calls))
            send = next(call for call in calls if "send-keys" in call)
            self.assertEqual(send[send.index("-t") + 1], "%2")
            self.assertIn(IGNITION_MESSAGE, send)
            self.assertEqual(load_workspace(root)["active_runner"], "codex")

    def test_ignite_issues_new_session_then_send_keys(self):
        """ignite must call new-session then send-keys with correct arguments."""
        calls = []

        def run(cmd, **kwargs):
            calls.append(cmd)
            return _ok_proc()

        h = TmuxHost(run=run)
        h.ignite("boss1", "/tmp/mydir", ["bash"])

        self.assertEqual(len(calls), 2)
        # new-session
        ns = calls[0]
        self.assertEqual(ns[0], "tmux")
        self.assertIn("new-session", ns)
        self.assertIn("-s", ns)
        self.assertEqual(ns[ns.index("-s") + 1], "boss1")
        self.assertIn("-c", ns)
        self.assertEqual(ns[ns.index("-c") + 1], "/tmp/mydir")
        self.assertIn("bash", ns)
        # send-keys
        sk = calls[1]
        self.assertEqual(sk[0], "tmux")
        self.assertIn("send-keys", sk)
        self.assertIn("-t", sk)
        self.assertEqual(sk[sk.index("-t") + 1], "=boss1:")
        self.assertIn(IGNITION_MESSAGE, sk)
        self.assertIn("Enter", sk)

    def test_ignite_uses_capture_output_and_text(self):
        """All run calls must use capture_output=True, text=True."""
        kwargs_seen = []

        def run(cmd, **kwargs):
            kwargs_seen.append(kwargs)
            return _ok_proc()

        TmuxHost(run=run).ignite("s", "/cwd", [])
        for kw in kwargs_seen:
            self.assertTrue(kw.get("capture_output"))
            self.assertTrue(kw.get("text"))

    def test_ignite_raises_host_error_on_new_session_failure(self):
        """Nonzero rc from new-session raises HostError with stderr excerpt."""
        call_count = [0]

        def run(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _err_proc(rc=1, stderr="session already exists")
            return _ok_proc()

        h = TmuxHost(run=run)
        with self.assertRaises(HostError) as ctx:
            h.ignite("dup", "/x", [])
        self.assertIn("session already exists", str(ctx.exception))

    def test_ignite_raises_host_error_on_send_keys_failure(self):
        """Nonzero rc from send-keys also raises HostError."""
        call_count = [0]

        def run(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                return _err_proc(rc=1, stderr="no such session")
            return _ok_proc()

        h = TmuxHost(run=run)
        with self.assertRaises(HostError) as ctx:
            h.ignite("gone", "/x", [])
        self.assertIn("no such session", str(ctx.exception))

    def test_ignite_wraps_oserror_as_host_error(self):
        """OSError from the subprocess seam becomes HostError."""
        def run(cmd, **kwargs):
            raise OSError("tmux not found")

        h = TmuxHost(run=run)
        with self.assertRaises(HostError):
            h.ignite("s", "/x", [])


# ---------------------------------------------------------------------------
# TmuxHost — alive / tail / kill
# ---------------------------------------------------------------------------

class TestTmuxHostAlive(unittest.TestCase):
    def test_alive_true_when_has_session_returns_zero(self):
        h = TmuxHost(run=lambda cmd, **kw: _ok_proc())
        self.assertTrue(h.alive("myboss"))

    def test_alive_false_when_has_session_returns_nonzero(self):
        h = TmuxHost(run=lambda cmd, **kw: _err_proc())
        self.assertFalse(h.alive("myboss"))

    def test_alive_issues_has_session_command(self):
        cmds = []
        h = TmuxHost(run=lambda cmd, **kw: (cmds.append(cmd), _ok_proc())[1])
        h.alive("abc")
        self.assertIn("has-session", cmds[0])
        self.assertIn("-t", cmds[0])
        self.assertEqual(cmds[0][cmds[0].index("-t") + 1], "=abc")


class TestTmuxHostTail(unittest.TestCase):
    def test_tail_returns_last_n_lines_of_stdout(self):
        output = "\n".join(f"line{i}" for i in range(20))

        h = TmuxHost(run=lambda cmd, **kw: _ok_proc(stdout=output))
        result = h.tail("s", lines=5)
        self.assertEqual(result, "\n".join(f"line{i}" for i in range(15, 20)))

    def test_tail_returns_empty_string_on_nonzero_rc(self):
        h = TmuxHost(run=lambda cmd, **kw: _err_proc())
        self.assertEqual(h.tail("s"), "")

    def test_tail_issues_capture_pane_command(self):
        cmds = []
        h = TmuxHost(run=lambda cmd, **kw: (cmds.append(cmd), _ok_proc())[1])
        h.tail("mysess")
        self.assertIn("capture-pane", cmds[0])
        self.assertIn("-p", cmds[0])
        self.assertIn("-t", cmds[0])

    def test_tail_default_lines_is_40(self):
        output = "\n".join(f"L{i}" for i in range(100))
        h = TmuxHost(run=lambda cmd, **kw: _ok_proc(stdout=output))
        result = h.tail("s")
        self.assertEqual(result, "\n".join(f"L{i}" for i in range(60, 100)))


class TestTmuxHostKill(unittest.TestCase):
    def test_kill_issues_kill_session_command(self):
        cmds = []
        h = TmuxHost(run=lambda cmd, **kw: (cmds.append(cmd), _ok_proc())[1])
        h.kill("dying")
        self.assertEqual(len(cmds), 1)
        self.assertIn("kill-session", cmds[0])
        self.assertIn("-t", cmds[0])
        self.assertEqual(cmds[0][cmds[0].index("-t") + 1], "=dying")


# ---------------------------------------------------------------------------
# TmuxHost — attach_hint
# ---------------------------------------------------------------------------

class TestTmuxHostAttachHint(unittest.TestCase):
    def test_attach_hint_format(self):
        h = TmuxHost()
        self.assertEqual(h.attach_hint("myname"), "tmux attach -t myname")


# ---------------------------------------------------------------------------
# HeadlessHost — ignite
# ---------------------------------------------------------------------------

class TestHeadlessHostIgnite(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.log_dir = Path(self._tmp.name) / "logs"

    def test_ignite_passes_argv_plus_ignition_to_popen(self):
        """popen must receive argv + [IGNITION_MESSAGE] as first positional arg."""
        popen_calls = []

        def fake_popen(argv, **kwargs):
            popen_calls.append((argv, kwargs))
            return _fake_popen()

        h = HeadlessHost(self.log_dir, popen=fake_popen)
        h.ignite("run1", "/mydir", ["python3", "boss.py"])

        self.assertEqual(len(popen_calls), 1)
        argv_used, kwargs_used = popen_calls[0]
        self.assertEqual(argv_used, ["python3", "boss.py", IGNITION_MESSAGE])

    def test_ignite_passes_cwd_as_string(self):
        popen_calls = []

        def fake_popen(argv, **kwargs):
            popen_calls.append(kwargs)
            return _fake_popen()

        h = HeadlessHost(self.log_dir, popen=fake_popen)
        h.ignite("run2", Path("/mydir"), [])
        self.assertEqual(popen_calls[0]["cwd"], "/mydir")

    def test_ignite_wires_stdout_to_named_log_file(self):
        """stdout in popen kwargs must be an open file named <name>.log."""
        popen_calls = []

        def fake_popen(argv, **kwargs):
            popen_calls.append(kwargs)
            return _fake_popen()

        h = HeadlessHost(self.log_dir, popen=fake_popen)
        h.ignite("myrun", "/x", [])

        fh = popen_calls[0]["stdout"]
        self.assertIn("myrun.log", fh.name)
        fh.close()

    def test_ignite_sets_stderr_to_stdout(self):
        popen_calls = []

        def fake_popen(argv, **kwargs):
            popen_calls.append(kwargs)
            return _fake_popen()

        h = HeadlessHost(self.log_dir, popen=fake_popen)
        h.ignite("r3", "/x", [])
        self.assertEqual(popen_calls[0]["stderr"], subprocess.STDOUT)

    def test_ignite_creates_log_dir_parents(self):
        nested = self.log_dir / "a" / "b"
        h = HeadlessHost(nested, popen=lambda *a, **k: _fake_popen())
        h.ignite("deep", "/x", [])
        self.assertTrue(nested.is_dir())

    def test_ignite_wraps_oserror_as_host_error(self):
        def bad_popen(argv, **kwargs):
            raise OSError("no such file")

        h = HeadlessHost(self.log_dir, popen=bad_popen)
        with self.assertRaises(HostError):
            h.ignite("err", "/x", ["nope"])


# ---------------------------------------------------------------------------
# HeadlessHost — alive / tail / kill
# ---------------------------------------------------------------------------

class TestHeadlessHostAlive(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.log_dir = Path(self._tmp.name)

    def test_alive_true_while_process_running(self):
        handle = _fake_popen(poll_result=None)
        h = HeadlessHost(self.log_dir, popen=lambda *a, **k: handle)
        h.ignite("run", "/x", [])
        self.assertTrue(h.alive("run"))

    def test_alive_false_after_process_exits(self):
        handle = _fake_popen(poll_result=0)
        h = HeadlessHost(self.log_dir, popen=lambda *a, **k: handle)
        h.ignite("run", "/x", [])
        self.assertFalse(h.alive("run"))

    def test_alive_false_for_unknown_name(self):
        h = HeadlessHost(self.log_dir, popen=lambda *a, **k: _fake_popen())
        self.assertFalse(h.alive("never-started"))

    def test_restarted_host_adopts_surviving_process_via_pid_file(self):
        # In-memory handles die with the conductor; without the persisted
        # pid a restart would ignite a SECOND boss (Rule 38 hazard —
        # review finding, W1-P4 final).
        handle = _fake_popen(poll_result=None)
        handle.pid = 4242
        first = HeadlessHost(self.log_dir, popen=lambda *a, **k: handle)
        first.ignite("run", "/x", [])
        probes = []
        reborn = HeadlessHost(self.log_dir,
                              popen=lambda *a, **k: _fake_popen(),
                              pid_alive=lambda p: probes.append(p) or True)
        self.assertTrue(reborn.alive("run"))
        self.assertEqual(probes, [4242])
        dead = HeadlessHost(self.log_dir,
                            popen=lambda *a, **k: _fake_popen(),
                            pid_alive=lambda p: False)
        self.assertFalse(dead.alive("run"))


class TestHeadlessHostTail(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.log_dir = Path(self._tmp.name)

    def _make_log(self, name: str, content: str) -> Path:
        p = self.log_dir / f"{name}.log"
        p.write_text(content, encoding="utf-8")
        return p

    def test_tail_returns_last_n_lines_from_log(self):
        self._make_log("r", "\n".join(f"line{i}" for i in range(20)))
        h = HeadlessHost(self.log_dir, popen=lambda *a, **k: _fake_popen())
        result = h.tail("r", lines=3)
        self.assertEqual(result, "line17\nline18\nline19")

    def test_tail_returns_empty_string_if_log_absent(self):
        h = HeadlessHost(self.log_dir, popen=lambda *a, **k: _fake_popen())
        self.assertEqual(h.tail("no-log"), "")

    def test_tail_default_lines_is_40(self):
        self._make_log("big", "\n".join(f"L{i}" for i in range(100)))
        h = HeadlessHost(self.log_dir, popen=lambda *a, **k: _fake_popen())
        result = h.tail("big")
        self.assertEqual(result, "\n".join(f"L{i}" for i in range(60, 100)))


class TestHeadlessHostKill(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.log_dir = Path(self._tmp.name)

    def test_kill_calls_terminate_on_running_handle(self):
        handle = _fake_popen(poll_result=None)
        h = HeadlessHost(self.log_dir, popen=lambda *a, **k: handle)
        h.ignite("proc", "/x", [])
        h.kill("proc")
        handle.terminate.assert_called_once()

    def test_kill_is_noop_for_unknown_name(self):
        h = HeadlessHost(self.log_dir, popen=lambda *a, **k: _fake_popen())
        # must not raise
        h.kill("phantom")

    def test_kill_swallows_errors_from_terminate(self):
        handle = _fake_popen(poll_result=None)
        handle.terminate.side_effect = OSError("already gone")
        h = HeadlessHost(self.log_dir, popen=lambda *a, **k: handle)
        h.ignite("noisy", "/x", [])
        h.kill("noisy")  # must not propagate


# ---------------------------------------------------------------------------
# pick_host
# ---------------------------------------------------------------------------

class TestPickHost(unittest.TestCase):
    def test_tmux_preference_with_binary_present_returns_tmux(self):
        result = pick_host("tmux", which=lambda name: "/usr/bin/tmux")
        self.assertEqual(result, "tmux")

    def test_tmux_preference_falls_back_to_headless_when_absent(self):
        """Silent degradation: degrade to invisible operation rather than fail."""
        result = pick_host("tmux", which=lambda name: None)
        self.assertEqual(result, "headless")

    def test_headless_preference_stays_headless_regardless_of_tmux(self):
        result = pick_host("headless", which=lambda name: "/usr/bin/tmux")
        self.assertEqual(result, "headless")

    def test_headless_preference_stays_headless_when_tmux_absent(self):
        result = pick_host("headless", which=lambda name: None)
        self.assertEqual(result, "headless")

    def test_unknown_preference_raises_host_error(self):
        with self.assertRaises(HostError):
            pick_host("screen", which=lambda name: None)

    def test_unknown_preference_raises_host_error_even_if_binary_present(self):
        with self.assertRaises(HostError):
            pick_host("screen", which=lambda name: "/usr/bin/screen")


# ---------------------------------------------------------------------------
# Live smoke test (env-gated, skipped by default)
# ---------------------------------------------------------------------------

@unittest.skipUnless(os.environ.get("DANZA_LIVE_TMUX") == "1",
                     "live tmux smoke (set DANZA_LIVE_TMUX=1 to enable)")
class TestTmuxHostLive(unittest.TestCase):
    def test_ignite_alive_tail_kill_roundtrip(self):
        """Real tmux: ignite a bash session, confirm alive, poll tail for the
        ignition message, then kill and confirm dead. Under ~10 s."""
        with tempfile.TemporaryDirectory() as tmp:
            session = f"danza-smoke-{os.getpid()}"
            h = TmuxHost()
            try:
                h.ignite(session, tmp, ["bash"])
                self.assertTrue(h.alive(session),
                                "session should be alive after ignite")
                # poll up to ~5 s for the ignition message to appear
                deadline = time.monotonic() + 5.0
                found = False
                while time.monotonic() < deadline:
                    output = h.tail(session, lines=40)
                    if IGNITION_MESSAGE in output:
                        found = True
                        break
                    time.sleep(0.2)
                self.assertTrue(found,
                                f"ignition message not found in tail: {output!r}")
            finally:
                h.kill(session)
            self.assertFalse(h.alive(session),
                             "session should be dead after kill")


if __name__ == "__main__":
    unittest.main()
