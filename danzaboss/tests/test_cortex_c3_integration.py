"""C3 integration surfaces: the /api/explain endpoint runs the real pipeline,
`danza cortex retrieve` works end to end, and ContextPipeline composes a
per-driver CORTEX slice next to the MemoryStore section."""
import io
import json
import tempfile
import unittest
import urllib.parse
import urllib.request

import _bootstrap  # noqa
from danzaboss.context.pipeline import ContextPipeline, DRIVER_CORTEX
from danzaboss.cortex import commands
from danzaboss.cortex.observation import Observation, Importance
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore
from danzaboss.cortex.ui.server import serve_in_thread
from danzaboss.memory.store import MemoryStore


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
        cls.tmp.cleanup()

    def _get(self, path):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
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


class TestPipelineCortexSource(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.cortex = seed(self.root)
        self.project = self.root.split("/")[-1]

    def tearDown(self):
        self.tmp.cleanup()

    def test_driver_slice_added_within_budget(self):
        pipe = ContextPipeline(MemoryStore(self.root), cortex_store=self.cortex,
                               project=self.project)
        ctx = pipe.compile("bonnie-qa", "t1", "verify the jwt auth bug fix",
                           cortex_budget=400)
        self.assertIn("CORTEX observations", ctx.sections)
        body = ctx.sections["CORTEX observations"]
        self.assertIn("JWT refresh race fixed", body)          # bonnie sees bugs
        self.assertNotIn("Fail-closed auth convention", body)  # type-filtered out

    def test_no_cortex_store_means_no_section(self):
        ctx = ContextPipeline(MemoryStore(self.root)).compile(
            "bonnie-qa", "t1", "anything")
        self.assertNotIn("CORTEX observations", ctx.sections)

    def test_every_driver_profile_uses_known_intents_and_types(self):
        from danzaboss.cortex.intent import INTENTS
        from danzaboss.cortex.observation import ObsType
        valid_types = {t.value for t in ObsType}
        for driver, prof in DRIVER_CORTEX.items():
            self.assertIn(prof["intent"], INTENTS, driver)
            if prof["types"] is not None:
                self.assertTrue(set(prof["types"]) <= valid_types, driver)


if __name__ == "__main__":
    unittest.main()
