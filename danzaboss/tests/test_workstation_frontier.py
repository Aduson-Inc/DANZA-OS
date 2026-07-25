"""Frontier scout tests (plan 01 Task 11 / Decision 7): canonical-repo gate,
7-day throttle, Tavily research pass (mocked transport, zero network), the
key-free code-health pass, the proposal store's per-item revision fingerprint
(mirrors build.py additions / product_scope.py scope conflicts), and the
opportunistic `maybe_scout` orchestrator that must never raise or leak the
API key. TAVILY_API_KEY is never set live here — the no-key silent-skip path
is the actual behavior in this environment and is asserted directly."""
import _bootstrap  # noqa: F401
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from danzaboss.frontier import codehealth, scout, store, tavily


def _now(days_ago: int = 0) -> dt.datetime:
    return (dt.datetime.now(dt.timezone.utc)
            - dt.timedelta(days=days_ago))


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_urlopen(body: dict, *, captured: dict | None = None):
    def urlopen(request, timeout=0):
        if captured is not None:
            captured["data"] = request.data
            captured["headers"] = dict(request.header_items())
        return _FakeResponse(body)
    return urlopen


class TavilyClientTests(unittest.TestCase):
    def test_results_mapped(self):
        body = {"results": [{"title": "Agentic dev tools 2026",
                             "url": "https://example.com/a",
                             "content": "multi-agent orchestration trends"}]}
        results = tavily.tavily_search("q", "secret-key",
                                       urlopen=fake_urlopen(body))
        self.assertEqual(results, [{"title": "Agentic dev tools 2026",
                                    "url": "https://example.com/a",
                                    "content": "multi-agent orchestration "
                                               "trends"}])

    def test_key_travels_in_request_body_not_url(self):
        captured = {}
        body = {"results": []}
        tavily.tavily_search("q", "super-secret-key",
                             urlopen=fake_urlopen(body, captured=captured))
        self.assertIn(b"super-secret-key", captured["data"])
        self.assertNotIn("super-secret-key", tavily.TAVILY_URL)

    def test_missing_results_field_raises(self):
        with self.assertRaises(tavily.FrontierError):
            tavily.tavily_search("q", "key", urlopen=fake_urlopen({}))

    def test_network_failure_raises_without_leaking_key(self):
        def broken(request, timeout=0):
            raise OSError("connection refused")
        try:
            tavily.tavily_search("q", "top-secret", urlopen=broken)
            self.fail("expected FrontierError")
        except tavily.FrontierError as exc:
            self.assertNotIn("top-secret", str(exc))

    def test_research_pass_caps_results_and_builds_proposals(self):
        body = {"results": [
            {"title": f"Result {i}", "url": f"https://x.io/{i}",
             "content": "c"} for i in range(10)]}
        items = tavily.research_pass("key", urlopen=fake_urlopen(body))
        self.assertLessEqual(len(items), tavily.MAX_RESULTS)
        self.assertTrue(all(item["source"] == "research" for item in items))
        self.assertEqual(items[0]["title"], "Result 0")


class CodeHealthTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_no_danzaboss_dir_is_empty(self):
        self.assertEqual(codehealth.code_health_pass(self.root), [])

    def test_oversized_module_is_flagged(self):
        pkg = self.root / "danzaboss"
        pkg.mkdir()
        big = pkg / "huge.py"
        big.write_text("\n".join(f"x = {i}" for i in range(900)),
                       encoding="utf-8")
        small = pkg / "tiny.py"
        small.write_text("x = 1\n", encoding="utf-8")
        proposals = codehealth.code_health_pass(self.root)
        titles = [p["title"] for p in proposals]
        self.assertTrue(any("huge.py" in t for t in titles))
        self.assertFalse(any("tiny.py" in t for t in titles))
        self.assertTrue(all(p["source"] == "code_health" for p in proposals))

    def test_test_files_are_excluded(self):
        pkg = self.root / "danzaboss" / "tests"
        pkg.mkdir(parents=True)
        big_test = pkg / "test_huge.py"
        big_test.write_text("\n".join(f"x = {i}" for i in range(900)),
                            encoding="utf-8")
        self.assertEqual(codehealth.code_health_pass(self.root), [])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_load_missing_is_never_ran_shape(self):
        state = store.load_state(self.root)
        self.assertIsNone(state["last_run"])
        self.assertEqual(state["proposals"], [])

    def test_corrupt_state_fails_closed(self):
        path = store.state_path(self.root)
        path.parent.mkdir(parents=True)
        path.write_text("not json", encoding="utf-8")
        with self.assertRaises(store.FrontierError):
            store.load_state(self.root)

    def test_add_proposals_assigns_ids_and_stamps_last_run(self):
        now = _now()
        added = store.add_proposals(
            self.root,
            [{"title": "Try stack X", "summary": "s", "source": "research"}],
            now=now)
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["id"], 1)
        self.assertEqual(added[0]["status"], "proposed")
        self.assertEqual(added[0]["revision"], 1)
        state = store.load_state(self.root)
        self.assertEqual(state["last_run"], now.isoformat(timespec="seconds"))
        self.assertEqual(len(state["proposals"]), 1)
        md = (self.root / store.PROPOSALS_MD_RELPATH).read_text()
        self.assertIn("Try stack X", md)

    def test_duplicate_titles_are_not_reproposed(self):
        store.add_proposals(self.root, [
            {"title": "Same idea", "summary": "a", "source": "research"}])
        added = store.add_proposals(self.root, [
            {"title": "same idea", "summary": "b", "source": "code_health"}])
        self.assertEqual(added, [])
        state = store.load_state(self.root)
        self.assertEqual(len(state["proposals"]), 1)

    def test_decide_approve_moves_to_backlog(self):
        store.add_proposals(self.root, [
            {"title": "Add template Y", "summary": "s", "source": "research"}])
        record = store.decide(self.root, 1, "approved", expected_revision=1)
        self.assertEqual(record["status"], "approved")
        self.assertEqual(record["revision"], 2)
        state = store.load_state(self.root)
        self.assertEqual(state["proposals"][0]["status"], "approved")
        md = (self.root / store.PROPOSALS_MD_RELPATH).read_text()
        self.assertIn("Backlog (approved)", md)
        self.assertIn("Add template Y", md)

    def test_decide_dismiss(self):
        store.add_proposals(self.root, [
            {"title": "Nope", "summary": "s", "source": "code_health"}])
        record = store.decide(self.root, 1, "dismissed", expected_revision=1)
        self.assertEqual(record["status"], "dismissed")

    def test_stale_revision_conflicts(self):
        store.add_proposals(self.root, [
            {"title": "One", "summary": "s", "source": "research"}])
        store.decide(self.root, 1, "approved", expected_revision=1)
        with self.assertRaises(store.FrontierRevisionConflict):
            store.decide(self.root, 1, "dismissed", expected_revision=1)

    def test_decide_unknown_id_raises(self):
        with self.assertRaises(store.FrontierError):
            store.decide(self.root, 99, "approved", expected_revision=1)

    def test_decide_invalid_decision_raises(self):
        store.add_proposals(self.root, [
            {"title": "One", "summary": "s", "source": "research"}])
        with self.assertRaises(store.FrontierError):
            store.decide(self.root, 1, "maybe", expected_revision=1)

    def test_never_ran_renders_cleanly(self):
        md = store.render_proposals_md(store.load_state(self.root))
        self.assertIn("never", md)

    def test_backlog_feature_maps_to_scope_contract(self):
        record = {"title": "Adopt template Q", "summary": "why it matters",
                  "source": "research"}
        feature = store.backlog_feature(record)
        self.assertEqual(set(feature), {"summary", "acceptance_criteria"})
        self.assertIn("Adopt template Q", feature["summary"])
        self.assertEqual(feature["acceptance_criteria"], ["why it matters"])

    def test_backlog_feature_neutralizes_sentence_breaks_in_titles(self):
        # a chatty Tavily title must still satisfy the product-scope
        # "one or two sentences" summary rule
        from danzaboss.workstation import product_scope
        record = {"title": "Wow! New tools? A deep dive. Really.",
                  "summary": "", "source": "research"}
        feature = store.backlog_feature(record)
        probe = {"version": product_scope.SCHEMA_VERSION, "revision": 1,
                 "approval": {"state": "draft", "approved_revision": None},
                 "features": [{"id": 1, "status": "pending", **feature}]}
        product_scope.validate_scope(probe)
        self.assertTrue(feature["acceptance_criteria"])


class CanonicalRepoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_unactivated_tree_is_canonical(self):
        self.assertTrue(scout.is_canonical_repo(self.root, env={}))

    def test_activated_tree_is_not_canonical(self):
        runtime = self.root / ".danza" / "runtime"
        runtime.mkdir(parents=True)
        (runtime / "team-state.json").write_text("{}", encoding="utf-8")
        self.assertFalse(scout.is_canonical_repo(self.root, env={}))

    def test_explicit_profile_override_wins(self):
        self.assertFalse(scout.is_canonical_repo(
            self.root, env={"DANZABOSS_PROFILE": "APP_BUILD"}))
        self.assertTrue(scout.is_canonical_repo(
            self.root, env={"DANZABOSS_PROFILE": "OS_DEV"}))

    def test_corrupt_profile_config_fails_closed(self):
        cfg = self.root / ".danza" / "runtime" / "profile.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("not json", encoding="utf-8")
        self.assertFalse(scout.is_canonical_repo(self.root, env={}))


class MaybeScoutTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_no_key_is_a_silent_skip(self):
        out = scout.maybe_scout(self.root, env={})
        self.assertEqual(out, {"ran": False, "reason": "no_key"})
        self.assertIsNone(store.load_state(self.root)["last_run"])

    def test_not_canonical_is_a_silent_skip_even_with_a_key(self):
        runtime = self.root / ".danza" / "runtime"
        runtime.mkdir(parents=True)
        (runtime / "team-state.json").write_text("{}", encoding="utf-8")
        out = scout.maybe_scout(self.root,
                                env={"TAVILY_API_KEY": "k"})
        self.assertEqual(out["reason"], "not_canonical")

    def test_not_due_is_a_silent_skip(self):
        store.add_proposals(self.root, [], now=_now(days_ago=1))
        out = scout.maybe_scout(self.root, env={"TAVILY_API_KEY": "k"})
        self.assertEqual(out["reason"], "not_due")

    def test_tavily_unreachable_skips_and_does_not_advance_last_run(self):
        def broken(request, timeout=0):
            raise OSError("no route to host")
        out = scout.maybe_scout(self.root, env={"TAVILY_API_KEY": "k"},
                                urlopen=broken)
        self.assertEqual(out["reason"], "tavily_unreachable")
        self.assertIsNone(store.load_state(self.root)["last_run"])

    def test_successful_run_writes_proposals_and_stamps_last_run(self):
        body = {"results": [{"title": "New stack", "url": "https://x.io",
                             "content": "c"}]}
        pkg = self.root / "danzaboss"
        pkg.mkdir()
        (pkg / "huge.py").write_text(
            "\n".join(f"x = {i}" for i in range(900)), encoding="utf-8")
        out = scout.maybe_scout(self.root, env={"TAVILY_API_KEY": "k"},
                                urlopen=fake_urlopen(body))
        self.assertTrue(out["ran"])
        state = store.load_state(self.root)
        self.assertIsNotNone(state["last_run"])
        sources = {p["source"] for p in state["proposals"]}
        self.assertEqual(sources, {"research", "code_health"})

    def test_run_never_raises_on_corrupt_state(self):
        path = store.state_path(self.root)
        path.parent.mkdir(parents=True)
        path.write_text("not json", encoding="utf-8")
        out = scout.maybe_scout(self.root, env={"TAVILY_API_KEY": "k"})
        self.assertFalse(out["ran"])


if __name__ == "__main__":
    unittest.main()
