"""W1 conductor — the deterministic relay postman (design spec section 7).

Watches team-state.json, ignites fresh boss sessions, and stops on the
states that need a human. It is a POSTMAN, not a boss: it reads turn
state through the kernel's StateManager and writes only its own JSONL
log and pidfile — it never holds a turn, so Rule 38 cannot be violated
from this seat. The decision core below is pure so every rail (valve,
stall, halt) is unit-testable without processes; the seat stays
swappable for an intelligent conductor (Hermes) later.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import time
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from danzaboss.cortex.inject import est_tokens
from danzaboss.kernel.state import StateError, StateManager, TeamState
from danzaboss.workstation import planner as planner_mod
from danzaboss.workstation import routing as routing_mod
from danzaboss.workstation import runners as runners_mod
from danzaboss.workstation import turnbrief as turnbrief_mod
from danzaboss.workstation.workspace import session_name as workspace_session_name


class ConductorError(RuntimeError):
    """Conductor cannot run safely (pidfile conflict, no registry)."""


class Action(str, Enum):
    IGNITE = "ignite"          # spawn a fresh boss session this tick
    WAIT = "wait"              # someone is (or should be) working
    HALT_BLOCKED = "halt_blocked"   # hard stop / Rule 18 loop — human needed
    STOP_DONE = "stop_done"    # goal met; relay over
    STOP_VALVE = "stop_valve"  # sessions dying without progress — stop relay


STALL_MINUTES = 10       # spec section 7 default T
DEAD_SESSION_VALVE = 2   # spec section 7 default K

# Appended to a routed, argv-activation runner's command in attachable
# modes so the ignited session actually starts its turn (SKILL.md trigger).
IGNITION_PHRASE = "Who's the Boss?"


@dataclass(frozen=True)
class Watch:
    """The conductor's between-tick bookkeeping. Deliberately the ONLY
    state it owns (beyond the log): a crashed conductor restarts with a
    fresh Watch, re-reads team-state, and resumes — statelessness IS the
    crash-recovery story (and what makes the seat swappable)."""
    session_alive: bool
    turn_at_ignite: int | None
    dead_sessions: int
    last_change_monotonic: float
    last_tail: str


def decide(state: TeamState, watch: Watch) -> Action:
    """Pure decision table — same discipline as kernel.scheduler.decide.

    Order matters: human-needed states outrank the valve, and the valve
    outranks ignition (a relay burning sessions must not get one more).

    "awaiting_handoff" ignites too: kernel handoff() leaves that status
    as the departing boss's FINAL act (state.py), so once its session is
    gone the baton already belongs to current_boss and nobody else will
    ever flip the status — waiting here would deadlock the relay. With a
    session still alive it means the departing boss is wrapping up: wait."""
    if state.status == "blocked":
        return Action.HALT_BLOCKED
    if state.status == "done":
        return Action.STOP_DONE
    if watch.dead_sessions >= DEAD_SESSION_VALVE:
        return Action.STOP_VALVE
    if (state.status in ("ready", "awaiting_handoff")
            and not watch.session_alive):
        return Action.IGNITE
    return Action.WAIT


def observe_session_end(state: TeamState, watch: Watch) -> Watch:
    """Account for a session found dead. A death WITHOUT a turn_number
    advance counts toward the valve (the session did no relay work); an
    advancing death is normal relay churn and resets the count."""
    advanced = (watch.turn_at_ignite is None
                or state.turn_number != watch.turn_at_ignite)
    return replace(watch, session_alive=False,
                   dead_sessions=0 if advanced else watch.dead_sessions + 1)


def is_stalled(watch: Watch, now_monotonic: float, *,
               stall_minutes: int = STALL_MINUTES) -> bool:
    """Rule 33, machine side: a LIVE session with no observed change for
    the threshold. Stalls are surfaced, never auto-killed — the human
    decides whether it is thinking or wedged (spec section 7)."""
    if not watch.session_alive:
        return False
    return now_monotonic - watch.last_change_monotonic >= stall_minutes * 60


TEAM_STATE_RELPATH = Path(".danza") / "runtime" / "team-state.json"
PIDFILE_RELPATH = Path(".danza") / "runtime" / "conductor.pid"
LOG_RELPATH = Path(".danza") / "runtime" / "conductor-log.jsonl"


def session_name(root: str | os.PathLike) -> str:
    """`danza-<project>` (spec section 7) — stable per repo so a
    restarted conductor finds the session it left behind. Sanitized:
    tmux rejects or rewrites '.'/':' in session names AND parses them
    as window/pane separators in -t targets, so a repo named
    'myapp.web' would create one name and probe another forever."""
    return workspace_session_name(root)


def _pid_alive(pid: int) -> bool:
    """Signal-0 probe. PermissionError means the pid exists but is not
    ours — still alive for single-instance purposes."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_pidfile(root: str | os.PathLike, *, pid: int | None = None,
                    alive: Callable[[int], bool] = _pid_alive) -> Path:
    """Single-instance rail: two conductors would double-ignite (spec
    section 7). A pidfile holding a LIVE pid refuses; a stale one is
    reclaimed (crashes must not require manual cleanup)."""
    pid = os.getpid() if pid is None else pid
    path = Path(root) / PIDFILE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):  # one reclaim attempt, then give up
        try:
            # O_EXCL closes the check-then-write race: two conductors
            # starting together must not both pass an exists() check.
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            text = path.read_text(encoding="utf-8").strip()
            existing = int(text) if text.isdigit() else None
            if existing is not None and alive(existing):
                raise ConductorError(
                    f"another conductor is running (pid {existing}); two "
                    "conductors would double-ignite")
            path.unlink(missing_ok=True)  # stale: reclaim and retry
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"{pid}\n")
        return path
    raise ConductorError("pidfile contention: could not claim "
                         f"{path} after reclaiming a stale pid")


