"""Project-local workspace state shared by connection and turn routing."""
from __future__ import annotations

import json
import re
from pathlib import Path


WORKSPACE_RELPATH = Path(".danza") / "runtime" / "workspace.json"
SCHEMA_VERSION = 1
VALID_HOSTS = frozenset({"tmux", "native_terminal", "headless", "unconfigured"})


def session_name(root: str | Path) -> str:
    """Return the one stable tmux session name owned by a project."""
    return "danza-" + re.sub(r"[^A-Za-z0-9_-]", "_",
                             Path(root).resolve().name)


def _path(root: str | Path) -> Path:
    return Path(root) / WORKSPACE_RELPATH


def _validate(root: str | Path, data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("workspace state must be a JSON object")
    required = ("schema_version", "session", "host", "order", "panes",
                "active_runner", "terminal_opened")
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError("workspace state is missing: " + ", ".join(missing))
    if data["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported workspace schema version")
    if data["session"] != session_name(root):
        raise ValueError("workspace session does not belong to this project")
    if data["host"] not in VALID_HOSTS - {"unconfigured"}:
        raise ValueError("workspace host is invalid")
    order = data["order"]
    panes = data["panes"]
    if (not isinstance(order, list)
            or not all(isinstance(item, str) and item for item in order)
            or len(order) != len(set(order))
            or len(order) > 4):
        raise ValueError("workspace order must contain at most four unique runners")
    if not isinstance(panes, dict):
        raise ValueError("workspace panes must be an object")
    if set(panes) != set(order):
        raise ValueError("workspace panes must match workspace order")
    if not all(isinstance(pane, str) and pane for pane in panes.values()):
        raise ValueError("workspace pane IDs must be non-empty strings")
    active = data["active_runner"]
    if active is not None and active not in order:
        raise ValueError("workspace active runner must be in the order")
    if not isinstance(data["terminal_opened"], bool):
        raise ValueError("workspace terminal_opened must be boolean")
    return data


def load_workspace(root: str | Path) -> dict | None:
    path = _path(root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read workspace state: {exc}") from exc
    return _validate(root, data)


def save_workspace(root: str | Path, data: dict) -> None:
    path = _path(root)
    _validate(root, data)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def workspace_summary(root: str | Path) -> dict:
    data = load_workspace(root)
    if data is None:
        return {
            "session": session_name(root),
            "host": "unconfigured",
            "order": [],
            "panes": {},
            "active_runner": None,
            "terminal_opened": False,
            "attach_command": None,
        }
    summary = dict(data)
    summary["attach_command"] = (
        f"tmux attach -t {data['session']}"
        if data["host"] == "tmux" else None)
    return summary
