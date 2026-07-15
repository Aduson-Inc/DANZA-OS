"""Runner registry for DANZA workstation — knows which AI runners exist and how
to invoke them in interactive or headless mode.

Why this module exists: the workstation UI needs a stable, validated record of
which AI CLI runners are available on the host, which one is the current boss,
and what argv to pass for each invocation mode. This is the single source of
truth; every other module imports from here rather than hard-coding runner names.

Presence vs. auth: detect_runners checks binary presence via shutil.which;
probe_auth confirms authentication by running one cheap headless no-op through
the runner's own CLI. build_registry combines both: detect → default_config →
probe, stamping every entry with auth ∈ ("ok", "unauthenticated", "unprobed").
Runners without a headless argv cannot be probed and stay "unprobed" —
potentially usable, but unconfirmed.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 2

RUNNERS_RELPATH: Path = Path(".danza") / "runtime" / "runners.json"

# Insertion order is significant: detect_runners returns results in this order,
# default_config picks the first detected runner as boss, and seat suggestion
# (workstation.routing) resolves ties in this order.
#
# v2 fields: display_name/strengths feed the SETUP tab's plain-English agent
# cards; suggested_seats drives seat auto-suggestion; activation says how an
# ignited session receives its kickoff phrase ("argv" = appended to the command,
# "typed" = typed into the session after launch).
KNOWN_RUNNERS: dict[str, dict] = {
    "claude": {
        "kind": "cli", "binary": "claude",
        "display_name": "Claude Code",
        "strengths": "Deep reasoning, complex building, careful review",
        "suggested_seats": ["plan", "build", "review", "security"],
        "activation": "argv",
        "interactive": ["claude"],
        "headless": ["claude", "-p", "--output-format", "json"],
    },
    "codex": {
        # Headless mode is not yet supported for codex (empty list signals
        # this). headless_argv will raise RunnerError rather than returning an
        # empty command — callers must not attempt headless dispatch for codex
        # until this is filled in.
        "kind": "cli", "binary": "codex",
        "display_name": "Codex",
        "strengths": "Fast, focused code edits",
        "suggested_seats": ["build", "qa"],
        "activation": "argv",
        "interactive": ["codex"],
        "headless": [],
    },
    "gemini": {
        "kind": "cli", "binary": "gemini",
        "display_name": "Gemini CLI",
        "strengths": "Long-context research and summarizing",
        "suggested_seats": ["research", "map"],
        "activation": "argv",
        "interactive": ["gemini"],
        "headless": [],
    },
    "grok": {
        "kind": "cli", "binary": "grok",
        "display_name": "Grok CLI",
        "strengths": "Quick answers and fast iteration",
        "suggested_seats": ["qa", "research"],
        "activation": "argv",
        "interactive": ["grok"],
        "headless": [],
    },
    "opencode": {
        "kind": "cli", "binary": "opencode",
        "display_name": "OpenCode",
        "strengths": "Flexible open-source coding",
        "suggested_seats": ["build", "design"],
        "activation": "argv",
        "interactive": ["opencode"],
        "headless": [],
    },
    # Copy-me template for any other CLI. Empty binary => never detected;
    # excluded from detect_runners results and from lineups.
    "generic": {
        "kind": "cli", "binary": "",
        "display_name": "Custom agent",
        "strengths": "",
        "suggested_seats": [],
        "activation": "argv",
        "interactive": [],
        "headless": [],
    },
}

_VALID_SESSION_HOSTS = ("tmux", "headless")
_VALID_ACTIVATIONS = ("argv", "typed")

# Auth-probe prompt: a one-word reply is the cheapest possible round trip that
# still proves the CLI can reach its backend with live credentials. Exit code
# is the only signal read — output content is deliberately ignored so vendor
# formatting changes cannot break the probe.
_PROBE_PROMPT = "Reply with the single word: pong"
_PROBE_TIMEOUT_SECONDS = 30
_REQUIRED_RUNNER_KEYS = ("kind", "binary", "display_name", "strengths",
                         "suggested_seats", "activation",
                         "interactive", "headless")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class RunnerError(ValueError):
    """Invalid registry state, unknown runner, or unsupported operation."""


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_runners(
        which: Callable[[str], str | None] = shutil.which
) -> dict[str, bool]:
    """Return presence (True/False) for every known runner, keyed by runner
    name.  Uses *which* to locate each runner's binary — injectable so tests
    never hit the real filesystem.

    Only binary presence is checked here; authenticated usability is
    probe_auth's job (it needs a real subprocess call).

    Entries with an empty binary (the "generic" copy-me template) are skipped
    entirely — there is nothing to look up, so they never appear as detected."""
    return {name: which(entry["binary"]) is not None
            for name, entry in KNOWN_RUNNERS.items()
            if entry["binary"]}


def probe_auth(entry: dict, run: Callable = subprocess.run) -> str:
    """Probe whether a runner entry is actually authenticated by running one
    cheap headless no-op. Returns "ok", "unauthenticated", or "unprobed".

    Injectable *run* mirrors detect_runners' injectable *which* — tests pass a
    double; production uses subprocess.run. Entries that are undetected or
    have no headless argv cannot be probed: they return "unprobed" without any
    subprocess call. Exit 0 → "ok"; a nonzero exit, a timeout, or an OSError
    (binary vanished between detect and probe) → "unauthenticated" — fail
    closed rather than assuming credentials exist."""
    if not entry.get("detected", False) or not entry["headless"]:
        return "unprobed"
    argv = list(entry["headless"]) + [_PROBE_PROMPT]
    try:
        result = run(argv, capture_output=True, text=True,
                     timeout=_PROBE_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return "unauthenticated"
    return "ok" if result.returncode == 0 else "unauthenticated"


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
    corrupt the module-level constant. Every entry is also stamped
    auth="unprobed" so a default config is always a complete, valid shape —
    build_registry upgrades the stamp for entries it can actually probe."""
    boss = next(
        (name for name in KNOWN_RUNNERS if detected.get(name, False)),
        None,
    )
    runners = {
        name: {**copy.deepcopy(entry),
               "detected": detected.get(name, False),
               "auth": "unprobed"}
        for name, entry in KNOWN_RUNNERS.items()
    }
    return {
        "version": SCHEMA_VERSION,
        "boss": boss,
        "session_host": "tmux",
        "permission_mode": None,
        "runners": runners,
    }


