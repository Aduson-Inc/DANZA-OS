"""`danza cortex` command group — the CLI surface agents and hooks call (C1).

Design rules:
  * hook subcommands FAIL OPEN (stderr + exit 0) — a CORTEX bug never bricks
    a session; same discipline as cli.py's guard hook.
  * non-hook subcommands are normal CLI: JSON out, nonzero exit on user error.
  * the store is repo-scoped: <cwd>/.danza/cortex/cortex.db
"""
from __future__ import annotations

import json
import os
import sys
from typing import Optional, TextIO

from .events import CaptureLog
from .extract import configured_extractor, draft_observations
from .factory import db_path, open_store
from .identity import resolve_project
from .learn import learn
from .inject import build_context
from .intent import WorkspaceState
from .observation import Observation
from ..hooks.gates import distillation_gate
from ..kernel.profile import active_profile, capture_event


def _project(root: str) -> str:
    return resolve_project(root)


def _read_json(stdin: TextIO) -> dict:
    raw = stdin.read()
    return json.loads(raw) if raw.strip() else {}


# ---- hook handlers (fail open) -----------------------------------------------

def _hook_session_start(root: str, payload: dict) -> int:
    sid = payload.get("session_id", "unknown")
    log = CaptureLog(db_path(root))
    log.open_session(sid, _project(root), environment="claude-code")
    store = open_store(root)
    # C5 scheduler: every session start is the tick — archive what expired
    # and apply usage learning BEFORE context is assembled, so the injected
    # block already reflects the store's learned state.
    store.age()
    learn(store)
    # C4.5 profile gate: OS_DEV (Layer 0) keeps CORTEX silent — store
    # housekeeping (age/learn) still runs, but no memory is injected into the
    # dev session. Runtime profiles (OS_BOOT_TEST/APP_BUILD) inject as before.
    if not active_profile(root).session_inject:
        return 0
    block = build_context(store, _project(root), stats=log.stats(_project(root)))
    if block:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart", "additionalContext": block}}))
    return 0


def _hook_post_tool_use(root: str, payload: dict) -> int:
    sid = payload.get("session_id", "unknown")
    ti = payload.get("tool_input", {}) or {}
    tool = payload.get("tool_name", "")
    command = ti.get("command", "")
    # C4.5 memory diet: the profile decides what becomes memory pressure.
    # OS_DEV (none) captures nothing — claude-mem holds build memory, so only one
    # memory system runs during OS builds. Runtime profiles capture per level.
    if not capture_event(active_profile(root), tool, command):
        return 0
    resp = payload.get("tool_response", {}) or {}
    outcome = ""
    if isinstance(resp, dict):
        outcome = str(resp.get("success", ""))[:200]
    log = CaptureLog(db_path(root))
    log.open_session(sid, _project(root))  # idempotent safety net
    log.record_event(sid, tool,
                     file_path=ti.get("file_path") or ti.get("path") or "",
                     command=command, outcome=outcome)
    return 0


def _hook_stop(root: str, payload: dict) -> int:
    sid = payload.get("session_id", "unknown")
    log = CaptureLog(db_path(root))
    sess = log.session(sid)
    if sess is None:
        return 0  # nothing captured -> nothing to gate
    prof = active_profile(root)
    # C4.5 profile gate: OS_DEV (Layer 0) does not nag for distillation — close
    # the session clean without blocking or drafting. Runtime profiles enforce.
    if not prof.distill_gate_active:
        log.mark_processed(sid)
        log.end_session(sid)
        return 0
    pending = log.pending(sid)
    decision = distillation_gate(len(pending), sess["observations_written"],
                                 bool(sess["gate_blocked"]),
                                 min_events=prof.distill_min_events)
    if not decision.allow:
        log.mark_gate_blocked(sid)
        print(json.dumps({"decision": "block", "reason": decision.reason}))
        return 0
    if (len(pending) >= prof.distill_min_events
            and sess["observations_written"] == 0):
        # tier-2 floor: gate already blocked once (or never applied) -> draft.
        # Below the profile's noise floor nothing is drafted: tiny sessions
        # must not become observation spam (C4.5 memory diet).
        store = open_store(root)
        # Tier 3 first when configured (off by default); its failure or
        # empty answer always falls back to the deterministic Tier-2 floor.
        tier3 = configured_extractor(root)
        drafts = tier3.extract(pending, _project(root)) if tier3 else []
        for d in drafts or draft_observations(pending, _project(root)):
            store.upsert(d)
    log.mark_processed(sid)
    log.end_session(sid)
    return 0


