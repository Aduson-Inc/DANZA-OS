"""Normalized hook events — DANZA governance layer.

Claude Code fires lifecycle hooks (PreToolUse, PostToolUse, SubagentStop, Stop,
SessionStart, PreCompact). We normalize whatever the environment passes into a
small, stable event object so the guard/gate logic is testable and independent of
any one environment's exact payload shape. The environment-specific adapter
(dispatcher + settings) is the only part that must track Claude Code's live API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolEvent:
    """A normalized PreToolUse/PostToolUse event."""
    actor: str                      # acting agent id, e.g. "tony-d-orchestrator"
    tool: str                       # "Write" | "Edit" | "Bash" | "Task" | ...
    path: str = ""                  # target file (Write/Edit)
    command: str = ""               # shell command (Bash)
    args: dict = field(default_factory=dict)
    payload_tokens: int = 0         # estimated tokens in a sub-agent dispatch
    task_id: Optional[str] = None   # the plan task this action belongs to
    elevation_token: Optional[Any] = None  # capability elevation, if minted


@dataclass
class TurnRecord:
    """A normalized Stop/end-of-turn record, for the end-of-turn gates."""
    actor: str
    claimed_subagents: list[str] = field(default_factory=list)   # who Tony D says ran
    evidence_actors: list[str] = field(default_factory=list)      # who actually ran (trace/SubagentStop)
    completed_features: list[str] = field(default_factory=list)
    verifications: dict = field(default_factory=dict)  # feature -> passed(bool)
    tests_green: Optional[bool] = None                  # regression suite result


@dataclass
class Decision:
    allow: bool
    reason: str
    hook: str

    @classmethod
    def ok(cls, hook: str) -> "Decision":
        return cls(True, "", hook)

    @classmethod
    def deny(cls, hook: str, reason: str) -> "Decision":
        return cls(False, reason, hook)
