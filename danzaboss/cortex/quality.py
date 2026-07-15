"""Package quality gate + the retrieval pipeline entry point — C3 (spec §6.14).

Scores every assembled package on relevance / coverage / redundancy /
token-efficiency. A package below threshold triggers exactly ONE re-plan
(Rule 18 spirit — no unbounded loops): widen retrieval and drop the weakest
category, then ship whichever attempt scored higher. build_package() is the
static retrieval/quality path shared by generic callers and the driver-context
base attempt. Only the driver front-door may pass its selected result into the
separate one-candidate adaptive comparison below.

Threshold is deliberately modest (set empirically per spec §16 Q5); it exists
to catch degenerate packages (nothing relevant, all duplicates), not to
perfectionist-loop.

Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .assemble import Package, TYPE_CATEGORY, assemble, budget_fractions
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


@dataclass
class AdaptiveSelection:
    """The selected bundle plus stable evidence for the budget decision."""
    bundle: PackageBundle
    evidence: dict


def _item_terms(item) -> set[str]:
    o = item.observation
    return (tokens(o.title) | tokens(o.summary)
            | {t.lower() for t in o.tags} | {c.lower() for c in o.concepts})


def _top_categories(intent_name: str) -> list[str]:
    return [cat for cat, _ in sorted(
        budget_fractions(intent_name).items(), key=lambda kv: -kv[1])[:3]]


def expansion_pressure(bundle: PackageBundle) -> list[str]:
    """Return only objective pressure signals from the selected base bundle."""
    reasons: list[str] = []
    by_id = {item.observation.id: item for item in bundle.retrieval.items}
    for dropped in bundle.package.dropped:
        item = by_id.get(dropped.get("id"))
        if item is not None and bundle.intent.terms & _item_terms(item):
            reasons.append("dropped_relevant")
            break

    present = {item.category for item in bundle.package.items}
    candidate_categories = {
        TYPE_CATEGORY.get(item.observation.type, "knowledge")
        for item in bundle.retrieval.items
    }
    if any(cat not in present and cat in candidate_categories
           for cat in _top_categories(bundle.intent.name)):
        reasons.append("missing_required_category")
    return reasons


def compare_expansion(base: QualityReport, candidate: QualityReport,
                      new_top_five_ids: list[str]) -> tuple[bool, str]:
    """Apply the binding relevance/coverage/high-rank acceptance rule."""
    if candidate.relevance < base.relevance:
        return False, "relevance_decreased"
    if candidate.coverage > base.coverage:
        return True, "coverage_improved"
    if new_top_five_ids:
        return True, "high_rank_context_admitted"
    return False, "no_accepted_improvement"


def select_adaptive_package(base: PackageBundle, *, base_budget: int,
                            ceiling: int) -> AdaptiveSelection:
    """Select base or one ceiling reassembly without performing retrieval."""
    saturated = base.package.used * 100 >= base_budget * 85
    pressure = expansion_pressure(base)
    evidence = {
        "requested_budget": None,
        "policy_base": base_budget,
        "policy_ceiling": ceiling,
        "explicit_budget": False,
        "selected_mode": "base",
        "initial_budget": base_budget,
        "initial_used": base.package.used,
        "base_used": base.package.used,
        "base_consumed_85_percent": saturated,
        "pressure_reasons": pressure,
        "expansion_considered": True,
        "expansion_qualified": saturated and bool(pressure),
        "expansion_attempted": False,
        "expansion_accepted": False,
        "base_relevance": base.report.relevance,
        "base_coverage": base.report.coverage,
        "candidate": None,
        "new_top_five_ids": [],
        "acceptance_reason": "below_85_percent" if not saturated
                             else "no_qualified_pressure",
        "selected_budget": base_budget,
        "selected_used": base.package.used,
    }
    if not evidence["expansion_qualified"]:
        return AdaptiveSelection(base, evidence)

    candidate_package = assemble(
        base.retrieval.items, base.intent.name, ceiling)
    candidate_report = score_package(candidate_package, base.intent)
    base_ids = {item.observation.id for item in base.package.items}
    candidate_ids = {item.observation.id for item in candidate_package.items}
    new_top_five_ids = [
        item.observation.id for item in base.retrieval.items[:5]
        if item.observation.id in candidate_ids
        and item.observation.id not in base_ids
    ]
    accepted, reason = compare_expansion(
        base.report, candidate_report, new_top_five_ids)
    evidence.update({
        "expansion_attempted": True,
        "expansion_accepted": accepted,
        "candidate": {
            "budget": ceiling,
            "used": candidate_package.used,
            "relevance": candidate_report.relevance,
            "coverage": candidate_report.coverage,
        },
        "new_top_five_ids": new_top_five_ids,
        "acceptance_reason": reason,
    })
    if not accepted:
        return AdaptiveSelection(base, evidence)

    candidate = PackageBundle(
        prompt=base.prompt,
        intent=base.intent,
        retrieval=base.retrieval,
        package=candidate_package,
        report=candidate_report,
        replanned=base.replanned,
        notes=list(base.notes) + [f"adaptive expansion accepted: {reason}"],
    )
    evidence.update({
        "selected_mode": "expanded",
        "selected_budget": ceiling,
        "selected_used": candidate_package.used,
    })
    return AdaptiveSelection(candidate, evidence)


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
                  threshold: float = DEFAULT_THRESHOLD,
                  graph=None) -> PackageBundle:
    """intent -> hybrid retrieve -> assemble -> quality gate -> one re-plan."""
    intent = detect(prompt, workspace)
    if intent_override:
        intent = Intent(name=intent_override, score=intent.score,
                        matched=intent.matched + [f"intent forced: {intent_override}"],
                        terms=intent.terms)

    retrieval = hybrid_retrieve(store, prompt, intent, project,
                                limit=limit, types=types, workspace=workspace,
                                graph=graph)
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
                                 workspace=workspace, graph=graph)
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
