import unittest
import _bootstrap  # noqa
from danzaboss.cortex.app_profile import (
    AppProfile, FeatureProfile, ScanFacts, learn_profile, diff_profiles)


class TestAppProfile(unittest.TestCase):
    def test_learn_is_app_agnostic(self):
        # a TypeScript+Neon app...
        scan = ScanFacts(languages=["TypeScript"], frameworks=["Next.js"],
                         databases=["Neon/Postgres"], entry_points=["app/page.tsx"],
                         detected_features=[{"name": "auth", "files": ["auth.ts"]},
                                            {"name": "mixer", "files": ["mixer.tsx"]}])
        p = learn_profile("noisemaker", scan, domain="audio tool",
                          goals=["ship v1"], big_feature_names={"mixer"})
        self.assertEqual(p.languages, ["TypeScript"])
        self.assertTrue(any(f.name == "mixer" and f.is_big for f in p.features))
        self.assertFalse(any(f.name == "auth" and f.is_big for f in p.features))

    def test_same_learner_works_for_python_app(self):
        scan = ScanFacts(languages=["Python"], frameworks=["FastAPI"],
                         databases=["SQLite"], detected_features=[{"name": "api"}])
        p = learn_profile("other-app", scan, domain="CRM")
        self.assertEqual(p.languages, ["Python"])
        self.assertEqual(p.domain, "CRM")  # no app-specific code path

    def test_research_topic_built_from_profile(self):
        scan = ScanFacts(detected_features=[{"name": "mixer", "description": "multi-track"}])
        p = learn_profile("noisemaker", scan, domain="audio tool")
        topic = p.research_topic_for("mixer")
        self.assertIn("mixer", topic)
        self.assertIn("audio tool", topic)   # domain drives the query, generically

    def test_big_features_filter(self):
        scan = ScanFacts(detected_features=[{"name": "a"}, {"name": "b"}])
        p = learn_profile("x", scan, big_feature_names={"b"})
        self.assertEqual([f.name for f in p.big_features()], ["b"])

    def test_confidence_scales_with_signal(self):
        low = learn_profile("x", ScanFacts())
        high = learn_profile("x", ScanFacts(languages=["Go"], frameworks=["gin"],
                             databases=["pg"], entry_points=["main.go"],
                             detected_features=[{"name": "f"}]))
        self.assertGreater(high.confidence, low.confidence)

    def test_diff_detects_migration(self):
        old = learn_profile("x", ScanFacts(languages=["Python"], databases=["SQLite"]))
        new = learn_profile("x", ScanFacts(languages=["TypeScript"], databases=["Neon"]))
        d = diff_profiles(old, new)
        self.assertIn("TypeScript", d["languages_added"])
        self.assertTrue(d["databases_changed"])


if __name__ == "__main__":
    unittest.main()
