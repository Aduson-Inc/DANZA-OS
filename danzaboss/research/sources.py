"""Multi-source collector — DANZA research intake.

Honest design note: for cutting-edge technical research, YouTube alone underperforms
(video lags written sources). So YouTube is ONE lane among several written lanes.
Each lane is a swappable port; live lanes need network/keys and are labelled. The
collector's job is to hand back the NEWEST, deduped, ranked source URLs for a topic —
it does NOT read them. Reading is delegated to a Summarizer (NotebookLM etc.).
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass
class Source:
    url: str
    title: str = ""
    lane: str = ""                 # web | youtube | github | rss | arxiv
    published: Optional[str] = None  # ISO date if known
    signal: float = 0.0            # lane-provided quality hint (views, stars, etc.)


class SourceLane(Protocol):
    """A single intake lane. Live adapters (network/keys) implement fetch();
    tests inject a StubLane. All are swappable."""
    name: str
    def fetch(self, topic: str, since_days: int) -> list[Source]: ...


class StubLane:
    """Deterministic lane for tests / offline dev."""
    def __init__(self, name: str, items: list[Source]):
        self.name = name
        self._items = items
    def fetch(self, topic: str, since_days: int) -> list[Source]:
        return list(self._items)


# --- live lane adapters (documented; require network/keys — NOT run in tests) ---
# Kept as thin, clearly-labelled stubs so the framework is complete and the
# integration surface is explicit. Each returns [] until wired with credentials.
class WebSearchLane:
    """Uses a web-search API (Brave/Tavily/Exa/etc.). Needs an API key."""
    name = "web"
    def __init__(self, api=None): self.api = api
    def fetch(self, topic, since_days):  # pragma: no cover - needs network/key
        return [] if self.api is None else self.api.search(topic, since_days)

class YouTubeLane:
    """Wraps the existing tools/research-pipeline/yt_search.py. One lane, not the star."""
    name = "youtube"
    def __init__(self, runner=None): self.runner = runner
    def fetch(self, topic, since_days):  # pragma: no cover - needs yt_dlp/network
        return [] if self.runner is None else self.runner(topic, since_days)

class GithubReleasesLane:
    name = "github"
    def __init__(self, api=None): self.api = api
    def fetch(self, topic, since_days):  # pragma: no cover
        return [] if self.api is None else self.api.releases(topic, since_days)


def _recency_score(src: Source, now: _dt.datetime) -> float:
    if not src.published:
        return 0.3  # unknown date -> mild penalty
    try:
        pub = _dt.datetime.fromisoformat(src.published.replace("Z", "+00:00"))
    except ValueError:
        return 0.3
    age_days = max(0.0, (now - pub.replace(tzinfo=None)).days)
    return 1.0 / (1.0 + age_days / 30.0)  # ~1.0 today, decays over weeks


class MultiSourceCollector:
    """Fuses lanes, dedupes by URL, ranks NEWEST-first (recency dominant, signal tiebreak)."""

    def __init__(self, lanes: list[SourceLane]):
        self.lanes = lanes

    def collect(self, topic: str, *, since_days: int = 30, limit: int = 15,
                now: Optional[_dt.datetime] = None) -> list[Source]:
        now = now or _dt.datetime.utcnow()
        seen: dict[str, Source] = {}
        for lane in self.lanes:
            for src in lane.fetch(topic, since_days):
                if not src.lane:
                    src.lane = lane.name
                if src.url not in seen:
                    seen[src.url] = src
        ranked = sorted(
            seen.values(),
            key=lambda s: (_recency_score(s, now), s.signal),
            reverse=True)
        return ranked[:limit]
