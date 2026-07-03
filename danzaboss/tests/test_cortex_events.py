import unittest
import _bootstrap  # noqa
from danzaboss.cortex.events import CaptureLog, redact


class TestRedaction(unittest.TestCase):
    def test_api_keys_and_passwords_redacted(self):
        cases = [
            "export ANTHROPIC_KEY=sk-ant-abc123def456ghi789jkl",
            "aws AKIA1234567890ABCDEF",
            "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6",
            "password=hunter2secret",
            "postgres://admin:s3cr3t@db.example.com/prod",
        ]
        for text in cases:
            out = redact(text)
            self.assertIn("[REDACTED]", out, f"failed to redact: {text}")
        self.assertNotIn("s3cr3t", redact(cases[4]))

    def test_clean_text_untouched(self):
        clean = "edited danzaboss/cortex/events.py to add CaptureLog"
        self.assertEqual(redact(clean), clean)


class TestCaptureLog(unittest.TestCase):
    def setUp(self):
        self.log = CaptureLog(":memory:")
        self.log.open_session("s1", "danza-os", environment="claude-code")

    def test_open_session_is_idempotent(self):
        self.log.open_session("s1", "danza-os")  # second call must not raise
        sess = self.log.session("s1")
        self.assertEqual(sess["project"], "danza-os")
        self.assertEqual(sess["status"], "active")
        self.assertEqual(sess["gate_blocked"], 0)

    def test_record_event_redacts_and_is_pending(self):
        eid = self.log.record_event("s1", "Bash", command="curl -H 'Bearer sk-ant-abc123def456ghi789'")
        self.assertGreater(eid, 0)
        pending = self.log.pending("s1")
        self.assertEqual(len(pending), 1)
        self.assertIn("[REDACTED]", pending[0]["command"])
        self.assertNotIn("sk-ant", pending[0]["command"])

    def test_mark_processed_clears_pending(self):
        self.log.record_event("s1", "Edit", file_path="a.py")
        self.log.record_event("s1", "Edit", file_path="b.py")
        self.assertEqual(self.log.mark_processed("s1"), 2)
        self.assertEqual(self.log.pending("s1"), [])

    def test_observation_and_gate_counters(self):
        self.log.note_observations("s1", 3)
        self.log.mark_gate_blocked("s1")
        sess = self.log.session("s1")
        self.assertEqual(sess["observations_written"], 3)
        self.assertEqual(sess["gate_blocked"], 1)

    def test_stats_counts(self):
        self.log.record_event("s1", "Read", file_path="x.py")
        s = self.log.stats("danza-os")
        self.assertEqual(s["sessions"], 1)
        self.assertEqual(s["events"], 1)
        self.assertEqual(s["pending_events"], 1)

    def test_unknown_session_returns_none(self):
        self.assertIsNone(self.log.session("nope"))


if __name__ == "__main__":
    unittest.main()
