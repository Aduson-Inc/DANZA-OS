"""Phase 4.1 Task 11 repository and documentation boundary."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa

from danzaboss.kernel.profile import active_profile
from danzaboss.kernel.state import StateManager
from danzaboss.product.scaffold import scaffold


REPO = Path(__file__).resolve().parents[2]

RETAINED_DOCS = (
    "README.md", "INSTALL.md", "ARCHITECTURE.md", "RUNBOOK.md", "CLAUDE.md",
    "AGENTS.md", "docs/danza-lexicon.md",
    "docs/superpowers/specs/2026-07-11-danza-os-product-completion-design.md",
)

REMOVED_DOCS = (
    "STATUS.md", "ROADMAP.md", "CORTEX.md",
    "docs/cognitive-memory-architecture.md",
    "docs/danza-adaptive-governance-and-research.md",
    "docs/superpowers/plans/2026-07-08-cortex-app-layer-test.md",
    "docs/superpowers/plans/2026-07-11-phase1-installable-product.md",
    "docs/superpowers/plans/2026-07-11-phase2-danza-dashboard.md",
    "docs/superpowers/plans/2026-07-12-phase3-grilling-onboarding.md",
    "docs/superpowers/plans/2026-07-12-phase4-conductor-setup-token-economy.md",
    "docs/superpowers/specs/2026-07-03-cortex-design.md",
    "docs/superpowers/specs/2026-07-05-workstation-onboarding-design.md",
    "docs/superpowers/specs/2026-07-08-cortex-app-layer-test-design.md",
    "docs/superpowers/specs/2026-07-10-tony-cortex-driver-context-wiring-design.md",
)


class OsDevRootIsolation(unittest.TestCase):
    def test_root_has_no_tracked_customer_activation_payload(self):
        for rel in (".claude/agents", ".claude/rules", ".claude/skills",
                    ".claude/settings.json", ".claude/settings.example.json",
                    ".danza/handoff.md", ".danza/feature-list.md",
                    ".danza/onboarding-template.md", ".danza/system-map.md"):
            self.assertFalse((REPO / rel).exists(), rel)

    def test_source_root_resolves_to_os_dev(self):
        profile = active_profile(REPO, env={})
        self.assertEqual(profile.name, "OS_DEV")
        self.assertIn("DANZA-OS", profile.description)
        self.assertNotIn("Fable", profile.description)
        self.assertNotIn("Claude", profile.description)

    def test_temporary_target_activates_packaged_app_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scaffold(root)
            StateManager(str(root / ".danza" / "runtime" /
                             "team-state.json")).init()
            self.assertEqual(active_profile(root, env={}).name, "APP_BUILD")
            prompts = {path.stem for path in
                       (root / ".claude" / "agents").glob("*.md")}
            self.assertEqual(prompts, {
                "tony-d-orchestrator", "jonathan-builder", "samantha-mapper",
                "angela-auditor", "bonnie-qa", "carmella-researcher",
                "hank-designer", "billy-security",
            })


class CleanupAndDocumentation(unittest.TestCase):
    def test_historical_candidate_trees_are_removed(self):
        self.assertFalse((REPO / ".planning").exists())
        self.assertFalse((REPO / ".codex" / "skills" /
                          "danza-forensic-auditor").exists())
        self.assertFalse((REPO / "docs" / "archive").exists())
        for rel in REMOVED_DOCS:
            self.assertFalse((REPO / rel).exists(), rel)

    def test_retained_docs_describe_current_product_without_stale_claims(self):
        combined = "\n".join((REPO / rel).read_text(encoding="utf-8")
                             for rel in RETAINED_DOCS)
        for required in ("OS_DEV", "APP_BUILD", "pyproject.toml", "danza init",
                         "PROJECT", "BUILD", "CORTEX", "Tony-D", "The Boss",
                         "adaptive"):
            self.assertIn(required, combined)
        for stale in ("733 tests", "984 tests", "no package manifest",
                      "no `pyproject.toml`", "Normal/Full Power", "Full Power",
                      "budgets.json", "2 features per turn",
                      "docs/cognitive-memory-architecture.md"):
            self.assertNotIn(stale, combined)

    def test_user_documentation_does_not_present_internal_infrastructure(self):
        for rel in ("README.md", "INSTALL.md", "ARCHITECTURE.md", "RUNBOOK.md",
                    "docs/danza-lexicon.md"):
            text = (REPO / rel).read_text(encoding="utf-8").lower()
            self.assertNotIn("conductor", text, rel)


if __name__ == "__main__":
    unittest.main()
