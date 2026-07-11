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
import threading
import time
import urllib.parse
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from ..cortex import commands as cortex_commands
from ..cortex.events import CaptureLog
from ..cortex.identity import resolve_project
from ..cortex.inject import est_tokens
from ..cortex.sqlite_backend import SqliteBackend
from ..cortex.ui.server import CortexUIHandler
from ..kernel.profile import active_profile
from .conductor import LOG_RELPATH, TEAM_STATE_RELPATH
from .planner import (PLAN_JSON_RELPATH, PLAN_MD_RELPATH, PlanningError,
                      parse_plan)
from .runners import RUNNERS_RELPATH, RunnerError, load_runners
from .state import STATE_RELPATH
from .wizard import Wizard

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
DEFAULT_PORT = 33100  # CORTEX keeps 33000 (D4)


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
    return {"boss": config.get("boss"),
            "session_host": config.get("session_host"),
            "detected": sorted(n for n, e in config.get("runners", {}).items()
                               if e.get("detected"))}


def _cortex_stats(root: str) -> dict:
    """The home-screen CORTEX strip — the same numbers the CORTEX stats view
    computes, so the two UIs can never disagree."""
    db = cortex_commands.db_path(root)
    project = resolve_project(root)
    s = CaptureLog(db).stats(project)
    count = read_tokens = 0
    for o in SqliteBackend(db).all(project):
        count += 1
        read_tokens += est_tokens(o.summary + o.reasoning)
    s.update({"observations_stored": count, "read_tokens": read_tokens})
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


def onboarding_summary(root: str) -> dict:
    """Wizard progress, read-only — Phase 3 turns this into /onboard forms."""
    wiz = Wizard(root)
    current = wiz.current_step()
    return {"project_type": wiz.project_type(),
            "complete": wiz.is_complete(),
            "current_step": current.id if current else None,
            "answered": len(wiz.answers),
            "steps": [{"id": s.id, "kind": s.kind, "title": s.title,
                       "status": wiz.status(s.id),
                       "questions": len(s.questions)}
                      for s in wiz.flow()]}


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
                RUNNERS_RELPATH, STATE_RELPATH):
        try:
            st = (Path(root) / rel).stat()
            parts.append(f"{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append("-")
    return "|".join(parts)


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
                limit = int((q.get("limit") or ["100"])[0])
                self._json(conductor_tail(self.root, limit))
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

    def do_POST(self):
        route = urllib.parse.urlparse(self.path).path
        if route.startswith("/cortex/"):
            self.path = self.path[len("/cortex"):]
            CortexUIHandler.do_POST(self)
            return
        self._json({"error": "read-only: product state is CLI-governed"}, 405)

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
