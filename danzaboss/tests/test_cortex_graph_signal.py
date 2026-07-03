"""The live graph signal (C4): impact closure feeds RRF fusion.

Three guarantees: graph=None keeps the pre-C4 behavior byte-for-byte, the
closure surfaces observations no lexical signal can reach, and depth orders
the ranking (an observation on the changed file beats one two hops out).
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


def chain_fixture():
    """a.py <- b.py <- c.py (imports = depends-on); obs on b.py and c.py."""
    store = ObservationStore(SqliteBackend(":memory:"))
    graph = GraphStore(":memory:")
    for f in ("a.py", "b.py", "c.py"):
        graph.add_node("file", f, project="p")
    graph.add_edge("file:b.py", "file:a.py", "imports")
    graph.add_edge("file:c.py", "file:b.py", "imports")

    on_b = store.upsert(obs(
        "Widget cache invalidation quirk", "cache keys drift on reload",
        "limitation", concepts=["widget-cache"], files=["b.py"],
        importance=Importance.HIGH.value, confidence=90))
    on_c = store.upsert(obs(
        "Renderer palette chosen", "muted tones for the dashboard renderer",
        "decision", concepts=["palette"], files=["c.py"],
        importance=Importance.HIGH.value, confidence=90))
    graph.add_node("observation", on_b.id, project="p")
    graph.add_edge(f"observation:{on_b.id}", "file:b.py", "about")
    graph.add_node("observation", on_c.id, project="p")
    graph.add_edge(f"observation:{on_c.id}", "file:c.py", "about")
    return store, graph, on_b, on_c


class TestGraphSignal(unittest.TestCase):
    def test_no_graph_keeps_signal_empty(self):
        store, graph, on_b, on_c = chain_fixture()
        ws = WorkspaceState(changed_files=["a.py"])
        prompt = "tidy the module"
        result = hybrid_retrieve(store, prompt, detect(prompt, ws), "p",
                                 workspace=ws)
        self.assertEqual(result.signals["graph"], [])

    def test_closure_reaches_lexically_invisible_observation(self):
        store, graph, on_b, on_c = chain_fixture()
        ws = WorkspaceState(changed_files=["a.py"])
        prompt = "tidy the module"   # shares no words with either observation
        result = hybrid_retrieve(store, prompt, detect(prompt, ws), "p",
                                 workspace=ws, graph=graph)
        self.assertIn(on_b.id, result.signals["graph"])
        self.assertIn(on_c.id, result.signals["graph"])
        self.assertIn(on_b.id, [i.observation.id for i in result.items])

    def test_depth_orders_the_signal(self):
        store, graph, on_b, on_c = chain_fixture()
        ws = WorkspaceState(changed_files=["b.py"])
        prompt = "tidy the module"
        result = hybrid_retrieve(store, prompt, detect(prompt, ws), "p",
                                 workspace=ws, graph=graph)
        sig = result.signals["graph"]
        # on_b sits on the changed file (depth 0); on_c is one hop out
        self.assertEqual(sig, [on_b.id, on_c.id])


if __name__ == "__main__":
    unittest.main()