_HOOKS = {"session-start": _hook_session_start,
          "post-tool-use": _hook_post_tool_use,
          "stop": _hook_stop}


def _cmd_hook(argv: list[str], root: str, stdin: TextIO) -> int:
    event = argv[0] if argv else ""
    handler = _HOOKS.get(event)
    if handler is None:
        print(f"unknown cortex hook event: {event!r}", file=sys.stderr)
        return 0  # fail open even on bad wiring
    try:
        return handler(root, _read_json(stdin))
    except Exception as e:  # noqa: BLE001 — fail open by design
        print(f"cortex hook internal error (failing open): {e}", file=sys.stderr)
        return 0


# ---- agent-facing commands -----------------------------------------------------

def _cmd_observe(argv: list[str], root: str, stdin: TextIO) -> int:
    session_id = None
    if "--session" in argv:
        session_id = argv[argv.index("--session") + 1]
    log = CaptureLog(db_path(root))
    if "--nothing-meaningful" in argv:
        if session_id:
            log.mark_processed(session_id)
            log.mark_gate_blocked(session_id)  # gate passes on next stop
        print(json.dumps({"status": "marked", "session": session_id}))
        return 0
    try:
        payload = _read_json(stdin)
    except json.JSONDecodeError as e:
        print(f"observe: invalid JSON on stdin: {e}", file=sys.stderr)
        return 2
    items = payload if isinstance(payload, list) else [payload]
    store = open_store(root)
    stored = []
    for item in items:
        item.setdefault("project", _project(root))
        try:
            obs = Observation(**item)
        except TypeError as e:
            print(f"observe: bad observation fields: {e}", file=sys.stderr)
            return 2
        stored.append(store.upsert(obs).id)
    if session_id:
        log.note_observations(session_id, len(stored))
        log.mark_processed(session_id)
    print(json.dumps({"stored": stored}))
    return 0


def _cmd_get(argv: list[str], root: str, stdin: TextIO) -> int:
    store = open_store(root)
    out = []
    for oid in argv:
        o = store.get(oid)
        if o:
            store.record_use(oid, source="get")
            out.append(o.to_row())
    print(json.dumps(out, indent=2))
    return 0


def _cmd_search(argv: list[str], root: str, stdin: TextIO) -> int:
    text = " ".join(argv)
    results = open_store(root).backend.search(text, project=_project(root))
    print(json.dumps([{"id": o.id, "type": o.type, "title": o.title,
                       "importance": o.importance, "confidence": o.confidence}
                      for o in results], indent=2))
    return 0


def workspace_snapshot(root: str) -> WorkspaceState:
    """Cheap L0 snapshot for intent detection: branch from .git/HEAD (no
    subprocess) + recent tool mix from the capture log's latest events."""
    branch = ""
    try:
        with open(os.path.join(root, ".git", "HEAD"), encoding="utf-8") as fh:
            head = fh.read().strip()
        if head.startswith("ref:"):
            branch = head.split("/", 2)[-1]
    except OSError:
        pass
    tools: list[str] = []
    commands: list[str] = []
    changed: list[str] = []
    try:
        log = CaptureLog(db_path(root))
        rows = log.conn.execute(
            "SELECT tool, command, file_path FROM events "
            "ORDER BY id DESC LIMIT 50").fetchall()
        for r in rows:
            tools.append(r["tool"])
            if r["command"]:
                commands.append(r["command"])
            if r["file_path"] and r["file_path"] not in changed:
                changed.append(r["file_path"])
    except Exception:  # noqa: BLE001 — snapshot is best-effort by design
        pass
    return WorkspaceState(branch=branch, recent_tools=tools,
                          recent_commands=commands, changed_files=changed)


