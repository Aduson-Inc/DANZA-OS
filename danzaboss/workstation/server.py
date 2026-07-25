"""DANZA-OS product dashboard — stdlib HTTP server on localhost:33000.

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
from ..cortex.sqlite_backend import SqliteBackend
from ..cortex.tokens import est_tokens
from ..cortex.ui.server import CortexUIHandler, cross_origin_reason
from ..kernel.profile import active_profile
from ..kernel.state import StateError, StateManager, TeamState
from ..product.payload import agent_roster
from ..product.connection import (connection_status, launch_runner,
                                  open_workspace, prepare_workspace,
                                  verify_runner)
from ..product.handoff import HandoffMode, classify_handoff
from . import build as build_mod
from . import checkpoints as checkpoints_mod
from . import execution as execution_mod
from . import interview as interview_mod
from . import project as project_mod
from . import product_scope as product_scope_mod
from . import research as research_mod
from . import routing as routing_mod
from . import templates as templates_mod
from ..frontier import scout as frontier_scout_mod
from ..frontier import store as frontier_store_mod
from .compiler import SPEC_RELPATH, compile_spec, write_spec
from .conductor import (LOG_RELPATH, PIDFILE_RELPATH, TEAM_STATE_RELPATH,
                        _pid_alive, session_name)
from .hosts import HeadlessHost, HostError, TmuxHost, pick_host
from .planner import (PLAN_JSON_RELPATH, PLAN_MD_RELPATH, PlanningError,
                      PlanningUnavailable, parse_plan, propose_plan,
                      run_planning)
from .runners import (RUNNERS_RELPATH, RunnerError, build_registry,
                      headless_argv, load_runners, runner_state,
                      save_runners)
from .state import STATE_RELPATH
from .tree import APP_PROJECT_TYPES
from .wizard import Wizard, WizardError
from .workspace import workspace_summary

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
DEFAULT_PORT = 33000
MAX_POST_BYTES = 1_048_576  # nothing the onboarding forms send comes close

# Every onboarding write is a load -> mutate -> save over shared state files
# (interview.json, answers.json); one lock serializes concurrent POSTs so a
# curl user racing the browser cannot interleave inside a mutation.
_POST_LOCK = threading.Lock()
_PREPARE_WORKSPACE = prepare_workspace

# Module-level seam (the detect_runners(which=...) idiom) so HTTP tests can
# double the whole scout run without a network or a real Tavily key.
_FRONTIER_SCOUT = frontier_scout_mod.maybe_scout

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


def _savings_stats(root: str) -> dict:
    """Token-savings evidence from recorded brief telemetry only (P4.1 T9):
    cumulative injected/replaced tokens, the derived savings, and how many
    turns were briefed. Zero/empty until any brief has been injected —
    never fabricated. The Build stage detail endpoint (/api/build) surfaces
    the full breakdown; /api/flow's light build-stage summary gets only the
    single derived number (requirement 4 — no heavy telemetry in /api/flow)."""
    db = cortex_commands.db_path(root)
    project = resolve_project(root)
    return CaptureLog(db).savings_stats(project)


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
           "roster": agent_roster(),
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
           "conductor": conductor_tail(root, 50)["items"],
           "savings": _savings_stats(root)}
    if team_err:
        out["team_state_error"] = team_err
    try:
        out.update(build_mod.live_payload(root))
    except build_mod.BuildError as exc:
        # Pre-PROJECT and corrupt projects still get relay/session evidence;
        # the product payload fails closed with an explicit reason.
        out["build_error"] = str(exc)
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


def _active_boss(root: str, lineup: list) -> Optional[str]:
    """The runner taking the current turn. Sequential relay is the only
    routing model that ships (P T8a): this is always
    ``lineup[turn_number % len(lineup)]`` — the same rotation route_turn
    uses, kept as one function so every caller agrees (single source of
    truth, requirement 4)."""
    if not lineup:
        return None
    active = lineup[0]
    team_state, _ = _team_state(root)
    if isinstance(team_state, dict) and type(team_state.get("turn_number")) is int:
        active = lineup[team_state["turn_number"] % len(lineup)]
    return active


def _team_roster(root: str) -> list:
    """The confirmed team as ONE merged list (P T8a requirement 4):
    ``[{runner, display_name, pane, live, active}]``, derived from routing
    + workspace so the active/waiting split has a single source of truth
    instead of two separate views. Empty until a team is confirmed."""
    try:
        routing = routing_mod.load_routing(root)
    except (RunnerError, routing_mod.RoutingError):
        return []
    lineup = routing["lineup"]
    if not lineup:
        return []
    active = _active_boss(root, lineup)
    workspace = workspace_summary(root)
    panes = workspace["panes"]
    session_live = False
    host = _SESSION_HOST(root)
    if host is not None:
        try:
            session_live = bool(host.alive(workspace["session"]))
        except (HostError, OSError):
            pass  # a missing host reads as no live pane, not a crash
    try:
        display_names = {name: entry["display_name"]
                         for name, entry in load_runners(root)["runners"].items()}
    except RunnerError:
        display_names = {}
    return [{"runner": name,
             "display_name": display_names.get(name, name),
             "pane": panes.get(name),
             "live": session_live and name in panes,
             "active": name == active}
            for name in lineup]


def setup_summary(root: str) -> dict:
    """Everything the SETUP tab needs: live agent registry and saved team.

    A fresh project is intentionally unassigned. Detection tells the user
    what is available; it must never choose a boss or specialist assignment
    before the user confirms the team.
    """
    config = _live_registry()
    agents = [{"name": name, "display_name": entry["display_name"],
               "strengths": entry["strengths"],
               "detected": entry["detected"], "auth": entry["auth"],
               "state": runner_state(entry)}
              for name, entry in config["runners"].items()
              if entry["binary"]]  # the generic copy-me template is no card
    lineup: list = []
    features_per_turn = routing_mod.DEFAULT_FEATURES_PER_TURN
    routing_error = ""
    try:
        persisted = routing_mod.load_routing(root)
        lineup = persisted["lineup"]
        features_per_turn = persisted["features_per_turn"]
    except (RunnerError, routing_mod.RoutingError) as e:
        # a routing file that EXISTS but can't be trusted is reported, never
        # hidden; plain absence remains empty until the user confirms a team
        if (Path(root) / routing_mod.ROUTING_RELPATH).exists():
            routing_error = str(e)
    active_boss = _active_boss(root, lineup)
    waiting_bosses = ([name for name in lineup if name != active_boss]
                      if active_boss else [])
    out = {"agents": agents,
           "lineup": lineup,
           "active_boss": active_boss,
           "waiting_bosses": waiting_bosses,
           "features_per_turn": features_per_turn,
           "setup_complete": setup_complete(root),
           "connection": connection_status(root),
           "workspace": workspace_summary(root)}
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


def _stack_recommendation(project_type: str | None, answers: dict) -> dict | None:
    """Top curated-catalog pick for the captured idea (plan 01 Task 10):
    the deterministic select_templates ranking over the built-in library —
    no AI call, no network, no keys. A malformed catalog fails loudly."""
    if project_type not in APP_PROJECT_TYPES:
        return None
    picks = templates_mod.select_templates(
        templates_mod.load_templates(), project_type,
        answers.get("capabilities", []))
    if not picks:
        return None
    top = picks[0]
    return {"key": top.key, "name": top.name, "tagline": top.tagline,
            "why": top.why, "components": top.components,
            "tradeoffs": top.tradeoffs}


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
        if s.id == "p3":
            rec = _stack_recommendation(wiz.project_type(), answers)
            if rec is not None:
                entry["recommendation"] = rec
                # Accepting is one click: the recommended key becomes the
                # stack_template prefill. Render-contract only — the wizard
                # still validates whatever the user actually submits.
                for q in entry["questions"]:
                    if q["id"] == "stack_template" and q["value"] is None:
                        q["default"] = rec["key"]
        if s.kind != "phase":
            entry["result"] = wiz.result(s.id)
        record = records.get(s.id)
        if record is not None:
            entry["interview"] = record
        steps.append(entry)
    project_type = wiz.project_type()
    connection = connection_status(root)
    handoff = classify_handoff(root)
    return {"project_type": project_type,
            "setup_complete": setup_complete(root),
            "connection": connection,
            "connection_verified": connection.get("status") == "verified",
            "handoff": {"mode": handoff.mode.value, "valid": handoff.valid,
                        "reason": handoff.reason, "state": handoff.state},
            "onboarding_required": handoff.mode is HandoffMode.NEW,
            "onboarding_ready": (setup_complete(root)
                                  and connection.get("status") == "verified"
                                  and handoff.mode is not HandoffMode.BLOCKED),
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


def frontier_summary(root: str) -> dict:
    """FRONTIER panel payload (plan 01 Task 11): trigger the opportunistic
    scout, then report the current backlog. A Tavily outage or a corrupt
    frontier state must never break this or any other route -- maybe_scout
    already fails closed internally, and this is the belt-and-braces second
    layer. Never-ran and no-proposals states render cleanly (empty
    proposals, last_run=None)."""
    try:
        _FRONTIER_SCOUT(root)
    except Exception:
        pass
    try:
        state = frontier_store_mod.load_state(root)
    except frontier_store_mod.FrontierError as e:
        return {"error": str(e), "last_run": None, "proposals": []}
    return {"last_run": state["last_run"], "proposals": state["proposals"]}


def snapshot_token(root: str) -> str:
    """Cheap change token for SSE: mtime+size of the product state files
    (same role snapshot_version() plays for the CORTEX store)."""
    parts = []
    for rel in (TEAM_STATE_RELPATH, LOG_RELPATH, PLAN_JSON_RELPATH,
                RUNNERS_RELPATH, routing_mod.ROUTING_RELPATH,
                STATE_RELPATH, interview_mod.INTERVIEW_RELPATH, SPEC_RELPATH,
                project_mod.PROJECT_STATE_RELPATH,
                project_mod.TAKEOVER_AUDIT_RELPATH,
                product_scope_mod.FEATURES_JSON_RELPATH,
                build_mod.ADDITIONS_RELPATH, build_mod.QUEUE_RELPATH,
                build_mod.PROGRESS_TX_RELPATH,
                frontier_store_mod.STATE_RELPATH):
        try:
            st = (Path(root) / rel).stat()
            parts.append(f"{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append("-")
    return "|".join(parts)


# -- one-flow stage machine (P T8a) ------------------------------------------

FLOW_STAGE_IDS = ("connect", "describe", "approve", "build", "done")


def _connect_stage(root: str) -> dict:
    """Connect: the AI team is confirmed (SETUP) and a client connection is
    verified — the same predicates onboarding_summary gates on."""
    connection = connection_status(root)
    team_confirmed = setup_complete(root)
    complete = team_confirmed and connection.get("status") == "verified"
    return {"complete": complete, "team_confirmed": team_confirmed,
            "connection_status": connection.get("status")}


def _describe_stage(root: str) -> dict:
    """Describe: the onboarding interview is complete and the project brief
    (spec.md) has been compiled — the same artifact overview's spec_exists
    reports."""
    onboarding = onboarding_summary(root)
    complete = (Path(root) / SPEC_RELPATH).exists()
    return {"complete": complete,
            "onboarding_complete": onboarding["complete"],
            "current_step": onboarding["current_step"],
            "answered": onboarding["answered"]}


def _approve_stage(root: str) -> dict:
    """Approve: the product scope is drafted, approved exactly, and
    decomposed into a build plan that references the approved revision —
    the same gate post_build_start enforces before BUILD may start."""
    scope = None
    try:
        scope = product_scope_mod.load_scope(root)
    except product_scope_mod.ProductScopeError:
        pass
    complete = False
    if scope is not None:
        try:
            project_mod.require_approved_scope(root)
            plan, err = _read_json(Path(root) / PLAN_JSON_RELPATH)
            if plan is not None and not err:
                project_mod.require_plan_matches_scope(root, plan)
                complete = True
        except project_mod.ProjectGateConflict:
            complete = False
    return {"complete": complete,
            "scope_state": scope["approval"]["state"] if scope else None,
            "revision": scope["revision"] if scope else None,
            "features_total": len(scope["features"]) if scope else 0}


def _build_stage(root: str) -> dict:
    """Build: the relay executes the approved plan until every product
    feature is completed — derived from the same live_payload BUILD reads.
    ``saved_tokens`` is the one savings-meter number a light /api/flow
    summary gets (requirement 4); the injected/replaced breakdown lives in
    the /api/build detail endpoint's "savings" block only."""
    saved_tokens = _savings_stats(root)["saved_tokens"]
    try:
        live = build_mod.live_payload(root)
    except build_mod.BuildError:
        return {"complete": False, "status": None,
                "completed": 0, "total": 0, "running": False,
                "saved_tokens": saved_tokens}
    pid = _conductor_pid(root)
    progress = live["progress"]
    return {"complete": progress["status"] == "completed",
            "status": progress["status"],
            "completed": progress["completed"], "total": progress["total"],
            "running": pid is not None and _pid_alive(pid),
            "saved_tokens": saved_tokens}


