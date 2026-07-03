"""Deterministic extractive compression — CORTEX read path, C3 (spec §6.11).

Renders an observation as a context entry and, when it must fit a smaller
budget, trims by dropping the *cheapest-to-lose* parts first: file list, then
evidence, then summary sentences from the end. The title and the reasoning are
NEVER compressed away — the WHY is the whole point of an observation, so the
floor entry is always "title + reasoning" (or title + first summary sentence
when there is no reasoning). LLM compression stays an optional port adapter;
this default keeps the hot path deterministic and offline.

Stdlib only.
"""
from __future__ import annotations

import re

from .inject import est_tokens
from .observation import Observation

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
MIN_ENTRY_TOKENS = 24   # below this an entry stops being useful — don't emit


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE.split(text.strip()) if s]


def _render(o: Observation, summary: str, *, evidence: int, files: int) -> str:
    parts = [f"### {o.title}  ({o.type}, {o.importance}, conf {o.confidence})"]
    if summary:
        parts.append(summary)
    if o.reasoning:
        parts.append(f"Why: {o.reasoning}")
    if evidence and o.evidence:
        parts.extend(f"- {e}" for e in o.evidence[:evidence])
    if files and o.files:
        parts.append("Files: " + ", ".join(o.files[:files]))
    return "\n".join(parts)


def entry_text(o: Observation) -> str:
    """The full, untrimmed context entry for an observation."""
    return _render(o, o.summary, evidence=4, files=4)


def compress_entry(o: Observation, target_tokens: int) -> tuple[str, bool]:
    """Fit an entry into target_tokens by extractive trimming.

    Returns (text, was_compressed). If even the floor exceeds the target the
    floor is returned anyway — the caller decides whether it still fits (see
    assemble.py's MIN allocation handling).
    """
    full = entry_text(o)
    if est_tokens(full) <= target_tokens:
        return full, False

    # ladder 1: drop files, then evidence
    for ev, fi in ((4, 0), (2, 0), (0, 0)):
        text = _render(o, o.summary, evidence=ev, files=fi)
        if est_tokens(text) <= target_tokens:
            return text, True

    # ladder 2: trim summary sentences from the end (keep at least one)
    sents = _sentences(o.summary)
    while len(sents) > 1:
        sents.pop()
        text = _render(o, " ".join(sents), evidence=0, files=0)
        if est_tokens(text) <= target_tokens:
            return text, True

    # floor: title + reasoning verbatim (reasoning is never sacrificed);
    # without reasoning, title + first summary sentence.
    floor_summary = "" if o.reasoning else (sents[0] if sents else o.summary)
    return _render(o, floor_summary, evidence=0, files=0), True
