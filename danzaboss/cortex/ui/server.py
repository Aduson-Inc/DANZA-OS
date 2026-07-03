"""CORTEX web dashboard — stdlib HTTP server on 127.0.0.1:33000 (C2).

Read-only window over the repo-scoped store (spec section 6): the UI can look,
filter, and explain, but never mutates memory. The single exception is
/api/settings, which writes display/injection knobs to ui-settings.json —
config, not curation. SSE at /api/events?stream pushes a refresh signal when
new observations land, so the feed updates live while you work.

Stdlib only. No build step; static assets live next to this file.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from ..events import CaptureLog
from ..inject import est_tokens
from ..sqlite_backend import SqliteBackend
from ..store import ObservationStore

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml"}

DEFAULT_SETTINGS = {"port": 33000, "max_full": 5, "token_ceiling": 2000,
                    "show_economics": True}


def settings_path(root: str) -> str:
    return os.path.join(root, ".danza", "cortex", "ui-settings.json")


def load_settings(root: str) -> dict:
    try:
        with open(settings_path(root), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        data = {}
    merged = dict(DEFAULT_SETTINGS)
    merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    return merged


def save_settings(root: str, updates: dict) -> dict:
    merged = load_settings(root)
    merged.update({k: v for k, v in updates.items() if k in DEFAULT_SETTINGS})
    path = settings_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2)
    return merged


def _trim(o) -> dict:
    """Feed-sized projection of an observation (full record via /api/observations/<id>)."""
    return {"id": o.id, "title": o.title, "summary": o.summary, "type": o.type,
            "importance": o.importance, "confidence": o.confidence,
            "confidence_source": o.confidence_source, "reasoning": o.reasoning,
            "tags": o.tags, "concepts": o.concepts, "files": o.files,
            "evidence": o.evidence, "created": o.created, "updated": o.updated,
            "usage_count": o.usage_count, "superseded_by": o.superseded_by,
            "read_tokens": est_tokens(o.summary + o.reasoning)}


def snapshot_version(db_path: str) -> str:
    """Cheap change token for SSE: observation count + latest update stamp."""
    be = SqliteBackend(db_path)
    row = be.conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(updated), '') FROM observations").fetchone()
    return f"{row[0]}:{row[1]}"


class CortexUIHandler(BaseHTTPRequestHandler):
    # set by make_server():
    root: str = "."
    db_path: str = ""
    project: str = ""

    server_version = "CortexUI/1.0"

    def log_message(self, fmt, *args):  # keep the terminal quiet
        pass

    # -- plumbing ----------------------------------------------------------
    def _json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, name: str) -> None:
        path = os.path.join(_STATIC_DIR, os.path.basename(name))
        ext = os.path.splitext(path)[1]
        if not os.path.exists(path) or ext not in _MIME:
            self._json({"error": "not found"}, 404)
            return
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", _MIME[ext])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _store(self) -> ObservationStore:
        return ObservationStore(SqliteBackend(self.db_path))

    # -- routes -------------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(parsed.query)
        route = parsed.path
        try:
            if route == "/" or route == "/index.html":
                self._static("index.html")
            elif route.startswith("/static/"):
                self._static(route[len("/static/"):])
            elif route == "/api/observations":
                self._api_observations(q)
            elif route.startswith("/api/observations/"):
                self._api_observation(route.rsplit("/", 1)[1])
            elif route == "/api/sessions":
                self._api_sessions()
            elif route == "/api/stats":
                self._api_stats()
            elif route == "/api/settings":
                self._json(load_settings(self.root))
            elif route == "/api/explain":
                self._api_explain(q)
            elif route == "/api/graph":
                self._api_graph(q)
            elif route == "/api/events":
                self._api_events()
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
        if urllib.parse.urlparse(self.path).path != "/api/settings":
            self._json({"error": "read-only: memory is agent-governed"}, 405)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            updates = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json({"error": "invalid JSON"}, 400)
            return
        self._json(save_settings(self.root, updates))

    # -- API impls ------------------------------------------------------------
    def _api_observations(self, q: dict) -> None:
        text = (q.get("q") or [""])[0]
        typ = (q.get("type") or [""])[0]
        importance = (q.get("importance") or [""])[0]
        limit = int((q.get("limit") or ["50"])[0])
        offset = int((q.get("offset") or ["0"])[0])
        be = SqliteBackend(self.db_path)
        if text.strip():
            items = be.search(text, project=self.project, limit=500)
        else:
            items = be.all(self.project)
            items.sort(key=lambda o: o.updated, reverse=True)
        if typ:
            items = [o for o in items if o.type == typ]
        if importance:
            items = [o for o in items if o.importance == importance]
        total = len(items)
        self._json({"total": total,
                    "items": [_trim(o) for o in items[offset:offset + limit]]})

    def _api_observation(self, obs_id: str) -> None:
        o = self._store().get(obs_id)
        if o is None:
            self._json({"error": "not found"}, 404)
            return
        self._json(o.to_row())

    def _api_sessions(self) -> None:
        log = CaptureLog(self.db_path)
        rows = log.conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT 50").fetchall()
        self._json({"items": [dict(r) for r in rows]})

    def _api_stats(self) -> None:
        log = CaptureLog(self.db_path)
        s = log.stats(self.project)
        by_type: dict[str, int] = {}
        by_importance: dict[str, int] = {}
        read_tokens = 0
        for o in SqliteBackend(self.db_path).all(self.project):
            by_type[o.type] = by_type.get(o.type, 0) + 1
            by_importance[o.importance] = by_importance.get(o.importance, 0) + 1
            read_tokens += est_tokens(o.summary + o.reasoning)
        s.update({"by_type": by_type, "by_importance": by_importance,
                  "observations_stored": sum(by_type.values()),
                  "read_tokens": read_tokens, "project": self.project})
        self._json(s)

    def _api_explain(self, q: dict) -> None:
        """Run the REAL C3 pipeline on a hypothetical prompt and return the
        full trace — the explain playground is a window, not a simulation."""
        from ..commands import workspace_snapshot
        from ..explain import trace as explain_trace
        from ..graph import GraphStore
        from ..quality import build_package
        prompt = (q.get("prompt") or [""])[0]
        if not prompt.strip():
            self._json({"error": "prompt required"}, 400)
            return
        budget = int((q.get("budget") or ["1500"])[0])
        bundle = build_package(self._store(), prompt, self.project, budget=budget,
                               workspace=workspace_snapshot(self.root),
                               graph=GraphStore(self.db_path))
        self._json(explain_trace(bundle))

    def _api_graph(self, q: dict) -> None:
        """Knowledge-graph window (C4): node search, neighborhood/impact
        subgraphs, or a degree-ranked overview when called bare."""
        from ..graph import GraphStore
        graph = GraphStore(self.db_path)
        text = (q.get("q") or [""])[0]
        node = (q.get("node") or [""])[0]
        if text.strip() and not node:
            self._json({"matches": [{"id": n.id, "kind": n.kind, "name": n.name}
                                    for n in graph.find(text)]})
            return
        if not node:
            top = graph.conn.execute(
                "SELECT n.id, n.kind, n.name, COUNT(*) AS degree "
                "FROM graph_nodes n JOIN graph_edges e "
                "ON e.src = n.id OR e.dst = n.id "
                "GROUP BY n.id ORDER BY degree DESC, n.id LIMIT 12").fetchall()
            self._json({"stats": graph.stats(),
                        "top": [dict(r) for r in top]})
            return
        if graph.node(node) is None:
            self._json({"error": f"unknown node: {node}"}, 404)
            return
        depth = int((q.get("depth") or ["2"])[0])
        mode = (q.get("mode") or ["neighborhood"])[0]
        nodes, edges = graph.subgraph(node, depth=depth, mode=mode)
        self._json({"center": node, "mode": mode, "depth": depth,
                    "nodes": [{"id": n.id, "kind": n.kind, "name": n.name,
                               "attrs": n.attrs} for n in nodes],
                    "edges": edges})

    def _api_events(self) -> None:
        """SSE: emit a refresh event whenever the store's change token moves."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        last = snapshot_version(self.db_path)
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                time.sleep(2)
                now = snapshot_version(self.db_path)
                if now != last:
                    last = now
                    self.wfile.write(b'data: {"type": "refresh"}\n\n')
                else:
                    self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


def make_server(root: str, port: int = 0) -> ThreadingHTTPServer:
    """Bind 127.0.0.1 only. port=0 -> ephemeral (tests)."""
    handler = type("BoundHandler", (CortexUIHandler,), {
        "root": root,
        "db_path": os.path.join(root, ".danza", "cortex", "cortex.db"),
        "project": os.path.basename(os.path.abspath(root)),
    })
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def serve(root: str, port: Optional[int] = None) -> None:
    port = port if port is not None else int(load_settings(root)["port"])
    server = make_server(root, port)
    host, bound = server.server_address[0], server.server_address[1]
    print(f"CORTEX dashboard: http://{host}:{bound}  (Ctrl-C to stop)")
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
