"""W1 onboarding wizard engine (design spec section 4).

Pure library: no HTTP, no AI calls. Walks tree.FLOW, validates and merges
answers, and enforces the revision rule: CHANGING an already-terminal step
marks every later terminal step stale, so approvals must be re-earned.
That rule is the structural guarantee behind "never builds the wrong thing".
"""
from __future__ import annotations

import os

from danzaboss.workstation import state as state_mod
from danzaboss.workstation.tree import FLOW, Question, Step, step_applies

TERMINAL = frozenset({"complete", "approved"})


class WizardError(ValueError):
    """Invalid submission or flow misuse. Fail closed (CLAUDE.md standard)."""


def _validate(question: Question, value: object) -> object:
    """Normalize one answer or raise. Kind rules are the whole contract."""
    kind = question.kind
    if kind in ("text", "longtext"):
        if not isinstance(value, str) or not value.strip():
            raise WizardError(f"{question.id}: expected non-empty text")
        return value.strip()
    if kind == "choice":
        if value not in question.options:
            raise WizardError(
                f"{question.id}: {value!r} not one of {question.options}")
        return value
    if kind in ("list", "uploads"):
        if (not isinstance(value, list)
                or not all(isinstance(v, str) and v.strip() for v in value)):
            raise WizardError(
                f"{question.id}: expected a list of non-empty strings")
        return [v.strip() for v in value]
    if kind == "multi":
        if (not isinstance(value, list)
                or any(v not in question.options for v in value)):
            raise WizardError(
                f"{question.id}: values must be from {question.options}")
        return list(value)
    raise WizardError(f"{question.id}: unsupported kind {kind!r}")


class Wizard:
    """Stateful facade over ONE target repo's onboarding."""

    def __init__(self, root: str | os.PathLike) -> None:
        self._root = root
        self._state = state_mod.load_state(root)

    # ---- read side ----------------------------------------------------
    @property
    def answers(self) -> dict:
        return dict(self._state["answers"])

    def project_type(self) -> str | None:
        return self._state["answers"].get("project_type")

    def flow(self) -> tuple[Step, ...]:
        return tuple(s for s in FLOW if step_applies(s, self.project_type()))

    def status(self, step_id: str) -> str:
        return self._state["steps"].get(step_id, {}).get("status", "pending")

    def result(self, step_id: str) -> dict | None:
        return self._state["steps"].get(step_id, {}).get("result")

    def current_step(self) -> Step | None:
        for step in self.flow():
            if self.status(step.id) not in TERMINAL:
                return step
        return None

    def is_complete(self) -> bool:
        return self.project_type() is not None and self.current_step() is None

    def visible_questions(self, step: Step,
                          incoming: dict | None = None) -> tuple[Question, ...]:
        """Questions shown given stored answers overlaid with an incoming
        payload — the overlay is what lets one payload both pick a branch
        and answer inside it (e.g. stack_choice + stack_template)."""
        answers = dict(self._state["answers"])
        answers.update(incoming or {})
        return tuple(
            q for q in step.questions
            if all(answers.get(qid) in accepted for qid, accepted in q.show_if)
        )

    # ---- write side ---------------------------------------------------
    def submit(self, step_id: str, answers: dict) -> None:
        """Validate + merge one phase's answers; stale downstream on change."""
        step = self._require_step(step_id, kind="phase")
        visible = self.visible_questions(step, incoming=answers)
        by_id = {q.id: q for q in visible}
        for qid in answers:
            if qid not in by_id:
                raise WizardError(f"unknown or hidden question: {qid}")
        merged = dict(self._state["answers"])
        changed = False
        for q in visible:
            if q.id in answers:
                value = _validate(q, answers[q.id])
            elif q.id in merged:
                continue
            elif q.default is not None:
                value = q.default
            elif q.required:
                raise WizardError(f"missing required answer: {q.id}")
            else:
                continue
            if merged.get(q.id) != value:
                merged[q.id] = value
                changed = True
        was_terminal = self.status(step_id) in TERMINAL
        self._state["answers"] = merged
        self._set_status(step_id, "complete")
        if changed and was_terminal:
            self._stale_after(step_id)
        state_mod.save_state(self._root, self._state)

    def record_result(self, step_id: str, result: dict, *,
                      approved: bool = False) -> None:
        """Store a research digest or checkpoint verdict produced upstream
        (P2 seams / P5 server). Checkpoints stay pending until approved."""
        step = self._require_step(step_id, kind=None)
        if step.kind == "phase":
            raise WizardError(f"{step_id} is a phase; use submit()")
        if step.kind == "checkpoint":
            status = "approved" if approved else "pending"
        else:  # research
            status = "complete"
        entry = self._state["steps"].setdefault(step_id, {})
        entry["status"] = status
        entry["result"] = result
        state_mod.save_state(self._root, self._state)

    # ---- internals ------------------------------------------------------
    def _require_step(self, step_id: str, kind: str | None) -> Step:
        for step in self.flow():
            if step.id == step_id:
                if kind is not None and step.kind != kind:
                    raise WizardError(
                        f"{step_id} is a {step.kind}, not a {kind}")
                return step
        raise WizardError(f"step not in the active flow: {step_id}")

    def _set_status(self, step_id: str, status: str) -> None:
        self._state["steps"].setdefault(step_id, {})["status"] = status

    def _stale_after(self, step_id: str) -> None:
        """Everything terminal after an edited step must be re-earned."""
        seen = False
        for step in self.flow():
            if step.id == step_id:
                seen = True
                continue
            if seen and self.status(step.id) in TERMINAL:
                self._set_status(step.id, "stale")