def release_pidfile(root: str | os.PathLike, *,
                    pid: int | None = None) -> None:
    """Remove the pidfile only if it still holds OUR pid — never rip out
    a newer conductor's claim."""
    pid = os.getpid() if pid is None else pid
    path = Path(root) / PIDFILE_RELPATH
    if path.exists() and path.read_text(encoding="utf-8").strip() == str(pid):
        path.unlink()


class Conductor:
    """One tick = read state, refresh the watch, decide, act. The loop
    adds nothing but sleep and the pidfile — all behavior lives in
    tick() so tests drive it deterministically."""

    _TERMINAL = frozenset({Action.HALT_BLOCKED, Action.STOP_DONE,
                           Action.STOP_VALVE})

    def __init__(self, root: str | os.PathLike, host: Any, *,
                 session_mode: str | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 poll_interval: float = 2.0,
                 stall_minutes: int = STALL_MINUTES) -> None:
        self._root = Path(root)
        self._host = host
        self._clock = clock
        self._sleep = sleep
        self._poll_interval = poll_interval
        self._stall_minutes = stall_minutes
        # Fail closed at construction: no registry / no boss / no usable
        # argv means no relay (the UI button stays dark with a reason —
        # spec section 7) — not a RunnerError ten minutes into a run.
        self._config = runners_mod.load_runners(root)
        # The RESOLVED host mode must come from whoever built `host`
        # (pick_host may have degraded tmux -> headless); trusting the
        # raw config here would feed interactive argv to a headless host.
        self._mode = session_mode or self._config.get("session_host")
        # The configured boss remains a required registry invariant, but the
        # conductor never substitutes it for a missing kernel route.
        runners_mod.boss_runner(self._config)   # no boss => no relay
        self._argv_for(self._config["boss"])    # unusable argv => no relay
        self._manager = StateManager(str(self._root / TEAM_STATE_RELPATH))
        self._name = session_name(root)
        self._watch = Watch(session_alive=False, turn_at_ignite=None,
                            dead_sessions=0,
                            last_change_monotonic=clock(), last_tail="")
        self._last_signature: tuple = ()
        self._stall_logged = False

    # -- the postman's ONLY writes ---------------------------------------
    def log(self, event: str, **fields: Any) -> None:
        """Append one JSONL line. This log plus the pidfile are the
        conductor's entire write surface (postman discipline)."""
        path = self._root / LOG_RELPATH
        path.parent.mkdir(parents=True, exist_ok=True)
        line = {"ts": _dt.datetime.now(_dt.timezone.utc)
                .isoformat(timespec="seconds"),
                "event": event, **fields}
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, sort_keys=True) + "\n")

    # -- internals --------------------------------------------------------
    def _argv_for(self, name: str, *, routed: bool = False) -> list[str]:
        """The named runner's argv for the RESOLVED mode (constructor),
        not isinstance, so test doubles and future hosts need no
        special-casing. Headless with an empty headless argv fails closed
        (the runners.headless_argv rule). In attachable modes an
        argv-activation runner gets the ignition phrase appended ONLY when
        routing chose it — the routed session must actually start its
        turn, while the no-routing path keeps today's bare argv (zero
        behavior change for existing users)."""
        entry = self._config["runners"][name]
        if self._mode == "headless":
            argv = list(entry["headless"])
            if not argv:
                raise runners_mod.RunnerError(
                    f"runner {name!r} does not support headless mode "
                    f"(headless argv is empty)")
            return argv
        argv = list(entry["interactive"])
        if routed and entry.get("activation") == "argv":
            argv.append(IGNITION_PHRASE)
        return argv

    def _route(self, state: TeamState) -> tuple[str, str, dict] | None:
        """(runner, work_type, plan_data) for this ignition. routing.json and
        plan.json are re-read on EVERY ignite — setup edits apply from the
        next turn, never mid-session (Decision 7). Routing and plan defects
        fail closed with a logged error. Choosing a fallback boss would make
        the postman a scheduler and could ignite work after a terminal kernel
        conclusion. plan_data rides back with the routing result so the P4.1
        T4 turn-brief compiler can reuse the same read instead of a second
        (potentially inconsistent) load of plan.json."""
        try:
            routing = routing_mod.load_routing(self._root)
            plan_data = json.loads(
                (self._root / planner_mod.PLAN_JSON_RELPATH)
                .read_text(encoding="utf-8"))
            runner, work_type = routing_mod.route_turn(routing, plan_data, state)
            return runner, work_type, plan_data
        except (runners_mod.RunnerError, OSError, ValueError) as exc:
            # RoutingError and JSONDecodeError are ValueErrors; a missing
            # plan.json is an OSError; a re-validated registry gone bad is
            # a RunnerError.
            self.log("routing_error", reason=str(exc))
            return None

    def _compile_turn_brief(self, state: TeamState, plan_data: dict,
                            runner: str, work_type: str | None) -> None:
        """Compile and write the P4.1 T4 turn brief before ignite. A brief
        must NEVER block a turn: any failure here (cortex down, a bad plan
        shape, a disk error) is logged and swallowed, never raised."""
        try:
            path = turnbrief_mod.write_turn_brief(
                self._root, state, plan_data, runner, work_type)
            text = path.read_text(encoding="utf-8")
            self.log("turn_brief", bytes=len(text.encode("utf-8")),
                     tokens=est_tokens(text))
        except Exception as exc:  # noqa: BLE001 - fail-open by design
            self.log("turn_brief_error", reason=str(exc))

    def _refresh_watch(self, state: TeamState) -> None:
        alive = self._host.alive(self._name)
        if self._watch.session_alive and not alive:
            self._watch = observe_session_end(state, self._watch)
            # A death mid-turn (in_progress) is an ORPHANED turn: nothing
            # will ever flip the status back, the valve only counts from
            # ignition cycles, and is_stalled needs a live session — so
            # this log line is the one surface the human gets (Rule 33).
            self.log("session_end", turn_number=state.turn_number,
                     dead_sessions=self._watch.dead_sessions,
                     status=state.status,
                     orphaned_turn=state.status == "in_progress")
        elif alive and not self._watch.session_alive:
            # Conductor restarted while the session survived: adopt it
            # (crash recovery by statelessness, spec section 7).
            self._watch = replace(self._watch, session_alive=True,
                                  turn_at_ignite=state.turn_number)
        tail = self._host.tail(self._name) if alive else ""
        try:
            mtime = (self._root / TEAM_STATE_RELPATH).stat().st_mtime
        except OSError:
            mtime = 0.0
        signature = (mtime, tail)
        if signature != self._last_signature:
            self._last_signature = signature
            self._watch = replace(self._watch,
                                  last_change_monotonic=self._clock(),
                                  last_tail=tail)
            self._stall_logged = False

    # -- one poll ----------------------------------------------------------
    def tick(self) -> Action:
        try:
            state = self._manager.load()
        except (StateError, TypeError, ValueError) as exc:
            # An unreadable team-state must not crash the daemon: wait
            # and keep reporting until a boss or human repairs it.
            # TypeError covers TeamState(**raw) choking on unknown keys.
            self.log("state_error", error=str(exc))
            return Action.WAIT
        self._refresh_watch(state)
        if (is_stalled(self._watch, self._clock(),
                       stall_minutes=self._stall_minutes)
                and not self._stall_logged):
            self.log("stall", session=self._name,
                     minutes=self._stall_minutes)
            self._stall_logged = True  # once per episode
        action = decide(state, self._watch)
        if action is Action.IGNITE:
            routed = self._route(state)
            if routed is None:
                return Action.WAIT
            runner, work_type, plan_data = routed
            argv = self._argv_for(runner, routed=work_type is not None)
            self._compile_turn_brief(state, plan_data, runner, work_type)
            self._host.ignite(self._name, self._root, argv, runner=runner)
            self._watch = replace(self._watch, session_alive=True,
                                  turn_at_ignite=state.turn_number,
                                  last_change_monotonic=self._clock())
            self._stall_logged = False
            self.log("ignite", session=self._name, argv=argv,
                     turn_number=state.turn_number, boss=state.current_boss,
                     runner=runner, work_type=work_type)
        elif action in self._TERMINAL:
            self.log(action.value, status=state.status,
                     dead_sessions=self._watch.dead_sessions)
        return action

    # -- the loop -----------------------------------------------------------
    def run(self, max_ticks: int | None = None) -> Action:
        """Poll until a terminal action (or max_ticks). Pidfile held for
        the duration; released even on crash so restarts are clean."""
        acquire_pidfile(self._root)
        action = Action.WAIT
        try:
            ticks = 0
            while max_ticks is None or ticks < max_ticks:
                action = self.tick()
                ticks += 1
                if action in self._TERMINAL:
                    break
                self._sleep(self._poll_interval)
        finally:
            release_pidfile(self._root)
        return action
