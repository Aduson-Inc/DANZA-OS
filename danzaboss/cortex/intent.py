"""Deterministic intent classifier — CORTEX read path, C3 (spec section 6.1).

Classifies a prompt into one of 12 intents using keyword/phrase scoring plus
workspace signals (branch name, recent tool mix). No LLM on the hot path: the
same prompt + workspace always yields the same intent, so retrieval is
unit-testable and explainable. Unknown prompts fall back to the balanced
"general" profile — RRF simply weights every signal evenly.

Each intent binds a signal-weight profile (used by retrieve.py's RRF fusion);
the matching budget profile lives in assemble.py.

Stdlib only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

_WORD = re.compile(r"[a-z0-9_]+")

INTENTS = ("fix_bug", "write_code", "explain", "refactor", "architecture",
           "docs", "testing", "deploy", "performance", "security",
           "planning", "learning")
GENERAL = "general"  # fallback profile, not one of the 12

# Single words match on token membership; phrases (with a space) match on
# substring and score double — a phrase is a stronger signal than a word.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fix_bug": ("fix", "bug", "broken", "error", "crash", "fails", "failing",
                "regression", "traceback", "exception", "debug", "not working"),
    "write_code": ("build", "implement", "add", "create", "write", "feature",
                   "wire", "new endpoint", "new module"),
    "explain": ("explain", "understand", "how does", "what is", "why does",
                "where is", "walk me through", "what happens"),
    "refactor": ("refactor", "cleanup", "restructure", "simplify", "rename",
                 "extract", "dedupe", "clean up", "tech debt"),
    "architecture": ("architecture", "design", "structure", "blueprint", "adr",
                     "module boundaries", "system map"),
    "docs": ("document", "docs", "readme", "changelog", "docstring",
             "documentation", "write up"),
    "testing": ("test", "tests", "coverage", "assert", "verify", "qa",
                "unit test", "test suite"),
    "deploy": ("deploy", "release", "ship", "rollout", "publish", "docker",
               "vps", "ci pipeline"),
    "performance": ("performance", "slow", "latency", "optimize", "profile",
                    "throughput", "speed up", "memory usage"),
    "security": ("security", "auth", "vulnerability", "cve", "owasp", "secret",
                 "injection", "xss", "permission", "token leak"),
    "planning": ("plan", "roadmap", "milestone", "prioritize", "scope",
                 "backlog", "next steps", "estimate"),
    "learning": ("lesson", "learned", "retrospective", "postmortem",
                 "best practice", "pattern"),
}

# Branch-name prefixes are a cheap, honest workspace signal.
_BRANCH_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("fix/", "bug/", "hotfix/"), "fix_bug"),
    (("feat/", "feature/"), "write_code"),
    (("perf/",), "performance"),
    (("sec/", "security/"), "security"),
    (("docs/", "doc/"), "docs"),
    (("test/", "tests/"), "testing"),
    (("refactor/", "chore/"), "refactor"),
    (("release/", "deploy/"), "deploy"),
)

# Per-intent RRF signal weights (retrieve.py). Only overrides are listed;
# everything else inherits the balanced default. Rationale mirrors spec §6.1:
# security leans on tags/links (graph binds in C4), explain leans on lexical
# match, fix_bug on when_relevant precision + freshness.
DEFAULT_WEIGHTS: dict[str, float] = {
    "fts": 1.0, "tags": 0.8, "when_relevant": 1.0, "recency": 0.6,
    "importance": 0.6, "usage": 0.4, "links": 0.5, "graph": 0.8,
}

_WEIGHT_OVERRIDES: dict[str, dict[str, float]] = {
    "fix_bug": {"fts": 1.2, "when_relevant": 1.2, "recency": 0.9, "links": 0.7},
    "write_code": {"tags": 1.0, "importance": 0.7},
    "explain": {"fts": 1.3, "tags": 1.0, "recency": 0.4},
    "refactor": {"tags": 1.0, "links": 0.8},
    "architecture": {"importance": 1.0, "links": 0.9, "graph": 1.2},
    "docs": {"fts": 1.1, "recency": 0.5},
    "testing": {"when_relevant": 1.2, "fts": 1.1},
    "deploy": {"recency": 1.0, "importance": 0.8},
    "performance": {"fts": 1.1, "usage": 0.6, "recency": 0.8},
    "security": {"tags": 1.2, "links": 1.0, "graph": 1.4, "importance": 1.0},
    "planning": {"importance": 1.0, "recency": 0.8, "usage": 0.6},
    "learning": {"usage": 0.8, "importance": 0.8},
}


def signal_weights(intent_name: str) -> dict[str, float]:
    """The RRF weight vector for an intent; GENERAL/unknown -> balanced."""
    weights = dict(DEFAULT_WEIGHTS)
    weights.update(_WEIGHT_OVERRIDES.get(intent_name, {}))
    return weights


@dataclass
class WorkspaceState:
    """Cheap live-workspace snapshot (L0) feeding intent detection."""
    branch: str = ""
    recent_tools: list[str] = field(default_factory=list)
    recent_commands: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)


@dataclass
class Intent:
    name: str
    score: float                       # winning raw score (0 = fallback)
    matched: list[str] = field(default_factory=list)  # explainability
    terms: set[str] = field(default_factory=set)      # prompt tokens (anti-relevance)

    @property
    def weights(self) -> dict[str, float]:
        return signal_weights(self.name)


def tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def detect(prompt: str, workspace: Optional[WorkspaceState] = None) -> Intent:
    """Score every intent; highest wins, zero everywhere -> GENERAL.

    Ties break by INTENTS declaration order so detection is fully deterministic.
    """
    low = prompt.lower()
    toks = tokens(prompt)
    scores: dict[str, float] = {name: 0.0 for name in INTENTS}
    matched: dict[str, list[str]] = {name: [] for name in INTENTS}

    for name, keys in _KEYWORDS.items():
        for key in keys:
            if " " in key:
                if key in low:
                    scores[name] += 2.0
                    matched[name].append(f'phrase "{key}"')
            elif key in toks:
                scores[name] += 1.0
                matched[name].append(f'keyword "{key}"')

    if workspace:
        branch = workspace.branch.lower()
        for prefixes, name in _BRANCH_HINTS:
            if any(branch.startswith(p) for p in prefixes):
                scores[name] += 2.0
                matched[name].append(f'branch "{workspace.branch}"')
        edits = sum(1 for t in workspace.recent_tools if t in ("Edit", "Write"))
        if edits >= 3:
            scores["write_code"] += 1.0
            matched["write_code"].append(f"tool mix: {edits} recent edits")
        test_cmds = sum(1 for c in workspace.recent_commands
                        if "test" in c or "pytest" in c)
        if test_cmds >= 2:
            scores["testing"] += 1.0
            matched["testing"].append(f"tool mix: {test_cmds} test commands")

    best = max(INTENTS, key=lambda n: scores[n])
    if scores[best] <= 0:
        return Intent(name=GENERAL, score=0.0,
                      matched=["no intent signal — balanced profile"], terms=toks)
    return Intent(name=best, score=scores[best], matched=matched[best], terms=toks)
