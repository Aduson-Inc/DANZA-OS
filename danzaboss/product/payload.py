"""Canonical packaged APP_BUILD payload and named character roster.

Layer-0 OS_DEV never reads product prompts from repository-root ``.claude``
files. Both the scaffolder and dashboard resolve the same package resource,
and visible roster identity is parsed from the shipped prompt definitions.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from importlib.resources import files


class PayloadError(ValueError):
    """The installed product payload is missing or internally inconsistent."""


@dataclass(frozen=True)
class AgentDefinition:
    """User-visible identity sourced from one canonical agent prompt."""
    id: str
    name: str
    role: str
    responsibility: str
    work_type: str


# Order is product hierarchy. Work types are internal routing keys; names,
# roles, and responsibilities are deliberately not duplicated here.
_ACTIVE_AGENT_WORK_TYPES = (
    ("tony-d-orchestrator", "plan"),
    ("jonathan-builder", "build"),
    ("samantha-mapper", "map"),
    ("angela-auditor", "review"),
    ("bonnie-qa", "qa"),
    ("carmella-researcher", "research"),
    ("hank-designer", "design"),
    ("billy-security", "security"),
)
_HEADING = re.compile(r"^#\s+(.+?)\s+—\s+(.+?)\s*$", re.MULTILINE)


def payload_root():
    """Return the sole packaged source for shipped APP_BUILD content."""
    root = files("danzaboss.product") / "templates" / "scaffold"
    if not root.is_dir():
        raise PayloadError("bundled scaffold payload missing - reinstall danza-os")
    for required in ("claude", "danza"):
        if not (root / required).is_dir():
            raise PayloadError(
                f"payload dir {required!r} missing - reinstall danza-os")
    return root


def _description(text: str, agent_id: str) -> str:
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise PayloadError(f"agent {agent_id!r} has invalid frontmatter")
    frontmatter = text.split("\n---\n", 1)[0][4:]
    for line in frontmatter.splitlines():
        if line.startswith("description:"):
            value = line.split(":", 1)[1].strip()
            try:
                description = json.loads(value)
            except json.JSONDecodeError as exc:
                raise PayloadError(
                    f"agent {agent_id!r} description must be JSON quoted") from exc
            if isinstance(description, str) and description.strip():
                return description.strip()
    raise PayloadError(f"agent {agent_id!r} has no description")


@lru_cache(maxsize=1)
def _definitions() -> tuple[AgentDefinition, ...]:
    directory = payload_root() / "claude" / "agents"
    expected = {f"{agent_id}.md" for agent_id, _ in _ACTIVE_AGENT_WORK_TYPES}
    actual = {child.name for child in directory.iterdir()
              if child.name.endswith(".md")}
    if actual != expected:
        raise PayloadError(
            "active agent prompt set mismatch: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}")
    definitions = []
    for agent_id, work_type in _ACTIVE_AGENT_WORK_TYPES:
        text = (directory / f"{agent_id}.md").read_text(encoding="utf-8")
        heading = _HEADING.search(text)
        if heading is None:
            raise PayloadError(f"agent {agent_id!r} has no Name — Role heading")
        definitions.append(AgentDefinition(
            id=agent_id,
            name=heading.group(1).strip(),
            role=heading.group(2).strip(),
            responsibility=_description(text, agent_id),
            work_type=work_type,
        ))
    return tuple(definitions)


def agent_roster() -> list[dict[str, str]]:
    """Return a fresh JSON-ready roster in canonical hierarchy order."""
    return [asdict(definition) for definition in _definitions()]
