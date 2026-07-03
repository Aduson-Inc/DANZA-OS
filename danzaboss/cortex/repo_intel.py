"""Repo intelligence — stdlib language analyzers feeding the knowledge graph (C4).

LanguageAnalyzerPort is the adapter seam (spec D7): the defaults are ast for
Python and honest regexes for JS/TS; a tree-sitter adapter can bind later
without touching scan_repo. Imports are resolved file-to-file wherever the
target lives in the repo, so impact closures ("what breaks if X changes")
run directly over file nodes.

Stdlib only.
"""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from .graph import GraphStore, node_id

IGNORE_DIRS = frozenset({".git", "__pycache__", "node_modules", ".danza",
                         ".claude", "venv", ".venv", "dist", "build",
                         ".pytest_cache", ".mypy_cache"})
_MAX_FILE_BYTES = 1_000_000  # generated/vendored monsters are not intelligence


@dataclass
class FileIntel:
    path: str
    module: str = ""
    imports: list[str] = field(default_factory=list)
    symbols: list[tuple[str, str]] = field(default_factory=list)


class LanguageAnalyzerPort:
    """Adapter seam: subclass with extensions + analyze()."""
    extensions: tuple[str, ...] = ()

    def analyze(self, path: str, source: str) -> FileIntel:
        raise NotImplementedError


def _py_module(path: str) -> str:
    parts = path[:-3].split("/") if path.endswith(".py") else path.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


class PythonAnalyzer(LanguageAnalyzerPort):
    extensions = (".py",)

    def analyze(self, path: str, source: str) -> FileIntel:
        module = _py_module(path)
        fi = FileIntel(path=path, module=module)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return fi  # broken file -> no intel, never a crash
        pkg = module.split(".")[:-1]
        for stmt in tree.body:
            if isinstance(stmt, ast.Import):
                fi.imports += [a.name for a in stmt.names]
            elif isinstance(stmt, ast.ImportFrom):
                if stmt.level:
                    base = pkg[:len(pkg) - (stmt.level - 1)] if stmt.level > 1 else pkg
                    if stmt.module:
                        fi.imports.append(".".join(base + stmt.module.split(".")))
                    else:
                        fi.imports += [".".join(base + [a.name])
                                       for a in stmt.names]
                elif stmt.module:
                    fi.imports += [f"{stmt.module}.{a.name}" for a in stmt.names]
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fi.symbols.append(("function", stmt.name))
            elif isinstance(stmt, ast.ClassDef):
                fi.symbols.append(("class", stmt.name))
        return fi


class RegexAnalyzer(LanguageAnalyzerPort):
    extensions = (".js", ".mjs", ".jsx", ".ts", ".tsx")
    _IMPORT = re.compile(
        r"""(?:import\s[^'"]*?from\s*|import\s*\(\s*|require\s*\(\s*)['"]([^'"]+)['"]""")
    _SYMBOL = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(function|class)\s+"
        r"([A-Za-z_$][\w$]*)", re.MULTILINE)

    def analyze(self, path: str, source: str) -> FileIntel:
        fi = FileIntel(path=path)
        fi.imports = list(dict.fromkeys(self._IMPORT.findall(source)))
        fi.symbols = [(kind, name) for kind, name in self._SYMBOL.findall(source)]
        return fi


def _default_analyzers() -> list[LanguageAnalyzerPort]:
    return [PythonAnalyzer(), RegexAnalyzer()]


def _resolve_python(imp: str, module_map: dict[str, str]) -> Optional[str]:
    """Try the full dotted name, then its parent (from a.b import symbol)."""
    if imp in module_map:
        return module_map[imp]
    parent = imp.rsplit(".", 1)[0]
    return module_map.get(parent)


def _resolve_relative_js(imp: str, src_path: str,
                         files: set[str]) -> Optional[str]:
    base = os.path.normpath(os.path.join(os.path.dirname(src_path), imp))
    base = base.replace(os.sep, "/")
    candidates = [base] + [base + ext for ext in RegexAnalyzer.extensions] \
        + [f"{base}/index{ext}" for ext in RegexAnalyzer.extensions]
    for cand in candidates:
        if cand in files:
            return cand
    return None


def scan_repo(root: str, project: str, graph: GraphStore,
              analyzers: Optional[list[LanguageAnalyzerPort]] = None) -> dict:
    """Walk root, analyze every recognized file, populate the graph."""
    analyzers = analyzers if analyzers is not None else _default_analyzers()
    by_ext = {ext: a for a in analyzers for ext in a.extensions}
    intels: list[FileIntel] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORE_DIRS)
        for fname in sorted(filenames):
            ext = os.path.splitext(fname)[1]
            analyzer = by_ext.get(ext)
            if analyzer is None:
                continue
            full = os.path.join(dirpath, fname)
            try:
                if os.path.getsize(full) > _MAX_FILE_BYTES:
                    continue
                with open(full, encoding="utf-8", errors="replace") as fh:
                    source = fh.read()
            except OSError:
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            intels.append(analyzer.analyze(rel, source))

    module_map = {fi.module: fi.path for fi in intels if fi.module}
    file_set = {fi.path for fi in intels}
    stats = {"files": 0, "modules": 0, "symbols": 0,
             "imports_resolved": 0, "imports_external": 0}

    for fi in intels:
        lang = "python" if fi.path.endswith(".py") else "javascript"
        fid = graph.add_node("file", fi.path, project, language=lang)
        stats["files"] += 1
        if fi.module:
            graph.add_node("module", fi.module, project, file=fi.path)
            stats["modules"] += 1
        for sym_kind, name in fi.symbols:
            sid = graph.add_node("symbol", f"{fi.path}::{name}", project,
                                 sym_kind=sym_kind)
            graph.add_edge(fid, sid, "declares")
            stats["symbols"] += 1
        for imp in fi.imports:
            if imp.startswith("."):
                target = _resolve_relative_js(imp, fi.path, file_set)
            else:
                target = _resolve_python(imp, module_map)
            if target:
                graph.add_edge(fid, node_id("file", target), "imports",
                               evidence=imp)
                stats["imports_resolved"] += 1
            else:
                mid = graph.add_node("module", imp, project, external=True)
                graph.add_edge(fid, mid, "imports")
                stats["imports_external"] += 1
    return stats
