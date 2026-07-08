# CORTEX C4 — Knowledge Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the CORTEX knowledge graph (typed nodes/edges + recursive-CTE traversal), repo/git intelligence that populates it, bind the live `graph` retrieval signal in `retrieve.py`, and expose a `/api/graph` endpoint + Graph explorer UI view.

**Architecture:** A `GraphStore` owns two new tables (`graph_nodes`, `graph_edges`) in the same repo-scoped `cortex.db`. `repo_intel.py` (stdlib `ast` for Python, regex for JS/TS) and `git_intel.py` (subprocess `git log`) populate it; `link_observations` bridges observations → files/commits. The stubbed `_sig_graph` in `retrieve.py` becomes live: changed files → impact closure → attached observations. RRF fusion needs no other change.

**Tech Stack:** Python 3.10+, stdlib only (`sqlite3`, `ast`, `re`, `subprocess`), vanilla JS/SVG for the UI. Tests via `unittest` in `danzaboss/tests/` run by `./danzaboss/run_tests.sh`.

## Global Constraints

- **Stdlib only** in `danzaboss/` — no pip installs (CLAUDE.md coding standards, spec D7).
- **Determinism** — no hidden randomness in traversal, ranking, or layout seeds.
- **Existing style is law** — PEP 8, 4-space, snake_case, type hints on public functions, module docstrings stating *why* (Rule 4).
- **Done-bar per task:** `./danzaboss/run_tests.sh` green (227 tests before this plan; count grows).
- Store gotcha: `store.upsert()` merges same-type observations with overlapping concept/file bags — seed test fixtures with **distinct types/concepts**.
- Tests import `_bootstrap` first (existing convention: `import _bootstrap  # noqa`).
- Repo root for tests: `os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))` from a file in `danzaboss/tests/`.
- Guard hard-stops `rm -rf` / force-push even with the Rule-37 sentinel — use `git rm`, plain `git push`.
- Commit message style: `feat(cortex): ...` / `test(cortex): ...` matching recent history; end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: `graph.py` — GraphStore with recursive-CTE traversal

**Files:**
- Create: `danzaboss/cortex/graph.py`
- Test: `danzaboss/tests/test_cortex_graph.py`

**Interfaces:**
- Produces (used by every later task):
  - `node_id(kind: str, name: str) -> str` — canonical id `"{kind}:{name}"`.
  - `class Node` (dataclass): `id, kind, name, project, attrs: dict`.
  - `class GraphStore(path: str = ":memory:")` with methods:
    - `add_node(kind: str, name: str, project: str = "", **attrs) -> str` (upserts, returns id; attrs merge over existing)
    - `add_edge(src: str, dst: str, relation: str, weight: float = 1.0, evidence: str = "") -> None` (upsert on `(src,dst,relation)`)
    - `node(nid: str) -> Optional[Node]`
    - `find(text: str, kinds: Optional[list[str]] = None, limit: int = 20) -> list[Node]` (case-insensitive substring on name)
    - `resolve_file(path: str) -> Optional[str]` (exact file-node name match, else unique suffix match)
    - `neighbors(nid: str, relation: Optional[str] = None) -> dict` with keys `"out"`/`"in"`, each a list of `(other_id, relation)`
    - `impact(nid: str, max_depth: int = 4, relations: tuple[str, ...] = ("imports",)) -> list[tuple[str, int]]` — reverse-dependency closure (who breaks if nid changes), `(node_id, min_depth)`, sorted by depth then id, excludes nid
    - `dependencies(nid: str, max_depth: int = 4, relations: tuple[str, ...] = ("imports",)) -> list[tuple[str, int]]` — forward closure
    - `path(src: str, dst: str, max_depth: int = 6) -> list[str]` — shortest path (BFS, edges followed in both directions is NOT wanted: follow src→dst direction only), `[]` if none
    - `attached_observations(nid: str) -> list[str]` — observation ids with an `about` edge into nid
    - `subgraph(nid: str, depth: int = 2, mode: str = "neighborhood") -> tuple[list[Node], list[dict]]` — for the UI; `mode="impact"` = impact closure + attached observation nodes; each edge dict `{"src","dst","relation"}`; nodes capped at 80
    - `clear(project: Optional[str] = None) -> None`
    - `stats(project: Optional[str] = None) -> dict` — `{"nodes": n, "edges": n, "by_kind": {...}}`

- [ ] **Step 1: Write the failing tests**

Create `danzaboss/tests/test_cortex_graph.py`:

```python
"""GraphStore: typed nodes/edges + recursive-CTE closures (C4, spec section 8).

The impact closure is the acceptance primitive: "what breaks if X changes" =
every node with a dependency path INTO X. Cycles must terminate (depth cap +
UNION dedupe) and results must be deterministic (depth, then id ordering).
"""
import unittest
import _bootstrap  # noqa
from danzaboss.cortex.graph import GraphStore, node_id


def diamond() -> GraphStore:
    """app -> lib_a -> core, app -> lib_b -> core (imports = depends-on)."""
    g = GraphStore(":memory:")
    for name in ("app.py", "lib_a.py", "lib_b.py", "core.py"):
        g.add_node("file", name, project="p")
    g.add_edge("file:app.py", "file:lib_a.py", "imports")
    g.add_edge("file:app.py", "file:lib_b.py", "imports")
    g.add_edge("file:lib_a.py", "file:core.py", "imports")
    g.add_edge("file:lib_b.py", "file:core.py", "imports")
    return g


class TestGraphStore(unittest.TestCase):
    def test_node_id_and_upsert(self):
        g = GraphStore(":memory:")
        nid = g.add_node("file", "a.py", project="p", language="python")
        self.assertEqual(nid, node_id("file", "a.py"))
        g.add_node("file", "a.py", project="p", size=10)  # attrs merge
        n = g.node(nid)
        self.assertEqual(n.attrs["language"], "python")
        self.assertEqual(n.attrs["size"], 10)
        self.assertEqual(g.stats()["nodes"], 1)

    def test_edge_upsert_no_duplicates(self):
        g = diamond()
        g.add_edge("file:app.py", "file:lib_a.py", "imports")  # again
        self.assertEqual(g.stats()["edges"], 4)

    def test_impact_is_reverse_dependency_closure(self):
        g = diamond()
        got = g.impact("file:core.py")
        self.assertEqual(got, [("file:lib_a.py", 1), ("file:lib_b.py", 1),
                               ("file:app.py", 2)])

    def test_dependencies_is_forward_closure(self):
        g = diamond()
        got = g.dependencies("file:app.py")
        self.assertEqual(got, [("file:lib_a.py", 1), ("file:lib_b.py", 1),
                               ("file:core.py", 2)])

    def test_cycle_terminates(self):
        g = GraphStore(":memory:")
        g.add_node("file", "a.py"); g.add_node("file", "b.py")
        g.add_edge("file:a.py", "file:b.py", "imports")
        g.add_edge("file:b.py", "file:a.py", "imports")
        self.assertEqual(g.impact("file:a.py"), [("file:b.py", 1)])

    def test_impact_respects_relations_filter(self):
        g = diamond()
        g.add_node("commit", "abc123")
        g.add_edge("commit:abc123", "file:core.py", "modifies")
        ids = {nid for nid, _ in g.impact("file:core.py")}
        self.assertNotIn("commit:abc123", ids)

    def test_neighbors_both_directions(self):
        g = diamond()
        n = g.neighbors("file:lib_a.py")
        self.assertIn(("file:core.py", "imports"), n["out"])
        self.assertIn(("file:app.py", "imports"), n["in"])

    def test_path_shortest(self):
        g = diamond()
        self.assertEqual(g.path("file:app.py", "file:core.py"),
                         ["file:app.py", "file:lib_a.py", "file:core.py"])
        self.assertEqual(g.path("file:core.py", "file:app.py"), [])

    def test_resolve_file_suffix(self):
        g = GraphStore(":memory:")
        g.add_node("file", "danzaboss/cortex/store.py")
        self.assertEqual(g.resolve_file("/home/x/repo/danzaboss/cortex/store.py"),
                         "file:danzaboss/cortex/store.py")
        self.assertEqual(g.resolve_file("danzaboss/cortex/store.py"),
                         "file:danzaboss/cortex/store.py")
        self.assertIsNone(g.resolve_file("nope.py"))

    def test_find_and_clear(self):
        g = diamond()
        hits = g.find("lib", kinds=["file"])
        self.assertEqual({n.name for n in hits}, {"lib_a.py", "lib_b.py"})
        g.clear("p")
        self.assertEqual(g.stats()["nodes"], 0)
        self.assertEqual(g.stats()["edges"], 0)

    def test_attached_observations(self):
        g = diamond()
        g.add_node("observation", "obs_1")
        g.add_edge("observation:obs_1", "file:core.py", "about")
        self.assertEqual(g.attached_observations("file:core.py"), ["obs_1"])

    def test_subgraph_impact_mode_includes_observations(self):
        g = diamond()
        g.add_node("observation", "obs_1")
        g.add_edge("observation:obs_1", "file:app.py", "about")
        nodes, edges = g.subgraph("file:core.py", depth=3, mode="impact")
        ids = {n.id for n in nodes}
        self.assertIn("file:core.py", ids)
        self.assertIn("file:app.py", ids)
        self.assertIn("observation:obs_1", ids)
        self.assertTrue(any(e["relation"] == "about" for e in edges))

    def test_subgraph_neighborhood_mode(self):
        g = diamond()
        nodes, _ = g.subgraph("file:lib_a.py", depth=1)
        ids = {n.id for n in nodes}
        self.assertEqual(ids, {"file:lib_a.py", "file:app.py", "file:core.py"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/home/tre/dev/DANZA-OS" && python3 -m unittest danzaboss.tests.test_cortex_graph -v 2>&1 | tail -5` — actually the suite convention is `cd danzaboss/tests && python3 test_cortex_graph.py`; use: `cd "/home/tre/dev/DANZA-OS/danzaboss/tests" && python3 test_cortex_graph.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'danzaboss.cortex.graph'`

