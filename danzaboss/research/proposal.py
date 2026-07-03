"""Proposal — the unit the research squad sends you to 'grill' on via chat."""
from __future__ import annotations

import datetime as _dt
import hashlib
from dataclasses import dataclass, field
from enum import Enum


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class ProposalStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    APPROVED = "approved"
    DENIED = "denied"
    DEFERRED = "deferred"


@dataclass
class Proposal:
    feature: str
    title: str
    rationale: str                 # WHY (competitor/cutting-edge evidence)
    effort: str = "medium"         # low | medium | high
    risk: str = "low"
    impact: int = 50               # 0-100; gates the throttle
    evidence: list[str] = field(default_factory=list)  # source URLs
    status: str = ProposalStatus.DRAFT.value
    created: str = field(default_factory=_utcnow)
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = "prop_" + hashlib.sha1(
                f"{self.feature}|{self.title}|{self.created}".encode()).hexdigest()[:12]

    def render_message(self) -> str:
        """The chat message you receive to approve/deny remotely."""
        return (f"[DANZA proposal] {self.title}\n"
                f"Feature: {self.feature} | impact {self.impact} | effort {self.effort} | risk {self.risk}\n"
                f"Why: {self.rationale}\n"
                f"Reply: APPROVE {self.id} / DENY {self.id} / LATER {self.id}")
