"""Vendor adapters normalize native client events into one DANZA contract."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from danzaboss.adapters import ADAPTERS, AdapterRegistry
from danzaboss.runtime.events import EventKind


class AdapterContract(unittest.TestCase):
    def test_supported_clients_are_adapters_not_agent_definitions(self):
        self.assertEqual(set(ADAPTERS), {
            "claude", "gemini", "grok", "hermes", "codex", "opencode"
        })

    def test_native_events_share_one_redacted_event_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = AdapterRegistry(Path(tmp))
            raw = registry.normalize(
                "gemini", {"event": "BeforeTool", "tool_name": "Read",
                           "path": "src/app.py",
                           "command": "echo api_key=secret-value"},
                actor="jonathan-builder", session_id="s1", task_id="T1")
            self.assertEqual(raw.kind, EventKind.READ)
            self.assertEqual(raw.actor, "jonathan-builder")
            saved = registry.emit(
                "gemini", {"event": "BeforeTool", "tool_name": "Read",
                           "path": "src/app.py",
                           "command": "echo api_key=secret-value"},
                actor="jonathan-builder", session_id="s1", task_id="T1")
            self.assertEqual(saved.kind, EventKind.READ)
            text = (Path(tmp) / ".danza" / "runtime" /
                    "events.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("secret-value", text)
            self.assertEqual(json.loads(text)["kind"], "read")

    def test_unknown_native_event_is_lifecycle_not_dropped(self):
        event = AdapterRegistry("/tmp").normalize(
            "codex", {"event": "thread.started"}, actor="codex")
        self.assertEqual(event.kind, EventKind.LIFECYCLE)


if __name__ == "__main__":
    unittest.main()