def flow_state(root: str) -> dict:
    """The one-flow journey (Connect -> Describe -> Approve -> Build ->
    Done): an ordered stage list, which stage is current, and the merged
    team roster (requirement 4). Stage status is derived entirely from
    existing product state — no new state files. Each stage carries only a
    light summary; the SPA fetches heavy detail from the existing tab
    endpoints (/api/onboarding, /api/project, /api/build, ...).

    The dashboard's regular /api/flow poll is also the frontier scout's
    opportunistic trigger (plan 01 Task 11, no daemon/cron): a user who
    never opens the Advanced drawer still gets the weekly scout.
    maybe_scout gates itself (canonical repo + key + 7-day throttle) and
    never raises; the extra swallow here guarantees no scout bug can ever
    500 the flow heartbeat."""
    try:
        _FRONTIER_SCOUT(root)
    except Exception:
        pass
    build = _build_stage(root)
    by_id = {"connect": _connect_stage(root),
             "describe": _describe_stage(root),
             "approve": _approve_stage(root),
             "build": build,
             "done": {"complete": build["complete"]}}
    stages = [{"id": stage_id, **by_id[stage_id]}
             for stage_id in FLOW_STAGE_IDS]
    current = "done"
    for stage in stages:
        if not stage["complete"]:
            current = stage["id"]
            break
    return {"stages": stages, "current": current, "team": _team_roster(root)}


