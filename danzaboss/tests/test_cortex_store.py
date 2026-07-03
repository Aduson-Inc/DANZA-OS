import unittest
import _bootstrap  # noqa
from danzaboss.cortex.observation import Observation, ObsType, Importance
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore
from danzaboss.cortex.ports import Query


def obs(title, summary, typ=ObsType.DECISION.value, project="p", **kw):
    return Observation(title=title, summary=summary, type=typ, project=project, **kw)


class TestStoreEvolution(unittest.TestCase):
    def setUp(self):
        self.store = ObservationStore(SqliteBackend(":memory:"))

    def test_upsert_merges_near_duplicate_not_duplicates(self):
        # ACCEPTANCE #1: merge instead of duplicate
        a = obs("Redis added for JWT refresh", "initial",
                concepts=["redis", "jwt"], files=["auth.ts"], confidence=60)
        self.store.upsert(a)
        b = obs("Redis added to fix JWT refresh race", "fuller reasoning",
                concepts=["redis", "jwt", "race"], files=["auth.ts"], confidence=90,
                reasoning="prevents duplicate refresh across tabs")
        self.store.upsert(b)
        all_obs = self.store.backend.all("p")
        self.assertEqual(len(all_obs), 1, "near-duplicate should merge into one row")
        merged = all_obs[0]
        self.assertIn("race", merged.concepts)              # unioned
        self.assertEqual(merged.summary, "fuller reasoning")  # higher-confidence body kept
        self.assertGreaterEqual(merged.confidence, 90)        # confidence climbed
        self.assertTrue(any(h["event"] == "merged" for h in merged.history))

    def test_distinct_observations_do_not_merge(self):
        self.store.upsert(obs("Redis added", "x", concepts=["redis"]))
        self.store.upsert(obs("Switched to Postgres", "y", concepts=["postgres"],
                              typ=ObsType.DEPENDENCY.value))
        self.assertEqual(len(self.store.backend.all("p")), 2)

    def test_supersede_marks_old(self):
        a = self.store.upsert(obs("Auth v1", "old"))
        b = obs("Auth v2", "new", concepts=["totally", "different"])
        b.supersedes = a.id
        self.store.upsert(b)
        old = self.store.get(a.id)
        self.assertEqual(old.superseded_by, b.id)

    def test_query_ranks_by_importance_and_confidence(self):
        self.store.upsert(obs("JWT critical bug", "s", typ=ObsType.SECURITY.value,
                              concepts=["jwt"], importance=Importance.CRITICAL.value, confidence=95))
        self.store.upsert(obs("JWT minor note", "s", typ=ObsType.IMPL_DETAIL.value,
                              concepts=["jwt"], importance=Importance.LOW.value, confidence=40))
        res = self.store.query(Query(text="jwt", project="p"))
        self.assertEqual(res[0].observation.importance, Importance.CRITICAL.value)

    def test_superseded_not_returned(self):
        a = self.store.upsert(obs("Old", "o", concepts=["auth"]))
        b = obs("New", "n", concepts=["zzz"]); b.supersedes = a.id
        self.store.upsert(b)
        res = self.store.query(Query(text="auth", project="p"))
        self.assertTrue(all(s.observation.id != a.id for s in res))

    def test_explainability_reasons_present(self):
        self.store.upsert(obs("JWT thing", "s", concepts=["jwt"], importance=Importance.HIGH.value))
        res = self.store.query(Query(text="jwt", project="p"))
        self.assertTrue(res[0].reasons)  # every result explains itself

    def test_aging_archives_expired_temporary(self):
        self.store.upsert(obs("temp note", "s", importance=Importance.TEMPORARY.value,
                              created="2020-01-01T00:00:00+00:00"))
        rep = self.store.age(now="2026-07-01T00:00:00+00:00")
        self.assertEqual(rep["archived"], 1)

    def test_aging_keeps_critical(self):
        self.store.upsert(obs("crit", "s", importance=Importance.CRITICAL.value,
                              created="2020-01-01T00:00:00+00:00"))
        rep = self.store.age(now="2026-07-01T00:00:00+00:00")
        self.assertEqual(rep["archived"], 0)


class TestAntiRelevancePrecision(unittest.TestCase):
    """ACCEPTANCE #2: when_not_relevant measurably raises precision."""

    def _corpus(self, store):
        # 'billing' query. One obs is keyword-relevant (mentions billing) but is a
        # TEST fixture note explicitly NOT relevant when the intent is 'fix_bug'.
        store.upsert(Observation(title="Billing webhook retry logic", summary="real",
                     type=ObsType.IMPL_DETAIL.value, project="p",
                     concepts=["billing", "webhook"], tags=["billing"]))
        store.upsert(Observation(title="Billing race root cause", summary="real",
                     type=ObsType.ROOT_CAUSE.value, project="p",
                     concepts=["billing", "race"], tags=["billing"]))
        # false positive: keyword-matches 'billing' but not useful for a bug fix
        store.upsert(Observation(title="Billing demo seed data", summary="fixture only",
                     type=ObsType.IMPL_DETAIL.value, project="p",
                     concepts=["billing", "seed"], tags=["billing"],
                     when_not_relevant=["fix_bug", "bug"]))

    def test_precision_improves_with_anti_relevance(self):
        # Baseline: no intent -> anti-relevance can't fire, false positive slips in.
        base_store = ObservationStore(SqliteBackend(":memory:"))
        self._corpus(base_store)
        base = base_store.query(Query(text="billing", project="p", limit=10))
        base_titles = {s.observation.title for s in base}
        self.assertIn("Billing demo seed data", base_titles)  # FP present without intent

        # With intent=fix_bug -> anti-relevance suppresses the fixture note.
        store = ObservationStore(SqliteBackend(":memory:"))
        self._corpus(store)
        res = store.query(Query(text="billing", project="p", intent="fix_bug", limit=10))
        titles = {s.observation.title for s in res}
        self.assertNotIn("Billing demo seed data", titles)   # FP suppressed

        def precision(titles):
            relevant = {"Billing webhook retry logic", "Billing race root cause"}
            return len(titles & relevant) / max(1, len(titles))

        self.assertGreater(precision(titles), precision(base_titles))


if __name__ == "__main__":
    unittest.main()
