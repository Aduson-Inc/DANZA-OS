"""AI checkpoint runner (design spec sections 3-4).

Builds a review prompt from answers-so-far plus the target repo's user
memory files (Constitution Rule 32), calls the boss CLI headless through
an INJECTABLE argv prefix, and parses a structured verdict. The AI only
proposes: this module never passes approved=True — approval stays a user
act (P5 server). Degraded wizard-only continuation on an unreachable CLI
is the spec'd fallback, not a silent failure: the recorded result carries
degraded=True and the compiler flags it in spec.md.
"""
from __future__ import annotations

import json
import subprocess

VERDICT_KEYS = ("summary", "concerns", "follow_up_questions",
                "recommendation", "verdict")
VERDICTS = ("approve", "revise")

JSON_CONTRACT = (
    "Respond with ONLY a JSON object, no prose around it, shaped exactly:\n"
    '{"summary": str, "concerns": [str], "follow_up_questions": [str], '
    '"recommendation": str, "verdict": "approve"|"revise"}'
)


class CheckpointError(ValueError):
    """The CLI answered, but not with a usable verdict (after one retry)."""


class CheckpointUnavailable(CheckpointError):
    """The CLI could not be run at all (missing, crashed, timed out)."""


def run_headless(command: list[str], prompt: str, *,
                 timeout: int = 180) -> str:
    """One boss-CLI call. `command` is an argv prefix (e.g. ["claude",
    "-p", "--output-format", "json"]); the prompt rides as the final
    argument, which is what lets tests substitute a stub interpreter."""
    try:
        proc = subprocess.run(list(command) + [prompt], capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CheckpointUnavailable(f"boss CLI failed to run: {exc}") from exc
    if proc.returncode != 0:
        raise CheckpointUnavailable(
            f"boss CLI exit {proc.returncode}: {(proc.stderr or '')[-2000:]}")
    return proc.stdout


def parse_json_reply(text: str) -> object:
    """Decode a JSON payload from the shapes real CLIs emit: the bare
    object, the `--output-format json` envelope ({"result": <text>}),
    and a ```json fence. Shared with research.py — one lenient decoder
    beats two divergent ones."""
    data = _loads(text)
    if isinstance(data, dict) and "result" in data and not all(
            k in data for k in VERDICT_KEYS):
        data = _loads(str(data["result"]))
    return data


def parse_verdict(text: str) -> dict:
    """Fail-closed validation of the checkpoint contract (spec section 4)."""
    data = parse_json_reply(text)
    if not isinstance(data, dict):
        raise CheckpointError(f"verdict is not an object: {text[:200]!r}")
    missing = [k for k in VERDICT_KEYS if k not in data]
    if missing:
        raise CheckpointError(f"verdict missing keys {missing}")
    if not isinstance(data["summary"], str) or not data["summary"].strip():
        raise CheckpointError("verdict.summary must be non-empty text")
    for key in ("concerns", "follow_up_questions"):
        value = data[key]
        if (not isinstance(value, list)
                or not all(isinstance(v, str) for v in value)):
            raise CheckpointError(f"verdict.{key} must be a list of strings")
    if not isinstance(data["recommendation"], str):
        raise CheckpointError("verdict.recommendation must be text")
    if data["verdict"] not in VERDICTS:
        raise CheckpointError(f"verdict.verdict must be one of {VERDICTS}")
    return {key: data[key] for key in VERDICT_KEYS}


def call_checkpoint(command: list[str], prompt: str, *,
                    timeout: int = 180) -> dict:
    """Call once; ONE retry on garbage with a harder instruction (spec
    section 4). Unavailability propagates — the caller decides whether
    to degrade (run_checkpoint does) or surface (research does)."""
    try:
        return parse_verdict(run_headless(command, prompt, timeout=timeout))
    except CheckpointUnavailable:
        raise
    except CheckpointError:
        retry = (prompt + "\n\nYour previous reply was not valid JSON. "
                 + JSON_CONTRACT)
        return parse_verdict(run_headless(command, retry, timeout=timeout))


def _loads(text: str) -> object:
    """json.loads that tolerates surrounding prose and code fences by
    slicing the outermost object — models decorate, contracts don't."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise CheckpointError(f"no JSON object in reply: {text[:200]!r}")
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise CheckpointError(
                f"unparseable JSON in reply: {text[:200]!r}") from exc
