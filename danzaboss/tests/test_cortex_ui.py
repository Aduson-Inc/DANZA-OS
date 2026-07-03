"""C2 acceptance: every dashboard route serves, JSON shapes hold, settings persist."""
import json
import tempfile
import unittest
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

    def test_snapshot_version_moves_on_write(self):
        v1 = snapshot_version(commands.db_path(self.root))
        ObservationStore(SqliteBackend(commands.db_path(self.root))).upsert(
            Observation(title="another fact entirely", summary="s",
                        type=ObsType.LESSON.value, project="p",
                        concepts=["completely", "different"]))
        self.assertNotEqual(v1, snapshot_version(commands.db_path(self.root)))


if __name__ == "__main__":
    unittest.main()
