"""C3 acceptance eval (design spec section 8): on a labeled fixture set the
fused hybrid ranking must beat BM25-alone. The fixture is adversarial by
design — each query has a lexical decoy that BM25 loves (shares the query
words) but that is explicitly not-relevant or speculative, plus true positives
that hybrid signals (when_relevant, importance, confidence) should surface.

Metric: MRR (mean reciprocal rank of the first relevant hit) over the query set.
"""
import unittest
import _bootstrap  # noqa
from danzaboss.cortex.intent import detect
from danzaboss.cortex.observation import Observation, Importance
from danzaboss.cortex.retrieve import hybrid_retrieve
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore


def obs(title, summary, typ, **kw):
    return Observation(title=title, summary=summary, type=typ, project="p", **kw)


def build_fixture() -> tuple[ObservationStore, list[tuple[str, set[str]]]]:
    store = ObservationStore(SqliteBackend(":memory:"))
    relevant_bug = store.upsert(obs(
        "JWT refresh race fixed in auth middleware",
        "cross-tab refresh duplicated tokens; serialized via redis lock",
        "bug_fix", concepts=["jwt", "auth"], when_relevant=["fix_bug", "login"],
        importance=Importance.HIGH.value, confidence=95,
        reasoning="the race broke login for multi-tab users"))
    relevant_cause = store.upsert(obs(
        "Login failures traced to expired refresh tokens",
        "root cause of intermittent login errors",
        "root_cause", concepts=["login", "token"],
        when_relevant=["fix_bug"], importance=Importance.HIGH.value, confidence=90))
    decoy_login = store.upsert(obs(
        "Login copy fix for marketing banner",
        "fixed the login copy bug on the login page login banner fix",
        "impl_detail", when_not_relevant=["fix_bug"], confidence=20,
        importance=Importance.LOW.value,
        confidence_source="speculation"))

    relevant_perf = store.upsert(obs(
        "Dashboard latency cut by caching the stats query",
        "p95 dropped from 900ms to 80ms",
        "performance", concepts=["dashboard", "latency"],
        when_relevant=["performance", "slow"],
        importance=Importance.HIGH.value, confidence=95))
    decoy_dash = store.upsert(obs(
        "Dashboard theme made slow-fade dark",
        "the dashboard is slow-fading between dashboard views now",
        "impl_detail", when_not_relevant=["performance"], confidence=20,
        importance=Importance.LOW.value, confidence_source="speculation"))

    relevant_sec = store.upsert(obs(
        "Bearer tokens redacted before storage",
        "secrets never become memory; redaction filter runs pre-insert",
        "security", tags=["security"], concepts=["token", "redaction"],
        when_relevant=["security"], importance=Importance.CRITICAL.value,
        confidence=95))
    store.upsert(obs("Chose Postgres for team store", "shared memory backend",
                     "decision", concepts=["postgres"]))
    store.upsert(obs("Feature list superseded by spec.md", "planning migration",
                     "milestone", concepts=["spec", "planning"]))

    queries = [
        ("fix the login bug", {relevant_bug.id, relevant_cause.id}),
        ("why is the dashboard slow", {relevant_perf.id}),
        ("security review of token handling", {relevant_sec.id}),
    ]
    assert decoy_login.id not in queries[0][1] and decoy_dash.id not in queries[1][1]
    return store, queries


def mrr(rankings: list[list[str]], relevant_sets: list[set[str]]) -> float:
    total = 0.0
    for ranked, relevant in zip(rankings, relevant_sets):
        for pos, oid in enumerate(ranked, start=1):
            if oid in relevant:
                total += 1.0 / pos
                break
    return total / len(relevant_sets)


class TestRetrievalEval(unittest.TestCase):
    def test_fused_ranking_beats_bm25_alone(self):
        store, queries = build_fixture()
        bm25_rankings, fused_rankings, relevant_sets = [], [], []
        for prompt, relevant in queries:
            bm25_rankings.append(
                [o.id for o in store.backend.search(prompt, project="p", limit=10)])
            intent = detect(prompt)
            result = hybrid_retrieve(store, prompt, intent, "p", limit=10)
            fused_rankings.append([i.observation.id for i in result.items])
            relevant_sets.append(relevant)

        bm25_score = mrr(bm25_rankings, relevant_sets)
        fused_score = mrr(fused_rankings, relevant_sets)
        self.assertGreater(
            fused_score, bm25_score,
            f"C3 acceptance: fused MRR ({fused_score:.3f}) must beat "
            f"BM25-alone MRR ({bm25_score:.3f})")
        self.assertEqual(fused_score, 1.0,
                         "every query's top hit should be a labeled relevant")

    def test_decoys_are_killed_not_just_demoted(self):
        store, queries = build_fixture()
        prompt, _ = queries[0]
        result = hybrid_retrieve(store, prompt, detect(prompt), "p")
        killed_titles = {k.title for k in result.killed}
        self.assertIn("Login copy fix for marketing banner", killed_titles)

    def test_every_retrieved_item_carries_reasons(self):
        store, queries = build_fixture()
        for prompt, _ in queries:
            result = hybrid_retrieve(store, prompt, detect(prompt), "p")
            for item in result.items:
                self.assertTrue(item.reasons, item.observation.title)


if __name__ == "__main__":
    unittest.main()
