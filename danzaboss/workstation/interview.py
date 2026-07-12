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

from danzaboss.workstation import checkpoints

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
