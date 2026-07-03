import unittest
import _bootstrap  # noqa
from danzaboss.cortex.intent import WorkspaceState, detect
from danzaboss.cortex.observation import Observation, Importance
from danzaboss.cortex.retrieve import hybrid_retrieve
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore


def obs(title, summary, typ="decision", project="p", **kw):
    return Observation(title=title, summary=summary, type=typ, project=project, **kw)


class TestHybridRetrieve(unittest.TestCase):
    def setUp(self):
        self.store = ObservationStore(SqliteBackend(":memory:"))

    def _retrieve(self, prompt, **kw):
        intent = detect(prompt)
        return hybrid_retrieve(self.store, prompt, intent, "p", **kw)

    def test_multi_signal_fusion_and_reasons(self):
        self.store.upsert(obs("JWT refresh race fixed", "auth middleware race",
                              typ="bug_fix", concepts=["jwt", "auth"],
                              when_relevant=["fix_bug", "auth"],
                              importance=Importance.HIGH.value, confidence=95))
        self.store.upsert(obs("Switched to Postgres", "for session storage",
                              typ="decision", concepts=["postgres"]))
        result = self._retrieve("fix the auth race bug")
        self.assertTrue(result.items)
        top = result.items[0]
        self.assertEqual(top.observation.title, "JWT refresh race fixed")
        self.assertGreaterEqual(len(top.signal_ranks), 2)  # fused, not single-signal
        self.assertTrue(top.reasons, "every item must carry reasons")

    def test_anti_relevance_kills_not_demotes(self):
        self.store.upsert(obs("Login copy fix for banner",
                              "fixed the login copy bug on the login page",
                              typ="impl_detail",
                              when_not_relevant=["fix_bug"],
                              confidence=20))
        result = self._retrieve("fix the login bug")
        ids = [i.observation.id for i in result.items]
        self.assertEqual(len(result.killed), 1)
        self.assertNotIn(result.killed[0].observation_id, ids)
        self.assertTrue(result.killed[0].trigger)  # trigger term recorded

    def test_graph_signal_is_stubbed_empty(self):
        self.store.upsert(obs("Anything", "body", concepts=["anything"]))
        result = self._retrieve("anything")
        self.assertEqual(result.signals["graph"], [])

    def test_superseded_and_archived_excluded(self):
        live = obs("Live decision", "current", concepts=["live"])
        live.superseded_by = "obs_x"
        self.store.backend.put(live)
        old = obs("Archived note", "old", concepts=["live"],
                  importance=Importance.ARCHIVE.value)
        self.store.backend.put(old)
        result = self._retrieve("live decision note")
        self.assertEqual(result.items, [])

    def test_types_filter_narrows_candidates(self):
        self.store.upsert(obs("A bug", "auth bug", typ="bug_fix", concepts=["auth"]))
        self.store.upsert(obs("A decision", "auth choice", typ="decision",
                              concepts=["auth"]))
        result = self._retrieve("auth", types=["bug_fix"])
        self.assertEqual([i.observation.type for i in result.items], ["bug_fix"])

    def test_links_signal_expands_from_changed_files(self):
        self.store.upsert(obs("Auth conventions", "always fail closed",
                              typ="convention", files=["auth.py"],
                              concepts=["failclosed"]))
        ws = WorkspaceState(changed_files=["auth.py"])
        result = self._retrieve("continue the current work", workspace=ws)
        self.assertIn("links", result.items[0].signal_ranks)

    def test_importance_and_confidence_shape_final_score(self):
        self.store.upsert(obs("Critical rule", "auth rule", concepts=["auth"],
                              importance=Importance.CRITICAL.value, confidence=100))
        self.store.upsert(obs("Speculative note", "auth guess", typ="impl_detail",
                              concepts=["auth"],
                              importance=Importance.LOW.value, confidence=20))
        result = self._retrieve("auth")
        self.assertEqual(result.items[0].observation.title, "Critical rule")
        self.assertGreater(result.items[0].final, result.items[1].final)


if __name__ == "__main__":
    unittest.main()
