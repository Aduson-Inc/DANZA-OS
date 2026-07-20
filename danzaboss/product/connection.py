"""UI-managed AI connection verification and project-local proof."""
from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
import subprocess
from pathlib import Path

from ..runtime.events import DanzaEvent, EventKind, ProjectEventLog
from ..workstation.runners import RunnerError, probe_auth


CONNECTION_RELPATH = Path(".danza") / "runtime" / "connection.json"


class ConnectionError(ValueError):
    """The selected client/model cannot be verified for this project."""


def _session_name(root: str | Path, runner: str) -> str:
    project = re.sub(r"[^A-Za-z0-9_-]", "_", Path(root).resolve().name)
    client = re.sub(r"[^A-Za-z0-9_-]", "_", runner)
    return f"danza-connect-{project}-{client}"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def connection_status(root: str | Path) -> dict:
    path = Path(root) / CONNECTION_RELPATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "unverified", "reason": "no verified connection"}
    if not isinstance(raw, dict) or raw.get("status") != "verified":
        return {"status": "unverified", "reason": "connection proof is invalid"}
    return raw


def launch_runner(root: str | Path, runner: str, config: dict, *,
                  run=subprocess.run, which=shutil.which) -> dict:
    """Start a selected interactive client in a project-scoped tmux session.

    Launching is deliberately separate from verification: the client may
    still be waiting for the user to sign in. The returned attach command is
    the honest handoff for that one-time authentication step; only
    ``verify_runner`` can create the verified project connection proof.
    """
    entries = config.get("runners", {}) if isinstance(config, dict) else {}
    entry = entries.get(runner)
    if not isinstance(entry, dict):
        raise ConnectionError(f"unknown runner: {runner}")
    if not entry.get("detected"):
        raise ConnectionError(f"{runner} is not installed on this machine")
    argv = entry.get("interactive")
    if not isinstance(argv, list) or not argv:
        raise ConnectionError(f"{runner} has no interactive client command")
    if which("tmux") is None:
        raise ConnectionError(
            "no supported interactive host is available; install tmux and "
            "try Connect again"
        )

    session = _session_name(root, runner)
    existing = run(["tmux", "has-session", "-t", f"={session}"],
                   capture_output=True, text=True)
    if existing.returncode != 0:
        started = run(["tmux", "new-session", "-d", "-s", session,
                       "-c", str(Path(root).resolve()), *argv],
                      capture_output=True, text=True)
        if started.returncode != 0:
            excerpt = (started.stderr or "")[-500:]
            raise ConnectionError(
                f"could not launch {runner} in tmux: {excerpt}")
        status = "launched"
    else:
        status = "already_running"
    return {
        "status": status,
        "runner": runner,
        "session": session,
        "host": "tmux",
        "attach_command": f"tmux attach -t {session}",
        "message": "Sign in in the client session, then return and verify.",
    }


def verify_runner(root: str | Path, runner: str, config: dict,
                  *, run=None) -> dict:
    entries = config.get("runners", {}) if isinstance(config, dict) else {}
    entry = entries.get(runner)
    if not isinstance(entry, dict):
        raise ConnectionError(f"unknown runner: {runner}")
    if not entry.get("detected"):
        raise ConnectionError(f"{runner} is not installed on this machine")
    auth = entry.get("auth")
    if auth != "ok":
        # A UI connection may supply a runner-specific adapter in a later
        # release. Until then, an unprobed client is not reported as working.
        raise ConnectionError(
            f"{runner} is present but not verified (auth={auth!r})")
    path = Path(root) / CONNECTION_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    proof = {
        "schema_version": 1,
        "status": "verified",
        "runner": runner,
        "client_surface": entry.get("kind", "cli"),
        "model": entry.get("model"),
        "contract_version": 1,
        "verified_at": _now(),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(proof, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    ProjectEventLog(root).append(DanzaEvent(
        kind=EventKind.CONNECTION, actor="user", session_id="connection",
        payload={"runner": runner, "status": "verified",
                 "client_surface": proof["client_surface"]},
    ))
    return proof
