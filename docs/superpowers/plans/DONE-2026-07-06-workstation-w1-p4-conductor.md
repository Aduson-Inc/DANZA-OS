# W1-P4: Runners Registry, Session Hosts, Conductor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the relay loop deterministically. A runner registry (`.danza/runtime/runners.json`) says WHICH AI CLIs exist and how to invoke them; a session-host interface says HOW a boss session runs (tmux detached by default, headless-per-turn fallback); a conductor daemon (postman, not boss) watches `team-state.json`, ignites fresh sessions per turn, pauses/halts on the states that need a human, and never holds a turn itself.

**Architecture:** Three new modules under `danzaboss/workstation/`: `runners.py` (registry schema + v1 claude runner + detection), `hosts.py` (SessionHost contract + TmuxHost + HeadlessHost, all subprocess seams injectable), `conductor.py` (pure `decide()` decision table + `Conductor` loop with pidfile, stall detection, dead-session valve, JSONL log). Turn state comes exclusively from `danzaboss/kernel/state.py`'s `StateManager`/`TeamState` — the conductor re-implements NO schema validation and writes NO state.

**Tech Stack:** Python 3.10+ stdlib only. `unittest` (auto-discovered by `danzaboss/run_tests.sh`).

**Spec:** `docs/superpowers/specs/2026-07-05-workstation-onboarding-design.md` §7 (ignition & conductor), §8 (testing). Phase map: `docs/superpowers/plans/DONE-2026-07-05-workstation-w1-p1-engine-foundations.md` (this = P4). Implementers do NOT need to read either — every task below is self-contained.

**Status-vocabulary decision (recorded here so nobody re-derives it):** the design
spec narrates `ready_for_<runner>` / `awaiting_user`; the MACHINE vocabulary is
`kernel/state.py`'s `TeamState`: `status ∈ {ready, in_progress, blocked,
awaiting_handoff, done}` plus `current_boss`. The conductor keys off
`status == "ready"` + `current_boss == <runner key>`. Cadence pauses
(`awaiting_user`) are a boss/P5 behavior; the conductor surfaces `blocked` and
waits on everything that isn't `ready`/`done`.

## Model Assignment & Token Discipline

- **Per-task model in each header.** `fable (inline)` = orchestrator implements directly (conductor decision table + loop — the "important files"). `sonnet` = dispatch to a sonnet subagent (registry, host shims — fully specified below).
- **No per-task reviews and NO full-suite runs per task** (user decision): run only the task's focused test module(s); the full suite runs once at Task 6.
- **Subagents must not read** the design spec, `CLAUDE.md`, the constitution, or any module not listed in their task's Files block. This plan is the single source.
- Run steps back-to-back; don't idle past the prompt-cache TTL.

## Global Constraints

- Python 3.10+, **stdlib only** — no pip installs anywhere in `danzaboss/`.
- PEP 8, 4-space indent, `snake_case`, type hints on all public functions, docstrings that state *why*.
- **Fail closed:** validation raises (`RunnerError`, `HostError`, `ConductorError`); never continue past bad state.
- **Deterministic:** all control logic pure and unit-testable. No wall-clock reads inside decisions — clocks, sleeps, `subprocess` seams, and pid-probes are injected constructor parameters with real defaults.
- **Postman discipline (spec §7):** the conductor reads team-state via `StateManager.load()` and writes ONLY `.danza/runtime/conductor-log.jsonl` + its pidfile. It never writes team-state, work files, or handoffs, and never holds a turn.
- **Hermetic tests:** `tempfile` fixture roots only; never touch this repo's real `.danza/`; no network; no real tmux except ONE env-gated live smoke (`DANZA_LIVE_TMUX=1`), skipped by default. Tests begin with `import _bootstrap  # noqa`.
- Test run incantation (from `danzaboss/tests/`): `python3 -m unittest <module> -v`; full suite: `./danzaboss/run_tests.sh` (currently 580 OK, skipped=13).
- Commit after every task; message style `feat(workstation): W1-P4 T<n> <what>`.

---

### Task 1: Runner registry (`runners.py`)

**Model:** sonnet

**Files:**
- Create: `danzaboss/workstation/runners.py`
- Test: `danzaboss/tests/test_workstation_runners.py`

