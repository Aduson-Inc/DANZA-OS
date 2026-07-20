"""Canonical packaged APP_BUILD payload and named character roster.

Layer-0 OS_DEV never reads product prompts from repository-root ``.claude``
files. Both the scaffolder and dashboard resolve the same package resource,
and visible roster identity is parsed from the shipped prompt definitions.
"""
from __future__ import annotations

import json
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
_WORK_TYPES = dict(_ACTIVE_AGENT_WORK_TYPES)


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


@lru_cache(maxsize=1)
def _definitions() -> tuple[AgentDefinition, ...]:
    try:
        manifest = json.loads(
            (files("danzaboss.agents") / "definitions.json")
            .read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PayloadError(f"agent definition manifest unavailable: {exc}") from exc
    if manifest.get("schema_version") != 1:
        raise PayloadError("unsupported agent definition manifest schema")
    entries = {entry.get("id"): entry for entry in manifest.get("agents", [])}
    expected = set(_WORK_TYPES)
    if set(entries) != expected:
        raise PayloadError(
            "canonical agent definition set mismatch: "
            f"missing={sorted(expected - set(entries))}, "
            f"extra={sorted(set(entries) - expected)}")
    definitions = []
    for agent_id, work_type in _ACTIVE_AGENT_WORK_TYPES:
        entry = entries[agent_id]
        if not all(isinstance(entry.get(key), str) and entry[key].strip()
                   for key in ("display_name", "role", "responsibility")):
            raise PayloadError(f"agent {agent_id!r} has invalid identity fields")
        definitions.append(AgentDefinition(
            id=agent_id,
            name=entry["display_name"],
            role=entry["role"],
            responsibility=entry["responsibility"],
            work_type=work_type,
        ))
    return tuple(definitions)


def agent_roster() -> list[dict[str, str]]:
    """Return a fresh JSON-ready roster in canonical hierarchy order."""
    return [asdict(definition) for definition in _definitions()]
