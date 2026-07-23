"""UI-managed AI connection verification and project-local proof."""
from __future__ import annotations

import datetime as _dt
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from ..runtime.events import DanzaEvent, EventKind, ProjectEventLog
from ..workstation.runners import RunnerError, probe_auth
from ..workstation.workspace import (load_workspace, save_workspace,
                                      session_name, workspace_summary)


CONNECTION_RELPATH = Path(".danza") / "runtime" / "connection.json"


class ConnectionError(ValueError):
    """The selected client/model cannot be verified for this project."""


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
        workspace = load_workspace(root)
        if workspace is not None and workspace["host"] != "native_terminal":
            raise ConnectionError(
                "the project workspace was created with tmux, but tmux is no "
                "longer available; restore tmux before connecting another client"
            )
        terminal = _open_terminal(argv, cwd=str(Path(root).resolve()),
                                  which=which, popen=popen)
        if not terminal["opened"]:
            raise ConnectionError(
                "DANZABOSS could not open a terminal for this client; install "
                "a terminal emulator or tmux and try Connect again"
            )
        order = list(workspace["order"]) if workspace else []
        panes = dict(workspace["panes"]) if workspace else {}
        if runner not in order:
            order.append(runner)
        panes[runner] = f"terminal:{runner}"
        save_workspace(root, {
            "schema_version": 1,
            "session": session_name(root),
            "host": "native_terminal",
            "order": order,
            "panes": panes,
            "active_runner": workspace["active_runner"] if workspace else None,
            "terminal_opened": True,
        })
        return {
            "status": "launched",
            "runner": runner,
            "session": None,
            "pane": f"terminal:{runner}",
            "host": "native_terminal",
            "terminal": terminal,
            "attach_command": None,
            "message": "The client is open. Sign in there, then return here and verify.",
        }

    session = session_name(root)
    workspace = load_workspace(root)
    existing = run(["tmux", "has-session", "-t", f"={session}"],
                   capture_output=True, text=True)
    if workspace is None and existing.returncode == 0:
        raise ConnectionError(
            "the project tmux session exists without DANZABOSS workspace "
            "state; close that session manually, then Connect again")
    if workspace is not None and workspace["host"] != "tmux":
        raise ConnectionError(
            "the project workspace is not a tmux workspace; recreate it before "
            "connecting a tmux client")
    if workspace is not None and runner in workspace["order"]:
        status = "already_running"
        pane_id = workspace["panes"][runner]
        terminal = {"opened": False, "launcher": None}
    else:
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
        pane_id = (getattr(started, "stdout", "") or "").strip().splitlines()
        pane_id = pane_id[0] if pane_id else ""
    if workspace is None or runner not in workspace["order"]:
        alive = run(["tmux", "has-session", "-t", f"={session}"],
                    capture_output=True, text=True)
        if alive.returncode != 0:
            raise ConnectionError(
                f"{runner} closed before it could connect; open the client "
                "again and complete its sign-in steps")
        order = list(workspace["order"]) if workspace else []
        panes = dict(workspace["panes"]) if workspace else {}
        order.append(runner)
        panes[runner] = pane_id
        terminal_opened = bool(workspace and workspace["terminal_opened"])
        if terminal_opened:
            terminal = {"opened": False, "launcher": None}
        else:
            terminal = _open_terminal(["tmux", "attach", "-t", session],
                                      cwd=str(Path(root).resolve()), which=which,
                                      popen=popen)
            terminal_opened = terminal["opened"]
        save_workspace(root, {
            "schema_version": 1,
            "session": session,
            "host": "tmux",
            "order": order,
            "panes": panes,
            "active_runner": workspace["active_runner"] if workspace else None,
            "terminal_opened": terminal_opened,
        })
    terminal["fallback_command"] = f"tmux attach -t {session}"
    return {
        "status": status,
        "runner": runner,
        "session": session,
        "pane": pane_id or None,
        "host": "tmux",
        "terminal": terminal,
        "attach_command": terminal["fallback_command"],
        "message": "The client is open. Sign in there, then return here and verify.",
    }


def prepare_workspace(root: str | Path, lineup: list[str], config: dict, *,
                      run=subprocess.run, which=shutil.which,
                      popen=subprocess.Popen) -> dict:
    """Ensure the selected lineup owns one ordered project workspace."""
    if (not isinstance(lineup, list) or not lineup or len(lineup) > 4
            or len(lineup) != len(set(lineup))):
        raise ConnectionError("workspace lineup must contain 1-4 unique clients")
    entries = config.get("runners", {}) if isinstance(config, dict) else {}
    for runner in lineup:
        entry = entries.get(runner)
        if not isinstance(entry, dict) or not entry.get("detected"):
            raise ConnectionError(f"{runner} is not installed on this machine")
        if entry.get("auth") != "ok":
            raise ConnectionError(f"{runner} is not verified")
    for runner in lineup:
        launch_runner(root, runner, config, run=run, which=which, popen=popen)
    workspace = load_workspace(root)
    if workspace is None:
        raise ConnectionError("workspace state was not created")
    current = list(workspace["order"])
    panes = dict(workspace["panes"])
    if workspace["host"] == "tmux":
        for index, runner in enumerate(lineup):
            if current[index] == runner:
                continue
            source_runner = current[index]
            target_index = current.index(runner)
            swapped = run(["tmux", "swap-pane", "-s", panes[source_runner],
                           "-t", panes[runner]], capture_output=True, text=True)
            if swapped.returncode != 0:
                excerpt = (swapped.stderr or "")[-500:]
                raise ConnectionError(
                    f"could not order workspace panes: {excerpt}")
            current[index], current[target_index] = (
                current[target_index], current[index])
    extras = [runner for runner in current if runner not in lineup]
    if extras:
        raise ConnectionError(
            "workspace contains clients outside the saved lineup; close the "
            "old workspace before saving a smaller team")
    save_workspace(root, {
        **workspace,
        "order": list(lineup),
        "active_runner": lineup[0],
    })
    return workspace_summary(root)


def open_workspace(root: str | Path, *, which=shutil.which,
                   popen=subprocess.Popen, run=subprocess.run) -> dict:
    """Open one terminal attached to the existing project workspace."""
    workspace = load_workspace(root)
    if workspace is None:
        raise ConnectionError("connect at least one client before opening the workspace")
    terminal = {"opened": False, "launcher": None}
    if workspace["host"] == "tmux":
        alive = run(["tmux", "has-session", "-t", f"={workspace['session']}"],
                    capture_output=True, text=True)
        if alive.returncode != 0:
            raise ConnectionError(
                f"workspace session {workspace['session']!r} is not running")
        terminal = _open_terminal(
            ["tmux", "attach", "-t", workspace["session"]],
            cwd=str(Path(root).resolve()), which=which, popen=popen)
        terminal["fallback_command"] = workspace_summary(root)["attach_command"]
        if terminal["opened"] and not workspace["terminal_opened"]:
            save_workspace(root, {**workspace, "terminal_opened": True})
    return {"workspace": workspace_summary(root), "terminal": terminal}


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
