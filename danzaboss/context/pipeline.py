"""Context-engineering pipeline — DANZABOSS Upgrade #8.

Each driver gets an isolated, *compiled* working context assembled from the
memory subsystem through a named processor pipeline (select -> compress ->
isolate), instead of the orchestrator hand-pasting whatever it happened to
remember into each sub-agent prompt (the Phase-1 "prompt boundary" info-loss risk).

Mirrors the three-tier context stack pattern: storage (MemoryStore) -> processor
pipeline (this module) -> compiled working context (what the model actually sees).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from danzaboss.memory.store import MemoryStore, MemoryRecord
# Table data only (not the store) — the single budget home since P4 T4, so the
# per-driver retrieval profile can never diverge from cortex/ again. A
# module-level import is acceptable here for plain dicts; context/ still has
# no hard import edge onto the cortex store itself.
from danzaboss.cortex.budgets import DRIVER_CORTEX


@dataclass
class CompiledContext:
    driver: str
    task_id: str
    sections: dict[str, str] = field(default_factory=dict)
    est_tokens: int = 0

    def render(self) -> str:
        parts = [f"# Context for {self.driver} — task {self.task_id}"]
        for name, body in self.sections.items():
            parts.append(f"\n## {name}\n{body}")
        return "\n".join(parts)


# A processor takes (records, budget) and returns (possibly transformed records).
Processor = Callable[[list[MemoryRecord], int], list[MemoryRecord]]


def select_relevant(store: MemoryStore, query: str, budget: int) -> list[MemoryRecord]:
    """Stage 1 — selection. Pull only records relevant to this task."""
    return store.retrieve(query, token_budget=budget, max_records=30)


def compress(records: list[MemoryRecord], budget: int) -> list[MemoryRecord]:
    """Stage 2 — compression. Drop near-duplicate records (same tag-set + prefix)
    so we don't spend budget on repeats. Deterministic."""
    seen: set[tuple] = set()
    out: list[MemoryRecord] = []
    for rec in records:
        key = (tuple(sorted(rec.tags)), rec.text[:60])
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


def isolate(records: list[MemoryRecord], budget: int) -> list[MemoryRecord]:
    """Stage 3 — isolation. Enforce the hard token budget as a final trim so the
    compiled context can never exceed what the driver can hold."""
    out, used = [], 0
    for rec in records:
        if used + rec.est_tokens() > budget:
            break
        out.append(rec)
        used += rec.est_tokens()
    return out


# Per-driver relevance profiles: which scopes and default queries matter to each
# specialist. Keeps each driver's context tight and on-topic.
DRIVER_PROFILES: dict[str, dict] = {
    "jonathan-builder":     {"scopes": ("semantic", "procedural"), "hint": "code style patterns build order"},
    "samantha-mapper":      {"scopes": ("semantic", "episodic"),   "hint": "structure dependencies routes schema"},
    "angela-auditor":       {"scopes": ("episodic", "procedural"), "hint": "decisions alerts loops violations"},
    "bonnie-qa":            {"scopes": ("semantic", "episodic"),   "hint": "tests verification edge cases regressions"},
    "carmella-researcher":  {"scopes": ("semantic",),              "hint": "api external standards research"},
    "hank-designer":        {"scopes": ("semantic", "procedural"), "hint": "design tokens colors fonts templates"},
    "billy-security":       {"scopes": ("semantic", "procedural"), "hint": "owasp auth secrets dependency"},
}


class ContextPipeline:
    def __init__(self, store: MemoryStore, processors: Optional[list[Processor]] = None,
                 cortex_store=None, project: str = ""):
        self.store = store
        # default pipeline: compress then isolate (selection is the store query)
        self.processors: list[Processor] = processors or [compress, isolate]
        # optional CORTEX source (C3): an ObservationStore bound to this repo.
        # Kept duck-typed so context/ has no hard import edge onto cortex/.
        self.cortex_store = cortex_store
        self.project = project

    def compile(self, driver: str, task_id: str, task_desc: str,
                token_budget: int = 1200, cortex_budget: int = 600) -> CompiledContext:
        profile = DRIVER_PROFILES.get(driver, {"scopes": None, "hint": ""})
        query = f"{task_desc} {profile['hint']}".strip()
        scopes = profile["scopes"]
        records = (self.store.retrieve(query, scopes=scopes, token_budget=token_budget * 2, max_records=40)
                   if scopes else select_relevant(self.store, query, token_budget * 2))
        for proc in self.processors:
            records = proc(records, token_budget)

        ctx = CompiledContext(driver=driver, task_id=task_id)
        body = "\n".join(f"- {r.text}" for r in records) or "- (no relevant memory yet)"
        ctx.sections["Relevant memory"] = body
        ctx.sections["Task"] = task_desc
        ctx.est_tokens = sum(r.est_tokens() for r in records) + max(1, len(task_desc) // 4)
        if self.cortex_store is not None:
            self._add_cortex_section(ctx, driver, task_desc, cortex_budget)
        return ctx

    def _add_cortex_section(self, ctx: CompiledContext, driver: str,
                            task_desc: str, cortex_budget: int) -> None:
        """Retrieve a per-driver CORTEX package through the real C3 pipeline."""
        from danzaboss.cortex.quality import build_package  # lazy: optional source
        cprofile = DRIVER_CORTEX.get(driver, {"intent": None, "types": None})
        bundle = build_package(self.cortex_store, task_desc, self.project,
                               budget=cortex_budget,
                               types=cprofile["types"],
                               intent_override=cprofile["intent"])
        rendered = bundle.package.render()
        if rendered:
            ctx.sections["CORTEX observations"] = rendered
            ctx.est_tokens += bundle.package.used
