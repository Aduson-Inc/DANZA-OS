import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

import _bootstrap  # noqa
from danzaboss.cortex import commands
from danzaboss.cortex.events import CaptureLog
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore


def run(argv, root, payload=None):
    stdin = io.StringIO(json.dumps(payload) if payload is not None else "")
    out = io.StringIO()
    with redirect_stdout(out):
        code = commands.main(argv, root=root, stdin=stdin)
    return code, out.getvalue()


class TestCortexCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _store(self):
        return ObservationStore(SqliteBackend(commands.db_path(self.root)))

    def test_session_start_opens_session_and_emits_context_shape(self):
        code, out = run(["hook", "session-start"], self.root,
                        {"session_id": "s1", "source": "startup"})
        self.assertEqual(code, 0)
        log = CaptureLog(commands.db_path(self.root))
        self.assertIsNotNone(log.session("s1"))
        if out.strip():  # empty store may legitimately emit nothing
            parsed = json.loads(out)
            self.assertEqual(parsed["hookSpecificOutput"]["hookEventName"],
                             "SessionStart")

    def test_post_tool_use_records_event(self):
        run(["hook", "session-start"], self.root, {"session_id": "s1"})
        code, out = run(["hook", "post-tool-use"], self.root,
                        {"session_id": "s1", "tool_name": "Edit",
                         "tool_input": {"file_path": "a.py"}})
        self.assertEqual(code, 0)
        log = CaptureLog(commands.db_path(self.root))
        self.assertEqual(len(log.pending("s1")), 1)

    def test_stop_blocks_once_then_floor_extracts(self):
        run(["hook", "session-start"], self.root, {"session_id": "s1"})
        run(["hook", "post-tool-use"], self.root,
            {"session_id": "s1", "tool_name": "Bash",
             "tool_input": {"command": 'git commit -m "feat: x"'}})
        # first stop: gate blocks
        code, out = run(["hook", "stop"], self.root, {"session_id": "s1"})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["decision"], "block")
        # second stop: floor extractor drafts, then allows silently
        code, out = run(["hook", "stop"], self.root, {"session_id": "s1"})
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")
        drafts = self._store().backend.all()
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].confidence, 20)
        log = CaptureLog(commands.db_path(self.root))
        self.assertEqual(log.pending("s1"), [])

    def test_observe_writes_observation_and_satisfies_gate(self):
        run(["hook", "session-start"], self.root, {"session_id": "s1"})
        run(["hook", "post-tool-use"], self.root,
            {"session_id": "s1", "tool_name": "Edit",
             "tool_input": {"file_path": "a.py"}})
        payload = {"title": "Capture log added", "summary": "events.py capture",
                   "type": "impl_detail", "reasoning": "tier-0 write path",
                   "concepts": ["capture"], "files": ["danzaboss/cortex/events.py"]}
        code, out = run(["observe", "--session", "s1"], self.root, payload)
        self.assertEqual(code, 0)
        self.assertEqual(len(self._store().backend.all()), 1)
        # gate now passes on first stop
        code, out = run(["hook", "stop"], self.root, {"session_id": "s1"})
        self.assertEqual(out.strip(), "")

    def test_observe_nothing_meaningful_clears_pending(self):
        run(["hook", "session-start"], self.root, {"session_id": "s1"})
        run(["hook", "post-tool-use"], self.root,
            {"session_id": "s1", "tool_name": "Edit",
             "tool_input": {"file_path": "a.py"}})
        code, _ = run(["observe", "--session", "s1", "--nothing-meaningful"],
                      self.root)
        self.assertEqual(code, 0)
        code, out = run(["hook", "stop"], self.root, {"session_id": "s1"})
        self.assertEqual(out.strip(), "")

    def test_get_and_search_roundtrip(self):
        payload = {"title": "Redis for JWT", "summary": "refresh cache",
                   "type": "decision", "concepts": ["redis", "jwt"]}
        run(["observe"], self.root, payload)
        code, out = run(["search", "redis"], self.root)
        self.assertEqual(code, 0)
        results = json.loads(out)
        self.assertEqual(len(results), 1)
        obs_id = results[0]["id"]
        code, out = run(["get", obs_id], self.root)
        self.assertEqual(json.loads(out)[0]["title"], "Redis for JWT")

    def test_stats_and_age_run(self):
        code, out = run(["stats"], self.root)
        self.assertEqual(code, 0)
        self.assertIn("sessions", json.loads(out))
        code, out = run(["age"], self.root)
        self.assertEqual(code, 0)
        self.assertIn("archived", json.loads(out))

    def test_hook_fails_open_on_garbage_stdin(self):
        stdin = io.StringIO("this is not json{{{")
        out = io.StringIO()
        with redirect_stdout(out):
            code = commands.main(["hook", "post-tool-use"],
                                 root=self.root, stdin=stdin)
        self.assertEqual(code, 0)  # never brick the session


if __name__ == "__main__":
    unittest.main()
