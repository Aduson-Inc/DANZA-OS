"""danza doctor - environment + activation health checks (spec section 5).

Wraps the cold-start selftest and adds the product-level checks a fresh
install needs: interpreter floor, git repo, scaffold integrity, active
profile, runner detection, and CORTEX state. D9 makes CORTEX load-bearing:
in an activated repo (team-state.json present, Rule 45) a dormant CORTEX or
an unwritable store is a FAILURE, never a warning.

Reuses the selftest Report/Check shape so callers render both the same way.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

from danzaboss.cortex.factory import db_path
from danzaboss.kernel.profile import active_profile
from danzaboss.product.scaffold import SCAFFOLD_VERSION_RELPATH
from danzaboss.selftest.harness import Report, run_cold_start
from danzaboss.workstation.runners import detect_runners

_TEAM_STATE_RELPATH = Path(".danza") / "runtime" / "team-state.json"
_RUNTIME_PROFILES = ("OS_BOOT_TEST", "APP_BUILD")


def run_doctor(root: str | os.PathLike = ".",
               which=shutil.which, env: dict | None = None) -> Report:
    """Health-check *root*. `which` and `env` are injectable so tests never
    depend on the host's real binaries or environment variables."""
    r = Report()
    root = Path(root)

    ver = sys.version_info
    r.add("python_version", ver >= (3, 10),
          f"{ver.major}.{ver.minor}.{ver.micro} (need >= 3.10)")

    is_git = (root / ".git").exists()
    r.add("git_repo", is_git,
          f"{root} {'is' if is_git else 'is NOT'} a git repo")

    _check_scaffold(r, root)

    try:
        prof = active_profile(str(root), env=env)
    except ValueError as e:
        r.add("profile", False, str(e))
        return r  # profile-dependent checks below cannot run
    r.add("profile", True, prof.name)

    detected = detect_runners(which)
    summary = ", ".join(f"{n}: {'detected' if ok else 'not found'}"
                        for n, ok in detected.items())
    r.add("runners", True, summary)  # informational: conduct fails loudly itself

    _check_cortex(r, root, prof)

    cold = run_cold_start()
    d = cold.to_dict()
    r.add("selftest", cold.ok, f"cold-start {d['passed']}/{d['total']} checks")
    return r


def _check_scaffold(r: Report, root: Path) -> None:
    """Scaffold integrity: every file the stamp records must still exist.

    No stamp is healthy for an unscaffolded tree (the OS source repo, or a
    legacy repo activated before the product existed) - the check only binds
    once `danza init` has stamped .danza/.scaffold-version."""
    manifest_path = root / SCAFFOLD_VERSION_RELPATH
    if not manifest_path.exists():
        if (root / _TEAM_STATE_RELPATH).exists():
            r.add("scaffold", True,
                  "activated without scaffold stamp (pre-product activation)")
        else:
            r.add("scaffold", True, "not an activated repo (no scaffold stamp)")
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        recorded = manifest["files"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
        r.add("scaffold", False, f"unreadable .scaffold-version: {e}")
        return
    missing = [rel for rel in recorded if not (root / rel).exists()]
    if missing:
        r.add("scaffold", False,
              f"missing scaffold files: {', '.join(sorted(missing)[:5])}"
              + (" ..." if len(missing) > 5 else ""))
    else:
        r.add("scaffold", True,
              f"v{manifest.get('version', '?')}, {len(recorded)} files present")


def _check_cortex(r: Report, root: Path, prof) -> None:
    """D9: CORTEX is load-bearing at runtime. An activated repo forced into a
    memory_level=none profile fails; a runtime profile must be able to write
    the store. Dormancy is only healthy where nothing is activated (Layer 0)."""
    activated = (root / _TEAM_STATE_RELPATH).exists()
    if activated and prof.memory_level == "none":
        r.add("cortex", False,
              f"CORTEX dormant (memory_level=none) in an ACTIVATED repo - "
              f"profile {prof.name} is a Layer-0 profile; remove the override "
              f"(D9: CORTEX is load-bearing at runtime)")
        return
    if prof.name in _RUNTIME_PROFILES:
        db = Path(db_path(str(root)))
        try:
            db.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(db)
            try:
                con.execute("PRAGMA user_version")
            finally:
                con.close()
            r.add("cortex", True, f"store writable at {db}")
        except (OSError, sqlite3.Error) as e:
            r.add("cortex", False, f"CORTEX store unwritable at {db}: {e}")
        return
    r.add("cortex", True, f"dormant by design in {prof.name} (repo not activated)")
