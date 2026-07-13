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

from dataclasses import dataclass, field
from typing import Optional

from .assemble import Package
# Both tables live in budgets.py since P4 T4 (the single budget home);
# re-exported here so existing importers keep working unchanged.
from .budgets import DRIVER_BUDGETS, DRIVER_CORTEX, resolve_budget  # noqa: F401
from .quality import build_package
from .store import ObservationStore

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
            "notes": self.notes,
            "observations": [
                {"id": i.observation.id, "type": i.observation.type,
                 "title": i.observation.title, "category": i.category,
                 "tokens": i.tokens}
                for i in self.package.items],
            "render": self.render(),
        }


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
    if budget is None:
        budget = default_budget(driver)
    prof, source = driver_profile(driver)
    bundle = build_package(store, task, project, budget=budget,
                           types=prof["types"],
                           intent_override=prof["intent"],
                           workspace=workspace, graph=graph)
    return DriverContext(
        driver=driver, task=task, project=project,
        intent=bundle.intent.name, budget=budget, used=bundle.package.used,
        package=bundle.package, profile_source=source, notes=list(bundle.notes))
