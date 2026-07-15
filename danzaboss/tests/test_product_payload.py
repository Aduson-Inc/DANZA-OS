"""Canonical packaged APP_BUILD payload integrity.

The package resource is the sole product authority.  Layer-0 OS_DEV must not
carry a second live ``.claude``/``.danza`` copy that needs parity maintenance.
"""
import json
import unittest
from importlib.resources import files
from pathlib import Path

import _bootstrap  # noqa

REPO = Path(__file__).resolve().parents[2]
PAYLOAD = files("danzaboss.product") / "templates" / "scaffold"

AGENTS = ["tony-d-orchestrator", "jonathan-builder", "samantha-mapper",
          "angela-auditor", "bonnie-qa", "carmella-researcher",
          "hank-designer", "billy-security"]

class PayloadStructure(unittest.TestCase):
    def test_package_payload_is_the_only_live_product_source(self):
        for rel in ("agents", "rules", "skills", "settings.json",
                    "settings.example.json"):
            self.assertFalse((REPO / ".claude" / rel).exists(), rel)
        for rel in ("handoff.md", "feature-list.md", "decision-log.md",
                    "system-map.md", "onboarding-template.md"):
            self.assertFalse((REPO / ".danza" / rel).exists(), rel)

    def test_exact_active_agent_prompt_set(self):
        actual = sorted(child.name[:-3]
                        for child in (PAYLOAD / "claude" / "agents").iterdir()
                        if child.name.endswith(".md"))
        self.assertEqual(actual, sorted(AGENTS))

    def test_retired_agent_not_shipped(self):
        self.assertFalse(
            (PAYLOAD / "claude" / "agents" / "mona-historian.md").is_file(),
            "mona-historian is RETIRED and must not ship to new repos")

    def test_handoff_is_bootstrap(self):
        text = (PAYLOAD / "danza" / "handoff.md").read_text(encoding="utf-8")
        self.assertIn("No handoff yet.", text)

    def test_no_dotfiles_in_payload(self):
        def walk(node, rel=""):
            for child in node.iterdir():
                path = f"{rel}/{child.name}"
                self.assertFalse(child.name.startswith("."),
                                 f"dotfile in payload: {path}")
                if child.is_dir():
                    walk(child, path)
        walk(PAYLOAD)

    def test_settings_use_installed_console_script(self):
        raw = (PAYLOAD / "claude" / "settings.json").read_text(encoding="utf-8")
        settings = json.loads(raw)
        commands = [h["command"]
                    for group in settings["hooks"].values()
                    for entry in group
                    for h in entry["hooks"]]
        self.assertTrue(commands, "scaffolded settings.json wires no hooks")
        for cmd in commands:
            self.assertTrue(cmd.startswith("danza "),
                            f"scaffolded hook must call the danza console script: {cmd}")
        session_start = [c for c in commands if "session-start" in c]
        self.assertIn("danza hook session-start", session_start,
                      "D8 auto-resume hook missing from SessionStart")
        self.assertIn("danza cortex hook session-start", session_start,
                      "CORTEX injection hook missing from SessionStart")
        self.assertIn("danza cortex hook post-tool-use", commands)
        self.assertIn("danza cortex hook stop", commands)

    def test_tony_prompt_uses_current_atomic_unit_contract(self):
        text = (PAYLOAD / "claude" / "agents" /
                "tony-d-orchestrator.md").read_text(encoding="utf-8")
        for required in ("# Tony-D — The Boss", ".danza/features.json",
                         ".danza/plan.json", "danza unit start",
                         "danza unit verify", "danza unit block",
                         "danza unit conclude", "verified atomic units"):
            self.assertIn(required, text)
        for stale in ("2-feature", "2 features", "next 2 features",
                      "Update `.danza/feature-list.md`"):
            self.assertNotIn(stale, text)

    def test_carmella_prompt_uses_installed_capabilities_only(self):
        text = (PAYLOAD / "claude" / "agents" /
                "carmella-researcher.md").read_text(encoding="utf-8")
        self.assertNotIn("tools/research-pipeline", text)

    def test_managed_block_template_exists(self):
        body = (PAYLOAD / "claude-md-managed-block.md").read_text(
            encoding="utf-8")
        self.assertIn("Who's the Boss?", body)
        self.assertFalse((files("danzaboss.product") / "templates"
                          / "claude-md-managed-block.md").is_file())
