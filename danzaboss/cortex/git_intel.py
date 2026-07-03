"""git_intel.py — CORTEX git intelligence (C4).

Commits are the join between memory and code: a commit touches files and is
referenced by observations, making it the bridge node that answers "which
observations were active when this code changed?" Intelligence is best-effort;
any subprocess or parse failure returns an empty result rather than crashing.

Stdlib only.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from .graph import GraphStore, node_id
from .store import ObservationStore

# Matches bare 7-40 lowercase hex tokens (short and full shas in evidence strings).
_SHA = re.compile(r"\b[0-9a-f]{7,40}\b")


@dataclass
class Commit:
    sha: str
    date: str
    subject: str
    files: list[str] = field(default_factory=list)


def parse_log(text: str) -> list[Commit]:
    """Parse ``git log --name-only --pretty=format:\\x1e%H\\x1f%aI\\x1f%s`` output.

    Record separator is ``\\x1e``; fields within the header line are separated
    by ``\\x1f``. Remaining non-blank lines after the header are file paths.
    Empty or malformed records are silently skipped.
    """
    commits: list[Commit] = []
    for record in text.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        lines = record.split("\n")
        header_parts = lines[0].split("\x1f")
        if len(header_parts) < 3:
            continue
        sha, date, subject = header_parts[0], header_parts[1], header_parts[2]
        files = [ln.strip() for ln in lines[1:] if ln.strip()]
        commits.append(Commit(sha=sha, date=date, subject=subject, files=files))
    return commits


def read_log(root: str, limit: int = 200) -> list[Commit]:
    """Run ``git log`` in *root* and return parsed commits.

    Returns ``[]`` on any failure: git binary missing, *root* not a repo,
    non-zero exit code, or any OS error. Intelligence is best-effort, never
    a crash.
    """
    try:
        result = subprocess.run(
            ["git", "log", f"-{limit}", "--name-only",
             "--pretty=format:\x1e%H\x1f%aI\x1f%s"],
            cwd=root, capture_output=True, text=True,
        )
        if result.returncode != 0:
            return []
        return parse_log(result.stdout)
    except (OSError, UnicodeDecodeError):
        return []


def ingest_git(root: str, project: str, graph: GraphStore,
               limit: int = 200) -> dict:
    """Load commit history into the graph and link commits to known files.

    Every commit becomes a ``commit`` node with ``date`` and ``subject`` attrs.
    A ``modifies`` edge is added only for files already present in the graph
    (exact node-name match via ``node_id("file", path)``). Deleted or unscanned
    files are noise and are silently skipped.

    Returns ``{"commits": n, "modifies_edges": n}``.
    """
    commits = read_log(root, limit)
    n_commits = 0
    n_edges = 0
    for commit in commits:
        cid = graph.add_node(
            "commit", commit.sha, project=project,
            date=commit.date, subject=commit.subject,
        )
        n_commits += 1
        for path in commit.files:
            fid = node_id("file", path)
            if graph.node(fid) is not None:
                graph.add_edge(cid, fid, "modifies")
                n_edges += 1
    return {"commits": n_commits, "modifies_edges": n_edges}


def _find_commit_node(graph: GraphStore, prefix: str) -> Optional[str]:
    """Return the node id of the commit whose sha starts with *prefix*, or None.

    Prefix-matches against commit node names via SQLite LIKE so that short shas
    (7+ chars) resolve to their full-sha node.
    """
    rows = graph.conn.execute(
        "SELECT id FROM graph_nodes WHERE kind='commit' AND name LIKE ?||'%'",
        (prefix,),
    ).fetchall()
    return rows[0]["id"] if rows else None


def link_observations(store: ObservationStore, project: str,
                      graph: GraphStore) -> dict:
    """Wire observation nodes into the graph via file and commit edges.

    For every live (non-superseded) observation in *project*:
    - Adds an ``observation`` node (name = obs.id, attrs: title, type).
    - Adds ``observation -about-> file`` edges for each ``obs.files`` entry
      that resolves via ``graph.resolve_file``.
    - Adds ``observation -references-> commit`` edges for each sha in
      ``obs.related_commits`` plus any 7-40 lowercase hex token found in
      ``obs.evidence`` strings that prefix-matches a commit node.

    Duplicate edges within one observation are suppressed via a per-observation
    seen-set, so a sha that appears in both ``related_commits`` and ``evidence``
    produces exactly one edge.

    Returns ``{"observations": n, "about_edges": n, "commit_edges": n}``.
    """
    n_obs = 0
    n_about = 0
    n_commit = 0

    for obs in store.backend.all(project):
        if obs.superseded_by:
            continue
        oid = graph.add_node(
            "observation", obs.id, project=project,
            title=obs.title, type=obs.type,
        )
        n_obs += 1

        # file edges
        for path in obs.files:
            fid = graph.resolve_file(path)
            if fid is not None:
                graph.add_edge(oid, fid, "about")
                n_about += 1

        # commit edges — deduplicated per observation
        seen: set[str] = set()

        for sha in obs.related_commits:
            cid = _find_commit_node(graph, sha)
            if cid and cid not in seen:
                graph.add_edge(oid, cid, "references")
                seen.add(cid)
                n_commit += 1

        for snippet in obs.evidence:
            for m in _SHA.finditer(snippet):
                token = m.group(0)
                cid = _find_commit_node(graph, token)
                if cid and cid not in seen:
                    graph.add_edge(oid, cid, "references")
                    seen.add(cid)
                    n_commit += 1

    return {"observations": n_obs, "about_edges": n_about, "commit_edges": n_commit}