- [ ] **Step 3: Implement `danzaboss/cortex/graph.py`**

```python
"""CORTEX knowledge graph — typed nodes/edges + recursive-CTE traversal (C4).

Lives in the same repo-scoped cortex.db as observations (spec section 3.3);
GraphStore opens its own connection like CaptureLog does. The impact closure
answers "what breaks if X changes": every node with a dependency path INTO X,
computed with a recursive CTE whose depth cap guarantees cycle termination.
Only dependency-shaped relations (default: imports) ride the closure —
commit/observation edges are annotations, not dependencies.

Stdlib only.
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


def node_id(kind: str, name: str) -> str:
    return f"{kind}:{name}"


@dataclass
class Node:
    id: str
    kind: str
    name: str
    project: str = ""
    attrs: dict = field(default_factory=dict)


class GraphStore:
    """Nodes + edges with deterministic traversal; deliberately dumb storage."""

    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.conn.execute("""CREATE TABLE IF NOT EXISTS graph_nodes (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
            project TEXT DEFAULT '', attrs TEXT DEFAULT '{}')""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS graph_edges (
            src TEXT NOT NULL, dst TEXT NOT NULL, relation TEXT NOT NULL,
            weight REAL DEFAULT 1.0, evidence TEXT DEFAULT '',
            PRIMARY KEY (src, dst, relation))""")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_edges_dst ON graph_edges(dst, relation)")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_nodes_kind ON graph_nodes(kind, name)")
        self.conn.commit()

    # -- write -----------------------------------------------------------------
    def add_node(self, kind: str, name: str, project: str = "", **attrs) -> str:
        nid = node_id(kind, name)
        row = self.conn.execute(
            "SELECT attrs FROM graph_nodes WHERE id = ?", (nid,)).fetchone()
        if row:
            merged = json.loads(row["attrs"] or "{}")
            merged.update(attrs)
            self.conn.execute(
                "UPDATE graph_nodes SET attrs = ?, project = ? WHERE id = ?",
                (json.dumps(merged), project or self.node(nid).project, nid))
        else:
            self.conn.execute(
                "INSERT INTO graph_nodes (id, kind, name, project, attrs) "
                "VALUES (?, ?, ?, ?, ?)",
                (nid, kind, name, project, json.dumps(attrs)))
        self.conn.commit()
        return nid

    def add_edge(self, src: str, dst: str, relation: str,
                 weight: float = 1.0, evidence: str = "") -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO graph_edges (src, dst, relation, weight, evidence) "
            "VALUES (?, ?, ?, ?, ?)", (src, dst, relation, weight, evidence))
        self.conn.commit()

    def clear(self, project: Optional[str] = None) -> None:
        if project:
            ids = [r["id"] for r in self.conn.execute(
                "SELECT id FROM graph_nodes WHERE project = ?", (project,))]
            qs = ",".join("?" for _ in ids) or "''"
            self.conn.execute(
                f"DELETE FROM graph_edges WHERE src IN ({qs}) OR dst IN ({qs})",
                ids + ids)
            self.conn.execute(
                "DELETE FROM graph_nodes WHERE project = ?", (project,))
        else:
            self.conn.execute("DELETE FROM graph_edges")
            self.conn.execute("DELETE FROM graph_nodes")
        self.conn.commit()

    # -- read ------------------------------------------------------------------
    @staticmethod
    def _decode(row: sqlite3.Row) -> Node:
        return Node(id=row["id"], kind=row["kind"], name=row["name"],
                    project=row["project"],
                    attrs=json.loads(row["attrs"] or "{}"))

    def node(self, nid: str) -> Optional[Node]:
        row = self.conn.execute(
            "SELECT * FROM graph_nodes WHERE id = ?", (nid,)).fetchone()
        return self._decode(row) if row else None

    def find(self, text: str, kinds: Optional[list[str]] = None,
             limit: int = 20) -> list[Node]:
        sql = "SELECT * FROM graph_nodes WHERE name LIKE ? ESCAPE '\\'"
        esc = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params: list = [f"%{esc}%"]
        if kinds:
            sql += f" AND kind IN ({','.join('?' for _ in kinds)})"
            params += kinds
        sql += " ORDER BY length(name), name LIMIT ?"
        params.append(limit)
        return [self._decode(r) for r in self.conn.execute(sql, params)]

    def resolve_file(self, path: str) -> Optional[str]:
        """Map a possibly-absolute path onto a file node (exact, else suffix)."""
        path = path.replace(os.sep, "/")
        nid = node_id("file", path)
        if self.node(nid):
            return nid
        rows = self.conn.execute(
            "SELECT id, name FROM graph_nodes WHERE kind = 'file' "
            "ORDER BY name").fetchall()
        matches = [r["id"] for r in rows if path.endswith("/" + r["name"])]
        return matches[0] if len(matches) == 1 else None

    def neighbors(self, nid: str, relation: Optional[str] = None) -> dict:
        rel_sql, rel_params = ("", []) if relation is None else \
            (" AND relation = ?", [relation])
        out = [(r["dst"], r["relation"]) for r in self.conn.execute(
            f"SELECT dst, relation FROM graph_edges WHERE src = ?{rel_sql} "
            "ORDER BY dst, relation", [nid] + rel_params)]
        inn = [(r["src"], r["relation"]) for r in self.conn.execute(
            f"SELECT src, relation FROM graph_edges WHERE dst = ?{rel_sql} "
            "ORDER BY src, relation", [nid] + rel_params)]
        return {"out": out, "in": inn}

    def _closure(self, nid: str, max_depth: int, relations: tuple[str, ...],
                 reverse: bool) -> list[tuple[str, int]]:
        """Recursive-CTE walk; reverse=True follows edges dst->src (impact)."""
        here, there = ("dst", "src") if reverse else ("src", "dst")
        rel_qs = ",".join("?" for _ in relations)
        sql = f"""
            WITH RECURSIVE closure(id, depth) AS (
                SELECT {there}, 1 FROM graph_edges
                 WHERE {here} = ? AND relation IN ({rel_qs})
                UNION
                SELECT e.{there}, c.depth + 1
                  FROM graph_edges e JOIN closure c ON e.{here} = c.id
                 WHERE c.depth < ? AND e.relation IN ({rel_qs})
            )
            SELECT id, MIN(depth) AS d FROM closure
             WHERE id != ? GROUP BY id ORDER BY d, id"""
        params = [nid, *relations, max_depth, *relations, nid]
        return [(r["id"], r["d"]) for r in self.conn.execute(sql, params)]

    def impact(self, nid: str, max_depth: int = 4,
               relations: tuple[str, ...] = ("imports",)) -> list[tuple[str, int]]:
        return self._closure(nid, max_depth, relations, reverse=True)

    def dependencies(self, nid: str, max_depth: int = 4,
                     relations: tuple[str, ...] = ("imports",)) -> list[tuple[str, int]]:
        return self._closure(nid, max_depth, relations, reverse=False)

    def path(self, src: str, dst: str, max_depth: int = 6) -> list[str]:
        """Deterministic BFS along edge direction; first shortest path wins."""
        if src == dst:
            return [src]
        seen = {src}
        queue: deque[list[str]] = deque([[src]])
        while queue:
            trail = queue.popleft()
            if len(trail) > max_depth:
                return []
            for nxt, _ in self.neighbors(trail[-1])["out"]:
                if nxt == dst:
                    return trail + [nxt]
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(trail + [nxt])
        return []

    def attached_observations(self, nid: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT n.name FROM graph_edges e JOIN graph_nodes n ON n.id = e.src "
            "WHERE e.dst = ? AND e.relation = 'about' AND n.kind = 'observation' "
            "ORDER BY n.name", (nid,)).fetchall()
        return [r["name"] for r in rows]

    def subgraph(self, nid: str, depth: int = 2,
                 mode: str = "neighborhood", cap: int = 80
                 ) -> tuple[list[Node], list[dict]]:
        ids: list[str] = [nid]
        if mode == "impact":
            ids += [i for i, _ in self.impact(nid, max_depth=depth)]
            for fid in list(ids):
                ids += [node_id("observation", o)
                        for o in self.attached_observations(fid)]
        else:
            frontier, seen = [nid], {nid}
            for _ in range(depth):
                nxt = []
                for cur in frontier:
                    n = self.neighbors(cur)
                    for other, _ in n["out"] + n["in"]:
                        if other not in seen:
                            seen.add(other)
                            nxt.append(other)
                frontier = nxt
            ids = sorted(seen, key=lambda i: (i != nid, i))
        uniq = list(dict.fromkeys(ids))[:cap]
        nodes = [n for n in (self.node(i) for i in uniq) if n]
        idset = {n.id for n in nodes}
        qs = ",".join("?" for _ in idset) or "''"
        edges = [{"src": r["src"], "dst": r["dst"], "relation": r["relation"]}
                 for r in self.conn.execute(
                     f"SELECT src, dst, relation FROM graph_edges "
                     f"WHERE src IN ({qs}) AND dst IN ({qs}) "
                     "ORDER BY src, dst, relation", list(idset) + list(idset))]
        return nodes, edges

    def stats(self, project: Optional[str] = None) -> dict:
        where, params = ("WHERE project = ?", [project]) if project else ("", [])
        nodes = self.conn.execute(
            f"SELECT COUNT(*) c FROM graph_nodes {where}", params).fetchone()["c"]
        by_kind = {r["kind"]: r["c"] for r in self.conn.execute(
            f"SELECT kind, COUNT(*) c FROM graph_nodes {where} GROUP BY kind",
            params)}
        edges = self.conn.execute(
            "SELECT COUNT(*) c FROM graph_edges").fetchone()["c"]
        return {"nodes": nodes, "edges": edges, "by_kind": by_kind}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/home/tre/dev/DANZA-OS/danzaboss/tests" && python3 test_cortex_graph.py`
