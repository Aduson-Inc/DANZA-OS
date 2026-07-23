"""C3 integration surfaces: the /api/explain endpoint runs the real pipeline,
and `danza cortex retrieve` works end to end."""
import io
import json
import tempfile
import unittest
import urllib.parse
import urllib.request

import _bootstrap  # noqa
from danzaboss.cortex import commands
from danzaboss.cortex.observation import Observation, Importance
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore
from danzaboss.cortex.ui.server import serve_in_thread


def seed(root: str) -> ObservationStore:
    store = ObservationStore(SqliteBackend(commands.db_path(root)))
    project = root.split("/")[-1]
    store.upsert(Observation(
        title="JWT refresh race fixed", summary="auth middleware race condition",
        type="bug_fix", project=project, concepts=["jwt", "auth"],
        when_relevant=["fix_bug"], importance=Importance.HIGH.value,
        confidence=95, reasoning="cross-tab refresh duplicated"))
    store.upsert(Observation(
        title="Fail-closed auth convention", summary="validation raises on violation",
        type="convention", project=project, concepts=["auth", "failclosed"],
        importance=Importance.CRITICAL.value, confidence=95))
    return store


class TestExplainEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = cls.tmp.name
        seed(cls.root)
        cls.server, cls.port = serve_in_thread(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def _get(self, path):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:  # HTTPError carries an open response socket
                return e.code, json.loads(e.read())

    def test_explain_runs_the_real_pipeline(self):
        q = urllib.parse.urlencode({"prompt": "fix the jwt auth bug", "budget": 600})
        status, t = self._get(f"/api/explain?{q}")
        self.assertEqual(status, 200)
        self.assertEqual(t["intent"]["name"], "fix_bug")
        self.assertTrue(t["fusion"])
        self.assertTrue(t["package"]["items"])
        self.assertLessEqual(t["package"]["used"], 600)
        for item in t["package"]["items"]:
            self.assertTrue(item["reasons"])

    def test_explain_requires_a_prompt(self):
        status, body = self._get("/api/explain")
        self.assertEqual(status, 400)
        self.assertIn("error", body)


class TestRetrieveCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        seed(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, argv):
        import contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = commands.main(argv, root=self.root, stdin=io.StringIO(""))
        return rc, out.getvalue()

    def test_default_output_is_the_package_block(self):
        rc, out = self._run(["retrieve", "fix", "the", "jwt", "auth", "bug"])
        self.assertEqual(rc, 0)
        self.assertIn("[CORTEX package] intent=fix_bug", out)
        self.assertIn("JWT refresh race fixed", out)

    def test_json_trace_and_explain_render(self):
        rc, out = self._run(["retrieve", "auth", "--json"])
        self.assertEqual(rc, 0)
        t = json.loads(out)
        self.assertIn("fusion", t)
        rc, out = self._run(["retrieve", "auth", "--explain"])
        self.assertEqual(rc, 0)
        self.assertIn("quality:", out)

    def test_retrieve_records_usage(self):
        self._run(["retrieve", "fix", "the", "jwt", "auth", "bug"])
        store = ObservationStore(SqliteBackend(commands.db_path(self.root)))
        used = [o for o in store.backend.all() if o.usage_count > 0]
        self.assertTrue(used, "retrieved observations must record usage")

    def test_prompt_is_required(self):
        rc, _ = self._run(["retrieve", "--json"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
