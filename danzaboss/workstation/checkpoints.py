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
from pathlib import Path

from danzaboss.workstation import templates as templates_mod
from danzaboss.workstation.wizard import Wizard

VERDICT_KEYS = ("summary", "concerns", "follow_up_questions",
                "recommendation", "verdict")
VERDICTS = ("approve", "revise")

JSON_CONTRACT = (
    "Respond with ONLY a JSON object, no prose around it, shaped exactly:\n"
    '{"summary": str, "concerns": [str], "follow_up_questions": [str], '
    '"recommendation": str, "verdict": "approve"|"revise"}'
)

# The one degraded-reason string for "no boss configured" — checkpoints,
# the interview, and the finish flow all report the same absence.
NO_BOSS_REASON = ("no AI agent is connected yet — "
                  "open Setup (or run 'danza runners')")


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
        result = data["result"]
        # Some CLIs decode the payload for us: result is already an
        # object, not JSON text — str() would yield Python repr and
        # fail to parse (P2-M1).
        data = result if isinstance(result, (dict, list)) else _loads(
            str(result))
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


CHECKPOINT_IDS = ("cp_concept", "cp_stack", "cp_final")
MEMORY_RELDIR = Path(".danza") / "memory"

_FOCUS = {
    "cp_concept": (
        "Concept review: reflect back what the user is building in plain "
        "words, flag contradictions and unstated assumptions, and ask the "
        "follow-up questions a senior product engineer would ask. Ground "
        "the review in the reality digest when one is present."),
    "cp_stack": (
        "Stack review: judge the chosen stack against the fitting templates "
        "listed. For a custom stack give reasoned pushback plus the nearest "
        "template; for no-preference recommend one option WITH trade-offs, "
        "never a bare pick (Rule 30); the user may still insist."),
    "cp_final": (
        "Final rundown: narrate the whole build back to the user — concept, "
        "features with priorities, stack, design, cadence — and list every "
        "gap that would surprise them mid-build."),
}


def read_memory(root, *, cap: int = 8000) -> str:
    """Rule 32: user memory files must inform checkpoint review when they
    exist. Reads the TARGET repo's .danza/memory/*.md, sorted for
    determinism, capped so memory informs the prompt without drowning
    the answers. The cap cuts at file boundaries — a file that does not
    fit is omitted whole (a truncated preference can invert its meaning);
    only when the very first file alone exceeds the cap is it hard-cut,
    so memory never silently vanishes."""
    directory = Path(root) / MEMORY_RELDIR
    if not directory.is_dir():
        return ""
    kept: list[str] = []
    used = 0
    for path in sorted(directory.glob("*.md")):
        part = f"--- {path.name} ---\n{path.read_text(encoding='utf-8')}"
        cost = len(part) + (1 if kept else 0)  # joining newline
        if used + cost <= cap:
            kept.append(part)
            used += cost
        elif not kept:
            return part[:cap]
    return "\n".join(kept)


def build_prompt(step_id: str, answers: dict, *,
                 research: dict | None = None, stack_options: tuple = (),
                 memory: str = "", concerns: tuple[str, ...] = ()) -> str:
    """Deterministic review prompt. All variable context (answers, digest,
    templates, memory) is inlined so the headless call needs no repo
    access — the prompt IS the context."""
    if step_id not in CHECKPOINT_IDS:
        raise CheckpointError(f"not a checkpoint step: {step_id}")
    lines = ["You are the DANZA onboarding reviewer.", _FOCUS[step_id], ""]
    if memory:
        lines += ["User memory (honor these preferences — Rule 32):",
                  memory, ""]
    lines += ["Answers so far (JSON):",
              json.dumps(answers, indent=2, sort_keys=True), ""]
    if research and not research.get("skipped"):
        lines += ["Reality digest (JSON):",
                  json.dumps(research, indent=2, sort_keys=True), ""]
    if stack_options:
        lines.append("Fitting stack templates:")
        lines += [f"- {t.key}: {t.name} — {t.tagline} (why: {t.why}; "
                  f"tradeoffs: {t.tradeoffs})" for t in stack_options]
        lines.append("")
    for concern in concerns:
        lines.append(f"KNOWN ISSUE to address in your review: {concern}")
    lines += ["", JSON_CONTRACT]
    return "\n".join(lines)


def _degraded_verdict(concerns: list[str], reason: str) -> dict:
    """The wizard-only-continuation verdict (spec section 4): recorded,
    flagged, never silent."""
    return {
        "summary": ("checkpoint degraded: boss CLI unreachable or "
                    "returned unusable output"),
        "concerns": list(concerns),
        "follow_up_questions": [],
        "recommendation": ("wizard-only continuation; re-run this "
                           "checkpoint when the CLI is available"),
        "verdict": "revise",
        "degraded": True,
        "degraded_reason": reason,
    }


def run_checkpoint(root, step_id: str, command: list[str] | None, *,
                   timeout: int = 180,
                   template_dir=templates_mod.DEFAULT_DIR) -> dict:
    """Build context from the target repo, call the boss CLI, record the
    verdict on the wizard. Never passes approved=True — approval is the
    user's click (P5). An unreachable CLI records a degraded verdict so
    onboarding can continue wizard-only, flagged (spec section 4).
    If command is None, records the degraded verdict without attempting
    a subprocess call."""
    wizard = Wizard(root)
    answers = wizard.answers
    concerns: list[str] = []
    stack_options: tuple = ()
    if step_id == "cp_stack":
        library = templates_mod.load_templates(template_dir)
        stack_options = tuple(templates_mod.select_templates(
            library, answers.get("project_type", ""),
            answers.get("capabilities", [])))
        chosen = answers.get("stack_template")
        if (answers.get("stack_choice") == "template" and chosen is not None
                and chosen not in {t.key for t in library}):
            concerns.append(
                f"{chosen!r} is not in the template library")
    # Freshness gate: result() returns stored data regardless of status,
    # and re-running research never re-stales downstream checkpoints — so
    # a staled digest must not ground this review in the wrong reality.
    research = (wizard.result("r_reality")
                if wizard.status("r_reality") == "complete" else None)
    prompt = build_prompt(step_id, answers,
                          research=research,
                          stack_options=stack_options,
                          memory=read_memory(root),
                          concerns=tuple(concerns))
    if command is None:
        verdict = _degraded_verdict(concerns, NO_BOSS_REASON)
    else:
        try:
            verdict = dict(call_checkpoint(command, prompt, timeout=timeout))
            verdict["degraded"] = False
        except CheckpointError as exc:
            verdict = _degraded_verdict(concerns, str(exc))
    wizard.record_result(step_id, verdict)
    return verdict
