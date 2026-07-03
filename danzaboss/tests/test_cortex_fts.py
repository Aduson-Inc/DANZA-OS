import unittest
import _bootstrap  # noqa
from danzaboss.cortex.observation import Observation, ObsType
from danzaboss.cortex.sqlite_backend import SqliteBackend


def obs(title, summary, project="p", **kw):
    return Observation(title=title, summary=summary,
                       type=ObsType.DECISION.value, project=project, **kw)


class TestFtsSearch(unittest.TestCase):
    def setUp(self):
        self.be = SqliteBackend(":memory:")
        self.be.put(obs("Redis chosen for JWT refresh cache",
                        "Redis holds refresh tokens to prevent races",
                        concepts=["redis", "jwt"]))
        self.be.put(obs("Postgres schema for billing",
                        "billing tables normalized to 3NF",
                        concepts=["postgres", "billing"]))

    def test_search_ranks_matching_observation_first(self):
        res = self.be.search("redis jwt")
        self.assertGreaterEqual(len(res), 1)
        self.assertIn("Redis", res[0].title)

    def test_search_scopes_by_project(self):
        self.be.put(obs("Redis elsewhere", "other repo", project="other",
                        concepts=["redis"]))
        res = self.be.search("redis", project="p")
        self.assertTrue(all(o.project == "p" for o in res))

    def test_search_handles_fts_special_chars(self):
        # quotes/operators in user text must not raise fts5 syntax errors
        res = self.be.search('redis AND "jwt" OR (cache*')
        self.assertIsInstance(res, list)

    def test_blank_query_returns_empty(self):
        self.assertEqual(self.be.search("   "), [])

    def test_delete_removes_from_index(self):
        target = self.be.search("billing")[0]
        self.be.delete(target.id)
        self.assertEqual(self.be.search("billing"), [])

    def test_put_same_id_does_not_duplicate_index(self):
        o = self.be.search("redis")[0]
        o.summary = "updated summary about redis caching"
        self.be.put(o)
        self.assertEqual(len(self.be.search("redis")), 1)


if __name__ == "__main__":
    unittest.main()
