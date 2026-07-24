"""CORTEX-native per-driver context compiler — a thin front-door (C-driver).

An APP_BUILD orchestrator needs each driver to receive a *budgeted, role-specific*
slice of project memory before it starts its task. This module is that front-door
and nothing more: it maps a driver id to a forced intent + a candidate-type
filter, then hands the real work to the existing CORTEX read path
(`quality.build_package` -> intent -> hybrid retrieve -> assemble -> quality
gate). No new memory substrate, no scoring of its own — the assembler already
guarantees the package never exceeds the requested budget.

The `DRIVER_CORTEX` table (salvaged from the retired context/pipeline.py) now
lives in `cortex/budgets.py` — the single budget home since P4 T4 — and is
re-exported here. It is the per-specialist retrieval
profile. Jonathan sees conventions/decisions/impl scoped to his task, Bonnie sees
failure history, Billy sees the security trail; the intent is forced (the driver's
job IS the intent) and the type filter narrows the candidate pool.

Because this is an explicit, on-demand call (like `danza cortex retrieve`) it is
profile-agnostic: it reads no execution profile and injects nothing, so it can
never make an OS_DEV (Layer 0) session "hot". CORTEX runs hot only where the
orchestrator chooses to call it — Layer 2/3 APP_BUILD.

Stdlib only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from .assemble import Package
# Both tables live in budgets.py since P4 T4 (the single budget home);
# re-exported here so existing importers keep working unchanged.
from .budgets import (  # noqa: F401
    DRIVER_BUDGETS, DRIVER_CORTEX, resolve_budget, resolve_policy)
from .quality import build_package, select_adaptive_package
from .store import ObservationStore
from .tokens import est_tokens

# Unknown drivers fall back here: no forced intent (let the classifier decide),
# no type filter (every category is a candidate). Predictable, never a crash.
_FALLBACK = {"intent": None, "types": None}


def default_budget(driver: str) -> int:
    """The role's default context budget; unknown drivers -> generic cap."""
    return resolve_budget(driver)


@dataclass
class DriverContext:
    """A compiled, budget-capped CORTEX package for one driver's task."""
    driver: str
    task: str
    project: str
    intent: str                 # the intent actually used (forced or detected)
    budget: int
    used: int                   # tokens the package actually consumed (<= budget)
    package: Package
    profile_source: str         # "driver_map" | "fallback"
    adaptation: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        """The context block the driver receives — header + package body."""
        head = (f"# CORTEX context for {self.driver} — intent={self.intent}, "
                f"~{self.used}t of {self.budget}t budget")
        body = self.package.render()
        return f"{head}\n{body}" if body else head

    def to_dict(self) -> dict:
        return {
            "driver": self.driver,
            "task": self.task,
            "project": self.project,
            "intent": self.intent,
            "budget": self.budget,
            "used": self.used,
            "profile_source": self.profile_source,
            "adaptation": self.adaptation,
            "notes": self.notes,
            "observations": [
                {"id": i.observation.id, "type": i.observation.type,
                 "title": i.observation.title, "category": i.category,
                 "tokens": i.tokens}
                for i in self.package.items],
            "render": self.render(),
        }


def replaced_tokens(ctx: DriverContext) -> int:
    """Estimated cost of the manual lookup ``ctx.package`` spared the caller
    (P4.1 T9 savings-meter telemetry): for each injected observation, what
    ``danza cortex get <id>`` would return in full (every field, not just
    the condensed/possibly-compressed package text actually injected) —
    the "before this brief existed" cost the turnbrief docstring describes
    as hand-running CORTEX lookups one at a time. Estimated with the same
    calibrated ``est_tokens`` heuristic as every other CORTEX token
    accounting call, never a fixed multiplier."""
    total = 0
    for item in ctx.package.items:
        raw = json.dumps(item.observation.to_row(), sort_keys=True)
        total += est_tokens(raw, kind="json")
    return total


def driver_profile(driver: str) -> tuple[dict, str]:
    """Resolve a driver's retrieval profile; unknown -> predictable fallback."""
    prof = DRIVER_CORTEX.get(driver)
    return (prof, "driver_map") if prof is not None else (_FALLBACK, "fallback")


def compile_driver_context(store: ObservationStore, driver: str, task: str,
                           project: str, budget: Optional[int] = None, *,
                           workspace=None, graph=None) -> DriverContext:
    """Compile a budget-capped, role-specific CORTEX package for `driver`.

    A thin wrapper over the real read path: pick the driver profile, force its
    intent, narrow to its types, and let `build_package` do intent detection,
    hybrid retrieval, budgeted assembly and the single quality re-plan.
    `budget=None` resolves the driver's role default via `default_budget`.
    """
    policy = resolve_policy(driver)
    explicit = budget is not None
    selected_budget = budget if explicit else policy.base
    prof, source = driver_profile(driver)
    bundle = build_package(store, task, project, budget=selected_budget,
                           types=prof["types"],
                           intent_override=prof["intent"],
                           workspace=workspace, graph=graph)
    if explicit:
        adaptation = {
            "requested_budget": selected_budget,
            "policy_base": policy.base,
            "policy_ceiling": policy.ceiling,
            "explicit_budget": True,
            "selected_mode": "explicit",
            "initial_budget": selected_budget,
            "initial_used": bundle.package.used,
            "base_used": None,
            "base_consumed_85_percent": None,
            "pressure_reasons": [],
            "expansion_considered": False,
            "expansion_qualified": False,
            "expansion_attempted": False,
            "expansion_accepted": False,
            "base_relevance": bundle.report.relevance,
            "base_coverage": bundle.report.coverage,
            "candidate": None,
            "new_top_five_ids": [],
            "acceptance_reason": "explicit_budget_bypass",
            "selected_budget": selected_budget,
            "selected_used": bundle.package.used,
        }
    else:
        selection = select_adaptive_package(
            bundle, base_budget=policy.base, ceiling=policy.ceiling)
        bundle = selection.bundle
        adaptation = selection.evidence
        selected_budget = adaptation["selected_budget"]
    return DriverContext(
        driver=driver, task=task, project=project,
        intent=bundle.intent.name, budget=selected_budget,
        used=bundle.package.used, package=bundle.package,
        profile_source=source, adaptation=adaptation,
        notes=list(bundle.notes))
