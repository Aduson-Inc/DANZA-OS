import unittest
from unittest.mock import patch
import _bootstrap  # noqa
from danzaboss.cortex.assemble import Package, PackageItem, assemble
from danzaboss.cortex.intent import detect
from danzaboss.cortex.observation import Observation, Importance
from danzaboss.cortex.quality import (
    PackageBundle,
    QualityReport,
    build_package,
    compare_expansion,
    expansion_pressure,
    score_package,
    select_adaptive_package,
)
from danzaboss.cortex.retrieve import RetrievalResult, RetrievedItem
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


def adaptive_bundle(*, used=85, dropped_relevant=True,
                    missing_category=False, replanned=False):
    intent = detect("build the login endpoint")
    included = RetrievedItem(
        observation=obs("Login endpoint implementation", "build login handler",
                        typ="impl_detail", concepts=["login"]),
        fused=1.0, final=1.0)
    if missing_category:
        dropped_type = "decision"
        dropped_title = "Login architecture decision"
        dropped_summary = "session layout"
    else:
        dropped_type = "impl_detail"
        dropped_title = ("Dropped login implementation" if dropped_relevant
                         else "Dropped orchid trivia")
        dropped_summary = ("login handler detail" if dropped_relevant
                           else "botanical notes")
    dropped = RetrievedItem(
        observation=obs(dropped_title, dropped_summary, typ=dropped_type),
        fused=0.9, final=0.9)
    pkg = Package(
        intent=intent.name, budget=100, used=used,
        allocation={"code": 100},
        items=[PackageItem(included.observation, "code", "login", used,
                           final=included.final)],
        dropped=[{"id": dropped.observation.id,
                  "title": dropped.observation.title,
                  "reason": "no budget left"}],
    )
    return PackageBundle(
        prompt="build the login endpoint", intent=intent,
        retrieval=RetrievalResult(items=[included, dropped]), package=pkg,
        report=score_package(pkg, intent), replanned=replanned)


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


