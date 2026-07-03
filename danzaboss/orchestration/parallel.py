"""Parallel dispatch planner — DANZABOSS Upgrade #9.

Decides which tasks may run in parallel and which must be serial. Follows the
Anthropic orchestrator-worker lesson: fan out *independent* work, but keep tasks
serial when they share context or have dependencies (multi-agent is a bad fit
when agents must coordinate closely).

Pure planning logic — it produces execution "waves" (batches). The caller then
dispatches each wave; within a wave tasks are independent and safe to run at once.
This is deterministic and unit-testable; it does not itself spawn anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class PTask:
    id: str
    depends_on: list[str] = field(default_factory=list)
    # resources a task touches; two tasks sharing a writeable resource must not
    # run in the same wave (prevents write conflicts / shared-context failure).
    writes: frozenset[str] = frozenset()
    verifiable: bool = True


class DependencyError(Exception):
    pass


def plan_waves(tasks: Iterable[PTask], *, max_parallel: int = 4) -> list[list[str]]:
    """Return a list of waves (each a list of task ids) respecting:
      1. dependency order (a task runs only after its deps),
      2. write-conflict isolation (no two tasks in a wave write the same resource),
      3. verifiability (unverifiable tasks are never dispatched — Upgrade #4),
      4. a max fan-out cap (bounded parallelism — cost control).
    Raises DependencyError on unknown deps or cycles.
    """
    tasks = list(tasks)
    by_id = {t.id: t for t in tasks}

    for t in tasks:
        if not t.verifiable:
            raise DependencyError(f"task {t.id!r} is not verifiable; decompose first")
        for d in t.depends_on:
            if d not in by_id:
                raise DependencyError(f"task {t.id!r} depends on unknown {d!r}")

    done: set[str] = set()
    waves: list[list[str]] = []
    remaining = set(by_id)

    while remaining:
        # candidates: all deps satisfied
        ready = [tid for tid in remaining
                 if all(d in done for d in by_id[tid].depends_on)]
        if not ready:
            raise DependencyError("dependency cycle detected among: "
                                  + ", ".join(sorted(remaining)))
        ready.sort()  # deterministic ordering

        wave: list[str] = []
        wave_writes: set[str] = set()
        for tid in ready:
            if len(wave) >= max_parallel:
                break
            writes = by_id[tid].writes
            if writes & wave_writes:
                continue  # write conflict -> defer to a later wave
            wave.append(tid)
            wave_writes |= writes

        waves.append(wave)
        done |= set(wave)
        remaining -= set(wave)

    return waves


def token_multiplier(waves: list[list[str]]) -> float:
    """Rough cost signal: parallelism trades tokens for wall-clock. Report the
    average fan-out so the orchestrator can decide if the speedup is worth it."""
    if not waves:
        return 0.0
    total = sum(len(w) for w in waves)
    return round(total / len(waves), 2)
