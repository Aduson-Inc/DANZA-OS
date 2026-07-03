"""Structured observability — DANZABOSS Upgrade #5.

Replaces prose run-logs with structured, queryable spans (JSONL). Every model
call, tool call, verification, and decision becomes a span with a trace id,
parent id, timing, and outcome. This gives Mona real data to learn from and
gives the anti-theatre rules (42-43) machine-checkable evidence that a
sub-agent actually ran.

Stdlib only. A span is a context manager so timing and error capture are automatic.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Iterator, Optional


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Span:
    name: str
    kind: str                       # "agent" | "tool" | "decision" | "verify" | "model"
    trace_id: str
    span_id: str
    parent_id: Optional[str]
    actor: Optional[str] = None
    attributes: dict = field(default_factory=dict)
    start: str = field(default_factory=_utcnow)
    end: Optional[str] = None
    duration_ms: Optional[float] = None
    status: str = "ok"              # "ok" | "error"
    error: Optional[str] = None


class Tracer:
    """Writes spans to an append-only JSONL file and offers simple queries."""

    def __init__(self, path: str, trace_id: Optional[str] = None):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.trace_id = trace_id or secrets.token_hex(6)
        self._stack: list[str] = []

    def _emit(self, span: Span) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(span)) + "\n")

    @contextmanager
    def span(self, name: str, kind: str, actor: Optional[str] = None,
             **attributes) -> Iterator[Span]:
        span = Span(name=name, kind=kind, trace_id=self.trace_id,
                    span_id=secrets.token_hex(6),
                    parent_id=self._stack[-1] if self._stack else None,
                    actor=actor, attributes=attributes)
        self._stack.append(span.span_id)
        t0 = time.perf_counter()
        try:
            yield span
        except Exception as exc:            # capture, mark, re-raise
            span.status = "error"
            span.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            span.duration_ms = round((time.perf_counter() - t0) * 1000, 3)
            span.end = _utcnow()
            self._stack.pop()
            self._emit(span)

    # -- queries (observability that actually pays off) -----------------------
    def load(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def summary(self) -> dict:
        spans = self.load()
        by_actor: dict[str, int] = {}
        errors = 0
        total_ms = 0.0
        for s in spans:
            if s.get("actor"):
                by_actor[s["actor"]] = by_actor.get(s["actor"], 0) + 1
            if s.get("status") == "error":
                errors += 1
            total_ms += s.get("duration_ms") or 0.0
        return {"span_count": len(spans), "errors": errors,
                "total_ms": round(total_ms, 3), "spans_by_actor": by_actor}

    def evidence_for(self, actor: str) -> list[dict]:
        """Anti-theatre: return the spans proving `actor` actually ran."""
        return [s for s in self.load() if s.get("actor") == actor]
