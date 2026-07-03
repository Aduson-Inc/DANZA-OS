"""Tests for danzaboss.cortex.git_intel (C4 git intelligence).

Coverage:
  - parse_log: two-commit fixture with shas, dates, subjects, file lists
  - read_log: non-git dir returns []; missing dir returns []
  - ingest_git: real temp git repo; commit node and modifies edge are created;
    unknown files produce no edge
  - link_observations: about and references edges wired correctly; superseded
    observations are skipped; no duplicate commit edges
"""
import os
import shutil
import subprocess
import tempfile
import unittest
import _bootstrap  # noqa

from danzaboss.cortex.git_intel import (
    Commit, parse_log, read_log, ingest_git, link_observations,
)
from danzaboss.cortex.graph import GraphStore, node_id
from danzaboss.cortex.observation import Observation, ObsType
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore

# ---------------------------------------------------------------------------
# Two-commit fixture — matches exact git log --name-only --pretty=format output
# ---------------------------------------------------------------------------
_SHA_A = "abc1234567890abcdef1234567890abcdef123456"
_SHA_B = "def4567890abcdef1234567890abcdef12345678"

_LOG_TEXT = (
    f"\x1e{_SHA_A}\x1f2024-01-15T10:00:00+00:00\x1fFirst commit\n\n"
    "pkg/core.py\n"
    "pkg/utils.py\n\n"
    f"\x1e{_SHA_B}\x1f2024-01-16T12:30:00+00:00\x1fSecond commit\n\n"
    "pkg/api.py\n"
)


class TestParseLog(unittest.TestCase):
    def test_two_commit_fixture(self):
        commits = parse_log(_LOG_TEXT)
        self.assertEqual(len(commits), 2)

        a = commits[0]
        self.assertEqual(a.sha, _SHA_A)
        self.assertEqual(a.date, "2024-01-15T10:00:00+00:00")
        self.assertEqual(a.subject, "First commit")
        self.assertIn("pkg/core.py", a.files)
        self.assertIn("pkg/utils.py", a.files)
        self.assertEqual(len(a.files), 2)

        b = commits[1]
        self.assertEqual(b.sha, _SHA_B)
        self.assertEqual(b.date, "2024-01-16T12:30:00+00:00")
        self.assertEqual(b.subject, "Second commit")
        self.assertEqual(b.files, ["pkg/api.py"])

    def test_empty_text_returns_empty_list(self):
        self.assertEqual(parse_log(""), [])

    def test_commit_with_no_files(self):
        text = f"\x1e{_SHA_A}\x1f2024-01-01T00:00:00+00:00\x1fEmpty commit\n"
        commits = parse_log(text)
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0].files, [])

    def test_malformed_record_skipped(self):
        """Records whose header has fewer than 3 \\x1f fields are dropped."""
        text = (
            f"\x1enotvalid\n\n"
            f"\x1e{_SHA_A}\x1f2024-01-01T00:00:00+00:00\x1fGood\n"
        )
        commits = parse_log(text)
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0].subject, "Good")


class TestReadLog(unittest.TestCase):
    def test_non_git_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = read_log(tmp)
            self.assertEqual(result, [])

    def test_missing_root_returns_empty(self):
        result = read_log("/tmp/danza_does_not_exist_xyz_abc_987")
        self.assertEqual(result, [])


@unittest.skipUnless(shutil.which("git"), "git not installed")
class TestIngestGit(unittest.TestCase):
    def _make_repo(self, tmp: str) -> None:
        """Init a git repo in *tmp* with one commit touching pkg/core.py."""
        os.makedirs(os.path.join(tmp, "pkg"))
        with open(os.path.join(tmp, "pkg", "core.py"), "w") as fh:
            fh.write("VALUE = 1\n")
        subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "."],
            cwd=tmp, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-m", "initial"],
            cwd=tmp, capture_output=True, check=True,
        )

    def test_commit_node_created_with_attrs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_repo(tmp)
            g = GraphStore(":memory:")
            stats = ingest_git(tmp, "p", g)
            self.assertEqual(stats["commits"], 1)
            rows = g.conn.execute(
                "SELECT * FROM graph_nodes WHERE kind='commit'"
            ).fetchall()
            self.assertEqual(len(rows), 1)
            n = g.node(rows[0]["id"])
            self.assertIn("initial", n.attrs.get("subject", ""))
            self.assertIn("date", n.attrs)

    def test_modifies_edge_for_known_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_repo(tmp)
            g = GraphStore(":memory:")
            # Pre-load the file node so ingest_git can link to it
            g.add_node("file", "pkg/core.py", project="p")
            stats = ingest_git(tmp, "p", g)
            self.assertGreaterEqual(stats["modifies_edges"], 1)
            edges = g.conn.execute(
                "SELECT * FROM graph_edges WHERE relation='modifies'"
            ).fetchall()
            self.assertGreaterEqual(len(edges), 1)

    def test_unknown_file_produces_no_modifies_edge(self):
        """Files not pre-loaded into the graph produce zero modifies edges."""
        with tempfile.TemporaryDirectory() as tmp:
            self._make_repo(tmp)
            g = GraphStore(":memory:")  # no file nodes pre-loaded
            stats = ingest_git(tmp, "p", g)
            self.assertEqual(stats["modifies_edges"], 0)
            edges = g.conn.execute(
                "SELECT * FROM graph_edges WHERE relation='modifies'"
            ).fetchall()
            self.assertEqual(len(edges), 0)


