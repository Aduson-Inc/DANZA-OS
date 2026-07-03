"""C1 acceptance (spec section 8): a session captures events, blocks an
un-distilled stop exactly once, and injects context into the NEXT session."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout

import _bootstrap  # noqa
from danzaboss.cortex import commands


def run(argv, root, payload=None):
    stdin = io.StringIO(json.dumps(payload) if payload is not None else "")
    out = io.StringIO()
    with redirect_stdout(out):
        code = commands.main(argv, root=root, stdin=stdin)
    return code, out.getvalue()


class TestC1Acceptance(unittest.TestCase):
    def test_full_lifecycle_capture_gate_distill_inject(self):
        with tempfile.TemporaryDirectory() as root:
            # -- session 1: work happens, agent distills under gate pressure --
            run(["hook", "session-start"], root, {"session_id": "s1"})
            run(["hook", "post-tool-use"], root,
                {"session_id": "s1", "tool_name": "Edit",
                 "tool_input": {"file_path": "danzaboss/cortex/events.py"}})
            _, out = run(["hook", "stop"], root, {"session_id": "s1"})
            self.assertEqual(json.loads(out)["decision"], "block")  # gate fired
            run(["observe", "--session", "s1"], root,
                {"title": "CaptureLog is the tier-0 write path",
                 "summary": "events.py appends redacted tool events per session",
                 "type": "impl_detail", "importance": "high",
                 "reasoning": "hooks must stay thin and fail open",
                 "concepts": ["capture", "events"],
                 "files": ["danzaboss/cortex/events.py"]})
            _, out = run(["hook", "stop"], root, {"session_id": "s1"})
            self.assertEqual(out.strip(), "")                        # gate passes
            # -- session 2: the knowledge is injected --
            _, out = run(["hook", "session-start"], root, {"session_id": "s2"})
            ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("CaptureLog is the tier-0 write path", ctx)
            self.assertIn("[CORTEX]", ctx)
            self.assertIn("hooks must stay thin", ctx)  # reasoning survives


if __name__ == "__main__":
    unittest.main()
