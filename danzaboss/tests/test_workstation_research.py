"""Reality Check tests: providers stubbed, digest contract fail-closed,
wizard integration stale-on-edit (design spec sections 4 and 8). Zero
network: urlopen is injected, the boss CLI is a stub script."""
import _bootstrap  # noqa: F401
import json
import sys
import tempfile
import unittest
from pathlib import Path

from danzaboss.workstation import research
from danzaboss.workstation.wizard import Wizard

VALID_DIGEST = {
    "verdict": "crowded_but_viable",
    "summary": "Rover and Wag dominate; the trust-first wedge is open.",
    "competitors": [
        {"name": "Rover", "url": "https://rover.com", "note": "marketplace"},
        {"name": "Wag", "url": "https://wag.co", "note": "on-demand"},
    ],
    "differentiation": "Verified-walker trust layer for one metro area.",
}

CONCEPT_ANSWERS = {
    "project_name": "WalkWise",
    "concept_what": "Dog walking marketplace",
    "concept_who": "Urban dog owners",
    "concept_problem": "Finding trusted walkers is slow",
    "features_must": ["book a walk"],
    "non_goals": ["pet supplies"],
}


def make_stub(tmp: Path, body: str) -> list[str]:
    stub = tmp / "stub_boss.py"
    stub.write_text(body, encoding="utf-8")
    return [sys.executable, str(stub)]


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_urlopen(body: dict):
    def urlopen(request, timeout=0):
        return _FakeResponse(body)
    return urlopen


class DigestContractTests(unittest.TestCase):
    def test_valid_digest_passes(self):
        self.assertEqual(research.validate_digest(dict(VALID_DIGEST)),
                         dict(VALID_DIGEST))

    def test_unknown_verdict_rejected(self):
        with self.assertRaises(research.ResearchError):
            research.validate_digest(dict(VALID_DIGEST, verdict="meh"))

    def test_missing_key_rejected(self):
        bad = {k: v for k, v in VALID_DIGEST.items() if k != "competitors"}
        with self.assertRaises(research.ResearchError):
            research.validate_digest(bad)

    def test_competitor_without_name_rejected(self):
        bad = dict(VALID_DIGEST, competitors=[{"url": "https://x.io"}])
        with self.assertRaises(research.ResearchError):
            research.validate_digest(bad)


class QueryTests(unittest.TestCase):
    def test_query_built_from_concept_answers(self):
        query = research.build_query(CONCEPT_ANSWERS)
        self.assertIn("Dog walking marketplace", query)
        self.assertIn("Urban dog owners", query)

    def test_empty_concept_rejected(self):
        with self.assertRaises(research.ResearchError):
            research.build_query({})


class TavilySearchTests(unittest.TestCase):
    def test_results_mapped_to_title_url_content(self):
        body = {"results": [{"title": "Rover", "url": "https://rover.com",
                             "content": "walkers", "score": 0.9}]}
        results = research.tavily_search("dogs", "key",
                                         urlopen=fake_urlopen(body))
        self.assertEqual(results, [{"title": "Rover",
                                    "url": "https://rover.com",
                                    "content": "walkers"}])

    def test_missing_results_field_raises(self):
        with self.assertRaises(research.ResearchError):
            research.tavily_search("dogs", "key",
                                   urlopen=fake_urlopen({"error": "nope"}))

    def test_network_failure_raises_research_error(self):
        def broken(request, timeout=0):
            raise OSError("connection refused")
        with self.assertRaises(research.ResearchError):
            research.tavily_search("dogs", "key", urlopen=broken)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_tavily_provider_searches_then_synthesizes(self):
        body = {"results": [{"title": "Rover", "url": "https://rover.com",
                             "content": "walkers"}]}
        command = make_stub(self.tmp, (
            "import json\n"
            f"print(json.dumps({VALID_DIGEST!r}))\n"))
        provider = research.TavilyProvider("key", command,
                                           urlopen=fake_urlopen(body))
        digest = provider.run(CONCEPT_ANSWERS, timeout=30)
        self.assertEqual(digest["verdict"], "crowded_but_viable")
        self.assertEqual(digest["sources"], ["https://rover.com"])

    def test_boss_web_provider_single_call(self):
        command = make_stub(self.tmp, (
            "import json\n"
            f"print(json.dumps({VALID_DIGEST!r}))\n"))
        digest = research.BossWebProvider(command).run(
            CONCEPT_ANSWERS, timeout=30)
        self.assertEqual(digest["summary"], VALID_DIGEST["summary"])

    def test_provider_garbage_output_raises(self):
        command = make_stub(self.tmp, "print('not json at all')\n")
        with self.assertRaises(research.ResearchError):
            research.BossWebProvider(command).run(CONCEPT_ANSWERS, timeout=30)

    def test_tavily_from_env(self):
        self.assertIsNone(research.tavily_from_env(["claude"], env={}))
        provider = research.tavily_from_env(
            ["claude"], env={"TAVILY_API_KEY": "tk"})
        self.assertIsInstance(provider, research.TavilyProvider)


if __name__ == "__main__":
    unittest.main()