**Interfaces:**
- Consumes: nothing from this repo beyond stdlib (`json`, `os`, `shutil`, `pathlib`).
- Produces (Tasks 3–5 and P5 import these):
  - `RunnerError(ValueError)` — invalid registry / unknown runner. Fail closed.
  - `RUNNERS_RELPATH: Path` = `Path(".danza") / "runtime" / "runners.json"`
  - `SCHEMA_VERSION = 1`
  - `KNOWN_RUNNERS: dict[str, dict]` — v1 ships `"claude"` (fully usable) and `"codex"` (detect-only placeholder). Each value: `{"kind": "cli", "binary": <str>, "interactive": [<argv>], "headless": [<argv prefix>]}`. For claude: binary `"claude"`, interactive `["claude"]`, headless `["claude", "-p", "--output-format", "json"]`. For codex: binary `"codex"`, interactive `["codex"]`, headless `[]` (empty = not yet supported; validation allows it but `headless_argv` refuses it).
  - `detect_runners(which=shutil.which) -> dict[str, bool]` — presence by binary lookup, injectable for tests. (Authed-ness needs a real API call; that check is P5's `/models` ping, out of scope here — presence is the v1 signal.)
  - `default_config(detected: dict[str, bool]) -> dict` — full config dict: `{"version": 1, "boss": <first detected runner key in KNOWN_RUNNERS order, else None>, "session_host": "tmux", "permission_mode": None, "runners": {<key>: {**KNOWN_RUNNERS[key], "detected": <bool>} for all known}}`.
  - `validate_config(config: object) -> dict` — raises `RunnerError` on: non-dict, wrong/missing `version`, `boss` not None and not a key of `runners`, `session_host` not in `("tmux", "headless")`, any runner entry missing `kind`/`binary`/`interactive`/`headless` or with non-list argv fields. Returns the config on success.
  - `save_runners(root, config: dict) -> Path` — validate, then atomic write (`.tmp` + `os.replace`) to `root / RUNNERS_RELPATH`, `mkdir(parents=True, exist_ok=True)`. Generated-whole config (the /models screen writes it entire) — plain overwrite is correct, same reasoning as `compiler.write_spec`.
  - `load_runners(root) -> dict` — read + `validate_config`. Missing file raises `RunnerError` ("no runner configured; run /models") — the button stays dark with a reason (spec §7), never a silent default.
  - `boss_runner(config: dict) -> dict` — the boss's runner entry; raises `RunnerError` if `boss` is None.
  - `headless_argv(config: dict) -> list[str]` and `interactive_argv(config: dict) -> list[str]` — copies of the boss runner's argv; `headless_argv` raises `RunnerError` if the list is empty (runner has no headless mode yet).

**Test contract** (`test_workstation_runners.py` — write first, watch it fail on ImportError, then implement):
1. `detect_runners` with a stub `which` returning a path only for `"claude"` → `{"claude": True, "codex": False}`.
2. `default_config` from that detection: boss `"claude"`, `session_host "tmux"`, both runners present with `detected` flags; `validate_config` accepts it.
3. `default_config` with nothing detected → boss `None`; `boss_runner` raises `RunnerError`.
4. save→load round-trip on a temp root lands at `RUNNERS_RELPATH`, leaves no `.tmp`, and returns an equal dict.
5. `load_runners` on an empty root raises `RunnerError` mentioning "/models".
6. `validate_config` rejects: boss not in runners; bad `session_host`; runner entry with `interactive` as a string; wrong `version`.
7. `headless_argv` for claude boss = `["claude", "-p", "--output-format", "json"]`; switching boss to `"codex"` (present in runners) → `headless_argv` raises (empty argv), `interactive_argv` returns `["codex"]`.
8. Mutating the returned argv list does not mutate the config (copies out).

- [ ] Step 1: failing test → Step 2: implement → Step 3: `python3 -m unittest test_workstation_runners -v` PASS → Step 4: commit `feat(workstation): W1-P4 T1 runner registry — schema, detection, claude v1`.

---

### Task 2: Session hosts (`hosts.py`)

**Model:** sonnet

**Files:**
- Create: `danzaboss/workstation/hosts.py`
- Test: `danzaboss/tests/test_workstation_hosts.py`

**Interfaces:**
- Consumes: stdlib only (`os`, `shutil`, `subprocess`, `pathlib`, `typing`).
- Produces (conductor + P5 import these):
  - `HostError(RuntimeError)` — a host operation failed. Fail closed.
  - `IGNITION_MESSAGE = "Who's the Boss?"`
  - `class SessionHost(Protocol)` with methods:
    - `ignite(name: str, cwd: str | os.PathLike, argv: list[str]) -> None` — start a fresh boss session and deliver `IGNITION_MESSAGE`.
    - `alive(name: str) -> bool`
    - `tail(name: str, lines: int = 40) -> str` — recent output for stall detection / UI; `""` if unavailable.
    - `kill(name: str) -> None` — best-effort terminate (used by tests/P5 stop button; the conductor itself never auto-kills — spec §7 stall rule).
  - `class TmuxHost` — default POSIX implementation. Constructor `TmuxHost(run=subprocess.run)` (injectable seam). Commands it issues (exactly, so the stub can assert):
    - ignite: `["tmux", "new-session", "-d", "-s", name, "-c", str(cwd)] + argv` then `["tmux", "send-keys", "-t", name, IGNITION_MESSAGE, "Enter"]`
    - alive: `["tmux", "has-session", "-t", name]` → returncode 0
    - tail: `["tmux", "capture-pane", "-p", "-t", name]` → last `lines` lines of stdout; returns `""` on nonzero rc
    - kill: `["tmux", "kill-session", "-t", name]`
    - Every `run` call uses `capture_output=True, text=True`. `ignite` raises `HostError` (with stderr excerpt) if either command exits nonzero; a dead `tmux` binary (`OSError`) also becomes `HostError`.
    - `attach_hint(name) -> str` returns `f"tmux attach -t {name}"` (the UI line, spec §7).
  - `class HeadlessHost` — per-turn fallback for hosts without tmux (spec §7): one detached headless process per ignition. Constructor `HeadlessHost(log_dir: str | os.PathLike, popen=subprocess.Popen)`. `ignite` opens `log_dir/<name>.log` for append and `popen(argv + [IGNITION_MESSAGE], cwd=..., stdout=<log>, stderr=STDOUT)`, storing the process handle by name; raises `HostError` on `OSError`. NOTE: `argv` here is the runner's HEADLESS argv (the conductor picks which argv to pass per host — Task 5). `alive` = handle exists and `poll() is None`. `tail` reads the last `lines` lines of the log file (`""` if absent). `kill` = `terminate()` best-effort.
  - `pick_host(preference: str, *, which=shutil.which) -> str` — `"tmux"` preference falls back to `"headless"` (with no error) when the tmux binary is absent; `"headless"` stays headless; anything else raises `HostError`.

**Test contract** (stub `run`/`popen` record calls and return canned `CompletedProcess`/fake-process objects — NO real tmux, NO real claude):
1. TmuxHost.ignite issues exactly the new-session + send-keys pair with the given name/cwd/argv; nonzero rc on either → `HostError` carrying stderr text.
2. TmuxHost.alive true/false from rc 0/1; tail returns last N lines of canned stdout and `""` on rc 1; kill issues kill-session.
3. attach_hint format.
4. HeadlessHost.ignite passes `argv + [IGNITION_MESSAGE]` and the cwd to popen, appends to `<name>.log`; alive flips false when the fake process's `poll()` returns 0; tail reads the log file tail; kill calls `terminate()`.
5. HeadlessHost.ignite wraps `OSError` from popen as `HostError`.
6. pick_host: ("tmux", tmux present) → "tmux"; ("tmux", absent) → "headless"; ("headless", present) → "headless"; ("screen", …) → HostError.
7. One env-gated LIVE smoke (`@unittest.skipUnless(os.environ.get("DANZA_LIVE_TMUX") == "1", ...)`): real TmuxHost against a real `tmux` running `["bash"]` in a temp dir — ignite, alive True, tail contains the ignition message eventually (poll ≤ 5 s), kill, alive False. Keep it under 10 s.

- [ ] Step 1: failing test → Step 2: implement → Step 3: `python3 -m unittest test_workstation_hosts -v` PASS (live test SKIPPED) → Step 4: commit `feat(workstation): W1-P4 T2 session hosts — tmux + headless behind one interface`.

---

### Task 3: Conductor decision table (`conductor.py`, pure part)

**Model:** fable (inline)

**Files:**
- Create: `danzaboss/workstation/conductor.py`
- Test: `danzaboss/tests/test_workstation_conductor.py`

**Interfaces:**
- Consumes: `TeamState` from `danzaboss.kernel.state` (READ-ONLY — the dataclass, not the manager, so decisions stay pure).
- Produces:
  - `ConductorError(RuntimeError)`
  - `class Action(str, Enum)`: `IGNITE`, `WAIT`, `HALT_BLOCKED`, `STOP_DONE`, `STOP_VALVE`
  - `STALL_MINUTES = 10` (spec §7 default), `DEAD_SESSION_VALVE = 2`
  - `@dataclass Watch` — the conductor's own bookkeeping between ticks (it is stateless beyond this + the log, spec §7 crash recovery): `session_alive: bool`, `turn_at_ignite: int | None`, `dead_sessions: int`, `last_change_monotonic: float`, `last_tail: str`
  - `decide(state: TeamState, watch: Watch) -> Action` — PURE decision table:
    - `status == "blocked"` → `HALT_BLOCKED`
    - `status == "done"` → `STOP_DONE`
    - `watch.dead_sessions >= DEAD_SESSION_VALVE` → `STOP_VALVE`
    - `status == "ready"` and not `watch.session_alive` → `IGNITE`
    - everything else (`in_progress`, `awaiting_handoff`, or a session already running) → `WAIT`
  - `observe_session_end(state: TeamState, watch: Watch) -> Watch` — called when a session that was alive is found dead: returns a new Watch with `session_alive=False` and `dead_sessions` incremented iff `state.turn_number == watch.turn_at_ignite` (exited WITHOUT advancing the turn — spec §7 valve), else reset to 0 (progress happened).
  - `is_stalled(watch: Watch, now_monotonic: float, *, stall_minutes: int = STALL_MINUTES) -> bool` — `session_alive` and `now - last_change >= stall_minutes * 60`. Callers refresh `last_change_monotonic`/`last_tail` whenever team-state mtime or the pane tail changes; stall is surfaced, never auto-killed.

**Test contract:** decision table exhaustively (each status × session_alive), valve counting (two no-advance exits → STOP_VALVE; an advancing exit resets the counter), stall boundary (9m59s no, 10m yes; output change resets). All pure — construct `TeamState(...)` directly.

- [ ] Steps: failing test → implement → `python3 -m unittest test_workstation_conductor -v` PASS → commit `feat(workstation): W1-P4 T3 conductor decision table — valve, stall, pure`.

---

### Task 4: Conductor loop, pidfile, JSONL log

**Model:** fable (inline)

**Files:**
- Modify: `danzaboss/workstation/conductor.py` (append)
- Test: `danzaboss/tests/test_workstation_conductor_loop.py`

**Interfaces:**
- Consumes: Task 1 (`load_runners`, `boss_runner`, `interactive_argv`, `headless_argv`), Task 2 (`SessionHost`, `pick_host`, hosts), Task 3, `StateManager`/`StateError` from `danzaboss.kernel.state`.
- Produces:
  - `PIDFILE_RELPATH = Path(".danza") / "runtime" / "conductor.pid"`
  - `LOG_RELPATH = Path(".danza") / "runtime" / "conductor-log.jsonl"`
  - `session_name(root) -> str` — `f"danza-{Path(root).resolve().name}"` (spec §7 `danza-<project>`)
  - `class Conductor` — constructor `Conductor(root, host: SessionHost, *, clock=time.monotonic, sleep=time.sleep, poll_interval: float = 2.0, stall_minutes: int = STALL_MINUTES)`. Reads the registry itself (`load_runners(root)`); chooses interactive argv for TmuxHost-like hosts vs headless argv when the registry's `session_host` is `"headless"` — the argv choice keys off the CONFIG, not isinstance, so test doubles work.
  - `acquire_pidfile(root, *, pid: int = os.getpid(), alive=<os.kill(pid,0) probe>) -> Path` — single-instance rail: an existing pidfile with a LIVE pid raises `ConductorError` (two conductors would double-ignite, spec §7); a stale pid is reclaimed (overwrite). Injectable `alive` probe for tests.
  - `release_pidfile(root, *, pid=...) -> None` — removes it only if it still holds our pid.
  - `Conductor.log(event: str, **fields)` — appends one JSON line `{"ts": <iso-utc>, "event": ..., **fields}` to `LOG_RELPATH` (append-only; the conductor's ONLY write besides the pidfile).
  - `Conductor.tick() -> Action` — one poll: `StateManager.load()` (a missing/invalid team-state logs `state_error` and returns `WAIT` — fail closed, never crash the daemon), refresh watch (session liveness via `host.alive`, change detection via team-state mtime + `host.tail`), run `observe_session_end` on death, `decide`, then act: `IGNITE` → `host.ignite(session_name, root, argv)` + log `ignite`; `HALT_BLOCKED`/`STOP_DONE`/`STOP_VALVE` → log with reason; stall → log `stall` (once per stall episode, re-armed when output changes).
  - `Conductor.run(max_ticks: int | None = None) -> Action` — acquire pidfile, loop `tick()` + `sleep(poll_interval)` until a terminal action (`HALT_BLOCKED`, `STOP_DONE`, `STOP_VALVE`) or `max_ticks`, release pidfile in a `finally`. Returns the last action.

**Test contract** (temp root + `StateManager.init()` fixtures + `FakeHost` recording ignites + injected clock/sleep):
1. status ready + no session → tick ignites once with the session name and logs it; second tick with the fake host now alive → WAIT, no double-ignite.
2. Interactive vs headless argv choice follows `config["session_host"]`.
3. blocked → HALT_BLOCKED terminal, reason logged; done → STOP_DONE.
4. Two consecutive session deaths without turn_number advance → STOP_VALVE with report line; death after `handoff()` advanced the turn → counter resets, relay continues (next ready ignites again).
5. Stall: alive session, no mtime/tail change past the threshold on the injected clock → one `stall` log line, session NOT killed; tail change re-arms.
6. Pidfile: second `acquire_pidfile` with a live probe raises; stale pid reclaimed; `run(max_ticks=1)` leaves no pidfile behind.
7. Corrupt team-state.json → tick logs `state_error`, returns WAIT, daemon survives.
8. The conductor never writes `team-state.json` (assert mtime/content unchanged by ticks).

- [ ] Steps: failing test → implement → `python3 -m unittest test_workstation_conductor_loop -v` PASS → commit `feat(workstation): W1-P4 T4 conductor loop — pidfile, stall, valve, JSONL log`.

---

### Task 5: CLI wiring (`danza conduct` + `danza runners`)

**Model:** sonnet

**Files:**
- Modify: `danzaboss/cli.py` (two subcommands, following the existing subcommand pattern in that file)
- Test: `danzaboss/tests/test_workstation_cli.py`

**Interfaces:**
- Consumes: Tasks 1–4 public API only.
- Produces:
  - `danza runners <root>` — detect + write a default registry if none exists (print what was detected and where it wrote); if one exists, print it (no overwrite — the /models screen owns edits in P5).
  - `danza conduct <root> [--poll N] [--max-ticks N]` — build the host via `pick_host(config["session_host"])` (TmuxHost or HeadlessHost with `log_dir=root/.danza/runtime`), run the Conductor, exit code 0 on `STOP_DONE`, 1 on `HALT_BLOCKED`/`STOP_VALVE`, 2 on `ConductorError` (pidfile conflict, no registry). Errors print to stderr, one line, no traceback.
- **Test contract:** invoke the cli mainfunc in-process (existing tests' pattern) on temp roots: `runners` writes then re-prints without clobbering a hand-edited value; `conduct --max-ticks 1` against a ready state + FakeHost is impossible through the real CLI (it builds real hosts) — so test `conduct` only for its failure modes (no registry → exit 2, pidfile conflict → exit 2) plus `--max-ticks 0` no-op happy path with a headless config on a fake `claude` binary placed on PATH via a temp dir. Keep it cheap; the loop logic is already covered by Task 4.

- [ ] Steps: failing test → implement → `python3 -m unittest test_workstation_cli -v` PASS → commit `feat(workstation): W1-P4 T5 CLI — danza runners / danza conduct`.

---

### Task 6: Phase close — full suite, final whole-branch review, ledger

**Model:** fable (inline). Process task.

- [ ] Step 1: `./danzaboss/run_tests.sh` — green required (expected ~615+ OK, skipped=13).
- [ ] Step 2: single whole-branch review over `git diff <P4 base>..HEAD` (code-review skill), with the P1–P3 deferred-minor lists in `.superpowers/sdd/progress.md` as triage input.
- [ ] Step 3: fix Critical/Important findings inline (own commits, regression tests); defer minors to the ledger.
- [ ] Step 4: append the P4 section to `.superpowers/sdd/progress.md` (Edit tool — the Bash guard false-positives on this file) and mark "W1-P4 COMPLETE".
- [ ] Step 5: push.

---

## Self-Review Notes

- **Spec §7 coverage:** runner registry + detection (T1) · session-host abstraction, tmux default, headless fallback, attach hint (T2) · relay decision table, dead-session valve K=2, stall T=10m surface-don't-kill (T3) · fresh-session-per-turn ignition, postman discipline, single-instance pidfile, conductor-log.jsonl, crash-recovery-by-statelessness (T4) · CLI entry points (T5). `/models` UI, button states, cadence `awaiting_user` pause, Telegram notify are P5/future by design.
- **Kernel reuse:** `TeamState` consumed read-only in `decide()`; `StateManager.load()` is the only state read; nothing here writes team-state (Rule-38 safety lives in the kernel, the conductor can't violate it).
- **No circular imports:** `conductor` → `runners`/`hosts`/`kernel.state`; `hosts`/`runners` → stdlib only; `cli` → all three. Nothing imports `conductor`.
- **Hermeticity:** every subprocess/pid/clock/sleep seam injectable; exactly one env-gated live tmux test, skipped by default.
