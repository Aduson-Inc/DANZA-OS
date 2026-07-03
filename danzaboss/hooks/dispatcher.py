"""Hook dispatcher — maps Claude Code lifecycle events to DANZA guards/gates.

This is the ONLY environment-specific layer: it must track Claude Code's live hook
event names + return contract. Everything it calls (guards/gates) is pure and tested.
Verify the event names + JSON return shape against the current Claude Code hooks
docs before wiring settings.json (see settings.example.json).
"""
from __future__ import annotations

from typing import Optional

from .events import ToolEvent, TurnRecord, Decision
from .guards import (GuardConfig, capability_guard, hard_stop_guard, turn_lock_guard,
                     file_protection_guard, scope_guard, context_budget_guard)
from .gates import run_all_gates
from ..security.capabilities import CapabilityRegistry


class HookDispatcher:
    def __init__(self, registry: CapabilityRegistry, cfg: Optional[GuardConfig] = None,
                 *, current_boss: str = "claude", approved_task_ids: Optional[set] = None,
                 claude_approval: bool = False):
        self.registry = registry
        self.cfg = cfg or GuardConfig()
        self.current_boss = current_boss
        self.approved_task_ids = approved_task_ids or set()
        self.claude_approval = claude_approval

    def pre_tool_use(self, ev: ToolEvent) -> Decision:
        """Run all applicable PreToolUse guards; first denial wins (fail-closed)."""
        for decision in (
            capability_guard(ev, self.registry),
            hard_stop_guard(ev, self.cfg),
            turn_lock_guard(ev, self.cfg, self.current_boss),
            file_protection_guard(ev, self.cfg, approval=self.claude_approval),
            scope_guard(ev, self.approved_task_ids),
            context_budget_guard(ev, self.cfg),
        ):
            if not decision.allow:
                return decision
        return Decision.ok("pre_tool_use")

    def stop(self, rec: TurnRecord) -> Decision:
        """Run end-of-turn gates; first denial blocks the handoff."""
        for decision in run_all_gates(rec):
            if not decision.allow:
                return decision
        return Decision.ok("stop")
