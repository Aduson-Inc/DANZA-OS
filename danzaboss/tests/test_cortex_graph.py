"""GraphStore: typed nodes/edges + recursive-CTE closures (C4, spec section 8).

The impact closure is the acceptance primitive: "what breaks if X changes" =
every node with a dependency path INTO X. Cycles must terminate (depth cap +
UNION dedupe) and results must be deterministic (depth, then id ordering).
"""
import unittest
import _bootstrap  # noqa
from danzaboss.cortex.graph import GraphStore, node_id


def diamond() -> GraphStore:
    """app -> lib_a -> core, app -> lib_b -> core (imports = depends-on)."""
    g = GraphStore(":memory:")
    for name in ("app.py", "lib_a.py", "lib_b.py", "core.py"):
        g.add_node("file", name, project="p")
    g.add_edge("file:app.py", "file:lib_a.py", "imports")
    g.add_edge("file:app.py", "file:lib_b.py", "imports")
    g.add_edge("file:lib_a.py", "file:core.py", "imports")
    g.add_edge("file:lib_b.py", "file:core.py", "imports")
    return g


class TestGraphStore(unittest.TestCase):
    def test_node_id_and_upsert(self):
        g = GraphStore(":memory:")
        nid = g.add_node("file", "a.py", project="p", language="python")
        self.assertEqual(nid, node_id("file", "a.py"))
        g.add_node("file", "a.py", project="p", size=10)  # attrs merge
        n = g.node(nid)
        self.assertEqual(n.attrs["language"], "python")
        self.assertEqual(n.attrs["size"], 10)
        self.assertEqual(g.stats()["nodes"], 1)

    def test_edge_upsert_no_duplicates(self):
        g = diamond()
        g.add_edge("file:app.py", "file:lib_a.py", "imports")  # again
        self.assertEqual(g.stats()["edges"], 4)

    def test_impact_is_reverse_dependency_closure(self):
        g = diamond()
        got = g.impact("file:core.py")
        self.assertEqual(got, [("file:lib_a.py", 1), ("file:lib_b.py", 1),
                               ("file:app.py", 2)])

    def test_dependencies_is_forward_closure(self):
        g = diamond()
        got = g.dependencies("file:app.py")
        self.assertEqual(got, [("file:lib_a.py", 1), ("file:lib_b.py", 1),
                               ("file:core.py", 2)])

    def test_cycle_terminates(self):
        g = GraphStore(":memory:")
        g.add_node("file", "a.py"); g.add_node("file", "b.py")
        g.add_edge("file:a.py", "file:b.py", "imports")
        g.add_edge("file:b.py", "file:a.py", "imports")
        self.assertEqual(g.impact("file:a.py"), [("file:b.py", 1)])

    def test_impact_respects_relations_filter(self):
        g = diamond()
        g.add_node("commit", "abc123")
        g.add_edge("commit:abc123", "file:core.py", "modifies")
        ids = {nid for nid, _ in g.impact("file:core.py")}
        self.assertNotIn("commit:abc123", ids)

    def test_neighbors_both_directions(self):
        g = diamond()
        n = g.neighbors("file:lib_a.py")
        self.assertIn(("file:core.py", "imports"), n["out"])
        self.assertIn(("file:app.py", "imports"), n["in"])

    def test_path_shortest(self):
        g = diamond()
        self.assertEqual(g.path("file:app.py", "file:core.py"),
                         ["file:app.py", "file:lib_a.py", "file:core.py"])
        self.assertEqual(g.path("file:core.py", "file:app.py"), [])

    def test_resolve_file_suffix(self):
        g = GraphStore(":memory:")
        g.add_node("file", "danzaboss/cortex/store.py")
        self.assertEqual(g.resolve_file("/home/x/repo/danzaboss/cortex/store.py"),
                         "file:danzaboss/cortex/store.py")
        self.assertEqual(g.resolve_file("danzaboss/cortex/store.py"),
                         "file:danzaboss/cortex/store.py")
        self.assertIsNone(g.resolve_file("nope.py"))

    def test_find_and_clear(self):
        g = diamond()
        hits = g.find("lib", kinds=["file"])
        self.assertEqual({n.name for n in hits}, {"lib_a.py", "lib_b.py"})
        g.clear("p")
        self.assertEqual(g.stats()["nodes"], 0)
        self.assertEqual(g.stats()["edges"], 0)

    def test_attached_observations(self):
        g = diamond()
        g.add_node("observation", "obs_1")
        g.add_edge("observation:obs_1", "file:core.py", "about")
        self.assertEqual(g.attached_observations("file:core.py"), ["obs_1"])

    def test_subgraph_impact_mode_includes_observations(self):
        g = diamond()
        g.add_node("observation", "obs_1")
        g.add_edge("observation:obs_1", "file:app.py", "about")
        nodes, edges = g.subgraph("file:core.py", depth=3, mode="impact")
        ids = {n.id for n in nodes}
        self.assertIn("file:core.py", ids)
        self.assertIn("file:app.py", ids)
        self.assertIn("observation:obs_1", ids)
        self.assertTrue(any(e["relation"] == "about" for e in edges))

    def test_subgraph_neighborhood_mode(self):
        g = diamond()
        nodes, _ = g.subgraph("file:lib_a.py", depth=1)
        ids = {n.id for n in nodes}
        self.assertEqual(ids, {"file:lib_a.py", "file:app.py", "file:core.py"})


if __name__ == "__main__":
    unittest.main()
