import json
import unittest
import _bootstrap  # noqa
from danzaboss.cortex.explain import render, trace
from danzaboss.cortex.observation import Observation, Importance
from danzaboss.cortex.quality import build_package
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore


def seeded_store():
    store = ObservationStore(SqliteBackend(":memory:"))
    store.upsert(Observation(
        title="JWT refresh race fixed", summary="auth middleware race",
        type="bug_fix", project="p", concepts=["jwt", "auth"],
        when_relevant=["fix_bug"], importance=Importance.HIGH.value,
        confidence=95, reasoning="cross-tab refresh duplicated"))
    store.upsert(Observation(
        title="Login copy tweak", summary="fixed login page copy bug wording",
        type="impl_detail", project="p", when_not_relevant=["fix_bug"],
        confidence=20))
    return store


class TestExplain(unittest.TestCase):
    def setUp(self):
        self.bundle = build_package(seeded_store(), "fix the login auth bug", "p",
                                    budget=600)

    def test_trace_is_json_serializable_and_complete(self):
        t = trace(self.bundle)
        json.dumps(t)  # must not raise
        for key in ("prompt", "intent", "signals", "killed", "fusion",
                    "package", "quality", "replanned", "notes"):
            self.assertIn(key, t)
        self.assertEqual(t["intent"]["name"], "fix_bug")
        self.assertIn("fts", t["signals"])

    def test_kills_carry_the_trigger_term(self):
        t = trace(self.bundle)
        self.assertEqual(len(t["killed"]), 1)
        self.assertEqual(t["killed"][0]["title"], "Login copy tweak")
        self.assertTrue(t["killed"][0]["trigger"])

    def test_every_fusion_row_and_package_item_has_reasons(self):
        t = trace(self.bundle)
        for row in t["fusion"]:
            self.assertTrue(row["reasons"])
        for item in t["package"]["items"]:
            self.assertTrue(item["reasons"])

    def test_render_text_covers_the_pipeline_stages(self):
        text = render(self.bundle)
        for marker in ("intent: fix_bug", "signals:", "anti-relevance kills:",
                       "fusion (final ranking):", "package:", "quality:"):
            self.assertIn(marker, text)
        self.assertIn("Login copy tweak", text)  # the kill is visible


if __name__ == "__main__":
    unittest.main()
