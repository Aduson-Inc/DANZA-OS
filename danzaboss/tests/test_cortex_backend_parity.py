"""Backend contract parity suite (C6).

One mixin defines the StorageBackend contract through port methods only;
every adapter runs the identical tests. SqliteBackend always runs. NeonBackend
runs when a live Postgres is reachable (DANZA_TEST_PG_DSN set + psycopg
installed) and skips cleanly otherwise — the spec's "identical test suite
green on both backends" acceptance (design §8, C6 row).
"""
import os
import tempfile
import unittest

import _bootstrap  # noqa
from danzaboss.cortex.observation import Observation, ObsType
from danzaboss.cortex.sqlite_backend import SqliteBackend

try:
    from danzaboss.cortex.neon_backend import NeonBackend, driver_available
except ImportError:  # adapter lands later in C6; harness ships first
    NeonBackend, driver_available = None, lambda: False

_PG_DSN = os.environ.get("DANZA_TEST_PG_DSN", "")


def obs(title, summary="s", typ=ObsType.DECISION.value, project="p", **kw):
    return Observation(title=title, summary=summary, type=typ,
                       project=project, **kw)


class BackendContractMixin:
    """The StorageBackend contract. Subclasses provide make_backend()."""

    def make_backend(self):
        raise NotImplementedError

    def setUp(self):
        self.be = self.make_backend()

    # -- put / get / delete / all ---------------------------------------------
    def test_put_get_roundtrip_preserves_all_fields(self):
        o = obs("Redis picked for session cache",
                summary="chose redis over memcached",
                tags=["cache", "redis"], concepts=["session", "cache"],
                files=["auth.py"], symbols=["SessionCache"],
                evidence=["auth.py:42"], when_relevant=["caching"],
                when_not_relevant=["frontend"], confidence=90,
                history=[{"ts": "2026-01-01T00:00:00+00:00", "event": "created"}])
        self.be.put(o)
        got = self.be.get(o.id)
        self.assertEqual(got.to_row(), o.to_row())
        self.assertIsInstance(got.confidence, int)
        self.assertIsInstance(got.layer, int)
        self.assertIsInstance(got.usage_count, int)

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.be.get("obs_does_not_exist"))

    def test_put_same_id_replaces_not_duplicates(self):
        o = obs("one truth")
        self.be.put(o)
        o.summary = "updated body"
        self.be.put(o)
        self.assertEqual(len(self.be.all("p")), 1)
        self.assertEqual(self.be.get(o.id).summary, "updated body")

    def test_delete_removes_row_and_search_index(self):
        o = obs("ephemeral fact", summary="deletable xyzzy")
        self.be.put(o)
        self.be.delete(o.id)
        self.assertIsNone(self.be.get(o.id))
        self.assertEqual([r.id for r in self.be.search("xyzzy")], [])

    def test_all_filters_by_project(self):
        self.be.put(obs("a", project="p1"))
        self.be.put(obs("b", project="p2"))
        self.assertEqual({o.project for o in self.be.all("p1")}, {"p1"})
        self.assertEqual(len(self.be.all()), 2)

    def test_unicode_roundtrip(self):
        o = obs("café schéma 中文", summary="naïve résumé — 実装 ✓",
                tags=["über"], concepts=["日本語"])
        self.be.put(o)
        got = self.be.get(o.id)
        self.assertEqual(got.title, "café schéma 中文")
        self.assertEqual(got.tags, ["über"])

    # -- search -----------------------------------------------------------------
    def test_search_matches_title_and_summary_terms(self):
        self.be.put(obs("Redis cache layer", summary="redis backs the cache"))
        self.be.put(obs("Unrelated build note", summary="webpack config"))
        hits = [o.title for o in self.be.search("redis")]
        self.assertEqual(hits, ["Redis cache layer"])

    def test_search_ranks_multi_term_match_first(self):
        strong = obs("Redis cache layer", summary="redis is the cache")
        weak = obs("Deploy notes", summary="redis mentioned once")
        self.be.put(strong)
        self.be.put(weak)
        hits = [o.id for o in self.be.search("redis cache")]
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0], strong.id)

    def test_search_respects_project_and_limit(self):
        for i in range(5):
            self.be.put(obs(f"redis note {i}", project="p1"))
        self.be.put(obs("redis elsewhere", project="p2"))
        hits = self.be.search("redis", project="p1", limit=3)
        self.assertEqual(len(hits), 3)
        self.assertTrue(all(o.project == "p1" for o in hits))

    def test_search_query_syntax_cannot_inject(self):
        self.be.put(obs("safe row", summary="plain content"))
        for hostile in ('"unclosed', 'a OR b NEAR(', "x*; DROP TABLE observations; --",
                        "NOT AND OR", "()^"):
            try:
                self.be.search(hostile)
            except Exception as e:  # noqa: BLE001 — the assertion IS "no raise"
                self.fail(f"search({hostile!r}) raised {e!r}")
        self.assertIsNotNone(self.be.get(self.be.all()[0].id))

    def test_search_empty_query_returns_nothing(self):
        self.be.put(obs("something"))
        self.assertEqual(self.be.search(""), [])
        self.assertEqual(self.be.search("   ...   "), [])

    # -- usage log ---------------------------------------------------------------
    def test_log_use_and_usage_log_roundtrip_newest_first(self):
        o = obs("used often")
        self.be.put(o)
        self.be.log_use(o.id, "2026-01-01T00:00:00+00:00", "get")
        self.be.log_use(o.id, "2026-01-02T00:00:00+00:00", "retrieve")
        log = self.be.usage_log()
        self.assertEqual([(r["obs_id"], r["source"]) for r in log],
                         [(o.id, "retrieve"), (o.id, "get")])

    def test_usage_log_respects_limit(self):
        o = obs("popular")
        self.be.put(o)
        for i in range(5):
            self.be.log_use(o.id, f"2026-01-0{i + 1}T00:00:00+00:00")
        self.assertEqual(len(self.be.usage_log(limit=2)), 2)


class TestSqliteContract(BackendContractMixin, unittest.TestCase):
    def make_backend(self):
        return SqliteBackend(":memory:")


class TestSqliteConcurrencyPragmas(unittest.TestCase):
    """C6 hardening: file-backed stores must run WAL with a busy timeout so
    concurrent sessions on the shared global DB queue instead of erroring."""

    def test_file_store_uses_wal_and_busy_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            be = SqliteBackend(os.path.join(tmp, "cortex.db"))
            mode = be.conn.execute("PRAGMA journal_mode").fetchone()[0]
            timeout = be.conn.execute("PRAGMA busy_timeout").fetchone()[0]
            self.assertEqual(mode.lower(), "wal")
            self.assertGreaterEqual(timeout, 5000)
            be.conn.close()

    def test_two_connections_share_one_file_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cortex.db")
            writer, reader = SqliteBackend(path), SqliteBackend(path)
            o = obs("visible across connections")
            writer.put(o)
            self.assertIsNotNone(reader.get(o.id))
            writer.conn.close()
            reader.conn.close()


@unittest.skipUnless(NeonBackend and _PG_DSN and driver_available(),
                     "needs DANZA_TEST_PG_DSN + psycopg")
class TestNeonContract(BackendContractMixin, unittest.TestCase):
    def make_backend(self):
        be = NeonBackend(_PG_DSN)
        with be.conn.cursor() as cur:  # each test starts from an empty store
            cur.execute("TRUNCATE observations, usage_log")
        be.conn.commit()
        return be


if __name__ == "__main__":
    unittest.main()
