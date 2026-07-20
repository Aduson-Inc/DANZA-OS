"""Standalone installer downloaded by the pinned platform wrappers.

This file intentionally uses only the Python standard library so dependency
inspection and approval happen before the project-local package install.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPOSITORY = "https://github.com/Aduson-Inc/DANZA-OS"
DEFAULT_BRANCH = "Production-DANZABOSS"


def _run(argv: list[str], *, cwd: Path | None = None) -> None:
    print("[DANZABOSS] + " + " ".join(argv))
    subprocess.run(argv, cwd=str(cwd) if cwd else None, check=True)


def _is_empty(root: Path) -> bool:
    return not any(root.iterdir())


def _approve(yes: bool) -> bool:
    if yes or os.environ.get("DANZA_APPROVE") == "1":
        return True
    answer = input("[DANZABOSS] Approve installation? [y/N] ")
    return answer.strip().lower() in {"y", "yes"}


def install(target: Path, branch: str, *, yes: bool = False,
            no_open: bool = False) -> int:
    target = target.expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    print(f"[DANZABOSS] Source: {REPOSITORY}@{branch}")
    print("[DANZABOSS] Mandatory dependencies: Python 3.10+, Git.")
    print("[DANZABOSS] Optional dependency: tmux; never installed automatically.")
    print("[DANZABOSS] AI clients/models are selected and verified in the UI.")

    if sys.version_info < (3, 10):
        print("[DANZABOSS] ERROR: Python 3.10+ is required.", file=sys.stderr)
        return 2
    if shutil.which("git") is None:
        print("[DANZABOSS] ERROR: Git is required.", file=sys.stderr)
        return 2
    if not (target / ".git").exists():
        if not _is_empty(target):
            print("[DANZABOSS] ERROR: existing targets must be Git repositories; "
                  "empty folders are initialized automatically.", file=sys.stderr)
            return 2
        if not _approve(yes):
            print("[DANZABOSS] Installation cancelled before changes were made.")
            return 2
        _run(["git", "init"], cwd=target)
    elif not _approve(yes):
        print("[DANZABOSS] Installation cancelled before changes were made.")
        return 2

    venv = target / ".danza" / "runtime" / "venv"
    _run([sys.executable, "-m", "venv", str(venv)])
    python = venv / ("Scripts" if os.name == "nt" else "bin") / "python"
    package = f"git+{REPOSITORY}@{branch}"
    _run([str(python), "-m", "pip", "install", "--upgrade", package])
    activate = [str(python), "-m", "danzaboss.cli", "activate", str(target)]
    if no_open:
        activate.append("--no-open")
    _run(activate)
    print("[DANZABOSS] Core activation complete: http://localhost:33000")
    print("[DANZABOSS] Final installation status is pending until Setup verifies "
          "the AI connection.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default=".")
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args(argv)
    if args.branch != DEFAULT_BRANCH:
        parser.error(f"branch must be pinned to {DEFAULT_BRANCH}")
    try:
        return install(Path(args.target), args.branch, yes=args.yes,
                       no_open=args.no_open)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"[DANZABOSS] ERROR: installation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
