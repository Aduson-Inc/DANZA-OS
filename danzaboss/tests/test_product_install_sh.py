"""Cross-platform installer wrapper contract; never touch the network."""
import os
import subprocess
import tempfile
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

    def test_piped_install_reads_approval_from_terminal(self):
        self.assertIn('read -r -p "Approve installation in this folder? [y/N] " answer </dev/tty',
                      self.text)
        self.assertIn("interactive approval requires a terminal", self.text)

    def test_wrapper_forwards_approval_to_inner_installer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            capture = root / "python-args.txt"
            (fake_bin / "python3").write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1\" == \"-c\" ]]; then exit 0; fi\n"
                "printf '%s\\n' \"$@\" > \"$CAPTURE\"\n",
                encoding="utf-8")
            (fake_bin / "git").write_text("#!/usr/bin/env bash\nexit 0\n",
                                            encoding="utf-8")
            (fake_bin / "curl").write_text(
                "#!/usr/bin/env bash\n"
                "while (($#)); do\n"
                "  if [[ \"$1\" == \"-o\" ]]; then out=\"$2\"; shift 2; else shift; fi\n"
                "done\n"
                ": > \"$out\"\n",
                encoding="utf-8")
            for command in fake_bin.iterdir():
                command.chmod(0o755)
            env = os.environ.copy()
            env.update({"PATH": f"{fake_bin}:/usr/bin:/bin",
                        "CAPTURE": str(capture), "DANZA_APPROVE": "1"})
            proc = subprocess.run(["bash", str(SCRIPT)], cwd=tmp, env=env,
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("--yes", capture.read_text(encoding="utf-8").splitlines())

    def test_exit_trap_is_safe_after_main_returns(self):
        self.assertNotIn("local python tmp", self.text)
        self.assertIn("trap 'rm -f \"$tmp\"' EXIT", self.text)

    def test_executable_bit(self):
        self.assertTrue(SCRIPT.stat().st_mode & 0o111,
                        "install.sh must be executable")