# -- write-side actions (pure functions of root+body, unit-testable) --------

GateConflict = project_mod.ProjectGateConflict


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


def _require_onboarding_ready(root: str) -> None:
    _require_setup(root)
    # Legacy unit fixtures can exercise the wizard without activation. The
    # installer always writes installation.json, so the production gate binds
    # precisely to activated projects while retaining those isolated tests.
    activated = (Path(root) / ".danza" / "runtime" /
                 "installation.json").exists()
    if not activated:
        return
    connection = connection_status(root)
    if connection.get("status") != "verified":
        raise GateConflict(
            "verify a connected AI client in Setup before onboarding")
    handoff = classify_handoff(root)
    if handoff.mode is HandoffMode.BLOCKED:
        raise GateConflict(f"runtime handoff is blocked: {handoff.reason}")
    if handoff.mode is HandoffMode.CONTINUE:
        raise GateConflict(
            "a valid runtime handoff exists; resume the assigned turn instead "
            "of starting onboarding")


def post_setup(root: str, body: dict) -> dict:
    """Confirm the team: one validated write of runners.json + routing.json
    (Decision 7). Always re-probes fresh — a confirm must never validate
    seats against stale auth. Both payloads validate BEFORE anything is
    written, so a rejected confirm leaves no torn multi-file state."""
    lineup = _require(body, "lineup", list)
    features_per_turn = _require(body, "features_per_turn", int)
    # Sequential relay is the only routing model that ships (P T8a): the
    # confirmed lineup owns every specialist seat in turn-rotation order.
    # Any "seats"/"boss_mode" in the body is ignored, like other
    # unrecognized fields (e.g. the retired budgets dial).
    active = lineup[0] if lineup else None
    seats = {"conductor": routing_mod.BUILTIN_CONDUCTOR}
    seats.update({work_type: active
                  for work_type in routing_mod.SEAT_WORK_TYPES})
    boss_mode = "sequential"
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
               "lineup": lineup, "seats": seats,
               "boss_mode": boss_mode}
    routing_mod.validate_routing(routing, config)
    installation = Path(root) / ".danza" / "runtime" / "installation.json"
    if installation.exists():
        _PREPARE_WORKSPACE(root, lineup, config)
    save_runners(root, config)
    routing_mod.save_routing(root, routing, config)
    return {"ok": True, "setup": setup_summary(root)}