class TestAdaptiveExpansion(unittest.TestCase):
    def test_real_retrieval_and_assembly_expand_a_qualified_package(self):
        store = ObservationStore(SqliteBackend(":memory:"))
        names = "alpha beta gamma delta epsilon zeta eta theta iota kappa".split()
        for name in names:
            store.upsert(obs(
                f"{name} login", f"build login endpoint {name} behavior",
                typ="impl_detail", concepts=["login", name],
                reasoning=f"keep {name} behavior deterministic and validated"))
        base = build_package(
            store, "build the login endpoint", "p", budget=100)
        selected = select_adaptive_package(
            base, base_budget=100, ceiling=200)
        self.assertGreaterEqual(base.package.used, 85)
        self.assertIn("dropped_relevant",
                      selected.evidence["pressure_reasons"])
        self.assertEqual(selected.evidence["selected_mode"], "expanded")
        self.assertEqual(selected.bundle.package.budget, 200)
        self.assertLessEqual(selected.bundle.package.used, 200)

    def test_irrelevant_dropped_candidate_is_not_pressure(self):
        reasons = expansion_pressure(
            adaptive_bundle(dropped_relevant=False, missing_category=False))
        self.assertNotIn("dropped_relevant", reasons)
        self.assertNotIn("missing_required_category", reasons)

    def test_missing_required_category_with_candidate_is_pressure(self):
        reasons = expansion_pressure(
            adaptive_bundle(dropped_relevant=False, missing_category=True))
        self.assertIn("missing_required_category", reasons)

    def test_below_85_percent_does_not_construct_candidate(self):
        base = adaptive_bundle(used=84, dropped_relevant=True)
        with patch("danzaboss.cortex.quality.assemble", wraps=assemble) as mocked:
            selected = select_adaptive_package(base, base_budget=100, ceiling=200)
        self.assertEqual(mocked.call_count, 0)
        self.assertEqual(selected.evidence["acceptance_reason"],
                         "below_85_percent")
        self.assertFalse(selected.evidence["expansion_qualified"])

    def test_saturated_without_pressure_does_not_construct_candidate(self):
        base = adaptive_bundle(used=85, dropped_relevant=False)
        with patch("danzaboss.cortex.quality.assemble", wraps=assemble) as mocked:
            selected = select_adaptive_package(base, base_budget=100, ceiling=200)
        self.assertEqual(mocked.call_count, 0)
        self.assertEqual(selected.evidence["acceptance_reason"],
                         "no_qualified_pressure")

    def test_qualified_replanned_base_constructs_one_candidate_only(self):
        base = adaptive_bundle(used=85, dropped_relevant=True, replanned=True)
        with patch("danzaboss.cortex.quality.assemble", wraps=assemble) as mocked:
            selected = select_adaptive_package(base, base_budget=100, ceiling=200)
        self.assertEqual(mocked.call_count, 1)
        self.assertIn("dropped_relevant",
                      selected.evidence["pressure_reasons"])
        self.assertTrue(selected.evidence["expansion_attempted"])
        self.assertTrue(selected.evidence["expansion_accepted"])
        self.assertEqual(selected.evidence["selected_mode"], "expanded")
        self.assertEqual(selected.evidence["selected_budget"], 200)
        self.assertLessEqual(selected.bundle.package.used, 200)
        self.assertTrue(base.replanned)

    def test_lower_relevance_is_rejected(self):
        base = QualityReport(1.0, 0.333, 1.0, 1.0, 0.8, True)
        candidate = QualityReport(0.5, 0.667, 1.0, 1.0, 0.7, True)
        self.assertEqual(compare_expansion(base, candidate, ["new"]),
                         (False, "relevance_decreased"))

    def test_rejected_candidate_keeps_base_and_records_comparison(self):
        base = adaptive_bundle(used=85, dropped_relevant=True)
        lower = QualityReport(0.0, 1.0, 1.0, 1.0, 0.6, True)
        with patch("danzaboss.cortex.quality.score_package",
                   return_value=lower):
            selected = select_adaptive_package(
                base, base_budget=100, ceiling=200)
        self.assertIs(selected.bundle, base)
        self.assertEqual(selected.evidence["selected_mode"], "base")
        self.assertEqual(selected.evidence["acceptance_reason"],
                         "relevance_decreased")
        self.assertEqual(selected.evidence["candidate"]["relevance"], 0.0)

    def test_equal_relevance_and_improved_coverage_is_accepted(self):
        base = QualityReport(1.0, 0.333, 1.0, 1.0, 0.8, True)
        candidate = QualityReport(1.0, 0.667, 1.0, 1.0, 0.9, True)
        self.assertEqual(compare_expansion(base, candidate, []),
                         (True, "coverage_improved"))

    def test_new_top_five_item_is_accepted_without_coverage_gain(self):
        report = QualityReport(1.0, 0.667, 1.0, 1.0, 0.9, True)
        self.assertEqual(compare_expansion(report, report, ["new"]),
                         (True, "high_rank_context_admitted"))

    def test_no_accepted_improvement_is_rejected(self):
        report = QualityReport(1.0, 0.667, 1.0, 1.0, 0.9, True)
        self.assertEqual(compare_expansion(report, report, []),
                         (False, "no_accepted_improvement"))

    def test_unchanged_candidate_keeps_base(self):
        base = adaptive_bundle(used=85, dropped_relevant=True)
        with patch("danzaboss.cortex.quality.assemble",
                   return_value=base.package), patch(
                       "danzaboss.cortex.quality.score_package",
                       return_value=base.report):
            selected = select_adaptive_package(
                base, base_budget=100, ceiling=200)
        self.assertIs(selected.bundle, base)
        self.assertEqual(selected.evidence["acceptance_reason"],
                         "no_accepted_improvement")


if __name__ == "__main__":
    unittest.main()
