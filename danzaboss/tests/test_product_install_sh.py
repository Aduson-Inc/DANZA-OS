"""Phase-1 T8 install.sh hardening: structural assertions + bash syntax
check. The script is never EXECUTED here - it installs from GitHub, and unit
tests must not touch the network. Each assertion maps to a spec section 5
requirement.
"""
import subprocess
import unittest
from pathlib import Path

import _bootstrap  # noqa

SCRIPT = Path(__file__).resolve().parents[2] / "install.sh"


class InstallShStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")
        cls.lines = [l for l in cls.text.splitlines() if l.strip()]

    def test_bash_syntax_valid(self):
        proc = subprocess.run(["bash", "-n", str(SCRIPT)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_strict_mode(self):
        self.assertIn("set -euo pipefail", self.text)

    def test_body_in_main_invoked_on_last_line(self):
        # curl|bash safety: a truncated download must not execute a partial
        # body - everything runs only if main's closing invocation arrived.
        self.assertEqual(self.lines[-1].strip(), 'main "$@"')
        self.assertIn("main() {", self.text)

    def test_https_only(self):
        self.assertNotIn("http://", self.text)

    def test_curl_hardened(self):
        self.assertIn("curl -fsSL", self.text)

    def test_env_knobs_present(self):
        for knob in ("DANZA_VERSION", "DANZA_BIN_DIR", "CONFIGURE"):
            self.assertIn(knob, self.text, f"missing env knob {knob}")

    def test_installs_from_github_via_pipx(self):
        self.assertIn("pipx install", self.text)
        # the git+ spec is composed from REPO_URL - assert both halves so the
        # install source provably stays the D2 GitHub repo
        self.assertIn('REPO_URL="https://github.com/Aduson-Inc/DANZA-OS"',
                      self.text)
        self.assertIn('"git+${REPO_URL}@${version}"', self.text)

    def test_executable_bit(self):
        self.assertTrue(SCRIPT.stat().st_mode & 0o111,
                        "install.sh must be executable")