def build_registry(which: Callable = shutil.which,
                   run: Callable = subprocess.run) -> dict:
    """Detect runners, build a default config, then auth-probe every entry:
    the one-call path from "empty machine" to a fully stamped registry.

    probe_auth itself skips undetected or headless-less entries (they keep
    "unprobed"), so the probe pass is safe to run over the whole table."""
    config = default_config(detect_runners(which=which))
    for entry in config["runners"].values():
        entry["auth"] = probe_auth(entry, run=run)
    return config


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
            f"runner config version {version!r} != expected {SCHEMA_VERSION} "
            f"— open the dashboard SETUP tab to reconnect your agents"
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
        if entry["activation"] not in _VALID_ACTIVATIONS:
            raise RunnerError(
                f"runner {name!r}.activation {entry['activation']!r} not in "
                f"{_VALID_ACTIVATIONS!r}"
            )
        for argv_key in ("interactive", "headless", "suggested_seats"):
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

    # An unauthenticated boss can never take a turn — reject at validation
    # time so the bad state is caught at save/load, not mid-relay. (Lineup
    # membership checks are routing.json's job, not this file's.)
    if boss is not None and runners[boss].get("auth") == "unauthenticated":
        raise RunnerError(
            f"boss {boss!r} is not logged in — open the dashboard SETUP tab "
            f"to reconnect your agents"
        )

    return config


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_runners(root: str | os.PathLike, config: dict) -> Path:
    """Validate *config* and atomically write it to RUNNERS_RELPATH under
    *root*.

    Atomic write (tmp → os.replace) so a crash never leaves a torn file.
    Plain overwrite is correct here — this is a generated-whole config (the
    /models screen writes the entire file at once), so merging would
    reintroduce stale runner entries. Same reasoning as compiler.write_spec."""
    validate_config(config)
    path = Path(root) / RUNNERS_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_runners(root: str | os.PathLike) -> dict:
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
