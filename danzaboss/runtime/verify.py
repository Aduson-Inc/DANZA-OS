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
    """Run a test/build command in the target repo. No shell-injection surprises:
    the command is the app's own configured test command, run in its own dir."""
    try:
        proc = subprocess.run(command, cwd=cwd, shell=True, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return VerifyResult(passed=False, command=command, exit_code=-1,
                           stdout_tail=_tail(e.stdout or ""), timed_out=True)
    return VerifyResult(
        passed=(proc.returncode == 0), command=command, exit_code=proc.returncode,
        stdout_tail=_tail(proc.stdout), stderr_tail=_tail(proc.stderr))


def _tail(text: str, n: int = 2000) -> str:
    return text[-n:] if text else ""
