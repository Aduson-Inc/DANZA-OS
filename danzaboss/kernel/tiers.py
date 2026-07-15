"""Verification tiers — cheapest safe verification per change (C4.5).

The same testing burden must not apply to every change: a docs tweak does not
need 277 tests and a kernel edit does not get away with a smoke check. This
module maps a set of touched paths to the LOWEST tier that still safely proves
the claim. Deterministic, path-based, no I/O.

  Tier 0  none        docs/comments only, no behavior
  Tier 1  smoke       UI/CSS/static assets — lint + browser check
  Tier 2  targeted    one module touched — run its test file
  Tier 3  subsystem   hooks/CORTEX/CLI/kernel/runtime — run the subsystem tests
  Tier 4  full        security/state, cross-subsystem, or any commit boundary
  Tier 5  boot        boot-image behavior — activate in a disposable repo
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tier:
    level: int
    name: str
    action: str          # what verification this tier demands


TIERS: dict[int, Tier] = {
    0: Tier(0, "none", "no tests needed; read the diff"),
    1: Tier(1, "smoke", "syntax/lint check + browser or render smoke test"),
    2: Tier(2, "targeted", "run the touched module's test file"),
    3: Tier(3, "subsystem", "run the touched subsystem's tests "
                            "(python3 -m unittest tests.test_<subsystem>*)"),
    4: Tier(4, "full", "./danzaboss/run_tests.sh — full suite green"),
    5: Tier(5, "boot", "activate the boot image in a disposable OS_BOOT_TEST repo"),
}

# boot-image surface: files that change what "Who's the Boss?" does at Layer 2
_BOOT_PREFIXES = (
    "danzaboss/product/templates/scaffold/claude/skills/",
    "danzaboss/product/templates/scaffold/claude/agents/",
    "danzaboss/product/templates/scaffold/claude/rules/",
)
# core surfaces where a slip corrupts state or safety: full suite, always
_FULL_MARKERS = ("danzaboss/security/", "danzaboss/kernel/state",
                 "run_tests.sh", "team_state.schema.json")
# subsystems with cross-module blast radius
_SUBSYSTEM_PREFIXES = ("danzaboss/hooks/", "danzaboss/cortex/",
                       "danzaboss/kernel/", "danzaboss/runtime/")
_SUBSYSTEM_FILES = ("danzaboss/cli.py",)
_STATIC_SUFFIXES = (".css", ".html", ".svg", ".png", ".ico")
_DOC_SUFFIXES = (".md", ".rst", ".txt")


def classify_path(path: str) -> int:
    """Tier for a single touched path."""
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    if p.startswith(_BOOT_PREFIXES):
        return 5
    if any(m in p for m in _FULL_MARKERS):
        return 4
    # static/docs outrank subsystem prefixes: a CSS file inside cortex/ui is a
    # smoke-check change, not a subsystem change
    if p.endswith(_STATIC_SUFFIXES) or "/ui/static/" in p:
        return 1
    if p.endswith(_DOC_SUFFIXES) or p.startswith("docs/") or p == "LICENSE":
        return 0
    if p.startswith(_SUBSYSTEM_PREFIXES) or p in _SUBSYSTEM_FILES:
        return 3
    if p.endswith(".py"):
        return 2
    return 1  # unknown non-doc artifact -> at least a smoke look


def recommend_tier(paths: list[str], *, commit_boundary: bool = False) -> Tier:
    """Lowest safe tier for a change set. The recommendation is the MAX of the
    per-path tiers; a commit boundary always demands at least the full suite
    (Tier 4) because commits are the never-regress line."""
    levels = [classify_path(p) for p in paths]
    level = max(levels, default=0)
    if len(paths) > 6 and any(lv in (2, 3) for lv in levels):
        level = max(level, 4)  # broad sweeps across code cannot stay targeted
    if commit_boundary:
        level = max(level, 4)
    return TIERS[level]
