import tempfile, unittest
import _bootstrap  # noqa
from danzaboss.memory.store import MemoryStore
from danzaboss.context.pipeline import ContextPipeline, compress, isolate


class TestContext(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore(tempfile.mkdtemp())
        self.store.remember("semantic", "code style: 4-space indent, snake_case", ["style"])
        self.store.remember("procedural", "build order: auth before profile", ["order"])
        self.store.remember("semantic", "the logo is teal", ["design"])
        self.pipe = ContextPipeline(self.store)

    def test_compile_targets_driver_profile(self):
        ctx = self.pipe.compile("jonathan-builder", "t1", "implement login form")
        self.assertEqual(ctx.driver, "jonathan-builder")
        self.assertIn("Relevant memory", ctx.sections)
        self.assertIn("Task", ctx.sections)

    def test_budget_is_enforced(self):
        for i in range(100):
            self.store.remember("semantic", "verbose fact %d " % i * 30, ["v"])
        ctx = self.pipe.compile("jonathan-builder", "t1", "build", token_budget=120)
        self.assertLessEqual(ctx.est_tokens, 120 + 40)  # small task overhead allowance

    def test_compress_dedupes(self):
        from danzaboss.memory.store import MemoryRecord
        recs = [MemoryRecord("semantic", "same prefix here aaaaa", ["x"]),
                MemoryRecord("semantic", "same prefix here aaaaa", ["x"])]
        self.assertEqual(len(compress(recs, 1000)), 1)

    def test_isolate_trims_to_budget(self):
        from danzaboss.memory.store import MemoryRecord
        recs = [MemoryRecord("semantic", "x" * 400) for _ in range(10)]  # ~100 tok each
        trimmed = isolate(recs, 150)
        self.assertLessEqual(sum(r.est_tokens() for r in trimmed), 150)

    def test_unknown_driver_still_compiles(self):
        ctx = self.pipe.compile("unknown-agent", "t9", "do something")
        self.assertIn("Task", ctx.sections)


if __name__ == "__main__":
    unittest.main()
