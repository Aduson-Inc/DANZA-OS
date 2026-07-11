"""Phase-1 T2 scaffold payload: the bundled .claude/.danza templates exist,
are reachable via importlib.resources, and stay byte-identical to the live
repo sources they were copied from.

Parity matters: the constitution/agents evolve in .claude/ (the authoritative
source); this test forces every such edit to consciously re-sync the shipped
payload instead of silently drifting. settings.json is intentionally NOT
parity-checked - the shipped one invokes the installed `danza` console script,
while the OS repo's uses PYTHONPATH module invocation.
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

CLAUDE_PARITY = ([f"agents/{a}.md" for a in AGENTS]
                 + ["rules/constitution.md", "skills/danza/SKILL.md"])

DANZA_PARITY = ["audit-report-template.md", "build-history.md",
                "build-orders.md", "decision-log.md", "feature-list.md",
                "handoff.md", "onboarding-answers.md", "onboarding-misses.md",
                "onboarding-template.md", "patterns.md",
                "self-assessment-log.md", "stack-philosophy.md",
                "system-map.md", "turn-log.md", "checkpoints.json",
                "design-tokens.json", "rankings.json",
                "design/README.md", "onboarding/README.md"]


@unittest.skipUnless((REPO / ".claude").is_dir(),
                     "parity checks need the source repo")
class PayloadParity(unittest.TestCase):
    def test_claude_payload_matches_repo_source(self):
        for rel in CLAUDE_PARITY:
            with self.subTest(rel=rel):
                bundled = (PAYLOAD / "claude" / rel).read_bytes()
                source = (REPO / ".claude" / rel).read_bytes()
                self.assertEqual(bundled, source,
                                 f"payload drifted from .claude/{rel} - re-sync it")

    def test_danza_payload_matches_repo_source(self):
        for rel in DANZA_PARITY:
            with self.subTest(rel=rel):
                bundled = (PAYLOAD / "danza" / rel).read_bytes()
                source = (REPO / ".danza" / rel).read_bytes()
                self.assertEqual(bundled, source,
                                 f"payload drifted from .danza/{rel} - re-sync it")


class PayloadStructure(unittest.TestCase):
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

    def test_managed_block_template_exists(self):
        body = (files("danzaboss.product") / "templates"
                / "claude-md-managed-block.md").read_text(encoding="utf-8")
        self.assertIn("Who's the Boss?", body)
