"""Summarizer port — the 'hand sources off, read only the result' step.

DANZA does NOT read the sources. It hands URLs + a research brief to a Summarizer,
which does the heavy reading (its tokens, not Claude's) and returns a distilled
result. NotebookLM is the default adapter, but because that automation is unofficial
and fragile, the summarizer is a SWAPPABLE PORT — swap in a paid API or local
summarizer if NotebookLM breaks. This is the token-economics win: ~0 to collect,
~1500 to read the distilled answer instead of 100K+ to read sources.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .sources import Source


@dataclass
class ResearchResult:
    topic: str
    findings: list[str]                 # distilled, actionable
    improvements: list[str]             # concrete proposed upgrades
    source_count: int = 0
    notebook_id: str = ""
    provider: str = ""


class Summarizer(Protocol):
    def summarize(self, topic: str, sources: list[Source], brief: str) -> ResearchResult: ...


class NotebookLMSummarizer:
    """Default adapter — wraps the notebooklm CLI/skill already in the repo.
    UNVERIFIED here (needs Google auth); labelled as the integration surface."""
    provider = "notebooklm"
    def __init__(self, cli=None):
        self.cli = cli
    def summarize(self, topic, sources, brief) -> ResearchResult:  # pragma: no cover - needs auth
        if self.cli is None:
            raise RuntimeError("NotebookLM CLI not configured (needs Google auth). "
                               "Swap in another Summarizer adapter or provide cli.")
        return self.cli.research(topic, [s.url for s in sources], brief)


class StubSummarizer:
    """Deterministic summarizer for tests / offline — proves the pipeline shape."""
    provider = "stub"
    def summarize(self, topic, sources, brief) -> ResearchResult:
        return ResearchResult(
            topic=topic,
            findings=[f"{len(sources)} sources reviewed for {topic}"],
            improvements=[f"proposed upgrade for {topic} (from {sources[0].lane})"] if sources else [],
            source_count=len(sources), provider=self.provider)
