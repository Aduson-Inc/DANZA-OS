"""One redacted, model-neutral event contract for all connected clients."""
from __future__ import annotations

import datetime as _dt
import json
import secrets
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..cortex.events import CaptureLog, redact
from ..cortex.factory import db_path
from ..cortex.identity import resolve_project


class EventKind(str, Enum):
    READ = "read"
    EDIT = "edit"
    COMMAND = "command"
    GIT = "git"
    DECISION = "decision"
    ERROR = "error"
    TEST = "test"
    VERIFICATION = "verification"
    LIFECYCLE = "lifecycle"
    SPAWN = "spawn"
    HANDOFF = "handoff"
    MEMORY = "memory"
    CONNECTION = "connection"


@dataclass(frozen=True)
class DanzaEvent:
    kind: EventKind
    actor: str
    session_id: str = ""
    task_id: str = ""
    payload: dict = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: "evt_" + secrets.token_hex(10))
    ts: str = field(default_factory=lambda: _dt.datetime.now(
        _dt.timezone.utc).isoformat(timespec="seconds"))


class ProjectEventLog:
    """Append-only project event ledger plus CORTEX raw capture."""

    RELPATH = Path(".danza") / "runtime" / "events.jsonl"

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.path = self.root / self.RELPATH

    def append(self, event: DanzaEvent) -> DanzaEvent:
        def redact_value(value):
            if isinstance(value, str):
                return redact(value)
            if isinstance(value, dict):
                return {str(key): redact_value(item)
                        for key, item in value.items()}
            if isinstance(value, list):
                return [redact_value(item) for item in value]
            if isinstance(value, tuple):
                return [redact_value(item) for item in value]
            if value is None or isinstance(value, (bool, int, float)):
                return value
            return redact(str(value))

        safe_payload = redact_value(event.payload)
        safe = DanzaEvent(kind=event.kind, actor=event.actor,
                          session_id=event.session_id, task_id=event.task_id,
                          payload=safe_payload, event_id=event.event_id,
                          ts=event.ts)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event_id": safe.event_id, "ts": safe.ts,
                                 "kind": safe.kind.value, "actor": safe.actor,
                                 "session_id": safe.session_id,
                                 "task_id": safe.task_id,
                                 "payload": safe.payload}, sort_keys=True) + "\n")
        session_id = safe.session_id or "danza-runtime"
        capture = CaptureLog(db_path(str(self.root)))
        capture.open_session(session_id, resolve_project(str(self.root)),
                             environment="danza-runtime")
        payload = safe.payload
        capture.record_event(
            session_id, safe.kind.value,
            file_path=str(payload.get("path", "")),
            command=str(payload.get("command", "")),
            outcome=str(payload.get("outcome", "")),
            excerpt=json.dumps(payload, sort_keys=True),
        )
        return safe
