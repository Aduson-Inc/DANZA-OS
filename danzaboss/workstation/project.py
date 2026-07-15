"""PROJECT backend: discovery, takeover audit, scope, and build gates."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from .product_scope import (
    FEATURES_JSON_RELPATH,
    RevisionConflict,
    approve_scope,
    load_scope,
    new_scope,
    revise_scope,
    write_scope,
)


PROJECT_STATE_RELPATH = Path(".danza") / "onboarding" / "project.json"
TAKEOVER_AUDIT_RELPATH = (
    Path(".danza") / "onboarding" / "takeover-audit.json"
)
PROJECT_MODES = frozenset({"new", "existing"})

_SUPPORTED_SOURCE_EXTENSIONS = frozenset({
    ".c", ".cc", ".cpp", ".cxx", ".go", ".h", ".hh", ".hpp",
    ".java", ".js", ".jsx", ".mjs", ".cjs", ".py", ".pyw", ".rb",
    ".rs", ".ts", ".tsx",
})
_UNSUPPORTED_SOURCE_EXTENSIONS = frozenset({
    ".cs", ".dart", ".ex", ".exs", ".kt", ".php", ".scala", ".sol",
    ".svelte", ".swift", ".vue",
})
_MANIFEST_NAMES = frozenset({
    "Cargo.toml", "Gemfile", "go.mod", "package.json", "pom.xml",
    "pyproject.toml", "requirements.txt", "setup.cfg", "setup.py",
})
_CONFIG_NAMES = frozenset({
    ".editorconfig", ".env.example", ".gitignore", "Dockerfile",
    "Makefile", "docker-compose.yml", "docker-compose.yaml", "tox.ini",
})
_CONFIG_EXTENSIONS = frozenset({".ini", ".json", ".toml", ".yaml", ".yml"})
_DOC_EXTENSIONS = frozenset({".md", ".mdx", ".rst"})


class ProjectGateConflict(ValueError):
    """PROJECT lifecycle phase or acknowledgement is not yet satisfied."""


class ProjectRevisionConflict(RevisionConflict):
    """A PROJECT write targets stale discovery or product-scope state."""


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _load_json(path: Path, label: str) -> dict:
    if not path.exists():
        raise ProjectGateConflict(f"{label} has not been created")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectGateConflict(f"{label} is corrupt: {exc}") from exc
    if not isinstance(value, dict):
        raise ProjectGateConflict(f"{label} must be a JSON object")
    return value


def _git(root: Path, *args: str, binary: bool = False):
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=not binary,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout


def _tracked_files(root: Path) -> list[str]:
    raw = _git(root, "ls-files", "-z", binary=True)
    if raw is None:
        return []
    return sorted(
        item.decode("utf-8", errors="surrogateescape")
        for item in raw.split(b"\0") if item
    )


def _repository_fingerprint(root: Path) -> tuple[str | None, str, list[str]]:
    head_raw = _git(root, "rev-parse", "HEAD")
    head = head_raw.strip() if isinstance(head_raw, str) else None
    tracked = _tracked_files(root)
    if head is None:
        payload = "\0".join(tracked).encode("utf-8", errors="surrogateescape")
    else:
        diff = _git(root, "diff", "--binary", "HEAD", "--", binary=True)
        payload = head.encode("ascii") + b"\0" + (diff or b"")
    return head, hashlib.sha256(payload).hexdigest(), tracked


def _paths_with(root: Path, tracked: list[str], predicate) -> list[str]:
    return [path for path in tracked if predicate(path, root / path)]


def _source_graph(root: Path, source_files: list[str]) -> dict:
    """Return deterministic file nodes and conservative textual edges."""
    known_stems = {Path(path).stem: path for path in source_files}
    edges: set[tuple[str, str]] = set()
    for path in source_files:
        try:
            text = (root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for stem, target in known_stems.items():
            if target == path:
                continue
            markers = (f"import {stem}", f"from {stem} import",
                       f"require('{stem}')", f'require("{stem}")',
                       f"from './{stem}'", f'from "./{stem}"')
            if any(marker in text for marker in markers):
                edges.add((path, target))
    return {"nodes": source_files,
            "edges": [[source, target] for source, target in sorted(edges)]}


def _audit_payload(root: Path, head: str | None, fingerprint: str,
                   tracked: list[str]) -> dict:
    source_candidates = [
        path for path in tracked
        if Path(path).suffix.lower()
        in _SUPPORTED_SOURCE_EXTENSIONS | _UNSUPPORTED_SOURCE_EXTENSIONS
    ]
    supported = [path for path in source_candidates
                 if Path(path).suffix.lower() in _SUPPORTED_SOURCE_EXTENSIONS]
    unsupported = [path for path in source_candidates
                   if Path(path).suffix.lower() in _UNSUPPORTED_SOURCE_EXTENSIONS]
    dirty_raw = _git(root, "status", "--porcelain", "--untracked-files=no")
    branch_raw = _git(root, "branch", "--show-current")
    history_raw = _git(root, "log", "-20", "--format=%H%x09%s")
    history = history_raw.splitlines() if isinstance(history_raw, str) else []
    danza_root = root / ".danza"
    danza_artifacts = []
    if danza_root.exists():
        danza_artifacts = sorted(
            str(path.relative_to(root)) for path in danza_root.rglob("*")
            if path.is_file()
        )
    manifests = _paths_with(
        root, tracked, lambda path, _full: Path(path).name in _MANIFEST_NAMES)
    tests = _paths_with(
        root, tracked,
        lambda path, _full: (
            "tests" in Path(path).parts
            or Path(path).name.startswith("test_")
            or Path(path).stem.endswith("_test")
            or Path(path).stem.endswith(".test")
            or Path(path).stem.endswith(".spec")
        ),
    )
    config = _paths_with(
        root, tracked,
        lambda path, _full: (
            Path(path).name in _CONFIG_NAMES
            or Path(path).suffix.lower() in _CONFIG_EXTENSIONS
        ),
    )
    docs = _paths_with(
        root, tracked,
        lambda path, _full: Path(path).suffix.lower() in _DOC_EXTENSIONS,
    )
    unsupported_extensions = sorted(
        {Path(path).suffix.lower() for path in unsupported}
    )
    gaps = [
        {"id": f"analyzer:{extension}", "kind": "analyzer_coverage",
         "detail": f"No source analyzer is available for {extension} files."}
        for extension in unsupported_extensions
    ]
    if head is None:
        gaps.append({
            "id": "git:unavailable", "kind": "git",
            "detail": "Git HEAD and tracked-worktree evidence are unavailable.",
        })
    total = len(source_candidates)
    percent = 100 if total == 0 else len(supported) * 100 // total
    evidence = {
        "repository": {"root": str(root.resolve()),
                       "tracked_files": len(tracked)},
        "git": {"branch": branch_raw.strip() if branch_raw else None,
                "tracked_changes": dirty_raw.splitlines() if dirty_raw else []},
        "manifests": manifests,
        "source_graph": _source_graph(root, supported),
        "tests": tests,
        "config": config,
        "docs": docs,
        "git_history": history,
        "danza_artifacts": danza_artifacts,
        "analyzer_coverage": {"supported": supported,
                              "unsupported": unsupported,
                              "percent": percent},
    }
    return {"version": 1, "head": head, "fingerprint": fingerprint,
            "evidence": evidence, "gaps": gaps}


def takeover_audit(root: str | os.PathLike) -> tuple[dict, bool]:
    root_path = Path(root)
    head, fingerprint, tracked = _repository_fingerprint(root_path)
    cache_path = root_path / TAKEOVER_AUDIT_RELPATH
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None
        if (isinstance(cached, dict)
                and cached.get("head") == head
                and cached.get("fingerprint") == fingerprint):
            return cached, True
    audit = _audit_payload(root_path, head, fingerprint, tracked)
    _atomic_json(cache_path, audit)
    return audit, False


def discover_project(root: str | os.PathLike, *, mode: str) -> dict:
    if mode not in PROJECT_MODES:
        raise ValueError(f"mode must be one of {sorted(PROJECT_MODES)!r}")
    audit = None
    cached = False
    if mode == "existing":
        audit, cached = takeover_audit(root)
    state = {"version": 1, "mode": mode,
             "audit_fingerprint": audit["fingerprint"] if audit else None,
             "acknowledged_gaps": []}
    _atomic_json(Path(root) / PROJECT_STATE_RELPATH, state)
    return {"mode": mode, "audit": audit, "cached": cached,
            "ready_for_scope": not (audit and audit["gaps"])}


def project_summary(root: str | os.PathLike) -> dict:
    state_path = Path(root) / PROJECT_STATE_RELPATH
    if not state_path.exists():
        return {"mode": None, "audit": None, "scope": None,
                "ready_for_scope": False}
    state = _load_json(state_path, "PROJECT discovery")
    audit = None
    if state.get("mode") == "existing":
        audit, _ = takeover_audit(root)
    scope = None
    if (Path(root) / FEATURES_JSON_RELPATH).exists():
        scope = load_scope(root)
    acknowledged = set(state.get("acknowledged_gaps", []))
    gaps = {gap["id"] for gap in (audit or {}).get("gaps", [])}
    current_discovery = (
        audit is None
        or state.get("audit_fingerprint") == audit["fingerprint"]
    )
    return {"mode": state.get("mode"), "audit": audit, "scope": scope,
            "ready_for_scope": current_discovery
            and gaps.issubset(acknowledged)}


def draft_scope(root: str | os.PathLike, *, features: list[dict],
                expected_revision: int | None = None,
                audit_fingerprint: str | None = None,
                acknowledged_gaps: list[str] | None = None) -> dict:
    state_path = Path(root) / PROJECT_STATE_RELPATH
    state = _load_json(state_path, "PROJECT discovery")
    if state.get("mode") == "existing":
        audit, _ = takeover_audit(root)
        if audit_fingerprint != audit["fingerprint"]:
            raise ProjectRevisionConflict(
                "takeover audit changed; discover the current repository "
                "revision before drafting scope"
            )
        required = {gap["id"] for gap in audit["gaps"]}
        supplied = set(acknowledged_gaps or [])
        if supplied != required:
            missing = sorted(required - supplied)
            unknown = sorted(supplied - required)
            raise ProjectGateConflict(
                f"material takeover gaps require exact acknowledgement "
                f"(missing {missing!r}, unknown {unknown!r})"
            )
        state["audit_fingerprint"] = audit["fingerprint"]
        state["acknowledged_gaps"] = sorted(supplied)
    elif audit_fingerprint is not None or acknowledged_gaps:
        raise ValueError("new projects do not accept takeover audit fields")

    scope_path = Path(root) / FEATURES_JSON_RELPATH
    if scope_path.exists():
        if type(expected_revision) is not int:
            raise ProjectRevisionConflict(
                "expected_revision is required when revising product scope")
        scope = revise_scope(root, expected_revision=expected_revision,
                             features=features)
    else:
        if expected_revision is not None:
            raise ProjectRevisionConflict(
                "expected_revision must be omitted for the first scope draft")
        scope = new_scope(features)
        write_scope(root, scope)
    _atomic_json(state_path, state)
    return scope


def approve_project_scope(root: str | os.PathLike, *,
                          expected_revision: int) -> dict:
    _load_json(Path(root) / PROJECT_STATE_RELPATH, "PROJECT discovery")
    return approve_scope(root, expected_revision=expected_revision)


def require_approved_scope(root: str | os.PathLike) -> dict:
    try:
        scope = load_scope(root)
    except ValueError as exc:
        raise ProjectGateConflict(
            "an approved product scope is required before decomposition or build"
        ) from exc
    approval = scope["approval"]
    if (approval["state"] != "approved"
            or approval["approved_revision"] != scope["revision"]):
        raise ProjectGateConflict(
            "the exact current product-scope revision must be approved before "
            "decomposition or build"
        )
    return scope


def scope_ref(scope: dict) -> str:
    return f"{FEATURES_JSON_RELPATH}#revision-{scope['revision']}"


def require_plan_matches_scope(root: str | os.PathLike,
                               plan: object) -> dict:
    scope = require_approved_scope(root)
    expected = scope_ref(scope)
    if not isinstance(plan, dict) or plan.get("spec_ref") != expected:
        raise ProjectGateConflict(
            f"build plan does not reference approved scope {expected}"
        )
    return scope
