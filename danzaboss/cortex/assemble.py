"""Context assembler — per-intent category budgets + marginal-value trim (C3).

The heart of the read path (spec §6.12/§9): given the fused retrieval ranking
and a token budget, decide how much of each *category* of memory to include —
dynamically, never fixed. Categories group observation types; each intent
carries a fraction table (the spec §9 budget matrix expressed as data). Pass 1
fills each category up to its allocation in fused-score order, compressing
entries that almost fit; pass 2 redistributes whatever budget is left to the
highest-value remaining items regardless of category (marginal value beats a
rigid quota). Everything skipped is recorded with a reason — the assembler
never silently drops.

Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .compress import MIN_ENTRY_TOKENS, compress_entry, entry_text
from .inject import est_tokens
from .observation import Observation
from .retrieve import RetrievedItem

# Observation types grouped into budget categories.
CATEGORY_TYPES: dict[str, set[str]] = {
    "diagnostics": {"bug_fix", "root_cause", "limitation"},
    "code": {"impl_detail", "convention", "api_behavior"},
    "architecture": {"decision", "milestone"},
    "operations": {"performance", "dependency", "security"},
    "knowledge": {"lesson"},
}
TYPE_CATEGORY: dict[str, str] = {
    t: cat for cat, types in CATEGORY_TYPES.items() for t in types}

# Spec §9 as data: fractions of the working budget per category, per intent.
# Rows sum to 1.0; GENERAL splits evenly.
BUDGET_FRACTIONS: dict[str, dict[str, float]] = {
    "fix_bug":      {"diagnostics": .40, "code": .25, "architecture": .10, "operations": .15, "knowledge": .10},
    "write_code":   {"diagnostics": .15, "code": .40, "architecture": .20, "operations": .15, "knowledge": .10},
    "explain":      {"diagnostics": .10, "code": .30, "architecture": .30, "operations": .10, "knowledge": .20},
    "refactor":     {"diagnostics": .20, "code": .35, "architecture": .25, "operations": .10, "knowledge": .10},
    "architecture": {"diagnostics": .10, "code": .15, "architecture": .40, "operations": .20, "knowledge": .15},
    "docs":         {"diagnostics": .10, "code": .25, "architecture": .25, "operations": .10, "knowledge": .30},
    "testing":      {"diagnostics": .35, "code": .25, "architecture": .10, "operations": .15, "knowledge": .15},
    "deploy":       {"diagnostics": .20, "code": .15, "architecture": .20, "operations": .35, "knowledge": .10},
    "performance":  {"diagnostics": .25, "code": .20, "architecture": .10, "operations": .40, "knowledge": .05},
    "security":     {"diagnostics": .20, "code": .10, "architecture": .20, "operations": .40, "knowledge": .10},
    "planning":     {"diagnostics": .10, "code": .15, "architecture": .35, "operations": .15, "knowledge": .25},
    "learning":     {"diagnostics": .10, "code": .20, "architecture": .20, "operations": .10, "knowledge": .40},
}
_EVEN = {cat: 1.0 / len(CATEGORY_TYPES) for cat in CATEGORY_TYPES}


def budget_fractions(intent_name: str) -> dict[str, float]:
    return dict(BUDGET_FRACTIONS.get(intent_name, _EVEN))


@dataclass
class PackageItem:
    observation: Observation
    category: str
    text: str
    tokens: int
    compressed: bool = False
    final: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass
class Package:
    intent: str
    budget: int
    used: int = 0
    items: list[PackageItem] = field(default_factory=list)
    allocation: dict[str, int] = field(default_factory=dict)
    dropped: list[dict] = field(default_factory=list)   # {id, title, reason}

    def render(self) -> str:
        """The actual context block an agent receives."""
        if not self.items:
            return ""
        head = (f"[CORTEX package] intent={self.intent} — {len(self.items)} "
                f"observations, ~{self.used}t of {self.budget}t budget")
        return "\n".join([head] + [i.text for i in self.items])


def assemble(items: list[RetrievedItem], intent_name: str, budget: int,
             *, drop_categories: frozenset[str] = frozenset()) -> Package:
    """Allocate budget across categories, fill in fused order, redistribute."""
    fractions = {c: f for c, f in budget_fractions(intent_name).items()
                 if c not in drop_categories}
    total_frac = sum(fractions.values()) or 1.0
    allocation = {c: int(budget * f / total_frac) for c, f in fractions.items()}

    pkg = Package(intent=intent_name, budget=budget, allocation=allocation)
    spent: dict[str, int] = {c: 0 for c in allocation}
    deferred: list[RetrievedItem] = []

    # pass 1 — category quotas, fused-score order
    for item in items:
        o = item.observation
        cat = TYPE_CATEGORY.get(o.type, "knowledge")
        if cat in drop_categories:
            pkg.dropped.append({"id": o.id, "title": o.title,
                                "reason": f"category '{cat}' dropped by re-plan"})
            continue
        room = allocation[cat] - spent[cat]
        if room < MIN_ENTRY_TOKENS:
            deferred.append(item)
            continue
        text, compressed = compress_entry(o, room)
        cost = est_tokens(text)
        if cost > room:
            deferred.append(item)
            continue
        spent[cat] += cost
        pkg.items.append(PackageItem(
            observation=o, category=cat, text=text, tokens=cost,
            compressed=compressed, final=item.final,
            reasons=item.reasons + [f"category {cat}: {cost}t of "
                                    f"{allocation[cat]}t allocation"
                                    + (" (compressed)" if compressed else "")]))

    # pass 2 — marginal value: leftover budget goes to the best remaining items
    pkg.used = sum(spent.values())
    for item in deferred:
        o = item.observation
        leftover = pkg.budget - pkg.used
        if leftover < MIN_ENTRY_TOKENS:
            pkg.dropped.append({"id": o.id, "title": o.title,
                                "reason": "no budget left"})
            continue
        text, compressed = compress_entry(o, leftover)
        cost = est_tokens(text)
        if cost > leftover:
            pkg.dropped.append({"id": o.id, "title": o.title,
                                "reason": f"floor entry ({cost}t) exceeds "
                                          f"remaining budget ({leftover}t)"})
            continue
        cat = TYPE_CATEGORY.get(o.type, "knowledge")
        pkg.used += cost
        pkg.items.append(PackageItem(
            observation=o, category=cat, text=text, tokens=cost,
            compressed=compressed, final=item.final,
            reasons=item.reasons + [f"category {cat}: {cost}t from "
                                    "redistributed leftover"
                                    + (" (compressed)" if compressed else "")]))
    return pkg
