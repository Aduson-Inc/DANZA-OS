"""Session host abstraction for boss process lifecycle (W1-P4 T2).

A SessionHost starts a new boss session (ignite), checks whether it is
running (alive), captures recent terminal output for stall detection and
dashboard display (tail), and stops it (kill).  Two concrete implementations
cover the two deployment scenarios:

  TmuxHost    — default POSIX host.  Gives the boss a persistent, detached
                tmux session that survives dashboard restarts and remains
                attachable with `tmux attach -t <name>`.  The conductor
                NEVER auto-kills a session; kill() exists for tests and the
                UI stop button so intentional termination is explicit, not
                accidental (automatic kills would destroy work in progress
                and make session recovery impossible without a save step).

  HeadlessHost — per-turn fallback for hosts where tmux is unavailable.
                 Trades away the attach-and-watch capability; output still
                 lands in a log file for tail() reads.

pick_host() selects a concrete type name: "tmux" degrades silently to
"headless" when the tmux binary is absent (degrade to invisible operation
rather than fail the whole dashboard startup).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

# The phrase that activates the DANZA OS inside the boss session.
IGNITION_MESSAGE = "Who's the Boss?"


class HostError(RuntimeError):
    """A host operation failed (bad exit code, missing binary, OS error)."""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class SessionHost(Protocol):
    """Interface every host implementation must satisfy."""

    def ignite(self, name: str, cwd: str | os.PathLike,
               argv: list[str]) -> None:
        """Start a fresh boss session and deliver IGNITION_MESSAGE to it."""
        ...

    def alive(self, name: str) -> bool:
        """Return True if the named session is currently running."""
        ...

    def tail(self, name: str, lines: int = 40) -> str:
        """Return the most recent `lines` lines of session output.

        Returns "" when the session is unreachable or the log is absent;
        callers use this for stall detection and UI display, so silence is
        preferable to an exception here.
        """
        ...

    def kill(self, name: str) -> None:
        """Best-effort terminate the named session.

        The conductor NEVER calls this automatically; it exists for tests and
        the dashboard stop button.  Killing a live boss mid-turn would corrupt
        the handoff state, so termination must always be an explicit user act.
        """
        ...


# ---------------------------------------------------------------------------
# TmuxHost
# ---------------------------------------------------------------------------

class TmuxHost:
    """Default POSIX session host backed by tmux.

    The injectable `run` seam (default: subprocess.run) lets tests assert on
    exact command shapes without spawning real processes.
    """

    def __init__(self, run: Callable = subprocess.run) -> None:
        self._run = run

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ignite(self, name: str, cwd: str | os.PathLike,
               argv: list[str]) -> None:
        """Create a detached tmux session then send the ignition phrase.

        Raises HostError if either command exits nonzero or the OS cannot
        exec tmux (e.g. binary not on PATH).
        """
        try:
            result = self._run(
                ["tmux", "new-session", "-d", "-s", name, "-c", str(cwd)]
                + argv,
                capture_output=True, text=True,
            )
        except OSError as exc:
            raise HostError(f"tmux new-session failed: {exc}") from exc

        if result.returncode != 0:
            excerpt = (result.stderr or "")[-500:]
            raise HostError(
                f"tmux new-session exited {result.returncode}: {excerpt}")

        try:
            sk = self._run(
                ["tmux", "send-keys", "-t", name, IGNITION_MESSAGE, "Enter"],
                capture_output=True, text=True,
            )
        except OSError as exc:
            raise HostError(f"tmux send-keys failed: {exc}") from exc

        if sk.returncode != 0:
            excerpt = (sk.stderr or "")[-500:]
            raise HostError(
                f"tmux send-keys exited {sk.returncode}: {excerpt}")

    def alive(self, name: str) -> bool:
        """True iff tmux has-session exits 0 for `name`."""
        result = self._run(
            ["tmux", "has-session", "-t", name],
            capture_output=True, text=True,
        )
        return result.returncode == 0

    def tail(self, name: str, lines: int = 40) -> str:
        """Capture recent pane output via tmux capture-pane.

        Returns "" on any failure; the caller uses this for display, not
        control flow, so silence beats an exception.
        """
        result = self._run(
            ["tmux", "capture-pane", "-p", "-t", name],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return ""
        all_lines = result.stdout.splitlines()
        return "\n".join(all_lines[-lines:])

    def kill(self, name: str) -> None:
        """Kill the named tmux session (best-effort; errors are not surfaced)."""
        self._run(
            ["tmux", "kill-session", "-t", name],
            capture_output=True, text=True,
        )

    def attach_hint(self, name: str) -> str:
        """Human-readable command to reattach to this session."""
        return f"tmux attach -t {name}"


# ---------------------------------------------------------------------------
# HeadlessHost
# ---------------------------------------------------------------------------

class HeadlessHost:
    """Per-turn fallback host for environments without tmux.

    The boss process runs as a plain subprocess; stdout and stderr are
    redirected to `log_dir/<name>.log` for later tail() reads.  There is no
    way to attach to a running session — that capability requires tmux.

    The injectable `popen` seam (default: subprocess.Popen) mirrors the
    TmuxHost pattern so tests can assert on exact call shapes.
    """

    def __init__(self, log_dir: str | os.PathLike,
                 popen: Callable = subprocess.Popen) -> None:
        self._log_dir = Path(log_dir)
        self._popen = popen
        self._handles: dict[str, object] = {}
        # Log file handles are stored alongside process handles so they are
        # explicitly closed on kill() rather than relying on GC — avoids
        # ResourceWarning when the subprocess seam is a stub that never reads
        # or closes the file object it receives.
        self._log_fhs: dict[str, object] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ignite(self, name: str, cwd: str | os.PathLike,
               argv: list[str]) -> None:
        """Spawn the boss subprocess and pipe its output to <name>.log.

        Raises HostError on OSError from the subprocess seam (e.g. missing
        executable, bad path).
        """
        self._log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._log_dir / f"{name}.log"

        try:
            # Open in append mode so a re-ignited session extends the log
            # rather than truncating evidence of the previous run.
            log_fh = open(log_path, "a", encoding="utf-8")
            handle = self._popen(
                argv + [IGNITION_MESSAGE],
                cwd=str(cwd),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
            )
        except OSError as exc:
            try:
                log_fh.close()
            except Exception:
                pass
            raise HostError(f"headless ignite failed for {name!r}: {exc}") from exc

        # Close any previous log handle for this name before replacing it.
        old_fh = self._log_fhs.get(name)
        if old_fh is not None:
            try:
                old_fh.close()
            except Exception:
                pass

        self._handles[name] = handle
        self._log_fhs[name] = log_fh

    def alive(self, name: str) -> bool:
        """True iff a handle exists for `name` and the process has not exited."""
        handle = self._handles.get(name)
        if handle is None:
            return False
        return handle.poll() is None

    def tail(self, name: str, lines: int = 40) -> str:
        """Read the last `lines` lines from the session log file.

        Returns "" if the log does not exist (e.g. before ignite or after the
        log_dir was cleaned up).
        """
        log_path = self._log_dir / f"{name}.log"
        if not log_path.exists():
            return ""
        all_lines = log_path.read_text(encoding="utf-8").splitlines()
        return "\n".join(all_lines[-lines:])

    def kill(self, name: str) -> None:
        """Terminate the process for `name`, swallowing all errors.

        The conductor never auto-kills (same reasoning as TmuxHost); this is
        only for tests and the UI stop button.
        """
        handle = self._handles.get(name)
        if handle is None:
            return
        try:
            handle.terminate()
        except Exception:
            pass
        # Close the associated log file handle so the OS flushes it and tests
        # do not emit ResourceWarning for unclosed files.
        self._close_log(name)

    def _close_log(self, name: str) -> None:
        """Close and remove the log file handle for `name` (best-effort)."""
        fh = self._log_fhs.pop(name, None)
        if fh is not None:
            try:
                fh.close()
            except Exception:
                pass

    def __del__(self) -> None:
        """Close all open log file handles on GC so tests emit no ResourceWarning.

        Python closes file objects during GC anyway, but emits ResourceWarning
        when it does so.  Explicit close here silences that — the same pattern
        used throughout the OS for tempfile / subprocess cleanup.
        """
        for name in list(self._log_fhs):
            self._close_log(name)


# ---------------------------------------------------------------------------
# Host selector
# ---------------------------------------------------------------------------

def pick_host(preference: str, *, which: Callable = shutil.which) -> str:
    """Resolve a host type name, degrading silently when hardware is absent.

    "tmux"     → "tmux" if the binary is on PATH; "headless" otherwise.
                 Silent fallback by design: degrade to invisible operation
                 rather than abort the dashboard startup because tmux is
                 missing.
    "headless" → "headless" unconditionally.
    anything else → HostError (unsupported preference).
    """
    if preference == "headless":
        return "headless"
    if preference == "tmux":
        return "tmux" if which("tmux") is not None else "headless"
    raise HostError(
        f"unsupported host preference {preference!r}; "
        f"choose 'tmux' or 'headless'")
