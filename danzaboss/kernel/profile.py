"""Execution profiles — the layer-aware efficiency governor (C4.5).

DANZABOSS behaves differently depending on WHY it is running:

  OS_DEV        Layer 0 — Fable/Claude improving DANZABOSS itself. Speed and
                judgment. Runtime ceremony is OFF; the Constitution is source
                material being edited, not binding law.
  OS_BOOT_TEST  Layer 2 boot validation in a disposable repo. Full governance
                ON, deliberately, to prove the boot image works.
  APP_BUILD     Layers 2/3 — activated DANZABOSS building a user app (Layer 4).
                Full governance, always.

Why this exists: without an explicit mode, Layer-2/3 runtime law (hard-stop
escalations, .claude/ immutability, per-session distillation demands, full-suite
reflexes) leaks into Layer-0 development and burns tokens on ceremony that
protects nothing. The fix is separation, not weakening: OS_DEV relaxes what only
matters at runtime, while destructive-command denial and research approval stay
binding in every profile.

Resolution order (first hit wins; deterministic, no hidden state):
  1. DANZABOSS_PROFILE environment variable
  2. .danza/runtime/profile.json         {"profile": "OS_DEV"}
  3. Heuristic: .danza/runtime/team-state.json exists -> APP_BUILD (the kernel
     writes it at activation, Rule 45); otherwise OS_DEV (unactivated source).
OS_BOOT_TEST is never inferred — boot tests must opt in via 1 or 2.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field

PROFILE_ENV_VAR = "DANZABOSS_PROFILE"
PROFILE_FILE = os.path.join(".danza", "runtime", "profile.json")
_TEAM_STATE_FILE = os.path.join(".danza", "runtime", "team-state.json")

MEMORY_LEVELS = ("none", "lightweight", "normal", "critical")


@dataclass(frozen=True)
class Profile:
    """One execution mode: which rules bind, which hooks run, how much ceremony."""
    name: str
    layer: int                        # dominant layer this mode serves
    description: str
    constitution_binding: bool        # is constitution.md active law here?
    ceremony: str                     # "minimal" | "full"
    # -- PreToolUse guard policy ------------------------------------------------
    claude_write_approval: bool       # Rule 37: .claude/ writes pre-approved?
    domain_ask_active: bool           # Rules 13-15: auth/payment/schema asks fire?
    destructive_deny_active: bool     # Rule 16: NEVER False in any profile
    # -- Stop / end-of-turn policy ----------------------------------------------
    turn_gates_active: bool           # anti-theatre / verify / regression gates
    reports_required: bool            # handoff + self-audit evidence reports
    # -- memory policy ----------------------------------------------------------
    memory_level: str                 # none | lightweight | normal | critical
    distill_min_events: int           # stop-gate blocks only at/above this count
    session_inject: bool              # session-start injects the CORTEX context block
    distill_gate_active: bool         # stop-hook enforces distillation (blocks + drafts)
    # -- orchestration policy ---------------------------------------------------
    agents_may_spawn: bool            # may the full driver roster be dispatched?
    subagents_on_demand_only: bool    # spawn only when the task clearly benefits
    # -- research policy (binding in EVERY profile) -------------------------------
    research_requires_approval: bool  # Tavily/web research needs explicit user OK

    def to_dict(self) -> dict:
        return asdict(self)


PROFILES: dict[str, Profile] = {
    "OS_DEV": Profile(
        name="OS_DEV", layer=0,
        description="Fable improving DANZABOSS itself — changing the factory",
        constitution_binding=False, ceremony="minimal",
        claude_write_approval=True, domain_ask_active=False,
        destructive_deny_active=True,
        turn_gates_active=False, reports_required=False,
        memory_level="lightweight", distill_min_events=3,
        session_inject=False, distill_gate_active=False,
        agents_may_spawn=False, subagents_on_demand_only=True,
        research_requires_approval=True),
    "OS_BOOT_TEST": Profile(
        name="OS_BOOT_TEST", layer=2,
        description="Boot-image validation in a disposable repo — full governance on",
        constitution_binding=True, ceremony="full",
        claude_write_approval=False, domain_ask_active=True,
        destructive_deny_active=True,
        turn_gates_active=True, reports_required=True,
        memory_level="normal", distill_min_events=1,
        session_inject=True, distill_gate_active=True,
        agents_may_spawn=True, subagents_on_demand_only=False,
        research_requires_approval=True),
    "APP_BUILD": Profile(
        name="APP_BUILD", layer=2,
        description="Activated DANZABOSS building a user app — runtime law binds",
        constitution_binding=True, ceremony="full",
        claude_write_approval=False, domain_ask_active=True,
        destructive_deny_active=True,
        turn_gates_active=True, reports_required=True,
        memory_level="normal", distill_min_events=1,
        session_inject=True, distill_gate_active=True,
        agents_may_spawn=True, subagents_on_demand_only=False,
        research_requires_approval=True),
}


def active_profile(root: str = ".", env: dict | None = None) -> Profile:
    """Resolve the active profile for a repo root. Raises ValueError on an
    explicitly configured but unknown name (fail closed on bad config); hook
    callers wrap this in their existing fail-open handlers."""
    env = env if env is not None else os.environ
    name = (env.get(PROFILE_ENV_VAR) or "").strip()
    if not name:
        cfg = os.path.join(root, PROFILE_FILE)
        if os.path.exists(cfg):
            try:
                with open(cfg, encoding="utf-8") as fh:
                    name = str(json.load(fh).get("profile", "")).strip()
            except (OSError, json.JSONDecodeError) as e:
                raise ValueError(f"unreadable profile config {cfg}: {e}") from e
    if name:
        key = name.upper()
        if key not in PROFILES:
            raise ValueError(f"unknown DANZABOSS profile {name!r}; "
                             f"expected one of {sorted(PROFILES)}")
        return PROFILES[key]
    # heuristic: activation creates team-state.json (Rule 45); no file -> Layer 0
    if os.path.exists(os.path.join(root, _TEAM_STATE_FILE)):
        return PROFILES["APP_BUILD"]
    return PROFILES["OS_DEV"]


# ---- memory significance (capture diet) ---------------------------------------
# In "lightweight" mode only events that could plausibly matter later are
# captured: file mutations, and shell commands that change or prove state
# (commits, pushes, test runs, danza CLI actions). Reads and trivial shell
# noise never become memory pressure.

_MUTATING_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
_SIGNIFICANT_CMD = re.compile(
    r"\bgit\s+(commit|push|merge|revert|rebase)\b"
    r"|\brun_tests\.sh\b|\bunittest\b|\bpytest\b"
    r"|danzaboss\.cli\b", re.IGNORECASE)


def event_significant(tool: str, command: str = "") -> bool:
    """Would a future session plausibly care that this event happened?"""
    if tool in _MUTATING_TOOLS:
        return True
    if tool == "Bash":
        return bool(_SIGNIFICANT_CMD.search(command or ""))
    return False


def capture_event(profile: Profile, tool: str, command: str = "") -> bool:
    """Should this tool event be recorded at the profile's memory level?"""
    if profile.memory_level == "none":
        return False
    if profile.memory_level == "lightweight":
        return event_significant(tool, command)
    return True  # normal / critical capture everything (redacted upstream)
