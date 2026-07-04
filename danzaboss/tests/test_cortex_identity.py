"""Tests for cortex.identity — stable project identity + rename self-heal.

The regression these guard: renaming the repo directory made every
project-scoped query return empty because identity was the dir basename.
"""

import json
import os
import sqlite3
import tempfile
import unittest

from danzaboss.cortex.identity import marker_path, migrate_project, resolve_project
from danzaboss.cortex.observation import Observation
from danzaboss.cortex.sqlite_backend import SqliteBackend


def _make_repo(parent: str, name: str) -> str:
    root = os.path.join(parent, name)
    os.makedirs(os.path.join(root, ".danza", "cortex"))
    return root


def _seed_observation(root: str, project: str) -> str:
    be = SqliteBackend(os.path.join(root, ".danza", "cortex", "cortex.db"))
    obs = Observation(title="seed", summary="seeded row", type="impl_detail",
                      project=project)
    be.put(obs)
    be.conn.close()
    return obs.id


class TestResolveProject(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_fresh_repo_pins_basename(self):
        root = _make_repo(self.tmp.name, "myapp")
        self.assertEqual(resolve_project(root), "myapp")
        with open(marker_path(root)) as fh:
            self.assertEqual(json.load(fh)["project"], "myapp")

    def test_marker_wins_over_basename(self):
        root = _make_repo(self.tmp.name, "renamed-dir")
        with open(marker_path(root), "w") as fh:
            json.dump({"project": "original-name"}, fh)
        self.assertEqual(resolve_project(root), "original-name")

    def test_rename_heals_legacy_rows(self):
        root = _make_repo(self.tmp.name, "NEW-NAME")
        _seed_observation(root, "OLD NAME")
        self.assertEqual(resolve_project(root), "NEW-NAME")
        be = SqliteBackend(os.path.join(root, ".danza", "cortex", "cortex.db"))
        self.assertEqual(len(be.search("seed", project="NEW-NAME")), 1)
        self.assertEqual(be.search("seed", project="OLD NAME"), [])
        be.conn.close()

    def test_resolve_is_idempotent(self):
        root = _make_repo(self.tmp.name, "stable")
        _seed_observation(root, "stable")
        self.assertEqual(resolve_project(root), "stable")
        self.assertEqual(resolve_project(root), "stable")

    def test_corrupt_marker_falls_back_to_basename(self):
        root = _make_repo(self.tmp.name, "fallback")
        with open(marker_path(root), "w") as fh:
            fh.write("{not json")
        self.assertEqual(resolve_project(root), "fallback")


class TestMigrateProject(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_migrates_all_scoped_tables(self):
        root = _make_repo(self.tmp.name, "repo")
        db = os.path.join(root, ".danza", "cortex", "cortex.db")
        _seed_observation(root, "old")
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE sessions (id TEXT, project TEXT)")
        conn.execute("INSERT INTO sessions VALUES ('s1', 'old')")
        conn.execute("CREATE TABLE graph_nodes (id TEXT, project TEXT)")
        conn.execute("INSERT INTO graph_nodes VALUES ('n1', 'old')")
        conn.commit()
        conn.close()
        moved = migrate_project(root, "new")
        self.assertEqual(moved, {"observations": 1, "sessions": 1,
                                 "graph_nodes": 1})
        conn = sqlite3.connect(db)
        for table in ("observations", "sessions", "graph_nodes"):
            rows = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE project = 'new'").fetchone()[0]
            self.assertEqual(rows, 1, table)
        conn.close()

    def test_no_db_is_a_noop(self):
        root = _make_repo(self.tmp.name, "empty")
        moved = migrate_project(root, "empty")
        self.assertEqual(sum(moved.values()), 0)


if __name__ == "__main__":
    unittest.main()
