"""Project activation: scaffold, initialize CORTEX, and verify the UI path."""
from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..cortex.events import CaptureLog
from ..cortex.factory import db_path, open_project_store
from ..cortex.identity import resolve_project
from ..kernel.state import StateManager
from ..product.scaffold import scaffold
from ..runtime.events import DanzaEvent, EventKind, ProjectEventLog


INSTALLATION_RELPATH = Path(".danza") / "runtime" / "installation.json"
UI_PID_RELPATH = Path(".danza") / "runtime" / "ui.pid"
UI_LOG_RELPATH = Path(".danza") / "runtime" / "ui.log"
UI_PORT = 33000


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


def start_ui(root: str | Path, *, open_browser: bool = True,
             popen=subprocess.Popen) -> int:
    root = Path(root).resolve()
    pid_path = root / UI_PID_RELPATH
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
            if _pid_alive(pid):
                return pid
        except (OSError, ValueError):
            pass
    log_path = root / UI_LOG_RELPATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("a", encoding="utf-8")
    argv = [sys.executable, "-m", "danzaboss.cli", "ui", str(root),
            "--port", str(UI_PORT)]
    if not open_browser:
        argv.append("--no-open")
    kwargs = {"cwd": str(root), "stdout": log, "stderr": subprocess.STDOUT}
    if os.name != "nt":
        kwargs["start_new_session"] = True
    proc = popen(argv, **kwargs)
    pid = int(proc.pid)
    pid_path.write_text(f"{pid}\n", encoding="utf-8")
    # The child owns the descriptor after spawn; closing the parent handle
    # avoids leaking it in long-running installer processes.
    log.close()
    return pid


def wait_for_ui(port: int = UI_PORT, *, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/overview", timeout=0.5) as response:
                return response.status == 200
        except (OSError, urllib.error.URLError):
            time.sleep(0.05)
    return False


def activate_project(root: str | Path, *, start_ui_process: bool = False,
                     open_browser: bool = True) -> dict:
    """Make the project runtime active before any onboarding can begin."""
    root = Path(root).resolve()
    if not (root / ".git").exists():
        raise ValueError("activation requires a Git repository")
    scaffold(root)
    state_path = root / ".danza" / "runtime" / "team-state.json"
    if not state_path.exists():
        StateManager(str(state_path)).init(current_boss="pending")
    # Opening the project store creates the authoritative DB and schema now,
    # not lazily at first AI session.
    open_project_store(str(root))
    session_id = f"install-{int(time.time())}"
    CaptureLog(db_path(str(root))).open_session(
        session_id, resolve_project(str(root)), environment="danza-runtime")
    ProjectEventLog(root).append(DanzaEvent(
        kind=EventKind.LIFECYCLE, actor="installer", session_id=session_id,
        payload={"event": "project_initialized", "cortex": "project-local"},
    ))
    installation = {
        "schema_version": 1,
        "status": "active",
        "project": resolve_project(str(root)),
        "cortex": "project-local",
        "ui_port": UI_PORT,
        "ai_connection": "pending",
        "activated_at": _now(),
    }
    _write_json(root / INSTALLATION_RELPATH, installation)
    if start_ui_process:
        pid = start_ui(root, open_browser=open_browser)
        installation["ui_pid"] = pid
        installation["ui"] = "started"
        _write_json(root / INSTALLATION_RELPATH, installation)
    return {"cortex": True, "project": installation["project"],
            "ui": installation.get("ui", "not-started"),
            "installation": installation}


def verify_installation(root: str | Path, *, require_connection: bool = False) -> dict:
    root = Path(root).resolve()
    required = [
        root / ".git", root / ".danza" / ".scaffold-version",
        root / ".danza" / "runtime" / "team-state.json",
        root / ".danza" / "cortex" / "cortex.db",
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    ui_ok = wait_for_ui() if (root / UI_PID_RELPATH).exists() else False
    try:
        connection = json.loads((root / ".danza" / "runtime" /
                                 "connection.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        connection = {"status": "unverified"}
    connection_ok = connection.get("status") == "verified"
    core_ok = not missing
    # `require_connection` is retained for callers that want to name the
    # gate explicitly. A successful installation always requires the complete
    # path: project files, project CORTEX, a live UI, and verified AI access.
    del require_connection
    ok = core_ok and ui_ok and connection_ok
    status = "verified" if ok else ("awaiting_ai_connection"
                                    if core_ok else "failed")
    installation_path = root / INSTALLATION_RELPATH
    if installation_path.exists():
        try:
            installation = json.loads(installation_path.read_text(
                encoding="utf-8"))
            if isinstance(installation, dict):
                installation["status"] = status
                installation["ui"] = "verified" if ui_ok else "unverified"
                installation["ai_connection"] = (
                    "verified" if connection_ok else "pending")
                _write_json(installation_path, installation)
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "status": status,
        "project_initialized": not missing,
        "cortex": (root / ".danza" / "cortex" / "cortex.db").is_file(),
        "ui": ui_ok,
        "ai_connection": connection_ok,
        "missing": missing,
    }
