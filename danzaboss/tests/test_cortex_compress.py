import unittest
import _bootstrap  # noqa
from danzaboss.cortex.compress import compress_entry, entry_text
from danzaboss.cortex.inject import est_tokens
from danzaboss.cortex.observation import Observation


def obs(**kw):
    base = dict(title="Redis chosen for JWT refresh",
                summary="Chose Redis to store refresh tokens. "
                        "It prevents the cross-tab race. "
                        "Rollout finished in one sprint.",
                type="decision", project="p",
                reasoning="prevents duplicate refresh across tabs",
                evidence=["auth.ts:42", "commit abc123", "PR #17", "log excerpt"],
                files=["auth.ts", "session.ts"])
    base.update(kw)
    return Observation(**base)


class TestCompress(unittest.TestCase):
    def test_untrimmed_when_it_fits(self):
        o = obs()
        text, compressed = compress_entry(o, 10_000)
        self.assertFalse(compressed)
        self.assertEqual(text, entry_text(o))

    def test_trims_evidence_and_files_first(self):
        o = obs()
        full_cost = est_tokens(entry_text(o))
        text, compressed = compress_entry(o, full_cost - 10)
        self.assertTrue(compressed)
        self.assertIn(o.summary, text)          # summary survives first
        self.assertIn("Why:", text)             # reasoning always survives

    def test_reasoning_is_never_compressed_away(self):
        o = obs()
        text, compressed = compress_entry(o, 1)  # impossible target -> floor
        self.assertTrue(compressed)
        self.assertIn(o.reasoning, text)
        self.assertIn(o.title, text)
        self.assertNotIn("auth.ts:42", text)     # evidence sacrificed

    def test_floor_without_reasoning_keeps_first_sentence(self):
        o = obs(reasoning="")
        text, _ = compress_entry(o, 1)
        self.assertIn("Chose Redis to store refresh tokens.", text)
        self.assertNotIn("Rollout finished", text)

    def test_summary_sentences_trim_from_the_end(self):
        o = obs(evidence=[], files=[])
        full_cost = est_tokens(entry_text(o))
        text, compressed = compress_entry(o, full_cost - 5)
        self.assertTrue(compressed)
        self.assertIn("Chose Redis", text)
        self.assertNotIn("Rollout finished", text)


if __name__ == "__main__":
    unittest.main()
