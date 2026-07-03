"""ResearchSquad — the always-on 'research team' (background, throttled).

Per big feature in the App Profile: collect newest sources (multi-lane) -> hand to
the summarizer (NotebookLM/other) which reads them -> turn improvements into
Proposals -> throttle -> send the survivors to you for remote approval.

Entirely app-agnostic: every query and decision is derived from the AppProfile, so
the same squad researches a noise app, a CRM, or anything. Runs off the hot build
path; deep research only for features the profile flags `is_big`.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional

from ..cortex.app_profile import AppProfile
from .sources import MultiSourceCollector
from .summarizer import Summarizer
from .proposal import Proposal
from .throttle import ProposalThrottle
from .messaging import MessagingChannel


@dataclass
class SquadConfig:
    since_days: int = 30
    source_limit: int = 15
    deep_only_big: bool = True     # cheap passes for small features, deep for big


class ResearchSquad:
    def __init__(self, collector: MultiSourceCollector, summarizer: Summarizer,
                 throttle: ProposalThrottle, channel: MessagingChannel,
                 cfg: Optional[SquadConfig] = None):
        self.collector = collector
        self.summarizer = summarizer
        self.throttle = throttle
        self.channel = channel
        self.cfg = cfg or SquadConfig()

    def research_feature(self, profile: AppProfile, feature_name: str) -> list[Proposal]:
        """Collect -> summarize -> draft proposals for one feature. No sending here."""
        topic = profile.research_topic_for(feature_name)
        sources = self.collector.collect(topic, since_days=self.cfg.since_days,
                                          limit=self.cfg.source_limit)
        brief = (f"App domain: {profile.domain}. Feature: {feature_name}. "
                 f"Find the newest, best-practice and cutting-edge improvements. "
                 f"Return concrete, buildable upgrades with rationale.")
        result = self.summarizer.summarize(topic, sources, brief)
        proposals = []
        for imp in result.improvements:
            proposals.append(Proposal(
                feature=feature_name, title=imp[:80], rationale=imp,
                evidence=[s.url for s in sources[:5]],
                impact=_estimate_impact(profile, feature_name)))
        return proposals

    def run_cycle(self, profile: AppProfile, now: Optional[_dt.datetime] = None) -> list[Proposal]:
        """One scheduled cycle across the profile's features. Returns what was sent."""
        now = now or _dt.datetime.utcnow()
        targets = profile.big_features() if self.cfg.deep_only_big else profile.features
        candidates: list[Proposal] = []
        for f in targets:
            candidates.extend(self.research_feature(profile, f.name))
        to_send = self.throttle.select(candidates, now)
        sent = []
        for p in to_send:
            allowed, _ = self.throttle.can_send(p, now)
            if not allowed:
                continue
            p.status = "sent"
            self.channel.send(p)
            self.throttle.record_sent(now)
            sent.append(p)
        return sent


def _estimate_impact(profile: AppProfile, feature_name: str) -> int:
    """Deterministic impact heuristic: big features + goal alignment score higher."""
    f = next((x for x in profile.features if x.name == feature_name), None)
    base = 70 if (f and f.is_big) else 45
    if any(feature_name.lower() in g.lower() for g in profile.goals):
        base += 15
    return min(100, base)
