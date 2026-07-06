"""W1-P4 conductor loop: ignition wiring, pidfile rail, stall/valve
surfacing, JSONL log — all against temp team-state fixtures with an
injected clock and a fake host. The conductor must never write
team-state (postman discipline, design spec section 7)."""
import json
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa
from danzaboss.kernel.state import StateManager
from danzaboss.workstation import runners as runners_mod
from danzaboss.workstation.conductor import (LOG_RELPATH, PIDFILE_RELPATH,
                                             TEAM_STATE_RELPATH, Action,
                                             Conductor, ConductorError,
                                             acquire_pidfile, release_pidfile,
                                             session_name)


class FakeHost:
    """Records ignitions; liveness and tail are test-settable."""

    def __init__(self):
        self.ignites = []
        self.alive_now = False
        self.tail_now = ""
        self.killed = []

    def ignite(self, name, cwd, argv):
        self.ignites.append((name, str(cwd), list(argv)))
        self.alive_now = True

    def alive(self, name):
        return self.alive_now

    def tail(self, name, lines=40):
        return self.tail_now

    def kill(self, name):
        self.killed.append(name)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class LoopFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / ".danza" / "runtime").mkdir(parents=True)
        runners_mod.save_runners(
            self.root, runners_mod.default_config({"claude": True,
                                                   "codex": False}))
        self.manager = StateManager(str(self.root / TEAM_STATE_RELPATH))
        self.manager.init(mode="relay", current_boss="claude")
        self.host = FakeHost()
        self.clock = FakeClock()

    def conductor(self, **over):
        kwargs = {"clock": self.clock, "sleep": lambda s: None,
                  "poll_interval": 0.0}
        kwargs.update(over)
        return Conductor(self.root, self.host, **kwargs)

    def log_events(self):
        path = self.root / LOG_RELPATH
        if not path.exists():
            return []
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines()]


class Ignition(LoopFixture):
    def test_ready_ignites_once_then_waits(self):
        con = self.conductor()
        self.assertIs(con.tick(), Action.IGNITE)
        self.assertEqual(len(self.host.ignites), 1)
        name, cwd, argv = self.host.ignites[0]
        self.assertEqual(name, session_name(self.root))
        self.assertEqual(cwd, str(self.root))
        self.assertEqual(argv, ["claude"])  # tmux host -> interactive argv
        self.assertIs(con.tick(), Action.WAIT)  # session alive: no re-ignite
        self.assertEqual(len(self.host.ignites), 1)
        self.assertIn("ignite", {e["event"] for e in self.log_events()})

    def test_headless_config_uses_headless_argv(self):
        config = runners_mod.load_runners(self.root)
        config["session_host"] = "headless"
        runners_mod.save_runners(self.root, config)
        self.conductor().tick()
        _, _, argv = self.host.ignites[0]
        self.assertEqual(argv, ["claude", "-p", "--output-format", "json"])

    def test_session_mode_override_beats_config(self):
        # pick_host may degrade tmux -> headless when tmux is absent; the
        # RESOLVED mode must drive argv or the headless host gets an
        # interactive claude (review finding, W1-P4 final).
        self.conductor(session_mode="headless").tick()
        _, _, argv = self.host.ignites[0]
        self.assertEqual(argv, ["claude", "-p", "--output-format", "json"])

    def test_null_boss_fails_at_construction(self):
        runners_mod.save_runners(
            self.root, runners_mod.default_config({"claude": False,
                                                   "codex": False}))
        with self.assertRaises(runners_mod.RunnerError):
            self.conductor()

    def test_relay_continues_after_handoff(self):
        # handoff() leaves awaiting_handoff; the conductor must ignite
        # the next boss once the departing session exits (deadlock fix).
        con = self.conductor()
        con.tick()                                     # ignite turn 0
        self.manager.transition(to_status="in_progress", actor="claude")
        self.manager.handoff("claude")                 # -> awaiting_handoff
        self.host.alive_now = False                    # session exits
        con.tick()                                     # observe death
        self.assertEqual(len(self.host.ignites), 2)    # next boss ignited

    def test_orphaned_turn_surfaced_in_session_end(self):
        con = self.conductor()
        con.tick()                                     # ignite
        self.manager.transition(to_status="in_progress", actor="claude")
        self.host.alive_now = False                    # dies mid-turn
        self.assertIs(con.tick(), Action.WAIT)
        ends = [e for e in self.log_events() if e["event"] == "session_end"]
        self.assertTrue(ends and ends[-1]["orphaned_turn"])

    def test_never_writes_team_state(self):
        state_path = self.root / TEAM_STATE_RELPATH
        before = state_path.read_text(encoding="utf-8")
        con = self.conductor()
        con.tick()
        con.tick()
        self.assertEqual(state_path.read_text(encoding="utf-8"), before)