Expected: `OK` (13 tests)

- [ ] **Step 5: Run the full suite, then commit**

Run: `cd "/home/tre/dev/DANZA-OS" && ./danzaboss/run_tests.sh 2>&1 | tail -3`
Expected: `OK`, test count 227 + 13 = 240

```bash
git add danzaboss/cortex/graph.py danzaboss/tests/test_cortex_graph.py
git commit -m "feat(cortex): C4 graph store — typed nodes/edges, recursive-CTE impact closure

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `repo_intel.py` — language analyzers + repo scan

**Files:**
- Create: `danzaboss/cortex/repo_intel.py`
- Test: `danzaboss/tests/test_cortex_repo_intel.py`

**Interfaces:**
- Consumes: `GraphStore`, `node_id` from Task 1.
- Produces:
  - `class FileIntel` (dataclass): `path: str` (repo-relative posix), `module: str`, `imports: list[str]`, `symbols: list[tuple[str, str]]` (kind, name).
  - `class LanguageAnalyzerPort` — base with `extensions: tuple[str, ...]` and `analyze(self, path: str, source: str) -> FileIntel` raising `NotImplementedError`. Adapter seam (spec D7): a tree-sitter adapter can replace the defaults later.
  - `class PythonAnalyzer(LanguageAnalyzerPort)` — `ast`-based; resolves relative imports against the file's dotted module.
  - `class RegexAnalyzer(LanguageAnalyzerPort)` — `.js .mjs .jsx .ts .tsx`; `import ... from '...'`/`require('...')` + `function`/`class` names; relative specifiers stay raw (resolved in `scan_repo`).
  - `IGNORE_DIRS: frozenset[str]`
  - `scan_repo(root: str, project: str, graph: GraphStore, analyzers: Optional[list[LanguageAnalyzerPort]] = None) -> dict` — returns `{"files": n, "modules": n, "symbols": n, "imports_resolved": n, "imports_external": n}`.

**Graph shape produced** (the contract Task 4 and the eval rely on):
- one `file` node per analyzed file (name = repo-relative posix path, attr `language`)
- one `module` node per Python file (attr `file` = path); external imports become `module` nodes with attr `external: True`
- `symbol` nodes named `"{path}::{symbol}"` (attr `kind`), edge `file -declares-> symbol`
- resolved import: `file:src -imports-> file:target` (file-to-file, so impact closures are file-level)
- unresolved import: `file:src -imports-> module:name`

- [ ] **Step 1: Write the failing tests**

Create `danzaboss/tests/test_cortex_repo_intel.py`:

```python
"""Repo intelligence: stdlib analyzers -> file/module/symbol graph (C4).

The acceptance test at the bottom runs the scanner over THIS repository and
asserts real dependency closures — "what breaks if observation.py changes"
must include store.py and retrieve.py (spec section 8, C4 acceptance).
"""
import os
import tempfile
import textwrap
import unittest
import _bootstrap  # noqa
from danzaboss.cortex.graph import GraphStore
from danzaboss.cortex.repo_intel import PythonAnalyzer, RegexAnalyzer, scan_repo

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPythonAnalyzer(unittest.TestCase):
    def test_module_imports_and_symbols(self):
        src = textwrap.dedent("""\
            import json
            import pkg.util
            from pkg.core import thing
            from .sibling import x
            from ..other import y

            def top(): ...

            class Widget: ...
        """)
        fi = PythonAnalyzer().analyze("pkg/sub/mod.py", src)
        self.assertEqual(fi.module, "pkg.sub.mod")
        self.assertIn("json", fi.imports)
        self.assertIn("pkg.util", fi.imports)
        self.assertIn("pkg.core.thing", fi.imports)
        self.assertIn("pkg.sub.sibling", fi.imports)   # level 1
        self.assertIn("pkg.other", fi.imports)          # level 2
        self.assertIn(("function", "top"), fi.symbols)
        self.assertIn(("class", "Widget"), fi.symbols)

    def test_init_module_name(self):
        fi = PythonAnalyzer().analyze("pkg/__init__.py", "")
        self.assertEqual(fi.module, "pkg")

    def test_syntax_error_yields_empty_intel(self):
        fi = PythonAnalyzer().analyze("bad.py", "def broken(:")
        self.assertEqual(fi.imports, [])
        self.assertEqual(fi.symbols, [])


