"""Thin client adapters for the vendor-neutral DANZA event contract."""
from __future__ import annotations

import json
from pathlib import Path

from ..runtime.events import DanzaEvent, EventKind, ProjectEventLog


_TOOL_KINDS = {
    "read": EventKind.READ,
    "write": EventKind.EDIT,
    "edit": EventKind.EDIT,
    "command": EventKind.COMMAND,
    "bash": EventKind.COMMAND,
    "shell": EventKind.COMMAND,
    "git": EventKind.GIT,
    "decision": EventKind.DECISION,
    "error": EventKind.ERROR,
    "test": EventKind.TEST,
    "verification": EventKind.VERIFICATION,
    "verify": EventKind.VERIFICATION,
    "spawn": EventKind.SPAWN,
    "handoff": EventKind.HANDOFF,
    "memory": EventKind.MEMORY,
    "connection": EventKind.CONNECTION,
    "session": EventKind.LIFECYCLE,
    "lifecycle": EventKind.LIFECYCLE,
}

_NATIVE_KIND = {
    "beforetool": EventKind.COMMAND,
    "aftertool": EventKind.COMMAND,
    "pre_tool_call": EventKind.COMMAND,
    "post_tool_call": EventKind.COMMAND,
    "tool_use": EventKind.COMMAND,
    "tool.execute.before": EventKind.COMMAND,
    "tool.execute.after": EventKind.COMMAND,
    "thread.started": EventKind.LIFECYCLE,
    "thread.completed": EventKind.LIFECYCLE,
    "turn.started": EventKind.LIFECYCLE,
    "turn.completed": EventKind.LIFECYCLE,
    "subagent_start": EventKind.SPAWN,
    "subagent_stop": EventKind.SPAWN,
}

ADAPTERS = {
    "claude": "claude-code",
    "gemini": "gemini-cli",
    "grok": "xai-tools",
    "hermes": "hermes-agent",
    "codex": "codex-app-server",
    "opencode": "opencode-cli",
}


def _kind(raw: dict) -> EventKind:
    tool = str(raw.get("tool_name", raw.get("tool", ""))).lower()
    if tool in {"read", "glob", "grep"}:
        return EventKind.READ
    if tool in {"write", "edit", "apply_patch"}:
        return EventKind.EDIT
    if tool in {"bash", "shell", "exec", "terminal"}:
        return EventKind.COMMAND
    for key in ("kind", "event", "type", "hook_event"):
        value = raw.get(key)
        if not isinstance(value, str):
            continue
        normalized = value.strip().lower().replace(" ", "")
        if normalized in _TOOL_KINDS:
            return _TOOL_KINDS[normalized]
        if normalized in _NATIVE_KIND:
            return _NATIVE_KIND[normalized]
    return EventKind.LIFECYCLE


class ClientAdapter:
    def __init__(self, client: str):
        if client not in ADAPTERS:
            raise ValueError(f"unsupported client adapter: {client}")
        self.client = client

    def normalize(self, raw: dict, *, actor: str, session_id: str = "",
                  task_id: str = "") -> DanzaEvent:
        if not isinstance(raw, dict):
            raise TypeError("native client event must be an object")
        payload = dict(raw)
        payload["client_adapter"] = ADAPTERS[self.client]
        payload.setdefault("path", raw.get("file_path", raw.get("path", "")))
        payload.setdefault("command", raw.get("command", ""))
        return DanzaEvent(kind=_kind(raw), actor=actor, session_id=session_id,
                          task_id=task_id, payload=payload)


class AdapterRegistry:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def normalize(self, client: str, raw: dict, *, actor: str,
                  session_id: str = "", task_id: str = "") -> DanzaEvent:
        return ClientAdapter(client).normalize(
            raw, actor=actor, session_id=session_id, task_id=task_id)

    def emit(self, client: str, raw: dict, *, actor: str,
             session_id: str = "", task_id: str = "") -> DanzaEvent:
        return ProjectEventLog(self.root).append(self.normalize(
            client, raw, actor=actor, session_id=session_id, task_id=task_id))
