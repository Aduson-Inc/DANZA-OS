"""Explainability formatting — C3 (spec §6.15).

The pipeline already accumulates reason strings on every item as it flows
(intent matches, per-signal ranks, multipliers, budget placement, kills); this
module only FORMATS that data — as a JSON-able trace for the UI explain
playground and as readable text for the CLI. No scoring logic lives here.

Stdlib only.
"""
from __future__ import annotations

from .quality import PackageBundle


def trace(bundle: PackageBundle) -> dict:
    """Machine-readable trace of one retrieval, for /api/explain and --json."""
    titles = {i.observation.id: i.observation.title
              for i in bundle.retrieval.items}
    for item in bundle.package.items:
        titles[item.observation.id] = item.observation.title
    return {
        "prompt": bundle.prompt,
        "intent": {"name": bundle.intent.name,
                   "score": bundle.intent.score,
                   "matched": bundle.intent.matched,
                   "weights": bundle.intent.weights},
        "signals": {name: ids for name, ids in bundle.retrieval.signals.items()},
        "killed": [{"id": k.observation_id, "title": k.title,
                    "trigger": k.trigger} for k in bundle.retrieval.killed],
        "fusion": [{"id": i.observation.id,
                    "title": i.observation.title,
                    "type": i.observation.type,
                    "fused": round(i.fused, 5),
                    "final": round(i.final, 5),
                    "signal_ranks": i.signal_ranks,
                    "reasons": i.reasons} for i in bundle.retrieval.items],
        "package": {
            "intent": bundle.package.intent,
            "budget": bundle.package.budget,
            "used": bundle.package.used,
            "allocation": bundle.package.allocation,
            "items": [{"id": i.observation.id, "title": i.observation.title,
                       "category": i.category, "tokens": i.tokens,
                       "compressed": i.compressed, "final": round(i.final, 5),
                       "reasons": i.reasons} for i in bundle.package.items],
            "dropped": bundle.package.dropped,
        },
        "quality": {"relevance": bundle.report.relevance,
                    "coverage": bundle.report.coverage,
                    "redundancy": bundle.report.redundancy,
                    "efficiency": bundle.report.efficiency,
                    "overall": bundle.report.overall,
                    "passed": bundle.report.passed,
                    "notes": bundle.report.notes},
        "replanned": bundle.replanned,
        "notes": bundle.notes,
        "titles": titles,
    }


def render(bundle: PackageBundle) -> str:
    """Human-readable retrieval trace for `danza cortex retrieve --explain`."""
    t = trace(bundle)
    lines = [f"prompt: {t['prompt']}",
             f"intent: {t['intent']['name']} (score {t['intent']['score']}) — "
             + "; ".join(t["intent"]["matched"])]

    lines.append("signals:")
    for name, ids in t["signals"].items():
        if not ids:
            lines.append(f"  {name:14s} —")
            continue
        shown = ", ".join(f"{t['titles'].get(i, i)[:40]}" for i in ids[:3])
        more = f" (+{len(ids) - 3} more)" if len(ids) > 3 else ""
        lines.append(f"  {name:14s} {shown}{more}")

    if t["killed"]:
        lines.append("anti-relevance kills:")
        for k in t["killed"]:
            lines.append(f"  x {k['title'][:50]} — triggered by '{k['trigger']}'")

    lines.append("fusion (final ranking):")
    for i, row in enumerate(t["fusion"][:10], start=1):
        ranks = " ".join(f"{s}#{r}" for s, r in sorted(row["signal_ranks"].items()))
        lines.append(f"  {i:2d}. {row['title'][:46]:46s} final={row['final']:.4f} [{ranks}]")

    p = t["package"]
    lines.append(f"package: {len(p['items'])} items, {p['used']}t of {p['budget']}t"
                 f" — allocation {p['allocation']}")
    for item in p["items"]:
        flag = " (compressed)" if item["compressed"] else ""
        lines.append(f"  + [{item['category']}] {item['title'][:46]} "
                     f"{item['tokens']}t{flag}")
    for d in p["dropped"]:
        lines.append(f"  - dropped: {d['title'][:46]} — {d['reason']}")

    q = t["quality"]
    lines.append(f"quality: overall {q['overall']} "
                 f"(rel {q['relevance']} cov {q['coverage']} "
                 f"red {q['redundancy']} eff {q['efficiency']}) "
                 f"{'PASS' if q['passed'] else 'BELOW THRESHOLD'}")
    if t["replanned"]:
        lines.extend(f"note: {n}" for n in t["notes"])
    return "\n".join(lines)