class TestRegexAnalyzer(unittest.TestCase):
    def test_js_imports_and_symbols(self):
        src = 'import { a } from "./util.js";\nconst b = require("lodash");\n' \
              'export function draw() {}\nclass Panel {}\n'
        fi = RegexAnalyzer().analyze("web/app.js", src)
        self.assertIn("./util.js", fi.imports)
        self.assertIn("lodash", fi.imports)
        self.assertIn(("function", "draw"), fi.symbols)
        self.assertIn(("class", "Panel"), fi.symbols)


class TestScanRepo(unittest.TestCase):
    def test_scan_builds_file_to_file_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "pkg"))
            open(os.path.join(tmp, "pkg", "__init__.py"), "w").close()
            with open(os.path.join(tmp, "pkg", "core.py"), "w") as fh:
                fh.write("VALUE = 1\n")
            with open(os.path.join(tmp, "pkg", "api.py"), "w") as fh:
                fh.write("from pkg.core import VALUE\nimport os\n")
            g = GraphStore(":memory:")
            stats = scan_repo(tmp, "p", g)
            self.assertEqual(stats["imports_resolved"], 1)
            self.assertEqual(
                g.impact("file:pkg/core.py"), [("file:pkg/api.py", 1)])
            n = g.neighbors("file:pkg/api.py", relation="imports")
            self.assertIn(("module:os", "imports"), n["out"])

    def test_scan_skips_ignore_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "__pycache__"))
            with open(os.path.join(tmp, "__pycache__", "junk.py"), "w") as fh:
                fh.write("import os\n")
            g = GraphStore(":memory:")
            scan_repo(tmp, "p", g)
            self.assertEqual(g.stats()["nodes"], 0)


class TestSelfRepoAcceptance(unittest.TestCase):
    """C4 acceptance: correct dependency closures on this repository itself."""

    @classmethod
    def setUpClass(cls):
        cls.g = GraphStore(":memory:")
        scan_repo(REPO_ROOT, "DANZA-OS", cls.g)

    def test_impact_of_observation_py(self):
        broke = {nid for nid, _ in
                 self.g.impact("file:danzaboss/cortex/observation.py", max_depth=6)}
        self.assertIn("file:danzaboss/cortex/store.py", broke)
        self.assertIn("file:danzaboss/cortex/retrieve.py", broke)
        self.assertIn("file:danzaboss/cortex/commands.py", broke)

    def test_dependencies_of_retrieve_py(self):
        deps = {nid for nid, _ in
                self.g.dependencies("file:danzaboss/cortex/retrieve.py", max_depth=1)}
        self.assertIn("file:danzaboss/cortex/intent.py", deps)
        self.assertIn("file:danzaboss/cortex/observation.py", deps)
        self.assertIn("file:danzaboss/cortex/store.py", deps)

    def test_symbols_declared(self):
        self.assertIn(
            ("file:danzaboss/cortex/graph.py::GraphStore", "declares"),
            [(d, r) for d, r in
             self.g.neighbors("file:danzaboss/cortex/graph.py")["out"]
             if r == "declares"] or
            [("file:danzaboss/cortex/graph.py::GraphStore", "declares")]
            if self.g.node("symbol:danzaboss/cortex/graph.py::GraphStore") else [])
        self.assertIsNotNone(
            self.g.node("symbol:danzaboss/cortex/graph.py::GraphStore"))


if __name__ == "__main__":
    unittest.main()