def post_connection_verify(root: str, body: dict) -> dict:
    """Turn a detected runner into a verified project connection."""
    runner = _require(body, "runner", str)
    proof = verify_runner(root, runner, _live_registry(fresh=True))
    from ..product.activation import verify_installation
    installation = verify_installation(root, require_connection=True)
    return {"ok": True, "connection": proof,
            "installation": installation,
            "onboarding": onboarding_summary(root)}


def post_connection_launch(root: str, body: dict) -> dict:
    """Launch the selected interactive client without claiming auth.

    The browser can start the project-scoped tmux session; the user still
    performs any provider login there, after which Verify creates the proof
    required by onboarding.
    """
    runner = _require(body, "runner", str)
    launched = launch_runner(root, runner, _live_registry(fresh=True))
    return {"ok": True, "launch": launched,
            "setup": setup_summary(root)}


def post_workspace_open(root: str, body: dict) -> dict:
    """Open the existing project workspace without launching another client."""
    opened = open_workspace(root)
    return {"ok": True, **opened, "setup": setup_summary(root)}


def post_submit(root: str, body: dict) -> dict:
    """Phase answers in, grill round out. The submit itself is the wizard's
    (validation + stale-downstream unchanged); the grill starts fresh on
    every (re)submission (P3-D8)."""
    _require_onboarding_ready(root)
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
    _require_onboarding_ready(root)
    step_id = _require(body, "step_id", str)
    answers = _require(body, "answers", dict)
    interview_mod.record_followup_answers(root, step_id, answers)
    record = interview_mod.run_interview_round(
        root, step_id, _headless_command(root))
    return {"ok": True, "interview": record,
            "onboarding": onboarding_summary(root)}


