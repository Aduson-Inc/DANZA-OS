import unittest
import _bootstrap  # noqa
from danzaboss.cortex.observation import Observation, ObsType, Importance
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore
from danzaboss.cortex.inject import build_context, rank_for_injection, est_tokens


def obs(title, **kw):
    kw.setdefault("summary", "s")
    kw.setdefault("type", ObsType.DECISION.value)
    kw.setdefault("project", "p")
    return Observation(title=title, **kw)


class TestInjection(unittest.TestCase):
    def setUp(self):
        self.store = ObservationStore(SqliteBackend(":memory:"))

    def test_empty_store_yields_empty_block(self):
        self.assertEqual(build_context(self.store, "p"), "")

    def test_critical_outranks_low(self):
        self.store.upsert(obs("minor note", importance=Importance.LOW.value,
                              concepts=["a"]))
        self.store.upsert(obs("auth is critical", importance=Importance.CRITICAL.value,
                              concepts=["b"]))
        ranked = rank_for_injection(self.store, "p")
        self.assertEqual(ranked[0].title, "auth is critical")

    def test_changed_file_overlap_boosts(self):
        self.store.upsert(obs("touches cli", files=["danzaboss/cli.py"],
                              concepts=["cli"]))
        self.store.upsert(obs("touches nothing", concepts=["other"]))
        ranked = rank_for_injection(self.store, "p",
                                    changed_files=["danzaboss/cli.py"])
        self.assertEqual(ranked[0].title, "touches cli")

    def test_block_contains_index_and_full_sections(self):
        self.store.upsert(obs("Redis decision", summary="why redis",
                              reasoning="races", concepts=["redis"]))
        block = build_context(self.store, "p", max_full=1)
        self.assertIn("[CORTEX]", block)
        self.assertIn("Redis decision", block)
        self.assertIn("why redis", block)          # full body present
        self.assertIn("danza cortex get", block)   # fetch-by-id hint

    def test_token_ceiling_limits_full_bodies(self):
        for i in range(10):
            self.store.upsert(obs(f"unique topic {i}", summary="x" * 800,
                                  concepts=[f"c{i}"]))
        block = build_context(self.store, "p", max_full=10, token_ceiling=500)
        self.assertLess(est_tokens(block), 900)  # ceiling + index margin

    def test_archived_never_injected(self):
        self.store.upsert(obs("dead knowledge", importance=Importance.ARCHIVE.value,
                              concepts=["dead"]))
        self.assertEqual(build_context(self.store, "p"), "")


if __name__ == "__main__":
    unittest.main()