def _cmd_retrieve(argv: list[str], root: str, stdin: TextIO) -> int:
    """danza cortex retrieve "<prompt>" [--budget N] [--intent NAME]
    [--types a,b] [--json | --explain]

    Default output is the assembled context package (what an agent injects);
    --explain prints the readable trace, --json the full machine trace.
    """
    from .explain import render, trace  # local: keep hook path imports lean
    from .graph import GraphStore
    from .quality import build_package

    def take_opt(flag: str) -> Optional[str]:
        if flag in argv:
            i = argv.index(flag)
            val = argv[i + 1]
            del argv[i:i + 2]
            return val
        return None

    budget = int(take_opt("--budget") or 1500)
    intent_override = take_opt("--intent")
    types_arg = take_opt("--types")
    types = [t.strip() for t in types_arg.split(",")] if types_arg else None
    as_json = "--json" in argv
    as_explain = "--explain" in argv
    prompt = " ".join(a for a in argv if not a.startswith("--"))
    if not prompt.strip():
        print("retrieve: a prompt is required", file=sys.stderr)
        return 2

    store = open_store(root)
    bundle = build_package(store, prompt, _project(root), budget=budget,
                           types=types, workspace=workspace_snapshot(root),
                           intent_override=intent_override,
                           graph=GraphStore(db_path(root)))
    for item in bundle.package.items:
        store.record_use(item.observation.id, source="retrieve")
    if as_json:
        print(json.dumps(trace(bundle), indent=2))
    elif as_explain:
        print(render(bundle))
    else:
        print(bundle.package.render() or "(no relevant observations)")
    return 0


def _cmd_context(argv: list[str], root: str, stdin: TextIO) -> int:
    """danza cortex context [--driver <agent-id> --task "<task>" [--budget N]
    [--json]]

    Bare form prints the session-start injection block (unchanged). With
    --driver it compiles a budget-capped, role-specific CORTEX package for that
    driver — the APP_BUILD front-door for per-driver context.
    """
    if "--driver" in argv:
        return _cmd_driver_context(argv, root)
    store = open_store(root)
    log = CaptureLog(db_path(root))
    print(build_context(store, _project(root), stats=log.stats(_project(root))))
    return 0


def _cmd_driver_context(argv: list[str], root: str) -> int:
    from .driver_context import compile_driver_context  # local: optional path
    from .graph import GraphStore

    def take_opt(flag: str) -> Optional[str]:
        if flag in argv:
            i = argv.index(flag)
            val = argv[i + 1] if i + 1 < len(argv) else None
            del argv[i:i + 2]
            return val
        return None

    driver = take_opt("--driver")
    task = take_opt("--task")
    budget_opt = take_opt("--budget")
    budget = int(budget_opt) if budget_opt else None   # None -> role default
    as_json = "--json" in argv
    if not driver or not task:
        print("context --driver <agent-id> --task \"<task>\" [--budget N] [--json]",
              file=sys.stderr)
        return 2

    store = open_store(root)
    ctx = compile_driver_context(store, driver, task, _project(root),
                                 budget=budget,
                                 workspace=workspace_snapshot(root),
                                 graph=GraphStore(db_path(root)))
    for item in ctx.package.items:
        store.record_use(item.observation.id, source="driver-context")
    # P4 T11: the compile seat is the one place every driver context passes,
    # so this is where per-agent spend telemetry gets its row.
    CaptureLog(db_path(root)).record_context_read(
        _project(root), driver, ctx.used, ctx.budget, ctx.adaptation)
    print(json.dumps(ctx.to_dict(), indent=2) if as_json
          else (ctx.render() or "(no relevant observations)"))
    return 0


def _cmd_age(argv: list[str], root: str, stdin: TextIO) -> int:
    store = open_store(root)
    print(json.dumps(store.age()))
    return 0


def _cmd_learn(argv: list[str], root: str, stdin: TextIO) -> int:
    """danza cortex learn — one usage-learning pass; prints what shifted."""
    store = open_store(root)
    print(json.dumps(learn(store), indent=2))
    return 0


