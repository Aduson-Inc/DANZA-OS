"""CORTEX Observation core — DANZA cognitive memory (P1).

The atomic unit of knowledge. Unlike transcript-compression memory, an Observation
carries reasoning (the WHY), explicit relevance controls (when_relevant /
when_not_relevant), a confidence score with a provenance source, an importance
tier that drives aging, and an append-only evolution history.

Stdlib only.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class ObsType(str, Enum):
    BUG_FIX = "bug_fix"
    DECISION = "decision"
    PERFORMANCE = "performance"
    DEPENDENCY = "dependency"
    SECURITY = "security"
    API_BEHAVIOR = "api_behavior"
    MILESTONE = "milestone"
    LESSON = "lesson"
    ROOT_CAUSE = "root_cause"
    LIMITATION = "limitation"
    IMPL_DETAIL = "impl_detail"
    CONVENTION = "convention"


class Importance(str, Enum):
    CRITICAL = "critical"      # almost never expires
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    TEMPORARY = "temporary"    # expires fast
    ARCHIVE = "archive"        # retained but not retrieved by default


# importance -> default time-to-live in hours (None = never expires)
TTL_HOURS: dict[Importance, Optional[int]] = {
    Importance.CRITICAL: None,
    Importance.HIGH: 24 * 365,
    Importance.MEDIUM: 24 * 90,
    Importance.LOW: 24 * 14,
    Importance.TEMPORARY: 24,
    Importance.ARCHIVE: None,
}


class ConfidenceSource(str, Enum):
    USER_STATED = "user_stated"                 # 100
    REPO_VERIFIED = "repo_verified"             # 95
    REPEATEDLY_SUCCESSFUL = "repeatedly_successful"  # 95
    DOC_VERIFIED = "doc_verified"               # 90
    LLM_INFERRED = "llm_inferred"               # 60
    SPECULATION = "speculation"                 # 20


CONFIDENCE_OF: dict[ConfidenceSource, int] = {
    ConfidenceSource.USER_STATED: 100,
    ConfidenceSource.REPO_VERIFIED: 95,
    ConfidenceSource.REPEATEDLY_SUCCESSFUL: 95,
    ConfidenceSource.DOC_VERIFIED: 90,
    ConfidenceSource.LLM_INFERRED: 60,
    ConfidenceSource.SPECULATION: 20,
}


@dataclass
class Observation:
    title: str
    summary: str
    type: str                                   # ObsType value
    project: str
    # scoring / lifecycle
    importance: str = Importance.MEDIUM.value
    confidence: int = 60
    confidence_source: str = ConfidenceSource.LLM_INFERRED.value
    layer: int = 2
    repository: str = ""
    branch: Optional[str] = None
    created: str = field(default_factory=_utcnow)
    updated: str = field(default_factory=_utcnow)
    last_used: Optional[str] = None
    usage_count: int = 0
    expires: Optional[str] = None
    # linkage
    tags: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    related_observations: list[str] = field(default_factory=list)
    related_docs: list[str] = field(default_factory=list)
    related_commits: list[str] = field(default_factory=list)
    related_issues: list[str] = field(default_factory=list)
    # reasoning (the differentiator)
    reasoning: str = ""
    evidence: list[str] = field(default_factory=list)
    resolution: Optional[str] = None
    lessons: Optional[str] = None
    future_risks: Optional[str] = None
    # precision controls
    when_relevant: list[str] = field(default_factory=list)
    when_not_relevant: list[str] = field(default_factory=list)
    # evolution
    id: str = ""
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    history: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            self.id = self._compute_id()
        if self.expires is None:
            self.expires = self._default_expiry()

    def _compute_id(self) -> str:
        basis = f"{self.project}|{self.type}|{self.title}|{self.created}"
        return "obs_" + hashlib.sha1(basis.encode()).hexdigest()[:16]

    def _default_expiry(self) -> Optional[str]:
        ttl = TTL_HOURS.get(Importance(self.importance))
        if ttl is None:
            return None
        exp = _dt.datetime.fromisoformat(self.created) + _dt.timedelta(hours=ttl)
        return exp.isoformat(timespec="seconds")

    # -- helpers --------------------------------------------------------------
    @staticmethod
    def confidence_for(source: ConfidenceSource) -> int:
        return CONFIDENCE_OF[source]

    def link_bag(self) -> set[str]:
        """The identity fingerprint used for near-duplicate detection."""
        return {c.lower() for c in self.concepts} | {f.lower() for f in self.files} \
            | {s.lower() for s in self.symbols}

    def to_row(self) -> dict[str, Any]:
        return asdict(self)
