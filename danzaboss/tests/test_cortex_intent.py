import unittest
import _bootstrap  # noqa
from danzaboss.cortex.intent import (GENERAL, INTENTS, WorkspaceState, detect,
                                     signal_weights, DEFAULT_WEIGHTS)


class TestIntentDetection(unittest.TestCase):
    def test_keyword_detection(self):
        self.assertEqual(detect("fix the login bug").name, "fix_bug")
        self.assertEqual(detect("implement the new feature").name, "write_code")
        self.assertEqual(detect("security review of auth tokens").name, "security")
        self.assertEqual(detect("optimize the slow dashboard query").name,
                         "performance")

    def test_phrase_scores_double(self):
        # "how does" (phrase, 2) should beat a single keyword hit
        intent = detect("how does the build work")
        self.assertEqual(intent.name, "explain")
        self.assertTrue(any("phrase" in m for m in intent.matched))

    def test_unknown_prompt_falls_back_to_general(self):
        intent = detect("zebra umbrella quixotic")
        self.assertEqual(intent.name, GENERAL)
        self.assertEqual(intent.score, 0.0)

    def test_deterministic(self):
        a = detect("fix the failing test for auth")
        b = detect("fix the failing test for auth")
        self.assertEqual((a.name, a.score, a.matched), (b.name, b.score, b.matched))

    def test_branch_signal_tips_the_scale(self):
        ws = WorkspaceState(branch="fix/login-race")
        self.assertEqual(detect("continue the work", ws).name, "fix_bug")

    def test_tool_mix_signals(self):
        ws = WorkspaceState(recent_tools=["Edit", "Write", "Edit", "Read"])
        self.assertEqual(detect("continue", ws).name, "write_code")
        ws2 = WorkspaceState(recent_commands=["python -m pytest", "run tests now"])
        self.assertEqual(detect("continue", ws2).name, "testing")

    def test_matched_reasons_are_populated(self):
        intent = detect("fix the crash")
        self.assertTrue(intent.matched)
        self.assertTrue(intent.terms)  # prompt tokens captured for anti-relevance


class TestSignalWeights(unittest.TestCase):
    def test_every_intent_has_a_full_weight_vector(self):
        for name in INTENTS + (GENERAL,):
            w = signal_weights(name)
            self.assertEqual(set(w), set(DEFAULT_WEIGHTS), name)

    def test_security_boosts_graph_and_tags(self):
        w = signal_weights("security")
        self.assertGreater(w["graph"], DEFAULT_WEIGHTS["graph"])
        self.assertGreater(w["tags"], DEFAULT_WEIGHTS["tags"])

    def test_unknown_intent_gets_balanced_defaults(self):
        self.assertEqual(signal_weights("nonsense"), DEFAULT_WEIGHTS)


if __name__ == "__main__":
    unittest.main()
