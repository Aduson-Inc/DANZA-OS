"""C6 federation: L2/L3 project store + L4/L5 global store.

Covers the two user-approved spec §16 stances:
  Q2 — project truth wins: a global near-duplicate is shadowed everywhere.
  Q4 — writes route by layer; shared-store safety is WAL/transactions +
       last-writer-wins (no locking layer), so routing must be exact.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import _bootstrap  # noqa
from danzaboss.cortex import commands, factory
from danzaboss.cortex.federate import FederatedStore, GLOBAL_LAYER
from danzaboss.cortex.observation import Observation, ObsType
from danzaboss.cortex.ports import Query
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore


def obs(title, layer=2, typ=ObsType.DECISION.value, project="p", **kw):
    return Observation(title=title, summary=kw.pop("summary", "s"),
                       type=typ, project=project, layer=layer, **kw)


def fed_pair():
    project = ObservationStore(SqliteBackend(":memory:"))
    global_ = ObservationStore(SqliteBackend(":memory:"))
    return FederatedStore(project, global_), project, global_


class TestFactory(unittest.TestCase):
    def test_global_db_env_override(self):
        with mock.patch.dict(os.environ, {factory.GLOBAL_DB_ENV: "/x/g.db"}):
            self.assertEqual(factory.global_db_path(), "/x/g.db")

    def test_default_global_path_is_under_home(self):
        with mock.patch.dict(os.environ, {factory.GLOBAL_DB_ENV: ""}):
            self.assertEqual(
                factory.global_db_path(),
                os.path.join(os.path.expanduser("~"), ".danza", "cortex",
                             "global.db"))

    def test_dsn_env_selects_neon_adapter(self):
        fake = mock.MagicMock()
        with mock.patch.dict(os.environ,
                             {factory.GLOBAL_DSN_ENV: "postgresql://x"}), \
             mock.patch("danzaboss.cortex.neon_backend.NeonBackend",
                        return_value=fake) as ctor:
            store = factory.open_global_store()
        ctor.assert_called_once_with("postgresql://x")
        self.assertIs(store.backend, fake)

    def test_open_store_is_federated(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ,
                             {factory.GLOBAL_DB_ENV: os.path.join(tmp, "g.db"),
                              factory.GLOBAL_DSN_ENV: ""}):
            self.assertIsInstance(factory.open_store(tmp), FederatedStore)


class TestFederatedRouting(unittest.TestCase):
    def setUp(self):
        self.fed, self.project, self.global_ = fed_pair()

    def test_upsert_routes_by_layer(self):
        self.fed.upsert(obs("project fact", layer=2))
        self.fed.upsert(obs("personal preference", layer=4))
        self.fed.upsert(obs("reusable pattern", layer=5))
        self.assertEqual(len(self.project.backend.all()), 1)
        self.assertEqual(len(self.global_.backend.all()), 2)

    def test_all_merges_project_and_global(self):
        self.fed.upsert(obs("project fact", layer=2, project="repo1"))
        self.fed.upsert(obs("reusable pattern", layer=5,
                            typ=ObsType.CONVENTION.value))
        titles = {o.title for o in self.fed.backend.all("repo1")}
        self.assertEqual(titles, {"project fact", "reusable pattern"})

    def test_sub_global_rows_in_global_store_are_ignored(self):
        stray = obs("should not leak", layer=2, project="other-repo")
        self.global_.backend.put(stray)  # misuse: an L2 row in the global DB
        self.assertEqual(self.fed.backend.all("repo1"), [])

    def test_get_and_record_use_fall_through_to_global(self):
        g = self.fed.upsert(obs("reusable pattern", layer=5))
        self.assertIsNotNone(self.fed.get(g.id))
        self.fed.record_use(g.id, source="test")
        self.assertEqual(self.global_.backend.get(g.id).usage_count, 1)
        self.assertEqual(self.global_.backend.usage_log()[0]["obs_id"], g.id)
        self.assertEqual(self.project.backend.usage_log(), [])

    def test_age_aggregates_both_stores(self):
        self.fed.upsert(obs("a", layer=2))
        self.fed.upsert(obs("b", layer=5))
        result = self.fed.age()
        self.assertEqual(result["kept"], 2)
        self.assertEqual(result["archived"], 0)

    def test_usage_log_merges_newest_first(self):
        p = self.fed.upsert(obs("local", layer=2))
        g = self.fed.upsert(obs("global", layer=5))
        self.fed.backend.log_use(p.id, "2026-01-01T00:00:00+00:00")
        self.fed.backend.log_use(g.id, "2026-01-02T00:00:00+00:00")
        log = self.fed.backend.usage_log()
        self.assertEqual([r["obs_id"] for r in log], [g.id, p.id])


class TestL2Precedence(unittest.TestCase):
    """Spec §16 Q2 (approved): project truth wins over cross-project advice."""

    def setUp(self):
        self.fed, self.project, self.global_ = fed_pair()
        self.local = self.fed.upsert(
            obs("Redis chosen for cache layer", layer=2,
                summary="this repo uses redis", concepts=["redis", "cache"]))
        self.shadowed = self.fed.upsert(
            obs("Redis chosen for caching layers", layer=5,
                summary="general advice", concepts=["redis", "cache"]))
        self.distinct = self.fed.upsert(
            obs("Prefer JWT rotation helper", layer=5,
                typ=ObsType.CONVENTION.value,
                summary="reusable auth pattern", concepts=["jwt", "auth"]))

    def test_near_duplicate_global_is_shadowed_in_all(self):
        ids = {o.id for o in self.fed.backend.all("p")}
        self.assertIn(self.local.id, ids)
        self.assertIn(self.distinct.id, ids)
        self.assertNotIn(self.shadowed.id, ids)

    def test_near_duplicate_global_is_shadowed_in_search(self):
        hits = {o.id for o in self.fed.backend.search("redis cache")}
        self.assertEqual(hits, {self.local.id})

    def test_distinct_global_knowledge_surfaces_in_query(self):
        scored = self.fed.query(Query(text="jwt auth rotation", project="p"))
        self.assertIn(self.distinct.id, [s.observation.id for s in scored])

    def test_search_dedupes_and_respects_limit(self):
        hits = self.fed.backend.search("redis cache jwt", limit=2)
        self.assertLessEqual(len(hits), 2)
        self.assertEqual(len({o.id for o in hits}), len(hits))


class TestCommandsFederation(unittest.TestCase):
    """Integration through the real CLI entry points."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.global_db = os.path.join(self.root, "global-home", "global.db")
        patcher = mock.patch.dict(os.environ,
                                  {factory.GLOBAL_DB_ENV: self.global_db,
                                   factory.GLOBAL_DSN_ENV: ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_cmd(self, argv, payload=None):
        out = io.StringIO()
        stdin = io.StringIO(json.dumps(payload) if payload is not None else "")
        with contextlib.redirect_stdout(out):
            rc = commands.main(argv, root=self.root, stdin=stdin)
        return rc, out.getvalue()

    def test_observe_routes_layer5_to_global_store(self):
        rc, out = self.run_cmd(["observe"], payload={
            "title": "Reusable retry-with-backoff helper",
            "summary": "battle-tested across projects",
            "type": ObsType.CONVENTION.value, "layer": 5})
        self.assertEqual(rc, 0)
        oid = json.loads(out)["stored"][0]
        self.assertIsNotNone(SqliteBackend(self.global_db).get(oid))
        self.assertEqual(
            SqliteBackend(factory.db_path(self.root)).all(), [])

    def test_search_and_get_reach_global_observations(self):
        rc, out = self.run_cmd(["observe"], payload={
            "title": "Reusable retry-with-backoff helper",
            "summary": "battle-tested across projects",
            "type": ObsType.CONVENTION.value, "layer": 5})
        oid = json.loads(out)["stored"][0]
        rc, out = self.run_cmd(["search", "retry", "backoff"])
        self.assertEqual(rc, 0)
        self.assertIn(oid, [r["id"] for r in json.loads(out)])
        rc, out = self.run_cmd(["get", oid])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)[0]["id"], oid)


