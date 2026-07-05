"""Compile approved wizard answers into .danza/spec.md (Upgrade #3).

Headings mirror danzaboss/planning/spec_template.md EXACTLY — the plan and
all tasks derive from this document, so the shape is law (Rule 34: the
template defines the format). spec.md itself is a generated artifact:
regenerated whole from answers on each final approval, which is why plain
overwrite here is correct where answers.json must merge.
"""
from __future__ import annotations

import os
from pathlib import Path

from danzaboss.workstation.templates import StackTemplate

CADENCE_LABELS = {
    "relay": "relay — 2 features per turn, alternate environments",
    "continuous": ("continuous-checkpointed — fresh session per turn, "
                   "pause for user approval every N features"),
    "supervised": "supervised — 2 features per turn, explicit user continue",
}

HARD_STOP_CAPS = ("accounts_auth", "payments")


def compile_spec(*, answers: dict, template: StackTemplate | None,
                 research: dict | None = None,
                 checkpoints: dict[str, str] | None = None,
                 overrides: tuple[str, ...] = (),
                 open_questions: tuple[str, ...] = ()) -> str:
    """Render the spec markdown from approved onboarding state."""
    checkpoints = checkpoints or {}
    caps = answers.get("capabilities", [])
    lines: list[str] = [f"# Spec — {answers['project_name']}", ""]

    lines += ["## 1. Intent",
              answers["concept_what"],
              f"For: {answers['concept_who']}. "
              f"Problem: {answers['concept_problem']}"]
    if research and not research.get("skipped"):
        lines.append(f"Reality check: {research.get('verdict', 'unknown')} — "
                     f"{research.get('summary', '')}".rstrip(" —"))
    else:
        lines.append("Reality check: not run (user skipped or unavailable).")
    for cp_id, summary in sorted(checkpoints.items()):
        lines.append(f"> {cp_id}: {summary}")

    lines += ["", "## 2. Functional requirements"]
    for n, feat in enumerate(answers.get("features_must", []), start=1):
        lines.append(f"- FR-{n}: {feat} — Acceptance: concrete verification "
                     "assigned at decomposition (plan.json leaf)")
    for feat in answers.get("features_nice", []):
        lines.append(f"- (nice-to-have, post-MVP): {feat}")

    lines += ["", "## 3. Non-functional requirements",
              f"- Deployment intent: {answers.get('deploy_intent', 'local')}",
              f"- Build cadence: "
              f"{CADENCE_LABELS[answers.get('cadence', 'continuous')]} "
              f"(N={answers.get('cadence_n', '4')})",
              f"- Capabilities: {', '.join(caps) if caps else 'none checked'}"]
    hard = [c for c in HARD_STOP_CAPS if c in caps]
    if hard:
        lines.append(f"- Hard-stop flags (Rules 13-14): {', '.join(hard)} — "
                     "the build pauses for user approval on these areas")
    lines.append(f"- Design inputs: .danza/design/ "
                 f"(direction: {answers.get('color_direction', 'propose')})")

    lines += ["", "## 4. Data model",
              "Derived from the FR list at planning; Samantha's map is "
              "authoritative after the first scan."]
    if answers.get("feature_notes"):
        lines.append(f"Notes: {answers['feature_notes']}")

    lines += ["", "## 5. External services / APIs"]
    if template is not None:
        lines.append(f"Approved stack: {template.name}")
        for role, choice in template.components.items():
            lines.append(f"- {role}: {choice}")
    else:
        lines.append("Approved stack (user-specified): "
                     f"{answers.get('stack_custom', 'unspecified')}")
    for note in overrides:
        lines.append(f"- OVERRIDE: {note}")

    lines += ["", "## 6. Explicit non-goals"]
    lines += [f"- {goal}" for goal in answers.get("non_goals", [])]

    framework = (template.testing_defaults.get("framework", "unset")
                 if template else "chosen at planning from the user stack")
    lines += ["", "## 7. Verification strategy",
              f"- Test framework: {framework}",
              "- Every FR maps to at least one concrete verification at "
              "decomposition (planning/decompose.py kinds); no FR without "
              "a check",
              "- Test-first for business logic and endpoints; tier 0-1 "
              "checks for scaffold/config; the suite accumulates and runs "
              "at cadence checkpoints"]

    lines += ["", "## 8. Open questions"]
    lines += [f"- {q}" for q in open_questions] if open_questions else ["None."]

    return "\n".join(lines) + "\n"


def write_spec(root: str | os.PathLike, text: str) -> Path:
    """Write .danza/spec.md atomically; returns the path written."""
    path = Path(root) / ".danza" / "spec.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path