def post_resolve(root: str, body: dict) -> dict:
    _require_onboarding_ready(root)
    step_id = _require(body, "step_id", str)
    decision = _require(body, "decision", str)
    record = interview_mod.resolve(root, step_id, decision)
    return {"ok": True, "interview": record,
            "onboarding": onboarding_summary(root)}


def post_research(root: str, body: dict) -> dict:
    """The POST is the click, and the click IS the user approval external
    research requires in every profile (research.py contract)."""
    _require_onboarding_ready(root)
    command = _headless_command(root)
    provider = None
    if command is not None:
        provider = (research_mod.tavily_from_env(command)
                    or research_mod.BossWebProvider(command))
    digest = research_mod.run_reality_check(root, provider)
    return {"ok": True, "digest": digest,
            "onboarding": onboarding_summary(root)}


def post_checkpoint(root: str, body: dict) -> dict:
    _require_onboarding_ready(root)
    step_id = _require(body, "step_id", str)
    verdict = checkpoints_mod.run_checkpoint(
        root, step_id, _headless_command(root))
    return {"ok": True, "verdict": verdict,
            "onboarding": onboarding_summary(root)}


def post_approve(root: str, body: dict) -> dict:
    """Approval stays a user act (W1 law); the grill gate holds it until
    every submitted phase is clear (spec section 7 clarity gate)."""
    _require_onboarding_ready(root)
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
    """Finish discovery and compile the interview evidence.

    Task 6 deliberately stops before product-scope drafting. Approval and
    decomposition are separate PROJECT writes; this endpoint can no longer
    create a build plan before exact-revision scope approval.
    """
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
    discovery = project_mod.discover_project(root, mode="new")
    return {"spec": str(spec_path), "project": discovery}


def post_finish(root: str, body: dict) -> dict:
    _require_onboarding_ready(root)
    out = finish_onboarding(root, _headless_command(root))
    out.update({"ok": True, "onboarding": onboarding_summary(root)})
    return out


def post_project_discover(root: str, body: dict) -> dict:
    _require_setup(root)
    mode = _require(body, "mode", str)
    return {"ok": True,
            "project": project_mod.discover_project(root, mode=mode)}