class TestLinkObservations(unittest.TestCase):
    def _make_store(self) -> ObservationStore:
        return ObservationStore(SqliteBackend(":memory:"))

    def test_about_and_references_edges(self):
        g = GraphStore(":memory:")
        store = self._make_store()

        # Seed graph: file node and a full-sha commit node
        g.add_node("file", "pkg/core.py", project="p")
        full_sha = "abc1234def567890abcdef1234567890abcdef00"
        g.add_node("commit", full_sha, project="p")

        obs = Observation(
            title="Core module fix",
            summary="Fixed a bug in the core module",
            type=ObsType.BUG_FIX.value,
            project="p",
            files=["pkg/core.py"],
            related_commits=["abc1234"],  # short prefix — resolved via LIKE
        )
        store.upsert(obs)

        stats = link_observations(store, "p", g)
        self.assertEqual(stats["observations"], 1)
        self.assertEqual(stats["about_edges"], 1)
        self.assertEqual(stats["commit_edges"], 1)

        about_edges = g.conn.execute(
            "SELECT * FROM graph_edges WHERE relation='about'"
        ).fetchall()
        self.assertEqual(len(about_edges), 1)

        ref_edges = g.conn.execute(
            "SELECT * FROM graph_edges WHERE relation='references'"
        ).fetchall()
        self.assertEqual(len(ref_edges), 1)

    def test_evidence_token_links_commit(self):
        g = GraphStore(":memory:")
        store = self._make_store()

        full_sha = "feed1234abcdef567890abcdef1234567890feed"
        g.add_node("commit", full_sha, project="p")

        obs = Observation(
            title="Decoder regression found",
            summary="Regression traced to a specific commit",
            type=ObsType.ROOT_CAUSE.value,  # distinct type avoids merge collision
            project="p",
            evidence=["Introduced in commit feed1234 during refactor"],
        )
        store.upsert(obs)

        stats = link_observations(store, "p", g)
        self.assertEqual(stats["commit_edges"], 1)

    def test_superseded_observation_skipped(self):
        g = GraphStore(":memory:")
        store = self._make_store()
        g.add_node("file", "pkg/api.py", project="p")

        obs = Observation(
            title="API deprecation notice",
            summary="Stale observation",
            type=ObsType.DECISION.value,
            project="p",
            files=["pkg/api.py"],
        )
        stored = store.upsert(obs)
        # Manually mark as superseded
        stored.superseded_by = "obs_replacement"
        store.backend.put(stored)

        stats = link_observations(store, "p", g)
        self.assertEqual(stats["observations"], 0)
        self.assertEqual(stats["about_edges"], 0)

    def test_unresolvable_file_produces_no_about_edge(self):
        g = GraphStore(":memory:")  # no file nodes pre-loaded
        store = self._make_store()

        obs = Observation(
            title="Phantom file reference",
            summary="File that is not in the graph",
            type=ObsType.PERFORMANCE.value,
            project="p",
            files=["nonexistent/missing.py"],
        )
        store.upsert(obs)

        stats = link_observations(store, "p", g)
        self.assertEqual(stats["about_edges"], 0)

    def test_no_duplicate_commit_edges(self):
        """Commit sha in both related_commits and evidence -> exactly one edge."""
        g = GraphStore(":memory:")
        store = self._make_store()

        full_sha = "cafe1234abcdef567890abcdef1234567890cafe"
        g.add_node("commit", full_sha, project="p")

        obs = Observation(
            title="Double reference check",
            summary="commit cafe1234 appears in two places",
            type=ObsType.LESSON.value,
            project="p",
            related_commits=["cafe1234"],
            evidence=["Also tagged cafe1234 in the audit log"],
        )
        store.upsert(obs)

        stats = link_observations(store, "p", g)
        self.assertEqual(stats["commit_edges"], 1)

        ref_edges = g.conn.execute(
            "SELECT * FROM graph_edges WHERE relation='references'"
        ).fetchall()
        self.assertEqual(len(ref_edges), 1)


if __name__ == "__main__":
    unittest.main()