class Terminals(LoopFixture):
    def test_blocked_halts_with_logged_reason(self):
        self.manager.transition(to_status="blocked", actor="claude")
        con = self.conductor()
        self.assertIs(con.run(max_ticks=3), Action.HALT_BLOCKED)
        events = [e for e in self.log_events() if e["event"] == "halt_blocked"]
        self.assertTrue(events)
        self.assertEqual(len(self.host.ignites), 0)

    def test_done_stops(self):
        self.manager.transition(to_status="in_progress", actor="claude")
        self.manager.transition(to_status="done", actor="claude")
        self.assertIs(self.conductor().run(max_ticks=3), Action.STOP_DONE)

    def test_valve_two_dead_sessions_without_progress(self):
        con = self.conductor()
        for _ in range(2):
            con.tick()                 # ignite
            self.host.alive_now = False  # dies without advancing the turn
            con.tick()                 # observe death -> re-ignite or valve
        result = con.tick()
        self.assertIs(result, Action.STOP_VALVE)
        self.assertIn("stop_valve", {e["event"] for e in self.log_events()})

    def test_turn_advance_resets_valve(self):
        con = self.conductor()
        con.tick()                     # ignite (turn 0)
        self.host.alive_now = False
        con.tick()                     # death without advance -> 1 strike
        self.manager.transition(to_status="in_progress", actor="claude")
        self.manager.handoff("claude")  # turn 0 -> 1
        self.manager.transition(to_status="ready", actor="claude")
        con.tick()                     # adopt ready state
        self.host.alive_now = False
        result = con.tick()            # death AFTER advance -> counter reset
        self.assertIsNot(result, Action.STOP_VALVE)


class StallSurfacing(LoopFixture):
    def test_stall_logged_once_and_rearmed_on_output(self):
        con = self.conductor(stall_minutes=1)
        con.tick()                     # ignite
        self.clock.now += 61
        con.tick()
        con.tick()
        stalls = [e for e in self.log_events() if e["event"] == "stall"]
        self.assertEqual(len(stalls), 1)       # once per episode
        self.assertEqual(self.host.killed, [])  # surfaced, never killed
        self.host.tail_now = "new output"
        con.tick()                     # change re-arms detection
        self.clock.now += 61
        con.tick()
        stalls = [e for e in self.log_events() if e["event"] == "stall"]
        self.assertEqual(len(stalls), 2)


class Pidfile(LoopFixture):
    def test_second_live_conductor_refused(self):
        acquire_pidfile(self.root, pid=111, alive=lambda p: True)
        with self.assertRaises(ConductorError):
            acquire_pidfile(self.root, pid=222, alive=lambda p: True)

    def test_stale_pid_reclaimed(self):
        acquire_pidfile(self.root, pid=111, alive=lambda p: True)
        path = acquire_pidfile(self.root, pid=222, alive=lambda p: False)
        self.assertEqual(path.read_text(encoding="utf-8").strip(), "222")

    def test_run_releases_pidfile(self):
        self.manager.transition(to_status="blocked", actor="claude")
        self.conductor().run(max_ticks=2)
        self.assertFalse((self.root / PIDFILE_RELPATH).exists())

    def test_release_leaves_foreign_pidfile(self):
        acquire_pidfile(self.root, pid=111, alive=lambda p: True)
        release_pidfile(self.root, pid=222)
        self.assertTrue((self.root / PIDFILE_RELPATH).exists())


class SessionName(unittest.TestCase):
    def test_dots_and_colons_sanitized_for_tmux(self):
        with tempfile.TemporaryDirectory(suffix="my.app") as tmp:
            name = session_name(tmp)
            self.assertTrue(name.startswith("danza-"))
            self.assertNotIn(".", name)
            self.assertNotIn(":", name)


class Degraded(LoopFixture):
    def test_corrupt_team_state_survived_as_wait(self):
        (self.root / TEAM_STATE_RELPATH).write_text("{not json",
                                                    encoding="utf-8")
        con = self.conductor()
        self.assertIs(con.tick(), Action.WAIT)
        self.assertIn("state_error", {e["event"] for e in self.log_events()})

    def test_unknown_team_state_key_survived_as_wait(self):
        # TeamState(**raw) raises TypeError on unknown keys — must be
        # caught, not crash the daemon (review finding, W1-P4 final).
        path = self.root / TEAM_STATE_RELPATH
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["notes"] = "written by an external tool"
        path.write_text(json.dumps(doc), encoding="utf-8")
        con = self.conductor()
        self.assertIs(con.tick(), Action.WAIT)
        self.assertIn("state_error", {e["event"] for e in self.log_events()})

    def test_missing_registry_fails_closed(self):
        (self.root / runners_mod.RUNNERS_RELPATH).unlink()
        with self.assertRaises(runners_mod.RunnerError):
            self.conductor()


if __name__ == "__main__":
    unittest.main()
