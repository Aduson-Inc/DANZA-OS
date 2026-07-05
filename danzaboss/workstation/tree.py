"""Question tree for the W1 onboarding wizard (design spec section 4).

The tree is DATA, not control flow: evolving onboarding (Constitution
Rule 21) means editing these declarations. The engine (wizard.py) walks
whatever FLOW declares and never hard-codes step order.
"""
from __future__ import annotations

from dataclasses import dataclass

APP_PROJECT_TYPES = frozenset({"website", "saas"})
SEED_PROJECT_TYPES = frozenset({"design_ideas", "workflow", "other", "not_sure"})

QUESTION_KINDS = ("choice", "text", "longtext", "list", "multi", "uploads")
STEP_KINDS = ("phase", "research", "checkpoint")


@dataclass(frozen=True)
class Question:
    """One wizard prompt.

    show_if: ((question_id, (accepted, values...)), ...) — every clause must
    match current answers for this question to be shown. Hidden questions
    are never required. `default` satisfies `required` when unanswered.
    """
    id: str
    prompt: str
    kind: str  # one of QUESTION_KINDS
    options: tuple[str, ...] = ()
    required: bool = True
    default: str | None = None
    show_if: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def __post_init__(self) -> None:
        # Fail closed at declaration time: a typo'd kind would otherwise
        # surface only when the engine validates an answer against it.
        if self.kind not in QUESTION_KINDS:
            raise ValueError(f"{self.id}: unknown question kind {self.kind!r}")


@dataclass(frozen=True)
class Step:
    """One flow step: a question phase, a research pass, or an AI checkpoint."""
    id: str
    kind: str  # one of STEP_KINDS
    title: str
    questions: tuple[Question, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in STEP_KINDS:
            raise ValueError(f"{self.id}: unknown step kind {self.kind!r}")


FLOW: tuple[Step, ...] = (
    Step("p0", "phase", "Project type", (
        Question("project_type", "What do you want to build?", "choice",
                 options=("website", "saas", "design_ideas", "workflow",
                          "other", "not_sure")),
    )),
    Step("p_seed", "phase", "Project seed", (
        Question("seed_name", "Name this idea", "text"),
        Question("seed_intent", "Describe it in a paragraph", "longtext"),
        Question("seed_links", "Any links or references?", "list",
                 required=False),
    )),
    Step("p1", "phase", "Concept", (
        Question("project_name", "Name the project", "text"),
        Question("concept_what", "What does the app do?", "longtext"),
        Question("concept_who", "Who is it for?", "longtext"),
        Question("concept_problem", "What problem does it solve?", "longtext"),
        Question("concept_similar", "Similar products you like", "list",
                 required=False),
        Question("features_must", "Must-have features", "list"),
        Question("features_nice", "Nice-to-have features", "list",
                 required=False),
        Question("non_goals", "What should this app NOT try to do?", "list"),
    )),
    Step("r_reality", "research", "Reality check"),
    Step("cp_concept", "checkpoint", "Concept review"),
    Step("p2", "phase", "Features", (
        Question("capabilities", "Which capabilities does it need?", "multi",
                 options=("accounts_auth", "payments", "admin_panel",
                          "notifications", "file_uploads", "search",
                          "realtime"),
                 required=False),
        Question("feature_notes", "Notes on any feature", "longtext",
                 required=False),
    )),
    Step("p3", "phase", "Stack", (
        Question("stack_choice", "Do you have a stack in mind?", "choice",
                 options=("template", "custom", "no_preference")),
        Question("stack_template", "Which template?", "text",
                 show_if=(("stack_choice", ("template",)),)),
        Question("stack_custom", "Describe your stack", "longtext",
                 show_if=(("stack_choice", ("custom",)),)),
    )),
    Step("cp_stack", "checkpoint", "Stack review"),
    Step("p4", "phase", "Design", (
        Question("design_urls", "Reference URLs", "list", required=False),
        Question("design_uploads", "Upload images", "uploads",
                 required=False),
        Question("color_direction", "Color direction", "choice",
                 options=("pick", "upload", "propose"), default="propose"),
        Question("style_words", "Style words (minimal, playful, ...)",
                 "list", required=False),
        Question("design_notes", "Design notes", "longtext", required=False),
    )),
    Step("p5", "phase", "Practicalities", (
        Question("repo_mode", "Fresh repo or existing?", "choice",
                 options=("fresh", "existing")),
        Question("deploy_intent", "Where will it run?", "choice",
                 options=("local", "vps", "platform"), default="local"),
        Question("cadence", "Build cadence", "choice",
                 options=("relay", "continuous", "supervised"),
                 default="continuous"),
        Question("cadence_n", "Pause for approval every N features", "text",
                 default="4", required=False),
    )),
    Step("cp_final", "checkpoint", "Final rundown"),
)


def step_applies(step: Step, project_type: str | None) -> bool:
    """Route by project type: seed types skip the full interview (D9).
    An unrecognized type raises — the wizard's choice validation makes it
    unreachable through submit(), so reaching it means corrupt state."""
    if step.id == "p0":
        return True
    if project_type is None:
        return False
    if project_type in APP_PROJECT_TYPES:
        return step.id != "p_seed"
    if project_type in SEED_PROJECT_TYPES:
        return step.id == "p_seed"
    raise ValueError(f"unknown project_type: {project_type!r}")
