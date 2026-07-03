"""Verifiable task decomposition — DANZABOSS Upgrade #4.

Enforces the kernel rule: *a task may only be dispatched to a driver if it has
a concrete verification method; otherwise it must be recursively decomposed
until every leaf is verifiable.*

This turns "it should work" into a structural impossibility: an unverifiable
task cannot pass ``ready_for_dispatch``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class VerificationKind(str, Enum):
    AUTOMATED_TEST = "automated_test"   # a test command / assertion
    COMMAND_OUTPUT = "command_output"   # a command whose output is checked
    HTTP_CHECK = "http_check"           # endpoint returns expected shape
    SCHEMA_CHECK = "schema_check"       # data matches a schema
    MANUAL_GATE = "manual_gate"         # explicit human/QA sign-off (last resort)


@dataclass
class Verification:
    kind: VerificationKind
    detail: str  # e.g. "pytest tests/test_login.py::test_ok" or the assertion

    def is_concrete(self) -> bool:
        return bool(self.detail and self.detail.strip())


@dataclass
class Task:
    """A unit of planned work.

    A task is *verifiable* if it either carries a concrete ``verification`` or
    all of its subtasks are verifiable. A leaf task with no verification is not
    dispatchable — it must be decomposed first.
    """
    id: str
    description: str
    verification: Optional[Verification] = None
    subtasks: list["Task"] = field(default_factory=list)

    # -- properties -----------------------------------------------------------
    def is_leaf(self) -> bool:
        return not self.subtasks

    def is_verifiable(self) -> bool:
        if self.is_leaf():
            return self.verification is not None and self.verification.is_concrete()
        return all(st.is_verifiable() for st in self.subtasks)

    def unverifiable_leaves(self) -> list["Task"]:
        """Return every leaf task that still lacks a concrete verification."""
        if self.is_leaf():
            ok = self.verification is not None and self.verification.is_concrete()
            return [] if ok else [self]
        out: list[Task] = []
        for st in self.subtasks:
            out.extend(st.unverifiable_leaves())
        return out

    def ready_for_dispatch(self) -> bool:
        """The gate the scheduler calls before handing a task to a driver."""
        return self.is_verifiable()

    def decompose(self, subtasks: list["Task"]) -> "Task":
        """Split this task into verifiable subtasks (removes own verification)."""
        if not subtasks:
            raise ValueError("decompose requires at least one subtask")
        self.subtasks = subtasks
        self.verification = None
        return self


class DispatchError(Exception):
    """Raised when an unverifiable task is dispatched."""


def assert_dispatchable(task: Task) -> None:
    """Fail-closed guard. Call this at the dispatch boundary."""
    if not task.ready_for_dispatch():
        bad = ", ".join(t.id for t in task.unverifiable_leaves())
        raise DispatchError(
            f"task {task.id!r} is not dispatchable; unverifiable leaves: [{bad}]. "
            f"Decompose until every leaf has a concrete verification method.")
