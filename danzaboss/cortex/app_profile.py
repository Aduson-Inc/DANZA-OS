"""App Profile — DANZA adaptability foundation.

The single artifact that makes DANZA general instead of app-specific. Every agent,
guard, and research query reads the profile at RUNTIME; nothing hardcodes a target
app. To build a different app you learn a different profile — zero code change.

The profile is *learned* (from a repo scan + onboarding), stored in CORTEX at the
project layer, and kept current by re-scanning. This is the mechanism behind
"learn my app, then adjust" — and it is identical machinery for any app.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


@dataclass
class FeatureProfile:
    name: str
    description: str = ""
    is_big: bool = False              # gates deep research spend (research squad)
    files: list[str] = field(default_factory=list)
    status: str = "planned"           # planned | in_progress | done
    conventions: list[str] = field(default_factory=list)


@dataclass
class AppProfile:
    """Learned, runtime-read description of ANY target app."""
    project: str
    # learned stack (language-agnostic; populated by analyzers, never assumed)
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    databases: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    # domain + intent
    domain: str = ""                  # e.g. "audio tool", "CRM" — drives research queries
    goals: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)  # budget, perf, platform
    conventions: list[str] = field(default_factory=list)
    features: list[FeatureProfile] = field(default_factory=list)
    # config knobs that downstream scripts read (never hardcoded)
    config: dict = field(default_factory=dict)
    learned_at: str = field(default_factory=_utcnow)
    confidence: int = 60              # how sure we are the profile matches reality

    def big_features(self) -> list[FeatureProfile]:
        return [f for f in self.features if f.is_big]

    def research_topic_for(self, feature_name: str) -> str:
        """Build an app-agnostic research query from the profile + a feature.
        Works for any domain because the domain comes from the learned profile."""
        f = next((x for x in self.features if x.name == feature_name), None)
        desc = f.description if f else feature_name
        domain = self.domain or "software"
        return f"{feature_name} {desc} best practices and latest improvements for {domain}".strip()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---- learning: build a profile from a repo scan (adapter-fed, not hardcoded) --

@dataclass
class ScanFacts:
    """Whatever a language-agnostic scan (tree-sitter/Samantha) extracted.
    The learner consumes facts; it never inspects a specific app itself."""
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    databases: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    detected_features: list[dict] = field(default_factory=list)  # {name, files, description?}


def learn_profile(project: str, scan: ScanFacts, *, domain: str = "",
                  goals: Optional[list[str]] = None,
                  big_feature_names: Optional[set[str]] = None) -> AppProfile:
    """Merge scan facts + onboarding intent into an AppProfile.

    `big_feature_names` (from onboarding) flags which features justify deep
    research; everything else gets only cheap passes. All inputs are data —
    the function is completely app-agnostic.
    """
    big = big_feature_names or set()
    features = [
        FeatureProfile(name=f.get("name", "unknown"),
                       description=f.get("description", ""),
                       files=f.get("files", []),
                       is_big=f.get("name") in big)
        for f in scan.detected_features
    ]
    # confidence: more signal from the scan -> higher confidence it reflects reality
    signal = sum(bool(x) for x in (scan.languages, scan.frameworks, scan.databases,
                                   scan.entry_points, scan.detected_features))
    confidence = min(95, 50 + signal * 9)
    return AppProfile(
        project=project, domain=domain, goals=goals or [],
        languages=scan.languages, frameworks=scan.frameworks,
        databases=scan.databases, entry_points=scan.entry_points,
        features=features, confidence=confidence)


def diff_profiles(old: AppProfile, new: AppProfile) -> dict:
    """What changed between two learnings — so DANZA 'adjusts' when the app moves
    (e.g., a stack migration). Downstream agents react to this delta."""
    def names(p): return {f.name for f in p.features}
    return {
        "languages_added": sorted(set(new.languages) - set(old.languages)),
        "frameworks_added": sorted(set(new.frameworks) - set(old.frameworks)),
        "databases_changed": sorted(set(new.databases) ^ set(old.databases)),
        "features_added": sorted(names(new) - names(old)),
        "features_removed": sorted(names(old) - names(new)),
    }
