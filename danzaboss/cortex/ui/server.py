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
from ..identity import resolve_project
from ..inject import est_tokens
from ..sqlite_backend import SqliteBackend
from ..store import ObservationStore

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml",
         ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp"}

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
            elif route == "/api/console":
                self._api_console(q)
            elif route == "/api/workflow":
                self._api_workflow()
            elif route == "/api/meta":
                self._api_meta()
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
        # simple human-friendly numbers (#1, #2, …) — stable per store, mapped
        # from the observations table rowid, like a ticket number
        nums = {r[1]: r[0] for r in be.conn.execute(
            "SELECT rowid, id FROM observations").fetchall()}
        out = []
        for o in items[offset:offset + limit]:
            row = _trim(o)
            row["num"] = nums.get(o.id, 0)
            out.append(row)
        self._json({"total": total, "items": out})

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

    def _api_console(self, q: dict) -> None:
        """Console stream (C4.5 UI): the raw telemetry that stays OUT of the
        memory feed — tool events, session lifecycle, distillation gate hits.
        Newest first, merged across sources, honestly derived from the capture
        log (no synthetic event kinds)."""
        limit = int((q.get("limit") or ["200"])[0])
        log = CaptureLog(self.db_path)
        rows: list[dict] = []
        for r in log.conn.execute(
                "SELECT session_id, ts, tool, file_path, command, outcome "
                "FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall():
            d = dict(r)
            kind = "memory"
            if d["tool"] == "Bash":
                kind = "command"
            elif d["tool"] in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                kind = "mutation"
            rows.append({"kind": kind, "ts": d["ts"], "session": d["session_id"],
                         "detail": d["file_path"] or d["command"] or d["tool"],
                         "tool": d["tool"], "outcome": d["outcome"]})
        for r in log.conn.execute(
                "SELECT id, started_at, ended_at, status, gate_blocked, "
                "observations_written FROM sessions "
                "ORDER BY started_at DESC LIMIT 40").fetchall():
            d = dict(r)
            rows.append({"kind": "session", "ts": d["started_at"],
                         "session": d["id"], "tool": "SessionStart",
                         "detail": "session opened", "outcome": ""})
            if d["gate_blocked"]:
                rows.append({"kind": "gate", "ts": d["ended_at"] or d["started_at"],
                             "session": d["id"], "tool": "Stop",
                             "detail": "distillation gate blocked the stop",
                             "outcome": ""})
            if d["ended_at"]:
                rows.append({"kind": "session", "ts": d["ended_at"],
                             "session": d["id"], "tool": "Stop",
                             "detail": f"session closed · "
                                       f"{d['observations_written']} distilled",
                             "outcome": ""})
        rows.sort(key=lambda r: r["ts"], reverse=True)
        self._json({"items": rows[:limit]})

    def _api_workflow(self) -> None:
        """Workflow map (C4.5 UI): the knowledge graph aggregated into big
        subsystem/feature blocks — n8n-style nodes, not one node per file.
        Each block lists its member files; edges are import flows between
        blocks weighted by how many file-level imports they bundle."""
        from ..graph import GraphStore
        graph = GraphStore(self.db_path)

        def group_of(path: str) -> str:
            parts = path.split("/")
            if len(parts) == 1:
                return "root"
            if parts[0] == "danzaboss":
                return "/".join(parts[:2]) if len(parts) > 2 else parts[0]
            return parts[0]

        files = graph.conn.execute(
            "SELECT id, name FROM graph_nodes WHERE kind = 'file'").fetchall()
        member: dict[str, list[str]] = {}
        gid: dict[str, str] = {}          # file node id -> group key
        for node_id, name in files:
            g = group_of(name)
            member.setdefault(g, []).append(name)
            gid[node_id] = g
        obs_count: dict[str, int] = {}
        for (src, dst) in graph.conn.execute(
                "SELECT src, dst FROM graph_edges WHERE relation = 'about'").fetchall():
            if dst in gid:
                g = gid[dst]
                obs_count[g] = obs_count.get(g, 0) + 1
        flows: dict[tuple[str, str], int] = {}
        for (src, dst) in graph.conn.execute(
                "SELECT src, dst FROM graph_edges WHERE relation = 'imports'").fetchall():
            gs, gd = gid.get(src), gid.get(dst)
            if gs and gd and gs != gd:
                flows[(gs, gd)] = flows.get((gs, gd), 0) + 1
        nodes = [{"id": g, "label": g.split("/")[-1], "files": sorted(fs),
                  "file_count": len(fs), "observations": obs_count.get(g, 0)}
                 for g, fs in sorted(member.items())]
        edges = [{"src": s, "dst": d, "weight": w}
                 for (s, d), w in sorted(flows.items())]
        self._json({"nodes": nodes, "edges": edges})

    def _api_meta(self) -> None:
        """Top-bar dropdown data: known projects and AI environments."""
        be = SqliteBackend(self.db_path)
        projects = [r[0] for r in be.conn.execute(
            "SELECT DISTINCT project FROM observations ORDER BY project").fetchall()]
        log = CaptureLog(self.db_path)
        envs = [r[0] for r in log.conn.execute(
            "SELECT DISTINCT environment FROM sessions "
            "WHERE environment != '' ORDER BY environment").fetchall()]
        self._json({"project": self.project,
                    "projects": projects or [self.project],
                    "environments": envs or ["claude-code"]})

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
        "project": resolve_project(root),
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
