"""Cross-platform installer contract tests; no network or package install."""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401


ROOT = Path(__file__).resolve().parents[2]


class InstallerContract(unittest.TestCase):
    def test_posix_wrapper_is_strict_and_pins_production_branch(self):
        script = ROOT / "install.sh"
        text = script.read_text(encoding="utf-8")
        self.assertEqual(subprocess.run(["bash", "-n", str(script)]).returncode, 0)
        self.assertIn("set -euo pipefail", text)
        self.assertIn("Production-DANZABOSS", text)
        self.assertNotIn("@main", text)
        self.assertIn("approve", text.lower())

    def test_windows_wrapper_is_present_and_pins_production_branch(self):
        script = ROOT / "install.ps1"
        text = script.read_text(encoding="utf-8")
        self.assertIn("Production-DANZABOSS", text)
        self.assertIn("Read-Host", text)
        self.assertIn("33000", text)


if __name__ == "__main__":
    unittest.main()