```

Note: `test_symbols_declared`'s first assert is redundant scaffolding — keep only the final `assertIsNotNone` line; write the test as:

```python
    def test_symbols_declared(self):
        self.assertIsNotNone(
            self.g.node("symbol:danzaboss/cortex/graph.py::GraphStore"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/home/tre/dev/DANZA-OS/danzaboss/tests" && python3 test_cortex_repo_intel.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'danzaboss.cortex.repo_intel'`

- [ ] **Step 3: Implement `danzaboss/cortex/repo_intel.py`**

```python
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
        for kind, name in fi.symbols:
            sid = graph.add_node("symbol", f"{fi.path}::{name}", project,
                                 kind=kind)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/home/tre/dev/DANZA-OS/danzaboss/tests" && python3 test_cortex_repo_intel.py`
Expected: `OK` (9 tests). If `test_impact_of_observation_py` fails, debug import resolution — the cortex modules use relative imports (`from .observation import Observation`), so level-1 resolution from `danzaboss.cortex.store` must yield `danzaboss.cortex.observation`.

- [ ] **Step 5: Run the full suite, then commit**

Run: `cd "/home/tre/dev/DANZA-OS" && ./danzaboss/run_tests.sh 2>&1 | tail -3`
Expected: `OK`

```bash
git add danzaboss/cortex/repo_intel.py danzaboss/tests/test_cortex_repo_intel.py
git commit -m "feat(cortex): C4 repo intelligence — stdlib analyzers build the file/module/symbol graph

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `git_intel.py` — commit history → observation links

**Files:**
- Create: `danzaboss/cortex/git_intel.py`
- Test: `danzaboss/tests/test_cortex_git_intel.py`

**Interfaces:**
- Consumes: `GraphStore`, `node_id` (Task 1); `ObservationStore` (existing).
- Produces:
  - `class Commit` (dataclass): `sha: str, date: str, subject: str, files: list[str]`
  - `parse_log(text: str) -> list[Commit]` — parses `git log --name-only --pretty=format:%x1e%H%x1f%aI%x1f%s` output (record sep `\x1e`, unit sep `\x1f`).
  - `read_log(root: str, limit: int = 200) -> list[Commit]` — subprocess `git log`; returns `[]` on any failure (no git, not a repo) — intelligence is best-effort, never a crash.
  - `ingest_git(root: str, project: str, graph: GraphStore, limit: int = 200) -> dict` — `commit` nodes (attrs `date`, `subject`) + `commit -modifies-> file` edges **only for files already in the graph** (via exact name match; deleted/unscanned files are noise). Returns `{"commits": n, "modifies_edges": n}`.
  - `link_observations(store: ObservationStore, project: str, graph: GraphStore) -> dict` — for every live observation: `observation` node (name = obs id, attrs `title`, `type`), `observation -about-> file` for each `obs.files` entry resolvable via `graph.resolve_file`, `observation -references-> commit` for each sha in `obs.related_commits` plus any `commit <sha>`/bare 7-40 hex token in `obs.evidence` that prefix-matches a commit node. Returns `{"observations": n, "about_edges": n, "commit_edges": n}`.

Implementation notes (full code left to the implementer — the shapes above are the contract; this module is thin plumbing):
- `_SHA = re.compile(r"\b[0-9a-f]{7,40}\b")` over evidence strings; prefix-match against commit nodes with `SELECT id FROM graph_nodes WHERE kind='commit' AND name LIKE ?||'%'`. Add a `prefix_match(kind, prefix)` helper on GraphStore ONLY if needed — otherwise query via `graph.conn` directly inside git_intel (GraphStore exposes `.conn` like CaptureLog).
- `read_log`: `subprocess.run(["git", "log", f"-{limit}", "--name-only", "--pretty=format:\x1e%H\x1f%aI\x1f%s"], cwd=root, capture_output=True, text=True)`; on `returncode != 0` or `FileNotFoundError` return `[]`.
- `parse_log`: split on `\x1e`, skip empties; per record, first line = header split on `\x1f`; remaining non-blank lines = file paths.

- [ ] **Step 1: Implement `danzaboss/cortex/git_intel.py`** per the contract above (module docstring: why = commits are the join between memory and code; fail-soft discipline).

- [ ] **Step 2: Write tests** in `danzaboss/tests/test_cortex_git_intel.py` covering: `parse_log` on a two-commit fixture string (shas, dates, subjects, file lists); `ingest_git` on a real temp git repo (`skipUnless(shutil.which("git"))`, `git init` + config user + one commit) asserting the commit node and `modifies` edge exist; `link_observations` with an in-memory store+graph — an observation with `files=["pkg/core.py"]` and `related_commits=["abc1234"]` gets `about` and `references` edges (seed the graph with `file:pkg/core.py` and `commit:abc1234def...`). Run: `cd "/home/tre/dev/DANZA-OS/danzaboss/tests" && python3 test_cortex_git_intel.py` → `OK`.

- [ ] **Step 3: Full suite + commit**

```bash
cd "/home/tre/dev/DANZA-OS" && ./danzaboss/run_tests.sh 2>&1 | tail -3
git add danzaboss/cortex/git_intel.py danzaboss/tests/test_cortex_git_intel.py
git commit -m "feat(cortex): C4 git intelligence — commits and observation links enter the graph

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Bind the live graph signal in `retrieve.py`

**Files:**
- Modify: `danzaboss/cortex/retrieve.py` (replace `_sig_graph` stub at line 150-152; `hybrid_retrieve` signature at line 167)
- Modify: `danzaboss/cortex/quality.py` (`build_package` at line 116 — add `graph` kwarg, thread into BOTH `hybrid_retrieve` calls at lines 129 and 141)
- Modify: `danzaboss/cortex/commands.py` (`_cmd_retrieve` — build `GraphStore(db_path(root))`, pass to `build_package`)
- Modify: `danzaboss/cortex/ui/server.py` (`_api_explain` at line 210 — pass `graph=GraphStore(self.db_path)` and `workspace=workspace_snapshot(self.root)`, importing `from ..commands import workspace_snapshot`)
- Test: `danzaboss/tests/test_cortex_graph_signal.py`

**Interfaces:**
- `hybrid_retrieve(store, prompt, intent, project, *, limit=20, types=None, workspace=None, graph=None)` — new optional kwarg, `Optional[GraphStore]`. `graph=None` keeps today's behavior exactly (signal returns `[]`).
- `build_package(store, prompt, project, *, budget=1500, limit=20, types=None, workspace=None, intent_override=None, threshold=DEFAULT_THRESHOLD, graph=None)`.

New `_sig_graph` (replaces the stub — same file section, keep the signal-function style):

```python
def _sig_graph(graph, cands: list[Observation],
               workspace: Optional[WorkspaceState]) -> list[str]:
    """Impact-closure signal: observations attached to files that depend on
    what the workspace just changed. This is reach no lexical signal has —
    the observation may share zero words with the prompt."""
    if graph is None or workspace is None or not workspace.changed_files:
        return []
    allowed = {o.id for o in cands}
    best: dict[str, tuple[int, int]] = {}   # obs id -> (min depth, -hits)
    for path in workspace.changed_files[:10]:
        fid = graph.resolve_file(path)
        if not fid:
            continue
        for node, depth in [(fid, 0)] + graph.impact(fid, max_depth=3):
            for oid in graph.attached_observations(node):
                if oid not in allowed:
                    continue
                d, h = best.get(oid, (99, 0))
                best[oid] = (min(d, depth), h - 1)
    ranked = sorted(best.items(), key=lambda kv: (kv[1][0], kv[1][1], kv[0]))
    return [oid for oid, _ in ranked[:SIGNAL_CAP]]
```

In `hybrid_retrieve`, change the signals dict entry to `"graph": _sig_graph(graph, cands, workspace),` and update the module docstring paragraph that says the graph signal "is a stub … until C4" to state it is now live. Import `GraphStore` under `TYPE_CHECKING` only, or just leave the parameter untyped (`graph=None`) with a docstring note — match file style (it uses plain `Optional[...]`; use `graph: Optional["GraphStore"] = None` with a `from .graph import GraphStore` inside `TYPE_CHECKING` guard, or simply accept duck-typed `graph`). Simplest consistent choice: `from typing import TYPE_CHECKING` + guarded import.

- [ ] **Step 1: Apply the four modifications.**
- [ ] **Step 2: Write `danzaboss/tests/test_cortex_graph_signal.py`** — three tests:
  1. `graph=None` → `result.signals["graph"] == []` and everything else unchanged (backward compatibility).
  2. Seeded graph (`file:a.py <- file:b.py` imports edge, obs attached to `b.py` via `about`), workspace `changed_files=["a.py"]` → the graph signal ranks that obs, and it appears in `result.items` even when the prompt shares no words with it (use distinct types/concepts per the store-merge gotcha).
  3. Depth ordering: obs on the changed file itself (depth 0) ranks before obs on a depth-2 dependent.
- [ ] **Step 3: Full suite + commit**

```bash
cd "/home/tre/dev/DANZA-OS" && ./danzaboss/run_tests.sh 2>&1 | tail -3
git add danzaboss/cortex/retrieve.py danzaboss/cortex/quality.py danzaboss/cortex/commands.py danzaboss/cortex/ui/server.py danzaboss/tests/test_cortex_graph_signal.py
git commit -m "feat(cortex): C4 live graph signal — impact closure feeds RRF fusion

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: CLI — `danza cortex index` + `danza cortex graph`

**Files:**
- Modify: `danzaboss/cortex/commands.py` (add `_cmd_index`, `_cmd_graph`; register in `_COMMANDS`; update usage string in `main()`)
- Modify: `danzaboss/cli.py:9` (usage line: add `index|graph` to the cortex command list)
- Test: append `class TestGraphCommands` to `danzaboss/tests/test_cortex_commands.py` (follow that file's existing harness pattern — read it first)

```python
def _cmd_index(argv: list[str], root: str, stdin: TextIO) -> int:
    """danza cortex index [--commits N] — rebuild the knowledge graph for this
    repo: scan files, ingest git history, link observations. Deterministic
    rebuild (clear + rescan) so the graph never drifts from reality."""
    from .git_intel import ingest_git, link_observations
    from .graph import GraphStore
    from .repo_intel import scan_repo
    limit = int(argv[argv.index("--commits") + 1]) if "--commits" in argv else 200
    graph = GraphStore(db_path(root))
    project = _project(root)
    graph.clear(project)
    stats = scan_repo(root, project, graph)
    stats.update(ingest_git(root, project, graph, limit=limit))
    store = ObservationStore(SqliteBackend(db_path(root)))
    stats.update(link_observations(store, project, graph))
    print(json.dumps(stats, indent=2))
    return 0


def _cmd_graph(argv: list[str], root: str, stdin: TextIO) -> int:
    """danza cortex graph <node-id-or-name> [--impact] [--deps] [--depth N]
    Default prints neighbors; --impact prints "what breaks if this changes"."""
    from .graph import GraphStore
    depth = int(argv[argv.index("--depth") + 1]) if "--depth" in argv else 4
    impact = "--impact" in argv
    deps = "--deps" in argv
    query = " ".join(a for a in argv if not a.startswith("--")
                     and a != str(depth))
    if not query.strip():
        print("graph: a node id or name is required", file=sys.stderr)
        return 2
    graph = GraphStore(db_path(root))
    node = graph.node(query)
    if node is None:
        hits = graph.find(query)
        if not hits:
            print(json.dumps({"error": f"no node matches {query!r}"}))
            return 1
        node = hits[0]
    if impact or deps:
        closure = (graph.impact if impact else graph.dependencies)(
            node.id, max_depth=depth)
        print(json.dumps({"node": node.id,
                          "mode": "impact" if impact else "dependencies",
                          "count": len(closure),
                          "closure": [{"id": i, "depth": d}
                                      for i, d in closure]}, indent=2))
    else:
        print(json.dumps({"node": node.id,
                          "neighbors": graph.neighbors(node.id)}, indent=2))
    return 0
```

Register: `_COMMANDS = {..., "index": _cmd_index, "graph": _cmd_graph}` and usage string `"danza cortex <hook|observe|get|search|retrieve|context|age|stats|ui|index|graph> ..."`. Watch the `--depth` arg-parsing subtlety in `_cmd_graph`: the naive filter above would drop a node named e.g. "4" — acceptable; node names are paths/shas. (Cleaner: pop flag+value pairs first, the way `_cmd_retrieve.take_opt` does — prefer that existing pattern.)

- [ ] **Step 1: Implement both commands** (use `take_opt`-style flag popping copied from `_cmd_retrieve`).
- [ ] **Step 2: Tests** — in a temp root with a tiny py file + no git: `index` exits 0 and prints stats JSON with `files >= 1`; `graph <that-file> --impact` exits 0 with `mode == "impact"`; unknown node exits 1.
- [ ] **Step 3: Smoke on this repo:** `cd "/home/tre/dev/DANZA-OS" && PYTHONPATH=. python3 -m danzaboss.cli cortex index` then `PYTHONPATH=. python3 -m danzaboss.cli cortex graph danzaboss/cortex/observation.py --impact` — expect store.py/retrieve.py in the closure. Show output.
- [ ] **Step 4: Full suite + commit**

```bash
git add danzaboss/cortex/commands.py danzaboss/cli.py danzaboss/tests/test_cortex_commands.py
git commit -m "feat(cortex): danza cortex index + graph commands — build and query the knowledge graph

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: `/api/graph` endpoint

**Files:**
- Modify: `danzaboss/cortex/ui/server.py` (route dispatch in `do_GET` around line 137; new `_api_graph` method)
- Test: append `class TestGraphEndpoint` to `danzaboss/tests/test_cortex_ui.py` (mirror that file's existing serve_in_thread + urllib pattern — read it first)

**API contract** (what Task 7's frontend consumes):
- `GET /api/graph?q=<text>` → `{"matches": [{"id", "kind", "name"}, ...]}` (node picker search, limit 20)
- `GET /api/graph?node=<id>&depth=<n>&mode=<neighborhood|impact>` → `{"center": id, "mode": m, "depth": n, "nodes": [{"id","kind","name","attrs"}...], "edges": [{"src","dst","relation"}...]}` (defaults: depth 2, mode neighborhood; unknown node → 404)
- `GET /api/graph` (no params) → `{"stats": {...}, "top": [{"id","kind","name","degree"}...]}` — 12 highest-degree nodes so the view boots non-empty

```python
    def _api_graph(self, q: dict) -> None:
        """Knowledge-graph window (C4): node search, neighborhood/impact
        subgraphs, or a degree-ranked overview when called bare."""
        from ..graph import GraphStore
        graph = GraphStore(self.db_path)
        text = (q.get("q") or [""])[0]
        node = (q.get("node") or [""])[0]
        if text.strip() and not node:
            self._json({"matches": [{"id": n.id, "kind": n.kind, "name": n.name}
                                    for n in graph.find(text)]})
            return
        if not node:
            top = graph.conn.execute(
                "SELECT n.id, n.kind, n.name, COUNT(*) AS degree "
                "FROM graph_nodes n JOIN graph_edges e "
                "ON e.src = n.id OR e.dst = n.id "
                "GROUP BY n.id ORDER BY degree DESC, n.id LIMIT 12").fetchall()
            self._json({"stats": graph.stats(),
                        "top": [dict(r) for r in top]})
            return
        if graph.node(node) is None:
            self._json({"error": f"unknown node: {node}"}, 404)
            return
        depth = int((q.get("depth") or ["2"])[0])
        mode = (q.get("mode") or ["neighborhood"])[0]
        nodes, edges = graph.subgraph(node, depth=depth, mode=mode)
        self._json({"center": node, "mode": mode, "depth": depth,
                    "nodes": [{"id": n.id, "kind": n.kind, "name": n.name,
                               "attrs": n.attrs} for n in nodes],
                    "edges": edges})
```

Route dispatch, inserted before the 404 fallback: `elif route == "/api/graph": self._api_graph(q)`.

- [ ] **Step 1: Implement endpoint + dispatch.**
- [ ] **Step 2: Tests** — seed a GraphStore at `<tmp-root>/.danza/cortex/cortex.db` with the Task-1 diamond fixture, boot `serve_in_thread`, assert: bare call returns stats+top; `?q=lib` returns 2 matches; `?node=file:core.py&mode=impact&depth=3` returns app.py in nodes; `?node=file:nope` → 404. POST to `/api/graph` → 405 (read-only rule).
- [ ] **Step 3: Full suite + commit**

```bash
cd "/home/tre/dev/DANZA-OS" && ./danzaboss/run_tests.sh 2>&1 | tail -3
git add danzaboss/cortex/ui/server.py danzaboss/tests/test_cortex_ui.py
git commit -m "feat(cortex): /api/graph endpoint — search, subgraph, impact closure over HTTP

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Graph explorer view (SVG force layout)

**Files:**
- Modify: `danzaboss/cortex/ui/static/index.html` (nav button + view section)
- Modify: `danzaboss/cortex/ui/static/app.js` (view loader + force layout + render)
- Modify: `danzaboss/cortex/ui/static/app.css` (append graph styles)

No unit tests for the frontend (consistent with C2/C3 — endpoint tests carry the contract; browser eyeball verifies). Verification step at the end.

**index.html** — nav: insert after the Explain button (line 24):
```html
    <button class="nav-btn" data-view="graph">Graph</button>
```
View section, inserted after the explain section (after line 81):
```html
  <!-- GRAPH EXPLORER -->
  <section class="view" id="view-graph" hidden>
    <form class="explain-form" id="graph-form">
      <input id="graph-node" class="explain-input" type="text"
             placeholder="Find a node — file, module, symbol, commit…"
             autocomplete="off">
      <label class="explain-budget mono">depth
        <input id="graph-depth" type="number" value="2" min="1" max="6"></label>
      <div class="mode-toggle" role="group" aria-label="Graph mode">
        <button type="button" class="mode-btn active" data-gmode="neighborhood">neighbors</button>
        <button type="button" class="mode-btn" data-gmode="impact">impact</button>
      </div>
      <button type="submit" class="save-btn">Explore</button>
    </form>
    <div class="graph-matches" id="graph-matches"></div>
    <div class="graph-meta mono dim" id="graph-meta"></div>
    <svg id="graph-svg" width="100%" height="640"
         preserveAspectRatio="xMidYMid meet"></svg>
  </section>
```

**app.js** — add a `graph` section before the SSE block; register in `refresh()` map (`graph: loadGraph`). Complete code:

```js
/* ---------- graph explorer (C4) ---------- */
const gstate = { mode: "neighborhood", center: null };

$$("#graph-form .mode-btn").forEach((b) => b.addEventListener("click", () => {
  $$("#graph-form .mode-btn").forEach((x) => x.classList.toggle("active", x === b));
  gstate.mode = b.dataset.gmode;
  if (gstate.center) exploreNode(gstate.center);
}));

$("#graph-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const text = $("#graph-node").value.trim();
  if (!text) return;
  const data = await api(`/api/graph?${new URLSearchParams({ q: text })}`);
  $("#graph-matches").innerHTML = (data.matches || []).map((m) =>
    `<button type="button" class="tag graph-match" data-id="${esc(m.id)}">
       ${esc(m.kind)}: ${esc(m.name)}</button>`).join(" ") ||
    '<span class="dim">no matching nodes — run <code>danza cortex index</code></span>';
});

$("#graph-matches").addEventListener("click", (ev) => {
  const b = ev.target.closest(".graph-match");
  if (b) exploreNode(b.dataset.id);
});

async function exploreNode(id) {
  gstate.center = id;
  const depth = +$("#graph-depth").value || 2;
  const data = await api(`/api/graph?${new URLSearchParams(
    { node: id, depth, mode: gstate.mode })}`);
  $("#graph-meta").textContent = gstate.mode === "impact"
    ? `${data.nodes.length - 1} nodes break if ${id} changes (depth ${depth})`
    : `${data.nodes.length} nodes · ${data.edges.length} edges (depth ${depth})`;
  renderGraph(data);
}

function layoutGraph(nodes, edges, w, h) {
  // deterministic: seeded on a circle, relaxed with repulsion + springs
  nodes.forEach((n, i) => {
    const a = (2 * Math.PI * i) / nodes.length;
    n.x = w / 2 + Math.cos(a) * h / 3;
    n.y = h / 2 + Math.sin(a) * h / 3;
  });
  const byId = new Map(nodes.map((n) => [n.id, n]));
  for (let it = 0; it < 200; it++) {
    for (const a of nodes) {                       // pairwise repulsion
      for (const b of nodes) {
        if (a === b) continue;
        const dx = a.x - b.x, dy = a.y - b.y;
        const d2 = Math.max(64, dx * dx + dy * dy);
        a.x += (dx / d2) * 900; a.y += (dy / d2) * 900;
      }
    }
    for (const e of edges) {                       // spring along edges
      const s = byId.get(e.src), t = byId.get(e.dst);
      if (!s || !t) continue;
      const dx = t.x - s.x, dy = t.y - s.y;
      const d = Math.max(1, Math.hypot(dx, dy));
      const f = (d - 110) / d * 0.02;
      s.x += dx * f; s.y += dy * f; t.x -= dx * f; t.y -= dy * f;
    }
    for (const n of nodes) {                       // gravity + bounds
      n.x += (w / 2 - n.x) * 0.005; n.y += (h / 2 - n.y) * 0.005;
      n.x = Math.min(w - 30, Math.max(30, n.x));
      n.y = Math.min(h - 20, Math.max(20, n.y));
    }
  }
}

function renderGraph(data) {
  const svg = $("#graph-svg");
  const w = svg.clientWidth || 900, h = 640;
  const nodes = data.nodes.map((n) => ({ ...n }));
  layoutGraph(nodes, data.edges, w, h);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const lines = data.edges.map((e) => {
    const s = byId.get(e.src), t = byId.get(e.dst);
    if (!s || !t) return "";
    return `<line class="gedge r-${esc(e.relation)}" x1="${s.x}" y1="${s.y}"
      x2="${t.x}" y2="${t.y}"><title>${esc(e.src)} —${esc(e.relation)}→ ${esc(e.dst)}</title></line>`;
  }).join("");
  const dots = nodes.map((n) => {
    const center = n.id === data.center ? " center" : "";
    const label = n.name.length > 28 ? "…" + n.name.slice(-27) : n.name;
    return `<g class="gnode k-${esc(n.kind)}${center}" data-id="${esc(n.id)}"
        transform="translate(${n.x},${n.y})">
      <circle r="${n.id === data.center ? 9 : 6}"><title>${esc(n.id)}</title></circle>
      <text x="10" y="4">${esc(label)}</text></g>`;
  }).join("");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.innerHTML = lines + dots;
}

$("#graph-svg").addEventListener("click", (ev) => {
  const g = ev.target.closest(".gnode");
  if (g) exploreNode(g.dataset.id);
});

async function loadGraph() {
  if (gstate.center) return;                       // keep the current view
  const data = await api("/api/graph");
  $("#graph-meta").textContent =
    `${data.stats.nodes} nodes · ${data.stats.edges} edges — search above, or click a hub`;
  $("#graph-matches").innerHTML = (data.top || []).map((m) =>
    `<button type="button" class="tag graph-match" data-id="${esc(m.id)}">
       ${esc(m.kind)}: ${esc(m.name)} (${m.degree})</button>`).join(" ");
}
```

And in `refresh()` change the map to include `graph: loadGraph`:
```js
  ({ feed: loadFeed, sessions: loadSessions, stats: loadStats,
     settings: loadSettings, explain: () => {}, graph: loadGraph
   }[state.view] || loadFeed)();
```

**app.css** — append (uses existing palette vars):
```css
/* ---------- graph explorer (C4) ---------- */
#graph-svg { background: var(--carbon); border: 1px solid var(--graphite); }
.graph-matches { margin: 10px 0; display: flex; flex-wrap: wrap; gap: 6px; }
.graph-match { cursor: pointer; }
.graph-meta { margin: 4px 0 8px; }
.gedge { stroke: var(--gunmetal); stroke-width: 1; }
.gedge.r-imports { stroke: var(--silver); opacity: .55; }
.gedge.r-about { stroke: var(--ember); opacity: .6; stroke-dasharray: 3 3; }
.gnode circle { fill: var(--gunmetal); stroke: var(--void); cursor: pointer; }
.gnode.k-file circle { fill: var(--silver); }
.gnode.k-module circle { fill: var(--gunmetal); }
.gnode.k-symbol circle { fill: var(--dim); }
.gnode.k-commit circle { fill: var(--ember); }
.gnode.k-observation circle { fill: var(--crimson); }
.gnode.center circle { stroke: var(--crimson); stroke-width: 2.5; }
.gnode text { fill: var(--text); font: 10px var(--font-mono); pointer-events: none; }
```

- [ ] **Step 1: Apply all three static-file edits.**
- [ ] **Step 2: Verify in a browser** — `PYTHONPATH=. python3 -m danzaboss.cli cortex index && PYTHONPATH=. python3 -m danzaboss.cli cortex ui --port 33001` in background, then Playwright: open `http://127.0.0.1:33001`, click Graph, search `retrieve`, click the file node, toggle impact — screenshot shows a rendered force graph with the center node ringed in crimson. Kill the server after.
- [ ] **Step 3: Full suite + commit**

```bash
cd "/home/tre/dev/DANZA-OS" && ./danzaboss/run_tests.sh 2>&1 | tail -3
git add danzaboss/cortex/ui/static/
git commit -m "feat(cortex): graph explorer view — SVG force layout with impact mode

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: C4-beats-C3 eval, docs, push

**Files:**
- Create: `danzaboss/tests/test_cortex_graph_eval.py`
- Modify: `CLAUDE.md` (test counts: three occurrences of "227"), `docs/superpowers/specs/2026-07-03-cortex-design.md` is historical — do NOT edit it.

**Eval design** (copies the adversarial pattern of `test_cortex_retrieval_eval.py`): each query has lexical decoys C3 ranks high, while the truly relevant observation shares few/no words with the prompt and is reachable ONLY through the graph — it is attached to a file that transitively depends on the file the workspace just changed. MRR(C4: graph passed) must beat MRR(C3: graph=None). Distinct types/concepts per fixture (store-merge gotcha).

```python
"""C4 acceptance eval (design spec section 8): with the knowledge graph bound,
retrieval must beat C3 on an extended fixture. The graph's edge is REACH:
the relevant observation shares almost no words with the prompt, but it is
attached to a file that transitively depends on the file just changed —
only the impact closure can surface it.
"""
import unittest
import _bootstrap  # noqa
from danzaboss.cortex.graph import GraphStore
from danzaboss.cortex.intent import WorkspaceState, detect
from danzaboss.cortex.observation import Importance, Observation
from danzaboss.cortex.retrieve import hybrid_retrieve
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore


def obs(title, summary, typ, **kw):
    return Observation(title=title, summary=summary, type=typ, project="p", **kw)


def build_fixture():
    store = ObservationStore(SqliteBackend(":memory:"))
    graph = GraphStore(":memory:")

    # dependency chain: checkout.py -> api.py -> stripe_client.py
    for f in ("pay/stripe_client.py", "pay/api.py", "pay/checkout.py"):
        graph.add_node("file", f, project="p")
    graph.add_edge("file:pay/api.py", "file:pay/stripe_client.py", "imports")
    graph.add_edge("file:pay/checkout.py", "file:pay/api.py", "imports")

    relevant = store.upsert(obs(
        "Checkout retries double-charge on client timeout",
        "retry loop lacks an idempotency key; second attempt bills again",
        "root_cause", concepts=["checkout", "idempotency"],
        files=["pay/checkout.py"], importance=Importance.HIGH.value,
        confidence=95))
    decoy_a = store.upsert(obs(
        "Stripe brand color updated on the payment page",
        "payment page stripe banner color changed for the payment redesign",
        "impl_detail", concepts=["branding"], confidence=20,
        importance=Importance.LOW.value, confidence_source="speculation"))
    decoy_b = store.upsert(obs(
        "Payment FAQ copy mentions stripe fees",
        "docs page about payment fees and stripe payment questions",
        "convention", concepts=["docs-copy"], confidence=20,
        importance=Importance.LOW.value, confidence_source="speculation"))
    graph.add_node("observation", relevant.id, project="p")
    graph.add_edge(f"observation:{relevant.id}", "file:pay/checkout.py", "about")

    # second scenario: auth chain, relevant obs two hops out
    for f in ("auth/jwt.py", "auth/session.py", "web/login.py"):
        graph.add_node("file", f, project="p")
    graph.add_edge("file:auth/session.py", "file:auth/jwt.py", "imports")
    graph.add_edge("file:web/login.py", "file:auth/session.py", "imports")
    relevant2 = store.upsert(obs(
        "Login page caches the session cookie past rotation",
        "stale cookie survives key rotation; users see phantom logouts",
        "limitation", concepts=["cookie-rotation"], files=["web/login.py"],
        importance=Importance.HIGH.value, confidence=90))
    decoy_c = store.upsert(obs(
        "JWT library changelog notes reviewed",
        "reviewed jwt release notes for the jwt upgrade ticket",
        "dependency", concepts=["changelog"], confidence=20,
        importance=Importance.LOW.value, confidence_source="speculation"))
    graph.add_node("observation", relevant2.id, project="p")
    graph.add_edge(f"observation:{relevant2.id}", "file:web/login.py", "about")

    queries = [
        ("touched the stripe payment client", WorkspaceState(
            changed_files=["pay/stripe_client.py"]), {relevant.id}),
        ("changed the jwt signing helper", WorkspaceState(
            changed_files=["auth/jwt.py"]), {relevant2.id}),
    ]
    assert decoy_a.id != relevant.id and decoy_b.id != relevant.id
    assert decoy_c.id != relevant2.id
    return store, graph, queries


def mrr(rankings, relevant_sets):
    total = 0.0
    for ranked, relevant in zip(rankings, relevant_sets):
        for pos, oid in enumerate(ranked, start=1):
            if oid in relevant:
                total += 1.0 / pos
                break
    return total / len(relevant_sets)


class TestGraphEval(unittest.TestCase):
    def test_c4_beats_c3_on_extended_fixture(self):
        store, graph, queries = build_fixture()
        c3, c4, relevant_sets = [], [], []
        for prompt, ws, relevant in queries:
            intent = detect(prompt, ws)
            r3 = hybrid_retrieve(store, prompt, intent, "p", limit=10,
                                 workspace=ws)
            r4 = hybrid_retrieve(store, prompt, intent, "p", limit=10,
                                 workspace=ws, graph=graph)
            c3.append([i.observation.id for i in r3.items])
            c4.append([i.observation.id for i in r4.items])
            relevant_sets.append(relevant)
        s3, s4 = mrr(c3, relevant_sets), mrr(c4, relevant_sets)
        self.assertGreater(
            s4, s3, f"C4 acceptance: graph-bound MRR ({s4:.3f}) must beat "
                    f"C3 MRR ({s3:.3f})")

    def test_graph_signal_is_ranked_in_result(self):
        store, graph, queries = build_fixture()
        prompt, ws, relevant = queries[0]
        r = hybrid_retrieve(store, prompt, detect(prompt, ws), "p",
                            workspace=ws, graph=graph)
        self.assertTrue(set(r.signals["graph"]) & relevant)


if __name__ == "__main__":
    unittest.main()
```

Caution: the `links` signal also uses `changed_files` (direct `obs.files` overlap) — the relevant observations here are attached to *dependent* files, never the changed file, so only the graph reaches them. If `s3 == s4`, check the decoys actually outrank in C3 (they share prompt words: "stripe", "payment", "jwt").

- [ ] **Step 1: Write and run the eval.** `cd "/home/tre/dev/DANZA-OS/danzaboss/tests" && python3 test_cortex_graph_eval.py` → `OK`.
- [ ] **Step 2: Update CLAUDE.md test counts** — replace the stale "227 tests" occurrences with the new total from the final suite run.
- [ ] **Step 3: Full suite, commit, push**

```bash
cd "/home/tre/dev/DANZA-OS" && ./danzaboss/run_tests.sh 2>&1 | tail -3
git add danzaboss/tests/test_cortex_graph_eval.py CLAUDE.md
git commit -m "test(cortex): C4 acceptance eval — graph-bound retrieval beats C3; doc refresh

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push
```

- [ ] **Step 4: Distill observations** (`danza cortex observe` — the Stop-gate enforces it) and update the `cortex-build-status` memory file: C4 done, C5 (learning & aging) next.

---

## Self-Review

1. **Spec coverage (section 8, C4 row):** graph store w/ recursive CTE — Task 1; repo intelligence stdlib analyzers — Task 2; git intelligence — Task 3; graph signal live — Task 4; graph UI view — Tasks 6–7; acceptance ("what depends on X / what breaks if X changes" correct on this repo) — Task 2 `TestSelfRepoAcceptance` + Task 5 smoke; C4-beats-C3 eval — Task 8. `/api/graph?node&depth` (spec section 6) — Task 6.
2. **Placeholder scan:** Task 3 intentionally specifies contract-plus-notes instead of full code (thin plumbing; per user's speed directive) — every shape, format string, and edge rule is stated exactly. No TBDs.
3. **Type consistency:** `GraphStore(path)`, `node_id(kind, name)`, `impact/dependencies -> list[tuple[str, int]]`, `subgraph -> (list[Node], list[dict])`, `attached_observations -> list[str]` used identically in Tasks 1, 4, 5, 6, 8. `hybrid_retrieve(..., graph=None)` matches between Tasks 4 and 8. Edge relations: `imports`, `declares`, `modifies`, `about`, `references` — closure default `("imports",)` everywhere.

