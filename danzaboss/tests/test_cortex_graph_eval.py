"""C4 acceptance eval (design spec section 8): with the knowledge graph bound,
retrieval must beat C3 on an extended fixture. The graph's edge is REACH:
the relevant observation shares almost no words with the prompt, but it is
attached to a file that transitively depends on the file just changed —
only the impact closure can surface it.
"""
import unittest
import _bootstrap  # noqa
from danzaboss.cortex.graph import GraphStore
from danzaboss.cortex.intent import WorkspaceState, detect
from danzaboss.cortex.observation import Importance, Observation
from danzaboss.cortex.retrieve import hybrid_retrieve
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore


def obs(title, summary, typ, **kw):
    return Observation(title=title, summary=summary, type=typ, project="p", **kw)


OLD = "2026-06-01T00:00:00+00:00"   # relevant facts are a month stale —
                                     # recency can't rescue them, only the graph


def build_fixture():
    store = ObservationStore(SqliteBackend(":memory:"))
    graph = GraphStore(":memory:")

    # high-importance noise: in a real store the importance signal's top ranks
    # belong to unrelated critical facts, not to whatever a tiny fixture holds
    noise = [
        ("Release 2.0 shipped to production", "cutover finished cleanly",
         "milestone", ["release-cutover"]),
        ("Postgres chosen over MySQL", "team standardizes on postgres",
         "decision", ["postgres-choice"]),
        ("Secrets scanner wired into CI", "gitleaks runs on every push",
         "security", ["secrets-scanner"]),
        ("Feed query cached for 10s", "p95 dropped from 900ms to 90ms",
         "performance", ["feed-cache"]),
        ("Webhook retries use exponential backoff", "vendor rate limits honored",
         "api_behavior", ["webhook-backoff"]),
        ("Import crash fixed for empty CSV rows", "guard added upstream",
         "bug_fix", ["csv-import-guard"]),
    ]
    for title, summary, typ, concepts in noise:
        store.upsert(obs(title, summary, typ, concepts=concepts,
                         importance=Importance.CRITICAL.value, confidence=95))

    # dependency chain: checkout.py -> api.py -> stripe_client.py
    for f in ("pay/stripe_client.py", "pay/api.py", "pay/checkout.py"):
        graph.add_node("file", f, project="p")
    graph.add_edge("file:pay/api.py", "file:pay/stripe_client.py", "imports")
    graph.add_edge("file:pay/checkout.py", "file:pay/api.py", "imports")

    relevant = store.upsert(obs(
        "Checkout retries double-charge on gateway timeout",
        "retry loop lacks an idempotency key; second attempt bills again",
        "root_cause", concepts=["checkout", "idempotency"],
        files=["pay/checkout.py"], importance=Importance.HIGH.value,
        confidence=95, created=OLD, updated=OLD))
    decoy_a = store.upsert(obs(
        "Stripe brand color updated on the payment page",
        "payment page stripe banner color changed for the payment redesign",
        "impl_detail", concepts=["stripe", "payment"], confidence=60,
        importance=Importance.MEDIUM.value))
    decoy_b = store.upsert(obs(
        "Payment FAQ copy mentions stripe fees",
        "docs page about payment fees and stripe payment questions",
        "convention", concepts=["payment", "faq"], confidence=60,
        importance=Importance.MEDIUM.value))
    graph.add_node("observation", relevant.id, project="p")
    graph.add_edge(f"observation:{relevant.id}", "file:pay/checkout.py", "about")

    # second scenario: auth chain, relevant obs two hops out
    for f in ("auth/jwt.py", "auth/session.py", "web/login.py"):
        graph.add_node("file", f, project="p")
    graph.add_edge("file:auth/session.py", "file:auth/jwt.py", "imports")
    graph.add_edge("file:web/login.py", "file:auth/session.py", "imports")
    relevant2 = store.upsert(obs(
        "Login screen keeps stale session cookies past rotation",
        "cookie survives key rotation; users hit phantom logouts",
        "limitation", concepts=["cookie-rotation"], files=["web/login.py"],
        importance=Importance.HIGH.value, confidence=90,
        created=OLD, updated=OLD))
    decoy_c = store.upsert(obs(
        "JWT library changelog notes reviewed",
        "reviewed jwt release notes for the jwt signing upgrade ticket",
        "dependency", concepts=["jwt", "changelog"], confidence=60,
        importance=Importance.MEDIUM.value))
    graph.add_node("observation", relevant2.id, project="p")
    graph.add_edge(f"observation:{relevant2.id}", "file:web/login.py", "about")

    queries = [
        ("touched the stripe payment client", WorkspaceState(
            changed_files=["pay/stripe_client.py"]), {relevant.id}),
        ("changed the jwt signing helper", WorkspaceState(
            changed_files=["auth/jwt.py"]), {relevant2.id}),
    ]
    assert decoy_a.id != relevant.id and decoy_b.id != relevant.id
    assert decoy_c.id != relevant2.id
    return store, graph, queries


def mrr(rankings, relevant_sets):
    total = 0.0
    for ranked, relevant in zip(rankings, relevant_sets):
        for pos, oid in enumerate(ranked, start=1):
            if oid in relevant:
                total += 1.0 / pos
                break
    return total / len(relevant_sets)


class TestGraphEval(unittest.TestCase):
    def test_c4_beats_c3_on_extended_fixture(self):
        store, graph, queries = build_fixture()
        c3, c4, relevant_sets = [], [], []
        for prompt, ws, relevant in queries:
            intent = detect(prompt, ws)
            r3 = hybrid_retrieve(store, prompt, intent, "p", limit=10,
                                 workspace=ws)
            r4 = hybrid_retrieve(store, prompt, intent, "p", limit=10,
                                 workspace=ws, graph=graph)
            c3.append([i.observation.id for i in r3.items])
            c4.append([i.observation.id for i in r4.items])
            relevant_sets.append(relevant)
        s3, s4 = mrr(c3, relevant_sets), mrr(c4, relevant_sets)
        self.assertGreater(
            s4, s3, f"C4 acceptance: graph-bound MRR ({s4:.3f}) must beat "
                    f"C3 MRR ({s3:.3f})")

    def test_graph_signal_is_ranked_in_result(self):
        store, graph, queries = build_fixture()
        prompt, ws, relevant = queries[0]
        r = hybrid_retrieve(store, prompt, detect(prompt, ws), "p",
                            workspace=ws, graph=graph)
        self.assertTrue(set(r.signals["graph"]) & relevant)


if __name__ == "__main__":
    unittest.main()
