"""Verification runner — the real 'Bonnie' gate.

Runs the TARGET app's own test/build command in a subprocess, scoped to the target
directory, and returns a structured pass/fail. This is what makes "verify before
done" and the regression gate mean something on a real app. Stdlib subprocess only.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field


@dataclass
class VerifyResult:
    passed: bool
    command: str
    exit_code: int
    stdout_tail: str = ""
    stderr_tail: str = ""
    timed_out: bool = False


def run_verification(command: str, cwd: str, *, timeout: int = 600) -> VerifyResult:
    """Run a test/build command in the target repo, returning a structured result.

    TRUST BOUNDARY: `command` runs through the shell (compound commands like
    "pytest && ruff check" are supported), so it MUST be a trusted, configured
    test command for the target app — never free-text from an untrusted actor.

    Fails closed: any launch/timeout error becomes passed=False, never an uncaught
    exception, so a bad target dir or timeout cannot brick the calling gate."""
    try:
        proc = subprocess.run(command, cwd=cwd, shell=True, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return VerifyResult(passed=False, command=command, exit_code=-1,
                           stdout_tail=_tail(e.stdout or ""), timed_out=True)
    except OSError as e:
        # e.g. cwd does not exist / not a directory -> fail closed, don't raise.
        return VerifyResult(passed=False, command=command, exit_code=-1,
                           stderr_tail=_tail(str(e)))
    return VerifyResult(
        passed=(proc.returncode == 0), command=command, exit_code=proc.returncode,
        stdout_tail=_tail(proc.stdout), stderr_tail=_tail(proc.stderr))


def _tail(text: str, n: int = 2000) -> str:
    return text[-n:] if text else ""
