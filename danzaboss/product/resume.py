"""Auto-resume SessionStart hook (spec D8, borrowed from GSD's session-start
pattern).

Why: in an activated repo a relay may be mid-flight. A fresh AI session that
does not know this will treat the repo as new work and violate the turn lock.
If .danza/handoff.md holds real handoff data (anything beyond the bootstrap
"No handoff yet."), we hand the session a CONTINUE MODE pointer at the
required reading (Rule 44: pointers, not briefings). Read-only: this hook
never mutates state, and its CLI wrapper fails open.
"""
from __future__ import annotations

import os
from pathlib import Path

from .handoff import HandoffMode, classify_handoff

HANDOFF_RELPATH = Path(".danza") / "handoff.md"
_BOOTSTRAP_MARKER = "No handoff yet."

_CONTINUE_BLOCK = (
    "CONTINUE MODE - a DANZA relay is in flight in this repo.\n"
    "Resume via the trigger phrase: \"Who's the Boss?\"\n"
    "Required reading before any work: .danza/handoff.md, "
    ".danza/runtime/team-state.json, .claude/rules/constitution.md."
)

_BLOCKED_BLOCK = (
    "DANZA STOP: runtime handoff validation failed.\n"
    "Do not start onboarding or agent work. Read .danza/handoff.md and "
    ".danza/runtime/handoff-state.json, then escalate the mismatch."
)


def session_start_context(root: str | os.PathLike = ".") -> str | None:
    """CONTINUE-MODE context block, or None when there is nothing to resume
    (missing/unreadable handoff, blank file, or the bootstrap marker)."""
    # A completely unactivated directory has no runtime boundary yet; the
    # hook remains quiet there. Once .danza exists, handoff state is mandatory
    # and classification is fail-closed.
    if not (Path(root) / ".danza").exists():
        return None
    result = classify_handoff(root)
    if result.mode is HandoffMode.NEW:
        return None
    if result.mode is HandoffMode.CONTINUE:
        return _CONTINUE_BLOCK
    return _BLOCKED_BLOCK + f"\nReason: {result.reason}"
