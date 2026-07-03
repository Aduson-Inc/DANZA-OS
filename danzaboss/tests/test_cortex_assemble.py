import unittest
import _bootstrap  # noqa
from danzaboss.cortex.assemble import (BUDGET_FRACTIONS, CATEGORY_TYPES,
                                       TYPE_CATEGORY, assemble, budget_fractions)
from danzaboss.cortex.observation import Observation
from danzaboss.cortex.retrieve import RetrievedItem


def item(title, typ, final, summary="s " * 30, **kw):
    o = Observation(title=title, summary=summary, type=typ, project="p", **kw)
    return RetrievedItem(observation=o, fused=final, final=final,
                         reasons=[f"fts rank 1"])


class TestBudgetTables(unittest.TestCase):
    def test_fraction_rows_sum_to_one(self):
        for intent, row in BUDGET_FRACTIONS.items():
            self.assertAlmostEqual(sum(row.values()), 1.0, places=6, msg=intent)
            self.assertEqual(set(row), set(CATEGORY_TYPES), intent)

    def test_every_obs_type_maps_to_a_category(self):
        from danzaboss.cortex.observation import ObsType
        for t in ObsType:
            self.assertIn(t.value, TYPE_CATEGORY)

    def test_unknown_intent_gets_even_split(self):
        row = budget_fractions("nonsense")
        self.assertAlmostEqual(sum(row.values()), 1.0, places=6)
        self.assertEqual(len(set(row.values())), 1)


class TestAssemble(unittest.TestCase):
    def test_budget_is_respected(self):
        items = [item(f"Obs {i}", "decision", 1.0 - i * 0.01, summary="word " * 120)
                 for i in range(10)]
        pkg = assemble(items, "fix_bug", budget=400)
        self.assertLessEqual(pkg.used, 400)
        self.assertTrue(pkg.items)

    def test_higher_scored_item_wins_its_category(self):
        strong = item("Strong decision", "decision", 2.0)
        weak = item("Weak decision", "decision", 0.1, summary="word " * 200)
        pkg = assemble([strong, weak], "architecture", budget=200)
        included = [i.observation.title for i in pkg.items]
        self.assertIn("Strong decision", included)

    def test_leftover_budget_redistributes_across_categories(self):
        # only diagnostics items retrieved -> their small fix_bug quota (40%)
        # must not strand the other 60% of the budget
        items = [item(f"Bug {i}", "bug_fix", 1.0 - i * 0.01, summary="word " * 40)
                 for i in range(8)]
        pkg = assemble(items, "fix_bug", budget=600)
        diag_quota = pkg.allocation["diagnostics"]
        self.assertGreater(pkg.used, diag_quota,
                           "pass 2 must spend leftover beyond the category quota")

    def test_oversized_entry_is_compressed_to_fit(self):
        big = item("Huge lesson", "lesson", 1.0, summary="verbose sentence. " * 100,
                   reasoning="the why survives")
        pkg = assemble([big], "learning", budget=300)
        self.assertEqual(len(pkg.items), 1)
        self.assertTrue(pkg.items[0].compressed)
        self.assertIn("the why survives", pkg.items[0].text)

    def test_dropped_items_carry_reasons(self):
        items = [item(f"Obs {i}", "decision", 1.0, summary="word " * 300)
                 for i in range(6)]
        pkg = assemble(items, "general", budget=120)
        self.assertTrue(pkg.dropped)
        self.assertTrue(all(d["reason"] for d in pkg.dropped))

    def test_drop_categories_excludes_and_records(self):
        items = [item("A bug", "bug_fix", 1.0), item("A decision", "decision", 0.9)]
        pkg = assemble(items, "fix_bug", budget=800,
                       drop_categories=frozenset({"diagnostics"}))
        cats = {i.category for i in pkg.items}
        self.assertNotIn("diagnostics", cats)
        self.assertTrue(any("dropped by re-plan" in d["reason"] for d in pkg.dropped))

    def test_every_included_item_carries_reasons(self):
        items = [item("A bug", "bug_fix", 1.0), item("A decision", "decision", 0.9)]
        pkg = assemble(items, "fix_bug", budget=800)
        for i in pkg.items:
            self.assertTrue(i.reasons)
            self.assertTrue(any("category" in r for r in i.reasons))

    def test_render_includes_header_and_bodies(self):
        pkg = assemble([item("A bug", "bug_fix", 1.0)], "fix_bug", budget=800)
        text = pkg.render()
        self.assertIn("[CORTEX package] intent=fix_bug", text)
        self.assertIn("A bug", text)
        self.assertEqual(assemble([], "fix_bug", budget=800).render(), "")


if __name__ == "__main__":
    unittest.main()
