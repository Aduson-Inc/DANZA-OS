"""Adaptive AI interview for dashboard onboarding (product spec section 7).

After each phase submission the boss CLI is asked, headless, whether the
user's answers are buildable as stated: it returns ambiguities and
follow-up questions until the phase is clear. The AI only reports; every
decision that gates progress (round cap, clarity, escalation) is
deterministic control logic in this module (D6). Follow-ups clarify the
user's stated idea and never introduce features (spec section 11 —
no drift). Reuses the checkpoint runner's subprocess + lenient JSON
parse: one CLI seam, not two.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from danzaboss.workstation import checkpoints
from danzaboss.workstation.wizard import TERMINAL, Wizard

REPLY_KEYS = ("ambiguities", "follow_up_questions", "clear")

INTERVIEW_CONTRACT = (
    "Respond with ONLY a JSON object, no prose around it, shaped exactly:\n"
    '{"ambiguities": [str], "follow_up_questions": [str], "clear": bool}')


class InterviewError(ValueError):
    """Invalid reply, record misuse, or gate violation. Fail closed."""


def parse_reply(text: str) -> dict:
    """Fail-closed validation + deterministic normalization of one grill
    reply. The AI's `clear` flag is honored only when it lists nothing
    left to ask — data never overrides the gate (spec section 11); and an
    unclear verdict must carry at least one ambiguity or question, or the
    round is unactionable."""
    try:
        data = checkpoints.parse_json_reply(text)
    except checkpoints.CheckpointError as exc:
        raise InterviewError(str(exc)) from exc
    if not isinstance(data, dict):
        raise InterviewError(f"reply is not an object: {text[:200]!r}")
    missing = [k for k in REPLY_KEYS if k not in data]
    if missing:
        raise InterviewError(f"reply missing keys {missing}")
    for key in ("ambiguities", "follow_up_questions"):
        value = data[key]
        if (not isinstance(value, list)
                or not all(isinstance(v, str) and v.strip() for v in value)):
            raise InterviewError(
                f"reply.{key} must be a list of non-empty strings")
    if not isinstance(data["clear"], bool):
        raise InterviewError("reply.clear must be a boolean")
    ambiguities = [v.strip() for v in data["ambiguities"]]
    follow_ups = [v.strip() for v in data["follow_up_questions"]]
    clear = data["clear"] and not ambiguities and not follow_ups
    if not clear and not ambiguities and not follow_ups:
        raise InterviewError(
            "unclear verdict with nothing to ask is unactionable")
    return {"ambiguities": ambiguities,
            "follow_up_questions": follow_ups, "clear": clear}


def build_interview_prompt(step_title: str, phase_answers: dict,
                           all_answers: dict, prior_rounds: list[dict],
                           memory: str = "") -> str:
    """Deterministic grill prompt: phase answers + accumulated spec context
    inline (spec section 7), so the headless call needs no repo access."""
    lines = [
        "You are the DANZA onboarding interviewer. A user just answered "
        f"the {step_title!r} phase of product onboarding. Grill the "
        "answers until they are crystal clear to build from: name every "
        "ambiguity, contradiction, or unstated assumption a builder "
        "would trip over, and ask the follow-up questions that resolve "
        "them.",
        "Do NOT invent or suggest features — never introduce features. "
        "Clarify only what the user already stated (their idea, their "
        "words). If everything is buildable as stated, say clear.", ""]
    if memory:
        lines += ["User memory (honor these preferences — Rule 32):",
                  memory, ""]
    lines += ["Answers for this phase (JSON):",
              json.dumps(phase_answers, indent=2, sort_keys=True), "",
              "All onboarding answers so far (JSON):",
              json.dumps(all_answers, indent=2, sort_keys=True), ""]
    for n, rnd in enumerate(prior_rounds, start=1):
        lines += [f"Round {n} follow-ups already asked and answered (JSON):",
                  json.dumps({"asked": rnd["follow_up_questions"],
                              "answers": rnd["answers"]},
                             indent=2, sort_keys=True), ""]
    lines += ["", INTERVIEW_CONTRACT]
    return "\n".join(lines)


def call_interview(command: list[str], prompt: str, *,
                   timeout: int = 180) -> dict:
    """Call once; ONE retry on garbage with a harder instruction (same
    policy as call_checkpoint). Unavailability propagates — the round
    controller decides how to degrade."""
    try:
        return parse_reply(
            checkpoints.run_headless(command, prompt, timeout=timeout))
    except checkpoints.CheckpointUnavailable:
        raise
    except InterviewError:
        retry = (prompt + "\n\nYour previous reply was not valid JSON. "
                 + INTERVIEW_CONTRACT)
        return parse_reply(
            checkpoints.run_headless(command, retry, timeout=timeout))


INTERVIEW_RELPATH = Path(".danza") / "onboarding" / "interview.json"
MAX_ROUNDS = 3  # hard cap per phase (design decision D6)


def _fresh_record() -> dict:
    return {"rounds": [], "clear": False, "degraded": False,
            "needs_user_decision": False, "resolution": None}


def load_interview(root: str | os.PathLike) -> dict:
    """Interview state, or the empty shape. Fails closed on corruption —
    the reader must not act on garbage (same asymmetry as state.py)."""
    path = Path(root) / INTERVIEW_RELPATH
    if not path.exists():
        return {"phases": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InterviewError(f"corrupt interview state: {path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("phases"), dict):
        raise InterviewError(f"corrupt interview state (shape): {path}")
    return data


def save_interview(root: str | os.PathLike, data: dict) -> None:
    """Atomic replace. Whole-file overwrite is correct here: this module is
    the file's only writer and every mutation goes load -> mutate -> save
    within one request (unlike answers.json, which has two writers and
    needs state.py's merge discipline)."""
    path = Path(root) / INTERVIEW_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, path)


