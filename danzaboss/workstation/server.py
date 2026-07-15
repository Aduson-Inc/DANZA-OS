"""DANZA-OS product dashboard — stdlib HTTP server on 127.0.0.1:33100 (Phase 2).

One process serves the whole product shell (design decision D4): the DANZA
dashboard at `/` and the complete CORTEX UI mounted under `/cortex/*` against
the same store. The dashboard is a read-only window over an activated repo's
product state — profile, team-state, plan progress, conductor log, runner
registry, wizard status. Later phases plug interactive surfaces into this
shell (/onboard forms in Phase 3, /models + BUILD controls in Phase 4), which
is why the read APIs live in module-level functions the handler only wires up.

Stdlib only. No build step; static assets live next to this file.
`cortex/ui/server.py` is the style reference (spec section 11).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import fields as dataclass_fields
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional

from ..cortex import commands as cortex_commands
from ..cortex.events import CaptureLog
from ..cortex.identity import resolve_project
from ..cortex.inject import est_tokens
from ..cortex.sqlite_backend import SqliteBackend
from ..cortex.ui.server import CortexUIHandler, cross_origin_reason
from ..kernel.profile import active_profile
from ..kernel.state import StateError, TeamState
from . import checkpoints as checkpoints_mod
from . import interview as interview_mod
from . import research as research_mod
from . import routing as routing_mod
from . import templates as templates_mod
from .compiler import SPEC_RELPATH, compile_spec, write_spec
from .conductor import (LOG_RELPATH, PIDFILE_RELPATH, TEAM_STATE_RELPATH,
                        _pid_alive, session_name)
from .hosts import HeadlessHost, HostError, TmuxHost, pick_host
from .planner import (PLAN_JSON_RELPATH, PLAN_MD_RELPATH, PlanningError,
                      PlanningUnavailable, parse_plan, run_planning)
from .runners import (RUNNERS_RELPATH, RunnerError, build_registry,
                      headless_argv, load_runners, save_runners)
from .state import STATE_RELPATH
from .tree import APP_PROJECT_TYPES
from .wizard import Wizard, WizardError

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
DEFAULT_PORT = 33100  # CORTEX keeps 33000 (D4)
MAX_POST_BYTES = 1_048_576  # nothing the onboarding forms send comes close

# Every onboarding write is a load -> mutate -> save over shared state files
# (interview.json, answers.json); one lock serializes concurrent POSTs so a
# curl user racing the browser cannot interleave inside a mutation.
_POST_LOCK = threading.Lock()

# GET /api/setup must not block the dashboard behind five auth-probe
# subprocesses on every poll, so the live registry is cached for a short TTL.
# Builder and clock are module-level seams (the detect_runners(which=...)
# idiom) so tests double them without ever touching the host's real CLIs.
_BUILD_REGISTRY = build_registry
_REGISTRY_CLOCK = time.monotonic
_REGISTRY_TTL_SECONDS = 60.0
_registry_cache: dict = {"at": 0.0, "config": None}


def _reset_registry_cache() -> None:
    _registry_cache.update(at=0.0, config=None)


def _live_registry(fresh: bool = False) -> dict:
    """The auth-probed runner registry, cached for _REGISTRY_TTL_SECONDS.

    fresh=True (POST /api/setup) rebuilds unconditionally — a team confirm
    must never validate seats against stale auth. The fresh result still
    lands in the cache so the summary rendered from the POST response
    agrees with it."""
    now = _REGISTRY_CLOCK()
    cached = _registry_cache["config"]
    if (not fresh and cached is not None
            and now - _registry_cache["at"] < _REGISTRY_TTL_SECONDS):
        return cached
    config = _BUILD_REGISTRY()
    _registry_cache.update(at=now, config=config)
    return config


# -- read-side assemblers (pure functions of root, unit-testable) -----------

def _read_json(path: Path) -> tuple[object, str]:
    """(data, "") on success, (None, "") if missing, (None, reason) if corrupt.

    Missing state is not an error — the dashboard renders absence honestly;
    corruption is reported, never silently dropped (spec section 11)."""
    if not path.exists():
        return None, ""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), ""
    except (OSError, json.JSONDecodeError) as e:
        return None, str(e)


def _team_state(root: str) -> tuple[Optional[dict], str]:
    data, err = _read_json(Path(root) / TEAM_STATE_RELPATH)
    if data is not None and not isinstance(data, dict):
        return None, "team-state.json is not a JSON object"
    if isinstance(data, dict) and not err:
        # Rule 45: the schema is machine-checkable — violations surface as
        # a warning while the raw document still renders (read-side honesty).
        known = {f.name for f in dataclass_fields(TeamState)}
        try:
            TeamState(**{k: v for k, v in data.items()
                         if k in known}).validate()
        except (StateError, TypeError) as e:
            err = f"team-state schema (Rule 45): {e}"
    return data, err


def _plan_summary(root: str) -> Optional[dict]:
    """Plan progress for the home screen. Validation goes through the real
    planner parser so the dashboard can never present a plan the conductor
    would refuse."""
    data, err = _read_json(Path(root) / PLAN_JSON_RELPATH)
    if data is None:
        return {"error": err} if err else None
    try:
        tasks = parse_plan(data)
    except PlanningError as e:
        return {"error": str(e)}

    def walk(ts) -> tuple[int, int]:
        total = leaves = 0
        for t in ts:
            total += 1
            sub_total, sub_leaves = walk(t.subtasks)
            total += sub_total
            leaves += sub_leaves if t.subtasks else 1
        return total, leaves

    total, leaves = walk(tasks)
    order = data.get("order", []) if isinstance(data, dict) else []
    return {"spec_ref": data.get("spec_ref", ""), "tasks": total,
            "leaves": leaves, "order": list(order)}


def _runner_summary(root: str) -> Optional[dict]:
    if not (Path(root) / RUNNERS_RELPATH).exists():
        return None
    try:
        config = load_runners(root)
    except RunnerError as e:
        return {"error": str(e)}
    summary = {"boss": config.get("boss"),
               "session_host": config.get("session_host"),
               "detected": sorted(n for n, e in config.get("runners", {}).items()
                                  if e.get("detected"))}
    # Phase 4: OVERVIEW's runners block covers the whole confirmed team.
    # Absent or invalid routing just omits the team keys here — the SETUP
    # tab (setup_summary) is where the reason surfaces.
    try:
        routing = routing_mod.load_routing(root)
        summary["lineup"] = routing["lineup"]
        summary["seats"] = routing["seats"]
    except (RunnerError, routing_mod.RoutingError):
        pass
    return summary


def _ignites_per_turn(root: str) -> dict:
    """Turn number -> ignite count from the conductor log — the per-turn
    denominator for the Tokens card (D10: cost regressions visible now)."""
    counts: dict = {}
    for item in conductor_tail(root)["items"]:
        if item.get("event") == "ignite" and "turn_number" in item:
            key = str(item["turn_number"])
            counts[key] = counts.get(key, 0) + 1
    return counts


def _cortex_stats(root: str) -> dict:
    """The home-screen CORTEX strip — the same numbers the CORTEX stats view
    computes, so the two UIs can never disagree — plus the P4 T11 telemetry
    (per-agent context spend, per-turn ignite counts)."""
    db = cortex_commands.db_path(root)
    project = resolve_project(root)
    log = CaptureLog(db)
    s = log.stats(project)
    count = read_tokens = 0
    for o in SqliteBackend(db).all(project):
        count += 1
        read_tokens += est_tokens(o.summary + o.reasoning)
    s.update({"observations_stored": count, "read_tokens": read_tokens,
              "per_agent": log.context_read_stats(project),
              "per_turn": _ignites_per_turn(root)})
    return s


def overview(root: str) -> dict:
    """Everything the OVERVIEW screen needs in one payload (spec section 6)."""
    team, team_err = _team_state(root)
    out = {"project": resolve_project(root),
           "root": os.path.abspath(root),
           "profile": active_profile(root).to_dict(),
           "team_state": team,
           "plan": _plan_summary(root),
           "spec_exists": (Path(root) / ".danza" / "spec.md").exists(),
           "runners": _runner_summary(root),
           "cortex": _cortex_stats(root)}
    if team_err:
        out["team_state_error"] = team_err
    return out


def conductor_tail(root: str, limit: int = 100) -> dict:
    """Last `limit` conductor JSONL events, newest first. Unparseable lines
    surface as {"event": "unparseable"} — never dropped silently (Rule 33:
    this log is the one surface the human gets)."""
    path = Path(root) / LOG_RELPATH
    if not path.exists():
        return {"items": []}
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()[-limit:]
    items = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            items.append({"event": "unparseable", "raw": line[:200]})
    items.reverse()
    return {"items": items}


def _conductor_pid(root: str) -> Optional[int]:
    """The pid recorded by the conductor's own pidfile, or None. The
    conductor's acquire_pidfile stays the single-instance authority —
    dashboard reads are a fast-path courtesy, never a second lock."""
    path = Path(root) / PIDFILE_RELPATH
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return int(text) if text.isdigit() else None


def _session_host(root: str):
    """The configured session host, or None when no registry exists yet —
    the BUILD tab degrades honestly instead of guessing tmux."""
    try:
        host_type = pick_host(load_runners(root)["session_host"])
    except (RunnerError, HostError):
        return None
    if host_type == "tmux":
        return TmuxHost()
    return HeadlessHost(log_dir=Path(root) / ".danza" / "runtime")


# module-level seam (the detect_runners(which=...) idiom) so HTTP tests
# can double the host without a tmux on the box
_SESSION_HOST = _session_host


def build_summary(root: str,
                  alive: Callable[[int], bool] = _pid_alive) -> dict:
    """Everything the BUILD tab's live strip needs: relay running-state,
    team-state, boss session tail, recent conductor events."""
    name = session_name(root)
    session = {"name": name, "alive": False, "tail": ""}
    host = _SESSION_HOST(root)
    if host is not None:
        try:
            session["alive"] = bool(host.alive(name))
            session["tail"] = host.tail(name)
        except (HostError, OSError):
            pass  # a missing tmux reads as a dead session, not a crash
    pid = _conductor_pid(root)
    team, team_err = _team_state(root)
    out = {"running": pid is not None and alive(pid),
           "team_state": team,
           "session": session,
           "conductor": conductor_tail(root, 50)["items"]}
    if team_err:
        out["team_state_error"] = team_err
    return out


def _headless_command(root: str) -> Optional[list]:
    """Boss argv for dashboard-triggered AI calls, or None when no runner
    is configured/headless-capable — callers degrade honestly (P3-D4)."""
    try:
        return headless_argv(load_runners(root))
    except RunnerError:
        return None


def setup_complete(root: str) -> bool:
    """The hard setup-first gate's condition (Phase 4 Decision 1/7):
    runners.json and routing.json both load valid and the lineup is
    non-empty."""
    try:
        # load_routing validates runners.json too (it re-checks the lineup
        # against the current registry), so one call covers both files
        routing = routing_mod.load_routing(root)
    except (RunnerError, routing_mod.RoutingError):
        return False
    return bool(routing["lineup"])


def setup_summary(root: str) -> dict:
    """Everything the SETUP tab needs: live agent registry, persisted (or
    suggested) seats, conductor, and the gate state."""
    config = _live_registry()
    agents = [{"name": name, "display_name": entry["display_name"],
               "strengths": entry["strengths"],
               "detected": entry["detected"], "auth": entry["auth"]}
              for name, entry in config["runners"].items()
              if entry["binary"]]  # the generic copy-me template is no card
    lineup: list = []
    seats: dict = {}
    features_per_turn = routing_mod.DEFAULT_FEATURES_PER_TURN
    routing_error = ""
    try:
        persisted = routing_mod.load_routing(root)
        lineup, seats = persisted["lineup"], persisted["seats"]
        features_per_turn = persisted["features_per_turn"]
    except (RunnerError, routing_mod.RoutingError) as e:
        # a routing file that EXISTS but can't be trusted is reported, never
        # hidden; plain absence silently falls through to the suggestion
        if (Path(root) / routing_mod.ROUTING_RELPATH).exists():
            routing_error = str(e)
        try:
            seats = routing_mod.suggest_seats(config)
            lineup = [name for name in config["runners"]
                      if name in set(seats.values())]
        except routing_mod.RoutingError:
            pass  # nothing connected: no team to suggest — honest emptiness
    out = {"agents": agents, "lineup": lineup, "seats": seats,
           "conductor": seats.get("conductor", routing_mod.BUILTIN_CONDUCTOR),
           "features_per_turn": features_per_turn,
           "setup_complete": setup_complete(root)}
    if routing_error:
        out["routing_error"] = routing_error
    return out


def _question_dict(q, answers: dict) -> dict:
    """One Question as the form-render contract: declaration + current
    value + show_if clauses so the client can mirror branch visibility
    (the server re-validates on submit — wizard stays authoritative)."""
    return {"id": q.id, "prompt": q.prompt, "kind": q.kind,
            "options": list(q.options), "required": q.required,
            "default": q.default, "value": answers.get(q.id),
            "show_if": [[qid, list(accepted)] for qid, accepted in q.show_if]}


def onboarding_summary(root: str) -> dict:
    """Everything the ONBOARD tab needs to render forms, the grill, and
    inline research/checkpoint results (Phase 3)."""
    wiz = Wizard(root)
    answers = wiz.answers
    records = interview_mod.load_interview(root)["phases"]
    current = wiz.current_step()
    steps = []
    for s in wiz.flow():
        entry = {"id": s.id, "kind": s.kind, "title": s.title,
                 "status": wiz.status(s.id),
                 "questions": [_question_dict(q, answers)
                               for q in s.questions]}
        if s.kind != "phase":
            entry["result"] = wiz.result(s.id)
        record = records.get(s.id)
        if record is not None:
            entry["interview"] = record
        steps.append(entry)
    project_type = wiz.project_type()
    return {"project_type": project_type,
            "setup_complete": setup_complete(root),
            "complete": wiz.is_complete(),
            "current_step": current.id if current else None,
            "answered": len(answers),
            "blocking_phase": interview_mod.blocking_phase(root, wiz),
            "boss_available": _headless_command(root) is not None,
            "app_project": project_type in APP_PROJECT_TYPES,
            "steps": steps}


def plan_detail(root: str) -> dict:
    """BUILD tab payload: the validated task tree plus the human plan.md."""
    summary = _plan_summary(root)
    md_path = Path(root) / PLAN_MD_RELPATH
    md = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    tree: list[dict] = []
    if summary is not None and "error" not in summary:
        data, _ = _read_json(Path(root) / PLAN_JSON_RELPATH)

        def node(t) -> dict:
            return {"id": t.id, "description": t.description, "kind": t.kind,
                    "size_est": t.size_est, "writes": list(t.writes),
                    "verified_by": (t.verification.detail
                                    if t.verification else None),
                    "subtasks": [node(s) for s in t.subtasks]}

        tree = [node(t) for t in parse_plan(data)]
    return {"plan": summary, "tree": tree, "plan_md": md}


def snapshot_token(root: str) -> str:
    """Cheap change token for SSE: mtime+size of the product state files
    (same role snapshot_version() plays for the CORTEX store)."""
    parts = []
    for rel in (TEAM_STATE_RELPATH, LOG_RELPATH, PLAN_JSON_RELPATH,
                RUNNERS_RELPATH, routing_mod.ROUTING_RELPATH,
                STATE_RELPATH, interview_mod.INTERVIEW_RELPATH, SPEC_RELPATH):
        try:
            st = (Path(root) / rel).stat()
            parts.append(f"{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append("-")
    return "|".join(parts)


# -- write-side actions (pure functions of root+body, unit-testable) --------

class GateConflict(Exception):
    """A write that must wait: open grill, missing verdict, wrong order."""


def _require(body: dict, key: str, kind: type):
    value = body.get(key)
    if not isinstance(value, kind):
        raise ValueError(f"body.{key} must be {kind.__name__}")
    return value


def _require_setup(root: str) -> None:
    """The hard setup-first gate (Phase 4 Decision 1): no onboarding write
    happens before the AI team is confirmed. Checked before anything else —
    fail closed, whatever the body says."""
    if not setup_complete(root):
        raise GateConflict(
            "finish Setup first — your AI team is not confirmed yet")


def post_setup(root: str, body: dict) -> dict:
    """Confirm the team: one validated write of runners.json + routing.json
    (Decision 7). Always re-probes fresh — a confirm must never validate
    seats against stale auth. Both payloads validate BEFORE anything is
    written, so a rejected confirm leaves no torn multi-file state."""
    lineup = _require(body, "lineup", list)
    seats = _require(body, "seats", dict)
    features_per_turn = _require(body, "features_per_turn", int)
    config = _live_registry(fresh=True)
    try:
        # keep host settings the user already chose; absence means defaults
        existing = load_runners(root)
        config["session_host"] = existing["session_host"]
        config["permission_mode"] = existing.get("permission_mode")
    except RunnerError:
        pass
    config["boss"] = lineup[0] if lineup else None
    routing = {"version": routing_mod.SCHEMA_VERSION,
               "features_per_turn": features_per_turn,
               "lineup": lineup, "seats": seats}
    routing_mod.validate_routing(routing, config)
    save_runners(root, config)
    routing_mod.save_routing(root, routing, config)
    return {"ok": True, "setup": setup_summary(root)}


def post_submit(root: str, body: dict) -> dict:
    """Phase answers in, grill round out. The submit itself is the wizard's
    (validation + stale-downstream unchanged); the grill starts fresh on
    every (re)submission (P3-D8)."""
    _require_setup(root)
    step_id = _require(body, "step_id", str)
    answers = _require(body, "answers", dict)
    wiz = Wizard(root)
    blocking = interview_mod.blocking_phase(root, wiz)
    if blocking and blocking != step_id:
        raise GateConflict(
            f"the {blocking} step still has open questions — "
            "answer those first")
    wiz.submit(step_id, answers)
    interview_mod.begin_phase(root, step_id)
    record = interview_mod.run_interview_round(
        root, step_id, _headless_command(root))
    return {"ok": True, "interview": record,
            "onboarding": onboarding_summary(root)}


def post_followup(root: str, body: dict) -> dict:
    _require_setup(root)
    step_id = _require(body, "step_id", str)
    answers = _require(body, "answers", dict)
    interview_mod.record_followup_answers(root, step_id, answers)
    record = interview_mod.run_interview_round(
        root, step_id, _headless_command(root))
    return {"ok": True, "interview": record,
            "onboarding": onboarding_summary(root)}


def post_resolve(root: str, body: dict) -> dict:
    _require_setup(root)
    step_id = _require(body, "step_id", str)
    decision = _require(body, "decision", str)
    record = interview_mod.resolve(root, step_id, decision)
    return {"ok": True, "interview": record,
            "onboarding": onboarding_summary(root)}


def post_research(root: str, body: dict) -> dict:
    """The POST is the click, and the click IS the user approval external
    research requires in every profile (research.py contract)."""
    _require_setup(root)
    command = _headless_command(root)
    provider = None
    if command is not None:
        provider = (research_mod.tavily_from_env(command)
                    or research_mod.BossWebProvider(command))
    digest = research_mod.run_reality_check(root, provider)
    return {"ok": True, "digest": digest,
            "onboarding": onboarding_summary(root)}


def post_checkpoint(root: str, body: dict) -> dict:
    _require_setup(root)
    step_id = _require(body, "step_id", str)
    verdict = checkpoints_mod.run_checkpoint(
        root, step_id, _headless_command(root))
    return {"ok": True, "verdict": verdict,
            "onboarding": onboarding_summary(root)}


def post_approve(root: str, body: dict) -> dict:
    """Approval stays a user act (W1 law); the grill gate holds it until
    every submitted phase is clear (spec section 7 clarity gate)."""
    _require_setup(root)
    step_id = _require(body, "step_id", str)
    wiz = Wizard(root)
    blocking = interview_mod.blocking_phase(root, wiz)
    if blocking:
        raise GateConflict(
            f"cannot approve {step_id} yet — the {blocking} step "
            "still has open questions")
    result = wiz.result(step_id)
    if result is None:
        raise GateConflict(
            f"run the AI review of {step_id} before approving it")
    wiz.record_result(step_id, result, approved=True)
    return {"ok": True, "onboarding": onboarding_summary(root)}


def finish_onboarding(root: str, command: Optional[list]) -> dict:
    """Compile spec.md from approved answers, then run validated planning
    (spec section 7 'Finish'). Deliberately gate-checked, fail-closed:
    planning has no degraded mode — nothing downstream can proceed
    without a valid plan."""
    wiz = Wizard(root)
    if wiz.project_type() not in APP_PROJECT_TYPES:
        raise WizardError("this project saved an idea — only website or "
                          "SaaS projects get a build brief")
    if not wiz.is_complete():
        raise GateConflict(
            "onboarding is not finished — complete every "
            "step and approve each AI review first")
    blocking = interview_mod.blocking_phase(root, wiz)
    if blocking:
        raise GateConflict(
            f"the {blocking} step still has open questions — "
            "answer those first")
    if command is None:
        raise PlanningUnavailable(
            f"{checkpoints_mod.NO_BOSS_REASON} — planning needs an AI agent")
    answers = wiz.answers
    template = None
    chosen = answers.get("stack_template")
    if chosen:
        library = {t.key: t for t in templates_mod.load_templates()}
        template = library.get(chosen)
    research_result = (wiz.result("r_reality")
                       if wiz.status("r_reality") == "complete" else None)
    verdicts = {}
    for cp_id in checkpoints_mod.CHECKPOINT_IDS:
        result = wiz.result(cp_id)
        if result:
            verdicts[cp_id] = result.get("summary", "")
    text = compile_spec(answers=answers, template=template,
                        research=research_result, checkpoints=verdicts,
                        open_questions=interview_mod.open_questions(root, wiz))
    spec_path = write_spec(root, text)
    out = run_planning(root, command)
    out["spec"] = str(spec_path)
    return out


def post_finish(root: str, body: dict) -> dict:
    _require_setup(root)
    out = finish_onboarding(root, _headless_command(root))
    out.update({"ok": True, "onboarding": onboarding_summary(root)})
    return out


CONDUCT_LOG_RELPATH = Path(".danza") / "runtime" / "conduct-ui.log"


def post_build_start(root: str, body: dict,
                     popen: Callable = subprocess.Popen,
                     alive: Callable[[int], bool] = _pid_alive) -> dict:
    """Start the relay: spawn `danza conduct` detached, output to a
    tailable log. The client disables Start until setup is confirmed and
    a plan exists, but the server re-validates both (server stays
    authoritative) — a direct POST gets a clean conflict, not a spawned
    subprocess that dies on its first read. A live pidfile refuses fast
    here, but the conductor's own acquire_pidfile remains the
    single-instance authority — this check is a courtesy, not a second
    lock."""
    _require_setup(root)
    if not (Path(root) / PLAN_JSON_RELPATH).is_file():
        raise GateConflict(
            "finish Onboarding first — there is no build plan yet")
    pid = _conductor_pid(root)
    if pid is not None and alive(pid):
        raise GateConflict("the build crew is already running")
    log_path = Path(root) / CONDUCT_LOG_RELPATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # append mode: a restarted relay extends the evidence, never truncates
    with open(log_path, "ab") as log:
        proc = popen([sys.executable, "-m", "danzaboss.cli",
                      "conduct", root],
                     stdout=log, stderr=subprocess.STDOUT,
                     start_new_session=True)
    return {"ok": True, "pid": proc.pid}


def post_build_stop(root: str, body: dict,
                    kill: Callable = os.kill,
                    alive: Callable[[int], bool] = _pid_alive) -> dict:
    """Stop the relay with SIGTERM only — the conductor's `finally`
    releases its own pidfile, so a clean shutdown leaves no stale lock."""
    pid = _conductor_pid(root)
    if pid is None or not alive(pid):
        raise GateConflict("the build crew is not running")
    kill(pid, signal.SIGTERM)
    return {"ok": True, "pid": pid}


_POST_ROUTES = {
    "/api/setup": post_setup,
    "/api/build/start": post_build_start,
    "/api/build/stop": post_build_stop,
    "/api/onboard/submit": post_submit,
    "/api/onboard/followup": post_followup,
    "/api/onboard/resolve": post_resolve,
    "/api/onboard/research": post_research,
    "/api/onboard/checkpoint": post_checkpoint,
    "/api/onboard/approve": post_approve,
    "/api/onboard/finish": post_finish,
}


# -- handler -----------------------------------------------------------------

class DanzaUIHandler(CortexUIHandler):
    """Dashboard routes at `/`; inherited CORTEX routes under `/cortex/*`.

    Subclassing (not wrapping) keeps D4 honest: one process, one handler
    hierarchy, one store handle — the mount strips the path prefix and lets
    the parent class do exactly what it does standalone."""

    server_version = "DanzaUI/1.0"

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        q = urllib.parse.parse_qs(parsed.query)
        try:
            if route == "/cortex":
                query = f"?{parsed.query}" if parsed.query else ""
                self._redirect(f"/cortex/{query}")
            elif route.startswith("/cortex/"):
                # the mount (D4): strip the prefix, let the parent class serve
                self.path = self.path[len("/cortex"):]
                CortexUIHandler.do_GET(self)
            elif route in ("/", "/index.html"):
                self._static("index.html", static_dir=_STATIC_DIR)
            elif route.startswith("/static/"):
                self._static(route[len("/static/"):], static_dir=_STATIC_DIR)
            elif route == "/api/overview":
                self._json(overview(self.root))
            elif route == "/api/conductor":
                raw = (q.get("limit") or ["100"])[0]
                try:
                    limit = int(raw)
                except ValueError:
                    limit = 0  # non-integers fall into the range rejection
                if not 1 <= limit <= 1000:
                    self._json({"error": "limit must be an integer "
                                         "between 1 and 1000"}, 400)
                else:
                    self._json(conductor_tail(self.root, limit))
            elif route == "/api/build":
                self._json(build_summary(self.root))
            elif route == "/api/setup":
                self._json(setup_summary(self.root))
            elif route == "/api/onboarding":
                self._json(onboarding_summary(self.root))
            elif route == "/api/plan":
                self._json(plan_detail(self.root))
            elif route == "/api/runners":
                self._json({"runners": _runner_summary(self.root)})
            elif route == "/api/events":
                self._danza_events()
            else:
                self._json({"error": "not found"}, 404)
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001 — surface as JSON, never crash the server
            try:
                self._json({"error": str(e)}, 500)
            except Exception:
                pass

    def _post_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not 0 <= length <= MAX_POST_BYTES:
            raise ValueError(f"body exceeds {MAX_POST_BYTES} bytes")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"body is not valid JSON: {e}")
        if not isinstance(data, dict):
            raise ValueError("body must be a JSON object")
        return data

    def do_POST(self):
        # CSRF guard (P3 final review #2) — before routing, so the CORTEX
        # /api/settings passthrough is covered too.
        reason = cross_origin_reason(self.headers.get("Origin"),
                                     self.headers.get("Host"),
                                     self.server.server_address[1])
        if reason:
            self._json({"error": reason}, 403)
            return
        route = urllib.parse.urlparse(self.path).path
        if route.startswith("/cortex/"):
            self.path = self.path[len("/cortex"):]
            CortexUIHandler.do_POST(self)
            return
        handler = _POST_ROUTES.get(route)
        if handler is None:
            self._json({"error": "not found"}, 404)
            return
        try:
            body = self._post_body()
            with _POST_LOCK:
                result = handler(self.root, body)
            self._json(result)
        except GateConflict as e:
            self._json({"error": str(e)}, 409)
        except ValueError as e:
            # WizardError / InterviewError / CheckpointError / ResearchError
            # / RunnerError / PlanningError are ValueError subclasses — one
            # honest 400 with the reason.
            self._json({"error": str(e)}, 400)
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001 — surface as JSON, never crash
            try:
                self._json({"error": str(e)}, 500)
            except Exception:
                pass

    def _danza_events(self) -> None:
        """SSE: refresh signal when any product state file changes."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        last = snapshot_token(self.root)
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                time.sleep(2)
                now = snapshot_token(self.root)
                if now != last:
                    last = now
                    self.wfile.write(b'data: {"type": "refresh"}\n\n')
                else:
                    self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


# -- lifecycle ----------------------------------------------------------------

def make_server(root: str, port: int = 0) -> ThreadingHTTPServer:
    """Bind 127.0.0.1 only. port=0 -> ephemeral (tests)."""
    handler = type("BoundHandler", (DanzaUIHandler,), {
        "root": root,
        "db_path": cortex_commands.db_path(root),
        "project": resolve_project(root),
    })
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def serve(root: str, port: Optional[int] = None,
          open_browser: bool = True) -> None:
    server = make_server(root, DEFAULT_PORT if port is None else port)
    host, bound = server.server_address[0], server.server_address[1]
    url = f"http://{host}:{bound}"
    print(f"DANZA-OS dashboard: {url}  (CORTEX at {url}/cortex/ — Ctrl-C to stop)")
    if open_browser:
        # after bind, before serve_forever blocks — the timer fires once the
        # loop is accepting, so the first page load never races the socket
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


def serve_in_thread(root: str, port: int = 0) -> tuple[ThreadingHTTPServer, int]:
    """Test/daemon helper: start on an ephemeral port, return (server, port)."""
    server = make_server(root, port)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, server.server_address[1]
