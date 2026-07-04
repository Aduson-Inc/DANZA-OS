"""MCP stdio server for CORTEX (C6) — the VPS/external-tool doorway.

Model Context Protocol over stdio: newline-delimited JSON-RPC 2.0. Stdlib
only — the transport is line-framed JSON, so no SDK is needed. Any MCP client
(Claude Code, an IDE, Hermes on the VPS) can search, fetch, and retrieve
CORTEX packages without touching the repo's CLI.

Read-only by design: the four tools mirror the agent-facing read surface
(search/get/retrieve/context). Distillation stays with in-session agents —
external clients consume memory, they do not write it.

Protocol notes: stdout carries ONLY protocol frames (tool text goes inside
results); diagnostics go to stderr. Requests with unknown methods get
-32601; notifications (no id) never get a response, per JSON-RPC 2.0.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Optional, TextIO

from .factory import open_store
from .identity import resolve_project

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "danza-cortex", "version": "1.0.0"}

_PARSE_ERROR, _INVALID_REQUEST = -32700, -32600
_METHOD_NOT_FOUND, _INVALID_PARAMS = -32601, -32602

TOOLS = [
    {
        "name": "cortex_search",
        "description": "Full-text search over CORTEX observations "
                       "(project store + global L4/L5 bank). Returns id, "
                       "type, title, importance, confidence per hit.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "search terms"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "cortex_get",
        "description": "Fetch full observations by id (records usage so the "
                       "learning engine sees the access).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["ids"],
        },
    },
    {
        "name": "cortex_retrieve",
        "description": "Run the full retrieval brain for a prompt: intent "
                       "detection, hybrid ranking, anti-relevance, budgeted "
                       "assembly. Returns the context package an agent "
                       "would inject.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "budget": {"type": "integer", "default": 1500,
                           "description": "token budget for the package"},
                "intent": {"type": "string",
                           "description": "optional intent override"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "cortex_context",
        "description": "The SessionStart context block: semantic index of "
                       "all observations + top relevant bodies + token "
                       "economics line.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class CortexMcpServer:
    """One server instance per repo root. run() owns the stdio loop."""

    def __init__(self, root: str):
        self.root = root

    # -- tool implementations (return plain text for MCP content) -------------
    def _tool_search(self, args: dict) -> str:
        query = args.get("query", "")
        if not query.strip():
            raise ValueError("cortex_search: 'query' is required")
        limit = int(args.get("limit", 10))
        store = open_store(self.root)
        hits = store.backend.search(query, project=resolve_project(self.root),
                                    limit=limit)
        return json.dumps([{"id": o.id, "type": o.type, "title": o.title,
                            "importance": o.importance,
                            "confidence": o.confidence} for o in hits],
                          indent=2)

    def _tool_get(self, args: dict) -> str:
        ids = args.get("ids") or []
        if not isinstance(ids, list) or not ids:
            raise ValueError("cortex_get: 'ids' must be a non-empty array")
        store = open_store(self.root)
        out = []
        for oid in ids:
            o = store.get(oid)
            if o:
                store.record_use(oid, source="mcp")
                out.append(o.to_row())
        return json.dumps(out, indent=2)

    def _tool_retrieve(self, args: dict) -> str:
        from .commands import workspace_snapshot  # lazy: pulls kernel imports
        from .graph import GraphStore
        from .quality import build_package
        from .factory import db_path

        prompt = args.get("prompt", "")
        if not prompt.strip():
            raise ValueError("cortex_retrieve: 'prompt' is required")
        store = open_store(self.root)
        bundle = build_package(store, prompt, resolve_project(self.root),
                               budget=int(args.get("budget", 1500)),
                               types=None,
                               workspace=workspace_snapshot(self.root),
                               intent_override=args.get("intent"),
                               graph=GraphStore(db_path(self.root)))
        for item in bundle.package.items:
            store.record_use(item.observation.id, source="mcp")
        return bundle.package.render() or "(no relevant observations)"

    def _tool_context(self, args: dict) -> str:
        from .events import CaptureLog
        from .factory import db_path
        from .inject import build_context

        store = open_store(self.root)
        project = resolve_project(self.root)
        stats = CaptureLog(db_path(self.root)).stats(project)
        return build_context(store, project, stats=stats) or "(empty store)"

    _TOOL_HANDLERS = {"cortex_search": _tool_search, "cortex_get": _tool_get,
                      "cortex_retrieve": _tool_retrieve,
                      "cortex_context": _tool_context}

    # -- JSON-RPC dispatch ------------------------------------------------------
    def handle(self, message: dict) -> Optional[dict]:
        """Process one JSON-RPC message; None for notifications."""
        if not isinstance(message, dict):  # valid JSON but not a request object
            return _error(None, _INVALID_REQUEST, "message must be an object")
        msg_id = message.get("id")
        method = message.get("method", "")
        params = message.get("params") or {}
        if not isinstance(params, dict):  # positional params unsupported
            params = {}

        if msg_id is None:  # notification — never answered
            return None
        if not isinstance(method, str) or not method:
            return _error(msg_id, _INVALID_REQUEST, "missing method")

        if method == "initialize":
            client = params.get("protocolVersion", PROTOCOL_VERSION)
            if not isinstance(client, str):
                client = PROTOCOL_VERSION
            version = client if client <= PROTOCOL_VERSION else PROTOCOL_VERSION
            return _result(msg_id, {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            })
        if method == "ping":
            return _result(msg_id, {})
        if method == "tools/list":
            return _result(msg_id, {"tools": TOOLS})
        if method == "tools/call":
            return self._call_tool(msg_id, params)
        return _error(msg_id, _METHOD_NOT_FOUND, f"unknown method {method!r}")

    def _call_tool(self, msg_id: Any, params: dict) -> dict:
        name = params.get("name", "")
        handler = self._TOOL_HANDLERS.get(name)
        if handler is None:
            return _error(msg_id, _INVALID_PARAMS, f"unknown tool {name!r}")
        try:
            text = handler(self, params.get("arguments") or {})
            return _result(msg_id, {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            })
        except Exception as e:  # noqa: BLE001 — tool errors are data, not crashes
            return _result(msg_id, {
                "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
                "isError": True,
            })

    def run(self, stdin: Optional[TextIO] = None,
            stdout: Optional[TextIO] = None) -> int:
        """Newline-delimited JSON-RPC loop until EOF."""
        stdin = stdin if stdin is not None else sys.stdin
        stdout = stdout if stdout is not None else sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as e:
                _write(stdout, _error(None, _PARSE_ERROR, f"parse error: {e}"))
                continue
            try:
                response = self.handle(message)
            except Exception as e:  # noqa: BLE001 — one bad frame must not kill the loop
                response = _error(None, _INVALID_REQUEST,
                                  f"internal error: {type(e).__name__}: {e}")
            if response is not None:
                _write(stdout, response)
        return 0


def _result(msg_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": code, "message": message}}


def _write(stdout: TextIO, message: dict) -> None:
    stdout.write(json.dumps(message) + "\n")
    stdout.flush()
