import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout

import _bootstrap  # noqa
from danzaboss.cortex import commands
from danzaboss.cortex.events import CaptureLog, redact
from danzaboss.kernel.profile import PROFILE_ENV_VAR


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


class TestContextReadTelemetry(unittest.TestCase):
    """P4 T11: per-agent context-read telemetry lives in the capture DB."""

    def test_record_and_stats_round_trip(self):
        log = CaptureLog(":memory:")
        log.record_context_read("danza-os", "jonathan-builder", 400, 900)
        log.record_context_read("danza-os", "jonathan-builder", 300, 900)
        log.record_context_read("danza-os", "bonnie-qa", 200, 800)
        stats = log.context_read_stats("danza-os")
        self.assertEqual(stats["jonathan-builder"], {"reads": 2, "tokens": 700})
        self.assertEqual(stats["bonnie-qa"], {"reads": 1, "tokens": 200})

    def test_stats_scoped_by_project(self):
        log = CaptureLog(":memory:")
        log.record_context_read("app-a", "jonathan-builder", 400, 900)
        log.record_context_read("app-b", "jonathan-builder", 100, 900)
        self.assertEqual(log.context_read_stats("app-a")
                         ["jonathan-builder"]["tokens"], 400)

    def test_stats_empty_on_fresh_db(self):
        self.assertEqual(CaptureLog(":memory:").context_read_stats("danza-os"), {})

    def test_four_argument_call_persists_empty_adaptation(self):
        log = CaptureLog(":memory:")
        log.record_context_read("danza-os", "jonathan-builder", 400, 2400)
        row = log.conn.execute(
            "SELECT adaptation FROM context_reads").fetchone()
        self.assertEqual(json.loads(row["adaptation"]), {})

    def test_structured_adaptation_round_trip(self):
        log = CaptureLog(":memory:")
        evidence = {"selected_mode": "expanded", "selected_budget": 4000}
        log.record_context_read(
            "danza-os", "jonathan-builder", 3000, 4000, evidence)
        row = log.conn.execute(
            "SELECT tokens, budget, adaptation FROM context_reads").fetchone()
        self.assertEqual((row["tokens"], row["budget"]), (3000, 4000))
        self.assertEqual(json.loads(row["adaptation"]), evidence)

    def test_old_db_upgrades_in_place(self):
        # a DB created before the context_reads table existed must gain it
        # on open (CREATE TABLE IF NOT EXISTS idiom), not crash on record.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cortex.db")
            conn = sqlite3.connect(path)
            conn.execute("""CREATE TABLE sessions (
                id TEXT PRIMARY KEY, project TEXT NOT NULL,
                environment TEXT DEFAULT '', started_at TEXT NOT NULL,
                ended_at TEXT, prompt_count INTEGER DEFAULT 0,
                observations_written INTEGER DEFAULT 0,
                gate_blocked INTEGER DEFAULT 0, status TEXT DEFAULT 'active')""")
            conn.execute("""CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                ts TEXT NOT NULL, tool TEXT NOT NULL, file_path TEXT DEFAULT '',
                command TEXT DEFAULT '', outcome TEXT DEFAULT '',
                excerpt TEXT DEFAULT '', processed INTEGER DEFAULT 0)""")
            conn.commit()
            conn.close()
            log = CaptureLog(path)
            log.record_context_read("danza-os", "samantha-mapper", 500, 900)
            stats = log.context_read_stats("danza-os")
            self.assertEqual(stats["samantha-mapper"],
                             {"reads": 1, "tokens": 500})

    def test_old_context_reads_schema_migrates_rows_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cortex.db")
            conn = sqlite3.connect(path)
            conn.execute("""CREATE TABLE context_reads (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
                project TEXT NOT NULL, driver TEXT NOT NULL,
                tokens INTEGER NOT NULL, budget INTEGER NOT NULL)""")
            conn.execute(
                "INSERT INTO context_reads (ts, project, driver, tokens, budget) "
                "VALUES ('old', 'danza-os', 'bonnie-qa', 123, 800)")
            conn.commit()
            conn.close()

            first = CaptureLog(path)
            second = CaptureLog(path)
            columns = [r["name"] for r in second.conn.execute(
                "PRAGMA table_info(context_reads)").fetchall()]
            self.assertEqual(columns.count("adaptation"), 1)
            rows = second.conn.execute(
                "SELECT tokens, budget, adaptation FROM context_reads").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]["tokens"], rows[0]["budget"]), (123, 800))
            self.assertEqual(json.loads(rows[0]["adaptation"]), {})
            self.assertEqual(
                second.context_read_stats("danza-os")["bonnie-qa"],
                {"reads": 1, "tokens": 123})
            first.conn.close()
            second.conn.close()


class TestDriverContextCLIRecordsRead(unittest.TestCase):
    """P4 T11: every `cortex context --driver` compile leaves a telemetry
    row — the compile seat is the one place all driver context passes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self._saved = os.environ.get(PROFILE_ENV_VAR)
        os.environ[PROFILE_ENV_VAR] = "APP_BUILD"

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(PROFILE_ENV_VAR, None)
        else:
            os.environ[PROFILE_ENV_VAR] = self._saved
        self.tmp.cleanup()

    def test_driver_context_records_one_read(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = commands.main(["context", "--driver", "jonathan-builder",
                                  "--task", "wire the telemetry"],
                                 root=self.root, stdin=io.StringIO(""))
        self.assertEqual(code, 0)
        project = commands._project(self.root)
        stats = CaptureLog(commands.db_path(self.root)).context_read_stats(project)
        self.assertEqual(stats["jonathan-builder"]["reads"], 1)
        self.assertGreaterEqual(stats["jonathan-builder"]["tokens"], 0)

    def test_cli_json_adaptation_matches_persisted_row(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = commands.main(
                ["context", "--driver", "jonathan-builder",
                 "--task", "wire adaptive telemetry", "--budget", "600",
                 "--json"], root=self.root, stdin=io.StringIO(""))
        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        log = CaptureLog(commands.db_path(self.root))
        row = log.conn.execute(
            "SELECT tokens, budget, adaptation FROM context_reads "
            "ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row["budget"], data["budget"])
        self.assertEqual(row["tokens"], data["used"])
        self.assertEqual(json.loads(row["adaptation"]), data["adaptation"])


if __name__ == "__main__":
    unittest.main()
