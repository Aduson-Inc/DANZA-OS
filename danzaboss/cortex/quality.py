"""Package quality gate + the retrieval pipeline entry point — C3 (spec §6.14).

Scores every assembled package on relevance / coverage / redundancy /
token-efficiency. A package below threshold triggers exactly ONE re-plan
(Rule 18 spirit — no unbounded loops): widen retrieval and drop the weakest
category, then ship whichever attempt scored higher. build_package() is the
single function the CLI, the UI explain endpoint, and the per-driver context
pipeline all call — one code path, one behaviour.

Threshold is deliberately modest (set empirically per spec §16 Q5); it exists
to catch degenerate packages (nothing relevant, all duplicates), not to
perfectionist-loop.

Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .assemble import Package, assemble, budget_fractions
from .intent import GENERAL, Intent, WorkspaceState, detect, tokens
from .retrieve import RetrievalResult, hybrid_retrieve
from .store import ObservationStore

DEFAULT_THRESHOLD = 0.35
_WEIGHTS = {"relevance": 0.40, "coverage": 0.25,
            "redundancy": 0.20, "efficiency": 0.15}


@dataclass
class QualityReport:
    relevance: float
    coverage: float
    redundancy: float
    efficiency: float
    overall: float
    passed: bool
    notes: list[str] = field(default_factory=list)


@dataclass
class PackageBundle:
    """Everything one retrieval produced — package plus its full trace."""
    prompt: str
    intent: Intent
    retrieval: RetrievalResult
    package: Package
    report: QualityReport
    replanned: bool = False
    notes: list[str] = field(default_factory=list)


def _item_terms(item) -> set[str]:
    o = item.observation
    return (tokens(o.title) | tokens(o.summary)
            | {t.lower() for t in o.tags} | {c.lower() for c in o.concepts})


def score_package(pkg: Package, intent: Intent,
                  threshold: float = DEFAULT_THRESHOLD) -> QualityReport:
    notes: list[str] = []
    if not pkg.items:
        return QualityReport(0.0, 0.0, 0.0, 0.0, 0.0, passed=False,
                             notes=["empty package"])

    # relevance: fraction of items sharing at least one prompt term
    if intent.terms:
        hits = sum(1 for i in pkg.items if intent.terms & _item_terms(i))
        relevance = hits / len(pkg.items)
    else:
        relevance = 1.0
        notes.append("no prompt terms — relevance vacuous")

    # coverage: of the intent's top-3 budget categories, how many are present
    top = sorted(budget_fractions(pkg.intent).items(),
                 key=lambda kv: -kv[1])[:3]
    present = {i.category for i in pkg.items}
    coverage = sum(1 for cat, _ in top if cat in present) / len(top)

    # redundancy: 1 - mean pairwise jaccard over item term bags (higher = better)
    bags = [_item_terms(i) for i in pkg.items]
    if len(bags) < 2:
        redundancy = 1.0
    else:
        sims, pairs = 0.0, 0
        for a in range(len(bags)):
            for b in range(a + 1, len(bags)):
                union = bags[a] | bags[b]
                sims += len(bags[a] & bags[b]) / len(union) if union else 0.0
                pairs += 1
        redundancy = 1.0 - sims / pairs

    # efficiency: >=60% of the budget spent on accepted items scores full
    efficiency = min(1.0, pkg.used / max(1, pkg.budget * 0.6))

    overall = sum(v * _WEIGHTS[k] for k, v in
                  (("relevance", relevance), ("coverage", coverage),
                   ("redundancy", redundancy), ("efficiency", efficiency)))
    return QualityReport(round(relevance, 3), round(coverage, 3),
                         round(redundancy, 3), round(efficiency, 3),
                         round(overall, 3), passed=overall >= threshold,
                         notes=notes)


def _weakest_category(pkg: Package) -> Optional[str]:
    """The allocated category contributing the least fused value."""
    value: dict[str, float] = {c: 0.0 for c in pkg.allocation}
    for i in pkg.items:
        value[i.category] = value.get(i.category, 0.0) + i.final
    if not value:
        return None
    return min(sorted(value), key=lambda c: value[c])


def build_package(store: ObservationStore, prompt: str, project: str, *,
                  budget: int = 1500, limit: int = 20,
                  types: Optional[list[str]] = None,
                  workspace: Optional[WorkspaceState] = None,
                  intent_override: Optional[str] = None,
                  threshold: float = DEFAULT_THRESHOLD) -> PackageBundle:
    """intent -> hybrid retrieve -> assemble -> quality gate -> one re-plan."""
    intent = detect(prompt, workspace)
    if intent_override:
        intent = Intent(name=intent_override, score=intent.score,
                        matched=intent.matched + [f"intent forced: {intent_override}"],
                        terms=intent.terms)

    retrieval = hybrid_retrieve(store, prompt, intent, project,
                                limit=limit, types=types, workspace=workspace)
    package = assemble(retrieval.items, intent.name, budget)
    report = score_package(package, intent, threshold)
    bundle = PackageBundle(prompt=prompt, intent=intent, retrieval=retrieval,
                           package=package, report=report)
    if report.passed:
        return bundle

    # exactly one re-plan: widen the net, drop the weakest category
    weakest = _weakest_category(package)
    drops = frozenset({weakest}) if weakest else frozenset()
    retrieval2 = hybrid_retrieve(store, prompt, intent, project,
                                 limit=limit * 2, types=types,
                                 workspace=workspace)
    package2 = assemble(retrieval2.items, intent.name, budget,
                        drop_categories=drops)
    report2 = score_package(package2, intent, threshold)

    note = (f"re-planned once: widened limit {limit}->{limit * 2}"
            + (f", dropped weakest category '{weakest}'" if weakest else ""))
    if report2.overall > report.overall:
        return PackageBundle(prompt=prompt, intent=intent, retrieval=retrieval2,
                             package=package2, report=report2, replanned=True,
                             notes=[note, "re-plan improved the package"])
    bundle.replanned = True
    bundle.notes = [note, "re-plan did not improve — shipping first attempt"]
    return bundle
