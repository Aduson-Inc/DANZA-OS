import unittest
import _bootstrap  # noqa
from danzaboss.cortex.assemble import assemble
from danzaboss.cortex.intent import detect
from danzaboss.cortex.observation import Observation, Importance
from danzaboss.cortex.quality import build_package, score_package
from danzaboss.cortex.retrieve import RetrievedItem
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore


def obs(title, summary, typ="decision", project="p", **kw):
    return Observation(title=title, summary=summary, type=typ, project=project, **kw)


def seeded_store():
    store = ObservationStore(SqliteBackend(":memory:"))
    store.upsert(obs("JWT refresh race fixed", "auth middleware race condition",
                     typ="bug_fix", concepts=["jwt", "auth"],
                     when_relevant=["fix_bug"], importance=Importance.HIGH.value,
                     confidence=95, reasoning="cross-tab refresh duplicated"))
    store.upsert(obs("Fail-closed auth convention", "validation raises on violation",
                     typ="convention", concepts=["auth", "failclosed"],
                     importance=Importance.CRITICAL.value, confidence=95))
    store.upsert(obs("Chose SQLite for local store", "zero-config local-first",
                     typ="decision", concepts=["sqlite", "storage"]))
    store.upsert(obs("Dashboard caching lesson", "cache the stats query",
                     typ="lesson", concepts=["dashboard", "cache"]))
    return store


class TestScorePackage(unittest.TestCase):
    def test_empty_package_fails(self):
        report = score_package(assemble([], "fix_bug", 500), detect("fix the bug"))
        self.assertFalse(report.passed)
        self.assertEqual(report.overall, 0.0)

    def test_relevant_package_passes(self):
        intent = detect("fix the auth bug")
        o = obs("Auth bug fixed", "the auth race bug is gone", typ="bug_fix",
                concepts=["auth"])
        items = [RetrievedItem(observation=o, fused=1.0, final=1.0, reasons=["r"])]
        pkg = assemble(items, intent.name, 300)
        report = score_package(pkg, intent)
        self.assertTrue(report.passed)
        self.assertGreater(report.relevance, 0.9)

    def test_redundancy_penalizes_near_duplicates(self):
        intent = detect("fix the auth bug")
        a = obs("Auth bug fixed in middleware", "the auth race bug is gone now",
                typ="bug_fix", concepts=["auth"])
        b = obs("Auth bug fixed in middleware again",
                "the auth race bug is gone now", typ="bug_fix", concepts=["auth"])
        dup_items = [RetrievedItem(observation=x, fused=1.0, final=1.0)
                     for x in (a, b)]
        dup = score_package(assemble(dup_items, intent.name, 600), intent)
        distinct = obs("Postgres chosen for sessions",
                       "shared team memory needs a server database",
                       typ="decision", concepts=["postgres"])
        mixed_items = [RetrievedItem(observation=x, fused=1.0, final=1.0)
                       for x in (a, distinct)]
        mixed = score_package(assemble(mixed_items, intent.name, 600), intent)
        self.assertGreater(mixed.redundancy, dup.redundancy)


class TestBuildPackage(unittest.TestCase):
    def test_end_to_end_bundle(self):
        bundle = build_package(seeded_store(), "fix the jwt auth bug", "p",
                               budget=800)
        self.assertEqual(bundle.intent.name, "fix_bug")
        self.assertTrue(bundle.package.items)
        titles = [i.observation.title for i in bundle.package.items]
        self.assertIn("JWT refresh race fixed", titles)
        for item in bundle.package.items:       # C3 acceptance: reasons everywhere
            self.assertTrue(item.reasons)

    def test_intent_override_forces_profile(self):
        bundle = build_package(seeded_store(), "look at auth", "p",
                               intent_override="security")
        self.assertEqual(bundle.intent.name, "security")
        self.assertTrue(any("forced" in m for m in bundle.intent.matched))

    def test_empty_store_replans_once_and_ships(self):
        store = ObservationStore(SqliteBackend(":memory:"))
        bundle = build_package(store, "fix the bug", "p")
        self.assertTrue(bundle.replanned)       # exactly one re-plan, then ship
        self.assertFalse(bundle.report.passed)
        self.assertEqual(bundle.package.items, [])

    def test_replan_is_recorded_in_notes(self):
        store = ObservationStore(SqliteBackend(":memory:"))
        store.upsert(obs("Unrelated trivia", "nothing to do with anything",
                         typ="lesson", concepts=["trivia"], confidence=20,
                         importance=Importance.LOW.value))
        bundle = build_package(store, "fix the jwt auth bug", "p", budget=400)
        if bundle.replanned:
            self.assertTrue(any("re-planned once" in n for n in bundle.notes))

    def test_types_filter_flows_through(self):
        bundle = build_package(seeded_store(), "auth", "p", types=["convention"])
        for item in bundle.package.items:
            self.assertEqual(item.observation.type, "convention")


if __name__ == "__main__":
    unittest.main()