def begin_phase(root: str | os.PathLike, step_id: str) -> dict:
    """A (re)submission restarts the grill: prior rounds interrogated
    answers that may have just changed (P3-D8)."""
    data = load_interview(root)
    data["phases"][step_id] = _fresh_record()
    save_interview(root, data)
    return data["phases"][step_id]


def _require_phase(wizard: Wizard, step_id: str):
    for step in wizard.flow():
        if step.id == step_id:
            if step.kind != "phase":
                raise InterviewError(
                    f"{step_id} is a {step.kind}; only phases are grilled")
            return step
    raise InterviewError(f"step not in the active flow: {step_id}")


def run_interview_round(root: str | os.PathLike, step_id: str,
                        command: list[str] | None, *,
                        timeout: int = 180) -> dict:
    """One grill round, cap-guarded. Every gate here is deterministic:
    settled records no-op, the cap escalates instead of calling again,
    and an unreachable boss records degraded so the wizard continues
    flagged, never silently (spec section 7)."""
    wizard = Wizard(root)
    step = _require_phase(wizard, step_id)
    data = load_interview(root)
    record = data["phases"].setdefault(step_id, _fresh_record())
    if (record["clear"] or record["resolution"] is not None
            or record["needs_user_decision"] or record["degraded"]):
        return record
    if len(record["rounds"]) >= MAX_ROUNDS:
        record["needs_user_decision"] = True  # defensive; set below normally
        save_interview(root, data)
        return record
    if command is None:
        record["degraded"] = True
        record["degraded_reason"] = ("no headless boss runner configured "
                                     "(open MODELS or run 'danza runners')")
        save_interview(root, data)
        return record
    answers = wizard.answers
    phase_answers = {q.id: answers[q.id]
                     for q in step.questions if q.id in answers}
    prompt = build_interview_prompt(step.title, phase_answers, answers,
                                    record["rounds"],
                                    memory=checkpoints.read_memory(root))
    try:
        reply = call_interview(command, prompt, timeout=timeout)
    except (checkpoints.CheckpointError, InterviewError) as exc:
        record["degraded"] = True
        record["degraded_reason"] = str(exc)
        save_interview(root, data)
        return record
    record["rounds"].append({**reply, "answers": {}})
    record["clear"] = reply["clear"]
    if not record["clear"] and len(record["rounds"]) >= MAX_ROUNDS:
        record["needs_user_decision"] = True
    save_interview(root, data)
    return record


