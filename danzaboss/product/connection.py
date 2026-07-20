"""UI-managed AI connection verification and project-local proof."""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from ..runtime.events import DanzaEvent, EventKind, ProjectEventLog
from ..workstation.runners import RunnerError, probe_auth


CONNECTION_RELPATH = Path(".danza") / "runtime" / "connection.json"


class ConnectionError(ValueError):
    """The selected client/model cannot be verified for this project."""


def _session_name(root: str | Path) -> str:
    project = re.sub(r"[^A-Za-z0-9_-]", "_", Path(root).resolve().name)
    return f"danza-project-{project}"


def _terminal_argv(command: list[str], *, which=shutil.which) -> tuple[str, list[str]] | None:
    """Return a platform terminal command for *command*.

    The dashboard owns the session. A terminal is only a display surface, so
    this is best-effort and the attach command remains a technical fallback
    in the API response. Provider login still happens in the native client.
    """
    if os.name == "nt" and which("wt.exe"):
        return "Windows Terminal", ["wt.exe", "new-tab", "--", *command]
    if sys.platform == "darwin" and which("open"):
        return "Terminal", ["open", "-a", "Terminal", "--args", *command]
    for name, argv in (
        ("x-terminal-emulator", ["x-terminal-emulator", "-e", *command]),
        ("gnome-terminal", ["gnome-terminal", "--", *command]),
        ("konsole", ["konsole", "-e", *command]),
        ("xfce4-terminal", ["xfce4-terminal", "--command",
                             " ".join(shlex.quote(part) for part in command)]),
        ("kitty", ["kitty", *command]),
        ("alacritty", ["alacritty", "-e", *command]),
        ("wezterm", ["wezterm", "start", "--", *command]),
    ):
        if which(name):
            return name, argv
    return None


def _open_terminal(command: list[str], *, cwd: str | None = None,
                   which=shutil.which,
                   popen=subprocess.Popen) -> dict:
    selected = _terminal_argv(command, which=which)
    if selected is None:
        return {"opened": False, "launcher": None}
    launcher, argv = selected
    try:
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                  "start_new_session": True}
        if cwd is not None:
            kwargs["cwd"] = cwd
        popen(argv, **kwargs)
    except OSError:
        return {"opened": False, "launcher": launcher}
    return {"opened": True, "launcher": launcher}


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
                  run=subprocess.run, which=shutil.which,
                  popen=subprocess.Popen) -> dict:
    """Start a selected interactive client in one project-scoped tmux session.

    Launching is deliberately separate from verification: the client may
    still be waiting for the user to sign in. Each connected client gets a
    pane in the same project session. The dashboard opens that session in a
    terminal when the platform provides one; only ``verify_runner`` can
    create the verified project connection proof.
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
        terminal = _open_terminal(argv, cwd=str(Path(root).resolve()),
                                  which=which, popen=popen)
        if not terminal["opened"]:
            raise ConnectionError(
                "DANZABOSS could not open a terminal for this client; install "
                "a terminal emulator or tmux and try Connect again"
            )
        return {
            "status": "launched",
            "runner": runner,
            "session": None,
            "pane": None,
            "host": "native_terminal",
            "terminal": terminal,
            "attach_command": None,
            "message": "The client is open. Sign in there, then return here and verify.",
        }

    session = _session_name(root)
    existing = run(["tmux", "has-session", "-t", f"={session}"],
                   capture_output=True, text=True)
    if existing.returncode != 0:
        started = run(["tmux", "new-session", "-d", "-P",
                       "-F", "#{pane_id}", "-s", session,
                       "-c", str(Path(root).resolve()), *argv],
                      capture_output=True, text=True)
        status = "launched"
    else:
        started = run(["tmux", "split-window", "-d", "-P",
                       "-F", "#{pane_id}", "-t", f"={session}",
                       "-c", str(Path(root).resolve()), *argv],
                      capture_output=True, text=True)
        status = "already_running"
    if started.returncode != 0:
        excerpt = (started.stderr or "")[-500:]
        raise ConnectionError(
            f"could not launch {runner} in the project session: {excerpt}")

    alive = run(["tmux", "has-session", "-t", f"={session}"],
                capture_output=True, text=True)
    if alive.returncode != 0:
        raise ConnectionError(
            f"{runner} closed before it could connect; open the client again "
            "and complete its sign-in steps")

    pane = (getattr(started, "stdout", "") or "").strip().splitlines()
    terminal = _open_terminal(["tmux", "attach", "-t", session],
                              cwd=str(Path(root).resolve()), which=which,
                              popen=popen)
    terminal["fallback_command"] = f"tmux attach -t {session}"
    return {
        "status": status,
        "runner": runner,
        "session": session,
        "pane": pane[0] if pane else None,
        "host": "tmux",
        "terminal": terminal,
        "attach_command": terminal["fallback_command"],
        "message": "The client is open. Sign in there, then return here and verify.",
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
