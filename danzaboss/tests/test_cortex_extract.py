import unittest
import _bootstrap  # noqa
from danzaboss.cortex.extract import draft_observations
from danzaboss.cortex.observation import ObsType


def ev(tool, file_path="", command="", outcome="", excerpt="", eid=1):
    return {"id": eid, "session_id": "s1", "ts": "2026-07-03T00:00:00+00:00",
            "tool": tool, "file_path": file_path, "command": command,
            "outcome": outcome, "excerpt": excerpt}


class TestFloorExtractor(unittest.TestCase):
    def test_git_commit_becomes_impl_detail_draft(self):
        events = [ev("Bash", command='git commit -m "feat: add capture log"')]
        drafts = draft_observations(events, "danza-os")
        self.assertEqual(len(drafts), 1)
        d = drafts[0]
        self.assertEqual(d.type, ObsType.IMPL_DETAIL.value)
        self.assertIn("feat: add capture log", d.title)
        self.assertEqual(d.confidence, 20)
        self.assertEqual(d.confidence_source, "speculation")
        self.assertEqual(d.importance, "low")

    def test_verify_fail_becomes_limitation(self):
        events = [ev("Bash", command='python3 -m danzaboss.cli verify "pytest" .',
                     outcome="FAIL")]
        drafts = draft_observations(events, "danza-os")
        self.assertEqual(drafts[0].type, ObsType.LIMITATION.value)

    def test_verify_pass_becomes_bug_fix(self):
        events = [ev("Bash", command='python3 -m danzaboss.cli verify "pytest" .',
                     outcome="PASS")]
        drafts = draft_observations(events, "danza-os")
        self.assertEqual(drafts[0].type, ObsType.BUG_FIX.value)

    def test_edit_cluster_of_three_becomes_one_draft(self):
        events = [ev("Edit", file_path="danzaboss/cortex/a.py", eid=1),
                  ev("Edit", file_path="danzaboss/cortex/b.py", eid=2),
                  ev("Write", file_path="danzaboss/cortex/c.py", eid=3)]
        drafts = draft_observations(events, "danza-os")
        self.assertEqual(len(drafts), 1)
        self.assertEqual(sorted(drafts[0].files),
                         ["danzaboss/cortex/a.py", "danzaboss/cortex/b.py",
                          "danzaboss/cortex/c.py"])

    def test_two_edits_are_below_cluster_threshold(self):
        events = [ev("Edit", file_path="a.py"), ev("Edit", file_path="b.py", eid=2)]
        self.assertEqual(draft_observations(events, "p"), [])

    def test_reads_and_unknown_tools_ignored(self):
        events = [ev("Read", file_path="x.py"), ev("Glob", command="**/*.py", eid=2)]
        self.assertEqual(draft_observations(events, "p"), [])


if __name__ == "__main__":
    unittest.main()
