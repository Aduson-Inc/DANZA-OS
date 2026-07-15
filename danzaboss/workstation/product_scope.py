"""Validated product-scope artifacts for the DANZA workstation.

``features.json`` is the authority. ``feature-list.md`` is always rendered
from the validated JSON shape and is never read as state.
"""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path


SCHEMA_VERSION = 1
FEATURES_JSON_RELPATH = Path(".danza") / "features.json"
FEATURE_LIST_RELPATH = Path(".danza") / "feature-list.md"

FEATURE_STATUSES = frozenset({"pending", "in_progress", "blocked",
                              "completed"})
APPROVAL_STATES = frozenset({"draft", "approved"})

_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+(?:\s|$)|[^.!?]+$")


class ProductScopeError(ValueError):
    """The product scope is missing, corrupt, or violates its contract."""


class RevisionConflict(ProductScopeError):
    """The caller acted on a revision that is no longer current."""


def _require_exact_keys(value: dict, expected: set[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise ProductScopeError(
            f"{label} keys must be exactly {sorted(expected)!r} "
            f"(missing {missing!r}, unexpected {extra!r})")


def validate_scope(scope: object) -> dict:
    """Validate and return a product-scope document, failing closed."""
    if not isinstance(scope, dict):
        raise ProductScopeError("product scope must be a JSON object")
    _require_exact_keys(scope, {"version", "revision", "approval",
                                "features"}, "product scope")
    if type(scope["version"]) is not int or scope["version"] != SCHEMA_VERSION:
        raise ProductScopeError(
            f"product scope version must be {SCHEMA_VERSION}")
    revision = scope["revision"]
    if type(revision) is not int or revision < 1:
        raise ProductScopeError("product scope revision must be a positive integer")

    approval = scope["approval"]
    if not isinstance(approval, dict):
        raise ProductScopeError("product scope approval must be an object")
    _require_exact_keys(approval, {"state", "approved_revision"}, "approval")
    if (not isinstance(approval["state"], str)
            or approval["state"] not in APPROVAL_STATES):
        raise ProductScopeError(
            f"approval.state must be one of {sorted(APPROVAL_STATES)!r}")
    approved_revision = approval["approved_revision"]
    if approval["state"] == "draft" and approved_revision is not None:
        raise ProductScopeError("draft scope cannot have an approved revision")
    if (approval["state"] == "approved"
            and (type(approved_revision) is not int
                 or approved_revision != revision)):
        raise ProductScopeError(
            "approved scope must name its exact current revision")

    features = scope["features"]
    if not isinstance(features, list) or not features:
        raise ProductScopeError("product scope features must be a non-empty array")
    seen: set[int] = set()
    for index, feature in enumerate(features):
        label = f"features[{index}]"
        if not isinstance(feature, dict):
            raise ProductScopeError(f"{label} must be an object")
        _require_exact_keys(feature, {"id", "summary", "acceptance_criteria",
                                      "status"}, label)
        feature_id = feature["id"]
        if type(feature_id) is not int or feature_id < 1:
            raise ProductScopeError(f"{label}.id must be a positive integer")
        if feature_id in seen:
            raise ProductScopeError(f"duplicate product feature id {feature_id}")
        seen.add(feature_id)
        summary = feature["summary"]
        if not isinstance(summary, str) or not summary.strip():
            raise ProductScopeError(f"{label}.summary must be a non-empty string")
        if len(summary.strip()) > 300:
            raise ProductScopeError(f"{label}.summary must be concise (max 300 chars)")
        sentence_count = len(_SENTENCE_RE.findall(summary.strip()))
        if sentence_count not in (1, 2):
            raise ProductScopeError(
                f"{label}.summary must contain one or two sentences")
        criteria = feature["acceptance_criteria"]
        if (not isinstance(criteria, list) or not criteria
                or not all(isinstance(item, str) and item.strip()
                           for item in criteria)):
            raise ProductScopeError(
                f"{label}.acceptance_criteria must be a non-empty array "
                "of non-empty strings")
        if (not isinstance(feature["status"], str)
                or feature["status"] not in FEATURE_STATUSES):
            raise ProductScopeError(
                f"{label}.status must be one of {sorted(FEATURE_STATUSES)!r}")
    return scope


def new_scope(features: list[dict]) -> dict:
    """Create revision 1 of an unapproved product scope."""
    scope = {"version": SCHEMA_VERSION, "revision": 1,
             "approval": {"state": "draft", "approved_revision": None},
             "features": copy.deepcopy(features)}
    return validate_scope(scope)


def load_scope(root: str | os.PathLike) -> dict:
    """Load authoritative scope JSON; missing or corrupt data is unusable."""
    path = Path(root) / FEATURES_JSON_RELPATH
    if not path.exists():
        raise ProductScopeError(f"product scope not found at {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ProductScopeError(f"corrupt product scope at {path}: {exc}") from exc
    try:
        return validate_scope(raw)
    except ProductScopeError as exc:
        raise ProductScopeError(f"corrupt product scope at {path}: {exc}") from exc


def render_feature_list_md(scope: dict) -> str:
    """Render the disposable human view from validated authority."""
    validate_scope(scope)
    approval = scope["approval"]
    progress = derive_progress(scope)
    approval_text = approval["state"]
    if approval["approved_revision"] is not None:
        approval_text += f" (revision {approval['approved_revision']})"
    else:
        approval_text += " (not approved)"
    lines = ["# Product features", "",
             "> Generated from `.danza/features.json`; do not edit this view.",
             "", f"Revision: {scope['revision']}",
             f"Approval: {approval_text}",
             f"Progress: {progress['completed']}/{progress['total']} "
             f"({progress['percent']}%) — {progress['status']}", ""]
    for feature in scope["features"]:
        mark = "x" if feature["status"] == "completed" else " "
        lines += [f"- [{mark}] **{feature['id']} — {feature['summary']}**",
                  f"  Status: {feature['status']}", "", "  <details>",
                  "  <summary>Acceptance criteria</summary>", ""]
        lines += [f"  - {criterion}"
                  for criterion in feature["acceptance_criteria"]]
        lines += ["", "  </details>", ""]
    return "\n".join(lines).rstrip() + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def derive_progress(scope: dict) -> dict:
    """Derive aggregate product status and progress from feature statuses."""
    validate_scope(scope)
    statuses = [feature["status"] for feature in scope["features"]]
    completed = statuses.count("completed")
    if completed == len(statuses):
        status = "completed"
    elif "blocked" in statuses:
        status = "blocked"
    elif all(value == "pending" for value in statuses):
        status = "pending"
    else:
        status = "in_progress"
    return {"status": status, "completed": completed,
            "total": len(statuses),
            "percent": completed * 100 // len(statuses)}


def _definitions(scope: dict) -> list[dict]:
    """Scope content whose edits require a new revision."""
    return [{key: feature[key]
             for key in ("id", "summary", "acceptance_criteria")}
            for feature in scope["features"]]


def _validate_transition(current: dict, candidate: dict) -> None:
    """Reject bypasses of revision, approval, and completion invariants."""
    current_revision = current["revision"]
    candidate_revision = candidate["revision"]
    current_by_id = {feature["id"]: feature
                     for feature in current["features"]}
    candidate_by_id = {feature["id"]: feature
                       for feature in candidate["features"]}

    for feature_id, feature in current_by_id.items():
        if feature["status"] == "completed":
            if candidate_by_id.get(feature_id) != feature:
                raise ProductScopeError(
                    f"completed product feature {feature_id} is immutable")

    if candidate_revision == current_revision:
        if _definitions(candidate) != _definitions(current):
            raise RevisionConflict(
                "product scope content changed without a new revision")
        old_approval = current["approval"]
        new_approval = candidate["approval"]
        approval_unchanged = new_approval == old_approval
        exact_approval = (
            old_approval == {"state": "draft", "approved_revision": None}
            and new_approval == {"state": "approved",
                                 "approved_revision": current_revision}
        )
        if not (approval_unchanged or exact_approval):
            raise RevisionConflict("invalid approval transition")
        return

    if candidate_revision != current_revision + 1:
        raise RevisionConflict(
            f"scope revision {candidate_revision} does not follow current "
            f"revision {current_revision}")
    if candidate["approval"] != {"state": "draft", "approved_revision": None}:
        raise RevisionConflict("a revised scope must return to draft approval")
    if derive_progress(current)["status"] == "completed":
        raise ProductScopeError("completed product scope is immutable")


def write_scope(root: str | os.PathLike, scope: dict) -> tuple[Path, Path]:
    """Validate and atomically replace authority and its generated view.

    If authority already exists it is read and validated first. Corruption is
    never healed implicitly, and revision/completion rules cannot be bypassed
    through this low-level persistence interface.
    """
    validate_scope(scope)
    json_path = Path(root) / FEATURES_JSON_RELPATH
    md_path = Path(root) / FEATURE_LIST_RELPATH
    if json_path.exists():
        _validate_transition(load_scope(root), scope)
    _atomic_write(json_path, json.dumps(scope, indent=2, sort_keys=True) + "\n")
    _atomic_write(md_path, render_feature_list_md(scope))
    return json_path, md_path


def revise_scope(root: str | os.PathLike, *, expected_revision: int,
                 features: list[dict]) -> dict:
    """Replace editable scope content as the next draft revision."""
    current = load_scope(root)
    if (type(expected_revision) is not int
            or expected_revision != current["revision"]):
        raise RevisionConflict(
            f"stale scope revision {expected_revision!r}; current revision "
            f"is {current['revision']}")
    candidate = {"version": SCHEMA_VERSION,
                 "revision": current["revision"] + 1,
                 "approval": {"state": "draft", "approved_revision": None},
                 "features": copy.deepcopy(features)}
    validate_scope(candidate)
    write_scope(root, candidate)
    return candidate


def approve_scope(root: str | os.PathLike, *, expected_revision: int) -> dict:
    """Approve only the exact revision the caller reviewed."""
    current = load_scope(root)
    if (type(expected_revision) is not int
            or expected_revision != current["revision"]):
        raise RevisionConflict(
            f"stale scope revision {expected_revision!r}; current revision "
            f"is {current['revision']}")
    if current["approval"]["state"] != "draft":
        raise RevisionConflict(
            f"scope revision {expected_revision} is already approved")
    approved = copy.deepcopy(current)
    approved["approval"] = {"state": "approved",
                            "approved_revision": expected_revision}
    write_scope(root, approved)
    return approved
