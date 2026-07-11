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

HANDOFF_RELPATH = Path(".danza") / "handoff.md"
_BOOTSTRAP_MARKER = "No handoff yet."

_CONTINUE_BLOCK = (
    "CONTINUE MODE - a DANZA relay is in flight in this repo.\n"
    "Resume via the trigger phrase: \"Who's the Boss?\"\n"
    "Required reading before any work: .danza/handoff.md, "
    ".danza/runtime/team-state.json, .claude/rules/constitution.md."
)


def session_start_context(root: str | os.PathLike = ".") -> str | None:
    """CONTINUE-MODE context block, or None when there is nothing to resume
    (missing/unreadable handoff, blank file, or the bootstrap marker)."""
    try:
        text = (Path(root) / HANDOFF_RELPATH).read_text(encoding="utf-8")
    except OSError:
        return None  # not an activated repo -> stay silent
    if not text.strip() or _BOOTSTRAP_MARKER in text:
        return None
    return _CONTINUE_BLOCK