def record_followup_answers(root: str | os.PathLike, step_id: str,
                            answers: dict) -> dict:
    """Merge the user's follow-up answers into the open round — they ride
    into the next round's prompt ('merge into the phase record')."""
    if (not isinstance(answers, dict) or not answers
            or not all(isinstance(k, str) and isinstance(v, str) and v.strip()
                       for k, v in answers.items())):
        raise InterviewError(
            "follow-up answers must map question -> non-empty text")
    data = load_interview(root)
    record = data["phases"].get(step_id)
    if record is None or not record["rounds"]:
        raise InterviewError(f"no interview round open for {step_id}")
    if (record["clear"] or record["resolution"] is not None
            or record["degraded"]):
        raise InterviewError(f"{step_id} interview already settled")
    if record["needs_user_decision"]:
        raise InterviewError(f"{step_id} escalated: resolve it instead")
    record["rounds"][-1]["answers"].update(
        {k: v.strip() for k, v in answers.items()})
    save_interview(root, data)
    return record


def resolve(root: str | os.PathLike, step_id: str, decision: str) -> dict:
    """The user's final word on escalated ambiguities. No drift beyond the
    user's stated intent — the decision is recorded verbatim and closes
    the grill (spec section 7)."""
    if not isinstance(decision, str) or not decision.strip():
        raise InterviewError("resolution must be non-empty text")
    data = load_interview(root)
    record = data["phases"].get(step_id)
    if record is None:
        raise InterviewError(f"no interview record for {step_id}")
    if record["clear"] or record["resolution"] is not None:
        raise InterviewError(f"{step_id} interview already settled")
    record["resolution"] = decision.strip()
    record["needs_user_decision"] = False
    save_interview(root, data)
    return record


def phase_clear(record: dict | None) -> bool:
    """THE clarity gate (D6), pure and deterministic. None = the phase was
    submitted outside the dashboard (library/CLI onboarding) — the
    interview is an additive product surface, not a new wizard
    invariant. Degraded passes flagged: spec.md carries the honesty."""
    if record is None:
        return True
    return bool(record["clear"] or record["degraded"]
                or record["resolution"] is not None)


def blocking_phase(root: str | os.PathLike, wizard: Wizard | None = None) -> str | None:
    """First flow phase that is terminal but not clear — what the UI must
    grill and what approve/finish/other-submits wait on."""
    wizard = wizard or Wizard(root)
    records = load_interview(root)["phases"]
    for step in wizard.flow():
        if step.kind != "phase":
            continue
        if (wizard.status(step.id) in TERMINAL
                and not phase_clear(records.get(step.id))):
            return step.id
    return None


def open_questions(root: str | os.PathLike, wizard: Wizard | None = None) -> tuple[str, ...]:
    """Spec section-8 lines: degraded grills and user-final decisions on
    ambiguities the AI could not clear — the honest appendix (P3-D5)."""
    wizard = wizard or Wizard(root)
    records = load_interview(root)["phases"]
    out: list[str] = []
    for step in wizard.flow():
        record = records.get(step.id)
        if record is None:
            continue
        if record["degraded"]:
            out.append(f"{step.id}: interview degraded — clarity not "
                       f"AI-verified ({record.get('degraded_reason', '')})")
        if record["resolution"] is not None:
            last = record["rounds"][-1] if record["rounds"] else {}
            listed = "; ".join(last.get("ambiguities", [])) or \
                "escalated ambiguities"
            out.append(f"{step.id}: {listed} — user decision (final): "
                       f"{record['resolution']}")
    return tuple(out)
