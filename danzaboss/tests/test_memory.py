import tempfile, unittest
import _bootstrap  # noqa
from danzaboss.memory.store import MemoryStore, SCOPES


class TestMemory(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore(tempfile.mkdtemp())

    def test_remember_and_stats(self):
        self.store.remember("semantic", "React uses functional components", ["react"])
        self.store.remember("episodic", "Turn 1 built login", ["turn1"])
        s = self.store.stats()
        self.assertEqual(s["semantic"], 1)
        self.assertEqual(s["episodic"], 1)

    def test_unknown_scope_rejected(self):
        with self.assertRaises(ValueError):
            self.store.remember("nonsense", "x")

    def test_retrieve_ranks_by_relevance(self):
        self.store.remember("semantic", "authentication uses bcrypt hashing", ["auth"])
        self.store.remember("semantic", "the footer is blue", ["design"])
        got = self.store.retrieve("how is auth password hashing done", max_records=1)
        self.assertEqual(len(got), 1)
        self.assertIn("bcrypt", got[0].text)

    def test_token_budget_bounds_results(self):
        for i in range(50):
            self.store.remember("semantic", "fact number %d " % i * 20, ["f"])
        got = self.store.retrieve("fact", token_budget=100, max_records=50)
        used = sum(r.est_tokens() for r in got)
        self.assertLessEqual(used, 100)

    def test_max_records_bounds_results(self):
        for i in range(30):
            self.store.remember("episodic", "event %d" % i, ["e"])
        got = self.store.retrieve("event", token_budget=10000, max_records=5)
        self.assertLessEqual(len(got), 5)

    def test_append_only_persists_across_instances(self):
        self.store.remember("procedural", "always run tests", ["rule"])
        from danzaboss.memory.store import MemoryStore as MS
        s2 = MS(self.store.root)
        self.assertEqual(s2.stats()["procedural"], 1)


if __name__ == "__main__":
    unittest.main()
