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
            if ids:  # empty IN () is invalid SQL; nothing to delete anyway
                qs = ",".join("?" for _ in ids)
                self.conn.execute(
                    f"DELETE FROM graph_edges "
                    f"WHERE src IN ({qs}) OR dst IN ({qs})",
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
        if not idset:  # unknown root: empty IN () is invalid SQL
            return [], []
        qs = ",".join("?" for _ in idset)
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