class TestReviewFixes(unittest.TestCase):
    """Regressions from the C6 code review (residency routing, shadowing of
    superseded rows, search starvation, cross-store supersession)."""

    def setUp(self):
        self.fed, self.project, self.global_ = fed_pair()

    def test_put_updates_row_where_it_lives_not_by_layer(self):
        legacy = obs("legacy global-layer row", layer=4)
        self.project.backend.put(legacy)  # pre-C6 rows all lived in the repo DB
        self.fed.record_use(legacy.id, source="get")
        self.assertEqual(self.project.backend.get(legacy.id).usage_count, 1)
        self.assertIsNone(self.global_.backend.get(legacy.id))  # no fork

    def test_superseded_project_row_does_not_shadow_global(self):
        dead = self.fed.upsert(obs("Redis chosen for cache", layer=2,
                                   concepts=["redis", "cache"]))
        dead.superseded_by = "obs_x"
        self.project.backend.put(dead)
        live = self.fed.upsert(obs("Redis chosen for caching", layer=5,
                                   concepts=["redis", "cache"]))
        self.assertIn(live.id, {o.id for o in self.fed.backend.all("p")})

    def test_search_keeps_global_hit_when_local_fills_limit(self):
        for i in range(6):  # backend.put: distinct rows, no near-dup merging
            self.project.backend.put(obs(f"retry note number {i} entry",
                                         layer=2,
                                         typ=ObsType.IMPL_DETAIL.value))
        g = self.fed.upsert(obs("Reusable retry backoff helper", layer=5,
                                typ=ObsType.CONVENTION.value))
        hits = self.fed.backend.search("retry", limit=6)
        self.assertEqual(len(hits), 6)
        self.assertIn(g.id, {o.id for o in hits})

    def test_supersedes_across_stores_marks_old_row(self):
        old = self.fed.upsert(obs("Old retry pattern", layer=2))
        new = self.fed.upsert(obs("Improved retry pattern", layer=5,
                                  supersedes=old.id))
        self.assertEqual(self.project.backend.get(old.id).superseded_by,
                         new.id)
        ids = {o.id for o in self.fed.backend.all("p")}
        self.assertIn(new.id, ids)


if __name__ == "__main__":
    unittest.main()
