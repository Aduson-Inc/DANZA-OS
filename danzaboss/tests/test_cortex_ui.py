"""C2 acceptance: every dashboard route serves, JSON shapes hold, settings persist."""
import json
import tempfile
import unittest
import urllib.error
import urllib.request

import _bootstrap  # noqa
from danzaboss.cortex.observation import Observation, ObsType, Importance
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore
from danzaboss.cortex import commands
from danzaboss.cortex.ui.server import serve_in_thread, load_settings, snapshot_version


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


class TestCortexUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = cls.tmp.name
        store = ObservationStore(SqliteBackend(commands.db_path(cls.root)))
        cls.obs = store.upsert(Observation(
            title="Redis chosen for JWT cache", summary="prevents refresh races",
            type=ObsType.DECISION.value, project=cls.root.split("/")[-1],
            importance=Importance.CRITICAL.value, confidence=95,
            reasoning="duplicate refresh across tabs", concepts=["redis", "jwt"]))
        cls.server, cls.port = serve_in_thread(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()

    def test_index_and_static_served(self):
        status, ctype, body = get(self.port, "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"CORTEX", body)
        for asset in ("/static/app.css", "/static/app.js"):
            status, _, _ = get(self.port, asset)
            self.assertEqual(status, 200, asset)

    def test_observations_feed_and_filters(self):
        _, _, body = get(self.port, "/api/observations")
        data = json.loads(body)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["title"], "Redis chosen for JWT cache")
        self.assertIn("read_tokens", data["items"][0])
        _, _, body = get(self.port, "/api/observations?q=redis")
        self.assertEqual(json.loads(body)["total"], 1)
        _, _, body = get(self.port, "/api/observations?type=bug_fix")
        self.assertEqual(json.loads(body)["total"], 0)

    def test_observation_detail_and_404(self):
        _, _, body = get(self.port, f"/api/observations/{self.obs.id}")
        self.assertEqual(json.loads(body)["reasoning"], "duplicate refresh across tabs")
        try:
            status, _, _ = get(self.port, "/api/observations/obs_nope")
        except urllib.error.HTTPError as e:
            status = e.code
        self.assertEqual(status, 404)

    def test_stats_and_sessions(self):
        _, _, body = get(self.port, "/api/stats")
        s = json.loads(body)
        self.assertEqual(s["observations_stored"], 1)
        self.assertIn("decision", s["by_type"])
        _, _, body = get(self.port, "/api/sessions")
        self.assertIn("items", json.loads(body))

    def test_settings_roundtrip(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/settings",
            data=json.dumps({"max_full": 9, "bogus_key": 1}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            saved = json.loads(r.read())
        self.assertEqual(saved["max_full"], 9)
        self.assertNotIn("bogus_key", saved)
        self.assertEqual(load_settings(self.root)["max_full"], 9)

    def test_mutation_rejected_everywhere_else(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/observations",
            data=b"{}", method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        self.assertEqual(status, 405)

    def test_feed_items_carry_simple_numbers(self):
        _, _, body = get(self.port, "/api/observations")
        item = json.loads(body)["items"][0]
        self.assertGreaterEqual(item.get("num", 0), 1)  # human-friendly #N

    def test_meta_lists_projects_and_environments(self):
        _, _, body = get(self.port, "/api/meta")
        m = json.loads(body)
        self.assertIn(m["project"], m["projects"])
        self.assertTrue(m["environments"])

    def test_console_streams_capture_telemetry(self):
        # seed one session with a mutation event via the real hook handlers
        commands._hook_session_start(self.root, {"session_id": "ui-s1"})
        from danzaboss.cortex.events import CaptureLog
        log = CaptureLog(commands.db_path(self.root))
        log.record_event("ui-s1", "Edit", file_path="danzaboss/cli.py")
        _, _, body = get(self.port, "/api/console")
        items = json.loads(body)["items"]
        kinds = {i["kind"] for i in items}
        self.assertIn("mutation", kinds)
        self.assertIn("session", kinds)
        mut = next(i for i in items if i["kind"] == "mutation")
        self.assertEqual(mut["detail"], "danzaboss/cli.py")

    def test_snapshot_version_moves_on_write(self):
        v1 = snapshot_version(commands.db_path(self.root))
        ObservationStore(SqliteBackend(commands.db_path(self.root))).upsert(
            Observation(title="another fact entirely", summary="s",
                        type=ObsType.LESSON.value, project="p",
                        concepts=["completely", "different"]))
        self.assertNotEqual(v1, snapshot_version(commands.db_path(self.root)))


class TestGraphEndpoint(unittest.TestCase):
    """C4: /api/graph serves search, subgraphs, impact closures — read-only."""

    @classmethod
    def setUpClass(cls):
        from danzaboss.cortex.graph import GraphStore
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = cls.tmp.name
        g = GraphStore(commands.db_path(cls.root))
        for name in ("app.py", "lib_a.py", "lib_b.py", "core.py"):
            g.add_node("file", name, project="p")
        g.add_edge("file:app.py", "file:lib_a.py", "imports")
        g.add_edge("file:app.py", "file:lib_b.py", "imports")
        g.add_edge("file:lib_a.py", "file:core.py", "imports")
        g.add_edge("file:lib_b.py", "file:core.py", "imports")
        cls.server, cls.port = serve_in_thread(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()

    def test_bare_call_returns_overview(self):
        status, _, body = get(self.port, "/api/graph")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["stats"]["nodes"], 4)
        self.assertTrue(data["top"])
        self.assertIn("degree", data["top"][0])

    def test_search_returns_matches(self):
        _, _, body = get(self.port, "/api/graph?q=lib")
        names = {m["name"] for m in json.loads(body)["matches"]}
        self.assertEqual(names, {"lib_a.py", "lib_b.py"})

    def test_impact_subgraph(self):
        _, _, body = get(self.port,
                         "/api/graph?node=file:core.py&mode=impact&depth=3")
        data = json.loads(body)
        ids = {n["id"] for n in data["nodes"]}
        self.assertIn("file:app.py", ids)
        self.assertEqual(data["mode"], "impact")
        self.assertTrue(data["edges"])

    def test_unknown_node_404(self):
        try:
            get(self.port, "/api/graph?node=file:nope.py")
            self.fail("expected 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_post_is_rejected_read_only(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/graph", data=b"{}",
            method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            self.fail("expected 405")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 405)


class TestWorkflowEndpoint(unittest.TestCase):
    """C4.5 UI: /api/workflow aggregates the file graph into subsystem blocks."""

    @classmethod
    def setUpClass(cls):
        from danzaboss.cortex.graph import GraphStore
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = cls.tmp.name
        g = GraphStore(commands.db_path(cls.root))
        files = ("danzaboss/cli.py", "danzaboss/kernel/state.py",
                 "danzaboss/kernel/profile.py", "danzaboss/hooks/guards.py",
                 "README.md")
        for name in files:
            g.add_node("file", name, project="p")
        g.add_edge("file:danzaboss/cli.py", "file:danzaboss/kernel/profile.py", "imports")
        g.add_edge("file:danzaboss/cli.py", "file:danzaboss/hooks/guards.py", "imports")
        g.add_edge("file:danzaboss/hooks/guards.py",
                   "file:danzaboss/kernel/state.py", "imports")
        g.add_node("observation", "obs_x", project="p")
        g.add_edge("observation:obs_x", "file:danzaboss/kernel/profile.py", "about")
        cls.server, cls.port = serve_in_thread(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()

    def test_blocks_are_groups_not_files(self):
        _, _, body = get(self.port, "/api/workflow")
        data = json.loads(body)
        ids = {n["id"] for n in data["nodes"]}
        self.assertEqual(ids, {"danzaboss", "danzaboss/kernel",
                               "danzaboss/hooks", "root"})
        kernel = next(n for n in data["nodes"] if n["id"] == "danzaboss/kernel")
        self.assertEqual(kernel["file_count"], 2)
        self.assertIn("danzaboss/kernel/profile.py", kernel["files"])
        self.assertEqual(kernel["observations"], 1)  # obs_x is about profile.py

    def test_flows_are_aggregated_imports_between_groups(self):
        _, _, body = get(self.port, "/api/workflow")
        flows = {(e["src"], e["dst"]): e["weight"]
                 for e in json.loads(body)["edges"]}
        self.assertEqual(flows[("danzaboss", "danzaboss/kernel")], 1)
        self.assertEqual(flows[("danzaboss", "danzaboss/hooks")], 1)
        self.assertEqual(flows[("danzaboss/hooks", "danzaboss/kernel")], 1)
        self.assertTrue(all(s != d for (s, d) in flows))  # no self-loops


if __name__ == "__main__":
    unittest.main()
