"""Runner registry for DANZA workstation — knows which AI runners exist and how
to invoke them in interactive or headless mode.

Why this module exists: the workstation UI needs a stable, validated record of
which AI CLI runners are available on the host, which one is the current boss,
and what argv to pass for each invocation mode. This is the single source of
truth; every other module imports from here rather than hard-coding runner names.

Presence vs. auth: detect_runners checks binary presence via shutil.which.
Confirmed authentication (e.g., a live /models ping) is deferred to the P5
auth-probe step — it requires a network call and real credentials. Presence is
the v1 signal; treat a detected runner as "potentially usable" until the P5
probe confirms it is actually authed.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1

RUNNERS_RELPATH: Path = Path(".danza") / "runtime" / "runners.json"

# Insertion order is significant: detect_runners returns results in this order,
# and default_config picks the first detected runner as boss.
KNOWN_RUNNERS: dict[str, dict] = {
    "claude": {
        "kind": "cli",
        "binary": "claude",
        "interactive": ["claude"],
        "headless": ["claude", "-p", "--output-format", "json"],
    },
    "codex": {
        # Detect-only placeholder. Headless mode is not yet supported for codex
        # (empty list signals this). headless_argv will raise RunnerError rather
        # than returning an empty command — callers must not attempt headless
        # dispatch for codex until this is filled in.
        "kind": "cli",
        "binary": "codex",
        "interactive": ["codex"],
        "headless": [],
    },
}

_VALID_SESSION_HOSTS = ("tmux", "headless")
_REQUIRED_RUNNER_KEYS = ("kind", "binary", "interactive", "headless")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class RunnerError(ValueError):
    """Invalid registry state, unknown runner, or unsupported operation."""


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_runners(which=shutil.which) -> dict[str, bool]:
    """Return presence (True/False) for every known runner, keyed by runner
    name.  Uses *which* to locate each runner's binary — injectable so tests
    never hit the real filesystem.

    Only binary presence is checked here; authenticated usability requires a
    live /models probe (P5, out of scope for this module)."""
    return {name: which(entry["binary"]) is not None
            for name, entry in KNOWN_RUNNERS.items()}


# ---------------------------------------------------------------------------
# Config construction
# ---------------------------------------------------------------------------

def default_config(detected: dict[str, bool]) -> dict:
    """Build a fresh runner config from a detect_runners result.

    Boss selection: first key in KNOWN_RUNNERS order that is detected, else
    None. Preserving KNOWN_RUNNERS insertion order matters so the preference
    ranking is consistent without a separate priority list.

    Each runner entry is a deep copy of the KNOWN_RUNNERS template with a
    'detected' flag appended so callers that mutate the returned config cannot
    corrupt the module-level constant."""
    boss = next(
        (name for name in KNOWN_RUNNERS if detected.get(name, False)),
        None,
    )
    runners = {
        name: {**copy.deepcopy(entry), "detected": detected.get(name, False)}
        for name, entry in KNOWN_RUNNERS.items()
    }
    return {
        "version": SCHEMA_VERSION,
        "boss": boss,
        "session_host": "tmux",
        "permission_mode": None,
        "runners": runners,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_config(config: object) -> dict:
    """Validate a runner config dict. Returns the config on success; raises
    RunnerError describing the first violation found.

    Validates: type, schema version, boss coherence, session_host whitelist,
    runners dict, and each runner entry's required keys and argv list types.
    Fail-closed: any structural defect is an error, never a silent default."""
    if not isinstance(config, dict):
        raise RunnerError(
            f"runner config must be a dict, got {type(config).__name__!r}"
        )

    version = config.get("version", _MISSING := object())
    if version is _MISSING:
        raise RunnerError("runner config missing 'version' key")
    if version != SCHEMA_VERSION:
        raise RunnerError(
            f"runner config version {version!r} != expected {SCHEMA_VERSION}"
        )

    runners = config.get("runners")
    if not isinstance(runners, dict):
        raise RunnerError(
            f"'runners' must be a dict, got {type(runners).__name__!r}"
        )

    boss = config.get("boss")
    if boss is not None and boss not in runners:
        raise RunnerError(
            f"boss {boss!r} is not a key in runners ({list(runners)!r})"
        )

    session_host = config.get("session_host")
    if session_host not in _VALID_SESSION_HOSTS:
        raise RunnerError(
            f"session_host {session_host!r} not in {_VALID_SESSION_HOSTS!r}"
        )

    for name, entry in runners.items():
        if not isinstance(entry, dict):
            raise RunnerError(
                f"runner {name!r} entry must be a dict, got "
                f"{type(entry).__name__!r}"
            )
        for key in _REQUIRED_RUNNER_KEYS:
            if key not in entry:
                raise RunnerError(
                    f"runner {name!r} entry missing required key {key!r}"
                )
        for argv_key in ("interactive", "headless"):
            argv = entry[argv_key]
            if not isinstance(argv, list):
                raise RunnerError(
                    f"runner {name!r}.{argv_key} must be a list of strings, "
                    f"got {type(argv).__name__!r}"
                )
            if not all(isinstance(s, str) for s in argv):
                raise RunnerError(
                    f"runner {name!r}.{argv_key} must be a list of strings; "
                    f"found non-string element"
                )

    return config


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_runners(root, config: dict) -> Path:
    """Validate *config* and atomically write it to RUNNERS_RELPATH under
    *root*.

    Atomic write (tmp → os.replace) so a crash never leaves a torn file.
    Plain overwrite is correct here — this is a generated-whole config (the
    /models screen writes the entire file at once), so merging would
    reintroduce stale runner entries. Same reasoning as compiler.write_spec."""
    validate_config(config)
    path = Path(root) / RUNNERS_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_runners(root) -> dict:
    """Read and validate the runner config from RUNNERS_RELPATH under *root*.

    Missing file → RunnerError mentioning /models so callers can surface a
    helpful message (the /models UI button stays dark with a reason rather than
    silently defaulting). Invalid JSON → RunnerError."""
    path = Path(root) / RUNNERS_RELPATH
    if not path.exists():
        raise RunnerError(
            f"runner config not found at {path}; open /models to generate it"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RunnerError(f"runner config at {path} is not valid JSON: {exc}") from exc
    return validate_config(raw)


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------

def boss_runner(config: dict) -> dict:
    """Return the boss's runner entry dict from *config*. RunnerError if boss
    is None (nothing was detected when the config was built)."""
    boss = config.get("boss")
    if boss is None:
        raise RunnerError(
            "no boss set in runner config — no supported runner was detected"
        )
    return config["runners"][boss]


def headless_argv(config: dict) -> list[str]:
    """A copy of the boss runner's headless argv prefix. Raises RunnerError if
    the list is empty (the runner does not yet support headless invocation)."""
    runner = boss_runner(config)
    argv = runner["headless"]
    if not argv:
        raise RunnerError(
            f"runner {config['boss']!r} does not support headless mode "
            f"(headless argv is empty)"
        )
    return list(argv)


def interactive_argv(config: dict) -> list[str]:
    """A copy of the boss runner's interactive argv. Always returns a list;
    callers own the returned copy and may mutate it freely."""
    runner = boss_runner(config)
    return list(runner["interactive"])