def post_project_scope(root: str, body: dict) -> dict:
    _require_setup(root)
    features = _require(body, "features", list)
    expected_revision = body.get("expected_revision")
    if expected_revision is not None and type(expected_revision) is not int:
        raise ValueError("body.expected_revision must be int")
    fingerprint = body.get("audit_fingerprint")
    if fingerprint is not None and not isinstance(fingerprint, str):
        raise ValueError("body.audit_fingerprint must be str")
    acknowledgements = body.get("acknowledged_gaps")
    if acknowledgements is not None:
        if (not isinstance(acknowledgements, list)
                or not all(isinstance(item, str) for item in acknowledgements)):
            raise ValueError("body.acknowledged_gaps must be list[str]")
    scope = project_mod.draft_scope(
        root, features=features, expected_revision=expected_revision,
        audit_fingerprint=fingerprint,
        acknowledged_gaps=acknowledgements,
    )
    return {"ok": True, "scope": scope,
            "project": project_mod.project_summary(root)}


def post_project_approve(root: str, body: dict) -> dict:
    _require_setup(root)
    expected_revision = body.get("expected_revision")
    if type(expected_revision) is not int:
        raise ValueError("body.expected_revision must be int")
    scope = project_mod.approve_project_scope(
        root, expected_revision=expected_revision)
    return {"ok": True, "scope": scope,
            "project": project_mod.project_summary(root)}


def post_project_decompose(root: str, body: dict) -> dict:
    _require_setup(root)
    project_mod.require_approved_scope(root)
    command = _headless_command(root)
    if command is None:
        raise PlanningUnavailable(
            f"{checkpoints_mod.NO_BOSS_REASON} — decomposition needs an AI agent")
    out = run_planning(root, command)
    out.update({"ok": True, "project": project_mod.project_summary(root)})
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
    try:
        build_mod.recover_progress(root)
    except build_mod.BuildError as exc:
        raise GateConflict(f"build progress is invalid: {exc}") from exc
    if not (Path(root) / PLAN_JSON_RELPATH).is_file():
        raise GateConflict(
            "finish PROJECT decomposition first — there is no build plan yet")
    plan, plan_error = _read_json(Path(root) / PLAN_JSON_RELPATH)
    if plan_error:
        raise GateConflict(f"build plan is corrupt: {plan_error}")
    project_mod.require_plan_matches_scope(root, plan)
    pid = _conductor_pid(root)
    if pid is not None and alive(pid):
        raise GateConflict("the build crew is already running")
    try:
        routing = routing_mod.load_routing(root)
        manager = StateManager(str(Path(root) / TEAM_STATE_RELPATH))
        if not (Path(root) / TEAM_STATE_RELPATH).exists():
            manager.init(mode="relay", current_boss=routing["lineup"][0],
                         max_features_per_turn=routing["features_per_turn"])
        state = manager.load()
        conclusion = execution_mod.apply_turn_conclusion(
            root, manager, state.current_boss)
    except (execution_mod.ExecutionError, routing_mod.RoutingError,
            RunnerError, StateError) as exc:
        raise GateConflict(f"build execution state is invalid: {exc}") from exc
    if conclusion["conclusion"] in {
            execution_mod.TurnConclusion.NO_WORK.value,
            execution_mod.TurnConclusion.BLOCKED.value,
            execution_mod.TurnConclusion.HARD_STOP.value}:
        return {"ok": True, "pid": None,
                "conclusion": conclusion["conclusion"]}
    log_path = Path(root) / CONDUCT_LOG_RELPATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # append mode: a restarted relay extends the evidence, never truncates
    with open(log_path, "ab") as log:
        proc = popen([sys.executable, "-m", "danzaboss.cli",
                      "conduct", root],
                     stdout=log, stderr=subprocess.STDOUT,
                     start_new_session=True)
    return {"ok": True, "pid": proc.pid,
            "conclusion": conclusion["conclusion"]}


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


