import os, tempfile, unittest
import _bootstrap  # noqa
from danzaboss.observability.trace import Tracer


class TestTrace(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "trace.jsonl")
        self.tr = Tracer(self.path)

    def test_span_emitted_with_timing(self):
        with self.tr.span("build", "agent", actor="jonathan-builder"):
            pass
        spans = self.tr.load()
        self.assertEqual(len(spans), 1)
        self.assertIsNotNone(spans[0]["duration_ms"])
        self.assertEqual(spans[0]["status"], "ok")

    def test_error_captured_and_reraised(self):
        with self.assertRaises(ValueError):
            with self.tr.span("bad", "tool", actor="x"):
                raise ValueError("boom")
        spans = self.tr.load()
        self.assertEqual(spans[0]["status"], "error")
        self.assertIn("boom", spans[0]["error"])

    def test_nesting_sets_parent(self):
        with self.tr.span("outer", "agent", actor="tony-d-orchestrator"):
            with self.tr.span("inner", "tool", actor="jonathan-builder"):
                pass
        spans = {s["name"]: s for s in self.tr.load()}
        self.assertIsNone(spans["outer"]["parent_id"])
        self.assertEqual(spans["inner"]["parent_id"], spans["outer"]["span_id"])

    def test_summary_counts(self):
        with self.tr.span("a", "agent", actor="jonathan-builder"):
            pass
        try:
            with self.tr.span("b", "agent", actor="bonnie-qa"):
                raise RuntimeError("x")
        except RuntimeError:
            pass
        s = self.tr.summary()
        self.assertEqual(s["span_count"], 2)
        self.assertEqual(s["errors"], 1)

    def test_evidence_for_actor(self):
        with self.tr.span("map", "agent", actor="samantha-mapper"):
            pass
        ev = self.tr.evidence_for("samantha-mapper")
        self.assertEqual(len(ev), 1)  # anti-theatre proof


if __name__ == "__main__":
    unittest.main()
