"""Repo scanner — learns an AppProfile from ANY real app directory.

Language-agnostic heuristics (stdlib only): detect languages by file extension,
frameworks/databases by manifest files, entry points by common names. This is the
"learn my app" step that feeds the AppProfile (and later Samantha's richer map).
Deliberately cheap and dependency-free; a tree-sitter analyzer can replace it later
behind the same output (ScanFacts).
"""
from __future__ import annotations

import os
from collections import Counter

from ..cortex.app_profile import ScanFacts, AppProfile, learn_profile

_LANG_BY_EXT = {
    ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript",
    ".jsx": "JavaScript", ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".java": "Java",
    ".kt": "Kotlin", ".swift": "Swift", ".php": "PHP", ".cs": "C#", ".c": "C", ".cpp": "C++",
}
_MANIFEST_FRAMEWORK = {
    "package.json": None,          # resolved by dependency sniff below
    "requirements.txt": "Python", "pyproject.toml": "Python", "go.mod": "Go",
    "Cargo.toml": "Rust", "Gemfile": "Ruby", "pom.xml": "Java",
}
_FRAMEWORK_HINTS = {
    "next": "Next.js", "react": "React", "vue": "Vue", "svelte": "Svelte",
    "express": "Express", "fastapi": "FastAPI", "flask": "Flask", "django": "Django",
    "gin": "gin", "rails": "Rails",
}
_DB_HINTS = {"neon": "Neon/Postgres", "postgres": "Postgres", "sqlite": "SQLite",
             "mysql": "MySQL", "mongodb": "MongoDB", "prisma": "Prisma", "supabase": "Supabase"}
_ENTRY_NAMES = {"main.py", "app.py", "index.ts", "index.js", "main.go", "main.rs",
                "app/page.tsx", "src/main.tsx", "src/index.ts"}
_IGNORE = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}


def scan_repo(root: str, *, max_files: int = 20000) -> ScanFacts:
    ext_counter: Counter = Counter()
    frameworks: set[str] = set()
    databases: set[str] = set()
    entry_points: list[str] = []
    feature_dirs: Counter = Counter()
    seen = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORE]
        rel_dir = os.path.relpath(dirpath, root)
        for fn in filenames:
            seen += 1
            if seen > max_files:
                break
            ext = os.path.splitext(fn)[1].lower()
            if ext in _LANG_BY_EXT:
                ext_counter[_LANG_BY_EXT[ext]] += 1
            rel = os.path.normpath(os.path.join(rel_dir, fn)) if rel_dir != "." else fn
            if fn in _ENTRY_NAMES or rel in _ENTRY_NAMES:
                entry_points.append(rel)
            if fn in _MANIFEST_FRAMEWORK:
                _sniff_manifest(os.path.join(dirpath, fn), frameworks, databases)
            # crude feature grouping: top-level source dirs
            top = rel.split(os.sep)[0]
            if top not in (".",) and not top.startswith("."):
                feature_dirs[top] += 1

    languages = [lang for lang, _ in ext_counter.most_common()]
    # infer features from prominent source subdirectories (heuristic, refined later)
    features = [{"name": name, "description": f"module: {name}",
                 "files": []} for name, cnt in feature_dirs.most_common(8)
                if cnt >= 2 and name not in ("tests", "test", "docs", "public", "assets")]
    return ScanFacts(languages=languages, frameworks=sorted(frameworks),
                     databases=sorted(databases), entry_points=entry_points[:10],
                     detected_features=features)


def _sniff_manifest(path: str, frameworks: set, databases: set) -> None:
    try:
        text = open(path, encoding="utf-8", errors="ignore").read().lower()
    except OSError:
        return
    for key, name in _FRAMEWORK_HINTS.items():
        if key in text:
            frameworks.add(name)
    for key, name in _DB_HINTS.items():
        if key in text:
            databases.add(name)


def profile_repo(project: str, root: str, *, domain: str = "",
                 goals: list[str] | None = None,
                 big_feature_names: set[str] | None = None) -> AppProfile:
    """Scan a real repo and produce an AppProfile — the whole 'learn my app' step."""
    facts = scan_repo(root)
    return learn_profile(project, facts, domain=domain, goals=goals or [],
                         big_feature_names=big_feature_names or set())
