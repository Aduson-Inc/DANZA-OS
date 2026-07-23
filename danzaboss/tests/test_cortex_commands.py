import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import _bootstrap  # noqa
from danzaboss.cortex import commands
from danzaboss.cortex.events import CaptureLog
from danzaboss.cortex.sqlite_backend import SqliteBackend
from danzaboss.cortex.store import ObservationStore
from danzaboss.kernel.profile import PROFILE_ENV_VAR


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
        # these tests exercise the RUNTIME hook contract (capture everything,
        # gate every session); OS_DEV's lighter policy is tested in test_profile
        self._saved_profile = os.environ.get(PROFILE_ENV_VAR)
        os.environ[PROFILE_ENV_VAR] = "APP_BUILD"

    def tearDown(self):
        if self._saved_profile is None:
            os.environ.pop(PROFILE_ENV_VAR, None)
        else:
            os.environ[PROFILE_ENV_VAR] = self._saved_profile
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

    def test_hook_fails_closed_on_garbage_stdin_in_app_build(self):
        # setUp pins this class to APP_BUILD (runtime law binds): an internal
        # error must refuse rather than silently proceed.
        stdin = io.StringIO("this is not json{{{")
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = commands.main(["hook", "post-tool-use"],
                                 root=self.root, stdin=stdin)
        self.assertEqual(code, 2)
        self.assertIn("refusing by policy", err.getvalue())

    def test_hook_fails_open_on_garbage_stdin_in_os_dev(self):
        # No team-state.json in self.root, so clearing the env override lets
        # the heuristic resolve OS_DEV (Layer 0) -> must never brick itself.
        os.environ.pop(PROFILE_ENV_VAR, None)
        stdin = io.StringIO("this is not json{{{")
        out = io.StringIO()
        with redirect_stdout(out):
            code = commands.main(["hook", "post-tool-use"],
                                 root=self.root, stdin=stdin)
        self.assertEqual(code, 0)

    def test_stop_hook_internal_error_fails_closed_with_block_json(self):
        # Stop has its own CC contract (decision: block, exit 0), already used
        # by the distillation gate itself -> internal errors reuse that shape.
        stdin = io.StringIO("this is not json{{{")
        out = io.StringIO()
        with redirect_stdout(out):
            code = commands.main(["hook", "stop"], root=self.root, stdin=stdin)
        self.assertEqual(code, 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["decision"], "block")
        self.assertIn("refusing by policy", result["reason"])

    def test_stop_hook_internal_error_fails_open_in_os_dev(self):
        os.environ.pop(PROFILE_ENV_VAR, None)
        stdin = io.StringIO("this is not json{{{")
        out = io.StringIO()
        with redirect_stdout(out):
            code = commands.main(["hook", "stop"], root=self.root, stdin=stdin)
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip(), "")

    def test_unknown_event_fails_closed_in_app_build(self):
        stdin = io.StringIO("")
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = commands.main(["hook", "bogus-event"],
                                 root=self.root, stdin=stdin)
        self.assertEqual(code, 2)
        self.assertIn("unknown cortex hook event", err.getvalue())
        self.assertIn("refusing by policy", err.getvalue())

    def test_unknown_event_fails_open_in_os_dev(self):
        os.environ.pop(PROFILE_ENV_VAR, None)
        stdin = io.StringIO("")
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = commands.main(["hook", "bogus-event"],
                                 root=self.root, stdin=stdin)
        self.assertEqual(code, 0)
        self.assertIn("unknown cortex hook event", err.getvalue())


class TestGraphCommands(unittest.TestCase):
    """danza cortex index rebuilds the graph; danza cortex graph queries it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "pkg"))
        open(os.path.join(self.root, "pkg", "__init__.py"), "w").close()
        with open(os.path.join(self.root, "pkg", "core.py"), "w") as fh:
            fh.write("VALUE = 1\n")
        with open(os.path.join(self.root, "pkg", "api.py"), "w") as fh:
            fh.write("from pkg.core import VALUE\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_index_builds_graph_and_prints_stats(self):
        code, out = run(["index"], self.root)
        self.assertEqual(code, 0)
        stats = json.loads(out)
        self.assertGreaterEqual(stats["files"], 3)
        self.assertEqual(stats["imports_resolved"], 1)
        self.assertIn("observations", stats)   # link stage ran (no git is fine)

    def test_graph_impact_after_index(self):
        run(["index"], self.root)
        code, out = run(["graph", "pkg/core.py", "--impact"], self.root)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["mode"], "impact")
        self.assertEqual(data["node"], "file:pkg/core.py")
        self.assertIn({"id": "file:pkg/api.py", "depth": 1}, data["closure"])

    def test_graph_neighbors_default_and_name_lookup(self):
        run(["index"], self.root)
        code, out = run(["graph", "file:pkg/api.py"], self.root)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn(["file:pkg/core.py", "imports"], data["neighbors"]["out"])

    def test_graph_unknown_node_exits_1(self):
        run(["index"], self.root)
        code, out = run(["graph", "no_such_thing_xyz"], self.root)
        self.assertEqual(code, 1)
        self.assertIn("error", json.loads(out))


if __name__ == "__main__":
    unittest.main()