def _cmd_stats(argv: list[str], root: str, stdin: TextIO) -> int:
    log = CaptureLog(db_path(root))
    s = log.stats(_project(root))
    s["observations_stored"] = len(
        open_store(root).backend.all(_project(root)))
    print(json.dumps(s, indent=2))
    return 0


def _cmd_index(argv: list[str], root: str, stdin: TextIO) -> int:
    """danza cortex index [--commits N] — rebuild the knowledge graph for this
    repo: scan files, ingest git history, link observations. Deterministic
    rebuild (clear + rescan) so the graph never drifts from reality."""
    from .git_intel import ingest_git, link_observations
    from .graph import GraphStore
    from .repo_intel import scan_repo
    limit = 200
    if "--commits" in argv:
        limit = int(argv[argv.index("--commits") + 1])
    graph = GraphStore(db_path(root))
    project = _project(root)
    graph.clear(project)
    stats = scan_repo(root, project, graph)
    stats.update(ingest_git(root, project, graph, limit=limit))
    store = open_store(root)
    stats.update(link_observations(store, project, graph))
    print(json.dumps(stats, indent=2))
    return 0


def _cmd_graph(argv: list[str], root: str, stdin: TextIO) -> int:
    """danza cortex graph <node-id-or-name> [--impact] [--deps] [--depth N]
    Default prints neighbors; --impact prints "what breaks if this changes"."""
    from .graph import GraphStore

    def take_opt(flag: str) -> Optional[str]:
        if flag in argv:
            i = argv.index(flag)
            val = argv[i + 1]
            del argv[i:i + 2]
            return val
        return None

    depth = int(take_opt("--depth") or 4)
    impact = "--impact" in argv
    deps = "--deps" in argv
    query = " ".join(a for a in argv if not a.startswith("--"))
    if not query.strip():
        print("graph: a node id or name is required", file=sys.stderr)
        return 2
    graph = GraphStore(db_path(root))
    node = graph.node(query)
    if node is None:
        hits = graph.find(query)
        if not hits:
            print(json.dumps({"error": f"no node matches {query!r}"}))
            return 1
        node = hits[0]
    if impact or deps:
        closure = (graph.impact if impact else graph.dependencies)(
            node.id, max_depth=depth)
        print(json.dumps({"node": node.id,
                          "mode": "impact" if impact else "dependencies",
                          "count": len(closure),
                          "closure": [{"id": i, "depth": d}
                                      for i, d in closure]}, indent=2))
    else:
        print(json.dumps({"node": node.id,
                          "neighbors": graph.neighbors(node.id)}, indent=2))
    return 0


def _cmd_ui(argv: list[str], root: str, stdin: TextIO) -> int:
    from .ui.server import serve  # local import: UI is optional at runtime
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else None
    serve(root, port=port)
    return 0


def _cmd_mcp(argv: list[str], root: str, stdin: TextIO) -> int:
    """danza cortex mcp — MCP stdio server; an external client's doorway
    into this repo's memory (C6). Blocks until the client closes stdin."""
    from .mcp_server import CortexMcpServer  # local: protocol loop is optional
    return CortexMcpServer(root).run(stdin=stdin)


_COMMANDS = {"hook": _cmd_hook, "observe": _cmd_observe, "get": _cmd_get,
             "search": _cmd_search, "retrieve": _cmd_retrieve,
             "context": _cmd_context, "age": _cmd_age, "learn": _cmd_learn,
             "stats": _cmd_stats, "ui": _cmd_ui, "index": _cmd_index,
             "graph": _cmd_graph, "mcp": _cmd_mcp}


def main(argv: list[str], *, root: Optional[str] = None,
         stdin: Optional[TextIO] = None) -> int:
    root = root or os.getcwd()
    stdin = stdin if stdin is not None else sys.stdin
    if not argv or argv[0] not in _COMMANDS:
        print("danza cortex <hook|observe|get|search|retrieve|context|age|learn"
              "|stats|ui|index|graph|mcp> ...", file=sys.stderr)
        return 2
    return _COMMANDS[argv[0]](argv[1:], root, stdin)
