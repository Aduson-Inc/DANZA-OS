"""Tests for verification tiers (C4.5) — cheapest safe verification per change."""
import unittest

import _bootstrap  # noqa

from danzaboss.kernel.tiers import classify_path, recommend_tier


class TestClassifyPath(unittest.TestCase):
    def test_docs_are_tier_zero(self):
        self.assertEqual(classify_path("docs/architecture.md"), 0)
        self.assertEqual(classify_path("README.md"), 0)
        self.assertEqual(classify_path("CLAUDE.md"), 0)

    def test_static_ui_is_tier_one(self):
        self.assertEqual(classify_path("danzaboss/cortex/ui/static/app.css"), 1)
        self.assertEqual(classify_path("danzaboss/cortex/ui/static/index.html"), 1)

    def test_plain_module_is_tier_two(self):
        self.assertEqual(classify_path("danzaboss/planning/decompose.py"), 2)
        self.assertEqual(classify_path("danzaboss/research/squad.py"), 2)

    def test_subsystems_are_tier_three(self):
        self.assertEqual(classify_path("danzaboss/hooks/guards.py"), 3)
        self.assertEqual(classify_path("danzaboss/cortex/retrieve.py"), 3)
        self.assertEqual(classify_path("danzaboss/cli.py"), 3)
        self.assertEqual(classify_path("danzaboss/kernel/profile.py"), 3)

    def test_security_and_state_are_tier_four(self):
        self.assertEqual(classify_path("danzaboss/security/capabilities.py"), 4)
        self.assertEqual(classify_path("danzaboss/kernel/state.py"), 4)

    def test_boot_surface_is_tier_five(self):
        self.assertEqual(classify_path(".claude/agents/tony-d-orchestrator.md"), 5)
        self.assertEqual(classify_path(".claude/rules/constitution.md"), 5)
        self.assertEqual(classify_path(".claude/skills/danza/SKILL.md"), 5)


class TestRecommendTier(unittest.TestCase):
    def test_empty_change_set_is_tier_zero(self):
        self.assertEqual(recommend_tier([]).level, 0)

    def test_mixed_changes_take_the_max(self):
        t = recommend_tier(["docs/notes.md", "danzaboss/hooks/gates.py"])
        self.assertEqual(t.level, 3)

    def test_commit_boundary_forces_full_suite(self):
        t = recommend_tier(["docs/notes.md"], commit_boundary=True)
        self.assertEqual(t.level, 4)

    def test_commit_boundary_does_not_downgrade_boot(self):
        t = recommend_tier([".claude/agents/jonathan-builder.md"],
                           commit_boundary=True)
        self.assertEqual(t.level, 5)

    def test_broad_code_sweep_escalates_to_full(self):
        paths = [f"danzaboss/planning/mod{i}.py" for i in range(7)]
        self.assertEqual(recommend_tier(paths).level, 4)

    def test_broad_docs_sweep_stays_cheap(self):
        paths = [f"docs/page{i}.md" for i in range(10)]
        self.assertEqual(recommend_tier(paths).level, 0)


if __name__ == "__main__":
    unittest.main()
