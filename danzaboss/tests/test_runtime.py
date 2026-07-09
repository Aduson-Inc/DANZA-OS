import os, tempfile, unittest
import _bootstrap  # noqa
from danzaboss.runtime.scan import scan_repo, profile_repo
from danzaboss.runtime.verify import run_verification
from danzaboss.runtime.runner import DanzaSession


def make_fake_app(kind="ts"):
    d = tempfile.mkdtemp()
    if kind == "ts":
        os.makedirs(os.path.join(d, "src"))
        open(os.path.join(d, "package.json"), "w").write('{"dependencies":{"next":"14","react":"18"}}')
        open(os.path.join(d, "src", "index.ts"), "w").write("export const x = 1\n")
        open(os.path.join(d, "src", "mixer.tsx"), "w").write("export const M = 2\n")
        open(os.path.join(d, "src", "app.tsx"), "w").write("export const A = 3\n")
    else:
        os.makedirs(os.path.join(d, "api"))
        open(os.path.join(d, "requirements.txt"), "w").write("fastapi\n")
        open(os.path.join(d, "main.py"), "w").write("print('hi')\n")
        open(os.path.join(d, "api", "routes.py"), "w").write("x=1\n")
        open(os.path.join(d, "api", "models.py"), "w").write("y=2\n")
    return d


class TestScan(unittest.TestCase):
    def test_scan_detects_ts_stack(self):
        facts = scan_repo(make_fake_app("ts"))
        self.assertIn("TypeScript", facts.languages)
        self.assertIn("Next.js", facts.frameworks)
        self.assertIn("React", facts.frameworks)

    def test_scan_detects_python_stack(self):
        facts = scan_repo(make_fake_app("py"))
        self.assertIn("Python", facts.languages)
        self.assertIn("FastAPI", facts.frameworks)
        self.assertTrue(any("main.py" in e for e in facts.entry_points))

    def test_profile_repo_produces_appprofile(self):
        prof = profile_repo("noisemaker", make_fake_app("ts"), domain="audio tool")
        self.assertEqual(prof.domain, "audio tool")
        self.assertIn("TypeScript", prof.languages)
        self.assertGreater(prof.confidence, 50)

    def test_scan_ignores_node_modules(self):
        d = make_fake_app("ts")
        nm = os.path.join(d, "node_modules", "junk"); os.makedirs(nm)
        open(os.path.join(nm, "a.js"), "w").write("x")
        facts = scan_repo(d)
        # JS from node_modules should not dominate; TS from src should be present
        self.assertIn("TypeScript", facts.languages)


class TestVerify(unittest.TestCase):
    def test_passing_command(self):
        r = run_verification("exit 0", cwd="/tmp")
        self.assertTrue(r.passed); self.assertEqual(r.exit_code, 0)

    def test_failing_command(self):
        r = run_verification("exit 1", cwd="/tmp")
        self.assertFalse(r.passed); self.assertEqual(r.exit_code, 1)

    def test_captures_output(self):
        r = run_verification("echo hello", cwd="/tmp")
        self.assertIn("hello", r.stdout_tail)

    def test_missing_cwd_returns_failure_not_crash(self):
        # The QA gate must fail closed on a bad target dir, never raise an
        # uncaught exception that bricks the calling hook/session.
        r = run_verification("echo hi", cwd="/nonexistent/dir/xyz")
        self.assertFalse(r.passed)
        self.assertNotEqual(r.exit_code, 0)
        self.assertIn("xyz", r.stderr_tail)   # the OSError is reported, not swallowed


class TestSession(unittest.TestCase):
    def test_session_learn_and_verify(self):
        app = make_fake_app("py")
        s = DanzaSession(project="p", target_dir=app,
                         memory_path=os.path.join(tempfile.mkdtemp(), "m.db"),
                         audit_path=os.path.join(tempfile.mkdtemp(), "a.jsonl"))
        prof = s.learn(domain="CRM")
        self.assertIn("Python", prof.languages)
        self.assertTrue(s.verify("exit 0").passed)
        # memory + dispatcher wire up without error
        self.assertIsNotNone(s.store())
        self.assertIsNotNone(s.dispatcher("claude", set()))


if __name__ == "__main__":
    unittest.main()