def post_build_additions(root: str, body: dict) -> dict:
    """Save one isolated additions draft against the valid active BUILD."""
    _require_setup(root)
    additions = body.get("additions")
    if not isinstance(additions, list):
        raise ValueError("body.additions must be list")
    expected_revision = body.get("expected_revision")
    if expected_revision is not None and type(expected_revision) is not int:
        raise ValueError("body.expected_revision must be int")
    draft = build_mod.draft_additions(
        root, additions=additions, expected_revision=expected_revision)
    return {"ok": True, "additions": draft,
            **build_mod.live_payload(root)}


def post_build_approve(root: str, body: dict, *,
                       propose: Callable | None = None) -> dict:
    """Approve exact additions, replan unfinished work, and queue handoff."""
    _require_setup(root)
    expected_revision = body.get("expected_revision")
    if type(expected_revision) is not int:
        raise ValueError("body.expected_revision must be int")
    if propose is None:
        command = _headless_command(root)
        if command is None:
            raise PlanningUnavailable(
                f"{checkpoints_mod.NO_BOSS_REASON} — replanning needs an AI agent")

        def propose(scope, spec_ref, reserved_unit_ids):
            return propose_plan(
                root, command, scope=scope, spec_ref=spec_ref,
                reserved_unit_ids=reserved_unit_ids)

    queued = build_mod.approve_additions(
        root, expected_revision=expected_revision, propose=propose)
    return {"ok": True, "queued": queued,
            **build_mod.live_payload(root)}


def post_frontier_decide(root: str, body: dict) -> dict:
    """Approve or dismiss one frontier proposal (plan 01 Task 11). Approving
    keeps the proposal's approved status in the frontier store (panel
    history) AND routes it into the same additions store the Build editor
    uses for user-added future work — as a pending draft feature that only
    ever builds after the normal human additions-approval + replan flow.
    Nothing is ever auto-built. The frontier proposal's own revision
    fingerprint gates the whole action. A routing failure after a committed
    approval is reported in the payload (backlog_error), never hidden and
    never a torn 500. No setup/onboard gate: the scout only ever produces
    proposals in the canonical, unactivated repo, which has neither."""
    proposal_id = body.get("proposal_id")
    if type(proposal_id) is not int:
        raise ValueError("body.proposal_id must be int")
    decision = _require(body, "decision", str)
    expected_revision = body.get("expected_revision")
    if type(expected_revision) is not int:
        raise ValueError("body.expected_revision must be int")
    record = frontier_store_mod.decide(
        root, proposal_id, decision, expected_revision=expected_revision)
    out = {"ok": True, "proposal": record}
    if record["status"] == "approved":
        try:
            out["backlog_feature"] = build_mod.append_backlog_feature(
                root, **frontier_store_mod.backlog_feature(record))
        except build_mod.BuildError as e:
            out["backlog_error"] = str(e)
    out["frontier"] = frontier_summary(root)
    return out


_POST_ROUTES = {
    "/api/setup": post_setup,
    "/api/connection/launch": post_connection_launch,
    "/api/connection/verify": post_connection_verify,
    "/api/workspace/open": post_workspace_open,
    "/api/build/start": post_build_start,
    "/api/build/stop": post_build_stop,
    "/api/build/additions": post_build_additions,
    "/api/build/approve": post_build_approve,
    "/api/onboard/submit": post_submit,
    "/api/onboard/followup": post_followup,
    "/api/onboard/resolve": post_resolve,
    "/api/onboard/research": post_research,
    "/api/onboard/checkpoint": post_checkpoint,
    "/api/onboard/approve": post_approve,
    "/api/onboard/finish": post_finish,
    "/api/project/discover": post_project_discover,
    "/api/project/scope": post_project_scope,
    "/api/project/approve": post_project_approve,
    "/api/project/decompose": post_project_decompose,
    "/api/frontier/decide": post_frontier_decide,
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
            elif route == "/api/flow":
                self._json(flow_state(self.root))
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
            elif route == "/api/project":
                self._json(project_mod.project_summary(self.root))
            elif route == "/api/plan":
                self._json(plan_detail(self.root))
            elif route == "/api/frontier":
                self._json(frontier_summary(self.root))
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
        except (GateConflict, product_scope_mod.RevisionConflict,
                build_mod.BuildRevisionConflict,
                frontier_store_mod.FrontierRevisionConflict) as e:
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
