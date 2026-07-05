"""Stack template library (design spec section 5).

Templates are DATA files: proven combinations, never pinned versions (the
planner resolves versions at build time, so templates don't rot). The
library evolves by adding files — research or checkpoints propose, the
user approves (Constitution Rule 21).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DIR = Path(__file__).parent / "templates" / "stacks"

REQUIRED_FIELDS = ("name", "tagline", "best_for", "components", "why",
                   "tradeoffs", "avoid_when", "testing_defaults",
                   "philosophy_fit", "rank")

# Presence alone is not fail-closed: a string best_for or a string rank
# loads fine and explodes later inside select_templates — past bad state.
_FIELD_TYPES = {"name": str, "tagline": str, "best_for": dict,
                "components": dict, "why": str, "tradeoffs": str,
                "avoid_when": str, "testing_defaults": dict,
                "philosophy_fit": str, "rank": int}


@dataclass(frozen=True)
class StackTemplate:
    """One proven combination. `key` is the filename stem — the stable id
    the wizard stores in answers (stack_template)."""
    key: str
    name: str
    tagline: str
    best_for: dict
    components: dict
    why: str
    tradeoffs: str
    avoid_when: str
    testing_defaults: dict
    philosophy_fit: str
    rank: int


def load_templates(directory: str | Path = DEFAULT_DIR
                   ) -> tuple[StackTemplate, ...]:
    """Load and validate every *.json template. Fail closed on a bad or
    empty library — a silent fallback would let onboarding recommend
    from nothing."""
    templates = []
    for path in sorted(Path(directory).glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = [f for f in REQUIRED_FIELDS if f not in data]
        if missing:
            raise ValueError(f"{path.name}: missing fields {missing}")
        for field, expected in _FIELD_TYPES.items():
            value = data[field]
            if isinstance(value, bool) or not isinstance(value, expected):
                raise ValueError(
                    f"{path.name}: field {field!r} must be "
                    f"{expected.__name__}, got {type(value).__name__}")
        templates.append(StackTemplate(
            key=path.stem, **{f: data[f] for f in REQUIRED_FIELDS}))
    if not templates:
        raise ValueError(f"no stack templates found in {directory}")
    return tuple(templates)


def select_templates(templates: tuple[StackTemplate, ...], project_type: str,
                     capabilities: list[str]) -> list[StackTemplate]:
    """Deterministic fit ranking: filter by project type, score by
    capability coverage, tie-break by declared rank then key. The wizard
    shows the top 2-3; Checkpoint 2 grounds its pushback in this list."""
    wanted = set(capabilities)
    fits = [t for t in templates
            if project_type in t.best_for.get("project_types", [])]

    def sort_key(t: StackTemplate) -> tuple:
        covered = len(wanted & set(t.best_for.get("capabilities", [])))
        return (-covered, t.rank, t.key)

    return sorted(fits, key=sort_key)
