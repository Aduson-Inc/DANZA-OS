"""PreToolUse guards — DANZA governance (Tier-1 hooks).

Each guard is a pure function: (ToolEvent, config) -> Decision. They fire only on
the dangerous/dishonest minority of actions; ordinary reads/edits pass untouched,
so trivial work is never slowed. All guards are app-agnostic — paths and patterns
come from config, never hardcoded to a specific app.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .events import ToolEvent, Decision
from ..security.capabilities import (
    CapabilityRegistry, Capability, CapabilityError)

_CODE_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
_DISPATCH_TOOLS = {"Task", "Agent"}


@dataclass
class GuardConfig:
    """All app-specific matching is configuration, not code."""
    # hard-stop file patterns (Rules 13-15) — regex, tuned per project profile
    auth_patterns: list[str] = field(default_factory=lambda: [r"auth", r"login", r"session", r"jwt", r"oauth"])
    payment_patterns: list[str] = field(default_factory=lambda: [r"payment", r"billing", r"stripe", r"checkout", r"invoice"])
    schema_patterns: list[str] = field(default_factory=lambda: [r"migration", r"schema", r"\.sql$", r"models?\.py$"])
    # destructive shell commands (Rule 16)
    destructive_cmds: list[str] = field(default_factory=lambda: [r"\brm\s+-rf?\b", r"\bgit\s+push\s+--force\b", r"\bdrop\s+table\b", r"\btruncate\b"])
    # file protection (Rules 34-37)
    template_glob: str = r".*-template\.md$"
    immutable_prefix: str = ".claude/"
    log_files: list[str] = field(default_factory=lambda: ["decision-log.md", "turn-log.md", "self-assessment-log.md", "build-history.md", "onboarding-misses.md", "patterns.md"])
    state_files: list[str] = field(default_factory=lambda: ["team-state.json", "handoff.md"])
    # context budget for sub-agent dispatch
    # calibrated to the json divisor in cortex/tokens.py; if the divisor changes, recalibrate this ceiling
    max_dispatch_tokens: int = 8000


def _matches_any(text: str, patterns: list[str]) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


# -- 1. capability / role guard (Rule 42 role separation, Upgrade #10) --------
def capability_guard(ev: ToolEvent, registry: CapabilityRegistry) -> Decision:
    hook = "capability_guard"
    cap = None
    if ev.tool in _CODE_WRITE_TOOLS:
        cap = Capability.WRITE_CODE
    elif ev.tool == "Bash":
        cap = Capability.RUN_TESTS  # coarse; refined by hard_stop for destructive
    if cap is None:
        return Decision.ok(hook)
    try:
        registry.check(ev.actor, cap, elevation=ev.elevation_token)
        return Decision.ok(hook)
    except CapabilityError as e:
        return Decision.deny(hook, str(e))


# -- 2. hard-stop guard (Rules 13-16) ----------------------------------------
def hard_stop_guard(ev: ToolEvent, cfg: GuardConfig) -> Decision:
    hook = "hard_stop_guard"
    domain = None
    target = ev.path or ev.command
    if _matches_any(target, cfg.auth_patterns):
        domain = "auth"
    elif _matches_any(target, cfg.payment_patterns):
        domain = "payment"
    elif _matches_any(target, cfg.schema_patterns):
        domain = "db_schema"
    if ev.tool == "Bash" and _matches_any(ev.command, cfg.destructive_cmds):
        domain = "destructive"
    if domain is None:
        return Decision.ok(hook)
    if ev.elevation_token is not None:
        return Decision.ok(hook)  # user-approved elevation present
    return Decision.deny(hook, f"HARD STOP: {domain} action requires user-approved "
                               f"elevation (Constitution Rules 13-16). Notify user.")


# -- 3. turn-lock / state-write guard (Rules 38/45, W1 defense-in-depth) ------
def turn_lock_guard(ev: ToolEvent, cfg: GuardConfig, current_boss: str) -> Decision:
    hook = "turn_lock_guard"
    if ev.tool not in _CODE_WRITE_TOOLS:
        return Decision.ok(hook)
    if not any(ev.path.endswith(sf) for sf in cfg.state_files):
        return Decision.ok(hook)
    if ev.actor != current_boss:
        return Decision.deny(hook, f"turn lock: {ev.actor} may not write turn state "
                                   f"owned by {current_boss}")
    return Decision.ok(hook)


# -- 4. file-protection guard (Rules 34-37) ----------------------------------
def file_protection_guard(ev: ToolEvent, cfg: GuardConfig, *, approval: bool = False) -> Decision:
    hook = "file_protection_guard"
    if ev.tool not in _CODE_WRITE_TOOLS:
        return Decision.ok(hook)
    p = ev.path
    if re.search(cfg.template_glob, p):
        return Decision.deny(hook, f"templates are read-only (Rule 34): {p}")
    if cfg.immutable_prefix in p and not approval:
        return Decision.deny(hook, f".claude/ is immutable without user approval (Rule 37): {p}")
    if ev.tool == "Write" and any(p.endswith(lf) for lf in cfg.log_files):
        return Decision.deny(hook, f"logs are append-only; use Edit-append not overwrite (Rule 36): {p}")
    return Decision.ok(hook)


# -- 5. scope guard (no unrequested/gold-plated work) ------------------------
def scope_guard(ev: ToolEvent, approved_task_ids: set[str]) -> Decision:
    hook = "scope_guard"
    if ev.tool not in _CODE_WRITE_TOOLS:
        return Decision.ok(hook)
    if ev.task_id is None:
        return Decision.deny(hook, "code write has no task_id; every build action must "
                                   "belong to an approved plan task")
    if ev.task_id not in approved_task_ids:
        return Decision.deny(hook, f"task {ev.task_id!r} is not in the approved plan "
                                   "(enhancement needs remote approval first)")
    return Decision.ok(hook)


# -- 6. context-budget guard (token discipline on dispatch) ------------------
def context_budget_guard(ev: ToolEvent, cfg: GuardConfig) -> Decision:
    hook = "context_budget_guard"
    if ev.tool not in _DISPATCH_TOOLS:
        return Decision.ok(hook)
    if ev.payload_tokens > cfg.max_dispatch_tokens:
        return Decision.deny(hook, f"sub-agent dispatch payload {ev.payload_tokens} tok "
                                   f"exceeds budget {cfg.max_dispatch_tokens}; use the "
                                   "compiled/budgeted context, not the whole repo")
    return Decision.ok(hook)
