"""Proposal throttle — stops the research squad from being overzealous.

Tre's rule: at most N upgrade suggestions per day, at set times only. Refined so it
doesn't backfire:
  * CEILING, not a quota — never manufacture proposals to hit the number.
  * IMPACT GATE — a proposal must clear a bar to spend a slot.
  * CONFIG, not hardcoded — count, windows, and threshold are all tunable per app.
Deterministic and unit-testable (time is injected).
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional

from .proposal import Proposal


@dataclass
class ThrottleConfig:
    max_per_day: int = 2
    allowed_hours: tuple[int, ...] = (9, 17)   # only send at ~9:00 and ~17:00 local
    window_minutes: int = 30                    # grace around each allowed hour
    min_impact: int = 60                        # proposals below this never spend a slot


@dataclass
class ThrottleState:
    day: str = ""                 # YYYY-MM-DD of the current count window
    sent_today: int = 0


class ProposalThrottle:
    def __init__(self, cfg: Optional[ThrottleConfig] = None,
                 state: Optional[ThrottleState] = None):
        self.cfg = cfg or ThrottleConfig()
        self.state = state or ThrottleState()

    def _roll_day(self, now: _dt.datetime) -> None:
        today = now.strftime("%Y-%m-%d")
        if self.state.day != today:
            self.state.day = today
            self.state.sent_today = 0

    def _in_window(self, now: _dt.datetime) -> bool:
        for h in self.cfg.allowed_hours:
            target = now.replace(hour=h, minute=0, second=0, microsecond=0)
            if abs((now - target).total_seconds()) <= self.cfg.window_minutes * 60:
                return True
        return False

    def can_send(self, proposal: Proposal, now: _dt.datetime) -> tuple[bool, str]:
        """Returns (allowed, reason). Reason explains a block for observability."""
        self._roll_day(now)
        if proposal.impact < self.cfg.min_impact:
            return False, f"impact {proposal.impact} < threshold {self.cfg.min_impact}"
        if not self._in_window(now):
            return False, f"outside allowed send windows {self.cfg.allowed_hours}"
        if self.state.sent_today >= self.cfg.max_per_day:
            return False, f"daily ceiling {self.cfg.max_per_day} reached"
        return True, "ok"

    def record_sent(self, now: _dt.datetime) -> None:
        self._roll_day(now)
        self.state.sent_today += 1

    def select(self, candidates: list[Proposal], now: _dt.datetime) -> list[Proposal]:
        """Pick the highest-impact proposals that fit the remaining budget/window.
        Ceiling-not-quota: returns [] if nothing clears the bar."""
        self._roll_day(now)
        if not self._in_window(now):
            return []
        remaining = max(0, self.cfg.max_per_day - self.state.sent_today)
        eligible = [p for p in candidates if p.impact >= self.cfg.min_impact]
        eligible.sort(key=lambda p: p.impact, reverse=True)
        return eligible[:remaining]
