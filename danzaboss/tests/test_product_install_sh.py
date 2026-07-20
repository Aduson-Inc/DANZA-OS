"""Cross-platform installer wrapper contract; never touch the network."""
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

    def test_installs_from_pinned_test_branch(self):
        self.assertIn('REPO_URL="https://github.com/Aduson-Inc/DANZA-OS"',
                      self.text)
        self.assertIn('DANZA_BRANCH="codex/production-danzaboss-install-flow"', self.text)
        self.assertNotIn("@main", self.text)
        self.assertIn("install.py", self.text)

    def test_approval_is_before_download(self):
        self.assertLess(self.text.index("Approve installation"),
                        self.text.index("curl -fsSL"))

    def test_exit_trap_is_safe_after_main_returns(self):
        self.assertIn('"${tmp:-}"', self.text)

    def test_executable_bit(self):
        self.assertTrue(SCRIPT.stat().st_mode & 0o111,
                        "install.sh must be executable")
