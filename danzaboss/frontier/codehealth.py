"""Code-health pass: local, key-free analysis of the canonical repo (no
network, no AI call) that can also emit frontier proposals. Deliberately
simple and deterministic (task 11 design guidance #4) -- one heuristic,
oversized modules, flagged for a human to consider splitting.
"""
from __future__ import annotations

from pathlib import Path

LINE_THRESHOLD = 700


def code_health_pass(root) -> list[dict]:
    """Python files under `danzaboss/` (excluding tests) longer than
    LINE_THRESHOLD lines become one proposal each. A missing danzaboss/ dir
    (e.g. an unexpected root) just yields no proposals -- never an error."""
    src_dir = Path(root) / "danzaboss"
    if not src_dir.is_dir():
        return []
    proposals = []
    for path in sorted(src_dir.rglob("*.py")):
        if "tests" in path.relative_to(src_dir).parts:
            continue
        try:
            with path.open(encoding="utf-8") as fh:
                lines = sum(1 for _ in fh)
        except OSError:
            continue
        if lines > LINE_THRESHOLD:
            rel = path.relative_to(root).as_posix()
            proposals.append({
                "title": f"Review {rel} for extraction",
                "summary": (f"{rel} is {lines} lines -- consider splitting "
                           "it into smaller, single-responsibility modules."),
                "source": "code_health",
            })
    return proposals
